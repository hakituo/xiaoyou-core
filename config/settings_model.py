"""
模型、LLM、图像生成、模型适配器相关配置
"""

from __future__ import annotations

import os
import importlib
from typing import Any, Dict, List, Optional

from config._base import BaseSettings, Field, SettingsConfigDict


def _get_model_config():
    """安全获取 config.model_config 模块。

    在 config 包初始化期间，__import__("config.model_config") 返回的是 config 包
    对象（可能部分初始化，无 model_config 属性）。改用 importlib.import_module
    直接获取子模块对象，避免依赖包属性的绑定时机。
    """
    return importlib.import_module("config.model_config")


# 各云端供应商的默认 base_url（OpenAI 兼容模式）
# 说明：
# - dashscope 此处为 OpenAI 兼容模式 URL，dashscope_client.py 使用的是原生 API URL，与此不同
# - aveline 使用自定义 URL，此处为 None（由调用方提供）
PROVIDER_BASE_URLS: Dict[str, Optional[str]] = {
    "deepseek": "https://api.deepseek.com/chat/completions",
    "siliconflow": "https://api.siliconflow.cn/v1/chat/completions",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    "minimax": "https://api.minimax.chat/v1/text/chatcompletion_v2",
    "ark": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    "aveline": None,  # Aveline使用自定义URL
}

# 各云端供应商的默认模型列表（按优先级从高到低）
PROVIDER_DEFAULT_MODELS: Dict[str, List[str]] = {
    "deepseek": ["deepseek-v4-flash", "deepseek-v4-pro"],
    "siliconflow": ["Pro/moonshotai/Kimi-K2.6", "Pro/deepseek-ai/DeepSeek-V3.2", "MiniMaxAI/MiniMax-M2.5"],
    "dashscope": ["qwen3-max-2025-09-23", "qwen3-plus"],
    "minimax": ["MiniMax-M2.5", "M2-her"],
    "ark": ["doubao-seed-2-0-lite-260215"],
    "zhipu": ["glm-4.5-air", "glm-4.6v"],
    "aveline": ["nalang-xl-0826-16k"],
}

# 支持的供应商列表（基于 PROVIDER_BASE_URLS 的键自动派生）
SUPPORTED_PROVIDERS = list(PROVIDER_BASE_URLS.keys())


class CloudProviderSettings(BaseSettings):
    """云端服务提供商配置"""

    provider: str = Field(
        default="local", description="提供商 (local, siliconflow, openai, custom)"
    )
    api_key: Optional[str] = Field(default=None, description="API Key")
    base_url: Optional[str] = Field(default=None, description="Base URL")
    model: Optional[str] = Field(default=None, description="模型名称")
    
    # DeepSeek 思考模式配置
    thinking_enabled: bool = Field(
        default=True, description="是否启用 DeepSeek 思考模式（仅 DeepSeek 模型有效）"
    )
    reasoning_effort: str = Field(
        default="high", description="DeepSeek 思考强度（high/max，仅 DeepSeek 模型有效）"
    )

    model_config = SettingsConfigDict(extra="allow")


class CloudProviderKeyConfig(BaseSettings):
    """单个供应商的多API key配置
    
    支持同一个供应商配置多个API key，每个key可以有不同的模型列表。
    模型路径格式: cloud:provider:key_alias:model
    例如: cloud:deepseek:qqbot1:deepseek-v4-pro
    """
    
    key_alias: str = Field(description="API key别名，用于在模型路径中标识")
    api_key: str = Field(description="API Key")
    api_key_env: Optional[str] = Field(default=None, description="API Key环境变量名（优先使用api_key）")
    base_url: Optional[str] = Field(default=None, description="Base URL")
    models: List[str] = Field(default_factory=list, description="该key可用的模型列表")
    
    # 思考模式配置
    thinking_enabled: bool = Field(default=True, description="是否启用思考模式")
    reasoning_effort: str = Field(default="high", description="思考强度")
    
    model_config = SettingsConfigDict(extra="allow")


