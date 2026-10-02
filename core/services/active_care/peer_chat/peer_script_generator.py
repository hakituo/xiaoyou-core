"""
双角色互聊剧本生成器（从 executor.py 拆分）

职责：负责生成双角色互聊剧本，包含 3 阶段流水线：
1. 配置加载（_load_peer_config → PeerConfigLoader）
2. 上下文拉取（_gather_peer_context → PeerContextGatherer）
3. LLM 剧本生成 + 回退 + 重试 + 过滤（_generate_script_llm → PeerScriptLLMGenerator）

分发和后处理逻辑已拆分到：
- peer_script_dispatch.dispatch_script  — 剧本分发到各自 QQ
- peer_script_hooks.run_peer_post_hooks — 后处理 hooks（日记/社交事件/巡检/历史/mention）

对外接口：
- PeerScriptGenerator(host).generate_peer_script(...)  主入口
- 委托给宿主（ActiveCareExecutor）的方法：
  - host.write_diary_entry / host.trigger_message（与主流程复用）
  - host._extract_text_from_llm_response（LLM 响应解析）
  - host.context / host.settings / host.storage（运行时状态）
"""

from core.utils.logger import get_module_logger

from typing import Any, Dict, Optional

from core.services.active_care.peer_chat.peer_config_loader import PeerConfigLoader
from core.services.active_care.peer_chat.peer_context import PeerContextGatherer
from core.services.active_care.peer_chat.peer_script_llm import PeerScriptLLMGenerator
from core.services.active_care.peer_chat.peer_script_dispatch import dispatch_script
from core.services.active_care.peer_chat.peer_script_hooks import run_peer_post_hooks

# peer_chat 独立日志文件，与 active_care 主流程分离
logger = get_module_logger("PEER_CHAT", "peer_chat.log")


