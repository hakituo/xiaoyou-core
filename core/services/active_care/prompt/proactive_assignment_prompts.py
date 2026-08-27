"""
主动关怀时段分工协商 prompt 构建

职责：
- 构建 peer chat 协商 prompt 的"主动关怀分工"追加段
- 说明时段划分、输出格式要求
- 供 PeerScriptGenerator 在 proactive_assignment 协商模式下注入 user_prompt

输出格式约定（LLM 必须在剧本末尾输出）：

<proactive_assignment>
{
  "assignments": [
    {"time_slot": "morning", "lead": "aveline", "reason": "Aveline 上午精神好"},
    {"time_slot": "afternoon", "lead": "ling", "reason": "Ling 下午有空"},
    {"time_slot": "evening", "lead": "aveline", "reason": "Aveline 晚上更适合陪主人"}
  ]
}
</proactive_assignment>
"""
from core.services.active_care.peer_chat.proactive_assignment_parser import (
    build_slot_list_text,
)


def build_proactive_assignment_negotiation_suffix(
    aveline_state: str = "",
    ling_state: str = "",
    role_states: dict = None,
) -> str:
    """构建主动关怀时段分工协商的 prompt 追加段

    Args:
        aveline_state: Aveline 今日状态简述（向后兼容）
        ling_state: Ling 今日状态简述（向后兼容）
        role_states: N 角色今日状态 dict {role_id: state_str}
            优先使用,为空时回退到 aveline_state/ling_state

    Returns:
        追加到 user_prompt 末尾的协商说明文本
    """
    slot_text = build_slot_list_text()

    # N 角色系统:优先用 role_states,向后兼容 aveline_state/ling_state
    state_section = ""
    if role_states:
        # 从 personas 查角色中文名
        try:
            from core.services.dual_role.personas import get_persona
            state_lines = []
            for rid, state_str in role_states.items():
                if not state_str:
                    continue
                p = get_persona(rid)
                display_name = p.cn_name if p else rid
                state_lines.append(f"  - {display_name}（{rid}）：{state_str}")
            if state_lines:
                state_section = (
                    "\n今日各自状态参考：\n"
                    + "\n".join(state_lines)
                    + "\n"
                )
        except Exception:
            pass
    elif aveline_state or ling_state:
        state_lines = []
        if aveline_state:
            state_lines.append(f"  - 七濑 澪（Aveline）：{aveline_state}")
        if ling_state:
            state_lines.append(f"  - Ling（Ling）：{ling_state}")
        state_section = (
            "\n今日各自状态参考：\n"
            + "\n".join(state_lines)
            + "\n"
        )

    return (
        f"\n\n========== 主动关怀时段分工协商 ==========\n"
        f"你们今天是双角色模式，需要协商「今天各时段谁来主导给主人发主动关怀消息」。\n"
        f"请基于你们各自的人设特点、今日状态和与主人的关系，自然地讨论谁更适合在哪个时段主导。\n"
        f"「主导角色」在该时段优先给主人发主动关怀，另一个角色尽量避免在同一时段重复发送。\n"
        f"注意：这是分工不是绝对禁止，如果主导角色长时间没发，另一个角色可以兜底。\n"
        f"\n"
        f"今天需要分配的时段：\n{slot_text}\n"
        f"{state_section}"
        f"\n"
        f"讨论完后，请在剧本末尾输出分工结果，格式如下：\n"
        f"<proactive_assignment>\n"
        f'{{"assignments": [{{"time_slot": "morning/afternoon/evening", "lead": "aveline或ling", "reason": "简短原因"}}]}}\n'
        f"</proactive_assignment>\n"
        f"\n"
        f"要求：\n"
        f"- 每个时段都要分配一个主导角色\n"
        f"- lead 只能是 aveline 或 ling\n"
        f"- reason 简短说明为什么这个角色适合这个时段\n"
        f"=========================================\n"
    )
