import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.agents.chat_agent_components.persona_system.prompt.dialogue_examples import (
    has_real_chat_corpus,
    select_real_chat_examples,
)


@dataclass
class PeerPromptResult:
    """peer chat prompt 的 static/dynamic 分离结果（缓存优化）

    system_prompt: 静态部分（角色设定/规则/示例），跨请求稳定，命中 DeepSeek Prompt Caching
    user_prompt:   动态部分（时间/状态/话题/历史），每次请求变化
    """
    system_prompt: str
    user_prompt: str


# ---- 静态模板（核心规则 + 正反例 + 输出格式，从数据文件读取，避免硬编码）----
_SCRIPT_TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "peer_chat_script_system.txt")
_SCRIPT_TEMPLATE_CACHE: Optional[str] = None


def _load_script_system_template() -> str:
    """读取互聊剧本的静态 system prompt 模板（进程内缓存一次）"""
    global _SCRIPT_TEMPLATE_CACHE
    if _SCRIPT_TEMPLATE_CACHE is None:
        with open(_SCRIPT_TEMPLATE_PATH, encoding="utf-8") as _f:
            _SCRIPT_TEMPLATE_CACHE = _f.read()
    return _SCRIPT_TEMPLATE_CACHE


# ============================================================
# 双角色互聊 Prompt 系统
# 核心思路：让 AI 之间的对话像真人室友一样自然、有连贯性
# ============================================================


# ---- 决策 Prompt ----

def build_peer_chat_decision_prompt(
    *,
    role_name: str,
    peer_name: str,
    time_str: str,
    energy: float,
    mood: str,
    elapsed_seconds: int,
    recent_topics: List[str],
    social_events_hint: str,
    bio_state: Dict[str, Any],
) -> PeerPromptResult:
    """构建双角色互聊决策 prompt（static/dynamic 分离，缓存优化）

    关键改进：不只决定"聊不聊"，还要输出具体的"情境"和"开场白思路"，
    让后续剧本生成有真实的对话起点。

    返回 PeerPromptResult:
      - system_prompt: 角色设定 + 决策规则 + 输出格式（跨请求稳定，命中缓存）
      - user_prompt:   当前时间/状态/话题/社交事件（每次变化）
    """
    # ========== 静态部分 (system message) ==========
    # 角色设定 + 规则 + 输出格式：对于同一角色对，这些跨请求完全不变
    system_parts = []
    system_parts.append(f"你是{role_name}，和{peer_name}住在一起。")
    system_parts.append("""
决策规则:
- 凌晨0-7点: 不打扰
- 精力<20: 太累了
- 刚聊过(<10分钟): 等一等
- 最近生活事件只是可选话题，不是触发即必聊；像真实室友一样判断现在说是否自然
- 两人住在一起，可以直接知道部分日常，也可以选择互相转告；必须尊重事件里标注的来源
- 若事件写着“Aveline 转告”或“Ling转告”，只能按这个来源表达，不得伪装成自己亲眼看到
- “用户自述现在清醒”只代表退出低打扰，不能说成 Samsung Health 已确认正式起床

⚠️ 关键：如果你决定聊天，必须想清楚"为什么现在想聊"和"具体想说什么"。
不要给一个泛泛的话题如"日常"，要给一个具体的情境，比如：
- "刚才看到她在看手机，想问问她在看什么"
- "今天她好像心情不太好，想关心一下"
- "刚收到的快递她可能感兴趣"

输出JSON:
{
  "thought": "你的内心想法（为什么想聊/不想聊）",
  "should_send": true/false,
  "situation": "具体情境描述（为什么现在想找她聊）",
  "opening_idea": "你想怎么开场（不是完整台词，是思路）",
  "topic": "话题关键词"
}""")

    # ========== 动态部分 (user message) ==========
    # 当前时间、状态、社交事件等：每次请求都不同
    life_context = _build_life_context(bio_state, time_str)
    recent_topics_str = "、".join(recent_topics[-5:]) if recent_topics else "无"

    user_parts = []
    user_parts.append("【双角色互聊决策】")
    user_parts.append(f"当前时间: {time_str}")
    user_parts.append(f"你的状态: 精力={energy:.0f}/100, 心情={mood}")

    if life_context:
        user_parts.append(f"\n当前生活情境:\n{life_context}")

    user_parts.append(f"距上次互聊: {_format_elapsed(elapsed_seconds)}")
    user_parts.append(f"最近聊过的话题: {recent_topics_str}")

    if social_events_hint:
        user_parts.append(f"\n最近发生的事:\n{social_events_hint}")

    return PeerPromptResult(
        system_prompt="\n".join(system_parts),
        user_prompt="\n".join(user_parts),
    )


# ---- 剧本生成 Prompt ----

