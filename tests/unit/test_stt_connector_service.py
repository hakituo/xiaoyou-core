"""multimodal/stt_connector.py 单元测试（五）：健康检查、语言列表、耗时估算与单例。

对应源码：`health_check` / `get_supported_languages` / `estimate_transcription_time(_async)`
/ `get_stt_connector` / `initialize_stt_connector` / `shutdown_stt_connector`。

文件末尾记录了本次补测发现的两处**既有缺陷**（只报告、未改源码）。
"""

from __future__ import annotations

import asyncio

import pytest

from multimodal import stt_connector as sc
from multimodal.stt_connector import STTConnector


def _bare(model_type="faster-whisper"):
    obj = STTConnector.__new__(STTConnector)
    obj.model_type = model_type
    obj.model_path = "models/x"
    obj.device = "cpu"
    obj.processor = None
    obj.model = None
    obj.modelscope_model = None
    obj.temp_audio_dir = "unused"
    return obj


async def _noop_async(self):  # noqa: ANN001
    return None


# --------------------------------------------------------------------------
# 1. health_check
# --------------------------------------------------------------------------


def test_health_check_whisper_requires_both_handles(monkeypatch):
    connector = _bare("whisper")
    monkeypatch.setattr(STTConnector, "_ensure_model_loaded", _noop_async)
    connector.model, connector.processor = object(), object()
    assert asyncio.run(connector.health_check()) is True

    connector.processor = None
    assert asyncio.run(connector.health_check()) is False


def test_health_check_paraformer(monkeypatch):
    connector = _bare("paraformer")
    monkeypatch.setattr(STTConnector, "_ensure_model_loaded", _noop_async)

    connector.modelscope_model = object()
    assert asyncio.run(connector.health_check()) is True

    connector.modelscope_model = None
    assert asyncio.run(connector.health_check()) is False


def test_health_check_faster_whisper_reports_false(monkeypatch):
    """⚠️ 记录既有行为：faster-whisper 分支没有对应判断，恒返回 False。

    即模型其实已加载，`health_check()` 仍报「不可用」—— 见文件末尾的缺陷说明。
    """
    connector = _bare("faster-whisper")
    monkeypatch.setattr(STTConnector, "_ensure_model_loaded", _noop_async)
    connector.model = object()

    assert asyncio.run(connector.health_check()) is False


def test_health_check_swallows_exceptions(monkeypatch):
    connector = _bare("whisper")

    async def _boom(self):
        raise RuntimeError("模型加载炸了")

    monkeypatch.setattr(STTConnector, "_ensure_model_loaded", _boom)

    assert asyncio.run(connector.health_check()) is False


# --------------------------------------------------------------------------
# 2. get_supported_languages
# --------------------------------------------------------------------------


def test_get_supported_languages_whisper_and_paraformer():
    whisper = _bare("whisper")
    languages = asyncio.run(whisper.get_supported_languages())
    assert "zh-CN" in languages and "auto" in languages

    paraformer = _bare("paraformer")
    assert asyncio.run(paraformer.get_supported_languages()) == ["zh-CN"]


def test_get_supported_languages_faster_whisper_returns_none():
    """⚠️ 记录既有行为：faster-whisper 分支缺失，返回 None（与 `-> list[str]` 不符）。"""
    connector = _bare("faster-whisper")

    assert asyncio.run(connector.get_supported_languages()) is None


# --------------------------------------------------------------------------
# 3. 耗时估算
# --------------------------------------------------------------------------


def test_estimate_transcription_time_scales_with_size(tmp_path):
    connector = _bare()
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"\x00" * (2 * 1024 * 1024))  # 2MB

    assert connector.estimate_transcription_time(str(audio)) == pytest.approx(4.0)


def test_estimate_transcription_time_floors_at_one_second(tmp_path):
    connector = _bare()
    audio = tmp_path / "tiny.wav"
    audio.write_bytes(b"\x00")

    assert connector.estimate_transcription_time(str(audio)) == pytest.approx(1.0)


def test_estimate_transcription_time_returns_default_on_error():
    connector = _bare()

    assert connector.estimate_transcription_time("/no/such/file.wav") == pytest.approx(5.0)


def test_estimate_transcription_time_async(tmp_path):
    connector = _bare()
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"\x00" * (2 * 1024 * 1024))

    assert asyncio.run(connector.estimate_transcription_time_async(str(audio))) == pytest.approx(4.0)
    assert asyncio.run(connector.estimate_transcription_time_async("/no/such.wav")) == pytest.approx(5.0)


# --------------------------------------------------------------------------
# 4. 单例与初始化 / 关闭
# --------------------------------------------------------------------------


def test_get_stt_connector_is_singleton(monkeypatch):
    """单例：重复调用返回同一对象，且只构造一次。"""
    built = []

    class _Fake:
        def __init__(self):
            built.append(1)

    monkeypatch.setattr(sc, "STTConnector", _Fake)
    monkeypatch.setattr(sc, "stt_connector", None)

    first = sc.get_stt_connector()
    second = sc.get_stt_connector()

    assert first is second
    assert built == [1], "只应构造一次"


def test_initialize_stt_connector_logs_health(monkeypatch):
    """initialize 返回连接器，并按 health_check 结果分支。"""
    monkeypatch.setattr(sc, "stt_connector", None)
    healthy = _bare()

    async def _health_ok(self):
        return True

    monkeypatch.setattr(STTConnector, "health_check", _health_ok)
    monkeypatch.setattr(sc, "STTConnector", lambda: healthy)

    assert asyncio.run(sc.initialize_stt_connector()) is healthy


def test_initialize_stt_connector_handles_unhealthy(monkeypatch):
    monkeypatch.setattr(sc, "stt_connector", None)
    unhealthy = _bare()

    async def _health_bad(self):
        return False

    monkeypatch.setattr(STTConnector, "health_check", _health_bad)
    monkeypatch.setattr(sc, "STTConnector", lambda: unhealthy)

    assert asyncio.run(sc.initialize_stt_connector()) is unhealthy


def test_shutdown_stt_connector_closes_and_clears(monkeypatch):
    closed = []

    class _Fake:
        async def close(self):
            closed.append(1)

    monkeypatch.setattr(sc, "stt_connector", _Fake())

    asyncio.run(sc.shutdown_stt_connector())

    assert closed == [1], "应调用 close()"
    assert sc.stt_connector is None, "关闭后单例应清空"


def test_shutdown_stt_connector_noop_when_absent(monkeypatch):
    monkeypatch.setattr(sc, "stt_connector", None)

    asyncio.run(sc.shutdown_stt_connector())  # 不应报错

    assert sc.stt_connector is None


# --------------------------------------------------------------------------
# 缺陷记录（只报告、未改源码）
# --------------------------------------------------------------------------
# 1) `health_check()` 对 `faster-whisper`（**默认模型类型**）恒返回 False：
#    方法体只有 whisper / paraformer 两个分支，缺少 faster-whisper 判断，
#    于是模型明明已加载也报「不可用」，`initialize_stt_connector()` 会误报降级告警。
# 2) `get_supported_languages()` 对 `faster-whisper` 返回 None（违反 `-> list[str]`），
#    调用方若直接遍历会 TypeError。
# 两处均属「缺分支」而非恒真/恒假守卫，按约定只报告、不擅自修改。
