"""
模型路由配置访问层。

配置来源优先级：
1. app.yaml 主入口展开后的 model_routing 节
2. model_config.json（向后兼容回退，仅在 YAML 不可用时使用）

当前推荐把模型配置拆到 `config/yaml/sections/model_routing.yaml`，
由 `config/yaml/app.yaml` 通过 imports 引入。
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("model_config")

# 向后兼容：model_config.json 路径（仅作回退）
_MODEL_CONFIG_FILE = Path(__file__).parent.parent / "model_config.json"
_MODEL_CONFIG_CACHE: Optional[Dict[str, Any]] = None

# app.yaml 路径
_APP_YAML_PATH = Path(__file__).parent / "yaml" / "app.yaml"
_MODEL_ROUTING_YAML_PATH = Path(__file__).parent / "yaml" / "sections" / "model_routing.yaml"
_YAML_MODEL_ROUTING_CACHE: Optional[Dict[str, Any]] = None


def _dump_yaml_block(data: Dict[str, Any], *, indent: int = 0) -> str:
    """将字典渲染为 YAML 文本块。"""
    import yaml

    dumped = yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()
    prefix = " " * indent
    return "\n".join(f"{prefix}{line}" if line else "" for line in dumped.splitlines())


def _get_nested_mapping(config: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = config.get(key, {})
    return value if isinstance(value, dict) else {}


def _render_model_routing_yaml(config: Dict[str, Any]) -> str:
    """渲染带完整中文注释的模型路由 YAML。"""
    lines = [
        "# ============================================================",
        "# 小友 Core 模型路由配置",
        "#",
        "# 本文件只负责“场景 -> 模型路径”的路由决策，不放服务级运行参数。",
        "# 运行时模型参数（本地 GGUF、采样参数、视觉 provider 等）请放到 modeling.yaml。",
        "# 由 config/yaml/app.yaml 通过 imports 自动引入。",
        "#",
        "# 分类原则：",
        "# 1. 只要某个字段表达的是“这个场景该选哪个模型”，就应该放在这里",
        "# 2. 只要某个字段表达的是“模型怎么跑、多大窗口、什么采样参数”，就放 modeling.yaml",
        "# 3. 运行开关、超时、轮询频率、fallback 行为，仍然放各自业务配置里",
        "# ============================================================",
        "",
        "model_routing:",
        "  # ============================================================",
        "  # DeepSeek API Key 分配说明（3 个 key 各司其职）",
        "  # ============================================================",
        "  # default (DEEPSEEK_API_KEY)         → 主对话、核心功能",
        "  # qqbot1  (DEEPSEEK_API_KEY_QQBOT1)  → 角色日程 / 睡眠判定",
        "  # qqbot2  (DEEPSEEK_API_KEY_QQBOT2)  → 辅助功能、压缩、自愈、蒸馏",
        "  # ============================================================",
        "",
        "  # 主对话模型",
        f'  default_chat_model: "{config.get("default_chat_model", "cloud:deepseek:deepseek-v4-flash")}"',
        "  chat_models:",
    ]

    chat_models = _get_nested_mapping(config, "chat_models")
    if chat_models:
        lines.append(_dump_yaml_block(chat_models, indent=4))
    else:
        lines.append("    {}")

    active_care_models = _get_nested_mapping(config, "active_care_models")
    lines.extend(
        [
            "",
            "  # 主动关怀模型（Active Care）",
            "  active_care_models:",
            _dump_yaml_block(active_care_models, indent=4) if active_care_models else "    {}",
            "",
            "  # 日记 / 总结导出模型",
            f'  journal_model: "{config.get("journal_model", "")}"',
            "",
            "  # 回退模型（主模型不可用时使用）",
            "  fallback_models:",
            _dump_yaml_block(_get_nested_mapping(config, "fallback_models"), indent=4),
            "",
            "  # 自愈系统模型",
            "  auto_heal_models:",
            _dump_yaml_block(_get_nested_mapping(config, "auto_heal_models"), indent=4),
            "",
            "  # 视觉理解模型",
            "  vision_models:",
            _dump_yaml_block(_get_nested_mapping(config, "vision_models"), indent=4),
            "",
            "  # 记忆系统辅助模型",
            "  # distillation: 夜间记忆蒸馏 / 历史压缩",
            "  memory_models:",
            _dump_yaml_block(_get_nested_mapping(config, "memory_models"), indent=4),
            "",
            "  # 角色日常系统模型",
            "  # plan_generator: 用于生成每日活动计划",
            "  # sleep_decision: 角色睡眠静默恢复判定",
            "  character_daily_models:",
            _dump_yaml_block(_get_nested_mapping(config, "character_daily_models"), indent=4),
            "",
            "  # 对话辅助模型",
            "  # context_compress: 长历史压缩摘要，避免与主对话争抢配额",
            "  chat_auxiliary_models:",
            _dump_yaml_block(_get_nested_mapping(config, "chat_auxiliary_models"), indent=4),
            "",
            "  # 供应商默认模型（只在外部只给 provider、没给具体 model 时兜底）",
            "  provider_default_models:",
            _dump_yaml_block(_get_nested_mapping(config, "provider_default_models"), indent=4),
            "",
            "  # Web 搜索供应商映射",
            "  # 这里不是 LLM 模型本身，而是“某个 LLM 厂商默认走哪个搜索实现”",
            "  web_search:",
            _dump_yaml_block(_get_nested_mapping(config, "web_search"), indent=4),
            "",
        ]
    )
    return "\n".join(lines)


def _load_model_routing_from_yaml() -> Optional[Dict[str, Any]]:
    """从 app.yaml 主入口加载展开后的 model_routing 节。"""
    global _YAML_MODEL_ROUTING_CACHE
    if _YAML_MODEL_ROUTING_CACHE is not None:
        return _YAML_MODEL_ROUTING_CACHE

    try:
        if not _APP_YAML_PATH.exists():
            return None

        from config.yaml_loader import load_resolved_yaml_config_from_disk

        yaml_config, _, _ = load_resolved_yaml_config_from_disk(_APP_YAML_PATH)

        routing = yaml_config.get("model_routing")
        if isinstance(routing, dict):
            _YAML_MODEL_ROUTING_CACHE = routing
            return routing
    except Exception as e:
        logger.warning(f"从 app.yaml 主入口加载 model_routing 失败: {e}")

    return None


def load_model_config() -> dict:
    """加载模型路由配置

    优先从 app.yaml 的 model_routing 节读取，
    回退到 model_config.json（向后兼容）。
    """
    global _MODEL_CONFIG_CACHE

    if _MODEL_CONFIG_CACHE is not None:
        return _MODEL_CONFIG_CACHE

    # 优先从 app.yaml 读取
    routing = _load_model_routing_from_yaml()
    if routing is not None:
        _MODEL_CONFIG_CACHE = routing
        return _MODEL_CONFIG_CACHE

    # 回退：从 model_config.json 读取（向后兼容）
    if _MODEL_CONFIG_FILE.exists():
        try:
            with open(_MODEL_CONFIG_FILE, "r", encoding="utf-8") as f:
                _MODEL_CONFIG_CACHE = json.load(f)
                logger.info("模型路由配置从 model_config.json 加载（向后兼容模式）")
                return _MODEL_CONFIG_CACHE
        except Exception as e:
            logger.error(f"加载 model_config.json 失败: {e}")

    logger.warning("未找到模型路由配置（app.yaml model_routing 和 model_config.json 均不可用）")
    return {}


def reload_model_config() -> dict:
    """重新加载模型路由配置（清空缓存后重新读取）"""
    global _MODEL_CONFIG_CACHE, _YAML_MODEL_ROUTING_CACHE
    _MODEL_CONFIG_CACHE = None
    _YAML_MODEL_ROUTING_CACHE = None
    return load_model_config()


def save_model_routing_to_yaml(config: Dict[str, Any]) -> bool:
    """将模型路由配置写回独立 YAML 文件。

    Args:
        config: 完整的 model_routing 配置字典

    Returns:
        bool: 是否写入成功
    """
    global _YAML_MODEL_ROUTING_CACHE, _MODEL_CONFIG_CACHE

    try:
        _MODEL_ROUTING_YAML_PATH.parent.mkdir(parents=True, exist_ok=True)
        _MODEL_ROUTING_YAML_PATH.write_text(
            _render_model_routing_yaml(config),
            encoding="utf-8",
        )

        # 更新缓存
        _YAML_MODEL_ROUTING_CACHE = config
        _MODEL_CONFIG_CACHE = config

        logger.info(f"模型路由配置已写回 {_MODEL_ROUTING_YAML_PATH}")
        return True
    except Exception as e:
        logger.error(f"写回模型路由 YAML 失败: {e}")
        return False


def _normalize_persona_key(persona_name: str) -> str:
    name = str(persona_name).strip().lower()
    if "七濑" in name or "澪" in name or "aveline" in name:
        return "aveline"
    if "Ling" in name or "ling" in name:
        return "ling"
    return name


def get_default_chat_model(default: str = "cloud:deepseek:deepseek-v4-flash") -> str:
    config = load_model_config()
    return config.get("default_chat_model", default)


def get_chat_model(persona_name: str, default: str = "") -> str:
    config = load_model_config()
    chat_models = config.get("chat_models", {})
    return chat_models.get(_normalize_persona_key(persona_name), default)


def get_active_care_content_model(persona_name: str, default: str = "") -> str:
    config = load_model_config()
    ac_models = config.get("active_care_models", {})
    content_models = ac_models.get("content_generation", {})
    return content_models.get(_normalize_persona_key(persona_name), content_models.get("default", default))


def get_active_care_decision_model(default: str = "") -> str:
    config = load_model_config()
    ac_models = config.get("active_care_models", {})
    return ac_models.get("decision", default)


def get_auto_eat_model(default: str = "") -> str:
    config = load_model_config()
    ac_models = config.get("active_care_models", {})
    return ac_models.get("auto_eat", default)


def get_journal_model(default: str = "") -> str:
    config = load_model_config()
    return config.get("journal_model", default)


def get_priority_analysis_model(default: str = "") -> str:
    config = load_model_config()
    ac_models = config.get("active_care_models", {})
    return ac_models.get("priority_analysis", default)


def get_vision_model(default: str = "") -> str:
    config = load_model_config()
    vision_models = config.get("vision_models", {})
    model = vision_models.get("default", default)
    if model.startswith("cloud:"):
        parts = model.split(":", 2)
        if len(parts) >= 3:
            model = parts[2]
    return model


def get_fallback_model_for_active_care(default: str = "") -> str:
    config = load_model_config()
    return config.get("fallback_models", {}).get("active_care", default)


def get_auto_heal_model(model_type: str = "analysis", default: str = "") -> str:
    config = load_model_config()
    ah_models = config.get("auto_heal_models", {})
    return ah_models.get(model_type, default)


def get_provider_default_model(provider: str, default: str = "") -> str:
    config = load_model_config()
    provider_defaults = config.get("provider_default_models", {})
    return provider_defaults.get(provider, default)


def get_character_daily_plan_model(default: str = "") -> str:
    config = load_model_config()
    cd_models = config.get("character_daily_models", {})
    return cd_models.get("plan_generator", default)


def get_character_daily_sleep_decision_model(default: str = "") -> str:
    config = load_model_config()
    cd_models = config.get("character_daily_models", {})
    return cd_models.get("sleep_decision", default)


def get_chat_context_compress_model(default: str = "") -> str:
    config = load_model_config()
    chat_aux_models = config.get("chat_auxiliary_models", {})
    return chat_aux_models.get("context_compress", default)


def get_web_search_config() -> dict:
    """获取web_search配置"""
    config = load_model_config()
    return config.get("web_search", {
        "enabled": True,
        "default_provider": "serper",
        "providers": {
            "zhipu": {"type": "zhipu_proxy", "model": "glm-4.5-air"},
            "zhipu_native": {"type": "server_side"},
            "bocha": {"type": "client_side", "api_url": "https://api.bochaai.com/v1/web-search", "api_key_env": "BOCHA_API_KEY"},
            "serper": {"type": "client_side", "api_url": "https://google.serper.dev/search", "api_key_env": "SERPER_API_KEY"},
        },
        "provider_mapping": {
            "zhipu": "zhipu_native",
            "deepseek": "serper",
            "siliconflow": "serper",
            "dashscope": "serper",
            "ark": "serper",
            "minimax": "serper",
            "aveline": "serper",
            "openai": "serper",
            "custom": "serper",
        },
    })


def is_web_search_enabled() -> bool:
    """web_search是否全局启用"""
    ws_config = get_web_search_config()
    return ws_config.get("enabled", True)


def get_web_search_provider_for_llm(llm_provider: str) -> str:
    """根据LLM厂商获取对应的web_search provider

    Args:
        llm_provider: LLM厂商名称（如 deepseek, zhipu, siliconflow 等）

    Returns:
        str: web_search provider名称（如 zhipu, bocha）
    """
    ws_config = get_web_search_config()
    mapping = ws_config.get("provider_mapping", {})
    return mapping.get(llm_provider, ws_config.get("default_provider", "serper"))


def get_web_search_type(provider_name: str) -> str:
    """获取指定web_search provider的搜索类型

    Args:
        provider_name: web_search provider名称

    Returns:
        str: "server_side"（服务端搜索）或 "client_side"（客户端搜索）
    """
    ws_config = get_web_search_config()
    providers = ws_config.get("providers", {})
    provider_cfg = providers.get(provider_name, {})
    return provider_cfg.get("type", "client_side")


def should_use_server_side_web_search(llm_provider: str, model_name: str = "") -> bool:
    """判断当前LLM是否应使用服务端web_search

    服务端搜索条件：
    1. web_search全局启用
    2. 该厂商映射到支持服务端搜索的provider（如zhipu）
    3. 当前模型在服务端搜索支持的模型列表中

    Args:
        llm_provider: LLM厂商名称
        model_name: 当前使用的模型名称

    Returns:
        bool: 是否使用服务端搜索
    """
    if not is_web_search_enabled():
        return False

    ws_provider = get_web_search_provider_for_llm(llm_provider)
    search_type = get_web_search_type(ws_provider)

    if search_type != "server_side":
        return False

    ws_config = get_web_search_config()
    providers = ws_config.get("providers", {})
    provider_cfg = providers.get(ws_provider, {})
    supported_models = provider_cfg.get("models", [])

    if not supported_models:
        return True

    model_lower = (model_name or "").lower()
    for supported in supported_models:
        if supported.lower() in model_lower:
            return True

    return False


def resolve_active_care_model_path(
    *,
    model_hint: str = "",
    model_type: str = "content",
    persona_name: str = "",
    settings=None,
    llm_module=None,
) -> str:
    """
    统一的 Active Care 模型路径解析

    按优先级依次尝试：
    1. 显式传入的 model_hint
    2. app.yaml model_routing 中的专用模型配置
    3. settings.life_simulation.active_care_model_hint
    4. LLM 模块当前模型
    5. 云端/本地 provider 回退

    Args:
        model_hint: 显式模型路径提示
        model_type: "content" (内容生成) 或 "decision" (决策)
        persona_name: 人设名称（仅 content 类型使用）
        settings: 配置对象
        llm_module: LLM 模块实例

    Returns:
        str: 解析后的模型路径
    """
    model_path = str(model_hint or "").strip() or None
    if model_path:
        return model_path

    try:
        if model_type == "decision":
            model_path = get_active_care_decision_model()
        else:
            model_path = get_active_care_content_model(persona_name)
    except Exception:
        model_path = ""

    if model_path:
        return model_path

    if settings is not None:
        try:
            from core.utils.config_accessor import get_active_care_config
            model_path = str(
                get_active_care_config("active_care_model_hint", default="", settings=settings)
                or ""
            ).strip()
            if model_path:
                return model_path
        except Exception:
            pass

    if llm_module is not None and hasattr(llm_module, "get_current_model_name"):
        try:
            model_path = llm_module.get_current_model_name()
            if model_path and model_path != "unknown":
                return model_path
        except Exception:
            pass

    if settings is not None:
        try:
            provider = settings.model.llm.provider
            if provider and provider != "local":
                return f"cloud:{provider}"
            elif settings.model.text_path:
                return settings.model.text_path
        except Exception:
            pass

    return model_path or ""
