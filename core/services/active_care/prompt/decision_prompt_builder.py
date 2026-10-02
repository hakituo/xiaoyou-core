"""决策 Prompt 组装器（与内容生成 prompt 解耦）

Prompt v2 原则：
- 决策层只判断“现在值不值得联系”，不负责写最终消息；
- 最终文本一律由生成层在决策 send 后产出；
- 模板只存在于 `persona_system/prompt/active_care_prompts.py`，本模块不内嵌文案；
- Prompt 优先级统一（P0~P6），各模块不再自行声明“最高优先级”。

职责边界：
- 本模块：把“决策输入数据”拼成发给决策模型的 system / user 两条消息；
- content_planner.py：准备决策输入数据（上下文快照 / 睡眠指标 / 行为指引 /
  状态约束），调用本模块拿组装结果，再负责 LLM 调用与结果归一化。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
    DECISION_SYSTEM_PROMPT_TEMPLATE,
    DECISION_USER_MESSAGE_TEMPLATE,
    NO_DEFER_LEAK_CONSTRAINT,
    SEND_DEFER_PROTOCOL,
    SHOULD_CONTACT_USER_GUIDE,
)


@dataclass
class DecisionPromptBundle:
    """一次决策请求的组装结果。"""

    system_prompt: str = ""
    user_message: str = ""
    sections: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def messages(self) -> List[Dict[str, str]]:
        """直接可投递给 LLM 的两条消息。"""
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self.user_message},
        ]

    @property
    def system_chars(self) -> int:
        return len(self.system_prompt or "")

    @property
    def user_chars(self) -> int:
        return len(self.user_message or "")


def build_active_care_decision_prompt(
    *,
    chosen_action: str,
    persona_summary: str = "",
    llm_ctx: Dict[str, Any],
    dynamic_constraints: List[str],
    specific_instruction: str = "",
    daily_push_text: str = "",
) -> DecisionPromptBundle:
    """组装决策 prompt（send/defer 二选一）。

    Args:
        chosen_action: 上游动作选择器已选定的候选意图（code 侧已过滤）。
        persona_summary: 截断后的身份摘要（P4，放 system，保持缓存稳定前缀）。
        llm_ctx: 决策上下文快照（json-serializable，进 user message）。
        dynamic_constraints: 当前状态约束行（P1 睡眠/模式/活动等）。
        specific_instruction: 候选动作的行为指引（透传给生成层，决策可参考）。
        daily_push_text: 今日推送优先级格式化文本（可为空）。

    Returns:
        DecisionPromptBundle：system / user 两条消息。
    """
    # ── system：身份摘要（P4）+ 决策角色 + 协议 + 判断原则 + 输出格式 ──
    # 注意 DECISION_SYSTEM_PROMPT_TEMPLATE 含 JSON 字面量 `{`/`}`，
    # 禁止 .format()，intent 槽位用 replace 填充。
    system_parts: List[str] = []
    if str(persona_summary or "").strip():
        system_parts.append(str(persona_summary).strip())
    system_parts.append(
        DECISION_SYSTEM_PROMPT_TEMPLATE.replace("{chosen_action}", chosen_action)
    )
    system_parts.append(SEND_DEFER_PROTOCOL.strip())
    system_parts.append(SHOULD_CONTACT_USER_GUIDE.strip())
    system_parts.append(NO_DEFER_LEAK_CONSTRAINT.strip())

    # 输出格式 schema 与 retry 指导（决策 schema 唯一真相源在 decision_output_parser）
    from core.services.active_care.decision.decision_output_parser import (
        _build_output_format_schema,
    )

    system_parts.append(_build_output_format_schema(chosen_action).strip())

    system_prompt = "\n\n".join(p for p in system_parts if p)

    # ── user：上下文快照 + P1 状态约束 + 行为指引 + 推送优先级 ──
    import json

    user_parts: List[str] = []
    user_parts.append(
        DECISION_USER_MESSAGE_TEMPLATE.format(
            context_json=json.dumps(llm_ctx, ensure_ascii=False)
        )
    )
    if dynamic_constraints:
        user_parts.append(
            "【当前状态约束（P1）】\n" + "\n".join(f"- {x}" for x in dynamic_constraints)
        )
    if str(specific_instruction or "").strip():
        user_parts.append(
            "【候选动作行为指引（仅当 send 时生成层会执行）】\n"
            + str(specific_instruction).strip()
        )
    if str(daily_push_text or "").strip():
        user_parts.append(str(daily_push_text).strip())

    return DecisionPromptBundle(
        system_prompt=system_prompt,
        user_message="\n\n".join(p for p in user_parts if p),
        sections=[
            {"name": "decision_system", "content": system_prompt},
            {"name": "decision_user", "content": user_parts[0] if user_parts else ""},
            {"name": "decision_status_constraints",
             "content": user_parts[1] if len(user_parts) > 1 else ""},
        ],
    )


__all__ = ["DecisionPromptBundle", "build_active_care_decision_prompt"]
