"""
调度器、语音、数据运维、VTube Studio 相关配置
"""

from __future__ import annotations

from typing import Optional

from config._base import BaseSettings, Field, SettingsConfigDict
from config.settings_model import CloudProviderSettings


class CPPSchedulerConnectionSettings(BaseSettings):
    """C++ 调度器连接配置（用于 HTTP Client 模式）"""

    host: str = Field(default="127.0.0.1", description="C++ 调度器地址")
    port: int = Field(default=8080, description="C++ 调度器端口")

    model_config = SettingsConfigDict(extra="allow")


class CPPSchedulerHTTPClientSettings(BaseSettings):
    enabled: bool = Field(default=False, description="是否启用 C++ 调度器 HTTP Client")
    host: str = Field(default="127.0.0.1", description="C++ 调度器地址")
    port: int = Field(default=8080, description="C++ 调度器端口")

    model_config = SettingsConfigDict(extra="allow")


class VTubeStudioSettings(BaseSettings):
    """VTube Studio 连接配置"""

    enabled: bool = Field(default=False, description="是否启用 VTube Studio 连接")
    host: str = Field(default="localhost", description="VTube Studio 主机地址")
    port: int = Field(default=8002, description="VTube Studio 端口")
    plugin_name: str = Field(default="Xiaoyou Core Plugin", description="插件名称")
    developer: str = Field(default="Xiaoyou Team", description="开发者名称")
    token_path: str = Field(default="vtube_token.txt", description="Token 存储路径")

    # 情绪到热键的映射 (Emotion -> HotkeyID/Name)
    emotion_hotkey_map: dict[str, str] = Field(
        default_factory=lambda: {
            "happy": "ExpressionHappy",
            "sad": "ExpressionSad",
            "angry": "ExpressionAngry",
            "anxious": "ExpressionAnxious",
            "shy": "ExpressionShy",
            "shocked": "ExpressionShocked",
            "neutral": "ExpressionNeutral",
            "tired": "ExpressionTired",
            "coquetry": "ExpressionLove",
            "excited": "ExpressionExcited",
        },
        description="情绪到热键/表情的映射",
    )

    model_config = SettingsConfigDict(env_prefix="XIAOYOU_VTS_", extra="allow")


class SchedulerSettings(BaseSettings):
    """调度器配置"""

    bio_enable_cognitive_delay: bool = Field(
        default=True, description="是否启用仿生学认知延迟(会影响首 token)"
    )
    bio_max_cognitive_delay: float = Field(
        default=1.8, description="仿生学最大认知延迟(秒)"
    )
    bio_min_delay_to_apply: float = Field(
        default=0.2, description="超过该阈值才施加认知延迟(秒)"
    )
    bio_energy_cost_base: float = Field(
        default=0.005, description="每次LLM推理基础能量消耗(0~1)"
    )
    bio_energy_cost_complexity: float = Field(
        default=0.02, description="LLM推理复杂度能量消耗系数(0~1)"
    )
    bio_dopamine_reward: float = Field(
        default=0.01, description="每次LLM推理多巴胺奖励(0~1)"
    )
    bio_cortisol_cost_base: float = Field(
        default=0.002, description="每次LLM推理基础压力增量(0~1)"
    )
    bio_cortisol_cost_complexity: float = Field(
        default=0.006, description="LLM推理复杂度压力增量系数(0~1)"
    )

    bio_decay_rate: float = Field(
        default=0.001, description="神经递质回归基线的衰减速率(每秒)"
    )
    bio_energy_awake_decay: float = Field(
        default=0.0001, description="清醒期能量自然衰减(每秒)"
    )
    bio_energy_sleep_recover: float = Field(
        default=0.0005, description="睡眠期能量恢复(每秒)"
    )
    bio_sleep_debt_awake_gain: float = Field(
        default=0.0002, description="清醒期睡眠债累积(每秒)"
    )
    bio_sleep_debt_sleep_recover: float = Field(
        default=0.0006, description="睡眠期睡眠债恢复(每秒)"
    )

    use_cpp: bool = Field(default=True, description="是否启用 C++ 调度器")
    use_cpp_for_llm: bool = Field(default=True, description="LLM 是否强制走 C++ 调度器")
    llm_backend: str = Field(default="python", description="LLM 后端 (cpp/python)")
    allow_cpp_llm_worker: bool = Field(
        default=False, description="允许启用 C++ LLM Worker"
    )
    worker_count: int = Field(default=4, description="C++ 调度器 CPU 工作线程数")
    cpp: CPPSchedulerConnectionSettings = Field(
        default_factory=CPPSchedulerConnectionSettings
    )
    cpp_http: CPPSchedulerHTTPClientSettings = Field(
        default_factory=CPPSchedulerHTTPClientSettings
    )

    gpu_gate_enabled: bool = Field(
        default=True, description="是否启用全局 GPU 任务背压门闩"
    )
    gpu_gate_max_concurrent: int = Field(default=1, description="全局 GPU 任务最大并发")
    gpu_gate_max_waiting: int = Field(default=8, description="全局 GPU 任务最大排队数")
    gpu_gate_acquire_timeout_seconds: float = Field(
        default=600.0, description="排队等待 GPU 任务门闩超时(秒)"
    )

    model_config = SettingsConfigDict(env_prefix="XIAOYOU_SCHEDULER_", extra="allow")


