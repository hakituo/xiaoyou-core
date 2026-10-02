"""config/voice_config.py 单元测试。

本模块是「persona -> 默认音色」的唯一权威解析入口。测试要钉住的是它的
**解析契约**（返回 voice_map 的 key、归一化子串匹配、未命中返回空串），
而不是某一份 app.yaml 的具体内容——因此绝大多数用例显式传入 voice_map，
只有一条"配置契约"用例读真实配置。
"""

from __future__ import annotations

import pytest

from config import voice_config

_GET_SETTINGS = "config.integrated_config.get_settings"


class _TtsStub:
    """模拟 ``settings.voice.tts``（pydantic 模型 + model_extra）。"""

    def __init__(self, extra):
        if extra is not None:
            self.model_extra = extra


class _BareTtsStub:
    """完全不带 model_extra 属性的对象，走 getattr 默认值分支。"""


class _SettingsStub:
    def __init__(self, tts):
        self.voice = type("_Voice", (), {"tts": tts})()


def _patch_settings(monkeypatch, tts):
    monkeypatch.setattr(_GET_SETTINGS, lambda: _SettingsStub(tts))


class TestNormalize:
    """归一化：去首尾空白、转小写、去掉所有空格。"""

    def test_removes_all_spaces_and_lowercases(self):
        assert voice_config._normalize("  七濑 Aveline  ") == "Aveline"

    def test_none_returns_empty(self):
        assert voice_config._normalize(None) == ""

    def test_empty_string_returns_empty(self):
        assert voice_config._normalize("") == ""

    def test_non_string_is_coerced(self):
        assert voice_config._normalize(123) == "123"


class TestLoadVoiceMap:
    """从 settings.voice.tts.model_extra['voice_map'] 读映射，任何异常都退化为空表。"""

    def test_reads_voice_map(self, monkeypatch):
        _patch_settings(monkeypatch, _TtsStub({"voice_map": {"Ling": "S_x", "Ye": "S_y"}}))
        assert voice_config.load_voice_map() == {"Ling": "S_x", "Ye": "S_y"}

    def test_coerces_keys_and_values_to_str(self, monkeypatch):
        _patch_settings(monkeypatch, _TtsStub({"voice_map": {1: 2}}))
        assert voice_config.load_voice_map() == {"1": "2"}

    def test_missing_model_extra_attribute_returns_empty(self, monkeypatch):
        _patch_settings(monkeypatch, _BareTtsStub())
        assert voice_config.load_voice_map() == {}

    def test_none_model_extra_returns_empty(self, monkeypatch):
        _patch_settings(monkeypatch, _TtsStub(None))
        assert voice_config.load_voice_map() == {}

    def test_missing_voice_map_key_returns_empty(self, monkeypatch):
        _patch_settings(monkeypatch, _TtsStub({"key_map": {"Ling": {}}}))
        assert voice_config.load_voice_map() == {}

    def test_none_voice_map_returns_empty(self, monkeypatch):
        _patch_settings(monkeypatch, _TtsStub({"voice_map": None}))
        assert voice_config.load_voice_map() == {}

    def test_settings_failure_returns_empty(self, monkeypatch):
        def _boom():
            raise RuntimeError("配置系统未就绪")

        monkeypatch.setattr(_GET_SETTINGS, _boom)
        assert voice_config.load_voice_map() == {}

    def test_real_config_exposes_non_empty_voice_map(self):
        """配置契约：入库的 app.yaml 必须提供非空 voice_map。

        这不是"测 app.yaml 的内容"，而是防止有人在重构配置时把
        ``voice.tts.voice_map`` 整段删掉——那会让所有角色的音色解析静默失败。
        """
        mapping = voice_config.load_voice_map()
        assert isinstance(mapping, dict)
        assert mapping, "app.yaml 的 voice.tts.voice_map 不应为空"
        assert "Ling" in mapping
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items())


