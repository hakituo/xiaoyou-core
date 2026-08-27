
from core.utils.logger import get_logger
from core.agents.chat_agent_components.persona_system import (
    get_dynamic_system_prompt as _get_dynamic_system_prompt,
    determine_mode as _determine_mode,
)

# Re-exporting functions to maintain backward compatibility
get_dynamic_system_prompt = _get_dynamic_system_prompt
determine_mode = _determine_mode

logger = get_logger("ChatAgent")

# Ideally we should deprecate this file and point users to persona_system
# But for now we keep it as a proxy.
