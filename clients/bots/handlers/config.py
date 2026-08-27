import os
import json
from typing import Any, Dict

from clients.bots.handlers.base import BaseHandler
from clients.bots.qq.settings import (
    CONFIG_FILE,
    DEFAULT_MODEL_PROVIDER,
    DEFAULT_MODEL_NAME,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_REFERENCE_AUDIO,
    DEFAULT_PERSONA_FILENAME,
    DEFAULT_PERSONA_FILE,
    OPENCLAW_MODEL,
    PUBLIC_PERSONA_FILE,
    logger,
)

class ConfigHandler(BaseHandler):
    """
    Handles configuration, session preferences, and user overrides.
    """

    def make_cloud_model_hint(self, provider: str, model_name: str, key_alias: str = None) -> str:
        """生成云端模型提示
        
        支持两种格式：
        1. cloud:provider:model（传统格式）
        2. cloud:provider:key_alias:model（多API key格式）
        """
        provider = str(provider or "").strip()
        model_name = str(model_name or "").strip()
        key_alias = str(key_alias or "").strip() or None
        
        if not provider or not model_name:
            return ""
        if provider == "local":
            return ""
        
        # 如果model_name已经包含完整的cloud:格式，直接返回
        if model_name.startswith("cloud:"):
            return model_name
        
        # 生成模型提示
        if key_alias:
            return f"cloud:{provider}:{key_alias}:{model_name}"
        else:
            return f"cloud:{provider}:{model_name}"

    async def get_session_prefs(self, session_id: str, qq_user_id: str) -> Dict[str, Any]:
        if session_id in self.adapter._session_prefs:
            cached = self.adapter._session_prefs[session_id]
            logger.info(f"[get_session_prefs] 缓存命中: session={session_id}, persona={cached.get('persona_filename')}, model={cached.get('chat_model')}")
            return cached

        override = {}
        override_key = ""
        try:
            # 双QQ模式：user_overrides 的 key 包含 role_id 以区分不同角色
            role_id = str(getattr(self.adapter.cfg, "role_id", "") or "").strip()
            if role_id:
                override_key = f"{qq_user_id}__{role_id}"
                override = self.adapter._user_overrides.get(override_key) or {}
            else:
                # 单QQ模式：直接用 qq_user_id 作为 key
                override_key = str(qq_user_id)
                override = self.adapter._user_overrides.get(override_key) or {}
        except Exception:
            override = {}
        if not isinstance(override, dict):
            override = {}

        provider = str(override.get("model_provider") or DEFAULT_MODEL_PROVIDER or "").strip()
        model_name = str(override.get("model_name") or DEFAULT_MODEL_NAME or "").strip()
        image_model = str(override.get("image_model") or DEFAULT_IMAGE_MODEL or "").strip()

        # 多QQ模式（role_id 存在时）：persona_filename、reference_audio、模型 以 adapter 自身配置为主
        # adapter 自身配置是源头（来自 multi_qq_config.json），不是 fallback
        own_persona = str(getattr(self.adapter.cfg, "persona_filename", "") or "").strip()
        own_ref_audio = str(getattr(self.adapter.cfg, "default_reference_audio", "") or "").strip()
        own_model_provider = str(getattr(self.adapter.cfg, "default_model_provider", "") or "").strip()
        own_model_name = str(getattr(self.adapter.cfg, "default_model_name", "") or "").strip()

        if role_id:
            # 双QQ模式：adapter 自身配置优先，override 只用于用户手动切换过的可变设置
            reference_audio = own_ref_audio or str(override.get("reference_audio") or DEFAULT_REFERENCE_AUDIO or "").strip()
            persona_filename = own_persona or str(override.get("persona_filename") or DEFAULT_PERSONA_FILENAME or "").strip()
            provider = own_model_provider or str(override.get("model_provider") or DEFAULT_MODEL_PROVIDER or "").strip()
            model_name = own_model_name or str(override.get("model_name") or DEFAULT_MODEL_NAME or "").strip()
        else:
            # 单QQ模式：override 优先（用户可能通过 /切人设 /切模型 切换过）
            reference_audio = str(override.get("reference_audio") or own_ref_audio or DEFAULT_REFERENCE_AUDIO or "").strip()
            persona_filename = str(override.get("persona_filename") or own_persona or DEFAULT_PERSONA_FILENAME or "").strip()
            provider = str(override.get("model_provider") or own_model_provider or DEFAULT_MODEL_PROVIDER or "").strip()
            model_name = str(override.get("model_name") or own_model_name or DEFAULT_MODEL_NAME or "").strip()

        # [DEBUG] 关键日志：定位 persona_filename 和模型来源
        logger.info(
            f"[get_session_prefs] session={session_id}, qq_user_id={qq_user_id}, "
            f"role_id={role_id!r}, override_key={override_key!r}, "
            f"override_persona={override.get('persona_filename')!r}, "
            f"own_persona={own_persona!r}, final_persona={persona_filename!r}, "
            f"own_model={own_model_provider}/{own_model_name!r}, "
            f"override_model={override.get('model_provider')}/{override.get('model_name')!r}, "
            f"final_model={provider}/{model_name!r}"
        )

        openclaw_model = str(override.get("openclaw_model") or OPENCLAW_MODEL or "").strip()
        reply_voice_only = override.get("reply_voice_only")
        llm_enabled = override.get("llm_enabled")
        t2i_mode = override.get("t2i_mode")
        session_tts_enabled = override.get("session_tts_enabled")
        mode = str(override.get("mode") or "normal").strip().lower() or "normal"
        bionic_delay = override.get("bionic_delay")
        debug_mode = override.get("debug_mode")

        if reply_voice_only is None or reply_voice_only == "":
            reply_voice_only = getattr(self.adapter, "reply_voice_only", False)

        if not self.adapter._is_master(qq_user_id):
            is_peer_bot = bool(
                getattr(self.adapter.cfg, "peer_qq_id", "")
                and qq_user_id == str(getattr(self.adapter.cfg, "peer_qq_id", ""))
            )
            if is_peer_bot:
                # 对方bot私聊：使用adapter自身persona（双QQ模式下每个角色有自己的persona）
                if not persona_filename:
                    persona_filename = own_persona or DEFAULT_PERSONA_FILE
            else:
                # 非主人非对方bot：使用公共人设
                persona_filename = PUBLIC_PERSONA_FILE
            reply_voice_only = False
        else:
            if not persona_filename:
                persona_filename = own_persona or DEFAULT_PERSONA_FILE

        prefs = {
            "model_provider": provider,
            "model_name": model_name,
            "chat_model": self.make_cloud_model_hint(provider, model_name),
            "image_model": image_model,
            "reference_audio": reference_audio,
            "persona_filename": persona_filename,
            "openclaw_model": openclaw_model,
            "reply_voice_only": bool(reply_voice_only),
            "llm_enabled": True if llm_enabled is None else bool(llm_enabled),
            "t2i_mode": bool(t2i_mode),
            "session_tts_enabled": bool(session_tts_enabled),
            "mode": mode,
            "bionic_delay": True if bionic_delay is None else bool(bionic_delay),
            "debug_mode": bool(debug_mode),
        }
        self.adapter._session_prefs[session_id] = prefs
        return prefs

    async def persist_user_override(self, qq_user_id: str, prefs: dict) -> bool:
        async with self.adapter._config_lock:
            try:
                cfg = {}
                if os.path.exists(CONFIG_FILE):
                    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                        cfg = json.load(f)

                if not isinstance(cfg, dict):
                    cfg = {}
                overrides = cfg.get("user_overrides")
                if not isinstance(overrides, dict):
                    overrides = {}

                # 双QQ模式：user_overrides 的 key 包含 role_id 以区分不同角色
                role_id = str(getattr(self.adapter.cfg, "role_id", "") or "").strip()
                if role_id:
                    override_key = f"{qq_user_id}__{role_id}"
                else:
                    override_key = str(qq_user_id)

                overrides[override_key] = {
                    "model_provider": prefs.get("model_provider") or "",
                    "model_name": prefs.get("model_name") or "",
                    "image_model": prefs.get("image_model") or "",
                    "reference_audio": prefs.get("reference_audio") or "",
                    "persona_filename": prefs.get("persona_filename") or "",
                    "openclaw_model": prefs.get("openclaw_model") or "",
                    "reply_voice_only": bool(prefs.get("reply_voice_only")),
                    "llm_enabled": bool(prefs.get("llm_enabled", True)),
                    "t2i_mode": bool(prefs.get("t2i_mode", False)),
                    "session_tts_enabled": bool(prefs.get("session_tts_enabled", False)),
                    "mode": str(prefs.get("mode") or "normal"),
                    "bionic_delay": bool(prefs.get("bionic_delay", True)),
                    "debug_mode": bool(prefs.get("debug_mode", False)),
                }
                cfg["user_overrides"] = overrides

                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)

                self.adapter._user_overrides = overrides
                return True
            except Exception as e:
                logger.error(f"保存配置失败: {e}")
                return False

    async def update_session_config(self, session_id: str, key: str, value: Any) -> bool:
        sid = str(session_id or "").strip()
        if not sid:
            return False
        prefs = self.adapter._session_prefs.get(sid)
        if not isinstance(prefs, dict):
            prefs = {}
            self.adapter._session_prefs[sid] = prefs
        prefs[str(key)] = value
        return True

    async def update_global_config(self, key: str, value: Any) -> bool:
        async with self.adapter._config_lock:
            try:
                cfg = {}
                if os.path.exists(CONFIG_FILE):
                    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                
                if not isinstance(cfg, dict):
                    cfg = {}
                
                cfg[key] = value
                
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                return True
            except Exception as e:
                logger.error(f"更新全局配置失败: {e}")
                return False
