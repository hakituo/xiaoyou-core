from typing import Any, Optional


def build_stream_system_prompt(
    service: Any, system_prompt: Optional[str], length_preference: Optional[str]
) -> Optional[str]:
    """流式聊天路径的 system prompt 加工：只施加长度约束。

    2026-10-01 去重：原先这里还会拼上 ``service._get_dynamic_context()``
    （【时间锚点】+ 用户状态 +【用户今日画像】），但那三样在 assembler 链路上
    已经有了——时间落在 user 消息前缀的「当前时间：」一行（连同防幻觉守卫句），
    用户状态/画像/睡眠锚点由 ``components/user_bio.py`` 注入。
    走 streaming 时 ``system_prompt`` 为 None，本函数的产物会整段变成
    ``service_extra_dynamic_context`` 落进 extra_dynamic_context，
    于是同一份事实在 prompt 里出现两遍（实测重复 259 字，用户睡眠行 ×4）。

    动态上下文现在统一交给 assembler，这里只保留长度约束。
    复核脚本：.workbuddy-ai/prompts/check_prompt_duplicates.py
    """
    return _apply_length_instruction(
        service.character_config, system_prompt, length_preference
    )


def build_generation_system_prompt(
    service: Any, system_prompt: Optional[str], length_preference: Optional[str]
) -> Optional[str]:
    return _apply_length_instruction(service.character_config, system_prompt, length_preference)


def _apply_length_instruction(
    character_config: Any, system_prompt: Optional[str], length_preference: Optional[str]
) -> Optional[str]:
    effective_len_pref = str(length_preference or "normal").lower()
    if _is_study_persona(character_config):
        effective_len_pref = "long"

    length_instruction = ""
    if effective_len_pref == "short":
        length_instruction = "\n(Constraint: Keep your response very concise, within 70 tokens.)"
    elif effective_len_pref == "normal":
        length_instruction = "\n(Constraint: Keep your response normal length, within 200 tokens.)"

    final_system_prompt = system_prompt
    if length_instruction:
        final_system_prompt = (final_system_prompt or "") + length_instruction
    return final_system_prompt


def _is_study_persona(character_config: Any) -> bool:
    try:
        if character_config and "study" in str(character_config.get("filename", "")).lower():
            return True
        from core.character.managers.persona_manager import get_persona_manager

        pm = get_persona_manager()
        return bool(pm.current_persona_file and "study" in pm.current_persona_file.lower())
    except Exception:
        return False
