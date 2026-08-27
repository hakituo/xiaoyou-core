from typing import Any, Dict, Optional

from core.utils.logger import get_logger

logger = get_logger("ModeControl")

def determine_mode(agent: Any, message: str = "") -> str:
    if message and agent._is_study_mode(message):
        return "study"
    return "chat"

def get_contrastive_prompting_injection(persona: Dict[str, Any]) -> str:
    """从人设配置中提取并生成对比示例 (Bad vs Good) 的注入内容"""
    if not isinstance(persona, dict):
        return ""
    
    cp = persona.get("contrastive_prompting")
    if not isinstance(cp, dict) or not cp.get("enabled", True):
        return ""
    
    examples = cp.get("examples")
    if not isinstance(examples, list) or not examples:
        return ""
    
    injection = "\n\n【对话风格参考 (Contrastive Prompting)】\n"
    injection += "要求：严格避免 Bad 示例中的行为，模仿 Good 示例中的语气与逻辑：\n"
    
    for idx, ex in enumerate(examples[:5]):
        bad = ex.get("bad", "")
        good = ex.get("good", "")
        reason = ex.get("reason", "")
        
        if bad and good:
            injection += f"\n例 {idx+1}:\n"
            injection += f"- Bad: \"{bad}\"\n"
            injection += f"- Good: \"{good}\"\n"
            if reason:
                injection += f"- 理由: {reason}\n"
    
    return injection

def load_kaomoji_examples(limit: int = 10) -> str:
    """[已废弃] 从本地库加载一些颜文字示例"""
    return ""

def check_sensitive_mode(agent: Any, user_id: str, message: str, current_persona_filename: str) -> bool:
    """检查是否处于敏感模式"""
    fn_lower = current_persona_filename.replace("\\", "/").lower()
    is_sensitive_persona_selected = "/sensitive/" in fn_lower
    
    if is_sensitive_persona_selected:
        return True

    def _is_sensitive_enabled_for(agent_obj: Any, cid: Optional[str]) -> bool:
        c = str(cid or "").strip()
        if not c:
            c = "default"
        try:
            mm = agent_obj._get_memory_manager(c)
            if hasattr(mm, "get_memories_by_topic"):
                mode_memories = mm.get_memories_by_topic("sensitive_mode_control", limit=1)
                if mode_memories and "SENSITIVE_MODE_ON" in str(mode_memories[0].get("content", "") or ""):
                    return True
        except Exception:
            return False
        return False

    if _is_sensitive_enabled_for(agent, user_id):
        return True

    if message:
        msg_lower = str(message).lower()
        if "/sensitive" in msg_lower or "[sensitive]" in msg_lower or "开启sensitive" in msg_lower or "/nsfw" in msg_lower or "[nsfw]" in msg_lower:
            logger.info("Sensitive mode triggered by current message command")
            return True
            
    return False

def get_style_guard(
    mode: str,
    is_sensitive_mode: bool,
    is_qq_source: bool,
    wants_long: bool,
    kaomoji_examples: str,
    emotion_intensity: int
) -> str:
    """
    风格约束生成器
    大部分风格定义已移至 core_aveline.json 等配置文件中。
    此处仅保留平台特定的格式硬约束（如 QQ 的表情/分段规则）。
    """
    style_guard = ""
    
    if is_qq_source:
        style_guard = (
            "\n\n【QQ 平台格式约束】\n"
            "- 只输出对话正文\n"
            "- 表情可用 [表情名] 或小黄脸；\n"
        )
    return style_guard

def get_natural_dialogue_policy(
    mode: str,
    is_sensitive_mode: bool,
    is_qq_source: bool,
    wants_long: bool,
    emotion_intensity: int
) -> str:
    """
    自然对话策略生成器
    仅保留学习模式下的特定约束，其他通用策略已移交配置文件 (core_aveline.json)。
    """
    natural_dialogue_policy_injection = ""
    
    if mode == "study" and (not is_sensitive_mode):
        natural_dialogue_policy_injection = (
            "\n\n【学习模式交互规范】\n"
            "- 学习场景允许步骤与列表，但优先用对话方式带着走：先复述你理解的卡点，再给下一步。\n"
            "- 每轮至少做 1 个对话动作：复述确认 / 追问 1 个关键点 / 给 2 个选项让用户选。\n"
            "- 信息不够时先问 1 个关键问题，不要连环追问；能给最小可执行的一步就先给。\n"
        )
        return natural_dialogue_policy_injection

    return ""