def build_script_generation_prompt(
    *,
    role_name: str,
    peer_name: str,
    role_id: str,
    peer_role_id: str,
    topic: str,
    situation: str,
    opening_idea: str,
    recent_master_history: str,
    recent_peer_scripts: str,
    time_str: str,
    bio_state: Optional[Dict[str, Any]] = None,
    peer_bio_state: Optional[Dict[str, Any]] = None,
) -> PeerPromptResult:
    """构建剧本生成的 prompt（static/dynamic 分离，缓存优化）

    关键改进：
    1. 注入具体情境和开场思路，不是泛泛的"话题"
    2. 注入双方当前状态（在做什么、心情如何）
    3. 上次互聊的结尾，确保连贯性
    4. 多组正反例，让 LLM 理解什么是自然的对话

    返回 PeerPromptResult:
      - system_prompt: 角色性格 + 核心规则 + 正反例 + 输出格式（跨请求稳定，命中缓存）
      - user_prompt:   当前时间/状态/话题/历史（每次变化）
    """
    from core.services.dual_role.personas import get_peer_profiles

    profiles = get_peer_profiles()
    my_profile = profiles.get(role_id, {})
    peer_profile = profiles.get(peer_role_id, {})

    # ========== 静态部分 (system message) ==========
    # 角色性格 + 核心规则 + 正反例 + 输出格式：跨请求稳定，命中 DeepSeek Prompt Caching
    sys_parts = []

    # ---- 基础设定 + 角色性格 + 关系（性格/关系文案均数据驱动，不走硬编码）----
    sys_parts.append(f"场景：{role_name}和{peer_name}住在一起。")

    if my_profile:
        sys_parts.append(f"\n{role_name}的性格：{my_profile.get('personality', '')}")
        sys_parts.append(f"{role_name}的说话风格：{my_profile.get('speaking_style', '')}")
    if peer_profile:
        sys_parts.append(f"\n{peer_name}的性格：{peer_profile.get('personality', '')}")
        sys_parts.append(f"{peer_name}的说话风格：{peer_profile.get('speaking_style', '')}")
        rel = peer_profile.get('relationship_to_peer', '')
        if rel:
            sys_parts.append(f"你们的关系：{rel}")

    # ---- 正反例 + 核心规则 + 输出格式：从模板文件渲染，角色行为指导数据驱动 ----
    guidance_lines = []
    role_guidance = (my_profile or {}).get('peer_chat_guidance', '')
    peer_guidance = (peer_profile or {}).get('peer_chat_guidance', '')
    if role_guidance:
        guidance_lines.append(f"   - {role_name}：{role_guidance}")
    if peer_guidance:
        guidance_lines.append(f"   - {peer_name}：{peer_guidance}")
    sys_parts.append(
        _load_script_system_template()
        .replace("__ROLE_ID__", role_id)
        .replace("__PEER_ROLE_ID__", peer_role_id)
        .replace("__PEER_NAME__", peer_name)
        .replace("__ROLE_GUIDANCE__", "\n".join(guidance_lines) or "   - 说人话，句句有内容")
    )

    # ========== 动态部分 (user message) ==========
    # 当前时间、状态、话题、历史：每次请求都不同
    user_parts = []
    user_parts.append("【双角色互聊剧本生成】")
    user_parts.append(f"当前时间: {time_str}")

    # ---- 当前状态（这是自然对话的关键）----
    life_context = _build_life_context(bio_state, time_str)
    peer_life_context = _build_life_context(peer_bio_state, time_str)
    if life_context:
        user_parts.append(f"\n{role_name}当前状态: {life_context}")
    if peer_life_context:
        user_parts.append(f"{peer_name}当前状态: {peer_life_context}")

    # ---- 具体情境（从决策阶段传入）----
    if situation:
        user_parts.append(f"\n💬 这次聊天的情境: {situation}")
    if opening_idea:
        user_parts.append(f"开场思路: {opening_idea}")
    if topic:
        user_parts.append(f"话题方向: {topic}")

    # 从真实聊天样本检索风格参考（数据驱动：哪个角色配置了真实语料就注哪边）。
    # 只放动态 user prompt，避免把随话题变化的内容混入可缓存的静态 system prompt。
    query = " ".join(
        part for part in (topic, situation, opening_idea) if str(part or "").strip()
    )
    if query:
        for _rid, _name in ((role_id, role_name), (peer_role_id, peer_name)):
            if has_real_chat_corpus(_name):
                try:
                    ling_examples = select_real_chat_examples(
                        query,
                        persona_name=_name,
                        top_k=2,
                        use_bert=False,
                    )
                except Exception:
                    ling_examples = []
                if ling_examples:
                    user_parts.append(
                        f"\n【{_name}真实聊天风格参考】\n"
                        + "\n\n".join(ling_examples)
                        + f"\n只学习{_name}的接话方式、长短和用词；样本事实不是当前事实，禁止照抄。"
                    )

    # ---- 上次互聊的结尾（确保连贯性）----
    if recent_peer_scripts:
        last_lines = _extract_last_few_lines(recent_peer_scripts, max_lines=6)
        if last_lines:
            user_parts.append(f"\n上次互聊的结尾:\n{last_lines}")
            user_parts.append("⚠️ 要么接续上次的话题自然延续，要么开启一个完全不同的话题。不要假装上次没聊过。")

    # ---- 和主人的最近互动（提供生活素材）----
    if recent_master_history:
        user_parts.append("\n双方最近和主人Master的互动（优先挑一个具体、有趣且适合分享的点；没有合适素材再聊别的）:")
        user_parts.append(recent_master_history)

    return PeerPromptResult(
        system_prompt="\n".join(sys_parts),
        user_prompt="\n".join(user_parts),
    )


