"""
仿生体状态 + 食物系统 + 情绪 + 学习状态组件
"""
from typing import Any, Dict, Optional

from ..context_gathering import build_food_context_text


def build_bionic_state(
    life_stats: Dict[str, Any],
    cpu_temp: Any,
    ram_usage: Any,
    actor_life_states: Optional[Dict[str, Dict[str, Any]]] = None,
    actor_relationships: Optional[Dict[str, float]] = None,
    role_sleep_states: Optional[Dict[str, Dict[str, Any]]] = None,
    current_persona_name: str = "",
) -> str:
    """
    构建仿生体状态组件，包含当前角色状态、室友状态和关系信息

    Args:
        life_stats: 生命模拟状态
        cpu_temp: CPU 温度
        ram_usage: RAM 使用率
        actor_life_states: 所有角色的生命状态
        actor_relationships: 角色间关系值
        current_persona_name: 当前角色名称（如 "七濑 澪" 或 "Ling"）
    """
    try:
        temp = float(cpu_temp or 0.0)
        cpu_i = int(round(max(0.0, (temp - 40.0) * 2.0)))
    except Exception:
        cpu_i = -1
    try:
        ram_i = int(round(float(ram_usage or 0.0)))
    except Exception:
        ram_i = -1

    lowered_name = str(current_persona_name or "").lower()
    is_bionic_role = "澪" in current_persona_name or "aveline" in lowered_name

    parts = []
    if cpu_i >= 0:
        parts.append(f"CPU{cpu_i}%")
    if ram_i >= 0:
        parts.append(f"RAM{ram_i}%")

    result = ""
    if is_bionic_role and parts:
        # 只有仿生体角色才感知硬件状态，其他角色只注入睡眠/关系状态。
        result = "你的硬件状态：" + " ".join(parts)

    # 室友的生理状态不再自动注入 prompt，需要通过 check_peer_status 工具主动查询
    # 只保留关系信息（关系值是角色自己知道的）
    sibling_block = _build_sibling_relationship_context(
        actor_relationships, current_persona_name
    )
    if sibling_block:
        result = f"{result}{sibling_block}" if result else sibling_block.lstrip("\n")

    sleep_block = _build_sleep_context(role_sleep_states, current_persona_name)
    if sleep_block:
        result = f"{result}{sleep_block}" if result else sleep_block.lstrip("\n")

    return result


def _build_sibling_relationship_context(
    actor_relationships: Optional[Dict[str, float]],
    current_persona_name: str,
) -> str:
    """构建室友关系上下文（不含生理状态，生理状态需通过 check_peer_status 工具查询）"""
    # 室友关系精简：去掉【】标题，只保留关键信息
    if not actor_relationships:
        return ""

    is_aveline = "澪" in current_persona_name or "aveline" in current_persona_name.lower()
    sibling_name = "Ling" if is_aveline else "澪姐"

    rel_key = "aveline|ling"
    try:
        rel_value = float(actor_relationships.get(rel_key) or 0.0)
    except Exception:
        rel_value = 0.0

    if rel_value >= 80:
        rel_label = "亲密无间"
    elif rel_value >= 60:
        rel_label = "非常要好"
    elif rel_value >= 40:
        rel_label = "关系不错"
    elif rel_value >= 20:
        rel_label = "逐渐熟悉"
    else:
        rel_label = "刚开始认识"

    return f"\n和{sibling_name}的关系：{rel_label}"


def _build_sleep_context(
    role_sleep_states: Optional[Dict[str, Dict[str, Any]]],
    current_persona_name: str,
) -> str:
    """构建睡眠状态上下文。"""
    if not role_sleep_states:
        return ""

    lowered_name = str(current_persona_name or "").lower()
    role_id = "ling" if "Ling" in current_persona_name or "ling" in lowered_name else "aveline"
    summary = role_sleep_states.get(role_id) or {}
    if not summary:
        return ""

    lines = []
    phase = str(summary.get("phase") or "").strip().lower()
    phase_label_map = {
        "sleeping": "正在睡觉",
        "night_awake": "半夜被叫醒后还醒着",
        "waking_up": "刚起床没多久",
        "fully_awake": "已经清醒",
        "sleep_later": "半夜还醒着，打算过会儿再睡",
        "stay_up_late": "今晚已经熬夜了",
    }
    if phase:
        lines.append(f"当前睡眠状态：{phase_label_map.get(phase, phase)}")
    if phase == "night_awake":
        lines.append("你是从睡梦里被拉起来的状态，回复要带点困意和迷糊感，不要像白天那样太利落")
    elif phase == "sleep_later":
        lines.append("现在本来已经该睡了，回复里可以自然提一句自己等会儿还要去睡")
    elif phase == "waking_up":
        lines.append("现在是刚醒后的缓冲期，说话还没完全进入白天状态")
    if summary.get("sleep_debt_hours", 0) or summary.get("sleep_debt", 0):
        debt = float(
            summary.get("sleep_debt_hours", summary.get("sleep_debt", 0.0)) or 0.0
        )
        if debt >= 0.3:
            lines.append(f"睡眠债约 {debt:.1f} 小时")
    inertia = float(summary.get("sleep_inertia_score", 0.0) or 0.0)
    if inertia >= 15:
        lines.append(f"睡眠惯性偏强（{inertia:.0f}/100）")
    nightmare = str(summary.get("nightmare_level") or "none")
    if nightmare != "none":
        lines.append(f"昨夜睡眠质量受影响：{nightmare}")
    impact = str(summary.get("impact_level") or "none")
    if impact != "none":
        lines.append(f"今日精神状态影响等级：{impact}")
    if not lines:
        return ""
    return "\n睡眠状态：" + "；".join(lines)


def build_food_context(
    life_stats: Dict[str, Any],
) -> str:
    """
    构建食物系统上下文组件

    Args:
        life_stats: 生命模拟状态

    Returns:
        食物上下文字符串
    """
    return build_food_context_text(life_stats)


def build_emotion_context(
    emotion_primary: str,
    emotion_intensity: int,
    emotion_confidence: int,
    emotion_sub_json: str,
) -> str:
    """
    构建情绪上下文组件

    Args:
        emotion_primary: 主情绪
        emotion_intensity: 情绪强度
        emotion_confidence: 置信度
        emotion_sub_json: 次要情绪 JSON

    Returns:
        情绪上下文字符串
    """
    if emotion_primary == "neutral" or emotion_intensity < 10:
        return ""

    from core.emotion.constants import EMOTION_CN_MAP, EMOTION_BEHAVIOR_HINTS

    cn_name = EMOTION_CN_MAP.get(emotion_primary, emotion_primary)
    behavior_hint = EMOTION_BEHAVIOR_HINTS.get(emotion_primary, "")

    # 精简版：只给一句话描述，不给结构化数据
    hint = f"，{behavior_hint}" if behavior_hint else ""
    return f"\n情绪：{cn_name}{hint}"


def build_study_context(
    is_study_mode: bool = False,
) -> str:
    # 学习画像已改为工具（get_study_profile），AI 需要时自行调用
    # 背单词实时状态也暂时注释，后续可改为工具按需查询
    return ""
