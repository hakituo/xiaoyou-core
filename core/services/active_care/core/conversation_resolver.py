"""
会话 ID 解析模块

从 ActiveCareContext 中拆出的会话 ID 解析逻辑，包括：
- 候选会话 ID 的收集与去重
- 主会话 ID 的解析与缓存
- 人设 token 的提取与匹配
"""

import time
import asyncio
import json
from datetime import timedelta
from typing import Any, Dict, List, Tuple

from core.utils.conversation_labels import is_primary_user_conversation_id
from core.utils.data_paths import get_user_chat_history_dir
from core.utils.logger import get_logger
from core.utils.timestamp_utils import safe_timestamp
from core.utils.time_utils import get_current_time
from core.services.active_care.shared.constants import (
    normalize_persona_token,
    extract_persona_token,
)

logger = get_logger("ACTIVE_CARE_CONTEXT")

# App 端（手机 App via WebSocket）投递开关。
# 当前 App 端尚未就绪，默认关闭：active care 主动消息只走 QQ（master 私聊 / QQ 官方）。
# 待 App 完成对接后，将此处改为 True，并在 _find_online_primary_for_persona 中
# 移除对 APP_CLIENT_UIDS 的排除，即可让主动消息也能投递到手机 App。
APP_DELIVERY_ENABLED: bool = False
APP_CLIENT_UIDS: Tuple[str, ...] = ("mobile_user", "app_user", "android_user")


# ---------------------------------------------------------------------------
# 模块级缓存（供 resolve_primary_conversation_id / get_candidate_conversation_ids 使用）
# ---------------------------------------------------------------------------
_primary_cid_cache_dict: Dict[str, Dict[str, Any]] = {}
_primary_cid_cache_ttl: float = 30.0

_candidate_cids_cache: List[str] = []
_candidate_cids_cache_ts: float = 0.0
_candidate_cids_cache_ttl: float = 30.0


def invalidate_primary_cid_cache() -> None:
    """清除主会话 ID 缓存"""
    _primary_cid_cache_dict.clear()


def invalidate_candidate_cids_cache() -> None:
    """清除候选会话 ID 缓存时间戳，强制下次重新计算"""
    global _candidate_cids_cache_ts
    _candidate_cids_cache_ts = 0.0


def _is_cid_online(cid: str) -> bool:
    """判断某个会话 ID 当前是否有活跃的 WebSocket 连接"""
    try:
        from core.interfaces.websocket.websocket_manager import get_websocket_manager

        mgr = get_websocket_manager()
        if mgr is None:
            return False
        return bool(mgr.is_user_online(cid))
    except Exception:
        return False


def _find_online_primary_for_persona(
    candidates: List[str], persona_cid: str, current_persona_token: str
) -> str:
    """
    在候选列表中查找与给定 persona 抽象会话属于同一 persona、
    且当前有活跃 WebSocket 连接的主用户私聊真实 user_id。
    """
    try:
        target_token = extract_persona_token_from_conversation_id(persona_cid)
    except Exception:
        target_token = ""
    for cid in candidates:
        if cid == persona_cid:
            continue
        if not is_primary_user_conversation_id(cid):
            continue
        # App 端尚未激活时，跳过 App 类 uid，避免主动消息误投到手机 App
        if not APP_DELIVERY_ENABLED and cid.lower() in APP_CLIENT_UIDS:
            continue
        if target_token:
            cand_token = extract_persona_token_from_conversation_id(cid)
            if cand_token and cand_token != target_token:
                continue
        if _is_cid_online(cid):
            return cid
    return ""


# ---------------------------------------------------------------------------
# 会话 ID 候选判定
# ---------------------------------------------------------------------------

def is_active_care_candidate_conversation_id(conversation_id: str) -> bool:
    """判断 conversation_id 是否是主动关怀的候选会话"""
    normalized = str(conversation_id or "").strip()
    if not normalized:
        return False
    if is_primary_user_conversation_id(normalized):
        return True
    lowered = normalized.lower()
    if "__persona__" in lowered and "__circle__" not in lowered and "__bg__" not in lowered:
        base = lowered.split("__persona__", 1)[0].strip("_")
        if base in {"default", "default_user"}:
            return True
        return is_primary_user_conversation_id(base)
    return False


def dedupe_conversation_ids(candidates: List[str]) -> List[str]:
    """对候选会话 ID 去重，并过滤掉不符合主动关怀候选条件的 ID"""
    seen = set()
    result = []
    for cid in candidates:
        normalized = str(cid or "").strip()
        if not normalized or normalized in seen:
            continue
        if not is_active_care_candidate_conversation_id(normalized):
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


# ---------------------------------------------------------------------------
# 从各数据源收集会话 ID
# ---------------------------------------------------------------------------

