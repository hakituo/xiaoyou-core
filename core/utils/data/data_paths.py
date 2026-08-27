import re
import shutil
import threading
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import structlog

from config.debug_config import is_debug_enabled
from core.utils.common import get_project_root
from core.utils.data.scope_registry import (
    _DYNAMIC_SCOPES,  # noqa: F401 - 兼容旧诊断脚本的私有导入
    _PERSONA_SLUG_TO_SCOPE,  # noqa: F401 - 兼容旧诊断脚本的私有导入
    _VALID_SCOPES,  # noqa: F401 - 兼容旧诊断脚本的私有导入
    get_registered_role_scopes,
    normalize_data_scope as _normalize_registered_scope,
    resolve_active_persona_scope as _resolve_registered_active_persona_scope,
    resolve_data_scope_from_conversation_id as _resolve_registered_conversation_scope,
    resolve_data_scope_from_source as _resolve_registered_source_scope,
    resolve_memory_user_id as _resolve_registered_memory_user_id,
    resolve_persona_slug_scope,
)

logger = structlog.get_logger(__name__)

_LOCK = threading.Lock()
_INITIALIZED = False

_LEGACY_BASE_NAME = "Aveline_daily_data"
_BASE_NAME = "companion_data"
_USER_DIR = "user_data"
# 特殊 scope 目录名(非角色)
_DUAL_ROLE_DIR = "dual_role"
_LING_SELF_MEAL_PREFIXES = ("自主进食(ling):", "自主进食:ling:")

def _get_role_scopes() -> set:
    """返回唯一注册表中的全部角色 scope。"""
    return get_registered_role_scopes()


def _get_valid_scopes() -> set:
    """获取所有合法 scope（角色 scope + 特殊 scope）"""
    return _get_role_scopes() | {"user", "dual_role"}


def _role_data_dir_name(scope: str) -> str:
    """根据 scope 返回对应的数据目录名(格式: {scope}_data)"""
    return f"{scope}_data"


# 向后兼容常量(动态计算,新增角色时自动生效)
_AVELINE_DIR = _role_data_dir_name("aveline")
_LING_DIR = _role_data_dir_name("ling")
_XIAOLU_DIR = _role_data_dir_name("xiaolu")
_YEYE_DIR = _role_data_dir_name("yeye")


def _move_path_merge(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return
    if src.is_file() and dst.is_file():
        return
    if src.is_file() and dst.is_dir():
        return
    if src.is_dir() and dst.is_file():
        return
    for child in list(src.iterdir()):
        _move_path_merge(child, dst / child.name)
    try:
        src.rmdir()
    except Exception:
        if is_debug_enabled("data_paths"):
            logger.info("删除源目录失败", path=str(src), exc_info=True)


def normalize_data_scope(scope: Optional[str], *, default: str = "user") -> str:
    return _normalize_registered_scope(scope, default=default)


def resolve_data_scope_from_conversation_id(
    conversation_id: Optional[str],
    *,
    default: str = "aveline",
) -> str:
    return _resolve_registered_conversation_scope(conversation_id, default=default)


def _resolve_scope_from_persona_slug(slug: str) -> str:
    """兼容旧私有入口，实际由唯一注册表解析。"""
    return resolve_persona_slug_scope(slug)


def _resolve_scope_from_active_persona() -> str:
    """兼容旧私有入口，实际由唯一注册表解析。"""
    return _resolve_registered_active_persona_scope()


def resolve_memory_user_id(conversation_id: Optional[str]) -> str:
    """将 conversation_id 转换为 scope 级别的 memory user_id

    跨平台共享模式（shared 前缀）：所有平台同一 persona 共享一份记忆池。
    例如：
      shared__persona__aveline   → shared__scope__aveline（QQ/Telegram/Android 互通）
      shared__persona__ling      → shared__scope__ling

    兼容旧格式（保留 user_id 前缀，不再被新代码生成，但旧数据仍可读）：
      private_10001__persona__ling_qq_love   → private_10001__scope__ling
    """
    return _resolve_registered_memory_user_id(conversation_id)


# 跨平台共享 conversation_id 前缀
# 所有平台同一 persona 用同一个 conversation_id，历史和记忆跨平台互通
_SHARED_BASE = "shared"


def build_shared_persona_conversation_id(persona_filename: str) -> str:
    """构建跨平台共享的 conversation_id

    所有平台（QQ/Telegram/websocket/Android）使用同一 persona 时，
    返回相同的 conversation_id：`shared__persona__{slug}`

    - 同一 persona 跨平台共享聊天历史和记忆池
    - 不同 persona 之间隔离（如 Aveline 和 Ling 不混）
    - 旧的 `{session_id}__persona__{slug}` 格式仍能被 resolve_data_scope_from_conversation_id
      正确解析，旧数据可读

    Args:
        persona_filename: persona 配置文件名（如 "aveline.json" 或 "aveline"）

    Returns:
        `shared__persona__{slug}` 格式的 conversation_id；persona_filename 为空返回 `shared`
    """
    raw = str(persona_filename or "").strip()
    if not raw:
        return _SHARED_BASE
    normalized = raw.replace("\\", "/").strip("/")
    stem = normalized.rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    safe = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff]+", "_", stem).strip("_").lower()
    if not safe:
        digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:8]
        safe = f"persona_{digest}"
    return f"{_SHARED_BASE}__persona__{safe}"