class PeerScriptGenerator:
    """双角色互聊剧本生成器（3 阶段流水线 + 委托分发/hooks）"""

    def __init__(self, host):
        """
        Args:
            host: ActiveCareExecutor 实例，提供 context/settings/storage 以及
                  write_diary_entry/trigger_message/_extract_text_from_llm_response 回调
        """
        self._host = host
        # 协商模式：剧本生成后保存分工结果，供 generate_peer_script 写入 registry
        self._last_negotiation_assignments: list = []
        self._last_raw_text: str = ""

        # 3 阶段流水线子模块（从本文件拆分出去，门面负责编排）
        self._config_loader = PeerConfigLoader()
        self._context_gatherer = PeerContextGatherer(host.context)
        self._script_llm = PeerScriptLLMGenerator(self)

    def record_raw_text(self, raw_text: str) -> None:
        """记录剧本 LLM 原文（供协商模式主入口解析分工结果，由 peer_script_llm 回调）"""
        self._last_raw_text = raw_text

    # ==================== 主入口 ====================

    async def generate_peer_script(
        self,
        role_id: str,
        peer_qq_id: str,
        topic: str = "",
        situation: str = "",
        opening_idea: str = "",
        persona_filename: str = "",
        negotiation_reminders: list = None,
        proactive_assignment_mode: bool = False,
        aveline_state: str = "",
        ling_state: str = "",
        role_states: Optional[Dict[str, str]] = None,
        avoid: Optional[list] = None,
    ) -> bool:
        """生成角色互聊剧本并分发（编排器，具体逻辑见各 _peer_* 私有方法）

        流程：
        1. _load_peer_config: 加载多QQ配置
        2. _gather_peer_context: 拉取历史/时间/生理状态
        3. _generate_script_llm: LLM 生成剧本（含回退+重试）
        4. _dispatch_script: 分发到各自QQ
        5. _run_peer_post_hooks: 后处理（日记/事件/巡检/历史/mention）

        Args:
            negotiation_reminders: 非空时进入"提醒分工协商"模式，
                会把待发提醒列表注入 prompt，要求剧本末尾输出 <assignment>JSON</assignment>，
                剧本分发成功后自动写入 ReminderAssignmentRegistry。
            proactive_assignment_mode: True 时进入"主动关怀时段分工协商"模式，
                会把时段划分注入 prompt，要求剧本末尾输出
                <proactive_assignment>JSON</proactive_assignment>，
                剧本分发成功后自动写入 ProactiveAssignmentRegistry。
            aveline_state: Aveline 今日状态简述（仅 proactive_assignment_mode 用,向后兼容）
            ling_state: Ling 今日状态简述（仅 proactive_assignment_mode 用,向后兼容）
            role_states: N 角色今日状态简述 dict {role_id: state_str}
                （仅 proactive_assignment_mode 用,N 角色扩展）
        """
        # 协商模式：清空上次结果
        self._last_negotiation_assignments = []
        self._last_raw_text = ""

        try:
            # N 角色系统:从 personas 获取 peer_role_id
            from core.services.dual_role.personas import get_peer_role_id
            peer_role_id = get_peer_role_id(role_id)
            if not peer_role_id:
                # 兜底:无 peer 时无法互聊
                logger.warning("Active Care: peer_chat role=%s 无 peer 角色", role_id)
                return False

            # 阶段1：加载配置
            cfg = self._config_loader.load(role_id, peer_role_id)
            if not cfg["master_qq_id"]:
                logger.warning("Active Care: peer_chat master_qq_id为空")
                return False

            # 阶段2：拉取上下文
            ctx = await self._context_gatherer.gather(role_id, peer_role_id, cfg)

            # 阶段3：LLM 生成剧本
            script = await self._script_llm.generate(
                role_id=role_id,
                peer_role_id=peer_role_id,
                role_name=cfg["role_name"],
                peer_name=cfg["peer_name"],
                topic=topic,
                situation=situation,
                opening_idea=opening_idea,
                context=ctx,
                negotiation_reminders=negotiation_reminders,
                proactive_assignment_mode=proactive_assignment_mode,
                aveline_state=aveline_state,
                ling_state=ling_state,
                role_states=role_states,
                avoid=avoid,
            )
            if not script:
                # 协商模式下剧本生成失败，仍尝试从 raw_text 解析分工（兜底）
                if negotiation_reminders and self._last_raw_text:
                    await self._persist_negotiation_assignments(
                        self._last_raw_text, role_id, peer_role_id
                    )
                if proactive_assignment_mode and self._last_raw_text:
                    await self._persist_proactive_assignment(
                        self._last_raw_text, role_id, peer_role_id
                    )
                return False

            # 阶段4：分发剧本
            sent_any, should_notify_user, notify_content = await dispatch_script(
                script=script,
                role_id=role_id,
                peer_role_id=peer_role_id,
                cfg=cfg,
            )

            # 协商模式：剧本分发成功后，从 raw_text 解析分工并写入 registry
            if negotiation_reminders and self._last_raw_text:
                await self._persist_negotiation_assignments(
                    self._last_raw_text, role_id, peer_role_id
                )
            # 主动关怀时段分工协商：剧本分发成功后解析并写入 registry
            if proactive_assignment_mode and self._last_raw_text:
                await self._persist_proactive_assignment(
                    self._last_raw_text, role_id, peer_role_id
                )

            # 阶段5：后处理 hooks
            if sent_any:
                await run_peer_post_hooks(
                    script=script,
                    role_id=role_id,
                    peer_role_id=peer_role_id,
                    cfg=cfg,
                    should_notify_user=should_notify_user,
                    notify_content=notify_content,
                    host=self._host,
                )
            else:
                logger.warning(
                    "Active Care: peer_chat剧本分发失败 %s<->%s",
                    cfg["role_name"], cfg["peer_name"],
                )

            return sent_any

        except Exception as e:
            logger.error(f"Active Care: generate_peer_script异常: {e}", exc_info=True)
            return False

    # ==================== 兼容入口（委托给拆分出的子模块） ====================

    def _load_peer_config(self, role_id: str, peer_role_id: str) -> Dict[str, Any]:
        """阶段1：加载多QQ配置（委托给 PeerConfigLoader，逻辑在 peer_config_loader.py）"""
        return self._config_loader.load(role_id, peer_role_id)

    async def _gather_peer_context(
        self, role_id: str, peer_role_id: str, cfg: Dict[str, Any]
    ) -> Dict[str, Any]:
        """阶段2：拉取上下文（委托给 PeerContextGatherer，逻辑在 peer_context.py）"""
        return await self._context_gatherer.gather(role_id, peer_role_id, cfg)

    async def _generate_script_llm(self, **kwargs) -> list:
        """阶段3：LLM 生成剧本（委托给 PeerScriptLLMGenerator，逻辑在 peer_script_llm.py）"""
        return await self._script_llm.generate(**kwargs)

    async def _persist_negotiation_assignments(
        self, raw_text: str, role_id: str, peer_role_id: str
    ) -> None:
        """协商模式：从剧本原文解析分工结果并写入 ReminderAssignmentRegistry

        解析失败时不抛异常，由调用方走兜底（先到先得）。
        """
        try:
            from core.services.active_care.peer_chat.negotiation_parser import (
                parse_assignments_from_script,
            )
            from core.services.active_care.storage.reminder_assignment_registry import (
                get_reminder_assignment_registry,
            )

            assignments = parse_assignments_from_script(raw_text)
            self._last_negotiation_assignments = assignments

            registry = get_reminder_assignment_registry()
            if assignments:
                # 有分工结果：写入 registry
                for a in assignments:
                    await registry.mark_assigned(
                        reminder_id=a["reminder_id"],
                        title=a.get("title", ""),
                        persona=a["assigned_to"],
                        reason=a.get("reason", ""),
                    )
                await registry.mark_negotiation_status("completed")
                logger.info(
                    "Active Care: 提醒分工协商完成，写入 %d 条分配",
                    len(assignments),
                )
            else:
                # 解析失败：标记 failed，走兜底
                await registry.mark_negotiation_status(
                    "failed", reason="剧本未包含有效 <assignment> 块"
                )
                logger.warning(
                    "Active Care: 提醒分工协商失败，剧本未包含有效分工 JSON，"
                    "退回先到先得模式"
                )
        except Exception as e:
            logger.error(
                "Active Care: _persist_negotiation_assignments 异常: %s",
                e, exc_info=True,
            )

    async def _persist_proactive_assignment(
        self, raw_text: str, role_id: str, peer_role_id: str
    ) -> None:
        """主动关怀时段分工协商：从剧本原文解析分工结果并写入 ProactiveAssignmentRegistry

        解析失败时不抛异常，由调用方走兜底（轮流制）。
        """
        try:
            from core.services.active_care.peer_chat.proactive_assignment_parser import (
                parse_proactive_assignment_from_script,
            )
            from core.services.active_care.storage.proactive_assignment_registry import (
                get_proactive_assignment_registry,
            )

            assignments = parse_proactive_assignment_from_script(raw_text)
            registry = get_proactive_assignment_registry()
            if assignments:
                # 有分工结果：写入 registry
                await registry.set_assignments(assignments)
                logger.info(
                    "Active Care: 主动关怀时段分工协商完成，写入 %d 条分配",
                    len(assignments),
                )
            else:
                # 解析失败：标记 failed，走兜底（轮流制）
                await registry.mark_negotiation_status(
                    "failed", reason="剧本未包含有效 <proactive_assignment> 块"
                )
                logger.warning(
                    "Active Care: 主动关怀时段分工协商失败，剧本未包含有效分工 JSON，"
                    "退回轮流制兜底"
                )
        except Exception as e:
            logger.error(
                "Active Care: _persist_proactive_assignment 异常: %s",
                e, exc_info=True,
            )