class ModelSettings(BaseSettings):
    """模型配置"""

    model_dir: str = Field(default="models", description="模型目录")
    cache_dir: str = Field(default="cache", description="缓存目录")
    device: str = Field(default="cuda", description="设备类型(cpu/cuda)")
    max_memory: Optional[int] = Field(default=None, description="最大内存使用(MB)")
    name: str = Field(
        default_factory=lambda: _get_model_config().get_default_chat_model("cloud:deepseek:deepseek-v4-flash").split(":")[-1] if ":" in _get_model_config().get_default_chat_model("cloud:deepseek:deepseek-v4-flash") else "deepseek-v4-flash",
        description="默认模型名称（从 YAML 的 model_routing.default_chat_model 自动同步）",
    )
    text_path: Optional[str] = Field(default=None, description="文本模型路径")
    summary_model_path: Optional[str] = Field(
        default=None, description="摘要/工具模型路径(CPU Offload)"
    )
    vision_path: Optional[str] = Field(default=None, description="视觉模型路径")
    image_gen_path: Optional[str] = Field(default=None, description="图像生成模型路径")
    whisper_path: Optional[str] = Field(default=None, description="Whisper模型路径")
    first_token_timeout: int = Field(default=30, description="首个token超时时间（秒）")
    model_load_timeout: int = Field(default=60, description="本地模型加载超时（秒）")

    journal_model_hint: str = Field(
        default_factory=lambda: _get_model_config().get_journal_model("cloud:siliconflow:MiniMaxAI/MiniMax-M2.5"),
        description="日记/总结/导出专用模型路由提示",
    )

    persona_model_map: Dict[str, str] = Field(
        default_factory=lambda: _get_model_config().load_model_config().get("chat_models", {}),
        description="人设到模型的映射（人设关键词 -> model_hint），前台对话时根据当前人设自动选择模型。配置在 YAML 的 model_routing.chat_models 中",
    )

    persona_audio_map: Dict[str, str] = Field(
        default={
            "aveline": "ref_audio/female/ref_calm.wav",
            "ling": "ref_audio/female/玲.wav",
        },
        description="人设到参考音频的映射（人设关键词 -> 参考音频路径），切换人设时自动联动参考音频",
    )

    llm_preload_on_startup: bool = Field(
        default=False,
        description="provider=local 时是否在启动阶段预加载本地 LLM（关闭可显著降低空闲内存占用）",
    )

    # HuggingFace 镜像配置
    hf_endpoint: str = Field(
        default="https://hf-mirror.com",
        description="HuggingFace 镜像地址（国内用户建议使用 hf-mirror.com）",
    )
    hf_offline: bool = Field(
        default=False,
        description="是否禁止 HuggingFace 联网下载（离线模式）",
    )

    # 多API key配置（同一供应商不同key的模型列表）
    # 格式: {provider: {key_alias: CloudProviderKeyConfig}}
    # 例如: {"deepseek": {"default": {...}, "qqbot1": {...}, "qqbot2": {...}}}
    cloud_provider_keys: Dict[str, Dict[str, CloudProviderKeyConfig]] = Field(
        default_factory=lambda: _load_cloud_provider_keys_from_env(),
        description="多API key配置，支持同一供应商配置多个API key，每个key有不同的模型列表"
    )

    # LLM Settings
    llm: CloudProviderSettings = Field(
        default_factory=lambda: CloudProviderSettings(
            provider="deepseek",
            model=_get_model_config().get_default_chat_model("cloud:deepseek:deepseek-v4-flash").split(":")[-1] if ":" in _get_model_config().get_default_chat_model("cloud:deepseek:deepseek-v4-flash") else "deepseek-v4-flash",
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv(
                "DEEPSEEK_BASE_URL", PROVIDER_BASE_URLS.get("deepseek")
            ),
            thinking_enabled=True,
            reasoning_effort="high",
        )
    )

    # DashScope/Qwen 模型配置 - 固定使用 Qwen 3.5 Plus
    dashscope_default_model: str = Field(
        default="qwen3.5-plus", description="DashScope 默认模型 (固定为 qwen3.5-plus)"
    )

    # Vision Settings
    vision: CloudProviderSettings = Field(
        default_factory=lambda: CloudProviderSettings(
            provider="siliconflow",
            model="Qwen/Qwen3-VL-235B-A22B-Thinking",
            api_key=os.getenv("SILICONFLOW_API_KEY"),
            base_url=PROVIDER_BASE_URLS.get("siliconflow"),
        )
    )

    # Image Generation Settings
    image: CloudProviderSettings = Field(
        default_factory=lambda: CloudProviderSettings(provider="forge", model="default")
    )

    # Legacy fields
    image_provider: str = Field(
        default="forge", description="图像生成提供商 (forge, comfyui, siliconflow)"
    )
    default_image_model: str = Field(
        default="illustrious", description="默认图像生成模型文件名"
    )
    fallback_image_model: str = Field(
        default="sensitive_v10.safetensors", description="备用图像生成模型文件名"
    )
    image_gen_width: int = Field(default=1024, description="图像生成默认宽度")
    image_gen_height: int = Field(default=1024, description="图像生成默认高度")
    image_gen_steps: int = Field(default=20, description="图像生成默认步数")
    image_output_dir: str = Field(default="output/image", description="图像输出目录")
    image_service_url: str = Field(
        default="ws://localhost:8001", description="图像服务WebSocket地址"
    )
    gpu_enabled: bool = Field(default=True, description="是否启用GPU")
    memory_limit: int = Field(default=16, description="内存限制(GB)")
    load_mode: str = Field(default="online", description="模型加载模式(online/local)")
    local_model_prefix: str = Field(default="./models/", description="本地模型路径前缀")

    forge_warmup_on_startup: bool = Field(
        default=False, description="是否在启动时进行 Forge API 预热（不占显存）"
    )
    forge_keep_model_loaded_seconds: int = Field(
        default=0, description="生图结束后 Forge 模型保留秒数（0 表示立刻释放）"
    )

    forge_dir: str = Field(
        default="models/Image/stable-diffusion-webui-forge-main",
        description="Forge 安装目录（包含 webui-user.bat）",
    )
    forge_auto_start: bool = Field(
        default=False,
        description="当检测到 Forge 未启动时，是否自动拉起 Forge 终端",
    )
    forge_startup_timeout_seconds: float = Field(
        default=180.0,
        description="自动拉起 Forge 后等待就绪的超时（秒）",
    )

    # ComfyUI Settings
    comfy_host: str = Field(default="127.0.0.1", description="ComfyUI 主机地址")
    comfy_port: int = Field(default=8188, description="ComfyUI 端口")
    comfy_auto_check_nunchaku: bool = Field(
        default=True, description="是否自动检查 Nunchaku 插件可用性"
    )
    comfy_auto_acceleration: bool = Field(
        default=True, description="是否自动检测并启用 SDXL Lightning/Turbo/LCM 加速"
    )

    # 生成参数
    temperature: float = Field(default=0.7, description="生成温度")
    min_p: float = Field(default=0.05, description="Min-P 采样")
    repetition_penalty: float = Field(default=1.08, description="重复惩罚")
    top_p: float = Field(default=0.9, description="Top-P 采样")
    top_k: int = Field(default=40, description="Top-K 采样")  # 生成参数
    max_new_tokens: Optional[int] = Field(default=None, description="最大生成长度")
    n_ctx: int = Field(default=4096, description="上下文窗口大小")
    n_gpu_layers: int = Field(
        default=-1,
        description="llama.cpp GPU layers (-1 表示全量卸载到 GPU，0 表示强制CPU模式)",
    )
    force_cpu_inference: bool = Field(
        default=False,
        description="强制使用CPU推理（即使有GPU也使用CPU，避免GPU推理卡死问题）",
    )
    flash_attn: bool = Field(
        default=True, description="是否启用 Flash Attention (加速推理并节省显存)"
    )
    offload_kqv: bool = Field(default=True, description="是否将 KV Cache 卸载到 GPU")
    n_batch: int = Field(
        default=512, description="推理批次大小 (8G 显存建议 256-512，显存充裕可提高)"
    )
    use_mmap: bool = Field(
        default=False,
        description="是否使用内存映射加载模型（False可避免DDR和GDDR双映射，但加载速度较慢）",
    )
    ram_mirror_offload: bool = Field(
        default=True, description="是否启用RAM镜像式迁移（GPU常驻时不启用mmap）"
    )

    kv_swap_enabled: bool = Field(
        default=True, description="是否启用 KVSwap（对话 KV 状态落盘/回载）"
    )
    kv_swap_dir: Optional[str] = Field(
        default=None, description="KVSwap 落盘目录（默认使用 cache_dir/kvswap）"
    )
    kv_swap_trigger_tokens: int = Field(
        default=2048, description="触发 KVSwap 的最小 token 数"
    )

    vram_reserve_mb: int = Field(
        default=0, description="为其它 GPU 任务预留的空闲显存(MB)"
    )
    tts_gpu_min_free_mb: int = Field(
        default=1200, description="TTS 尝试使用 GPU 时的最低空闲显存(MB)"
    )
    dynamic_kv_offload: bool = Field(
        default=True, description="显存紧张时自动将 KV Cache 放到 CPU"
    )

    model_config = SettingsConfigDict(env_prefix="XIAOYOU_MODEL_", extra="allow")


