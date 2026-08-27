import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler


class SafeRotatingFileHandler(RotatingFileHandler):
    """Windows 安全的 RotatingFileHandler，轮转失败时不会崩溃"""

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            # Windows 下文件被其他进程占用时，直接截断当前日志继续写入
            try:
                if self.stream:
                    self.stream.close()
                    self.stream = None
                # 尝试以写模式重新打开（截断）
                with open(self.baseFilename, "w", encoding=self.encoding):
                    pass
                self.stream = self._open()
            except Exception:
                pass

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOTS_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "..", ".."))

env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()

_HAS_STATUS_RENDERER = False
generate_dashboard_overview_image = None
generate_dashboard_detail_image = None
generate_model_list_image = None
generate_persona_list_image = None
generate_voice_list_image = None
generate_help_image = None

try:
    from clients.bots.utils.status_renderer import (
        generate_dashboard_overview_image,
        generate_dashboard_detail_image,
        generate_model_list_image,
        generate_persona_list_image,
        generate_voice_list_image,
        generate_help_image,
    )

    _HAS_STATUS_RENDERER = True
except Exception:
    try:
        sys.path.append(os.path.join(BASE_DIR, "..", "..", ".."))
        status_renderer = __import__(
            "clients.bots.utils.status_renderer",
            fromlist=[
                "generate_dashboard_overview_image",
                "generate_dashboard_detail_image",
                "generate_model_list_image",
                "generate_persona_list_image",
                "generate_voice_list_image",
                "generate_help_image",
            ],
        )
        generate_dashboard_overview_image = getattr(status_renderer, "generate_dashboard_overview_image", None)
        generate_dashboard_detail_image = getattr(status_renderer, "generate_dashboard_detail_image", None)
        generate_model_list_image = getattr(status_renderer, "generate_model_list_image", None)
        generate_persona_list_image = getattr(status_renderer, "generate_persona_list_image", None)
        generate_voice_list_image = getattr(status_renderer, "generate_voice_list_image", None)
        generate_help_image = getattr(status_renderer, "generate_help_image", None)
        _HAS_STATUS_RENDERER = True
    except Exception:
        _HAS_STATUS_RENDERER = False

logger = logging.getLogger("QQAdapter")
logger.setLevel(logging.INFO)
logger.handlers.clear()
logger.propagate = False

_fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
_stdout = logging.StreamHandler(sys.stdout)
_stdout.setFormatter(_fmt)
logger.addHandler(_stdout)