def resolve_data_scope_from_source(
    source: Optional[str],
    *,
    default: str = "user",
) -> str:
    return _resolve_registered_source_scope(source, default=default)


def _iter_existing_chat_history_roots(base: Path) -> Iterable[Path]:
    user_chat = (base / _USER_DIR / "chat_history").resolve()
    if user_chat.exists():
        yield user_chat
    # 动态遍历所有角色 scope
    for scope in _get_role_scopes():
        role_chat = (base / _role_data_dir_name(scope) / "chat_history").resolve()
        if role_chat.exists():
            yield role_chat


def _resolve_scope_from_chat_history_path(rel_parts: list[str]) -> str:
    normalized = [str(part or "").strip() for part in rel_parts if str(part or "").strip()]
    joined = "/".join(normalized)
    lower_joined = joined.lower()
    if any("Ling" in part for part in normalized) or "ling" in lower_joined:
        return "ling"
    return "aveline"


def _target_chat_history_parts(rel_parts: list[str]) -> list[str]:
    normalized = [str(part or "").strip() for part in rel_parts if str(part or "").strip()]
    if len(normalized) >= 5:
        return normalized[:3] + normalized[4:]
    return normalized


def _split_daily_event_scope(line: str, *, default_scope: str) -> str:
    try:
        payload = json.loads(line)
    except Exception:
        if is_debug_enabled("data_paths"):
            logger.info("解析daily event JSON失败", exc_info=True)
        return default_scope
    if not isinstance(payload, dict):
        return default_scope
    conversation_id = str(payload.get("conversation_id") or "").strip()
    if conversation_id:
        return resolve_data_scope_from_conversation_id(
            conversation_id, default=default_scope
        )
    source = str(payload.get("source") or "").strip()
    if source:
        return resolve_data_scope_from_source(source, default=default_scope)
    return default_scope


def _migrate_active_care_layout(base: Path) -> None:
    legacy_root = (base / "active_care").resolve()
    if not legacy_root.exists():
        return
    for scope in ("aveline", "ling"):
        src = legacy_root / scope
        if not src.exists():
            continue
        dst = (base / (_AVELINE_DIR if scope == "aveline" else _LING_DIR) / "active_care").resolve()
        _move_path_merge(src, dst)
    try:
        legacy_root.rmdir()
    except Exception:
        if is_debug_enabled("data_paths"):
            logger.info("删除旧active_care目录失败", path=str(legacy_root), exc_info=True)


