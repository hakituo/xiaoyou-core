"""日志配置加载与日志目录解析。

负责：
- 从集成配置（config.integrated_config）延迟加载日志相关设置
- 将日志目录解析为 ``<base>/YYYY/M/D`` 的按日分层路径
- 确保日志目录存在（延迟初始化一次）
"""
import os
from datetime import datetime
from typing import Any, Dict

# 配置缓存，避免每次都重新加载
_settings_cache = None

# 确保日志目录存在（延迟初始化）
_log_dir_initialized = False


def _get_settings():
    """延迟加载配置，避免循环导入"""
    global _settings_cache
    if _settings_cache is None:
        from config.integrated_config import get_settings
        _settings_cache = get_settings()
    return _settings_cache


def _resolve_daily_log_dir(base_log_dir: str) -> str:
    base = str(base_log_dir or "logs").strip() or "logs"
    now = datetime.now()
    return os.path.join(base, str(now.year), str(now.month), str(now.day))


# 获取日志配置
def get_log_config() -> Dict[str, Any]:
    """从配置加载器获取日志配置"""
    try:
        log_settings = _get_settings().log
        return {
            "log_dir": _resolve_daily_log_dir(log_settings.log_dir),
            "log_level": log_settings.level,
            "use_json": log_settings.use_json_format,
            "rotation_type": log_settings.rotation_type,
            "max_bytes": log_settings.max_bytes,
            "backup_count": log_settings.backup_count,
            "rotation_when": log_settings.rotation_when,
            "rotation_interval": log_settings.rotation_interval,
            "console_level": getattr(log_settings, "console_level", "INFO"),
        }
    except Exception:
        # 如果属性访问失败，使用默认值
        return {
            "log_dir": _resolve_daily_log_dir("./logs/"),
            "log_level": "INFO",
            "use_json": False,
            "rotation_type": "size",
            "max_bytes": 10485760,  # 10MB
            "backup_count": 5,
            "rotation_when": "midnight",
            "rotation_interval": 1,
            "console_level": "INFO",
        }


def ensure_log_dir():
    """确保日志目录存在（幂等）"""
    global _log_dir_initialized
    if _log_dir_initialized:
        return
    log_cfg = get_log_config()
    os.makedirs(log_cfg["log_dir"], exist_ok=True)
    _log_dir_initialized = True
