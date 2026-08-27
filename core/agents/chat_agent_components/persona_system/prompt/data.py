"""
Prompt 数据获取和准备

所有 prompt 相关的数据获取、处理逻辑都放在这里
"""
import os
import json
import time
from typing import Any, Dict, Optional, Tuple
from datetime import datetime

from core.utils.logger import get_logger
from core.character.managers.persona_manager import get_persona_manager
from core.character.aveline import get_aveline_system_prompt_template

from .user_identification import resolve_user_name, resolve_user_name_from_persona_logic
from .qq_integration import apply_qq_optimizations
from .mode_control import determine_mode, check_sensitive_mode
from .context_gathering import (
    get_context_injection,
    prepare_emotion_context,
    prepare_life_stats,
    determine_model_info,
)

logger = get_logger("PromptData")

# 缓存
_expanded_persona_cache: Dict[str, str] = {}
_static_base_cache: Dict[str, str] = {}
_bionic_state_cache: Dict[str, Any] = None


def clear_persona_cache():
    """清除人设模板缓存（人设切换时调用）"""
    global _expanded_persona_cache, _static_base_cache, _bionic_state_cache
    _expanded_persona_cache = {}
    _static_base_cache = {}
    _bionic_state_cache = None


class PromptData:
    """
    Prompt 数据容器
    """
    def __init__(self):
        # 基础信息
        self.agent: Optional[Any] = None
        self.user_id: str = "default"
        self.message: Optional[str] = None
        self.user_name: Optional[str] = None
        
        # 模式和人设
        self.mode: str = "chat"
        self.persona_filename: str = ""
        self.persona_name: str = "Ling"
        self.persona_data: Dict[str, Any] = {}
        
        # 用户相关
        self.resolved_user_name: str = "Master"
        self.is_qq_source: bool = False
        self.is_sensitive_mode: bool = False
        
        # 模型相关
        self.model_name: str = ""
        self.is_cloud_model: bool = True
        self.is_local_gguf: bool = False
        self.prompt_budget: Optional[int] = None
        
        # 上下文数据
        self.ctx_data: Dict[str, Any] = {}
        self.emotion_data: Tuple = ("neutral", 0, 0, "")
        self.life_stats: Dict[str, Any] = {}
        self.immune_stats: Dict[str, Any] = {}
        self.bio_stats: Dict[str, Any] = {}
        self.cpu_temp: float = 45
        self.ram_usage: float = 50
        self.last_conversation_seconds: Optional[int] = None
        
        # 模板
        self.base_template: str = ""
        self.dialogue_injection: str = ""