def _scope_to_chat_history_root(base: Path, scope: str) -> Path:
    """根据 scope 返回对应的 chat_history 根目录(N 角色动态)"""
    valid_scopes = _get_valid_scopes()
    scope = scope if scope in valid_scopes else "aveline"
    if scope == "user":
        return (base / _USER_DIR / "chat_history").resolve()
    if scope == "dual_role":
        # dual_role 没有 chat_history 目录，归到 aveline_data
        return (base / _role_data_dir_name("aveline") / "chat_history").resolve()
    # 所有角色 scope 统一用 {scope}_data 目录
    return (base / _role_data_dir_name(scope) / "chat_history").resolve()


def _migrate_user_chat_history_layout(base: Path) -> None:
    user_chat = (base / _USER_DIR / "chat_history").resolve()
    if not user_chat.exists():
        return
    for file_path in sorted(user_chat.rglob("*.jsonl")):
        try:
            rel_parts = list(file_path.relative_to(user_chat).parts)
        except Exception:
            if is_debug_enabled("data_paths"):
                logger.info("获取聊天记录相对路径失败", path=str(file_path), exc_info=True)
            continue
        scope = _resolve_scope_from_chat_history_path(rel_parts)
        target_root = _scope_to_chat_history_root(base, scope)
        target_rel_parts = _target_chat_history_parts(rel_parts)
        target_path = target_root.joinpath(*target_rel_parts)
        _move_path_merge(file_path, target_path)
    for index_path in sorted(user_chat.rglob("index.json")):
        try:
            index_path.unlink()
        except Exception:
            if is_debug_enabled("data_paths"):
                logger.info("删除index.json失败", path=str(index_path), exc_info=True)


def _migrate_daily_diary_layout(base: Path) -> None:
    user_daily = (base / _USER_DIR / "daily").resolve()
    if not user_daily.exists():
        return
    for file_path in sorted(user_daily.rglob("diary/*.json")):
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            if is_debug_enabled("data_paths"):
                logger.info("解析日记JSON失败", path=str(file_path), exc_info=True)
            continue
        scope = resolve_data_scope_from_source(
            payload.get("source"), default="user"
        )
        if scope not in {"aveline", "ling"}:
            continue
        try:
            rel_parts = list(file_path.relative_to(user_daily).parts)
        except Exception:
            if is_debug_enabled("data_paths"):
                logger.info("获取日记相对路径失败", path=str(file_path), exc_info=True)
            continue
        target_root = (
            (base / _AVELINE_DIR / "daily").resolve()
            if scope == "aveline"
            else (base / _LING_DIR / "daily").resolve()
        )
        target_path = target_root.joinpath(*rel_parts)
        _move_path_merge(file_path, target_path)


def _migrate_daily_event_layout(base: Path) -> None:
    user_daily = (base / _USER_DIR / "daily").resolve()
    if not user_daily.exists():
        return
    for event_file in sorted(user_daily.rglob("events/*.jsonl")):
        try:
            rel_parts = list(event_file.relative_to(user_daily).parts)
        except Exception:
            if is_debug_enabled("data_paths"):
                logger.info("获取事件文件相对路径失败", path=str(event_file), exc_info=True)
            continue
        try:
            lines = event_file.read_text(encoding="utf-8").splitlines()
        except Exception:
            if is_debug_enabled("data_paths"):
                logger.info("读取事件文件失败", path=str(event_file), exc_info=True)
            continue
        buckets = {"aveline": [], "ling": []}
        for line in lines:
            text = str(line or "").strip()
            if not text:
                continue
            scope = _split_daily_event_scope(text, default_scope="aveline")
            if scope in buckets:
                buckets[scope].append(text)
        for scope, items in buckets.items():
            if not items:
                continue
            target_root = (
                (base / _AVELINE_DIR / "daily").resolve()
                if scope == "aveline"
                else (base / _LING_DIR / "daily").resolve()
            )
            target_path = target_root.joinpath(*rel_parts)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                existing = target_path.read_text(encoding="utf-8").splitlines()
            else:
                existing = []
            merged = existing + [x for x in items if x not in existing]
            target_path.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")