_log_dir = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_path = os.path.join(_log_dir, "qq_adapter.log")
_file = SafeRotatingFileHandler(_log_path, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8", delay=True)
_file.setFormatter(_fmt)
logger.addHandler(_file)

DEFAULT_PERSONA_FILE = os.path.join(
    PROJECT_ROOT,
    "core",
    "character",
    "configs",
    "qq",
    "Aveline_QQ_Master.json",
)

DEFAULT_CONFIG = {
    "napcat_ws_url": "ws://127.0.0.1:3001",
    "xiaoyou_ws_url": "ws://127.0.0.1:8000/api/v1/ws",
    "access_token": "",
    "napcat_access_token": "",
    "xiaoyou_access_token": "",
    "master_qq_id": "",
    "public_persona_file": "",
    "reply_voice_only": False,
    "temp_images_ttl_seconds": 24 * 3600,
    "temp_images_max_files": 300,
    "session_idle_seconds": 30 * 60,
    "qq_stream_split": True,
    "qq_stream_comma_split_probability": 0.72,
    "qq_strip_markdown": True,
    "qq_stream_long_threshold": 60,
    "qq_typing_delay_per_char_seconds": 0.25,
    "qq_typing_delay_min_seconds": 0.5,
    "qq_typing_delay_max_seconds": 7.5,
    "qq_typing_delay_short_text_threshold": 4,
    "qq_typing_delay_short_text_factor": 0.85,
    "qq_typing_delay_random_min_factor": 0.9,
    "qq_typing_delay_random_max_factor": 1.35,
    "qq_typing_delay_surprise_probability": 0.0,
    "qq_typing_delay_surprise_min_seconds": 1,
    "qq_typing_delay_surprise_max_seconds": 3,
    "qq_typing_delay_use_bionic_profile": True,
    "qq_typing_delay_bionic_profile_ttl_seconds": 180,
    "qq_auto_meme_enabled": False,
    "qq_auto_meme_base_probability": 0.16,
    "qq_auto_meme_keyword_bonus": 0.2,
    "qq_auto_meme_emotion_bonus": 0.18,
    "qq_auto_meme_exclaim_bonus": 0.08,
    "qq_auto_meme_max_probability": 0.7,
    "qq_auto_meme_cooldown_seconds": 35,
    "qq_auto_meme_repeat_penalty_seconds": 180,
    "qq_auto_meme_delay_min_seconds": 1.2,
    "qq_auto_meme_delay_max_seconds": 4.8,
    "remote_screenshot_enabled": False,
    "remote_screenshot_cooldown_seconds": 8,
    "remote_file_ops_enabled": False,
    "openclaw_enabled": False,
    "openclaw_http_base_url": "http://127.0.0.1:18789",
    "openclaw_api_key": "",
    "openclaw_model": "",
    "openclaw_timeout_seconds": 120,
    "openclaw_retry_attempts": 2,
    "openclaw_retry_base_delay_seconds": 0.8,
    "max_concurrent_messages": 6,
}

CONFIG_FILE = os.path.join(BASE_DIR, "..", "config", "config.json")
config = dict(DEFAULT_CONFIG)
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            raw_cfg = json.load(f)
        if isinstance(raw_cfg, dict):
            config.update(raw_cfg)
    except Exception as e:
        logger.error(f"读取配置失败: {e}")

NAPCAT_WS_URL = config.get("napcat_ws_url", "ws://127.0.0.1:3001")
XIAOYOU_WS_URL = config.get("xiaoyou_ws_url", "ws://127.0.0.1:6789")


def _normalize_loopback(url: str) -> str:
    u = str(url or "").strip()
    if not u:
        return u
    return u.replace("ws://localhost", "ws://127.0.0.1").replace("wss://localhost", "wss://127.0.0.1")


NAPCAT_WS_URL = _normalize_loopback(NAPCAT_WS_URL)
XIAOYOU_WS_URL = _normalize_loopback(XIAOYOU_WS_URL)
ENABLE_QQ_FACE_INJECTION = bool(config.get("enable_qq_face_injection", True))
ENABLE_QQ_VISION = bool(config.get("enable_qq_vision", True))
ENABLE_QQ_VOICE = bool(config.get("enable_qq_voice", True))
AUTO_TTS_FOR_VOICE_INPUT = bool(config.get("auto_tts_for_voice_input", True))


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

NAPCAT_ACCESS_TOKEN = str(
    os.getenv("NAPCAT_ACCESS_TOKEN")
    or config.get("napcat_access_token")
    or config.get("access_token")
    or ""
).strip()
XIAOYOU_ACCESS_TOKEN = str(
    os.getenv("XIAOYOU_ACCESS_TOKEN")
    or config.get("xiaoyou_access_token")
    or config.get("access_token")
    or ""
).strip()

MASTER_QQ_ID = str(os.getenv("XIAOYOU_QQ_MASTER_ID") or config.get("master_qq_id") or "").strip()
PUBLIC_PERSONA_FILE = (
    str(os.getenv("XIAOYOU_QQ_PUBLIC_PERSONA_FILE") or config.get("public_persona_file") or "").strip()
    or DEFAULT_PERSONA_FILE
)

REPLY_VOICE_ONLY = _parse_bool(os.getenv("XIAOYOU_QQ_REPLY_VOICE_ONLY") or config.get("reply_voice_only"))
QQ_STREAM_SPLIT = _parse_bool(os.getenv("XIAOYOU_QQ_STREAM_SPLIT") or config.get("qq_stream_split"))
QQ_STREAM_COMMA_SPLIT_PROBABILITY = float(
    os.getenv("XIAOYOU_QQ_STREAM_COMMA_SPLIT_PROBABILITY")
    or config.get("qq_stream_comma_split_probability")
    or 0.4
)
QQ_MAX_BUBBLE_LEN = int(
    os.getenv("XIAOYOU_QQ_MAX_BUBBLE_LEN")
    or config.get("qq_max_bubble_len")
    or 150
)
QQ_MIN_SPLIT_LEN = int(
    os.getenv("XIAOYOU_QQ_MIN_SPLIT_LEN")
    or config.get("qq_min_split_len")
    or 40
)
QQ_STRIP_MARKDOWN = _parse_bool(os.getenv("XIAOYOU_QQ_STRIP_MARKDOWN") or config.get("qq_strip_markdown"))
QQ_STREAM_LONG_THRESHOLD = int(os.getenv("XIAOYOU_QQ_STREAM_LONG_THRESHOLD") or config.get("qq_stream_long_threshold") or 240)
QQ_TYPING_DELAY_PER_CHAR_SECONDS = float(
    os.getenv("XIAOYOU_QQ_TYPING_DELAY_PER_CHAR_SECONDS")
    or config.get("qq_typing_delay_per_char_seconds")
    or 0.18
)
QQ_TYPING_DELAY_MIN_SECONDS = float(
    os.getenv("XIAOYOU_QQ_TYPING_DELAY_MIN_SECONDS")
    or config.get("qq_typing_delay_min_seconds")
    or 1.6
)
QQ_TYPING_DELAY_MAX_SECONDS = float(
    os.getenv("XIAOYOU_QQ_TYPING_DELAY_MAX_SECONDS")
    or config.get("qq_typing_delay_max_seconds")
    or 7.5
)
QQ_TYPING_DELAY_SHORT_TEXT_THRESHOLD = int(
    os.getenv("XIAOYOU_QQ_TYPING_DELAY_SHORT_TEXT_THRESHOLD")
    or config.get("qq_typing_delay_short_text_threshold")
    or 4
)
QQ_TYPING_DELAY_SHORT_TEXT_FACTOR = float(
    os.getenv("XIAOYOU_QQ_TYPING_DELAY_SHORT_TEXT_FACTOR")
    or config.get("qq_typing_delay_short_text_factor")
    or 0.85
)
QQ_TYPING_DELAY_RANDOM_MIN_FACTOR = float(
    os.getenv("XIAOYOU_QQ_TYPING_DELAY_RANDOM_MIN_FACTOR")
    or config.get("qq_typing_delay_random_min_factor")
    or 0.9
)
QQ_TYPING_DELAY_RANDOM_MAX_FACTOR = float(
    os.getenv("XIAOYOU_QQ_TYPING_DELAY_RANDOM_MAX_FACTOR")
    or config.get("qq_typing_delay_random_max_factor")
    or 1.35
)
QQ_TYPING_DELAY_SURPRISE_PROBABILITY = float(
    os.getenv("XIAOYOU_QQ_TYPING_DELAY_SURPRISE_PROBABILITY")
    or config.get("qq_typing_delay_surprise_probability")
    or 0.0
)
QQ_TYPING_DELAY_SURPRISE_MIN_SECONDS = float(
    os.getenv("XIAOYOU_QQ_TYPING_DELAY_SURPRISE_MIN_SECONDS")
    or config.get("qq_typing_delay_surprise_min_seconds")
    or 1
)
QQ_TYPING_DELAY_SURPRISE_MAX_SECONDS = float(
    os.getenv("XIAOYOU_QQ_TYPING_DELAY_SURPRISE_MAX_SECONDS")
    or config.get("qq_typing_delay_surprise_max_seconds")
    or 3
)
QQ_TYPING_DELAY_USE_BIONIC_PROFILE = _parse_bool(
    os.getenv("XIAOYOU_QQ_TYPING_DELAY_USE_BIONIC_PROFILE")
    or config.get("qq_typing_delay_use_bionic_profile")
)
QQ_TYPING_DELAY_BIONIC_PROFILE_TTL_SECONDS = int(
    os.getenv("XIAOYOU_QQ_TYPING_DELAY_BIONIC_PROFILE_TTL_SECONDS")
    or config.get("qq_typing_delay_bionic_profile_ttl_seconds")
    or 180
)

ENABLE_LLM_INTENT_ROUTER = bool(config.get("enable_llm_intent_router", False))
# [Fix] 提高意图识别置信度阈值，减少中文闲聊误判为命令（原值0.6过低）
LLM_INTENT_THRESHOLD = float(config.get("llm_intent_threshold") or 0.72)

DEFAULT_MODEL_PROVIDER = str(config.get("default_model_provider") or "")
DEFAULT_MODEL_NAME = str(config.get("default_model_name") or "")
DEFAULT_IMAGE_MODEL = str(config.get("default_image_model") or "")
DEFAULT_PERSONA_FILENAME = str(config.get("default_persona_filename") or "")
DEFAULT_REFERENCE_AUDIO = str(config.get("default_reference_audio") or "")

USER_OVERRIDES = config.get("user_overrides") if isinstance(config.get("user_overrides"), dict) else {}


def _ws_to_http_base(ws_url: str) -> str:
    try:
        from urllib.parse import urlparse

        p = urlparse(str(ws_url or "").strip())
        if not p.scheme or not p.netloc:
            return "http://127.0.0.1:8000"
        if p.scheme == "ws":
            scheme = "http"
        elif p.scheme == "wss":
            scheme = "https"
        else:
            scheme = p.scheme
        return f"{scheme}://{p.netloc}"
    except Exception:
        return "http://127.0.0.1:8000"


XIAOYOU_HTTP_BASE_URL = str(config.get("xiaoyou_http_base_url") or "").strip() or _ws_to_http_base(XIAOYOU_WS_URL)
HTTP_TIMEOUT_SECONDS = float(config.get("http_timeout_seconds") or 60)
VISION_TIMEOUT_SECONDS = float(config.get("vision_timeout_seconds") or 180)
STT_TIMEOUT_SECONDS = float(config.get("stt_timeout_seconds") or 60)
OPENCLAW_ENABLED = _parse_bool(os.getenv("OPENCLAW_ENABLED") or config.get("openclaw_enabled"))
OPENCLAW_HTTP_BASE_URL = str(
    os.getenv("OPENCLAW_HTTP_BASE_URL")
    or config.get("openclaw_http_base_url")
    or "http://127.0.0.1:18789"
).strip()
OPENCLAW_API_KEY = str(os.getenv("OPENCLAW_API_KEY") or config.get("openclaw_api_key") or "").strip()
OPENCLAW_MODEL = str(os.getenv("OPENCLAW_MODEL") or config.get("openclaw_model") or "").strip()
OPENCLAW_TIMEOUT_SECONDS = float(
    os.getenv("OPENCLAW_TIMEOUT_SECONDS") or config.get("openclaw_timeout_seconds") or 120
)
OPENCLAW_RETRY_ATTEMPTS = int(
    os.getenv("OPENCLAW_RETRY_ATTEMPTS") or config.get("openclaw_retry_attempts") or 2
)
OPENCLAW_RETRY_BASE_DELAY_SECONDS = float(
    os.getenv("OPENCLAW_RETRY_BASE_DELAY_SECONDS")
    or config.get("openclaw_retry_base_delay_seconds")
    or 0.8
)
REMOTE_SCREENSHOT_ENABLED = _parse_bool(
    os.getenv("XIAOYOU_QQ_REMOTE_SCREENSHOT_ENABLED")
    or config.get("remote_screenshot_enabled")
)
REMOTE_SCREENSHOT_COOLDOWN_SECONDS = float(
    os.getenv("XIAOYOU_QQ_REMOTE_SCREENSHOT_COOLDOWN_SECONDS")
    or config.get("remote_screenshot_cooldown_seconds")
    or 8
)
REMOTE_FILE_OPS_ENABLED = _parse_bool(
    os.getenv("XIAOYOU_QQ_REMOTE_FILE_OPS_ENABLED")
    or config.get("remote_file_ops_enabled")
)

TEMP_IMAGES_TTL_SECONDS = int(config.get("temp_images_ttl_seconds") or 24 * 3600)
TEMP_IMAGES_MAX_FILES = int(config.get("temp_images_max_files") or 300)
SESSION_IDLE_SECONDS = int(config.get("session_idle_seconds") or 30 * 60)
MAX_CONCURRENT_MESSAGES = int(config.get("max_concurrent_messages") or 6)
