"""Active Care QQ 连接解析器。

把 NapCat、官方机器人、多 QQ 配置和 WebSocket 兜底扫描集中在这里，
避免执行器直接依赖所有客户端接入细节。
"""

import hashlib
import json
import os
import time
from typing import Dict, List, Set, Tuple

from config.debug_config import is_debug_enabled
from core.utils.config_accessor import get_config
from core.utils.logger import get_module_logger

logger = get_module_logger("ACTIVE_CARE_EXECUTOR", "active_care_schedule.log")

# 常驻角色白名单：即使没有探测到真实客户端连接，也允许 Active Care / peer chat 运行。
# 其余角色（如 rushuang / yeye）必须有真实客户端接入才会被视为可投递连接，
# 否则后台会在前端根本没打开的情况下自说自话地发消息。
#
# 权威源已收敛到 character_runtime.yaml 的 autonomous_roles（core/character/runtime_roles.py）：
# 那里同时被 CharacterDaily / ActivityInstance / 睡眠问候 / Active Care 消费，
# 新增角色只改配置即可，不必再回来加常量。ALWAYS_ON_ROLE_IDS 只作为配置不可用时的回退值保留。
_FALLBACK_ALWAYS_ON_ROLE_IDS = frozenset({"aveline", "ling", "ye"})
# 兼容既有导入方（历史常量名）。
ALWAYS_ON_ROLE_IDS = _FALLBACK_ALWAYS_ON_ROLE_IDS


def always_on_role_ids() -> Set[str]:
    """常驻角色集合：优先读配置，读不到才用回退值。"""
    try:
        from core.character.runtime_roles import get_autonomous_role_ids

        configured = get_autonomous_role_ids()
        if configured:
            return set(configured)
    except Exception:  # noqa: BLE001 - 配置异常不能阻断主动消息主链路
        pass
    return set(_FALLBACK_ALWAYS_ON_ROLE_IDS)

# multi_qq_config.json 中 persona_filename → role_id 的兜底映射，
# 委托给 personas.find_persona_by_filename_hint（权威注册表），
# 用于配置里缺失 role_id 时仍能正确判定是否属于常驻白名单。


def _infer_role_id(role_id: str, persona_filename: str) -> str:
    """尽力推断 role_id，避免因配置缺字段而误判白名单。"""
    rid = str(role_id or "").strip().lower()
    if rid:
        return rid
    from core.services.dual_role.personas import find_persona_by_filename_hint

    matched = find_persona_by_filename_hint(persona_filename)
    return matched.role_id if matched else ""


def is_always_on_role(role_id: str, persona_filename: str = "") -> bool:
    """判断角色是否属于无需真实连接即可后台运行的常驻白名单。"""
    return _infer_role_id(role_id, persona_filename) in always_on_role_ids()


def has_live_client_connection(role_id: str) -> bool:
    """检查指定角色当前是否有真实存活的客户端接入。

    仅查询 napcat / official 两个注册表，因为它们会校验 transport 是否存活；
    静态配置不能作为「客户端已连上」的证据。
    """
    rid = str(role_id or "").strip().lower()
    if not rid:
        return False

    try:
        from clients.bots.qq.main import QQAdapter

        for inst in QQAdapter.get_active_instances() or []:
            if str(inst.get("role_id") or "").strip().lower() == rid:
                return True
    except ImportError:
        pass
    except Exception:
        if is_debug_enabled("active_care_executor"):
            logger.info("检查 napcat 实时连接失败", exc_info=True)

    try:
        from clients.bots.qq_official.adapter import QQOfficialAdapter

        for inst in QQOfficialAdapter.get_active_instances() or []:
            if str(inst.get("role_id") or "").strip().lower() == rid:
                return True
    except ImportError:
        pass
    except Exception:
        if is_debug_enabled("active_care_executor"):
            logger.info("检查 official 实时连接失败", exc_info=True)

    return False


def can_send_proactive_message(role_id: str, persona_filename: str = "") -> bool:
    """判断角色此刻是否允许后台主动发消息。

    常驻角色（Ling / Aveline）始终允许；其余角色必须有真实客户端接入，
    避免前端没打开时后台仍在自动推送。
    """
    if is_always_on_role(role_id, persona_filename):
        return True
    return has_live_client_connection(role_id)


# ==================== 角色真实在线判定（peer chat 门禁）====================

# 新版 QQ adapter 上报的 client_id 形如 qq_{role_id}_{session_id}
# （见 clients/bots/qq/session/session.py 的 _client_id）
_QQ_CLIENT_ID_PREFIX = "qq_"

