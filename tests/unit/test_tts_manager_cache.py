"""multimodal/tts_manager.py 单元测试（二）：缓存读写、淘汰、清理与磁盘检查。

⚠️ 依赖前提同 `test_tts_manager_core.py`：`soundfile` 属 voice 可选 extra，
CI 未安装 → 用 `importorskip` 整体跳过而不是失败。

⚠️ 所有用例都把 `TEMP_DIR` 重定向到 tmp_path，**绝不碰仓库真实的 `models/tts`**。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest


from multimodal import tts_manager as tm  # noqa: E402
from multimodal.tts_manager import TTSCacheConfig, TTSCacheManager  # noqa: E402


def _make(monkeypatch, tmp_path, config=None):
    temp_dir = tmp_path / "tts"
    monkeypatch.setattr(TTSCacheManager, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(tm, "_tts_manager_instance", None)
    return TTSCacheManager(config)


def _audio(tmp_path, name="a.wav", size=16):
    p = tmp_path / "tts" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    return str(p)


# --------------------------------------------------------------------------
# 1. _cache_put / _cache_get
# --------------------------------------------------------------------------


def test_cache_put_then_get_hits(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    path = _audio(tmp_path)

    mgr._cache_put("k", path)
    assert mgr._cache_get("k") == path
    assert mgr._cache_hits == 1
    assert mgr._cache_misses == 0


def test_cache_get_miss_increments_counter(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)

    assert mgr._cache_get("nope") is None
    assert mgr._cache_misses == 1
    assert mgr._cache_hits == 0


def test_cache_get_drops_entry_when_file_deleted(monkeypatch, tmp_path):
    """文件被外部删掉后，条目应从缓存里剔除并计一次 miss。"""
    mgr = _make(monkeypatch, tmp_path)
    path = _audio(tmp_path)
    mgr._cache_put("k", path)

    Path(path).unlink()

    assert mgr._cache_get("k") is None
    assert "k" not in mgr._tts_cache, "失效条目应被剔除"
    assert mgr._cache_misses == 1


def test_cache_hit_refreshes_timestamp_and_lru_order(monkeypatch, tmp_path):
    """命中应刷新时间戳并把条目移到 LRU 尾部。"""
    mgr = _make(monkeypatch, tmp_path)
    first, second = _audio(tmp_path, "a.wav"), _audio(tmp_path, "b.wav")
    mgr._cache_put("a", first)
    mgr._cache_put("b", second)
    mgr._tts_cache["a"]["timestamp"] = 0.0

    mgr._cache_get("a")

    assert mgr._tts_cache["a"]["timestamp"] > 0
    assert list(mgr._tts_cache.keys())[-1] == "a", "命中项应被移到尾部"


def test_cache_put_evicts_oldest_beyond_max_entries(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path, TTSCacheConfig(max_entries=2))
    paths = [_audio(tmp_path, f"{i}.wav") for i in range(3)]

    for i, p in enumerate(paths):
        mgr._cache_put(f"k{i}", p)

    assert len(mgr._tts_cache) == 2
    assert "k0" not in mgr._tts_cache
    assert not Path(paths[0]).exists(), "被驱逐的文件应从磁盘删除"


def test_cache_put_tolerates_missing_file_on_evict(monkeypatch, tmp_path):
    """被驱逐的文件已不存在时不应报错。"""
    mgr = _make(monkeypatch, tmp_path, TTSCacheConfig(max_entries=1))
    mgr._cache_put("k0", str(tmp_path / "gone.wav"))

    mgr._cache_put("k1", _audio(tmp_path, "b.wav"))

    assert "k0" not in mgr._tts_cache


# --------------------------------------------------------------------------
# 2. clear_cache
# --------------------------------------------------------------------------


def test_clear_cache_removes_files_and_entries(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    path = _audio(tmp_path)
    mgr._cache_put("k", path)

    mgr.clear_cache()

    assert mgr._tts_cache == {}
    assert not Path(path).exists()


def test_clear_cache_warns_when_remove_fails(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    mgr._cache_put("k", _audio(tmp_path))

    def _boom(path):
        raise OSError("被占用")

    monkeypatch.setattr(tm.os, "remove", _boom)

    mgr.clear_cache()  # 不应抛异常

    assert mgr._tts_cache == {}


# --------------------------------------------------------------------------
# 3. _check_and_clean_cache
# --------------------------------------------------------------------------


def test_clean_cache_skips_within_interval(monkeypatch, tmp_path):
    """未到清理间隔时直接返回，不动缓存。"""
    mgr = _make(monkeypatch, tmp_path, TTSCacheConfig(cleanup_interval_sec=3600))
    path = _audio(tmp_path)
    mgr._cache_put("k", path)
    mgr.last_cache_clean = time.time()

    mgr._check_and_clean_cache()

    assert "k" in mgr._tts_cache


def test_clean_cache_removes_expired_entries(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path, TTSCacheConfig(cleanup_interval_sec=0, entry_ttl_sec=10))
    path = _audio(tmp_path)
    mgr._cache_put("k", path)
    mgr._tts_cache["k"]["timestamp"] = time.time() - 100
    mgr.last_cache_clean = 0

    mgr._check_and_clean_cache()

    assert "k" not in mgr._tts_cache
    assert not Path(path).exists(), "过期条目的文件应被删除"
    assert mgr.last_cache_clean > 0


def test_clean_cache_tolerates_expired_file_remove_failure(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path, TTSCacheConfig(cleanup_interval_sec=0, entry_ttl_sec=10))
    mgr._cache_put("k", _audio(tmp_path))
    mgr._tts_cache["k"]["timestamp"] = time.time() - 100
    mgr.last_cache_clean = 0

    def _boom(path):
        raise OSError("删不掉")

    monkeypatch.setattr(tm.os, "remove", _boom)

    mgr._check_and_clean_cache()  # 不应抛异常

    assert "k" not in mgr._tts_cache


def test_clean_cache_evicts_when_over_quota(monkeypatch, tmp_path):
    """缓存体积超配额时触发按大小驱逐。"""
    mgr = _make(
        monkeypatch,
        tmp_path,
        TTSCacheConfig(cleanup_interval_sec=0, entry_ttl_sec=99999, max_disk_mb=0),
    )
    for i in range(3):
        mgr._cache_put(f"k{i}", _audio(tmp_path, f"{i}.wav", size=1024))
    mgr.last_cache_clean = 0

    mgr._check_and_clean_cache()

    assert len(mgr._tts_cache) < 3, "超配额应驱逐掉条目"


# --------------------------------------------------------------------------
# 4. _evict_by_size
# --------------------------------------------------------------------------


def test_evict_by_size_frees_until_target(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    for i in range(3):
        mgr._cache_put(f"k{i}", _audio(tmp_path, f"{i}.wav", size=2 * 1024 * 1024))

    mgr._evict_by_size(1.0)

    assert len(mgr._tts_cache) == 2, "释放够 1MB 后应停止驱逐"


def test_evict_by_size_stops_when_cache_empty(monkeypatch, tmp_path):
    """缓存为空时不应死循环。"""
    mgr = _make(monkeypatch, tmp_path)

    mgr._evict_by_size(1000.0)

    assert mgr._tts_cache == {}


# --------------------------------------------------------------------------
# 5. _check_disk_space
# --------------------------------------------------------------------------


def test_check_disk_space_passes_when_enough(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path, TTSCacheConfig(min_free_disk_mb=1))

    mgr._check_disk_space()  # 不应抛异常


def test_check_disk_space_raises_when_insufficient(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path, TTSCacheConfig(min_free_disk_mb=1))
    monkeypatch.setattr(tm, "_get_disk_usage", lambda path: (0, 0))

    with pytest.raises(tm.TTSDiskSpaceError, match="磁盘空间不足"):
        mgr._check_disk_space()
