"""
服务器、网络、安全、平台相关配置
"""

from __future__ import annotations

from typing import Optional

from config._base import BaseSettings, Field, SettingsConfigDict


class ServerSettings(BaseSettings):
    """服务器配置"""

    port: int = Field(default=8000, description="服务器端口")
    host: str = Field(default="0.0.0.0", description="服务器主机")
    max_connections: int = Field(default=10, description="最大连接数")

    shutdown_timeout_seconds: float = Field(
        default=15.0, description="服务关闭总超时(秒)"
    )
    shutdown_service_timeout_seconds: float = Field(
        default=5.0, description="单个服务关闭超时(秒)"
    )
    force_exit_timeout_seconds: float = Field(
        default=30.0, description="关闭超时后强制退出(秒，<=0 表示禁用)"
    )

    # WebSocket配置
    ws_port: int = Field(default=8765, description="WebSocket服务端口")
    ws_heartbeat_interval: int = Field(default=30, description="心跳间隔（秒）")
    ws_timeout: int = Field(default=60, description="超时时间（秒）")
    ws_user_message_merge_wait_ms: int = Field(
        default=700, description="用户连续输入合并等待窗口（毫秒）"
    )
    ws_skip_merge_wait_platforms: str = Field(
        default="qq", description="跳过二次合并等待的平台列表，逗号分隔"
    )

    # 性能配置
    max_requests_per_minute: int = Field(default=60, description="每分钟最大请求数")
    max_ip_requests_per_minute: int = Field(
        default=30, description="每IP每分钟最大请求数"
    )
    max_content_length: int = Field(
        default=16 * 1024 * 1024, description="最大内容长度"
    )
    max_upload_image_size: int = Field(
        default=10 * 1024 * 1024, description="最大上传图片大小(字节)"
    )

    # 安全配置
    allowed_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000,http://localhost:3001,http://localhost:8000,http://localhost:8001,http://localhost:8002,http://127.0.0.1:5173,http://127.0.0.1:3000,http://127.0.0.1:3001,http://127.0.0.1:8000,http://127.0.0.1:8001,http://127.0.0.1:8002,http://[::1]:5173,http://[::1]:3000,http://[::1]:3001,http://[::1]:8000,http://[::1]:8001,http://[::1]:8002,http://localhost,capacitor://localhost,https://localhost,app://localhost",
        description="允许的跨域来源，逗号分隔",
    )

    model_config = SettingsConfigDict(env_prefix="XIAOYOU_SERVER_", extra="allow")


class CacheSettings(BaseSettings):
    """缓存配置"""

    size: int = Field(default=1000, description="LRU缓存大小")
    ttl: int = Field(default=3600, description="缓存过期时间（秒）")

    model_config = SettingsConfigDict(env_prefix="XIAOYOU_CACHE_", extra="allow")


class SystemSettings(BaseSettings):
    """系统配置"""

    use_local_models_only: bool = Field(default=False, description="是否仅使用本地模型")
    timezone: str = Field(default="Asia/Shanghai", description="系统时区")

    model_config = SettingsConfigDict(env_prefix="XIAOYOU_SYSTEM_", extra="allow")


class MonitorSettings(BaseSettings):
    """监控配置"""

    cpu_threshold_high: float = Field(default=99.0, description="CPU高负载阈值")
    cpu_threshold_medium: float = Field(default=95.0, description="CPU中负载阈值")
    memory_threshold_high: float = Field(default=98.0, description="内存高负载阈值")
    memory_threshold_medium: float = Field(default=95.0, description="内存中负载阈值")
    gpu_memory_threshold_high: float = Field(
        default=99.0, description="GPU显存高负载阈值"
    )
    gpu_memory_threshold_medium: float = Field(
        default=95.0, description="GPU显存中负载阈值"
    )

    model_config = SettingsConfigDict(env_prefix="XIAOYOU_MONITOR_", extra="allow")


class UserSettings(BaseSettings):
    display_name: str = Field(default="", description="用户称呼/显示名称")

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_USER_",
        extra="allow",
    )


class SecuritySettings(BaseSettings):
    """安全配置"""

    web_access_token: Optional[str] = Field(
        default=None, description="Web访问密码/Token (为空则不启用)"
    )

    model_config = SettingsConfigDict(
        env_prefix="XIAOYOU_SECURITY_",
        extra="allow",
    )


class PlatformSettings(BaseSettings):
    """第三方平台配置"""

    class QQSettings(BaseSettings):
        sync_active_care: bool = Field(
            default=True, description="是否将 Active Care 消息同步到 QQ"
        )

    qq: QQSettings = Field(default_factory=QQSettings)

    model_config = SettingsConfigDict(env_prefix="XIAOYOU_PLATFORM_", extra="allow")
