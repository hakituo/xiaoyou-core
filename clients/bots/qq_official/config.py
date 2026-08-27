"""
QQ官方机器人配置类
基于QQ开放平台API v2
"""

import json
import logging
import os
from dataclasses import dataclass, field, fields

logger = logging.getLogger("QQOfficial")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "..", ".."))


def _parse_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v or "").strip().lower()
    if not s:
        return False
    if s in {"1", "true", "yes", "y", "on", "enable", "enabled", "开启"}:
        return True
    if s in {"0", "false", "no", "n", "off", "disable", "disabled", "关闭"}:
        return False
    return bool(v)


@dataclass
class QQOfficialConfig:
    """QQ官方机器人配置"""
    # 机器人身份
    app_id: str = ""
    app_secret: str = ""
    
    # 机器人信息
    role_id: str = ""
    role_name: str = ""
    
    # 小悠后端连接
    xiaoyou_ws_url: str = "ws://127.0.0.1:8000/api/v1/ws"
    xiaoyou_http_base_url: str = ""
    xiaoyou_access_token: str = ""
    
    # 主人QQ号
    master_qq_id: str = ""
    
    # 人设配置
    persona_filename: str = ""
    default_reference_audio: str = ""
    default_model_provider: str = ""
    default_model_name: str = ""
    deepseek_api_key_env: str = ""  # 环境变量名，用于获取DeepSeek API key
    
    # 回复模式
    reply_mode: str = "at_only"  # at_only / all
    reply_voice_only: bool = False
    
    # 消息处理
    qq_strip_markdown: bool = True
    qq_max_bubble_len: int = 150
    qq_min_split_len: int = 40
    
    # 打字延迟
    qq_typing_delay_per_char_seconds: float = 0.25
    qq_typing_delay_min_seconds: float = 0.5
    qq_typing_delay_max_seconds: float = 7.5
    
    # 环境
    sandbox_mode: bool = True  # 沙箱模式
    
    # 超时设置
    http_timeout_seconds: float = 60.0
    
    # 用户配置覆盖
    user_overrides: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict, role_id: str = "") -> "QQOfficialConfig":
        """从字典创建配置"""
        kwargs = {"role_id": str(role_id or "")}
        for f in fields(cls):
            if f.name == "role_id":
                continue
            if f.name not in d:
                continue
            val = d[f.name]
            if f.type in (bool, "bool") and not isinstance(val, bool):
                val = _parse_bool(val)
            elif f.type in (int, "int") and not isinstance(val, int):
                try:
                    val = int(val)
                except (ValueError, TypeError):
                    pass
            elif f.type in (float, "float") and not isinstance(val, (int, float)):
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    pass
            elif f.type in (str, "str") and val is not None:
                val = str(val).strip()
            kwargs[f.name] = val
        return cls(**kwargs)

    @classmethod
    def from_env(cls, role_id: str = "") -> "QQOfficialConfig":
        """从环境变量和配置文件加载"""
        from dotenv import load_dotenv

        env_path = os.path.join(PROJECT_ROOT, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
        else:
            load_dotenv()

        cfg = {}
        
        # 从配置文件加载
        config_file = os.path.join(BASE_DIR, "..", "config", "config_official.json")
        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    raw_cfg = json.load(f)
                if isinstance(raw_cfg, dict):
                    cfg.update(raw_cfg)
            except Exception as e:
                logger.error(f"读取官方机器人配置失败: {e}")

        # 角色配置
        if role_id:
            role_file = os.path.join(BASE_DIR, "..", "config", f"config_official_{role_id}.json")
            if os.path.exists(role_file):
                try:
                    with open(role_file, "r", encoding="utf-8") as f:
                        raw_role = json.load(f)
                    if isinstance(raw_role, dict):
                        cfg.update(raw_role)
                except Exception as e:
                    logger.error(f"读取角色配置失败 ({role_id}): {e}")

        cfg["role_id"] = role_id

        # 环境变量映射
        env_mappings = {
            "app_id": ["QQ_OFFICIAL_APP_ID"],
            "app_secret": ["QQ_OFFICIAL_APP_SECRET"],
            "master_qq_id": ["QQ_OFFICIAL_MASTER_QQ_ID", "XIAOYOU_QQ_MASTER_ID"],
            "xiaoyou_access_token": ["XIAOYOU_ACCESS_TOKEN"],
            "persona_filename": ["QQ_OFFICIAL_PERSONA_FILE"],
            "sandbox_mode": ["QQ_OFFICIAL_SANDBOX"],
        }
        
        for cfg_key, env_names in env_mappings.items():
            for env_name in env_names:
                val = os.getenv(env_name)
                if val is not None:
                    cfg[cfg_key] = val
                    break

        return cls.from_dict(cfg, role_id=role_id)

    def to_dict(self) -> dict:
        """转换为字典"""
        d = {}
        for f in fields(self):
            if f.name.startswith("_"):
                continue
            d[f.name] = getattr(self, f.name)
        return d
