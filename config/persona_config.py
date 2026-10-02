# -*- coding: utf-8 -*-
"""「role -> 默认人设文件」的唯一权威解析入口。

默认人设只在一个地方配置：app.yaml 的 ``persona.default_map``（角色 -> 人设文件）：

    persona:
      default_map:
        aveline: core_aveline.json
        ling: core_ling.json

与 ``voice.tts.voice_map``（角色 -> 默认音色）同级维护：改这一处就改了角色的默认人设，
不需要再去改代码里的硬编码、QQ 账号配置或客户端逻辑。消费方：

- ``PersonaManager`` 启动时的默认人设（未显式切换过时用哪个）
- ``/api/v1/personas``：把默认人设排在该角色第一位并标 ``is_default``，
  客户端（Android）据此决定默认选中哪一版
- ``core/services/dual_role/personas.py``：Active Care / peer chat 按角色取人设文件
- ``clients/bots``（QQ）：账号配置没有显式写 ``persona_filename`` 时的兜底

匹配规则：调用方可能传 role_id（``ling``）、人设文件名（``core_ling.json``）或
会话 id（``private_10001__persona__core_ling``），统一按“切成字母数字片段后整段相等”
来匹配，避免 ``lin`` 这类子串把 ``core_ling.json`` 抢走。
"""

from pathlib import Path
from typing import Any, Dict

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_APP_YAML = _PROJECT_ROOT / "config" / "yaml" / "app.yaml"
_SECTION = "persona"
_KEY = "default_map"
_TOKEN_SPLIT = ("_", "-", ".", "/", "\\", ":", " ")


def _segments(text: Any) -> list[str]:
    """把 token 切成小写片段：``core_ling.json`` -> ['core', 'ling', 'json']。"""
    normalized = str(text or "").strip().lower()
    for sep in _TOKEN_SPLIT:
        normalized = normalized.replace(sep, " ")
    return [part for part in normalized.split() if part]


def load_persona_default_map() -> Dict[str, str]:
    """读取 app.yaml 的 ``persona.default_map``（不缓存，支持热更新）。

    直接读 YAML 而不是走 ``config.integrated_config``：本模块会被 core 侧在导入期调用
    （默认人设要参与模块常量初始化），走整包初始化会引入反向依赖。
    """
    try:
        raw = yaml.safe_load(_APP_YAML.read_text(encoding="utf-8")) or {}
        section = raw.get(_SECTION) if isinstance(raw, dict) else None
        mapping = section.get(_KEY) if isinstance(section, dict) else None
        if not isinstance(mapping, dict):
            return {}
        return {str(k).strip(): str(v).strip() for k, v in mapping.items() if str(k).strip() and str(v).strip()}
    except Exception:
        return {}


def get_default_persona_filename(role_or_persona: str, fallback: str = "") -> str:
    """解析角色对应的默认人设文件名；未命中或读取失败时返回 ``fallback``。

    @param role_or_persona: role_id / 人设文件名 / 会话 id 里的任意一种写法。
    @param fallback: 未命中时返回的原值，调用方通常传自己原来的硬编码兜底。
    """
    mapping = load_persona_default_map()
    if not mapping:
        return fallback

    segments = set(_segments(role_or_persona))
    if not segments:
        return fallback

    for role_key, filename in mapping.items():
        if segments == set(_segments(role_key)):
            return filename

    matched = [
        (role_key, filename)
        for role_key, filename in mapping.items()
        if set(_segments(role_key)) and set(_segments(role_key)) <= segments
    ]
    if not matched:
        return fallback
    # 多个 key 都能命中时取最长的（与 persona 别名匹配同规则，避免短 key 抢匹配）。
    matched.sort(key=lambda item: len(str(item[0])), reverse=True)
    return matched[0][1]
