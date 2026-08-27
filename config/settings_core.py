"""
内存管理、日志、免疫系统、自愈服务相关配置
"""

from __future__ import annotations

from typing import Optional

from config._base import BaseSettings, Field, SettingsConfigDict


class MemorySettings(BaseSettings):
    """内存管理配置"""

    # 对话历史配置
    short_term_capacity: int = Field(default=60, description="短期记忆容量（内存中保留的最大条数）")
    long_term_capacity: int = Field(default=100000, description="长期记忆容量（基本不限制）")
    trim_threshold: int = Field(default=60, description="短期记忆修剪触发阈值，超过此数量触发修剪")
    history_dir: str = Field(default="", description="运行时目录基类（留空时各模块回退到 'runtime'）；实际由 preference_manager/session_manager/vocabulary/metacognition/user_physiology 等模块使用")
    auto_save_interval: int = Field(default=300, description="自动保存间隔(秒)")
    history_cleanup_interval_seconds: float = Field(
        default=300.0, description="历史目录空文件清理间隔(秒)"
    )
    history_archive_interval_seconds: float = Field(
        default=1800.0, description="历史目录归档检查间隔(秒)"
    )
    history_retention_days: int = Field(default=30, description="历史目录保留天数")
    history_auto_archive_enabled: bool = Field(
        default=True, description="是否启用历史目录自动归档"
    )
    readable_history_enabled: bool = Field(
        default=False, description="是否启用 readable 记忆镜像导出"
    )
    append_user_journal_to_memory: bool = Field(
        default=True, description="是否将用户日记追加到通用记忆系统"
    )
    append_auto_daily_summary_to_user_journal: bool = Field(
        default=True, description="是否将 AI 生成的用户每日总结追加为日记条目"
    )
    enable_user_daily_summary_generation: bool = Field(
        default=True, description="是否允许为用户自动生成每日总结/日记"
    )

    # 内存管理配置
    memory_pruning_threshold: float = Field(default=0.3, description="重要性阈值")
    long_term_memory_db: str = Field(
        default="long_term_memory.db", description="长期记忆数据库文件"
    )
    high_memory_threshold: int = Field(default=90, description="高内存使用率阈值")
    very_high_memory_threshold: int = Field(
        default=98, description="非常高内存使用率阈值"
    )
    gc_interval: int = Field(default=300, description="垃圾回收间隔")
    slow_response_threshold: float = Field(default=5.0, description="慢响应阈值")
    critical_response_threshold: float = Field(
        default=10.0, description="严重慢响应阈值"
    )

    # 缓存配置 (优化项)
    l1_cache_size: int = Field(default=20, description="L1缓存大小(最近访问)")
    l2_cache_size: int = Field(default=50, description="L2缓存大小(常用记忆)")

    model_config = SettingsConfigDict(env_prefix="XIAOYOU_MEMORY_", extra="allow")


class LogSettings(BaseSettings):
    """日志配置"""

    level: str = Field(default="INFO", description="日志级别")
    file: str = Field(default="logs/flask_app.log", description="日志文件名")
    error_dir: str = Field(default="logs/errors", description="错误日志目录")
    log_dir: str = Field(default="logs", description="日志目录")
    use_json_format: bool = Field(default=False, description="是否使用JSON格式")
    rotation_type: str = Field(default="size", description="日志轮转类型(size/time)")
    max_bytes: int = Field(default=10 * 1024 * 1024, description="单个日志文件最大大小")
    backup_count: int = Field(default=5, description="保留日志文件数量")
    rotation_when: str = Field(default="midnight", description="时间轮转点")
    rotation_interval: int = Field(default=1, description="时间轮转间隔")
    console_level: str = Field(default="INFO", description="控制台日志级别")

    model_config = SettingsConfigDict(env_prefix="XIAOYOU_LOG_", extra="allow")


class ImmuneSettings(BaseSettings):
    enabled: bool = Field(default=True, description="是否启用免疫系统")
    interval: float = Field(default=10.0, description="自检间隔(秒)")
    restart_window_seconds: int = Field(default=600, description="重启统计窗口(秒)")
    max_restarts_per_window: int = Field(default=2, description="窗口内最大重启次数")
    min_restart_interval_seconds: float = Field(
        default=30.0, description="两次重启最小间隔(秒)"
    )

    memory_medium_threshold: float = Field(
        default=90.0, description="内存中负载阈值(%)"
    )
    memory_emergency_threshold: float = Field(
        default=96.0, description="内存紧急阈值(%)"
    )
    llm_load_memory_block_threshold: Optional[float] = Field(
        default=None,
        description="本地LLM加载/切换模型的内存阻断阈值(%)；为空则沿用memory_emergency_threshold",
    )
    cpu_medium_threshold: float = Field(default=95.0, description="CPU中负载阈值(%)")
    cpu_emergency_threshold: float = Field(default=99.0, description="CPU紧急阈值(%)")

    model_config = SettingsConfigDict(env_prefix="XIAOYOU_IMMUNE_", extra="allow")


class AutoHealSettings(BaseSettings):
    """自愈服务配置"""

    enabled: bool = Field(default=True, description="是否启用自愈服务")
    auto_apply: bool = Field(default=False, description="是否自动应用补丁（否则等待审批）")
    check_interval: float = Field(default=30.0, description="检查间隔（秒）")
    suppress_duration: float = Field(default=300.0, description="同一规则触发后的抑制时间（秒）")

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_AUTO_HEAL_",
        extra="allow",
    )


class SelfImprovementSettings(BaseSettings):
    """自我改进系统配置"""

    enabled: bool = Field(default=True, description="是否启用自我改进系统")
    correction_detection: bool = Field(
        default=True, description="是否启用通用纠正检测（6种信号）"
    )
    learning_log: bool = Field(
        default=True, description="是否启用结构化学习日志"
    )
    core_memory: bool = Field(
        default=True, description="是否启用 MEMORY.md 核心记忆管理"
    )
    auto_slim: bool = Field(
        default=True, description="是否启用 MEMORY.md 自动瘦身"
    )
    drift_guard: bool = Field(
        default=True, description="是否启用记忆漂移防护"
    )
    daily_log: bool = Field(
        default=True, description="是否启用每日日志"
    )
    promotion: bool = Field(
        default=True, description="是否启用学习晋升（重复模式→永久规则）"
    )
    memory_max_size_kb: int = Field(
        default=5, description="MEMORY.md 最大大小（KB）"
    )
    experience_max_items: int = Field(
        default=15, description="业务经验区最大条目数"
    )
    corrections_max_items: int = Field(
        default=10, description="纠正记录区最大条目数"
    )
    promotion_recurrence_threshold: int = Field(
        default=3, description="晋升阈值：重复出现次数"
    )
    daily_log_retention_days: int = Field(
        default=30, description="每日日志保留天数"
    )
    prompt_injection: bool = Field(
        default=True, description="是否在 prompt 中注入自我改进指令"
    )

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_SELF_IMPROVEMENT_",
        extra="allow",
    )
