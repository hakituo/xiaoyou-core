#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
优化版 TTS Manager 综合测试套件。

测试覆盖:
- 线程安全
- Future 超时机制
- 缓存管理
- 磁盘空间监控
- 错误处理
- 优雅关闭
"""

import os
import sys
import pytest
import asyncio
import threading
import tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from multimodal.tts_manager import (
    TTSCacheManager,
    TTSCacheConfig,
    TTSInitializationError,
    TTSSynthesisError,
    TTSTimeoutError,
    TTSDiskSpaceError,
    get_tts_manager,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def test_config(temp_dir):
    return TTSCacheConfig(
        max_entries=5,
        max_disk_mb=10,
        cleanup_interval_sec=1,
        entry_ttl_sec=2,
        synthesis_timeout_sec=5,
        min_free_disk_mb=1,
        normalize_text=True
    )


@pytest.fixture
def manager(test_config, temp_dir, monkeypatch):
    monkeypatch.setattr(
        "multimodal.tts_manager.TTSCacheManager.TEMP_DIR",
        temp_dir
    )

    mgr = TTSCacheManager(test_config)
    yield mgr

    try:
        mgr.close()
    except Exception:
        pass


def _make_mock_engine(**overrides):
    """创建一个不会干扰 _generate_cache_key 的 mock engine"""
    mock_engine = MagicMock(spec=[])
    for key, value in overrides.items():
        setattr(mock_engine, key, value)
    return mock_engine


# ============================================================================
# 线程安全测试
# ============================================================================

def test_background_loop_thread_safety(manager):
    results = []

    def init_worker():
        try:
            manager._ensure_background_loop()
            results.append(manager._bg_thread.ident)
        except Exception as e:
            results.append(f"error: {e}")

    threads = [threading.Thread(target=init_worker) for _ in range(10)]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 10
    assert all(isinstance(r, int) for r in results), f"Got errors: {results}"
    assert len(set(results)) == 1, "Multiple background threads created!"


def test_cache_concurrent_access(manager):
    cache_key = "test_key"
    file_path = os.path.join(manager.TEMP_DIR, "test.wav")

    with open(file_path, "wb") as f:
        f.write(b"test audio data")

    def cache_worker():
        for _ in range(100):
            manager._cache_put(cache_key, file_path)
            result = manager._cache_get(cache_key)
            assert result == file_path or result is None

    threads = [threading.Thread(target=cache_worker) for _ in range(5)]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert cache_key in manager._tts_cache


# ============================================================================
# Future 超时测试
# ============================================================================

@pytest.mark.asyncio
async def test_future_timeout_mechanism(manager):
    cache_key = "timeout_test"

    loop = asyncio.get_running_loop()
    stuck_future = loop.create_future()
    manager._inflight_async[cache_key] = stuck_future

    with pytest.raises(TTSTimeoutError) as exc_info:
        await manager._wait_for_inflight_async(cache_key, timeout=0.1)

    assert "超时" in str(exc_info.value) or "timeout" in str(exc_info.value).lower()
    assert cache_key not in manager._inflight_async, "Future not cleaned up!"


@pytest.mark.asyncio
async def test_synthesis_timeout(manager):
    async def slow_synthesize(*args, **kwargs):
        await asyncio.sleep(10)

    mock_engine = _make_mock_engine()
    mock_engine.synthesize_bytes = AsyncMock(side_effect=slow_synthesize)
    mock_engine.synthesize = AsyncMock(side_effect=slow_synthesize)

    manager.new_engine = mock_engine
    manager._initialized = True

    with pytest.raises((TTSTimeoutError, asyncio.TimeoutError)):
        await asyncio.wait_for(
            manager.async_text_to_speech("test", speed=1.0),
            timeout=1.0
        )


# ============================================================================
# 缓存管理测试
# ============================================================================

def test_cache_key_generation(manager):
    key1 = manager._generate_cache_key("Hello  World")
    key2 = manager._generate_cache_key("Hello World")
    key3 = manager._generate_cache_key("  Hello World  ")

    assert key1 == key2 == key3, "Text normalization not working"

    key4 = manager._generate_cache_key("Hello World", speed=1.0)
    key5 = manager._generate_cache_key("Hello World", speed=1.5)

    assert key4 != key5, "Speed not affecting cache key"


def test_cache_lru_eviction(manager):
    for i in range(manager.config.max_entries + 2):
        cache_key = f"key_{i}"
        file_path = os.path.join(manager.TEMP_DIR, f"test_{i}.wav")

        with open(file_path, "wb") as f:
            f.write(b"test")

        manager._cache_put(cache_key, file_path)

    assert len(manager._tts_cache) <= manager.config.max_entries

    assert "key_0" not in manager._tts_cache
    assert "key_1" not in manager._tts_cache


def test_cache_expiration(manager):
    import time

    cache_key = "expire_test"
    file_path = os.path.join(manager.TEMP_DIR, "expire.wav")

    with open(file_path, "wb") as f:
        f.write(b"test")

    manager._cache_put(cache_key, file_path)

    manager._tts_cache[cache_key]["timestamp"] = time.time() - 10000

    manager.last_cache_clean = 0
    manager._check_and_clean_cache()

    assert cache_key not in manager._tts_cache
    assert not os.path.exists(file_path)


# ============================================================================
# 磁盘空间管理测试
# ============================================================================

def test_disk_space_check_insufficient(manager):
    with patch("multimodal.tts_manager._get_disk_usage") as mock_disk:
        mock_disk.return_value = (1000, 0)

        with pytest.raises(TTSDiskSpaceError) as exc_info:
            manager._check_disk_space()

        error_msg = str(exc_info.value).lower()
        assert "磁盘空间不足" in str(exc_info.value) or "insufficient" in error_msg


def test_disk_quota_eviction(manager):
    total_size = 0
    for i in range(10):
        cache_key = f"large_{i}"
        file_path = os.path.join(manager.TEMP_DIR, f"large_{i}.wav")

        with open(file_path, "wb") as f:
            f.write(b"x" * (2 * 1024 * 1024))

        manager._cache_put(cache_key, file_path)
        total_size += 2

    with patch("multimodal.tts_manager._get_directory_size") as mock_size:
        mock_size.return_value = manager.config.max_disk_mb + 10

        manager.last_cache_clean = 0
        manager._check_and_clean_cache()

    assert len(manager._tts_cache) < 10


# ============================================================================
# 错误处理测试
# ============================================================================

def test_empty_text_validation(manager):
    with pytest.raises(ValueError) as exc_info:
        manager.text_to_speech("")

    assert "非空" in str(exc_info.value) or "non-empty" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_empty_text_validation_async(manager):
    with pytest.raises(ValueError) as exc_info:
        await manager.async_text_to_speech("")

    assert "非空" in str(exc_info.value) or "non-empty" in str(exc_info.value).lower()


def test_initialization_failure(manager):
    with patch("multimodal.tts_manager.TTSCacheManager._initialize") as mock_init:
        mock_init.return_value = False

        manager._initialized = False

        with pytest.raises(TTSInitializationError):
            manager.text_to_speech("test")


@pytest.mark.asyncio
async def test_synthesis_error_propagation(manager):
    mock_engine = _make_mock_engine()
    mock_engine.synthesize_bytes = AsyncMock(side_effect=RuntimeError("Engine error"))
    mock_engine.synthesize = AsyncMock(side_effect=RuntimeError("Engine error"))

    manager.new_engine = mock_engine
    manager._initialized = True

    with pytest.raises(TTSSynthesisError) as exc_info:
        await manager.async_text_to_speech("test")

    error_msg = str(exc_info.value).lower()
    assert "合成失败" in str(exc_info.value) or "synthesis failed" in error_msg


# ============================================================================
# 关闭测试
# ============================================================================

@pytest.mark.asyncio
async def test_graceful_shutdown_with_inflight(manager):
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    manager._inflight_async["test_key"] = future

    shutdown_task = asyncio.create_task(manager.shutdown())

    await asyncio.sleep(0.1)

    future.set_result("/path/to/audio.wav")

    await shutdown_task

    assert manager._shutting_down


@pytest.mark.asyncio
async def test_shutdown_prevents_new_requests(manager):
    manager._shutting_down = True

    with pytest.raises(TTSSynthesisError) as exc_info:
        await manager.async_text_to_speech("test")

    error_msg = str(exc_info.value)
    assert "关闭" in error_msg or "shutting down" in error_msg.lower()


# ============================================================================
# 健康检查测试
# ============================================================================

def test_health_check_metrics(manager):
    manager._cache_hits = 80
    manager._cache_misses = 20
    manager._synthesis_count = 25

    health = manager.health_check()

    assert health["initialized"] == manager._initialized
    assert health["cache_hit_rate"] == 0.8
    assert health["cache_hits"] == 80
    assert health["cache_misses"] == 20
    assert health["synthesis_count"] == 25
    assert "cache_entries" in health
    assert "free_disk_mb" in health


# ============================================================================
# 集成测试
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_deduplication(manager):
    call_count = 0

    async def mock_synthesize(text, **kwargs):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.1)
        return b"audio data"

    mock_engine = _make_mock_engine()
    mock_engine.synthesize_bytes = mock_synthesize

    manager.new_engine = mock_engine
    manager._initialized = True

    tasks = [manager.async_text_to_speech("Same text") for _ in range(5)]
    results = await asyncio.gather(*tasks)

    assert len(set(results)) == 1
    assert call_count == 1


@pytest.mark.asyncio
async def test_cache_hit_performance(manager):
    import time

    cache_key = manager._generate_cache_key("test text")
    file_path = os.path.join(manager.TEMP_DIR, f"tts_{cache_key}.wav")

    with open(file_path, "wb") as f:
        f.write(b"cached audio")

    manager._cache_put(cache_key, file_path)

    start = time.perf_counter()
    result = manager._cache_get(cache_key)
    elapsed = time.perf_counter() - start

    assert result == file_path
    assert elapsed < 0.001, f"Cache hit took {elapsed}s, should be <1ms"


# ============================================================================
# 配置测试
# ============================================================================

def test_custom_configuration():
    config = TTSCacheConfig(
        max_entries=100,
        max_disk_mb=500,
        synthesis_timeout_sec=30,
        normalize_text=False
    )

    mgr = TTSCacheManager(config)

    assert mgr.config.max_entries == 100
    assert mgr.config.max_disk_mb == 500
    assert mgr.config.synthesis_timeout_sec == 30
    assert not mgr.config.normalize_text


# ============================================================================
# 单例测试
# ============================================================================

def test_singleton_pattern():
    mgr1 = get_tts_manager()
    mgr2 = get_tts_manager()

    assert mgr1 is mgr2, "Should return same instance"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
