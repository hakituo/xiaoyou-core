"""
双角色互聊剧本生成器（从 executor.py 拆分）

职责：负责生成双角色互聊剧本，包含 3 阶段流水线：
1. 配置加载（_load_peer_config）
2. 上下文拉取（_gather_peer_context）
3. LLM 剧本生成 + 回退 + 重试 + 过滤（_generate_script_llm）

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
import asyncio

from typing import Any, Dict, Optional

from core.llm import get_llm_module
from core.utils.config_accessor import get_active_care_config
from config.debug_config import is_debug_enabled
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
            cfg = self._load_peer_config(role_id, peer_role_id)
            if not cfg["master_qq_id"]:
                logger.warning("Active Care: peer_chat master_qq_id为空")
                return False

            # 阶段2：拉取上下文
            ctx = await self._gather_peer_context(role_id, peer_role_id, cfg)

            # 阶段3：LLM 生成剧本
            script = await self._generate_script_llm(
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

    # ==================== 阶段1：配置加载 ====================

    def _load_peer_config(
        self, role_id: str, peer_role_id: str
    ) -> Dict[str, Any]:
        """阶段1：加载多QQ配置（master_qq_id / 角色 QQ 号 / persona 文件名）

        通过 get_multi_qq_role_config() 强类型访问 + 环境变量读取，
        回退到 personas 权威源(N 角色动态)。
        """
        import os as _os
        # 局部导入：避免 config 包循环导入（peer_script_generator 可能在 config 完成初始化前被导入）
        from config.settings_adapters import get_multi_qq_role_config
        from core.services.dual_role.personas import get_persona

        role_cfg = get_multi_qq_role_config(role_id)
        peer_cfg = get_multi_qq_role_config(peer_role_id)

        master_qq_id = _os.getenv("XIAOYOU_QQ_MASTER_ID", "").strip()

        # 角色 QQ 号:N 角色通用读法
        # 优先从 multi_qq_config 读 role_qq_id,缺失时读环境变量
        def _resolve_role_qq(rid: str, cfg_obj) -> str:
            """从 config 或 env var 解析角色 QQ 号(N 角色通用)"""
            if cfg_obj is not None:
                val = str(getattr(cfg_obj, "role_qq_id", "") or "").strip()
                if val:
                    return val
            # 向后兼容:aveline/ling 用旧 env var 名
            if rid == "aveline":
                val = _os.getenv("XIAOYOU_QQ_BOT_NUMBER", "").strip()
                if val:
                    return val
            elif rid == "ling":
                val = _os.getenv("XIAOYOU_QQ_BOT_NUMBER_LING", "").strip()
                if val:
                    return val
            # N 角色通用:XIAOYOU_QQ_BOT_NUMBER_{ROLE_ID_UPPER}
            return _os.getenv(f"XIAOYOU_QQ_BOT_NUMBER_{rid.upper()}", "").strip()

        role_qq_id = _resolve_role_qq(role_id, role_cfg)
        peer_role_qq_id = _resolve_role_qq(peer_role_id, peer_cfg)

        # persona_filename:优先用强类型配置,缺失时从 personas 查 config_filename
        role_persona_fn = ""
        if role_cfg is not None:
            role_persona_fn = str(getattr(role_cfg, "persona_filename", "") or "").strip()
        if not role_persona_fn:
            p = get_persona(role_id)
            if p:
                role_persona_fn = p.config_filename

        peer_persona_fn = ""
        if peer_cfg is not None:
            peer_persona_fn = str(getattr(peer_cfg, "persona_filename", "") or "").strip()
        if not peer_persona_fn:
            p = get_persona(peer_role_id)
            if p:
                peer_persona_fn = p.config_filename

        # role_name:优先用强类型配置,缺失时从 personas 查 cn_name
        role_name = ""
        if role_cfg is not None:
            role_name = str(getattr(role_cfg, "role_name", "") or "").strip()
        if not role_name:
            p = get_persona(role_id)
            if p:
                role_name = p.cn_name

        peer_name = ""
        if peer_cfg is not None:
            peer_name = str(getattr(peer_cfg, "role_name", "") or "").strip()
        if not peer_name:
            p = get_persona(peer_role_id)
            if p:
                peer_name = p.cn_name

        return {
            "master_qq_id": master_qq_id,
            "role_qq_id": role_qq_id,
            "peer_role_qq_id": peer_role_qq_id,
            "role_persona_fn": role_persona_fn,
            "peer_persona_fn": peer_persona_fn,
            "role_name": role_name,
            "peer_name": peer_name,
        }

    # ==================== 阶段2：上下文拉取 ====================

    async def _gather_peer_context(
        self, role_id: str, peer_role_id: str, cfg: Dict[str, Any]
    ) -> Dict[str, Any]:
        """阶段2：拉取生成剧本所需的上下文（主人聊天记录/互聊历史/时间/生理状态）"""
        from clients.bots.qq.peer_chat import PeerChatManager

        # 同时获取双方各自和主人的真实聊天，避免只看到当前全局 persona。
        recent_master_sections = []
        try:
            from clients.bots.qq.utils import build_persona_conversation_id

            seen_conversation_ids = set()
            for persona_fn, speaker_name in (
                (str(cfg.get("role_persona_fn") or ""), str(cfg.get("role_name") or role_id)),
                (str(cfg.get("peer_persona_fn") or ""), str(cfg.get("peer_name") or peer_role_id)),
            ):
                if not persona_fn:
                    continue
                conversation_id = build_persona_conversation_id("shared", persona_fn)
                if not conversation_id or conversation_id in seen_conversation_ids:
                    continue
                seen_conversation_ids.add(conversation_id)
                section = await PeerChatManager.get_recent_master_history(
                    self._host.context,
                    conversation_id,
                    limit=8,
                    speaker_name=speaker_name,
                )
                if section:
                    recent_master_sections.append(section)
        except Exception as e:
            if is_debug_enabled("peer_script"):
                logger.info(f"获取主人聊天记录失败: {e}")
        recent_master_history = "\n\n".join(recent_master_sections)

        # 获取之前的互聊剧本记录
        recent_peer_scripts = ""
        try:
            recent_peer_scripts = await PeerChatManager.get_recent_peer_scripts(
                self._host.context, role_id, limit=5
            )
        except Exception as e:
            if is_debug_enabled("peer_script"):
                logger.info(f"获取互聊剧本记录失败: {e}")

        # 构建时间字符串
        from core.utils.time_utils import get_current_time
        now_dt = get_current_time()
        time_str = now_dt.strftime('%Y-%m-%d %H:%M')

        # 获取双方生理状态
        bio_state = None
        peer_bio_state = None
        try:
            from core.services.life_simulation import get_life_simulation_service
            life_sim = get_life_simulation_service()
            if life_sim:
                bio_state = life_sim.get_bio_state(role_id)
                peer_bio_state = life_sim.get_bio_state(peer_role_id)
        except Exception:
            pass

        return {
            "recent_master_history": recent_master_history,
            "recent_peer_scripts": recent_peer_scripts,
            "time_str": time_str,
            "bio_state": bio_state,
            "peer_bio_state": peer_bio_state,
        }

    # ==================== 阶段3：LLM 剧本生成 ====================

    async def _generate_script_llm(
        self,
        *,
        role_id: str,
        peer_role_id: str,
        role_name: str,
        peer_name: str,
        topic: str,
        situation: str,
        opening_idea: str,
        context: Dict[str, Any],
        negotiation_reminders: list = None,
        proactive_assignment_mode: bool = False,
        aveline_state: str = "",
        ling_state: str = "",
        role_states: Optional[Dict[str, str]] = None,
        enforce_round_limit: bool = True,
    ) -> list:
        """阶段3：通过 LLM 生成剧本（含 DeepSeek 回退 + 解析失败重试 + 质量过滤）

        Args:
            negotiation_reminders: 非空时进入协商模式，在 prompt 中注入待发提醒列表，
                要求剧本末尾输出 <assignment>JSON</assignment> 块。
            proactive_assignment_mode: True 时进入主动关怀时段分工协商模式，
                在 prompt 中注入时段划分，要求剧本末尾输出
                <proactive_assignment>JSON</proactive_assignment> 块。
            enforce_round_limit: True 时硬性校验 3<=轮数<=6，越界按解析失败丢弃；
                False 时不强制轮数上限，供评估脚本观察模型真实轮数（不落生产）。

        Returns:
            过滤后的剧本列表，失败返回空列表
        """
        from clients.bots.qq.peer_chat import PeerChatManager
        from core.agents.chat_agent_components.persona_system.prompt.qq_peer_context import (
            build_script_generation_prompt,
        )
        from config.model_config import resolve_active_care_model_path

        # 【缓存优化】static/dynamic 分离：system message 跨请求稳定，命中 DeepSeek Prompt Caching
        prompt_result = build_script_generation_prompt(
            role_name=role_name,
            peer_name=peer_name,
            role_id=role_id,
            peer_role_id=peer_role_id,
            topic=topic,
            situation=situation,
            opening_idea=opening_idea,
            recent_master_history=context["recent_master_history"],
            recent_peer_scripts=context["recent_peer_scripts"],
            time_str=context["time_str"],
            bio_state=context["bio_state"],
            peer_bio_state=context["peer_bio_state"],
        )

        llm = get_llm_module()
        peer_chat_model_hint = str(
            get_active_care_config("peer_chat_content_model_hint", default="", settings=self._host.settings)
            or ""
        ).strip()
        model_path = resolve_active_care_model_path(
            model_hint=peer_chat_model_hint,
            model_type="content",
            persona_name=role_name,
            settings=self._host.settings,
            llm_module=llm,
        )

        # 协商模式：在 user_prompt 末尾追加待发提醒列表 + 输出格式要求
        user_prompt = prompt_result.user_prompt
        if negotiation_reminders:
            from core.services.active_care.peer_chat.negotiation_parser import (
                build_reminder_list_text,
            )
            reminder_text = build_reminder_list_text(negotiation_reminders)
            negotiation_suffix = (
                f"\n\n========== 提醒分工协商 ==========\n"
                f"你们今天是双角色模式，需要协商「今天这些提醒谁去发给主人」。\n"
                f"请基于你们各自的人设特点和与主人的关系，自然地讨论谁更适合发哪条提醒。\n"
                f"讨论完后，请在剧本末尾输出分工结果，格式如下：\n"
                f"<assignment>\n"
                f'{{"assignments": [{{"reminder_id": "提醒ID", "assigned_to": "aveline或ling", "reason": "简短原因"}}]}}\n'
                f"</assignment>\n\n"
                f"今日待发提醒列表：\n{reminder_text}\n"
                f"=================================\n"
            )
            user_prompt = user_prompt + negotiation_suffix

        # 主动关怀时段分工协商模式：追加时段划分 + 输出格式要求
        if proactive_assignment_mode:
            from core.services.active_care.prompt.proactive_assignment_prompts import (
                build_proactive_assignment_negotiation_suffix,
            )
            proactive_suffix = build_proactive_assignment_negotiation_suffix(
                aveline_state=aveline_state,
                ling_state=ling_state,
                role_states=role_states,
            )
            user_prompt = user_prompt + proactive_suffix

        # 【缓存优化】构建 system + user 分离的 messages
        messages = [
            {"role": "system", "content": prompt_result.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # 超时配置
        try:
            from config.integrated_config import get_settings
            _script_timeout = float(get_settings().dual_role.peer_chat_script_timeout_seconds)
        except Exception:
            _script_timeout = 45.0

        raw = None
        try:
            raw = await asyncio.wait_for(
                llm.chat(
                    messages,
                    temperature=0.9,
                    max_new_tokens=800,
                    model_path=model_path,
                ),
                timeout=_script_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Active Care: peer_chat剧本LLM超时(%.0fs)", _script_timeout)
            try:
                from core.services.active_care.peer_chat.peer_chat_metrics import get_peer_chat_metrics
                get_peer_chat_metrics().incr("script_llm_timeout")
            except Exception:
                pass
            return []
        except Exception as llm_err:
            logger.warning("Active Care: peer_chat LLM调用失败 (model_path=%s): %s", model_path, llm_err)
            # 回退到直接 DeepSeekClient
            from core.llm.openai_compat.deepseek_client import DeepSeekClient
            import os as _os
            api_key = _os.getenv("DEEPSEEK_API_KEY_QQBOT1") or _os.getenv("DEEPSEEK_API_KEY")
            if not api_key:
                raise RuntimeError(f"peer_chat LLM 调用失败且无回退 API Key: {llm_err}") from llm_err
            fallback_llm = DeepSeekClient(api_key=api_key, model="deepseek-v4-pro", thinking_enabled=False)
            raw = await fallback_llm.chat(
                messages,
                temperature=0.9,
                max_tokens=800,
            )

        logger.info("Active Care: peer_chat剧本LLM返回 raw_type=%s, raw_preview=%s", type(raw).__name__, str(raw)[:200])
        raw_text = self._host._extract_text_from_llm_response(raw).strip()
        # 协商模式：保存 raw_text 供主入口解析分工结果
        self._last_raw_text = raw_text
        if not raw_text:
            logger.warning("Active Care: peer_chat剧本LLM返回空内容")
            return []

        # 解析剧本
        script = PeerChatManager.parse_script(raw_text)
        if script and enforce_round_limit and not 3 <= len(script) <= 6:
            logger.warning(
                "Active Care: peer_chat剧本轮数越界 (%d)，按解析失败重试",
                len(script),
            )
            script = []
        if not script:
            # 解析失败：用更简单的提示重试一次
            logger.warning("Active Care: peer_chat剧本解析失败，重试一次: %s", raw_text[:100])
            try:
                from core.services.active_care.peer_chat.peer_chat_metrics import get_peer_chat_metrics
                get_peer_chat_metrics().incr("parse_retries")
            except Exception:
                pass
            retry_prompt = (
                f"请直接输出JSON格式的对话剧本，不要加任何说明文字。\n"
                f"格式: {{\"script\": [{{\"role\": \"{role_id}\", \"content\": \"...\" }}, {{\"role\": \"{peer_role_id}\", \"content\": \"...\"}}]}}\n"
                f"话题: {topic}\n角色: {role_name}({role_id}) 和 {peer_name}({peer_role_id})\n"
                f"生成4-6轮自然对话。"
            )
            try:
                retry_raw = await asyncio.wait_for(
                    llm.chat(
                        [
                            {"role": "system", "content": prompt_result.system_prompt},
                            {"role": "user", "content": retry_prompt},
                        ],
                        temperature=0.9,
                        max_new_tokens=600,
                        model_path=model_path,
                    ),
                    timeout=min(_script_timeout, 30.0),
                )
                retry_text = self._host._extract_text_from_llm_response(retry_raw).strip()
                if retry_text:
                    script = PeerChatManager.parse_script(retry_text)
                    if script and enforce_round_limit and not 3 <= len(script) <= 6:
                        logger.warning(
                            "Active Care: peer_chat重试剧本轮数仍越界 (%d)",
                            len(script),
                        )
                        script = []
            except Exception as retry_err:
                logger.warning("Active Care: peer_chat 重试也失败: %s", retry_err)
            if not script:
                logger.warning("Active Care: peer_chat剧本解析重试后仍失败")
                return []

        logger.info(
            "Active Care: peer_chat剧本生成成功 %s<->%s (%d轮, topic=%s)",
            role_name, peer_name, len(script), topic[:30],
        )
        try:
            from core.services.active_care.peer_chat.peer_chat_metrics import get_peer_chat_metrics
            get_peer_chat_metrics().incr("scripts_generated")
        except Exception:
            pass
        return script
