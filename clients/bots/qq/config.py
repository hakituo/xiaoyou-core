import json
import logging
import os
from dataclasses import dataclass, field, fields
from urllib.parse import urlparse

logger = logging.getLogger("QQAdapter")

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


def _normalize_loopback(url: str) -> str:
    u = str(url or "").strip()
    if not u:
        return u
    return u.replace("ws://localhost", "ws://127.0.0.1").replace("wss://localhost", "wss://127.0.0.1")


@dataclass
class QQAdapterConfig:
    role_id: str = ""
    role_name: str = ""
    napcat_ws_url: str = "ws://127.0.0.1:3001"
    napcat_access_token: str = ""
    xiaoyou_ws_url: str = "ws://127.0.0.1:8000/api/v1/ws"
    xiaoyou_http_base_url: str = ""
    xiaoyou_access_token: str = ""
    master_qq_id: str = ""  # 从环境变量 XIAOYOU_QQ_MASTER_ID 或配置文件读取，不硬编码
    peer_qq_id: str = ""
    group_id: str = ""
    persona_filename: str = ""
    default_reference_audio: str = ""
    reply_mode: str = "at_only"
    reply_voice_only: bool = False
    enable_qq_face_injection: bool = True
    enable_qq_vision: bool = True
    enable_qq_voice: bool = True
    enable_llm_intent_router: bool = False
    llm_intent_threshold: float = 0.72
    qq_message_buffer_window_seconds: float = 0.35
    qq_message_buffer_max: int = 8
    qq_skip_backend_merge_wait: bool = True
    qq_stream_split: bool = True
    qq_stream_comma_split_probability: float = 0.72
    qq_stream_long_threshold: int = 60
    qq_strip_markdown: bool = True
    qq_max_bubble_len: int = 150
    qq_min_split_len: int = 40
    qq_typing_delay_per_char_seconds: float = 0.25
    qq_typing_delay_min_seconds: float = 0.5
    qq_typing_delay_max_seconds: float = 7.5
    qq_typing_delay_short_text_threshold: int = 4
    qq_typing_delay_short_text_factor: float = 0.85
    qq_typing_delay_random_min_factor: float = 0.9
    qq_typing_delay_random_max_factor: float = 1.35
    qq_typing_delay_surprise_probability: float = 0.0
    qq_typing_delay_surprise_min_seconds: float = 1.0
    qq_typing_delay_surprise_max_seconds: float = 3.0
    qq_typing_delay_use_bionic_profile: bool = True
    qq_typing_delay_bionic_profile_ttl_seconds: int = 180
    qq_auto_meme_base_probability: float = 0.16
    qq_auto_meme_keyword_bonus: float = 0.2
    qq_auto_meme_emotion_bonus: float = 0.18
    qq_auto_meme_exclaim_bonus: float = 0.08
    qq_auto_meme_max_probability: float = 0.7
    qq_auto_meme_cooldown_seconds: float = 35.0
    qq_auto_meme_repeat_penalty_seconds: float = 180.0
    qq_auto_meme_delay_min_seconds: float = 1.2
    qq_auto_meme_delay_max_seconds: float = 4.8
    user_overrides: dict = field(default_factory=dict)
    openclaw_enabled: bool = False
    openclaw_http_base_url: str = "http://127.0.0.1:18789"
    openclaw_api_key: str = ""
    openclaw_model: str = ""
    openclaw_timeout_seconds: float = 120.0
    openclaw_retry_attempts: int = 2
    openclaw_retry_base_delay_seconds: float = 0.8
    http_timeout_seconds: float = 60.0
    vision_timeout_seconds: float = 180.0
    stt_timeout_seconds: float = 60.0
    temp_images_ttl_seconds: int = 24 * 3600
    temp_images_max_files: int = 300
    session_idle_seconds: int = 30 * 60
    max_concurrent_messages: int = 6
    default_model_provider: str = ""
    default_model_name: str = ""
    default_image_model: str = ""
    auto_tts_for_voice_input: bool = True
    remote_screenshot_enabled: bool = False
    remote_screenshot_cooldown_seconds: float = 8.0
    remote_file_ops_enabled: bool = False
    _FIELD_TYPES = None

    @classmethod
    def _get_field_types(cls):
        if cls._FIELD_TYPES is None:
            cls._FIELD_TYPES = {f.name: f.type for f in fields(cls)}
        return cls._FIELD_TYPES

    @staticmethod
    def _ws_to_http_base(ws_url: str) -> str:
        try:
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

    def __post_init__(self):
        self.napcat_ws_url = _normalize_loopback(self.napcat_ws_url)
        self.xiaoyou_ws_url = _normalize_loopback(self.xiaoyou_ws_url)
        if not self.xiaoyou_http_base_url:
            self.xiaoyou_http_base_url = self._ws_to_http_base(self.xiaoyou_ws_url)

    @classmethod
    def from_dict(cls, d: dict, role_id: str = "") -> "QQAdapterConfig":
        ft = cls._get_field_types()
        kwargs = {"role_id": str(role_id or "")}
        for f in fields(cls):
            if f.name == "role_id":
                continue
            if f.name not in d:
                continue
            val = d[f.name]
            expected = ft.get(f.name)
            if expected in (bool, "bool") and not isinstance(val, bool):
                val = _parse_bool(val)
            elif expected in (int, "int") and not isinstance(val, int):
                try:
                    val = int(val)
                except (ValueError, TypeError):
                    pass
            elif expected in (float, "float") and not isinstance(val, (int, float)):
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    pass
            elif expected in (str, "str") and val is not None:
                val = str(val).strip()
            elif expected in (dict, "dict") and isinstance(val, dict):
                pass
            kwargs[f.name] = val
        return cls(**kwargs)

    @classmethod
    def from_env(cls, role_id: str = "") -> "QQAdapterConfig":
        from dotenv import load_dotenv

        env_path = os.path.join(PROJECT_ROOT, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
        else:
            load_dotenv()

        cfg = dict(cls._default_config_dict())
        config_file = os.path.join(BASE_DIR, "..", "config", "config.json")
        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    raw_cfg = json.load(f)
                if isinstance(raw_cfg, dict):
                    cfg.update(raw_cfg)
            except Exception as e:
                logger.error(f"读取配置失败: {e}")

        if role_id:
            role_file = os.path.join(BASE_DIR, "..", "config", f"config_{role_id}.json")
            if os.path.exists(role_file):
                try:
                    with open(role_file, "r", encoding="utf-8") as f:
                        raw_role = json.load(f)
                    if isinstance(raw_role, dict):
                        cfg.update(raw_role)
                except Exception as e:
                    logger.error(f"读取角色配置失败 ({role_id}): {e}")

        cfg["role_id"] = role_id

        env_mappings = {
            "napcat_access_token": ["NAPCAT_ACCESS_TOKEN"],
            "xiaoyou_access_token": ["XIAOYOU_ACCESS_TOKEN"],
            "master_qq_id": ["XIAOYOU_QQ_MASTER_ID"],
            "persona_filename": ["XIAOYOU_QQ_PUBLIC_PERSONA_FILE"],
            "reply_voice_only": ["XIAOYOU_QQ_REPLY_VOICE_ONLY"],
            "qq_message_buffer_window_seconds": ["XIAOYOU_QQ_MESSAGE_BUFFER_WINDOW_SECONDS"],
            "qq_message_buffer_max": ["XIAOYOU_QQ_MESSAGE_BUFFER_MAX"],
            "qq_skip_backend_merge_wait": ["XIAOYOU_QQ_SKIP_BACKEND_MERGE_WAIT"],
            "qq_stream_split": ["XIAOYOU_QQ_STREAM_SPLIT"],
            "qq_stream_comma_split_probability": ["XIAOYOU_QQ_STREAM_COMMA_SPLIT_PROBABILITY"],
            "qq_max_bubble_len": ["XIAOYOU_QQ_MAX_BUBBLE_LEN"],
            "qq_min_split_len": ["XIAOYOU_QQ_MIN_SPLIT_LEN"],
            "qq_strip_markdown": ["XIAOYOU_QQ_STRIP_MARKDOWN"],
            "qq_stream_long_threshold": ["XIAOYOU_QQ_STREAM_LONG_THRESHOLD"],
            "qq_typing_delay_per_char_seconds": ["XIAOYOU_QQ_TYPING_DELAY_PER_CHAR_SECONDS"],
            "qq_typing_delay_min_seconds": ["XIAOYOU_QQ_TYPING_DELAY_MIN_SECONDS"],
            "qq_typing_delay_max_seconds": ["XIAOYOU_QQ_TYPING_DELAY_MAX_SECONDS"],
            "qq_typing_delay_short_text_threshold": ["XIAOYOU_QQ_TYPING_DELAY_SHORT_TEXT_THRESHOLD"],
            "qq_typing_delay_short_text_factor": ["XIAOYOU_QQ_TYPING_DELAY_SHORT_TEXT_FACTOR"],
            "qq_typing_delay_random_min_factor": ["XIAOYOU_QQ_TYPING_DELAY_RANDOM_MIN_FACTOR"],
            "qq_typing_delay_random_max_factor": ["XIAOYOU_QQ_TYPING_DELAY_RANDOM_MAX_FACTOR"],
            "qq_typing_delay_surprise_probability": ["XIAOYOU_QQ_TYPING_DELAY_SURPRISE_PROBABILITY"],
            "qq_typing_delay_surprise_min_seconds": ["XIAOYOU_QQ_TYPING_DELAY_SURPRISE_MIN_SECONDS"],
            "qq_typing_delay_surprise_max_seconds": ["XIAOYOU_QQ_TYPING_DELAY_SURPRISE_MAX_SECONDS"],
            "qq_typing_delay_use_bionic_profile": ["XIAOYOU_QQ_TYPING_DELAY_USE_BIONIC_PROFILE"],
            "qq_typing_delay_bionic_profile_ttl_seconds": ["XIAOYOU_QQ_TYPING_DELAY_BIONIC_PROFILE_TTL_SECONDS"],
            "openclaw_enabled": ["OPENCLAW_ENABLED"],
            "openclaw_http_base_url": ["OPENCLAW_HTTP_BASE_URL"],
            "openclaw_api_key": ["OPENCLAW_API_KEY"],
            "openclaw_model": ["OPENCLAW_MODEL"],
            "openclaw_timeout_seconds": ["OPENCLAW_TIMEOUT_SECONDS"],
            "openclaw_retry_attempts": ["OPENCLAW_RETRY_ATTEMPTS"],
            "openclaw_retry_base_delay_seconds": ["OPENCLAW_RETRY_BASE_DELAY_SECONDS"],
            "remote_screenshot_enabled": ["XIAOYOU_QQ_REMOTE_SCREENSHOT_ENABLED"],
            "remote_screenshot_cooldown_seconds": ["XIAOYOU_QQ_REMOTE_SCREENSHOT_COOLDOWN_SECONDS"],
            "remote_file_ops_enabled": ["XIAOYOU_QQ_REMOTE_FILE_OPS_ENABLED"],
        }
        for cfg_key, env_names in env_mappings.items():
            for env_name in env_names:
                val = os.getenv(env_name)
                if val is not None:
                    cfg[cfg_key] = val
                    break

        if "access_token" in cfg:
            fallback = str(cfg.pop("access_token") or "").strip()
            if not cfg.get("napcat_access_token"):
                cfg["napcat_access_token"] = fallback
            if not cfg.get("xiaoyou_access_token"):
                cfg["xiaoyou_access_token"] = fallback

        if "public_persona_file" in cfg:
            cfg.pop("public_persona_file", None)

        return cls.from_dict(cfg, role_id=role_id)

    @classmethod
    def _default_config_dict(cls) -> dict:
        d = {}
        for f in fields(cls):
            if f.name.startswith("_"):
                continue
            d[f.name] = f.default if f.default is not f.default_factory else f.default_factory()
        return d

    def to_dict(self) -> dict:
        d = {}
        for f in fields(self):
            if f.name.startswith("_"):
                continue
            d[f.name] = getattr(self, f.name)
        return d
