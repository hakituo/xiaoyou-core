"""双角色互聊剧本 LLM 生成器

职责：通过 LLM 生成互动剧本（含超时、DeepSeek 回退、解析失败重试、轮数过滤）。

从 peer_script_generator.py 的 _generate_script_llm 拆分。
依赖宿主 generator 的：
- settings（取 peer_chat_content_model_hint 与超时配置）
- _extract_text_from_llm_response（LLM 响应解析）
- record_raw_text（写回剧本原文，供协商模式主入口解析分工结果）
- _last_raw_text（协商解析兜底）
"""

import asyncio

from typing import Any, Dict, Optional

from core.llm import get_llm_module
from core.utils.config_accessor import get_dual_role_config
from core.utils.logger import get_module_logger
from config.debug_config import is_debug_enabled

# peer_chat 独立日志文件，与 active_care 主流程分离
logger = get_module_logger("PEER_CHAT", "peer_chat.log")


class PeerScriptLLMGenerator:
    """双角色互聊剧本 LLM 生成器"""

    def __init__(self, host):
        """
        Args:
            host: PeerScriptGenerator 实例，提供 record_raw_text 回调；
                  settings / _extract_text_from_llm_response 经由 host._host（ActiveCareExecutor）获取。
        """
        self._host = host
        # 依用户规则统一注释说明：host._host 即底层 ActiveCareExecutor，提供运行时设置与解析能力
        self._executor = host._host

    async def generate(
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
        avoid: Optional[list] = None,
        enforce_round_limit: bool = True,
    ) -> list:
        """阶段3：通过 LLM 生成剧本（含 DeepSeek 回退 + 解析失败重试 + 质量过滤）

        Args:
            negotiation_reminders: 非空时进入协商模式，在 prompt 中注入待发提醒列表，
                要求剧本末尾输出 <assignment>JSON</assignment> 块。
            proactive_assignment_mode: True 时进入主动关怀时段分工协商模式，
                在 prompt 中注入时段划分，要求剧本末尾输出
                <proactive_assignment>JSON</proactive_assignment> 块。
            enforce_round_limit: True 时硬性校验轮数<=6（无下限，话题自然结束即可），
                越界按解析失败丢弃；False 时不强制轮数上限，供评估脚本观察模型真实轮数（不落生产）。

        Returns:
            过滤后的剧本列表，失败返回空列表
        """
        from clients.bots.qq.peer_chat import PeerChatManager
        from core.agents.chat_agent_components.persona_system.prompt.qq_peer_context import (
            build_script_generation_prompt,
        )
        from core.services.active_care.peer_chat.peer_knowledge import (
            build_knowledge_buckets,
            validate_peer_script,
        )
        from config.model_config import resolve_active_care_model_path

        # 【知识防火墙】把双方状态 + 主人私聊素材按信息权限拆分为知识分桶：
        # 各自与主人的私聊只归各自知道，跨关系内容被保密过滤；剧本生成器虽能看到
        # 双方状态，但最高规则约束角色只能说自己权限内的话（Validator 做兜底校验）。
        knowledge = build_knowledge_buckets(
            role_id=role_id,
            peer_role_id=peer_role_id,
            role_name=role_name,
            peer_name=peer_name,
            bio_state=context.get("bio_state"),
            peer_bio_state=context.get("peer_bio_state"),
            master_history_by_role=context.get("master_history_by_role") or {},
            time_str=context.get("time_str") or "",
        )

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
            knowledge=knowledge,
            avoid=avoid,
        )

        llm = get_llm_module()
        peer_chat_model_hint = str(
            get_dual_role_config("peer_chat_content_model_hint", default="", settings=self._executor.settings)
            or ""
        ).strip()
        model_path = resolve_active_care_model_path(
            model_hint=peer_chat_model_hint,
            model_type="content",
            persona_name=role_name,
            settings=self._executor.settings,
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
            fallback_llm = DeepSeekClient(api_key=api_key, model="deepseek-v4-flash", thinking_enabled=False)
            raw = await fallback_llm.chat(
                messages,
                temperature=0.9,
                max_tokens=800,
            )

        # 原文预览很长，默认不落盘（debug.peer_chat 打开才输出）
        if is_debug_enabled("peer_chat"):
            logger.info("Active Care: peer_chat剧本LLM返回 raw_type=%s, raw_preview=%s", type(raw).__name__, str(raw)[:200])
        raw_text = self._executor._extract_text_from_llm_response(raw).strip()
        # 协商模式：保存 raw_text 供主入口解析分工结果
        self._host.record_raw_text(raw_text)
        if not raw_text:
            logger.warning("Active Care: peer_chat剧本LLM返回空内容")
            return []

        # 解析剧本
        script = PeerChatManager.parse_script(raw_text)
        if script and enforce_round_limit and len(script) > 6:
            logger.warning(
                "Active Care: peer_chat剧本轮数越界 (%d>6)，按解析失败重试",
                len(script),
            )
            script = []
        # 知识防火墙：剧本越权/隐私泄漏则丢弃，触发重试
        if script:
            violations = validate_peer_script(
                script, knowledge, role_id=role_id, peer_role_id=peer_role_id
            )
            if violations:
                logger.warning(
                    "Active Care: peer_chat剧本信息越权/泄漏，按失败重试: %s",
                    " | ".join(violations),
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
                f"生成2-6轮自然对话。"
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
                retry_text = self._executor._extract_text_from_llm_response(retry_raw).strip()
                if retry_text:
                    script = PeerChatManager.parse_script(retry_text)
                    if script and enforce_round_limit and len(script) > 6:
                        logger.warning(
                            "Active Care: peer_chat重试剧本轮数仍越界 (%d>6)",
                            len(script),
                        )
                        script = []
                    if script:
                        violations = validate_peer_script(
                            script, knowledge, role_id=role_id, peer_role_id=peer_role_id
                        )
                        if violations:
                            logger.warning(
                                "Active Care: peer_chat重试剧本仍信息越权/泄漏，丢弃: %s",
                                " | ".join(violations),
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