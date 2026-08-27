"""
模型路径解析与原生工具准备
从 streaming.py 解耦：人设-模型映射解析、云端/本地模型路径判定、
服务端 web_search 判断、原生 function calling 工具列表准备
"""
from typing import Any, List, Optional, Tuple

from config.debug_config import is_debug_enabled
from core.utils.logger import get_logger

logger = get_logger("ChatAgent")


def resolve_model_by_persona(settings) -> Optional[str]:
    """根据当前人设查找映射的模型，返回 model_hint 或 None"""
    try:
        persona_model_map = getattr(settings.model, "persona_model_map", None)
        if not persona_model_map:
            return None

        from core.character.managers.persona_manager import get_persona_manager
        pm = get_persona_manager()
        current_filename = str(pm.get_current_filename() or "").strip().lower()
        if not current_filename:
            return None

        for persona_key, model_hint in persona_model_map.items():
            key_lower = str(persona_key).strip().lower()
            if key_lower in current_filename:
                return model_hint

        return None
    except Exception as e:
        logger.warning(f"Failed to resolve model by persona: {e}")
        return None


def resolve_model_path(model_hint: Optional[str]) -> Tuple[bool, Optional[str]]:
    """判定本轮对话使用的模型，返回 (is_cloud, model_path)

    优先级：显式 model_hint > 人设映射 > provider 默认模型 > 本地模型路径
    """
    model_path = None
    is_cloud = True
    try:
        from config.integrated_config import get_settings
        from config.model_config import get_default_chat_model
        settings = get_settings()
        provider = settings.model.llm.provider

        if model_hint:
            if model_hint.startswith("cloud:"):
                is_cloud = True
                model_path = model_hint
            else:
                is_cloud = False
                model_path = model_hint
        else:
            persona_model_hint = resolve_model_by_persona(settings)
            if persona_model_hint:
                if persona_model_hint.startswith("cloud:"):
                    is_cloud = True
                    model_path = persona_model_hint
                else:
                    is_cloud = False
                    model_path = persona_model_hint
                logger.info(f"StreamChat: Resolved model by persona: {persona_model_hint}")
            elif provider in ["deepseek", "siliconflow", "dashscope", "openai", "aveline"]:
                is_cloud = True
                default_model = get_default_chat_model()
                if default_model and default_model.startswith("cloud:"):
                    model_path = default_model
                else:
                    model_path = None
            else:
                is_cloud = False
                model_path = settings.model.text_path

        logger.info(f"StreamChat: Using provider={provider}, is_cloud={is_cloud}, model_path={model_path}")
    except Exception as e:
        logger.warning(f"Failed to get model config: {e}")
        is_cloud = True
        model_path = None

    return is_cloud, model_path


def detect_server_side_search(agent: Any) -> bool:
    """判断当前LLM是否使用服务端web_search"""
    use_server_side_search = False
    try:
        from config.model_config import should_use_server_side_web_search, is_web_search_enabled
        if is_web_search_enabled() and hasattr(agent, "llm_module"):
            current_model = agent.llm_module.get_current_model_name()
            current_provider = ""
            if current_model and current_model.startswith("cloud:"):
                parts = current_model.split(":", 2)
                if len(parts) >= 2:
                    current_provider = parts[1]
            model_name = current_model.split(":")[-1] if ":" in current_model else current_model
            use_server_side_search = should_use_server_side_web_search(current_provider, model_name)
            if use_server_side_search:
                logger.info(f"[Web Search] 使用服务端搜索, provider={current_provider}, model={model_name}")
    except Exception as e:
        if is_debug_enabled("streaming"):
            logger.info(f"[Web Search] 服务端搜索判断失败: {e}")
    return use_server_side_search


def prepare_native_tools(
    agent: Any,
    persona_filename: Optional[str],
    is_sensitive_mode: bool,
    use_server_side_search: bool,
    active_tool_names: Optional[List[str]] = None,
) -> Optional[List[dict]]:
    """准备本轮所需的原生 function calling 工具列表。"""
    openai_tools = None
    if hasattr(agent, "tool_registry") and agent.tool_registry:
        from core.tools.tool_visibility import filter_tool_names

        native_tool_names = (
            list(active_tool_names)
            if active_tool_names is not None
            else agent.tool_registry.get_active_tools()
        )
        native_tool_names = filter_tool_names(
            native_tool_names,
            tool_registry=agent.tool_registry,
            persona_filename=persona_filename,
            is_sensitive_mode=is_sensitive_mode,
        )
        # 服务端搜索时，从本地工具列表中移除web_search（避免重复搜索）
        if use_server_side_search:
            native_tool_names = [
                name for name in native_tool_names if name != "web_search"
            ]
        openai_tools = agent.tool_registry.get_openai_tools(
            include_names=native_tool_names
        )
        if openai_tools:
            import json

            schema_chars = len(json.dumps(openai_tools, ensure_ascii=False, separators=(",", ":")))
            logger.info(
                "[Native Tools] Registered %d tools for function calling, schema_chars=%d",
                len(openai_tools),
                schema_chars,
            )
    return openai_tools
