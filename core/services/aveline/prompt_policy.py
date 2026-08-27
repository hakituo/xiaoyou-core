from typing import Any, Optional


def build_stream_system_prompt(
    service: Any, system_prompt: Optional[str], length_preference: Optional[str]
) -> Optional[str]:
    dynamic_context = service._get_dynamic_context()
    merged_prompt = system_prompt
    if dynamic_context:
        if merged_prompt:
            merged_prompt = f"{merged_prompt}\n\n{dynamic_context}"
        else:
            merged_prompt = dynamic_context
    return _apply_length_instruction(service.character_config, merged_prompt, length_preference)


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