class TextModelSettings(BaseSettings):
    """文本模型配置"""

    text_model_path: Optional[str] = Field(default=None, description="文本模型路径")
    draft_model_path: Optional[str] = Field(
        default="", description="草稿模型路径 (Speculative Decoding)，设为空字符串禁用"
    )
    draft_gpu_device_id: int = Field(
        default=-1, description="草稿模型 GPU ID (-1 为 CPU)"
    )
    quantization: Optional[Dict[str, Any]] = Field(default=None, description="量化配置")

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_MODEL_ADAPTER_TEXT_MODEL_", extra="allow"
    )


class ModelAdapterSettings(BaseSettings):
    """模型适配器配置"""

    text_model: Optional[TextModelSettings] = TextModelSettings()

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_MODEL_ADAPTER_", extra="allow"
    )


def _load_cloud_provider_keys_from_env() -> Dict[str, Dict[str, CloudProviderKeyConfig]]:
    """从环境变量加载多API key配置

    环境变量格式:
    - DEEPSEEK_API_KEY: 默认API key（可选）
    - DEEPSEEK_API_KEY_Aveline: Aveline 角色专用 key
    - DEEPSEEK_API_KEY_Ling: Ling（Ling）角色专用 key
    - DEEPSEEK_API_KEY_QQBOT1: QQ bot 1的API key
    - DEEPSEEK_API_KEY_QQBOT2: QQ bot 2的API key

    返回格式:
    {
        "deepseek": {
            "default": CloudProviderKeyConfig(...),   # 仅当 DEEPSEEK_API_KEY 存在时
            "aveline": CloudProviderKeyConfig(...),
            "ling": CloudProviderKeyConfig(...),
            "qqbot1": CloudProviderKeyConfig(...),
            "qqbot2": CloudProviderKeyConfig(...)
        }
    }
    """
    result: Dict[str, Dict[str, CloudProviderKeyConfig]] = {}

    # 支持的供应商列表（从模块级常量派生）
    providers = SUPPORTED_PROVIDERS

    for provider in providers:
        provider_keys: Dict[str, CloudProviderKeyConfig] = {}

        # 获取默认API key（可选，不存在则跳过 default 槽位）
        default_key_env = f"{provider.upper()}_API_KEY"
        default_key = os.getenv(default_key_env)

        # 供应商 base_url（默认值 + 环境变量覆盖）
        base_url = PROVIDER_BASE_URLS.get(provider)
        base_url_env = f"{provider.upper()}_BASE_URL"
        env_base_url = os.getenv(base_url_env)
        if env_base_url:
            base_url = env_base_url

        if default_key:
            # 添加默认key
            provider_keys["default"] = CloudProviderKeyConfig(
                key_alias="default",
                api_key=default_key,
                api_key_env=default_key_env,
                base_url=base_url,
                models=PROVIDER_DEFAULT_MODELS.get(provider, []),
                thinking_enabled=True,
                reasoning_effort="high",
            )

        # 查找其他API key（格式: PROVIDER_API_KEY_XXX），即使没有默认 key 也扫描
        prefix = f"{provider.upper()}_API_KEY_"
        for env_name, env_value in os.environ.items():
            if env_name.startswith(prefix) and env_name != default_key_env:
                # 提取别名（转小写）
                key_alias = env_name[len(prefix):].lower()
                if key_alias and env_value:
                    provider_keys[key_alias] = CloudProviderKeyConfig(
                        key_alias=key_alias,
                        api_key=env_value,
                        api_key_env=env_name,
                        base_url=base_url,
                        models=PROVIDER_DEFAULT_MODELS.get(provider, []),
                        thinking_enabled=True,
                        reasoning_effort="high",
                    )

        if provider_keys:
            result[provider] = provider_keys

    return result
