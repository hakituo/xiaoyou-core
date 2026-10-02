"""主动关怀 peer_chat 决策模块

从 decision.py 拆分而来，职责：决策当前角色是否主动找对方角色（室友）聊天。

对外暴露 PeerChatDecider 类，供 ActiveCareDecision 门面与 peer_chat_scheduler 委托调用。
"""

import asyncio
from typing import Any, Dict

from config.integrated_config import get_settings
from core.llm import get_llm_module
from core.services.active_care.decision.decision_output_parser import (
    _parse_peer_chat_output,
)
from core.utils.logger import get_logger

logger = get_logger("ACTIVE_CARE_DECISION")


class PeerChatDecider:
    """peer_chat 发送决策器

    只负责用 LLM 判断"当前角色该不该主动找对方角色聊天"，
    不负责聊天内容生成（peer_script_* 模块负责）。
    """

    def __init__(self):
        self.settings = get_settings()

    async def decide(
        self,
        context: Dict[str, Any],
        role_id: str,
        peer_name: str,
    ) -> Dict[str, Any]:
        """决策是否主动找对方角色聊天"""
        from core.agents.chat_agent_components.persona_system.prompt.qq_peer_context import (
            build_peer_chat_decision_prompt,
        )

        llm = get_llm_module()
        now_iso = str(context.get("now") or "")

        bio = context.get("bio_state", {})
        # 从 life 子字典获取 energy/mood
        life = bio.get("life", {}) if isinstance(bio, dict) else {}
        energy = float(life.get("energy", bio.get("energy", 50)))
        mood = str(life.get("mood", bio.get("mood", "neutral")))
        elapsed = int(context.get("elapsed_seconds", 0) or 0)

        from core.services.dual_role.personas import get_role_names
        role_name = get_role_names(role_id)["cn_name"]
        recent_topics = list(context.get("recent_peer_chat_topics") or [])

        # 社交事件上下文
        social_events_hint = ""
        try:
            from core.services.dual_role.social_events import get_social_event_engine
            engine = get_social_event_engine()
            social_events_hint = engine.build_recent_events_context(
                "default",
                max_items=3,
                viewer_role_id=role_id,
            )
        except Exception:
            social_events_hint = ""

        # 【缓存优化】static/dynamic 分离：system message 跨请求稳定，命中 DeepSeek Prompt Caching
        prompt_result = build_peer_chat_decision_prompt(
            role_name=role_name,
            peer_name=peer_name,
            time_str=now_iso,
            energy=energy,
            mood=mood,
            elapsed_seconds=elapsed,
            recent_topics=recent_topics,
            social_events_hint=social_events_hint,
            bio_state=bio,
        )
        messages = [
            {"role": "system", "content": prompt_result.system_prompt},
            {"role": "user", "content": prompt_result.user_prompt},
        ]

        try:
            from config.model_config import resolve_active_care_model_path
            model_path = resolve_active_care_model_path(
                model_type="decision",
                settings=self.settings,
                llm_module=llm,
            )
            # 决策 LLM 调用加超时保护（避免卡死整个 scheduler 周期）
            try:
                _decision_timeout = float(get_settings().dual_role.peer_chat_decision_timeout_seconds)
            except Exception:
                _decision_timeout = 20.0
            try:
                raw = await asyncio.wait_for(
                    llm.chat(
                        messages,
                        temperature=0.3,
                        max_new_tokens=300,
                        model_path=model_path,
                    ),
                    timeout=_decision_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("Active Care: peer_chat决策LLM超时(%.0fs)，降级为不发送", _decision_timeout)
                try:
                    from core.services.active_care.peer_chat.peer_chat_metrics import get_peer_chat_metrics
                    get_peer_chat_metrics().incr("decision_timeout")
                except Exception:
                    pass
                return {
                    "thought": f"决策LLM超时({_decision_timeout}s)",
                    "should_send": False,
                    "intent": "peer_chat",
                    "reason_code": "llm_timeout",
                    "reason": f"决策LLM超时({_decision_timeout}s)",
                    "topic": "",
                    "situation": "",
                    "opening_idea": "",
                    "social_action": "",
                    "avoid": [],
                }
            if isinstance(raw, dict):
                raw = str(raw.get("response") or raw.get("text") or "")
            # 使用 peer chat 专用 parser：一次解析提取全部字段
            # （thought/should_send/situation/opening_idea/topic），含正则兜底
            return _parse_peer_chat_output(str(raw or ""))
        except Exception as e:
            logger.warning(f"Active Care: peer_chat决策失败: {e}")
            return {
                "thought": f"决策异常: {e}",
                "should_send": False,
                "intent": "peer_chat",
                "reason_code": "decision_error",
                "reason": f"决策异常: {e}",
                "topic": "",
                "situation": "",
                "opening_idea": "",
                "social_action": "",
                "avoid": [],
            }
