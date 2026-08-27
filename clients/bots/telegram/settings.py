"""Telegram 适配器配置。

从 app.yaml 的 telegram 段和 .env 加载，优先走 pydantic model
（config.settings_adapters.TelegramAdapterSettings），失败时回退到环境变量。
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "..", ".."))

# 加载 .env
env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()


class SafeRotatingFileHandler(RotatingFileHandler):
    """Windows 安全的 RotatingFileHandler，轮转失败时不崩溃。"""

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            try:
                if self.stream:
                    self.stream.close()
                    self.stream = None
                with open(self.baseFilename, "w", encoding=self.encoding):
                    pass
                self.stream = self._open()
            except Exception:
                pass


# 日志配置
logger = logging.getLogger("TelegramAdapter")
logger.setLevel(logging.INFO)
logger.handlers.clear()
logger.propagate = False

_fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
_stdout = logging.StreamHandler(sys.stdout)
_stdout.setFormatter(_fmt)
logger.addHandler(_stdout)

_log_dir = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_path = os.path.join(_log_dir, "telegram_adapter.log")
_file = SafeRotatingFileHandler(_log_path, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8", delay=True)
_file.setFormatter(_fmt)
logger.addHandler(_file)


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


# ============ 通过 pydantic model 统一加载配置 ============

try:
    from config.settings_adapters import get_telegram_adapter_settings

    _tg_settings = get_telegram_adapter_settings()
    ENABLED = _tg_settings.enabled
    TELEGRAM_BOT_TOKEN = _tg_settings.bot_token
    ENABLE_TELEGRAM_VOICE = _tg_settings.enable_voice
    ENABLE_TELEGRAM_VISION = _tg_settings.enable_vision
    STRIP_MARKDOWN = _tg_settings.strip_markdown
    XIAOYOU_HTTP_BASE_URL = _tg_settings.http_base_url
    XIAOYOU_WS_URL = _tg_settings.ws_url
    XIAOYOU_ACCESS_TOKEN = _tg_settings.access_token
    HTTP_TIMEOUT_SECONDS = _tg_settings.http_timeout_seconds
    SESSION_TIMEOUT_MINUTES = _tg_settings.session_timeout_minutes
    MASTER_USER_ID = _tg_settings.master_user_id
    TELEGRAM_PROXY_URL = _tg_settings.proxy_url
    PERSONA_FILENAME = _tg_settings.persona_filename
except Exception as e:
    logger.warning(f"加载 Telegram 适配器配置失败，使用默认值: {e}")
    # 无法读取 app.yaml 时保持关闭，禁止遗留环境变量绕过统一开关。
    ENABLED = False
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    ENABLE_TELEGRAM_VOICE = _parse_bool(os.getenv("ENABLE_TELEGRAM_VOICE", "true"))
    ENABLE_TELEGRAM_VISION = _parse_bool(os.getenv("ENABLE_TELEGRAM_VISION", "true"))
    STRIP_MARKDOWN = _parse_bool(os.getenv("TELEGRAM_STRIP_MARKDOWN", "false"))
    XIAOYOU_HTTP_BASE_URL = os.getenv("XIAOYOU_HTTP_BASE_URL", "http://localhost:8000")
    XIAOYOU_WS_URL = os.getenv("XIAOYOU_WS_URL", "ws://localhost:8000/api/v1/ws")
    XIAOYOU_ACCESS_TOKEN = os.getenv("XIAOYOU_ACCESS_TOKEN", "")
    HTTP_TIMEOUT_SECONDS = int(os.getenv("TELEGRAM_HTTP_TIMEOUT", "60"))
    SESSION_TIMEOUT_MINUTES = int(os.getenv("TELEGRAM_SESSION_TIMEOUT", "30"))
    MASTER_USER_ID = str(os.getenv("TELEGRAM_MASTER_USER_ID", "")).strip()
    TELEGRAM_PROXY_URL = str(os.getenv("TELEGRAM_PROXY_URL", "")).strip()
    PERSONA_FILENAME = str(
        os.getenv("TELEGRAM_PERSONA_FILENAME", "sensitive/Frost.json")
    ).strip()

# 流式断句配置（参照 QQ，但针对 Telegram 频率限制调优）
TG_STREAM_SPLIT = _parse_bool(os.getenv("TG_STREAM_SPLIT", "true"))
TG_MAX_BUBBLE_LEN = int(os.getenv("TG_MAX_BUBBLE_LEN", "150"))
TG_MIN_SPLIT_LEN = int(os.getenv("TG_MIN_SPLIT_LEN", "40"))
TG_STREAM_LONG_THRESHOLD = int(os.getenv("TG_STREAM_LONG_THRESHOLD", "240"))

# 打字延迟（Telegram 频率限制：1条/秒/chat，所以最小延迟设为 1.2s）
TG_TYPING_DELAY_PER_CHAR_SECONDS = float(os.getenv("TG_TYPING_DELAY_PER_CHAR_SECONDS", "0.12"))
TG_TYPING_DELAY_MIN_SECONDS = float(os.getenv("TG_TYPING_DELAY_MIN_SECONDS", "1.2"))
TG_TYPING_DELAY_MAX_SECONDS = float(os.getenv("TG_TYPING_DELAY_MAX_SECONDS", "6.0"))

# 流式增量编辑配置（边收 LLM chunk 边编辑同一条 Telegram 消息）
# 开启后，AI 回复会像 ChatGPT 一样逐字出现在同一条消息里，而不是等全部生成完再一次性发。
# Telegram 编辑消息有频率限制（约 1 次/秒/chat），所以用节流间隔控制。
# 0.8 秒是实测安全下限，比 1.5 秒更"丝滑"，同时不会触发 429。
TG_STREAM_EDIT_ENABLED = _parse_bool(os.getenv("TG_STREAM_EDIT_ENABLED", "false"))
TG_STREAM_EDIT_INTERVAL_SECONDS = float(os.getenv("TG_STREAM_EDIT_INTERVAL_SECONDS", "0.8"))
# 首个 chunk 到达后立即发送（不等节流间隔），让用户尽快看到回复开始
TG_STREAM_EDIT_FIRST_CHUNK_IMMEDIATE = _parse_bool(os.getenv("TG_STREAM_EDIT_FIRST_CHUNK_IMMEDIATE", "true"))
# 流式编辑时单条消息最大长度（超过则停止编辑，等 done 后断句发送剩余部分）
TG_STREAM_EDIT_MAX_LEN = int(os.getenv("TG_STREAM_EDIT_MAX_LEN", "800"))
# 收到 429 Too Many Requests 时的自动退避倍数（每次 429 间隔 *= 此值）
TG_STREAM_EDIT_BACKOFF_MULTIPLIER = float(os.getenv("TG_STREAM_EDIT_BACKOFF_MULTIPLIER", "1.5"))
# 退避后的最大间隔（秒），避免退避太久用户等太久
TG_STREAM_EDIT_BACKOFF_MAX_SECONDS = float(os.getenv("TG_STREAM_EDIT_BACKOFF_MAX_SECONDS", "3.0"))
# 是否在流式编辑期间持续发送"正在输入"状态（让用户感知 AI 在打字）
TG_STREAM_EDIT_TYPING_ACTION = _parse_bool(os.getenv("TG_STREAM_EDIT_TYPING_ACTION", "true"))

# Telegram 消息长度限制
TG_MESSAGE_MAX_LEN = 4096


def load_config():
    """向后兼容接口。"""
    return {}


config = load_config()