# 心跳超时兜底：与 WebSocketManager 默认 heartbeat_timeout 对齐
_WS_ALIVE_TIMEOUT_FALLBACK = 60.0


def _known_role_ids() -> Set[str]:
    """所有已登记角色的 role_id（人设注册表 + 常驻白名单 + 多QQ配置）。"""
    role_ids: Set[str] = set(always_on_role_ids())
    try:
        from core.services.dual_role.personas import get_all_role_ids

        role_ids.update(str(rid).strip().lower() for rid in get_all_role_ids() if rid)
    except Exception:
        pass
    try:
        from config.settings_adapters import get_multi_qq_raw_dict

        role_ids.update(
            str(rid).strip().lower() for rid in (get_multi_qq_raw_dict() or {})
        )
    except Exception:
        pass
    role_ids.discard("")
    return role_ids


def _iter_live_qq_client_ids() -> List[str]:
    """遍历当前存活的 QQ WebSocket 连接，返回其 client_id 列表。"""
    client_ids: List[str] = []
    try:
        from core.interfaces.websocket.websocket_manager import get_websocket_manager

        ws_manager = get_websocket_manager()
        if not ws_manager or not hasattr(ws_manager, "connections"):
            return []
        timeout = float(
            getattr(ws_manager, "heartbeat_timeout", 0) or _WS_ALIVE_TIMEOUT_FALLBACK
        )
        for conn in list(ws_manager.connections.values()):
            websocket = getattr(conn, "websocket", None)
            platform = str(getattr(conn, "platform", "") or "").strip().lower()
            client_id = str(
                getattr(conn, "client_id", "")
                or getattr(websocket, "client_id", "")
                or ""
            ).strip().lower()
            if not client_id.startswith(_QQ_CLIENT_ID_PREFIX) and "qq" not in platform:
                continue
            try:
                # 心跳超时的僵尸连接不算在线
                if not conn.is_alive(timeout):
                    continue
            except Exception:
                # 连接对象缺少心跳字段（如测试桩）时，仍在注册表里即视为存活
                pass
            if client_id:
                client_ids.append(client_id)
    except Exception:
        if is_debug_enabled("active_care_executor"):
            logger.info("扫描 WebSocket 实时连接失败", exc_info=True)
    return client_ids


def get_live_qq_role_ids() -> Set[str]:
    """当前有真实 WebSocket 接入的 QQ 角色 role_id 集合。

    只认带角色前缀的 client_id（qq_{role_id}_{session_id}）。旧客户端不上报
    role_id 时无法区分角色，这类连接不会出现在结果里。
    """
    known = _known_role_ids()
    live: Set[str] = set()
    for client_id in _iter_live_qq_client_ids():
        token = client_id[len(_QQ_CLIENT_ID_PREFIX):]
        role_id = token.split("_", 1)[0].strip()
        if role_id in known:
            live.add(role_id)
    return live


def has_real_role_connection(role_id: str) -> bool:
    """角色此刻是否有真实接入（adapter 注册表或带角色标识的 WS 连接）。"""
    rid = str(role_id or "").strip().lower()
    if not rid:
        return False
    if has_live_client_connection(rid):
        return True
    return rid in get_live_qq_role_ids()


def check_peer_chat_participants_online(
    role_id: str, peer_role_id: str
) -> Tuple[bool, str]:
    """peer chat 双方在线门禁。

    peer chat 是角色互聊：一方 bot 没开时，另一方说出的台词只会变成 QQ 离线
    消息——计数与 last_peer_chat_ts 被白白消耗，对方永远收不到也不会回。
    因此要求参与互聊的双方都有真实连接。

    无法识别任何角色的环境（旧客户端不上报 role_id）不做拦截，避免误伤。

    Returns:
        (是否放行, 原因说明)
    """
    try:
        enabled = bool(
            get_config("dual_role.peer_chat_require_live_connections", default=True)
        )
    except Exception:
        enabled = True
    if not enabled:
        return True, "门禁未启用"

    live_roles = get_live_qq_role_ids()
    participants = (
        str(role_id or "").strip().lower(),
        str(peer_role_id or "").strip().lower(),
    )
    missing = [
        rid
        for rid in participants
        if rid and not has_live_client_connection(rid) and rid not in live_roles
    ]
    if not missing:
        return True, "双方均有真实连接"
    if not live_roles:
        return True, "无角色可识别的 QQ 连接（旧客户端），跳过门禁"
    return False, f"角色 {missing} 无真实 QQ 连接（live={sorted(live_roles)}）"


