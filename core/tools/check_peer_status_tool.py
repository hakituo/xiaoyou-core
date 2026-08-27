"""CheckPeerStatusTool — 让 LLM 能查看另一个角色的生理状态。

在和用户聊天时，如果用户问"Ling怎么样了"或"七濑 澪在干嘛"，
LLM 可以调用此工具获取对方角色的实时生理状态。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("CheckPeerStatusTool")

_PEER_ROLE_NAMES = {
    "ling": "Ling",
    "aveline": "七濑 澪",
}


class CheckPeerStatusInput(BaseModel):
    peer_role: str = Field(
        description="要查看的角色。'ling'（Ling）或 'aveline'（七濑 澪）。"
    )


class CheckPeerStatusTool(BaseTool):
    name = "check_peer_status"
    description = (
        "查看另一个角色（Ling/七濑 澪）的当前生理状态。"
        "当用户问'Ling怎么样了'、'七濑 澪在干嘛'、'她吃饭了吗'等问题时使用。"
        "返回对方角色的能量、饥饿、心情、状态等信息。"
    )
    short_description = "查看Ling/七濑 澪的当前状态"
    args_schema = CheckPeerStatusInput
    category = "memory"
    enabled_by_default = True

    async def _run(self, peer_role: str = "ling") -> str:
        peer_role = peer_role.strip().lower()
        if peer_role not in _PEER_ROLE_NAMES:
            return f"无效的角色 '{peer_role}'，可选值：ling（Ling）、aveline（七濑 澪）。"

        peer_name = _PEER_ROLE_NAMES[peer_role]

        try:
            from core.services.life_simulation.service import get_life_simulation_service
            life_sim = get_life_simulation_service()
            state = life_sim.get_actor_life_state(peer_role)
        except Exception as e:
            logger.warning(f"获取{peer_name}生理状态失败: {e}")
            return f"无法获取{peer_name}的当前状态。"

        if not isinstance(state, dict) or not state:
            return f"暂时没有{peer_name}的状态数据。"

        return _format_actor_state(peer_name, state)


def _format_actor_state(name: str, state: dict) -> str:
    parts = [f"{name}的当前状态："]

    energy = state.get("energy")
    if energy is not None:
        try:
            e = float(energy)
            if e < 20:
                parts.append(f"  能量：{e:.0f}/100（非常疲惫）")
            elif e < 40:
                parts.append(f"  能量：{e:.0f}/100（比较累）")
            elif e < 60:
                parts.append(f"  能量：{e:.0f}/100（有点累）")
            elif e < 80:
                parts.append(f"  能量：{e:.0f}/100（精神还行）")
            else:
                parts.append(f"  能量：{e:.0f}/100（精力充沛）")
        except (ValueError, TypeError):
            pass

    hunger = state.get("hunger")
    if hunger is not None:
        try:
            h = float(hunger)
            if h < 20:
                parts.append(f"  饱腹感：{h:.0f}/100（很饿）")
            elif h < 40:
                parts.append(f"  饱腹感：{h:.0f}/100（有点饿）")
            elif h < 60:
                parts.append(f"  饱腹感：{h:.0f}/100（还行）")
            elif h < 80:
                parts.append(f"  饱腹感：{h:.0f}/100（挺饱的）")
            else:
                parts.append(f"  饱腹感：{h:.0f}/100（吃得很饱）")
        except (ValueError, TypeError):
            pass

    thirst = state.get("thirst")
    if thirst is not None:
        try:
            t = float(thirst)
            if t < 30:
                parts.append(f"  口渴度：{t:.0f}/100（很渴）")
            elif t < 60:
                parts.append(f"  口渴度：{t:.0f}/100（有点渴）")
            else:
                parts.append(f"  口渴度：{t:.0f}/100（不渴）")
        except (ValueError, TypeError):
            pass

    mood_score = state.get("mood_score")
    if mood_score is not None:
        try:
            m = float(mood_score)
            if m < 30:
                parts.append(f"  心情：{m:.0f}/100（心情不好）")
            elif m < 50:
                parts.append(f"  心情：{m:.0f}/100（心情一般）")
            elif m < 70:
                parts.append(f"  心情：{m:.0f}/100（心情不错）")
            else:
                parts.append(f"  心情：{m:.0f}/100（心情很好）")
        except (ValueError, TypeError):
            pass

    is_sick = state.get("is_sick")
    if is_sick:
        parts.append("  健康：身体不舒服")

    shyness = state.get("shyness_score")
    if shyness is not None:
        try:
            s = float(shyness)
            if s > 70:
                parts.append("  状态：很害羞/紧张")
        except (ValueError, TypeError):
            pass

    food_inventory = state.get("food_inventory")
    if isinstance(food_inventory, list) and food_inventory:
        food_names = []
        for item in food_inventory[:5]:
            if isinstance(item, dict):
                food_names.append(str(item.get("name", item)))
            else:
                food_names.append(str(item))
        parts.append(f"  食物库存：{', '.join(food_names)}")

    return "\n".join(parts)
