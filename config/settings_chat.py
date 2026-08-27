"""
对话、上下文、RAG、向量检索相关配置
"""

from __future__ import annotations

import importlib
from typing import Optional

from config._base import BaseSettings, Field, SettingsConfigDict


def _get_model_config():
    """安全获取 config.model_config 模块（避免包初始化期间的循环导入）。"""
    return importlib.import_module("config.model_config")


class ChatPostProcessSettings(BaseSettings):
    enabled: bool = Field(default=True, description="是否启用对话输出后处理")
    buffer_min_chars: int = Field(
        default=3, description="最小缓冲长度（到达后尝试按标点分段输出）"
    )
    buffer_hard_chars: int = Field(
        default=80, description="硬上限缓冲长度（超过后强制输出，避免延迟）"
    )
    buffer_max_delay_ms: int = Field(default=20, description="最大缓冲延迟（毫秒）")
    strip_sentence_period: bool = Field(
        default=True, description="尽量移除句末句号（更口语）"
    )
    enable_kaomoji: bool = Field(default=True, description="是否启用颜文字策略")
    max_kaomoji_per_reply: int = Field(
        default=1, description="单次回复最多插入颜文字数量"
    )
    base_kaomoji_probability: float = Field(default=0.04, description="基础颜文字概率")
    emit_backchannel_on_slow_ttft: bool = Field(
        default=True, description="首 token 较慢时是否先输出简短口头反馈"
    )
    slow_ttft_backchannel_delay_ms: int = Field(
        default=200, description="首 token 延迟超过该阈值(毫秒)时输出口头反馈"
    )
    slow_ttft_backchannel_text: str = Field(
        default="嗯…", description="首 token 较慢时输出的口头反馈文本"
    )
    paragraph_min_sentences: int = Field(
        default=3, description="段落缓冲：累积至少几个句子后才发送一次 WebSocket 消息"
    )
    paragraph_max_chars: int = Field(
        default=500, description="段落缓冲：缓冲区字符数超过此值时强制发送"
    )

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_CHAT_POSTPROCESS_",
        extra="allow",
    )


class ChatRewriteSettings(BaseSettings):
    enabled: bool = Field(default=False, description="是否启用二阶段回复润色")
    max_source_chars: int = Field(default=900, description="触发润色的最大原文长度")
    max_tokens: int = Field(default=220, description="润色最大输出 tokens")
    temperature: float = Field(default=0.35, description="润色温度")

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_CHAT_REWRITE_",
        extra="allow",
    )


class ChatContextBudgetSettings(BaseSettings):
    enabled: bool = Field(default=True, description="是否启用上下文预算控制")
    local_chars_per_token: float = Field(
        default=1.5, description="本地模型字符/Token 估计（越小越保守）"
    )
    buffer_chars: int = Field(default=200, description="预留缓冲字符数")
    min_history_chars: int = Field(default=500, description="最小历史配额字符数")
    image_tool_history_cap_chars: int = Field(
        default=800, description="触发画图工具时历史配额上限字符数"
    )
    max_total_chars_cap: int = Field(default=24000, description="上下文总字符硬上限")
    max_user_message_chars: int = Field(
        default=2400, description="单条用户输入最大字符数"
    )
    cloud_max_history_messages: int = Field(
        default=18, description="云端模型历史注入最大消息数"
    )
    cloud_max_history_chars: int = Field(
        default=6000, description="云端模型历史注入最大字符数"
    )
    cloud_relevance_keep_recent: int = Field(
        default=8, description="云端历史保留的最近消息数"
    )
    cloud_relevance_top_k: int = Field(
        default=12, description="云端历史按相关性补充的消息数"
    )
    cloud_relevance_candidate_window: int = Field(
        default=80, description="云端历史相关性筛选候选窗口大小"
    )
    long_message_compress_threshold: int = Field(
        default=400,
        description="非近期窗口中 assistant 消息超过该字符数时自动压缩为摘要"
    )
    long_message_compress_recent_window: int = Field(
        default=6,
        description="最近 N 条消息不做压缩（保持近期对话原貌）"
    )
    long_message_compress_max_chars: int = Field(
        default=160,
        description="压缩后的摘要最大字符数"
    )
    # 学习会话压缩配置
    study_session_compress_enabled: bool = Field(
        default=True,
        description="是否在退出学习模式时压缩学习上下文（节省token）"
    )
    study_session_compress_recent_window: int = Field(
        default=4,
        description="最近N条消息不压缩（保持近期对话原貌）"
    )
    study_session_compress_max_chars: int = Field(
        default=600,
        description="学习会话压缩摘要最大字符数"
    )

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_CHAT_CONTEXT_BUDGET_",
        extra="allow",
    )