def get_prompt_data(
    agent: Any,
    user_id: Optional[str] = None,
    message: Optional[str] = None,
    user_name: Optional[str] = None,
    memory_manager: Any = None,
    _is_sensitive_mode: Optional[bool] = None,
    persona_filename: Optional[str] = None,
) -> PromptData:
    """
    获取并准备所有 prompt 相关的数据

    Args:
        agent: ChatAgent 实例
        user_id: 用户 ID
        message: 用户消息
        user_name: 用户名称
        memory_manager: 可选的已有 WeightedMemoryManager 实例，避免重复创建
        _is_sensitive_mode: 可选，如果已在外层计算好则直接使用，避免重复调用 check_sensitive_mode
        persona_filename: 可选，外部指定人设文件名（用于双QQ等per-connection人设场景），
                          优先级高于全局 PersonaManager 的当前人设

    Returns:
        填充好的 PromptData 对象
    """
    t_total = time.perf_counter()
    t_last = t_total
    timings: Dict[str, float] = {}

    data = PromptData()
    data.agent = agent
    data.user_id = str(user_id or "").strip() or "default"
    data.message = message
    data.user_name = user_name
    
    # 1. 确定模式
    data.mode = determine_mode(agent, message or "")
    
    # 2. 解析用户名
    data.resolved_user_name = user_name
    if not data.resolved_user_name:
        data.resolved_user_name = resolve_user_name(agent, data.user_id, user_name)
    
    if data.resolved_user_name == "你" and not user_name:
        persona_name = resolve_user_name_from_persona_logic()
        if persona_name:
            data.resolved_user_name = persona_name
    
    t_now = time.perf_counter()
    timings["user_resolve"] = t_now - t_last
    t_last = t_now

    # 3. 获取人设信息（外部指定优先于全局 PersonaManager）
    try:
        if persona_filename:
            data.persona_filename = str(persona_filename).strip()
            logger.info(f"[get_prompt_data] 使用外部传入的 persona_filename={data.persona_filename!r}")
        else:
            pm = get_persona_manager()
            data.persona_filename = str(pm.get_current_filename() or "")
            logger.info(f"[get_prompt_data] 外部未传入 persona_filename，使用全局 PersonaManager={data.persona_filename!r}")
        data.persona_name = get_persona_name_from_filename(data.persona_filename)
    except Exception:
        pass

    try:
        _, data.persona_data = get_template_data(persona_filename=data.persona_filename)
    except Exception:
        data.persona_data = {}
    
    # 4. 是否是 QQ 来源
    uid_lower = data.user_id.strip().lower()
    data.is_qq_source = bool(
        uid_lower.startswith("group_")
        or uid_lower.startswith("private_")
        or uid_lower.startswith("qq_")
        or uid_lower == "default_user"
    )
    
    # 5. 检查敏感模式（如果外层已计算好则复用）
    if _is_sensitive_mode is not None:
        data.is_sensitive_mode = _is_sensitive_mode
    else:
        data.is_sensitive_mode = check_sensitive_mode(
            agent, user_id, message, data.persona_filename
        )
    
    # 6. 确定模型信息
    data.model_name, data.is_cloud_model, data.is_local_gguf, data.prompt_budget = \
        determine_model_info(agent)
    
    t_now = time.perf_counter()
    timings["model_info"] = t_now - t_last
    t_last = t_now

    # 7. 获取上下文数据（传入 memory_manager 避免重复创建）
    data.ctx_data = get_context_injection(data.user_id, memory_manager=memory_manager)
    data.user_physiology_context = data.ctx_data.get("user_physiology", "")
    data.life_sim_state = data.ctx_data.get("life_sim_state", {})
    data.cpu_temp = data.ctx_data.get("cpu_temp", 45)
    data.ram_usage = data.ctx_data.get("ram_usage", 50)
    data.last_conversation_seconds = data.ctx_data.get("last_conversation_seconds")
    
    # 8. 准备情绪和生命状态
    data.emotion_data = prepare_emotion_context(data.ctx_data)
    data.life_stats, data.immune_stats, data.bio_stats = \
        prepare_life_stats(data.life_sim_state)
    
    t_now = time.perf_counter()
    timings["context_gather"] = t_now - t_last
    t_last = t_now

    # 9. 获取基础模板
    data.base_template = get_base_template(
        agent=agent,
        mode=data.mode,
        user_id=user_id,
        user_name=data.resolved_user_name,
        persona_filename=data.persona_filename,
    )
    
    # 10. 应用 QQ 优化
    data.base_template = apply_qq_optimizations(
        data.base_template, user_id, data.persona_filename
    )
    
    t_now = time.perf_counter()
    timings["template"] = t_now - t_last
    t_last = t_now

    # 11. 获取对话示例
    if data.persona_name:
        from .dialogue_examples import get_dialogue_examples
        data.dialogue_injection = get_dialogue_examples(
            agent,
            message,
            data.mode,
            data.is_sensitive_mode,
            data.is_local_gguf,
            allow_sensitive_dialogue_examples=data.is_sensitive_mode,
            persona_name=data.persona_name,
        )
    
    t_now = time.perf_counter()
    timings["dialogue_examples"] = t_now - t_last
    t_last = t_now
    
    # 记录日志
    try:
        total_cost = time.perf_counter() - t_total
        timing_str = ", ".join([f"{k}: {v:.4f}s" for k, v in timings.items()])
        logger.info(
            "PromptData: TemplateLen=%s, Persona=%s, Mode=%s, Cloud=%s, Sensitive=%s, Model=%s",
            str(len(data.base_template) if data.base_template else 0),
            data.persona_filename,
            data.mode,
            str(data.is_cloud_model),
            str(data.is_sensitive_mode),
            data.model_name,
        )
        if total_cost >= 0.05:
            logger.info(
                "get_prompt_data: %.4fs total. Details: %s",
                total_cost, timing_str,
            )
    except Exception:
        pass
    
    return data