class TestGetPersonaDefaultVoice:
    """解析 persona 对应音色名（voice_map 的 key）。"""

    def test_matches_by_persona_name(self):
        assert (
            voice_config.get_persona_default_voice(
                persona_name="Ye", voice_map={"Ye": "S_y"}
            )
            == "Ye"
        )

    def test_matches_by_filename_substring(self):
        assert (
            voice_config.get_persona_default_voice(
                persona_filename="core_aveline.json", voice_map={"Aveline": "S_a"}
            )
            == "Aveline"
        )

    def test_filename_matching_is_case_insensitive(self):
        assert (
            voice_config.get_persona_default_voice(
                persona_filename="PERSONA_Ye.JSON", voice_map={"Ye": "S_y"}
            )
            == "Ye"
        )

    def test_normalization_hits_spaced_variant(self):
        """voice_map 里同时有 ``Aveline`` 和 ``七濑 Aveline`` 两种写法，归一化后都能命中。"""
        assert (
            voice_config.get_persona_default_voice(
                persona_name="七濑 Aveline", voice_map={"Aveline": "S_n"}
            )
            == "Aveline"
        )

    def test_returns_original_key_not_normalized_key(self):
        """返回值是 voice_map 的原始 key，大小写保持原样。"""
        assert (
            voice_config.get_persona_default_voice(
                persona_name="AVELINE", voice_map={"Aveline": "S_a"}
            )
            == "Aveline"
        )

    def test_name_takes_priority_over_filename(self):
        assert (
            voice_config.get_persona_default_voice(
                persona_filename="b.json",
                persona_name="a",
                voice_map={"a": "1", "b": "2"},
            )
            == "a"
        )

    def test_empty_voice_map_returns_empty(self):
        assert (
            voice_config.get_persona_default_voice(persona_name="Ye", voice_map={}) == ""
        )

    def test_no_haystack_returns_empty(self):
        assert voice_config.get_persona_default_voice(voice_map={"Ye": "S_y"}) == ""

    def test_whitespace_only_haystack_returns_empty(self):
        assert (
            voice_config.get_persona_default_voice(
                persona_name="   ", persona_filename="  ", voice_map={"Ye": "S_y"}
            )
            == ""
        )

    def test_no_match_returns_empty(self):
        assert (
            voice_config.get_persona_default_voice(
                persona_name="不存在的角色", voice_map={"Ye": "S_y"}
            )
            == ""
        )

    def test_blank_role_key_is_skipped(self):
        """归一化后为空串的 key 不能"匹配一切"。"""
        assert (
            voice_config.get_persona_default_voice(
                persona_name="Ye", voice_map={"   ": "S_x", "Ye": "S_y"}
            )
            == "Ye"
        )

    def test_only_blank_role_key_returns_empty(self):
        assert (
            voice_config.get_persona_default_voice(
                persona_name="Ye", voice_map={"   ": "S_x"}
            )
            == ""
        )

    def test_none_voice_map_falls_back_to_loader(self, monkeypatch):
        monkeypatch.setattr(voice_config, "load_voice_map", lambda: {"Ye": "S_y"})
        assert (
            voice_config.get_persona_default_voice(persona_name="Ye") == "Ye"
        )

    def test_none_voice_map_with_empty_loader_returns_empty(self, monkeypatch):
        monkeypatch.setattr(voice_config, "load_voice_map", lambda: {})
        assert voice_config.get_persona_default_voice(persona_name="Ye") == ""

    def test_real_config_resolves_known_persona(self):
        """端到端：真实配置下 persona_name="Ling" 应解析回 "Ling"。"""
        assert voice_config.get_persona_default_voice(persona_name="Ling") == "Ling"

    @pytest.mark.parametrize(
        "persona_filename,persona_name,expected",
        [
            ("", "Ye", "Ye"),
            ("persona_Ye.json", "", "Ye"),
            ("", "", ""),
            ("unrelated.json", "无关", ""),
        ],
    )
    def test_parametrized_contract(self, persona_filename, persona_name, expected):
        assert (
            voice_config.get_persona_default_voice(
                persona_filename=persona_filename,
                persona_name=persona_name,
                voice_map={"Ye": "S_y"},
            )
            == expected
        )