class VoiceSettings(BaseSettings):
    """语音配置"""

    enabled: bool = Field(default=True, description="是否启用语音功能")

    # STT Settings
    stt: CloudProviderSettings = Field(
        default_factory=lambda: CloudProviderSettings(provider="local", model="base")
    )

    # TTS Settings
    tts: CloudProviderSettings = Field(
        default_factory=lambda: CloudProviderSettings(
            provider="qwen3", model="qwen3"
        )
    )

    # Legacy fields for backward compatibility (will be deprecated)
    default_engine: str = Field(default="qwen3", description="DEPRECATED")
    stt_engine: str = Field(default="faster_whisper", description="DEPRECATED")
    tts_engine: str = Field(default="qwen3", description="DEPRECATED")

    default_voice: str = Field(default="zh-CN-XiaoxiaoNeural", description="默认语音")
    default_speed: float = Field(default=1.0, description="默认语速")
    gpt_model_path: Optional[str] = Field(
        default="models/voice/GPT/流萤-e10.ckpt", description="GPT模型路径"
    )
    sovits_model_path: Optional[str] = Field(
        default="models/voice/SoVITS/Aveline_Violet_Mix.pth",
        description="SoVITS模型路径",
    )
    reference_audio: Optional[str] = Field(default=None, description="参考音频路径")

    # TTS VRAM 阈值配置 (MB)
    tts_vram_threshold_mb: int = Field(
        default=4096, description="TTS 所需的最低可用显存 (MB)，低于此值将跳过 TTS"
    )

    model_config = SettingsConfigDict(env_prefix="XIAOYOU_VOICE_", extra="allow")


class DataOpsSettings(BaseSettings):
    human_digest_enabled: bool = Field(default=False, description="是否启用可读整理摘要接口")
    taxonomy_version: str = Field(default="tax_v1", description="taxonomy 版本号")
    human_digest_version: str = Field(
        default="human_digest_v1", description="可读整理产物版本号"
    )
    human_digest_include_device_context: bool = Field(
        default=True, description="可读摘要是否默认读取设备上下文"
    )
    topic_judgement_mode: str = Field(
        default="posthoc",
        description="主题判定模式：posthoc(后置规则优先) / hybrid(融合) / llm_first(LLM优先)",
    )
    conversation_defer_analysis: bool = Field(
        default=True,
        description="会话写入时是否延后主题/权重分析到后端数据整理流程",
    )
    rule_analysis_worker_enabled: bool = Field(
        default=True, description="是否启用S_rule异步分析Worker"
    )
    rule_analysis_worker_count: int = Field(
        default=2, description="S_rule分析并发Worker数量"
    )
    rule_analysis_queue_size: int = Field(
        default=512, description="S_rule分析队列上限"
    )
    rule_analysis_batch_size: int = Field(
        default=32, description="单次S_rule分析最多处理条数"
    )
    ai_shadow_worker_enabled: bool = Field(
        default=True, description="是否启用S_ai影子分析Worker"
    )
    ai_shadow_worker_count: int = Field(
        default=1, description="S_ai影子分析并发Worker数量"
    )
    ai_shadow_queue_size: int = Field(
        default=256, description="S_ai影子分析队列上限"
    )
    ai_shadow_batch_size: int = Field(
        default=8, description="单次S_ai影子分析最多处理条数"
    )
    ai_shadow_timeout_ms: int = Field(
        default=1200, description="单条S_ai影子分析超时毫秒"
    )
    ai_shadow_strategy: str = Field(
        default="auto",
        description="S_ai影子分析策略：auto(优先LLM) / rule_fallback(规则回退)",
    )
    fusion_worker_enabled: bool = Field(
        default=True, description="是否启用S_fuse裁决Worker"
    )
    fusion_worker_count: int = Field(
        default=1, description="S_fuse裁决并发Worker数量"
    )
    fusion_queue_size: int = Field(
        default=256, description="S_fuse裁决队列上限"
    )
    fusion_batch_size: int = Field(
        default=16, description="单次S_fuse裁决最多处理条数"
    )
    fusion_override_min_confidence: float = Field(
        default=0.75, description="S_fuse触发覆盖策略最小置信度"
    )
    fusion_supplement_min_confidence: float = Field(
        default=0.5, description="S_fuse触发补充策略最小置信度"
    )
    fusion_allow_override: bool = Field(
        default=False, description="S_fuse是否允许覆盖规则主标签"
    )
    rule_only_degrade_enabled: bool = Field(
        default=True, description="规则队列高水位时是否降级为Rule-only"
    )
    rule_only_degrade_threshold_ratio: float = Field(
        default=0.8, description="触发Rule-only降级的S_rule队列占比阈值(0~1)"
    )

    model_config = SettingsConfigDict(env_prefix="XIAOYOU_DATA_OPS_", extra="allow")
