# -*- coding: utf-8 -*-
"""「persona -> 默认音色」的唯一权威解析入口。

音色配置源始终是 app.yaml 的 ``voice.tts.voice_map``（角色名 -> 火山音色 ID）：

    voice:
      tts:
        voice_map:
          Ling: "S_LvHb6zN62"
          Ye: "S_EbG6m9272"
          Aveline: "S_HbG6m9272"

QQ 端（``clients/bots/qq/voice_service.py``）与 Android（经 persona API 的
``default_voice`` 字段）都从本模块解析，避免各端各抄一份"角色 -> 音色"硬编码表。
历史上 Android 抄了 QQ 的 role_id 映射、却把 fallback 写成"用户全局音色"，
导致Ye/Aveline等未登记角色解析失败，正是重复维护映射表带来的问题。

注意本函数返回的是 **voice_map 的 key（角色名）**，不是音色 ID：
拿到后直接作为 ``voice`` 传给 ``/api/v1/media/tts``，由 TTS 引擎再用 voice_map
换成真正的音色 ID（与 QQ 端传 role_name 的行为完全一致）。
"""

from typing import Any, Dict, Optional


def _normalize(text: Any) -> str:
    """归一化用于匹配的文本：去首尾空白、转小写、去掉所有空格。

    voice_map 里同时存在 ``Aveline`` 和 ``七濑 Aveline`` 两种写法，归一化后都能命中。
    """
    return str(text or "").strip().lower().replace(" ", "")


def load_voice_map() -> Dict[str, str]:
    """读取 app.yaml 的 ``voice.tts.voice_map``（不缓存在本层，避免热更新失效）。"""
    try:
        from config.integrated_config import get_settings

        tts_config = get_settings().voice.tts
        extra = getattr(tts_config, "model_extra", {}) or {}
        voice_map = extra.get("voice_map", {}) or {}
        return {str(k): str(v) for k, v in voice_map.items()}
    except Exception:
        return {}


def get_persona_default_voice(
    persona_filename: str = "",
    persona_name: str = "",
    voice_map: Optional[Dict[str, str]] = None,
) -> str:
    """解析 persona 对应的音色名（voice_map 的 key），未命中返回空串。

    匹配顺序与后端既有习惯一致：用 voice_map 里的角色名对 persona 的展示名/文件名
    做归一化子串匹配，例如 ``Ye`` 命中 ``Ye``、``aveline`` 命中 ``core_aveline.json``。

    @param voice_map: 调用方已加载好的映射，为 None 时从 app.yaml 重新读取。
    """
    models = voice_map if voice_map is not None else load_voice_map()
    if not models:
        return ""
    haystacks = [h for h in (_normalize(persona_name), _normalize(persona_filename)) if h]
    if not haystacks:
        return ""
    for role_key in models:
        key = _normalize(role_key)
        if key and any(key in haystack for haystack in haystacks):
            return str(role_key)
    return ""