def get_template_data(
    persona_filename: str = "",
    fallback_template: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """
    获取模板和人设数据（已合并详细人设）
    
    Args:
        persona_filename: 人设文件名
        fallback_template: 备用模板
        
    Returns:
        (template, persona_data) 元组
    """
    cache_key = str(persona_filename or "").strip()
    persona_data = {}
    
    # 尝试从缓存获取（已合并详细人设的）
    if cache_key and cache_key in _expanded_persona_cache:
        template = _expanded_persona_cache[cache_key]
        # 同时也获取一下 persona_data
        try:
            pm = get_persona_manager()
            current_filename = str(pm.get_current_filename() or "").strip()
            if persona_filename and current_filename and persona_filename == current_filename:
                persona_data = pm.get_current_persona() or {}
            elif persona_filename:
                persona_data = pm.get_persona_by_filename(persona_filename) or {}
            else:
                persona_data = pm.get_current_persona() or {}
        except Exception:
            pass
        return template, persona_data
    
    # 没有缓存，从头构建
    template = str(fallback_template or "").strip()
    
    # 获取人设数据
    try:
        pm = get_persona_manager()
        current_filename = str(pm.get_current_filename() or "").strip()
        if persona_filename and current_filename and persona_filename == current_filename:
            persona_data = pm.get_current_persona() or {}
        elif persona_filename:
            persona_data = pm.get_persona_by_filename(persona_filename) or {}
        else:
            persona_data = pm.get_current_persona() or {}
    except Exception:
        pass
    
    # 获取原始模板（如果还没有）
    if not template and isinstance(persona_data, dict):
        template = str(
            persona_data.get("system_prompt_template")
            or persona_data.get("system_prompt")
            or ""
        ).strip()
        if not template:
            interaction = persona_data.get("interaction_logic")
            if isinstance(interaction, dict):
                template = str(
                    interaction.get("system_prompt_template")
                    or ""
                ).strip()
    
    # 合并详细人设（只做一次）
    from .components import build_detailed_persona
    from .assembler import _merge_template_and_persona
    detailed_persona = build_detailed_persona(persona_data)
    if detailed_persona:
        template = _merge_template_and_persona(template, detailed_persona)
    
    # 缓存
    if cache_key and template:
        _expanded_persona_cache[cache_key] = template
    
    return template, persona_data


def get_base_template(
    agent: Any,
    mode: str,
    user_id: str,
    user_name: str,
    persona_filename: str = "",
) -> str:
    """
    获取基础模板（已包含详细人设）
    
    Args:
        agent: ChatAgent 实例
        mode: 模式
        user_id: 用户 ID
        user_name: 用户名
        persona_filename: 人设文件名
        
    Returns:
        基础模板字符串
    """
    # 1. 获取基础模板
    current_config_prompt = getattr(agent.config, "system_prompt", "")
    
    try:
        aveline_tmpl = get_aveline_system_prompt_template()
    except Exception:
        aveline_tmpl = ""
    
    template = ""
    # get_template_data 已经包含详细人设了
    persona_template, persona_data = get_template_data(persona_filename=persona_filename)
    if mode not in ["study"] and persona_template:
        template = persona_template
    elif aveline_tmpl and len(str(aveline_tmpl)) > 10:
        template = str(aveline_tmpl)
    else:
        template = str(current_config_prompt or "")
    
    # 2. 如果 template 还没有详细人设（比如用的是 aveline_tmpl），我们再合并一次
    if (template == aveline_tmpl or template == current_config_prompt) and persona_data:
        from .components import build_detailed_persona
        from .assembler import _merge_template_and_persona
        detailed_persona = build_detailed_persona(persona_data)
        if detailed_persona:
            template = _merge_template_and_persona(template, detailed_persona)
    
    # 3. 模式特殊处理
    if mode == "romance":
        romance_tmpl = _get_prompt_template(agent, "PROMPT_TEMPLATE_ROMANCE")
        if romance_tmpl:
            template = romance_tmpl.format(user_name=user_name)
    elif mode == "study":
        study_tmpl = _get_study_template(agent, persona_filename)
        if study_tmpl:
            template = study_tmpl.format(user_name=user_name)
    
    return template


def is_bionic_character(persona_filename: str) -> bool:
    """
    判断是否需要注入角色状态块
    """
    filename_lower = str(persona_filename or "").lower()
    return "aveline" in filename_lower or "ling" in filename_lower


def get_persona_name_from_filename(persona_filename: str) -> str:
    """
    从文件名获取人设名
    """
    lowered = str(persona_filename or "").strip().lower()
    if "ling" in lowered:
        return "Ling"
    if "aveline" in lowered:
        return "七濑 澪"
    if "qq_official_1" in lowered or "xiaoyou1" in lowered:
        return "小鹿"
    if "qq_official_2" in lowered or "xiaoyou2" in lowered:
        return "Coco"
    return "Ling"


def get_cached_bionic_state(
    life_stats: Dict[str, Any],
    cpu_temp: Any,
    ram_usage: Any,
    actor_life_states: Optional[Dict[str, Dict[str, Any]]] = None,
    actor_relationships: Optional[Dict[str, float]] = None,
    role_sleep_states: Optional[Dict[str, Dict[str, Any]]] = None,
    current_persona_name: str = "",
    cache_duration: int = 300,
) -> str:
    """
    获取缓存的角色状态块（状态变化时立即失效）

    Args:
        life_stats: 生命状态
        cpu_temp: CPU 温度
        ram_usage: RAM 使用率
        actor_life_states: 所有角色的生命状态
        actor_relationships: 角色间关系值
        current_persona_name: 当前角色名称
        cache_duration: 缓存持续时间（秒）
    """
    from .components import build_bionic_state
    from core.utils.time_utils import get_current_time

    global _bionic_state_cache

    current_time = get_current_time()

    cache_key = (
        str(current_persona_name or "").strip().lower(),
        json.dumps(role_sleep_states or {}, ensure_ascii=False, sort_keys=True),
    )
    if (_bionic_state_cache is None or
        _bionic_state_cache.get("cache_key") != cache_key or
        (current_time - _bionic_state_cache.get("timestamp", datetime.min)).total_seconds() > cache_duration):
        state_str = build_bionic_state(
            life_stats, cpu_temp, ram_usage,
            actor_life_states=actor_life_states,
            actor_relationships=actor_relationships,
            role_sleep_states=role_sleep_states,
            current_persona_name=current_persona_name,
        )
        _bionic_state_cache = {
            "timestamp": current_time,
            "cache_key": cache_key,
            "data": state_str
        }
    else:
        state_str = _bionic_state_cache.get("data", "")

    return state_str


# ========== 内部辅助函数 ==========

def _get_prompt_template(agent_obj: Any, attr_name: str) -> str:
    """
    从 agent 或模块获取 prompt 模板
    """
    val = getattr(agent_obj, attr_name, None)
    if isinstance(val, str) and val.strip():
        return val
    try:
        from core.agents import chat_agent as chat_agent_mod
        val = getattr(chat_agent_mod, attr_name, None)
        if isinstance(val, str) and val.strip():
            return val
    except Exception:
        pass
    return ""


def _get_study_template(agent: Any, persona_filename: str) -> str:
    """
    获取学习模式模板
    """
    try:
        pm = get_persona_manager()
        study_config_file = "study/Aveline_Study.json"
        
        config_exists = False
        if hasattr(pm, "configs_dir"):
            if os.path.exists(os.path.join(pm.configs_dir, study_config_file)):
                config_exists = True
        
        if config_exists:
            with open(os.path.join(pm.configs_dir, study_config_file), 'r', encoding='utf-8') as f:
                study_data = json.load(f)
                study_tmpl = study_data.get("system_prompt_template", "")
                base_prompt_content = study_data.get("system_prompt_base", "")
                if "{base_system_prompt}" in study_tmpl:
                    study_tmpl = study_tmpl.replace("{base_system_prompt}", base_prompt_content)
                return study_tmpl
    except Exception as e:
        logger.error(f"加载学习模式模板失败: {e}")
    
    # 回退到内置模板
    return _get_prompt_template(agent, "PROMPT_TEMPLATE_STUDY")