async def get_active_conversation_ids_from_ws() -> List[str]:
    """从 WebSocket 连接中获取当前活跃的会话 ID"""
    try:
        from core.interfaces.websocket.websocket_manager import (
            get_websocket_manager,
        )

        ws_manager = get_websocket_manager()
        if not ws_manager or not hasattr(ws_manager, "connections"):
            return []

        ids = []
        for conn in list(ws_manager.connections.values()):
            uid = str(getattr(conn, "user_id", "") or "").strip()
            if not uid or uid.startswith("group_"):
                continue
            ids.append(uid)
        return ids
    except Exception:
        return []


async def get_recent_conversation_ids_from_session_manager() -> List[str]:
    """从会话管理器获取最近活跃的会话 ID"""
    try:
        from core.managers.session_manager import get_session_manager

        sessions = get_session_manager().get_sessions()
        if not isinstance(sessions, list):
            return []
        ids: List[str] = []
        for item in sessions[:16]:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("id") or "").strip()
            if not sid:
                continue
            if sid not in {"default", "default_user"} and (
                not is_primary_user_conversation_id(sid)
            ):
                continue
            ids.append(sid)
        return ids
    except Exception:
        return []


async def get_recent_conversation_ids_from_chat_history() -> List[str]:
    """从聊天历史文件中获取最近 3 天内的会话 ID"""
    try:
        chat_dir = get_user_chat_history_dir()
        if not chat_dir or not chat_dir.exists():
            return []

        now = get_current_time()
        ids_with_ts: List[Tuple[str, float]] = []

        for days_ago in range(3):
            check_date = now - timedelta(days=days_ago)
            day_dir = chat_dir / check_date.strftime("%Y") / check_date.strftime("%m") / check_date.strftime("%d")
            if not day_dir.exists():
                continue

            index_file = day_dir / "index.json"
            if index_file.exists():
                try:
                    content = await asyncio.to_thread(index_file.read_text, encoding="utf-8")
                    index_data = json.loads(content)
                    for item in (index_data.get("files") or []):
                        cid = str(item.get("conversation_id") or "").strip()
                        if cid and cid not in ("default", "default_user"):
                            if not is_primary_user_conversation_id(cid):
                                continue
                            rel_path = str(item.get("relative_path") or "")
                            file_path = chat_dir / rel_path
                            if file_path.exists():
                                file_ts = file_path.stat().st_mtime
                                ids_with_ts.append((cid, file_ts))
                except Exception:
                    pass

        ids_with_ts.sort(key=lambda x: x[1], reverse=True)
        seen = set()
        result = []
        for cid, _ in ids_with_ts:
            if cid not in seen:
                seen.add(cid)
                result.append(cid)
        return result[:8]
    except Exception as e:
        logger.debug(f"Failed to get recent conversation IDs from chat history: {e}")
        return []


# ---------------------------------------------------------------------------
# 人设 token 相关
# ---------------------------------------------------------------------------

def normalize_persona_token_local(text: str) -> str:
    """将人设文件名标准化为 token（委托给 constants.normalize_persona_token）"""
    return normalize_persona_token(text)


def extract_persona_token_from_conversation_id(conversation_id: str) -> str:
    """从 conversation_id 中提取人设 token 并标准化"""
    token = extract_persona_token(conversation_id)
    return normalize_persona_token(token) if token else ""


def extract_persona_token_from_persona_filename(persona_filename: str) -> str:
    """从 persona_filename 提取 persona token（如 'qq/Aveline_QQ_Master.json' -> 'aveline'）"""
    return normalize_persona_token(persona_filename)


def get_current_persona_token() -> str:
    """获取当前激活的人设 token"""
    try:
        from core.character.managers.persona_manager import get_persona_manager

        current_filename = str(get_persona_manager().get_current_filename() or "").strip()
        return normalize_persona_token(current_filename)
    except Exception:
        return ""


def is_candidate_matching_current_persona(conversation_id: str, persona_token: str) -> bool:
    """判断候选会话 ID 是否匹配当前人设 token"""
    if not persona_token:
        return True

    cid = str(conversation_id or "").strip()
    lowered = cid.lower()
    cid_token = extract_persona_token_from_conversation_id(cid)

    if cid_token:
        return cid_token == persona_token or persona_token in cid_token

    if lowered in {"default", "default_user"}:
        return False

    return is_primary_user_conversation_id(cid)


# ---------------------------------------------------------------------------
# 候选会话 ID 收集（带缓存）
# ---------------------------------------------------------------------------