class QQConnectionResolver:
    """解析 Active Care 可投递的 QQ 连接。"""

    def __init__(self) -> None:
        self._log_state_signatures: Dict[str, str] = {}
        self._log_state_timestamps: Dict[str, float] = {}
        self._log_heartbeat_seconds = 1800.0

    def resolve(self, *, emit_logs: bool = True) -> List[Dict[str, str]]:
        """按可靠性顺序解析 QQ 连接。

        napcat / official 注册表已校验 transport 存活，属于真实连接；
        multi_qq_config 仅为静态配置，已在该分支内按常驻白名单过滤；
        websocket 兜底分支的 role_id 由共享 master_qq_id 猜测得出，
        可能把未接入的角色贴到连接上，故在出口再做一次一致性过滤。
        """
        results = self._resolve_from_napcat_registry(emit_logs=emit_logs)
        results.extend(self._resolve_from_official_registry(emit_logs=emit_logs))
        self._log_registry_results(results, emit_logs=emit_logs)

        # 常驻角色（Ling / Aveline）无论是否探测到适配器实例都必须保留，
        # 否则一旦某个非常驻角色先建立了真实连接，就会因为“注册表有结果即返回”
        # 而把常驻角色挤掉，导致它们的主动关怀被误停、双 QQ 模式退化为单角色。
        config_results = self._resolve_from_multi_qq_config(emit_logs=emit_logs)
        merged = self._merge_connections(results, config_results)
        if merged:
            return merged

        ws_results = self._resolve_from_websocket(emit_logs=emit_logs)
        return self._filter_unverified_roles(ws_results, emit_logs=emit_logs)

    @staticmethod
    def _merge_connections(
        primary: List[Dict[str, str]], fallback: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """合并真实连接与常驻角色配置连接，按 role_id 去重（真实连接优先）。"""
        merged = list(primary)
        seen = {
            str(c.get("role_id") or "").strip().lower()
            for c in primary
            if str(c.get("role_id") or "").strip()
        }
        for conn in fallback:
            rid = str(conn.get("role_id") or "").strip().lower()
            if rid and rid in seen:
                continue
            if rid:
                seen.add(rid)
            merged.append(conn)
        return merged

    def _filter_unverified_roles(
        self, results: List[Dict[str, str]], *, emit_logs: bool = True
    ) -> List[Dict[str, str]]:
        """剔除由配置猜测得出、缺乏真实接入证据的非常驻角色连接。"""
        kept: List[Dict[str, str]] = []
        dropped: List[str] = []
        for conn in results:
            role_id = str(conn.get("role_id") or "").strip()
            persona_fn = str(conn.get("persona_filename") or "").strip()
            # role_id 为空说明没匹配到任何角色配置，属于通用 QQ 连接，保留原行为。
            if not role_id or is_always_on_role(role_id, persona_fn):
                kept.append(conn)
            else:
                dropped.append(role_id)
        if dropped and emit_logs and self._should_emit_state_log(
            "websocket_filtered_roles", sorted(dropped)
        ):
            logger.info(
                "Active Care: WebSocket 兜底连接中 %s 缺乏真实接入证据，已过滤",
                sorted(dropped),
            )
        return kept

    def get_first_user_id(self) -> str:
        """获取第一个 QQ 用户 ID，用于旧单 QQ 调用路径。"""
        connections = self.resolve()
        if connections:
            return connections[0].get("user_id", "")
        return ""

    def _resolve_from_napcat_registry(self, *, emit_logs: bool = True) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        try:
            from clients.bots.qq.main import QQAdapter

            active_instances = QQAdapter.get_active_instances()
            if emit_logs and self._should_emit_state_log(
                "napcat_registry_count",
                {"count": len(active_instances) if active_instances else 0},
            ):
                logger.info(
                    "Active Care: QQAdapter 注册表查询结果: %d 个实例",
                    len(active_instances) if active_instances else 0,
                )
            should_log_instances = bool(active_instances) and emit_logs and self._should_emit_state_log(
                "napcat_registry_instances",
                [
                    (
                        str(item.get("role_id") or "").strip(),
                        str(item.get("persona_filename") or "").strip(),
                        str(item.get("master_qq_id") or "").strip(),
                    )
                    for item in active_instances
                ],
            )
            if active_instances:
                for inst in active_instances:
                    master_qq_id = str(inst.get("master_qq_id") or "").strip()
                    persona_filename = str(inst.get("persona_filename") or "").strip()
                    role_id = str(inst.get("role_id") or "").strip()
                    if should_log_instances:
                        logger.info(
                            "Active Care: QQAdapter 实例: role_id=%s, persona=%s, master_qq=%s",
                            role_id,
                            persona_filename,
                            master_qq_id,
                        )
                    if master_qq_id:
                        user_id = f"private_{master_qq_id}"
                        results.append(
                            {
                                "user_id": user_id,
                                "persona_filename": persona_filename,
                                "client_id": f"qq_{user_id}",
                                "role_id": role_id,
                                "adapter_type": "napcat",
                            }
                        )
        except ImportError:
            pass
        except Exception as e:
            if is_debug_enabled("active_care_executor"):
                logger.info("Active Care: QQAdapter 注册表查询失败: %s", e)
        return results

    def _resolve_from_official_registry(self, *, emit_logs: bool = True) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        try:
            from clients.bots.qq_official.adapter import QQOfficialAdapter

            official_instances = QQOfficialAdapter.get_active_instances()
            if official_instances:
                for inst in official_instances:
                    master_qq_id = str(inst.get("master_qq_id") or "").strip()
                    persona_filename = str(inst.get("persona_filename") or "").strip()
                    role_id = str(inst.get("role_id") or "").strip()
                    app_id = str(inst.get("app_id") or "").strip()
                    if master_qq_id:
                        user_id = f"private_{master_qq_id}"
                        results.append(
                            {
                                "user_id": user_id,
                                "persona_filename": persona_filename,
                                "client_id": f"qq_official_{app_id}",
                                "role_id": role_id,
                                "adapter_type": "official",
                            }
                        )
        except ImportError:
            pass
        except Exception as e:
            if is_debug_enabled("active_care_executor"):
                logger.info("Active Care: QQOfficialAdapter 注册表查询失败: %s", e)
        return results

    def _resolve_from_multi_qq_config(self, *, emit_logs: bool = True) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        try:
            # P2-2: 通过统一入口 get_multi_qq_raw_dict() 读取，避免脆弱的 parents[4] 路径计算
            # get_multi_qq_config() 内部已应用 env var override（XIAOYOU_QQ_MASTER_ID 等）
            # 局部导入：避免 config 包循环导入
            from config.settings_adapters import get_multi_qq_raw_dict

            multi_cfg = get_multi_qq_raw_dict()
            if not isinstance(multi_cfg, dict) or not multi_cfg:
                return []
            skipped_roles: List[str] = []
            for role_id, role_cfg in multi_cfg.items():
                if not isinstance(role_cfg, dict):
                    continue
                persona_fn = str(role_cfg.get("persona_filename") or "").strip()
                # 这一级只是读静态配置，无法证明客户端真的连上了。
                # 非常驻角色必须由 napcat/official/websocket 等真实连接来源提供，
                # 否则前端未打开时后台会照常触发主动关怀与 peer chat。
                if not is_always_on_role(str(role_id), persona_fn):
                    skipped_roles.append(str(role_id))
                    continue
                master_qq = str(role_cfg.get("master_qq_id") or "").strip()
                if not master_qq:
                    master_qq = os.getenv("XIAOYOU_QQ_MASTER_ID", "").strip()
                # 双QQ模式下 master_qq_id 可能为空（bot互聊场景），
                # 用 role_id 作为兜底标识，确保连接不被跳过
                if master_qq:
                    user_id = f"private_{master_qq}"
                else:
                    user_id = f"multi_qq_{role_id}"
                results.append(
                    {
                        "user_id": user_id,
                        "persona_filename": persona_fn,
                        "client_id": f"qq_{role_id}",
                        "role_id": str(role_id),
                        "adapter_type": "multi_qq_config",
                    }
                )
            if results and emit_logs and self._should_emit_state_log(
                "multi_qq_config_connections",
                [(r["role_id"], r["persona_filename"]) for r in results],
            ):
                logger.info(
                    "Active Care: 从 multi_qq_config 获取到 %d 个 QQ 连接: %s",
                    len(results),
                    [(r["role_id"], r["persona_filename"]) for r in results],
                )
            if skipped_roles and emit_logs and self._should_emit_state_log(
                "multi_qq_config_skipped_roles", sorted(skipped_roles)
            ):
                logger.info(
                    "Active Care: multi_qq_config 中 %s 无真实客户端连接，"
                    "非常驻角色不参与后台主动行为",
                    sorted(skipped_roles),
                )
        except Exception as e:
            if is_debug_enabled("active_care_executor"):
                logger.info("Active Care: multi_qq_config 读取失败: %s", e)
        return results

    def _resolve_from_websocket(self, *, emit_logs: bool = True) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        try:
            from core.interfaces.websocket.websocket_manager import get_websocket_manager

            ws_manager = get_websocket_manager()
            if not ws_manager or not hasattr(ws_manager, "connections"):
                return []

            # 预加载 multi_qq_config 用于补充 persona_filename 和 role_id
            multi_cfg = self._load_multi_qq_config()

            for conn in list(ws_manager.connections.values()):
                platform = str(getattr(conn, "platform", "") or "").lower().strip()
                ws_client_id = str(
                    get_config("websocket.client_id", default="", settings=conn)
                ).lower().strip()
                is_qq_conn = (
                    platform == "qq" or "qq" in platform or ws_client_id.startswith("qq_")
                )
                if is_qq_conn:
                    uid = str(getattr(conn, "user_id", "") or "").strip()
                    if uid and not uid.startswith("group_"):
                        # 从 multi_qq_config 尝试匹配 persona_filename 和 role_id
                        persona_filename, role_id = self._match_multi_qq_config(
                            uid, multi_cfg
                        )
                        results.append(
                            {
                                "user_id": uid,
                                "persona_filename": persona_filename,
                                "client_id": ws_client_id or f"qq_{uid}",
                                "role_id": role_id,
                                "adapter_type": "websocket",
                            }
                        )
            if emit_logs and self._should_emit_state_log(
                "websocket_connections",
                [(r["user_id"], r["role_id"], r["persona_filename"]) for r in results],
            ):
                logger.info("Active Care: WebSocket 扫描到 %d 个 QQ 连接", len(results))
        except Exception:
            if is_debug_enabled("active_care_executor"):
                logger.info("WebSocket连接扫描获取QQ连接失败", exc_info=True)
        return results

    def _load_multi_qq_config(self) -> Dict:
        """加载 multi_qq_config 配置（通过统一入口 get_multi_qq_raw_dict）"""
        try:
            # 局部导入：避免 config 包循环导入
            from config.settings_adapters import get_multi_qq_raw_dict

            cfg = get_multi_qq_raw_dict()
            if isinstance(cfg, dict):
                return cfg
        except Exception:
            pass
        return {}

    @staticmethod
    def _match_multi_qq_config(uid: str, multi_cfg: Dict) -> tuple:
        """根据 user_id 从 multi_qq_config 中匹配 persona_filename 和 role_id。

        uid 格式通常为 "private_123456"，需提取 QQ 号进行匹配。
        """
        if not multi_cfg:
            return "", ""
        # 从 uid 提取 QQ 号（private_123456 -> 123456）
        qq_number = uid.replace("private_", "") if uid.startswith("private_") else uid
        for role_id, role_cfg in multi_cfg.items():
            if not isinstance(role_cfg, dict):
                continue
            master_qq = str(role_cfg.get("master_qq_id") or "").strip()
            if not master_qq:
                master_qq = os.getenv("XIAOYOU_QQ_MASTER_ID", "").strip()
            if master_qq == qq_number:
                persona_fn = str(role_cfg.get("persona_filename") or "").strip()
                return persona_fn, str(role_id)
        return "", ""

    def _log_registry_results(self, results: List[Dict[str, str]], *, emit_logs: bool = True) -> None:
        if not emit_logs:
            return
        if not self._should_emit_state_log(
            key="registry_results_summary",
            payload=[(r["role_id"], r["adapter_type"], r["persona_filename"]) for r in results],
        ):
            return
        logger.info("Active Care: QQ 连接实例数量: %d", len(results))
        if results:
            logger.info(
                "Active Care: 获取到 %d 个 QQ 连接: %s",
                len(results),
                [(r["role_id"], r["adapter_type"]) for r in results],
            )

    def _should_emit_state_log(self, key: str, payload) -> bool:
        """仅在状态变化或长时间静默后输出观测日志，避免固定频率刷屏。"""
        now = time.time()
        payload_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        signature = hashlib.md5(payload_text.encode("utf-8", errors="replace")).hexdigest()
        last_signature = self._log_state_signatures.get(key, "")
        last_ts = float(self._log_state_timestamps.get(key, 0.0) or 0.0)
        if signature != last_signature or (now - last_ts) >= self._log_heartbeat_seconds:
            self._log_state_signatures[key] = signature
            self._log_state_timestamps[key] = now
            return True
        return False