def _migrate_misplaced_memory_files(base: Path) -> None:
    """将 aveline_data/memories 中 misplaced 的文件迁移到正确的角色目录

    处理的场景：
    1. peer_ling 文件被错误放在 aveline_data 下（应放在 dual_role 或 ling_data）
    2. private_*__persona__ling_love 文件被错误放在 aveline_data 下（应放在 ling_data）
    3. 裸 "ling" 文件被错误放在 aveline_data 下（旧版 journal_helpers 用裸 source 当 user_id，
       而 resolve_data_scope_from_conversation_id 不识别裸 "ling"，导致写入 aveline_data）
    """
    aveline_memories = (base / _AVELINE_DIR / "memories").resolve()
    ling_memories = (base / _LING_DIR / "memories").resolve()
    dual_role_memories = (base / "dual_role" / "memories").resolve()

    if not aveline_memories.exists():
        return

    # 需要迁移的文件模式
    for src_file in aveline_memories.rglob("*.json"):
        if not src_file.is_file():
            continue

        filename = src_file.name
        # 提取 conversation_id（去掉 _weighted.json 或 _short.json 后缀）
        cid = filename
        for suffix in ["_weighted.json", "_short.json"]:
            if cid.endswith(suffix):
                cid = cid[:-len(suffix)]
                break

        # 判断目标目录
        target_root = None
        if cid.startswith("peer_ling") or cid == "peer_ling":
            # peer_ling 属于 dual_role
            target_root = dual_role_memories
        elif cid.startswith("peer_aveline") or cid == "peer_aveline":
            # peer_aveline 属于 dual_role
            target_root = dual_role_memories
        elif "__persona__ling" in cid or "__scope__ling" in cid:
            # ling 相关的 persona/scope 文件
            target_root = ling_memories
        elif cid in {"ling", "wang_ling", "core_ling"}:
            # 裸角色名文件（旧版 journal_helpers 直接用 source 作为 user_id）
            target_root = ling_memories

        if target_root is None:
            continue
        
        # 计算目标路径（保持相对路径结构）
        try:
            rel_path = src_file.relative_to(aveline_memories)
        except ValueError:
            continue
        
        dst_file = target_root / rel_path
        
        # 执行迁移
        if dst_file.exists():
            # 如果目标已存在，比较文件大小，保留更大的
            src_size = src_file.stat().st_size
            dst_size = dst_file.stat().st_size
            if src_size <= dst_size:
                # 源文件更小或相等，删除源文件
                src_file.unlink()
                if is_debug_enabled("data_paths"):
                    logger.info("删除 misplaced 文件（目标已存在且更大）", src=str(src_file), dst=str(dst_file))
                continue
            else:
                # 源文件更大，删除目标文件后移动
                dst_file.unlink()
        
        # 移动文件
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        src_file.rename(dst_file)
        if is_debug_enabled("data_paths"):
            logger.info("迁移 misplaced 文件", src=str(src_file), dst=str(dst_file))


def _migrate_role_layout(base: Path) -> None:
    _migrate_active_care_layout(base)
    _migrate_user_chat_history_layout(base)
    _migrate_daily_diary_layout(base)
    _migrate_daily_event_layout(base)
    _migrate_misplaced_memory_files(base)
    legacy_background_circle = (base / _USER_DIR / "background_circle").resolve()
    dual_role_background_circle = (base / "dual_role" / "background_circle").resolve()
    _move_path_merge(legacy_background_circle, dual_role_background_circle)


def _migrate_legacy_layout(project_root: Path) -> None:
    legacy_base = (project_root / _LEGACY_BASE_NAME).resolve()
    if not legacy_base.exists():
        return
    base = (project_root / _BASE_NAME).resolve()
    user = base / _USER_DIR
    aveline = base / _AVELINE_DIR
    user.mkdir(parents=True, exist_ok=True)
    aveline.mkdir(parents=True, exist_ok=True)
    mapping = {
        "daily": user / "daily",
        "daily_records": user / "daily_records",
        "schedule": user / "schedule",
        "status": user / "status",
        "monthly": user / "monthly",
        "templates": user / "templates",
        "reminders.json": user / "reminders.json",
        "latest_device_context.json": user / "latest_device_context.json",
        "index.json": user / "index.json",
        "aveline_life": aveline / "aveline_life",
    }
    for item in list(legacy_base.iterdir()):
        target = mapping.get(item.name)
        if target is None:
            target = user / "legacy_misc" / item.name
        _move_path_merge(item, target)
    try:
        legacy_base.rmdir()
    except Exception:
        if is_debug_enabled("data_paths"):
            logger.info("删除旧版数据目录失败", path=str(legacy_base), exc_info=True)