class ChatContextCompressSettings(BaseSettings):
    enabled: bool = Field(default=True, description="是否启用构建阶段上下文压缩")
    max_summary_chars: int = Field(default=900, description="压缩摘要最大字符数")
    min_truncate_chars_to_compress: int = Field(
        default=800, description="被截断部分达到该字符数才触发压缩"
    )
    model_path: Optional[str] = Field(
        default=None, description="上下文压缩小模型 GGUF 路径（可选）"
    )
    # API模型配置（优先级高于model_path，设置后使用API调用而非本地模型）
    api_model: Optional[str] = Field(
        default_factory=lambda: _get_model_config().get_chat_context_compress_model(""),
        description="上下文压缩API模型（从 YAML 的 model_routing.chat_auxiliary_models.context_compress 自动同步）"
    )
    timeout_seconds: float = Field(default=0.8, description="压缩推理超时(秒)")
    max_tokens: int = Field(default=160, description="压缩最大输出 tokens")

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_CHAT_CONTEXT_COMPRESS_",
        extra="allow",
    )


class ChatRagSettings(BaseSettings):
    enabled: bool = Field(default=True, description="是否启用记忆 RAG 注入")
    min_memory_items_to_rag: int = Field(
        default=6, description="记忆条目不足时跳过 RAG 检索"
    )
    prefer_fast_keyword_when_embedding_unloaded: bool = Field(
        default=True,
        description="嵌入模型未加载时优先走关键词快速检索，避免首轮阻塞加载",
    )
    enable_query_rewrite: bool = Field(
        default=False, description="是否启用小模型查询改写（0.5B模型太弱，已禁用）"
    )
    query_rewrite_model_path: Optional[str] = Field(
        default=None,  # 设为None，不再使用0.5B模型
        description="查询改写模型 GGUF 路径（默认 None 表示禁用，需配合 enable_query_rewrite=True 才生效）",
    )
    query_rewrite_timeout_seconds: float = Field(
        default=0.25, description="查询改写超时(秒)"
    )
    query_rewrite_max_tokens: int = Field(
        default=48, description="查询改写最大输出 tokens"
    )
    slow_rag_threshold_seconds: float = Field(
        default=0.35, description="记忆检索超过该阈值时记录慢日志(秒)"
    )
    embedding_cache_max_items: int = Field(
        default=2048, description="记忆向量 base64 解码缓存最大条目数（LRU）"
    )
    query_embedding_cache_max_items: int = Field(
        default=256, description="查询向量缓存最大条目数（LRU）"
    )
    hybrid_limit: int = Field(default=4, description="混合检索返回条目数")
    min_similarity: float = Field(default=0.55, description="混合检索最小相似度阈值")
    keyword_fallback_limit: int = Field(
        default=8, description="嵌入不可用时关键词检索条目数"
    )

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_CHAT_RAG_",
        extra="allow",
    )


class ChatSettings(BaseSettings):
    postprocess: ChatPostProcessSettings = Field(
        default_factory=ChatPostProcessSettings, description="对话输出后处理配置"
    )
    rewrite: ChatRewriteSettings = Field(
        default_factory=ChatRewriteSettings, description="二阶段回复润色配置"
    )
    context_budget: ChatContextBudgetSettings = Field(
        default_factory=ChatContextBudgetSettings, description="上下文预算控制配置"
    )
    context_compress: ChatContextCompressSettings = Field(
        default_factory=ChatContextCompressSettings, description="上下文压缩配置"
    )
    rag: ChatRagSettings = Field(
        default_factory=ChatRagSettings, description="记忆 RAG 相关配置"
    )
    privacy_isolation: bool = Field(
        default=False,
        description="隐私隔离开关。开启后 sensitive 类别的记忆不会进入上下文、不会被搜索工具搜到；关闭则所有记忆平等对待",
    )

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_CHAT_",
        extra="allow",
    )


class VectorSearchSettings(BaseSettings):
    """向量检索配置"""

    max_document_length: int = Field(default=2000, description="文档最大长度")
    max_query_length: int = Field(default=1000, description="查询最大长度")
    tts_text_max_length: int = Field(default=500, description="TTS 最大文本长度")
    truncate_log_interval_seconds: float = Field(
        default=60.0, description="截断日志汇总间隔（秒）"
    )
    dialogue_examples_auto_ingest_on_startup: bool = Field(
        default=False,
        description="启动阶段是否自动灌入对话示例",
    )

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_VECTOR_SEARCH_", extra="allow"
    )
