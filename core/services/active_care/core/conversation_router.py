"""Active Care 会话路由器

负责解析目标会话 ID 和客户端路由（QQ/QQ Official 双 QQ 模式）。
从 executor.py 拆分而来，方法签名与原 _xxx 方法保持一致。

依赖注入策略：整体传入 executor 实例（参考 SleepSessionManager 模式）。
"""
from typing import Optional, Tuple

from config.debug_config import is_debug_enabled
from core.utils.logger import get_module_logger

logger = get_module_logger("ACTIVE_CARE_EXECUTOR", "active_care_schedule.log")


class ConversationRouter:
    """会话路由解析器

    通过整体注入 executor 实例访问 context/storage/qq_connection_resolver 等依赖。
    """

    def __init__(self, executor):
        """构造器

        Args:
            executor: ActiveCareExecutor 实例（门面），用于访问：
                - executor.context: ActiveCareContext
                - executor.storage: ActiveCareStorage
                - executor.qq_connection_resolver: QQConnectionResolver
        """
        self._executor = executor

    async def resolve_target_conversation(
        self,
        client_type: Optional[str],
        persona_filename: str = "",
    ) -> Tuple[str, str, str]:
        """解析目标会话ID和客户端路由

        Args:
            client_type: 客户端类型
            persona_filename: 人设文件名，为空时回退到全局 PersonaManager

        Returns:
            (target_conversation_id, original_conversation_id, requested_client_type)
        """
        executor = self._executor
        target_conversation_id = await executor.context.resolve_primary_conversation_id()

        requested_client_type = str(client_type or "").strip().lower()
        original_conversation_id = target_conversation_id

        # 支持 QQ 和 QQ Official 两种客户端类型
        is_qq_client = requested_client_type in ("qq", "qq_official")

        if is_qq_client:
            qq_user_id = executor.qq_connection_resolver.get_first_user_id()
            if qq_user_id:
                # original_conversation_id 在下游承担的是 WebSocket 广播/离线队列键，
                # 必须保留真实 QQ 传输 ID。逻辑主会话可能是 shared__scope__*，
                # 若沿用它，消息会进入一个 QQ 重连永远不会清空的离线队列。
                original_conversation_id = qq_user_id
                # 双QQ模式：如果传入了 persona_filename，直接用它构建 conversation_id
                # 不依赖全局 resolve_primary_conversation_id（它可能返回另一个persona的cid）
                if persona_filename:
                    persona_cid = self.build_persona_conversation_id_for_qq(
                        qq_user_id, persona_filename=persona_filename,
                    )
                    if persona_cid:
                        logger.info(
                            "Active Care: QQ route using persona_filename-based conversation_id=%s "
                            "(QQ user_id=%s, persona=%s, original resolved=%s)",
                            persona_cid,
                            qq_user_id,
                            persona_filename,
                            original_conversation_id,
                        )
                        target_conversation_id = persona_cid
                        # 关键修复：QQ persona 覆盖后，必须同步更新 scope
                        # 否则后续读取 proactive_state 会读到另一个 persona 的状态
                        try:
                            correct_scope = executor.storage.resolve_scope_from_conversation_id(target_conversation_id)
                            executor.storage.set_runtime_scope(correct_scope)
                            logger.info(
                                "Active Care: scope 已同步为 %s (基于 persona_cid=%s)",
                                correct_scope, target_conversation_id,
                            )
                        except Exception:
                            if is_debug_enabled("active_care_executor"):
                                logger.info("同步scope失败", exc_info=True)
                        return target_conversation_id, original_conversation_id, requested_client_type

                if "__persona__" in target_conversation_id:
                    base_cid = target_conversation_id.split("__persona__", 1)[0]
                    if qq_user_id == base_cid:
                        logger.info(
                            "Active Care: QQ route keeping persona conversation_id=%s "
                            "(QQ user_id=%s matches base)",
                            target_conversation_id,
                            qq_user_id,
                        )
                    else:
                        logger.info(
                            "Active Care: QQ route using actual QQ user_id=%s "
                            "(original resolved=%s, base mismatch)",
                            qq_user_id,
                            target_conversation_id,
                        )
                        target_conversation_id = qq_user_id
                else:
                    persona_cid = self.build_persona_conversation_id_for_qq(
                        qq_user_id, persona_filename=persona_filename,
                    )
                    if persona_cid:
                        logger.info(
                            "Active Care: QQ route using persona conversation_id=%s "
                            "(QQ user_id=%s, original resolved=%s)",
                            persona_cid,
                            qq_user_id,
                            original_conversation_id,
                        )
                        target_conversation_id = persona_cid
                    else:
                        logger.info(
                            "Active Care: QQ route using actual QQ user_id=%s (original resolved=%s)",
                            qq_user_id,
                            original_conversation_id,
                        )
                        target_conversation_id = qq_user_id

        # 最终统一设置 scope，确保与 target_conversation_id 一致
        try:
            correct_scope = executor.storage.resolve_scope_from_conversation_id(target_conversation_id)
            executor.storage.set_runtime_scope(correct_scope)
        except Exception:
            if is_debug_enabled("active_care_executor"):
                logger.info("设置运行时scope失败", exc_info=True)
            pass

        return target_conversation_id, original_conversation_id, requested_client_type

    def build_persona_conversation_id_for_qq(self, qq_user_id: str, persona_filename: str = "") -> str:
        """根据人设为QQ用户构建含persona后缀的conversation_id

        解决问题：QQ adapter发送消息时使用 build_persona_conversation_id() 构建含
        __persona__ 后缀的 conversation_id，而 Active Care 解析的 QQ user_id 不含
        该后缀，导致主动消息保存到不同的 memory manager，bot在后续对话中看不到
        自己发的主动消息。

        Args:
            qq_user_id: QQ用户ID（如 private_10001）
            persona_filename: 人设文件名，为空时回退到全局 PersonaManager

        Returns:
            含persona后缀的conversation_id，如果无人设则返回空字符串
        """
        try:
            from clients.bots.qq.utils import build_persona_conversation_id

            # 优先使用传入的 persona_filename
            current_filename = str(persona_filename or "").strip()
            if not current_filename:
                from core.character.managers.persona_manager import get_persona_manager
                pm = get_persona_manager()
                current_filename = str(pm.get_current_filename() or "").strip()
            if not current_filename:
                return ""

            persona_cid = build_persona_conversation_id(qq_user_id, current_filename)
            if "__persona__" not in persona_cid:
                logger.info(
                    "Active Care: build_persona_conversation_id returned non-persona cid=%s, skipping",
                    persona_cid,
                )
                return ""

            logger.info(
                "Active Care: built persona conversation_id=%s from QQ user_id=%s, persona=%s",
                persona_cid,
                qq_user_id,
                current_filename,
            )
            return persona_cid
        except Exception as e:
            logger.warning(f"Active Care: failed to build persona conversation_id: {e}")
            return ""