def _migrate_self_meals_from_user_records(base: Path) -> None:
    user_records = (base / _USER_DIR / "daily_records").resolve()
    if not user_records.exists():
        return
    for record_path in user_records.rglob("daily_record.json"):
        try:
            payload = json.loads(record_path.read_text(encoding="utf-8"))
        except Exception:
            if is_debug_enabled("data_paths"):
                logger.info("解析daily_record.json失败", path=str(record_path), exc_info=True)
            continue
        meals = payload.get("meals")
        if not isinstance(meals, list) or not meals:
            continue
        user_meals = []
        aveline_self_meals = []
        ling_self_meals = []
        for meal in meals:
            if not isinstance(meal, dict):
                continue
            content = str(meal.get("content") or "")
            lowered = content.lower()
            if any(lowered.startswith(prefix) for prefix in _LING_SELF_MEAL_PREFIXES):
                ling_self_meals.append(meal)
            elif content.startswith("自主进食:"):
                aveline_self_meals.append(meal)
            elif lowered.startswith("投喂(ling):") or lowered.startswith("投喂(ling):".lower()):
                ling_self_meals.append(meal)
            elif lowered.startswith("投喂:") or lowered.startswith("投喂:".lower()):
                aveline_self_meals.append(meal)
            else:
                user_meals.append(meal)
        if not aveline_self_meals and not ling_self_meals:
            continue
        payload["meals"] = user_meals
        try:
            record_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.warning("写入daily_record.json失败", path=str(record_path), exc_info=True)
            continue
        for meal in aveline_self_meals:
            try:
                y, m, d = record_path.parts[-4], record_path.parts[-3], record_path.parts[-2]
                target_dir = (base / _AVELINE_DIR / "life_records" / y / m / d).resolve()
                target_dir.mkdir(parents=True, exist_ok=True)
                target_file = target_dir / "daily_record.json"
                a_payload = {"date": f"{y}-{int(m):02d}-{int(d):02d}", "meals": []}
                if target_file.exists():
                    try:
                        a_payload = json.loads(target_file.read_text(encoding="utf-8"))
                    except Exception:
                        if is_debug_enabled("data_paths"):
                            logger.info("解析aveline daily_record.json失败，使用默认值", path=str(target_file), exc_info=True)
                        a_payload = {"date": f"{y}-{int(m):02d}-{int(d):02d}", "meals": []}
                a_meals = a_payload.get("meals")
                if not isinstance(a_meals, list):
                    a_meals = []
                    a_payload["meals"] = a_meals
                if meal not in a_meals:
                    a_meals.append(meal)
                target_file.write_text(
                    json.dumps(a_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                logger.warning("写入aveline自主进食记录失败", path=str(target_file), exc_info=True)
                continue
        for meal in ling_self_meals:
            try:
                y, m, d = record_path.parts[-4], record_path.parts[-3], record_path.parts[-2]
                target_dir = (base / _LING_DIR / "life_records" / y / m / d).resolve()
                target_dir.mkdir(parents=True, exist_ok=True)
                target_file = target_dir / "daily_record.json"
                l_payload = {"date": f"{y}-{int(m):02d}-{int(d):02d}", "meals": []}
                if target_file.exists():
                    try:
                        l_payload = json.loads(target_file.read_text(encoding="utf-8"))
                    except Exception:
                        if is_debug_enabled("data_paths"):
                            logger.info("解析ling daily_record.json失败，使用默认值", path=str(target_file), exc_info=True)
                        l_payload = {"date": f"{y}-{int(m):02d}-{int(d):02d}", "meals": []}
                l_meals = l_payload.get("meals")
                if not isinstance(l_meals, list):
                    l_meals = []
                    l_payload["meals"] = l_meals
                if meal not in l_meals:
                    l_meals.append(meal)
                target_file.write_text(
                    json.dumps(l_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                logger.warning("写入ling自主进食记录失败", path=str(target_file), exc_info=True)
                continue


def _is_ling_persona_name(name: str) -> bool:
    text = str(name or "").strip().lower()
    return text in {"Ling", "ling", "wang_ling", "wangling"}


def _migrate_persona_export_layout(base: Path) -> None:
    old_persona_root = (base / _AVELINE_DIR / "persona_data").resolve()
    if not old_persona_root.exists():
        return
    ling_persona_root = (base / _LING_DIR / "persona_data").resolve()
    ling_persona_root.mkdir(parents=True, exist_ok=True)
    for child in list(old_persona_root.iterdir()):
        if not _is_ling_persona_name(child.name):
            continue
        _move_path_merge(child, ling_persona_root / child.name)
    _move_path_merge(ling_persona_root / "Ling", ling_persona_root / "ling")
    _move_path_merge(old_persona_root / "七濑 澪", old_persona_root / "aveline")


def _ensure_initialized() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _LOCK:
        if _INITIALIZED:
            return
        root = get_project_root()
        base = (root / _BASE_NAME).resolve()
        user = (base / _USER_DIR).resolve()
        _migrate_legacy_layout(root)
        user.mkdir(parents=True, exist_ok=True)
        # N 角色通用:为所有已注册角色创建 {role}_data 目录
        role_scopes = _get_role_scopes()
        for scope in role_scopes:
            role_dir = (base / _role_data_dir_name(scope)).resolve()
            role_dir.mkdir(parents=True, exist_ok=True)
            # 生命记录子目录(兼容旧硬编码:aveline_life / ling_life)
            life_dir_name = f"{scope}_life"
            (role_dir / life_dir_name).mkdir(parents=True, exist_ok=True)
            (role_dir / "life_records").mkdir(parents=True, exist_ok=True)
        _migrate_role_layout(base)
        _migrate_self_meals_from_user_records(base)
        _migrate_persona_export_layout(base)
        _INITIALIZED = True


def get_companion_data_dir() -> Path:
    _ensure_initialized()
    return (get_project_root() / _BASE_NAME).resolve()


def get_user_data_dir() -> Path:
    _ensure_initialized()
    return (get_companion_data_dir() / _USER_DIR).resolve()


def get_aveline_data_dir() -> Path:
    _ensure_initialized()
    return (get_companion_data_dir() / _AVELINE_DIR).resolve()


def get_ling_data_dir() -> Path:
    _ensure_initialized()
    return (get_companion_data_dir() / _LING_DIR).resolve()


def get_role_data_dir(scope: Optional[str]) -> Path:
    """N 角色通用:返回 scope 对应的数据目录

    所有角色 scope 统一用 {scope}_data 目录格式。
    特殊 scope: user → user_data, dual_role → dual_role
    """
    normalized = normalize_data_scope(scope, default="user")
    if normalized == "user":
        return get_user_data_dir()
    if normalized == "dual_role":
        return get_dual_role_data_dir()
    # 所有角色 scope 统一用 {scope}_data 目录
    _ensure_initialized()
    return (get_companion_data_dir() / _role_data_dir_name(normalized)).resolve()


def get_xiaolu_data_dir() -> Path:
    _ensure_initialized()
    return (get_companion_data_dir() / _role_data_dir_name("xiaolu")).resolve()


def get_yeye_data_dir() -> Path:
    _ensure_initialized()
    return (get_companion_data_dir() / _role_data_dir_name("yeye")).resolve()


def get_dual_role_data_dir() -> Path:
    _ensure_initialized()
    return (get_companion_data_dir() / _DUAL_ROLE_DIR).resolve()


def get_dual_role_reminder_assignment_path() -> Path:
    """获取双角色提醒分工共享文件路径

    用于跨 persona 协调"今日提醒谁发"，避免 Aveline 和 Ling 重复发同一条提醒。
    每日自动滚动（日期变更时清空重写）。
    """
    _ensure_initialized()
    return (get_dual_role_data_dir() / "reminder_assignment_today.json").resolve()


def get_proactive_assignment_path() -> Path:
    """获取双角色主动关怀时段分工共享文件路径

    用于跨 persona 协调"今日各时段谁主导发主动关怀"，避免 Aveline 和 Ling
    各自独立决策导致重复轰炸用户。每日自动滚动（日期变更时清空重写）。
    """
    _ensure_initialized()
    return (get_dual_role_data_dir() / "proactive_assignment_today.json").resolve()


def get_user_daily_dir() -> Path:
    _ensure_initialized()
    return (get_user_data_dir() / "daily").resolve()


def get_user_daily_records_dir() -> Path:
    _ensure_initialized()
    return (get_user_data_dir() / "daily_records").resolve()


def get_user_chat_history_dir() -> Path:
    _ensure_initialized()
    return (get_user_data_dir() / "chat_history").resolve()


def get_user_weighted_history_dir() -> Path:
    """获取 weighted memory 的 history 目录"""
    _ensure_initialized()
    return (get_user_data_dir() / "history").resolve()


def get_role_chat_history_dir(scope: Optional[str]) -> Path:
    _ensure_initialized()
    return (get_role_data_dir(scope) / "chat_history").resolve()


def get_chat_history_dir_for_conversation(conversation_id: Optional[str]) -> Path:
    _ensure_initialized()
    scope = resolve_data_scope_from_conversation_id(conversation_id, default="aveline")
    return get_role_chat_history_dir(scope)


def get_all_chat_history_dirs() -> list[Path]:
    _ensure_initialized()
    roots = []
    # 动态遍历所有角色 scope + 特殊 scope
    all_scopes = _get_role_scopes() | {"dual_role", "user"}
    for scope in all_scopes:
        path = get_role_chat_history_dir(scope)
        if path not in roots:
            roots.append(path)
    return roots


def get_user_schedule_dir() -> Path:
    _ensure_initialized()
    return (get_user_data_dir() / "schedule").resolve()


def get_user_status_dir() -> Path:
    _ensure_initialized()
    return (get_user_data_dir() / "status").resolve()


def get_user_reminders_file() -> Path:
    _ensure_initialized()
    return (get_user_data_dir() / "reminders.json").resolve()


def get_user_latest_device_context_file() -> Path:
    _ensure_initialized()
    return (get_user_data_dir() / "latest_device_context.json").resolve()


def get_aveline_life_dir() -> Path:
    _ensure_initialized()
    return (get_aveline_data_dir() / "aveline_life").resolve()


def get_aveline_life_records_dir() -> Path:
    _ensure_initialized()
    return (get_aveline_data_dir() / "life_records").resolve()


def get_ling_life_dir() -> Path:
    _ensure_initialized()
    return (get_ling_data_dir() / "ling_life").resolve()


def get_ling_life_records_dir() -> Path:
    _ensure_initialized()
    return (get_ling_data_dir() / "life_records").resolve()


def get_aveline_persona_data_dir() -> Path:
    _ensure_initialized()
    return (get_aveline_data_dir() / "persona_data").resolve()


def get_ling_persona_data_dir() -> Path:
    _ensure_initialized()
    return (get_ling_data_dir() / "persona_data").resolve()


def get_role_profiles_dir(scope: Optional[str]) -> Path:
    """获取角色多版本人设档案目录

    路径: {role}_data/persona_data/profiles/
    存放格式: {Role}_{Target}.json（如 Aveline_Qi.json / Ling_Aveline.json）
    """
    _ensure_initialized()
    normalized = normalize_data_scope(scope, default="aveline")
    if normalized in {"user", "dual_role"}:
        # user / dual_role 不存角色人设，回退到 aveline
        base = get_aveline_persona_data_dir()
    else:
        # 所有角色 scope 统一用 {scope}_data/persona_data
        base = (get_role_data_dir(normalized) / "persona_data").resolve()
    return (base / "profiles").resolve()


def get_role_profile_path(scope: Optional[str], role_name: str, target: str) -> Path:
    """获取角色多版本人设档案文件路径

    Args:
        scope: 角色域（aveline/ling）
        role_name: 角色名（如 Aveline / Ling）
        target: 面向对象（如 Qi / Ling / Aveline / default）

    Returns:
        档案文件路径
    """
    profiles_dir = get_role_profiles_dir(scope)
    safe_role = str(role_name or "").strip() or "Role"
    safe_target = str(target or "default").strip() or "default"
    return (profiles_dir / f"{safe_role}_{safe_target}.json").resolve()


def get_user_person_profile_path() -> Path:
    """获取用户自身档案路径（Master的基本信息）

    路径: user_data/person_profile.json
    """
    _ensure_initialized()
    return (get_user_data_dir() / "person_profile.json").resolve()


def get_user_people_profiles_dir() -> Path:
    """获取用户人际关系档案目录

    路径: user_data/people_profiles/
    存放格式: {person_id}.json（如 wang_ling.json）
    """
    _ensure_initialized()
    return (get_user_data_dir() / "people_profiles").resolve()


def get_user_people_profile_path(person_id: str) -> Path:
    """获取用户人际关系中某个角色的档案路径

    路径: user_data/people_profiles/{person_id}.json
    """
    safe_id = str(person_id or "").strip() or "unknown"
    return (get_user_people_profiles_dir() / f"{safe_id}.json").resolve()


def get_role_daily_dir(scope: Optional[str]) -> Path:
    _ensure_initialized()
    return (get_role_data_dir(scope) / "daily").resolve()


def get_daily_dir_for_conversation(conversation_id: Optional[str]) -> Path:
    _ensure_initialized()
    scope = resolve_data_scope_from_conversation_id(conversation_id, default="aveline")
    return get_role_daily_dir(scope)


def get_active_care_dir(scope: Optional[str]) -> Path:
    _ensure_initialized()
    normalized = normalize_data_scope(scope, default="aveline")
    return (get_role_data_dir(normalized) / "active_care").resolve()


def get_role_memories_dir(scope: Optional[str]) -> Path:
    _ensure_initialized()
    normalized = normalize_data_scope(scope, default="aveline")
    return (get_role_data_dir(normalized) / "memories").resolve()


def get_memories_dir_for_conversation(conversation_id: Optional[str]) -> Path:
    _ensure_initialized()
    scope = resolve_data_scope_from_conversation_id(conversation_id, default="aveline")
    return get_role_memories_dir(scope)


def get_sessions_file_for_scope(scope: Optional[str]) -> Path:
    _ensure_initialized()
    normalized = normalize_data_scope(scope, default="aveline")
    return (get_role_memories_dir(normalized) / "sessions.json").resolve()


def get_background_circle_dir() -> Path:
    _ensure_initialized()
    return (get_dual_role_data_dir() / "background_circle").resolve()


# ── Study Daily 辅助函数 ────────────────────────────────────

def get_study_root_dir() -> Path:
    """返回学习根目录 D:\\AI\\Study（从 settings.study.study_root 读取）"""
    try:
        from config.integrated_config import get_settings
        settings = get_settings()
        study_root = str(getattr(settings, "study", None).study_root or "").strip()
        if study_root:
            return Path(study_root).expanduser().resolve()
    except Exception:
        pass
    # 回退到默认路径
    return Path("D:/AI/Study").resolve()


def get_study_daily_dir() -> Path:
    """返回 D:\\AI\\Study\\Daily 路径（从 settings.study.study_root 读取）"""
    return (get_study_root_dir() / "Daily").resolve()


def get_study_daily_date_dir(date: "datetime") -> Path:
    """返回 D:\\AI\\Study\\Daily/YYYY/MM/DD/ 子目录路径"""
    base = get_study_daily_dir()
    return (base / date.strftime("%Y") / date.strftime("%m") / date.strftime("%d")).resolve()
