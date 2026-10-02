"""multimodal/tts_manager.py 单元测试（一）：配置、构造、辅助函数、文本规范化、缓存键。

⚠️ 依赖前提：`soundfile` 属于 `voice` 可选 extra（`pyproject.toml`），
CI 只跑 `uv sync --extra dev` 不会装它，而 `tts_manager.py` 顶层就 `import soundfile`。
因此本文件用 `pytest.importorskip` 在缺依赖的环境里**整体跳过**，而不是失败。
（这也是仓库既有 `test_tts_manager_optimized.py` 被写进 CI `--ignore` 名单的原因。）

⚠️ `TTSCacheManager.TEMP_DIR` 默认指向仓库真实的 `models/tts`，
本文件所有用例都会把它重定向到 tmp_path，**绝不碰真实目录**。
"""

from __future__ import annotations

from pathlib import Path

import pytest


from multimodal import tts_manager as tm  # noqa: E402
from multimodal.tts_manager import TTSCacheConfig, TTSCacheManager  # noqa: E402


@pytest.fixture
def temp_dir(tmp_path):
    """把 TEMP_DIR 指到 tmp_path，并还原模块级单例。"""
    d = tmp_path / "tts"
    return d


def _make(monkeypatch, temp_dir, config=None):
    monkeypatch.setattr(TTSCacheManager, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(tm, "_tts_manager_instance", None)
    return TTSCacheManager(config)


# --------------------------------------------------------------------------
# 1. TTSCacheConfig 与异常层次
# --------------------------------------------------------------------------


def test_config_defaults():
    cfg = TTSCacheConfig()
    assert cfg.max_entries == 30
    assert cfg.max_disk_mb == 200
    assert cfg.cleanup_interval_sec == 3600
    assert cfg.entry_ttl_sec == 3600
    assert cfg.synthesis_timeout_sec == 60
    assert cfg.min_free_disk_mb == 100
    assert cfg.normalize_text is True


def test_exception_hierarchy_and_payload():
    """四种异常都继承 TTSError；TTSSynthesisError 额外带 text / provider。"""
    for exc_type in (
        tm.TTSInitializationError,
        tm.TTSSynthesisError,
        tm.TTSTimeoutError,
        tm.TTSDiskSpaceError,
    ):
        assert issubclass(exc_type, tm.TTSError)

    err = tm.TTSSynthesisError("炸了", text="你好", provider="volcano")
    assert err.text == "你好"
    assert err.provider == "volcano"
    assert "炸了" in str(err)

    # 默认值分支
    assert tm.TTSSynthesisError("x").text == ""
    assert tm.TTSSynthesisError("x").provider == ""


def test_tts_manager_alias_is_cache_manager():
    """向后兼容别名。"""
    assert tm.TTSManager is TTSCacheManager


# --------------------------------------------------------------------------
# 2. 模块级辅助函数
# --------------------------------------------------------------------------


def test_write_bytes_to_file_is_atomic(tmp_path):
    target = tmp_path / "a.bin"
    tm._write_bytes_to_file(str(target), b"hello")

    assert target.read_bytes() == b"hello"
    assert not Path(f"{target}.tmp").exists(), "临时文件应被 os.replace 消费掉"


def test_write_bytes_to_file_cleans_temp_on_failure(tmp_path, monkeypatch):
    """写失败时要清掉 .tmp 残留并向上抛。"""
    target = tmp_path / "a.bin"

    def _boom(src, dst):
        raise OSError("替换失败")

    monkeypatch.setattr(tm.os, "replace", _boom)

    with pytest.raises(OSError, match="替换失败"):
        tm._write_bytes_to_file(str(target), b"x")

    assert not Path(f"{target}.tmp").exists(), "失败后不应留下 .tmp"


def test_get_disk_usage_returns_megabytes(tmp_path):
    used, free = tm._get_disk_usage(str(tmp_path))
    assert used >= 0
    assert free > 0


def test_get_disk_usage_returns_zero_on_error():
    assert tm._get_disk_usage("/definitely/not/a/path") == (0, 0)


def test_get_directory_size_counts_only_files(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * (1024 * 1024))
    (tmp_path / "sub").mkdir()

    assert tm._get_directory_size(str(tmp_path)) >= 1


def test_get_directory_size_returns_zero_on_error():
    assert tm._get_directory_size("/definitely/not/a/path") == 0


# --------------------------------------------------------------------------
# 3. 构造与临时目录
# --------------------------------------------------------------------------


def test_init_creates_temp_dir(monkeypatch, temp_dir):
    connector = _make(monkeypatch, temp_dir)

    assert temp_dir.is_dir()
    assert connector.config.max_entries == 30
    assert connector._initialized is False
    assert connector.new_engine is None
    assert connector._cache_hits == 0


def test_init_accepts_custom_config(monkeypatch, temp_dir):
    cfg = TTSCacheConfig(max_entries=3, synthesis_timeout_sec=7)
    connector = _make(monkeypatch, temp_dir, cfg)

    assert connector.config is cfg


def test_ensure_temp_dir_replaces_file_with_dir(monkeypatch, temp_dir):
    """TEMP_DIR 位置上若是文件，应先删掉再建目录。"""
    temp_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir.write_bytes(b"i am a file")

    _make(monkeypatch, temp_dir)

    assert temp_dir.is_dir(), "应把同名文件替换成目录"


# --------------------------------------------------------------------------
# 4. 文本规范化与缓存键
# --------------------------------------------------------------------------


def test_normalize_text_collapses_whitespace(monkeypatch, temp_dir):
    connector = _make(monkeypatch, temp_dir)

    assert connector._normalize_text("  你好   世界 \n 啊 ") == "你好 世界 啊"


def test_normalize_text_disabled_returns_raw(monkeypatch, temp_dir):
    connector = _make(monkeypatch, temp_dir, TTSCacheConfig(normalize_text=False))

    assert connector._normalize_text("  原样  ") == "  原样  "


def test_cache_key_is_deterministic_and_sensitive_to_params(monkeypatch, temp_dir):
    connector = _make(monkeypatch, temp_dir)

    base = connector._generate_cache_key("你好", 1.0, "happy")
    assert base == connector._generate_cache_key("你好", 1.0, "happy")
    assert base != connector._generate_cache_key("你好", 1.2, "happy")
    assert base != connector._generate_cache_key("你好", 1.0, "sad")
    assert base != connector._generate_cache_key("再见", 1.0, "happy")


def test_cache_key_normalizes_text_by_default(monkeypatch, temp_dir):
    """默认开启规范化：多空格与单空格应得到同一个键。"""
    connector = _make(monkeypatch, temp_dir)

    assert connector._generate_cache_key("你好  世界") == connector._generate_cache_key("你好 世界")


def test_cache_key_uses_provider_from_engine_settings(monkeypatch, temp_dir):
    connector = _make(monkeypatch, temp_dir)
    connector.new_engine = type("E", (), {"settings": object()})()
    monkeypatch.setattr(
        tm, "get_config", lambda *a, **kw: type("C", (), {"provider": "volcano"})()
    )

    with_provider = connector._generate_cache_key("你好")
    monkeypatch.setattr(tm, "get_config", lambda *a, **kw: type("C", (), {"provider": None})())
    without_provider = connector._generate_cache_key("你好")

    assert with_provider != without_provider, "provider 应参与缓存键"


def test_cache_key_falls_back_to_unknown_on_error(monkeypatch, temp_dir):
    connector = _make(monkeypatch, temp_dir)
    connector.new_engine = type("E", (), {"settings": object()})()

    def _boom(*a, **kw):
        raise RuntimeError("配置读取失败")

    monkeypatch.setattr(tm, "get_config", _boom)

    assert connector._generate_cache_key("你好") == connector._generate_cache_key("你好")
