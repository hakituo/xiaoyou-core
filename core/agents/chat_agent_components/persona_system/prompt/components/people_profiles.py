"""
人物档案注入组件

在聊天时根据消息内容自动注入被提及人物的档案摘要。
角色人设和用户档案由 build_detailed_persona 负责（保持现状），
本组件只负责"提及的其他人物"的按需注入。
"""

from typing import Optional


def build_mentioned_people_injection(
    message_text: str,
    user_id: Optional[str] = None,
) -> str:
    """
    构建被提及人物的档案注入文本

    扫描消息文本，找出提到的人物（基于 alias 匹配），
    返回这些人物的档案摘要（薄注入：仅 description）。

    注入策略：
    - 用户自己的档案不在这里注入（由 build_detailed_persona 常驻注入）
    - 只注入被提及的其他人物
    - 每个人物只注入精简摘要（description），详细事实通过工具查询

    Args:
        message_text: 当前用户消息文本
        user_id: 用户 ID（预留，后续向量搜索可能需要）

    Returns:
        注入文本，无匹配时返回空字符串
    """
    if not message_text or not message_text.strip():
        return ""

    try:
        from core.character.people import get_people_profile_manager
        from core.character.people.models import ProfileType

        manager = get_people_profile_manager()
        mentioned = manager.find_mentioned_people(message_text)

        if not mentioned:
            return ""

        lines: list[str] = ["【提及的人物】（以下是你了解的关于他们的信息）"]
        for person in mentioned:
            # 跳过用户自身档案（已由 build_detailed_persona 注入）
            if person.profile_type == ProfileType.SELF:
                continue
            summary = person.get_injection_summary(thick=False)
            if summary:
                lines.append(f"- {summary}")

        if len(lines) <= 1:
            return ""

        lines.append(
            "（以上信息是你自然了解的，用你自己的方式融入对话，不要照读。"
            "如果需要更详细的信息，可以调用 query_person_profile 工具查询。）"
        )
        return "\n".join(lines)
    except Exception:
        # 档案系统不可用时静默降级，不影响正常对话
        return ""