async def get_candidate_conversation_ids(
    storage: Any,
    persona_filename: str = "",
) -> List[str]:
    """
    收集所有候选会话 ID（带模块级缓存）

    Args:
        storage: ActiveCareStorage 实例，用于访问 _recent_user_message_cache
        persona_filename: 人设文件名，用于按 persona 过滤
    """
    global _candidate_cids_cache, _candidate_cids_cache_ts

    now = time.time()
    if _candidate_cids_cache and (now - _candidate_cids_cache_ts) < _candidate_cids_cache_ttl:
        return _candidate_cids_cache

    candidates = ["default", "default_user"]

    # 从 storage 的最近用户消息缓存中获取会话 ID
    recent_msg_cache = getattr(storage, "_recent_user_message_cache", {})
    if isinstance(recent_msg_cache, dict):
        candidates.extend(list(recent_msg_cache.keys()))

    candidates.extend(await get_active_conversation_ids_from_ws())
    candidates.extend(await get_recent_conversation_ids_from_session_manager())
    candidates.extend(await get_recent_conversation_ids_from_chat_history())
    result = dedupe_conversation_ids(candidates)

    # 按 persona 过滤（支持 dual QQ 模式）
    persona_token = ""
    if persona_filename:
        persona_token = extract_persona_token_from_persona_filename(persona_filename)
    else:
        persona_token = get_current_persona_token()
    if persona_token:
        matched = [
            cid for cid in result
            if is_candidate_matching_current_persona(cid, persona_token)
        ]
        if matched:
            result = matched

    _candidate_cids_cache = result
    _candidate_cids_cache_ts = now
    return result


# ---------------------------------------------------------------------------
# 主会话 ID 解析（带缓存）
# ---------------------------------------------------------------------------

async def resolve_primary_conversation_id(
    storage: Any,
    persona_filename: str = "",
) -> str:
    """
    解析主会话 ID（带模块级缓存）

    Args:
        storage: ActiveCareStorage 实例，用于访问 _recent_user_message_cache
        persona_filename: 人设文件名
    """
    now = time.time()
    cache_key = f"pf:{persona_filename}" if persona_filename else "default"
    cached_entry = _primary_cid_cache_dict.get(cache_key)
    if cached_entry and (now - cached_entry.get("ts", 0)) < _primary_cid_cache_ttl:
        return cached_entry.get("cid", "default")

    result = await _resolve_primary_conversation_id_uncached(storage, persona_filename=persona_filename)

    _primary_cid_cache_dict[cache_key] = {"cid": result, "ts": now}
    return result


async def _resolve_primary_conversation_id_uncached(
    storage: Any,
    persona_filename: str = "",
) -> str:
    """
    解析主会话 ID（无缓存，实际逻辑）

    Args:
        storage: ActiveCareStorage 实例
        persona_filename: 人设文件名
    """
    # 需要延迟导入，避免循环依赖
    from core.services.active_care.core.context import ActiveCareContext

    candidates = await get_candidate_conversation_ids(storage)
    if not candidates:
        return "default"

    # 如果传入了 persona_filename，用它来过滤；否则使用全局 persona token
    if persona_filename:
        current_persona_token = extract_persona_token_from_persona_filename(persona_filename)
    else:
        current_persona_token = get_current_persona_token()
    if current_persona_token:
        matched_candidates = [
            cid
            for cid in candidates
            if is_candidate_matching_current_persona(cid, current_persona_token)
        ]
        if matched_candidates:
            logger.debug(
                "Active Care primary cid filtering by current persona token=%s: %d -> %d",
                current_persona_token,
                len(candidates),
                len(matched_candidates),
            )
            candidates = matched_candidates

    best_id = ""
    best_ts = -1.0

    # 从 storage 的最近用户消息缓存中查找最新时间戳
    recent_msg_cache = getattr(storage, "_recent_user_message_cache", {})
    for cid in candidates:
        cached = recent_msg_cache.get(cid)
        if not isinstance(cached, dict):
            continue
        ts = safe_timestamp(cached.get("timestamp"))
        if ts >= best_ts:
            best_ts = ts
            best_id = cid
    if best_id:
        # 若选中的是 persona 抽象会话（如 shared__persona__xxx），但当前没有
        # 对应的活跃 WebSocket 连接（该 cid 下无人注册），则回退到同一 persona
        # 下、当前有活跃连接且属于主用户私聊的真实 user_id（如 private_xxx），
        # 否则主动消息会被广播到一个无人注册的连接而永远进离线队列、收不到。
        if "__persona__" in best_id and not _is_cid_online(best_id):
            alt = _find_online_primary_for_persona(
                candidates, best_id, current_persona_token
            )
            if alt:
                logger.info(
                    "Active Care target %s has no live connection, fallback to online primary %s",
                    best_id,
                    alt,
                )
                return alt
        return best_id

    # 回退：从历史记录中查找
    for cid in candidates:
        try:
            # 通过 ActiveCareContext 的方法获取历史记录
            ctx = ActiveCareContext(storage)
            history = await asyncio.to_thread(
                ctx._get_history_for_conversation, cid, 1
            )
        except Exception:
            history = []
        if not history:
            continue
        ts = safe_timestamp(history[-1].get("timestamp"))
        if ts >= best_ts:
            best_ts = ts
            best_id = cid
    if best_id:
        return best_id

    # 最终回退：返回第一个非默认会话 ID
    for cid in candidates:
        if cid not in {"default", "default_user"}:
            return cid
    return "default"