# ---- 辅助函数 ----

def _build_life_context(bio_state: Optional[Dict[str, Any]], time_str: str) -> str:
    """从生理状态构建生活情境描述"""
    if not bio_state:
        return ""
    parts = []
    life = bio_state.get("life", {}) if isinstance(bio_state, dict) else {}
    if not life:
        return ""

    energy = life.get("energy")
    if energy is not None:
        try:
            e = float(energy)
            if e < 20:
                parts.append("很累")
            elif e < 50:
                parts.append("有点疲惫")
            elif e > 80:
                parts.append("精力充沛")
        except (ValueError, TypeError):
            pass

    mood = life.get("mood", "")
    if mood and str(mood) not in ("neutral", "normal", ""):
        parts.append(f"心情{mood}")

    hunger = life.get("hunger")
    if hunger is not None:
        try:
            h = float(hunger)
            # hunger 值越高表示越饱（100=完全饱，0=完全饿）
            if h < 30:
                parts.append("很饿")
            elif h < 60:
                parts.append("有点饿了")
        except (ValueError, TypeError):
            pass

    activity = life.get("current_activity", "")
    if activity:
        parts.append(f"正在{activity}")

    is_sick = bio_state.get("is_sick", False) if isinstance(bio_state, dict) else False
    if is_sick:
        parts.append("身体不舒服")

    return "，".join(parts) if parts else ""


def _format_elapsed(seconds: int) -> str:
    """格式化时间间隔"""
    if seconds < 60:
        return f"{seconds}秒"
    if seconds < 3600:
        return f"{seconds // 60}分钟"
    if seconds < 86400:
        return f"{seconds // 3600}小时"
    return f"{seconds // 86400}天"


def _extract_last_few_lines(peer_scripts_text: str, max_lines: int = 6) -> str:
    """从互聊历史文本中提取最后几行"""
    if not peer_scripts_text:
        return ""
    lines = [ln for ln in peer_scripts_text.strip().split("\n") if ln.strip()]
    return "\n".join(lines[-max_lines:])


# ---- QQ 双角色私聊上下文（用于实时消息回复，非剧本模式）----

def build_qq_peer_role_context(peer_context: Dict[str, Any]) -> str:
    """构建双角色私聊模式下的角色上下文"""
    if not isinstance(peer_context, dict) or not peer_context:
        return ""

    sender_name = str(peer_context.get("sender_role_name") or "对方角色").strip()
    recipient_name = str(peer_context.get("recipient_role_name") or "你").strip()

    sender_personality = str(peer_context.get("sender_personality") or "").strip()
    sender_speaking_style = str(peer_context.get("sender_speaking_style") or "").strip()
    sender_relationship = str(peer_context.get("sender_relationship") or "").strip()
    recipient_personality = str(peer_context.get("recipient_personality") or "").strip()
    recipient_speaking_style = str(peer_context.get("recipient_speaking_style") or "").strip()
    recent_events = str(peer_context.get("recent_events") or "").strip()

    parts = []
    parts.append("【双角色私聊模式】")
    parts.append(f"你现在不是在跟主人Master聊天，你是在跟你的室友「{sender_name}」私聊。")
    parts.append(f"你当前身份是「{recipient_name}」，{sender_name}不是用户，不要把她当成用户来回应。")

    if sender_personality:
        parts.append(f"\n对方性格：{sender_name}{sender_personality}")
    if sender_speaking_style:
        parts.append(f"对方说话风格：{sender_speaking_style}")
    if sender_relationship:
        parts.append(f"你们的关系：{sender_relationship}")

    if recipient_personality:
        parts.append(f"\n你的性格：你{recipient_personality}")
    if recipient_speaking_style:
        parts.append(f"你的说话风格：{recipient_speaking_style}")

    if recent_events:
        parts.append(f"\n{recent_events}")

    parts.append("\n请自然地跟对方聊天，像真正的室友/姐妹一样。可以接话、问候、聊日常、一起吃饭、互相调侃。不要解释系统机制，不要用对用户的语气。")

    return "\n".join(parts)
