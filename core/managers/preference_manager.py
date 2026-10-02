#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Preference Manager
Manages user preferences, modes, and HCI settings.
"""

import os
import json
import asyncio
from typing import Any

from core.utils.logger import get_logger
from core.utils.async_locks import LazyAsyncLock
from config.integrated_config import get_settings
from core.services.study.persona import StudyPersonaProfile
from core.utils.data_paths import get_user_data_dir

logger = get_logger("PREFERENCE_MANAGER")


class PreferenceManager:
    _instance = None

    def __init__(self):
        self.settings = get_settings()
        self.study_persona_profile = StudyPersonaProfile()
        self.prefs_file = self._get_prefs_file_path()
        self.preferences = {
            "mode": "normal",  # normal, privacy, study
            "active_care_enabled": True,
            "response_length": "normal",  # short, normal, long
            "conversation_style": "natural",  # natural, assistant
            "sensitivity": "medium",  # low, medium, high
            "debug_visible": False,
        }
        # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._lock = LazyAsyncLock()
        self._load_preferences()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = PreferenceManager()
        return cls._instance

    def _get_prefs_file_path(self) -> str:
        return str(get_user_data_dir() / "user_preferences.json")

    def _load_preferences(self):
        try:
            if os.path.exists(self.prefs_file):
                with open(self.prefs_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.preferences.update(data)
        except Exception as e:
            logger.error(f"Failed to load preferences: {e}")

    async def save_preferences(self):
        async with self._lock:
            try:
                # Run in executor to avoid blocking
                await asyncio.to_thread(self._save_sync)
            except Exception as e:
                logger.error(f"Failed to save preferences: {e}")

    def _save_sync(self):
        with open(self.prefs_file, "w", encoding="utf-8") as f:
            json.dump(self.preferences, f, ensure_ascii=False, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        return self.preferences.get(key, default)

    async def set(self, key: str, value: Any):
        old_value = self.preferences.get(key)
        self.preferences[key] = value
        await self.save_preferences()
        logger.info(f"Preference updated: {key} = {value}")

        # Emit event
        from core.core_engine.event_bus import get_event_bus, EventTypes

        try:
            await get_event_bus().publish(
                EventTypes.PREFERENCE_CHANGED, key=key, value=value, old_value=old_value
            )
        except Exception as e:
            logger.error(f"Failed to publish preference change event: {e}")

    # --- Convenience Methods ---

    def get_mode(self) -> str:
        return self.preferences.get("mode", "normal")

    async def set_mode(self, mode: str) -> str:
        valid_modes = ["normal", "privacy", "study", "entertainment"]
        if mode not in valid_modes:
            raise ValueError(f"Invalid mode. Choose from {valid_modes}")
        await self.set("mode", mode)
        return mode

    def is_active_care_enabled(self) -> bool:
        return self.preferences.get("active_care_enabled", True)

    async def set_active_care(self, enabled: bool):
        await self.set("active_care_enabled", enabled)

    def get_system_prompt_addition(self) -> str:
        """
        Get prompt instructions based on current preferences.
        """
        mode = self.get_mode()
        length = self.preferences.get("response_length", "normal")
        style = str(
            self.preferences.get("conversation_style", "natural") or "natural"
        ).strip()

        instructions = []

        fixed_name = (
            str(getattr(self.settings, "user", None).display_name or "").strip()
            if getattr(self.settings, "user", None)
            else ""
        )
        if fixed_name:
            # instructions.append(
            #     f"用户的称呼固定为“{fixed_name}”，你必须始终这样称呼用户；严禁使用任何其他名字或错别字。"
            # )
            pass
        else:
            # instructions.append(
            #     "除非用户明确告诉你他的称呼，否则不要主动使用任何人名称呼用户，更不要编造或改写用户名字。"
            # )
            pass

        # instructions.append(
        #     "默认使用‘你’进行称呼与指代；除非用户明确要求使用敬语，或用户全程主动使用‘您/请您’，否则严禁使用‘您’。"
        # )
        pass

        if mode == "privacy":
            instructions.append(
                "当前处于【私密模式】。请注意：不要将任何对话内容上传到云端，保持回复简短且不涉及敏感个人信息。"
            )
        elif mode == "study":
            instructions.append(self.study_persona_profile.build_mode_instruction())

        if length == "short":
            instructions.append("请保持回复非常简短，直击要点。")
        elif length == "long":
            instructions.append("可以进行详细的解释和展开。")

        if mode == "normal" and style == "natural" and length != "long":
            # User requested removal of verbose SimPO instructions
            pass

        # Memory Humanization (HCI Phase 2)
        # instructions.append(
        #     "\n[记忆引用协议]\n"
        #     '仅当 Context 里确实有对应记忆时才允许引用；没有就不要说"我记得"、更不要编造。'
        #     "当你引用记忆时，请尽量使用拟人化的不确定语气，例如："
        #     "“我记得你上次提到过...”、“好像你之前说过...”、“如果不弄错的话...”。"
        #     "这能让对话更自然，也为你可能记错留有余地。"
        # ) # User requested removal

        return "\n".join(instructions)


def get_preference_manager() -> PreferenceManager:
    return PreferenceManager.get_instance()
