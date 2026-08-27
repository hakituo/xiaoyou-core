# -*- coding: utf-8 -*-
"""适配器配置（P2-2: 收敛独立配置到 pydantic model）

将原本散落在 config/asr_config.json、config/yaml/app.yaml、
clients/bots/multi_qq_config.json 的配置收敛为 pydantic model，
提供统一的加载入口和类型校验。

设计原则：
- Telegram 非敏感配置统一由 app.yaml 承载，敏感值继续由环境变量提供
- 其余历史 JSON 文件保留为数据载体，但读取走 pydantic 校验
- 提供带缓存的 get_xxx() 单例访问入口，避免每次调用都重新读文件
- 环境变量优先级高于 JSON 文件（与原行为保持一致）
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from config._base import BaseSettings, Field, SettingsConfigDict


def _get_project_root() -> Path:
    """获取项目根目录（委托给 core.utils.common，避免循环导入）。"""
    from core.utils.common import get_project_root
    return Path(get_project_root())


# ==================== ASR 配置 ====================

class ASRSettings(BaseSettings):
    """ASR（语音识别）配置。

    收敛来源：config/asr_config.json
    """

    model_path: str = Field(
        default="models/faster-whisper",
        description="ASR 模型路径（相对路径会基于项目根目录解析）",
    )
    model_type: str = Field(
        default="faster-whisper",
        description="ASR 模型类型：whisper / paraformer / faster-whisper",
    )
    sample_rate: int = Field(default=16000, description="采样率")
    language: str = Field(default="zh-CN", description="识别语言")
    enable_vad: bool = Field(default=True, description="是否启用 VAD（语音活动检测）")
    enable_punctuation: bool = Field(default=True, description="是否启用标点恢复")
    use_gpu: bool = Field(default=True, description="是否使用 GPU 推理")

    model_config = SettingsConfigDict(extra="allow")


_asr_settings_cache: Optional[ASRSettings] = None
_asr_lock = threading.Lock()


def get_asr_settings() -> ASRSettings:
    """获取 ASR 配置单例（带缓存）。

    优先级：环境变量 > config/asr_config.json > 默认值
    """
    global _asr_settings_cache
    if _asr_settings_cache is not None:
        return _asr_settings_cache

    with _asr_lock:
        if _asr_settings_cache is not None:
            return _asr_settings_cache

        # 默认值
        data: Dict[str, Any] = {}

        # 从 JSON 文件加载
        json_path = _get_project_root() / "config" / "asr_config.json"
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
            except Exception as e:
                from core.utils.logger import get_logger
                get_logger("config.asr").warning("加载 asr_config.json 失败: %s", e)

        # 环境变量覆盖
        env_model_path = os.getenv("ASR_MODEL_PATH", "").strip()
        if env_model_path:
            data["model_path"] = env_model_path
        env_model_type = os.getenv("ASR_MODEL_TYPE", "").strip()
        if env_model_type:
            data["model_type"] = env_model_type

        # 相对路径解析（保持与 stt_connector.py 原逻辑一致）
        model_path = str(data.get("model_path", "models/faster-whisper"))
        p = Path(model_path)
        if (
            not p.is_absolute()
            and p.parts
            and p.parts[0] in ("models", "data", "config", "output")
        ):
            data["model_path"] = str(_get_project_root() / p)

        _asr_settings_cache = ASRSettings(**data)
        return _asr_settings_cache


# ==================== 天气查询配置 ====================

class WeatherSettings(BaseSettings):
    """天气查询配置（和风天气 QWeather，JWT 认证）。

    申请地址：https://console.qweather.com/
    免费订阅：1000 次/天，含实时+24小时+7天预报+空气质量+预警
    认证方式：Ed25519 JWT（私钥本地保管，公钥上传到控制台凭据）
    """

    api_host: str = Field(
        default="",
        description="和风天气 API Host（控制台-设置里查看，类似 xxx.re.qweatherapi.com）",
    )
    credential_id: str = Field(
        default="",
        description="凭据 ID（控制台-项目管理-凭据里查看，作 JWT 的 iss）",
    )
    project_id: str = Field(
        default="",
        description="项目 ID（作 JWT 的 sub，可选）",
    )
    private_key_path: str = Field(
        default="config/qweather_private_key.pem",
        description="Ed25519 私钥文件路径（PEM 格式，已被 .gitignore 忽略）",
    )
    default_location: str = Field(
        default="",
        description="默认查询城市（留空时需用户指定，如 '北京' 或 '116.41,39.92'）",
    )
    timeout_seconds: float = Field(
        default=8.0,
        description="HTTP 请求超时秒数",
    )
    jwt_ttl_minutes: int = Field(
        default=30,
        description="JWT 有效期（分钟），过期后重新生成",
    )

    model_config = SettingsConfigDict(env_prefix="QWEATHER_", env_file=None)


_weather_settings_cache: Optional[WeatherSettings] = None


def get_weather_settings() -> WeatherSettings:
    """获取天气配置单例（带缓存）。

    优先级：环境变量 QWEATHER_* > 默认值
    """
    global _weather_settings_cache
    if _weather_settings_cache is not None:
        return _weather_settings_cache

    import os

    _weather_settings_cache = WeatherSettings(
        api_host=os.environ.get("QWEATHER_API_HOST", ""),
        credential_id=os.environ.get("QWEATHER_CREDENTIAL_ID", ""),
        project_id=os.environ.get("QWEATHER_PROJECT_ID", ""),
        private_key_path=os.environ.get(
            "QWEATHER_PRIVATE_KEY_PATH", "config/qweather_private_key.pem"
        ),
        default_location=os.environ.get("QWEATHER_DEFAULT_LOCATION", ""),
    )
    return _weather_settings_cache


# ==================== Telegram 适配器配置 ====================

class TelegramAdapterSettings(BaseSettings):
    """Telegram 适配器配置。

    收敛来源：config/yaml/app.yaml 的 telegram 段 + 环境变量。
    """

    enabled: bool = Field(default=False, description="是否启用 Telegram 适配器（默认关闭）")
    bot_token: str = Field(default="", description="Telegram Bot Token")
    enable_voice: bool = Field(default=True, description="是否启用语音消息")
    enable_vision: bool = Field(default=True, description="是否启用图片/视觉")
    strip_markdown: bool = Field(default=False, description="是否剥离 Markdown 标记（False=支持加粗/隐藏/删除线等格式）")
    http_base_url: str = Field(
        default="http://localhost:8000", description="小优核心服务 HTTP 地址"
    )
    ws_url: str = Field(
        default="ws://localhost:8000/api/v1/ws", description="小优核心服务 WebSocket 地址"
    )
    access_token: str = Field(default="", description="访问令牌")
    master_user_id: str = Field(default="", description="仅响应的 Telegram 用户 ID")
    proxy_url: str = Field(default="", description="Telegram API 代理地址")
    persona_filename: str = Field(
        default="sensitive/Frost.json", description="Telegram 默认人设文件名"
    )
    http_timeout_seconds: int = Field(default=30, description="HTTP 请求超时(秒)")
    session_timeout_minutes: int = Field(default=30, description="会话超时(分钟)")

    model_config = SettingsConfigDict(extra="allow")


_telegram_settings_cache: Optional[TelegramAdapterSettings] = None
_telegram_lock = threading.Lock()


def get_telegram_adapter_settings() -> TelegramAdapterSettings:
    """获取 Telegram 适配器配置单例（带缓存）。

    启用开关和非敏感功能项以 app.yaml 的 telegram 段为准；
    Bot Token、Master 用户 ID、代理等本机值由环境变量补充。
    """
    global _telegram_settings_cache
    if _telegram_settings_cache is not None:
        return _telegram_settings_cache

    with _telegram_lock:
        if _telegram_settings_cache is not None:
            return _telegram_settings_cache

        # app.yaml 已由统一配置系统完成 YAML 合并和 pydantic 校验。
        # 延迟导入可避免 integrated_config 聚合本 model 时发生循环导入。
        from config.integrated_config import get_settings

        data: Dict[str, Any] = get_settings().telegram.model_dump()

        # app.yaml 是启用状态的唯一真源，避免遗留环境变量悄悄覆盖显式开关。
        env_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if env_token:
            data["bot_token"] = env_token
        if os.getenv("ENABLE_TELEGRAM_VOICE"):
            data["enable_voice"] = os.getenv("ENABLE_TELEGRAM_VOICE", "").lower() == "true"
        if os.getenv("ENABLE_TELEGRAM_VISION"):
            data["enable_vision"] = os.getenv("ENABLE_TELEGRAM_VISION", "").lower() == "true"
        if os.getenv("TELEGRAM_STRIP_MARKDOWN"):
            data["strip_markdown"] = os.getenv("TELEGRAM_STRIP_MARKDOWN", "").lower() == "true"
        if os.getenv("XIAOYOU_HTTP_BASE_URL"):
            data["http_base_url"] = os.getenv("XIAOYOU_HTTP_BASE_URL", "")
        if os.getenv("XIAOYOU_WS_URL"):
            data["ws_url"] = os.getenv("XIAOYOU_WS_URL", "")
        if os.getenv("XIAOYOU_ACCESS_TOKEN"):
            data["access_token"] = os.getenv("XIAOYOU_ACCESS_TOKEN", "")
        if os.getenv("TELEGRAM_MASTER_USER_ID"):
            data["master_user_id"] = os.getenv("TELEGRAM_MASTER_USER_ID", "").strip()
        if os.getenv("TELEGRAM_PROXY_URL"):
            data["proxy_url"] = os.getenv("TELEGRAM_PROXY_URL", "").strip()
        if os.getenv("TELEGRAM_PERSONA_FILENAME"):
            data["persona_filename"] = os.getenv(
                "TELEGRAM_PERSONA_FILENAME", ""
            ).strip()
        if os.getenv("TELEGRAM_HTTP_TIMEOUT"):
            try:
                data["http_timeout_seconds"] = int(os.getenv("TELEGRAM_HTTP_TIMEOUT", "30"))
            except ValueError:
                pass
        if os.getenv("TELEGRAM_SESSION_TIMEOUT"):
            try:
                data["session_timeout_minutes"] = int(os.getenv("TELEGRAM_SESSION_TIMEOUT", "30"))
            except ValueError:
                pass

        _telegram_settings_cache = TelegramAdapterSettings(**data)
        return _telegram_settings_cache


# ==================== 多 QQ 适配器配置 ====================

class MultiQQRoleConfig(BaseSettings):
    """单个 QQ 角色的配置。"""

    role_id: str = Field(default="", description="角色 ID（aveline/ling 等）")
    role_name: str = Field(default="", description="角色显示名称")
    napcat_ws_url: str = Field(default="", description="NapCat WebSocket 地址")
    xiaoyou_ws_url: str = Field(
        default="ws://127.0.0.1:8000/api/v1/ws", description="小优核心 WS 地址"
    )
    master_qq_id: str = Field(default="", description="主人 QQ 号")
    peer_qq_id: str = Field(default="", description="对端 QQ 号")
    group_id: str = Field(default="", description="群号")
    persona_filename: str = Field(default="", description="人格配置文件名")
    default_reference_audio: str = Field(default="", description="默认参考音频路径")
    default_model_provider: str = Field(default="deepseek", description="默认模型提供商")
    default_model_name: str = Field(default="", description="默认模型名")

    model_config = SettingsConfigDict(extra="allow")


class MultiQQConfig(BaseSettings):
    """多 QQ 适配器配置。

    收敛来源：clients/bots/multi_qq_config.json + 环境变量覆盖
    """

    roles: Dict[str, MultiQQRoleConfig] = Field(
        default_factory=dict, description="角色 ID → 角色配置映射"
    )

    model_config = SettingsConfigDict(extra="allow")


_multi_qq_config_cache: Optional[MultiQQConfig] = None
_multi_qq_lock = threading.Lock()


def get_multi_qq_config() -> MultiQQConfig:
    """获取多 QQ 适配器配置单例（带缓存）。

    优先级：环境变量 > clients/bots/multi_qq_config.json > 默认值
    """
    global _multi_qq_config_cache
    if _multi_qq_config_cache is not None:
        return _multi_qq_config_cache

    with _multi_qq_lock:
        if _multi_qq_config_cache is not None:
            return _multi_qq_config_cache

        # JSON 文件路径（统一用项目根目录解析，避免脆弱的 parents[4]）
        json_path = _get_project_root() / "clients" / "bots" / "multi_qq_config.json"
        roles_data: Dict[str, Any] = {}
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    raw = json.load(f) or {}
                    if isinstance(raw, dict):
                        for role_id, role_cfg in raw.items():
                            if not isinstance(role_cfg, dict):
                                continue
                            role_cfg = dict(role_cfg)
                            role_cfg.setdefault("role_id", role_id)
                            roles_data[role_id] = role_cfg
            except Exception as e:
                from core.utils.logger import get_logger
                get_logger("config.multi_qq").warning(
                    "加载 multi_qq_config.json 失败: %s", e
                )

        # 环境变量覆盖（保持与 multi_qq_adapter.py 原逻辑一致）
        master_qq_id = os.getenv("XIAOYOU_QQ_MASTER_ID", "").strip()
        xiaoyou_access_token = os.getenv("XIAOYOU_ACCESS_TOKEN", "").strip()
        napcat_access_token = os.getenv("NAPCAT_ACCESS_TOKEN", "").strip()
        group_id = os.getenv("XIAOYOU_QQ_GROUP_ID", "").strip()
        # 向后兼容:aveline/ling 用旧 env var 名
        aveline_qq = os.getenv("XIAOYOU_QQ_BOT_NUMBER", "").strip()
        ling_qq = os.getenv("XIAOYOU_QQ_BOT_NUMBER_LING", "").strip()

        # N 角色通用:收集所有角色的 QQ 号(从 env var)
        role_qq_from_env = {
            "aveline": aveline_qq,
            "ling": ling_qq,
        }
        for env_key, env_val in os.environ.items():
            if env_key.startswith("XIAOYOU_QQ_BOT_NUMBER_"):
                role_suffix = env_key[len("XIAOYOU_QQ_BOT_NUMBER_"):].lower()
                if role_suffix and env_val.strip():
                    role_qq_from_env[role_suffix] = env_val.strip()

        for role_id, role_cfg in roles_data.items():
            if master_qq_id and not role_cfg.get("master_qq_id"):
                role_cfg["master_qq_id"] = master_qq_id
            if group_id and not role_cfg.get("group_id"):
                role_cfg["group_id"] = group_id
            # access_token 字段不在 MultiQQRoleConfig 里，但保留在 dict 中
            # 以便向后兼容 QQAdapterConfig.from_dict 的调用方式
            if xiaoyou_access_token and not role_cfg.get("xiaoyou_access_token"):
                role_cfg["xiaoyou_access_token"] = xiaoyou_access_token
            if napcat_access_token and not role_cfg.get("napcat_access_token"):
                role_cfg["napcat_access_token"] = napcat_access_token
            # peer_qq_id 自动填充:取第一个其他角色的 own QQ(向后兼容原双角色逻辑)
            # 原逻辑:aveline 的 peer = ling_qq, ling 的 peer = aveline_qq
            # N 角色系统:遍历 role_qq_from_env,选第一个非自己的 QQ 填入 peer_qq_id
            # (角色自己的 QQ 号不存到 config,仅用于填充其他角色的 peer_qq_id)
            if not role_cfg.get("peer_qq_id"):
                for other_role_id, other_own_qq in role_qq_from_env.items():
                    if other_role_id == role_id:
                        continue
                    if other_own_qq:
                        role_cfg["peer_qq_id"] = other_own_qq
                        break

        # 构造 pydantic model（保留原始 dict 字段供 QQAdapterConfig.from_dict 使用）
        roles: Dict[str, MultiQQRoleConfig] = {}
        for role_id, role_cfg in roles_data.items():
            try:
                roles[role_id] = MultiQQRoleConfig(**role_cfg)
            except Exception as e:
                from core.utils.logger import get_logger
                get_logger("config.multi_qq").warning(
                    "构造 MultiQQRoleConfig[%s] 失败: %s", role_id, e
                )

        _multi_qq_config_cache = MultiQQConfig(roles=roles)
        # 同时保留原始 dict 以兼容 QQAdapterConfig.from_dict 的调用方式
        _multi_qq_config_cache._raw_dict = roles_data  # type: ignore[attr-defined]
        return _multi_qq_config_cache


def get_multi_qq_role_config(role_id: str) -> Optional[MultiQQRoleConfig]:
    """获取指定角色的 QQ 配置。"""
    return get_multi_qq_config().roles.get(role_id)


def get_multi_qq_raw_dict() -> Dict[str, Any]:
    """获取多 QQ 配置的原始 dict（兼容 QQAdapterConfig.from_dict 的调用方式）。

    P2-2: 这是一个过渡桥接函数，待 QQAdapterConfig 也迁移到 pydantic 后可移除。
    """
    cfg = get_multi_qq_config()
    return getattr(cfg, "_raw_dict", {}) or {rid: rc.model_dump() for rid, rc in cfg.roles.items()}


def reset_adapter_settings_cache() -> None:
    """重置所有适配器配置缓存（主要用于测试）。"""
    global _asr_settings_cache, _telegram_settings_cache, _multi_qq_config_cache
    with _asr_lock, _telegram_lock, _multi_qq_lock:
        _asr_settings_cache = None
        _telegram_settings_cache = None
        _multi_qq_config_cache = None
