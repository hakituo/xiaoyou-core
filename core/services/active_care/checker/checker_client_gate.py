"""
主动关怀检查器 - 客户端门控

负责检测客户端状态和私密模式，包括：
- 活跃客户端检测
- 用户进程活动检测
- 私密/敏感模式检测
- 客户端类型探测
"""
from typing import Any, Callable, Dict

from core.utils.logger import get_module_logger
from config.debug_config import is_debug_enabled
from core.utils.client_utils import probe_client_type, has_active_client
from core.services.active_care.detection.activity_detector import get_activity_detector

logger = get_module_logger("ACTIVE_CARE_CLIENT_GATE", "active_care_schedule.log")


class CheckerClientGate:
    """主动关怀检查器 - 客户端门控

    封装客户端检测和私密模式判断逻辑，
    让 ProactiveChecker 不再内联这些检测细节。
    """

    def __init__(
        self,
        context: Any,
        storage: Any,
        get_config_value: Callable[[str, Any], Any],
    ):
        self._context = context
        self._storage = storage
        self._get_config_value = get_config_value

    # ==================== 客户端检测 ====================

    def has_active_client(self) -> bool:
        """检测是否有活跃客户端连接"""
        return has_active_client()

    async def detect_user_activity(self, now: float) -> Dict[str, Any]:
        """检测用户当前进程活动状态，返回活动信息字典"""
        try:
            activity_enabled = bool(
                self._get_config_value("active_care_activity_detection_enabled", True)
            )
            if not activity_enabled:
                return {}

            busy_threshold = float(
                self._get_config_value("active_care_activity_busy_threshold", 0.60)
            )
            cache_ttl = float(
                self._get_config_value("active_care_activity_cache_ttl_seconds", 30.0)
            )

            detector = get_activity_detector(
                busy_threshold=busy_threshold,
                enabled=activity_enabled,
                cache_ttl_seconds=cache_ttl,
            )
            result = await detector.detect()
            return result.to_dict()
        except Exception as e:
            logger.warning("Active Care: detect_user_activity 异常: %s", e)
            return {}

    async def check_private_mode(self) -> bool:
        """检测当前是否处于私密/敏感模式

        Returns:
            True 表示应跳过主动关怀（私密模式激活）
        """
        try:
            primary_cid = await self._context.resolve_primary_conversation_id()
            if not primary_cid:
                if is_debug_enabled("active_care"):
                    logger.info("Active Care check_private_mode: primary_cid is empty, returning False")
                return False
            from core.services.active_care.core.persona_resolver import PersonaResolver
            persona_filename = PersonaResolver.resolve_persona_filename_static(
                primary_cid, self._storage
            )
            is_sensitive = PersonaResolver.is_sensitive_mode(persona_filename)

            current_persona_filename = ""
            current_is_sensitive = False
            try:
                from core.character.managers.persona_manager import get_persona_manager

                current_persona_filename = str(
                    get_persona_manager().get_current_filename() or ""
                ).strip()
                current_is_sensitive = PersonaResolver.is_sensitive_mode(
                    current_persona_filename
                )
            except Exception:
                current_persona_filename = ""
                current_is_sensitive = False

            if (
                is_sensitive
                and current_persona_filename
                and not current_is_sensitive
                and str(persona_filename or "").strip().lower()
                != current_persona_filename.strip().lower()
            ):
                logger.warning(
                    "Active Care check_private_mode: primary persona(%s) is sensitive but current persona(%s) is not; using current persona state.",
                    persona_filename,
                    current_persona_filename,
                )
                is_sensitive = False

            if is_debug_enabled("active_care"):
                logger.info(
                    "Active Care check_private_mode: primary_cid=%s persona_filename=%s is_sensitive=%s",
                    primary_cid, persona_filename, is_sensitive,
                )
            if is_sensitive:
                # 隐私隔离开关：关闭时不跳过 active care
                try:
                    from config.integrated_config import get_settings
                    privacy_isolation = bool(getattr(getattr(get_settings(), "chat", None), "privacy_isolation", False))
                except Exception:
                    privacy_isolation = False
                if privacy_isolation:
                    return True
        except Exception as e:
            logger.warning("Active Care check_private_mode error: %s", e)
        return False

    def probe_client_type(self) -> str:
        """探测客户端类型"""
        return probe_client_type()
