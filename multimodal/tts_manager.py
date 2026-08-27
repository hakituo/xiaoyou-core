#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
优化版 TTS Manager - 改进的线程安全、错误处理和资源管理。

关键改进:
- 修复了后台循环创建中的线程安全问题
- 添加了 Future 超时机制，防止请求卡死
- 结构化异常层次，便于错误处理
- 优雅关闭，正确清理资源
- 完整的类型注解
- 磁盘空间监控和管理
- 文本规范化提升缓存命中率
- 健康检查端点
"""

import os
import time
import logging
import hashlib
import asyncio
import soundfile as sf
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple
import threading
import concurrent.futures
from threading import Lock, Event

from core.utils.common import get_project_root
from core.utils.config_accessor import get_config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================================
# 自定义异常
# ============================================================================

class TTSError(Exception):
    """TTS 操作基础异常"""
    pass


class TTSInitializationError(TTSError):
    """引擎初始化失败"""
    pass


class TTSSynthesisError(TTSError):
    """音频合成失败"""
    def __init__(self, message: str, text: str = "", provider: str = ""):
        super().__init__(message)
        self.text = text
        self.provider = provider


class TTSTimeoutError(TTSError):
    """合成操作超时"""
    pass


class TTSDiskSpaceError(TTSError):
    """磁盘空间不足"""
    pass


# ============================================================================
# 配置
# ============================================================================

@dataclass
class TTSCacheConfig:
    """TTS 缓存管理器配置"""
    max_entries: int = 30
    max_disk_mb: int = 200
    cleanup_interval_sec: int = 3600
    entry_ttl_sec: int = 3600
    synthesis_timeout_sec: int = 60
    min_free_disk_mb: int = 100
    normalize_text: bool = True


# ============================================================================
# 辅助函数
# ============================================================================

def _write_bytes_to_file(path: str, data: bytes) -> None:
    """原子写入字节数据到文件"""
    temp_path = f"{path}.tmp"
    try:
        with open(temp_path, "wb") as f:
            f.write(data)
        os.replace(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def _get_disk_usage(path: str) -> Tuple[int, int]:
    """获取磁盘使用情况（已用MB，可用MB）"""
    try:
        import shutil
        total, used, free = shutil.disk_usage(path)
        return used // (1024 * 1024), free // (1024 * 1024)
    except Exception:
        return 0, 0


def _get_directory_size(path: str) -> int:
    """获取目录总大小（MB）"""
    try:
        total = 0
        for entry in os.scandir(path):
            if entry.is_file():
                total += entry.stat().st_size
        return total // (1024 * 1024)
    except Exception:
        return 0


# ============================================================================
# 优化版 TTS 管理器
# ============================================================================

class TTSCacheManager:
    """
    优化版 TTS 管理器，提供缓存、去重和资源管理。

    在底层 TTS 引擎之上提供缓存层，
    避免冗余合成操作并管理音频文件生命周期。
    """

    TEMP_DIR = str(get_project_root() / "models" / "tts")

    def __init__(self, config: Optional[TTSCacheConfig] = None):
        self.config = config or TTSCacheConfig()

        self._lock = Lock()
        self._init_lock = Lock()
        self._initialized = False

        self._tts_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()

        self._inflight_async: Dict[str, asyncio.Future] = {}
        self._inflight_sync: Dict[str, concurrent.futures.Future] = {}

        self.last_cache_clean = time.time()

        self._cache_hits = 0
        self._cache_misses = 0
        self._synthesis_count = 0

        self.new_engine = None

        self._bg_loop: Optional[asyncio.AbstractEventLoop] = None
        self._bg_thread: Optional[threading.Thread] = None
        self._bg_loop_ready = Event()
        self._shutting_down = False

        self._ensure_temp_dir()

    def _ensure_temp_dir(self) -> None:
        """确保临时目录存在"""
        if os.path.exists(self.TEMP_DIR) and not os.path.isdir(self.TEMP_DIR):
            os.remove(self.TEMP_DIR)
        os.makedirs(self.TEMP_DIR, exist_ok=True)

    def _ensure_background_loop(self) -> None:
        """
        确保后台事件循环存在（线程安全）。

        修复：使用原子标志的正确双重检查锁定。
        """
        if self._bg_loop is not None and self._bg_loop.is_running():
            return

        with self._init_lock:
            if self._bg_loop is not None and self._bg_loop.is_running():
                return

            self._bg_loop_ready.clear()

            def run_loop():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                with self._init_lock:
                    self._bg_loop = loop
                    self._bg_loop_ready.set()

                try:
                    loop.run_forever()
                finally:
                    try:
                        pending = asyncio.all_tasks(loop)
                        for task in pending:
                            task.cancel()
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                        loop.close()
                    except Exception as e:
                        logger.warning(f"关闭后台循环时出错: {e}")

            self._bg_thread = threading.Thread(
                target=run_loop, daemon=True, name="TTSBackgroundLoop"
            )
            self._bg_thread.start()

        if not self._bg_loop_ready.wait(timeout=5):
            raise TTSInitializationError("后台循环在5秒内未能启动")

    def _initialize(self) -> bool:
        """
        初始化 TTS 引擎（线程安全）。

        Returns:
            初始化成功返回 True
        """
        if self._initialized:
            return True

        with self._init_lock:
            if self._initialized:
                return True

            try:
                from core.voice.tts_engine import TTSManager as NewTTSManager

                self.new_engine = NewTTSManager()

                self._ensure_background_loop()
                future = asyncio.run_coroutine_threadsafe(
                    self.new_engine.initialize(), self._bg_loop
                )
                future.result(timeout=60)

                self._initialized = True
                logger.info("TTS 引擎初始化成功")
                return True

            except Exception as e:
                logger.error(f"TTS 引擎初始化失败: {e}")
                raise TTSInitializationError(f"引擎初始化失败: {e}") from e

    def _normalize_text(self, text: str) -> str:
        """
        规范化文本以生成一致的缓存键。

        Args:
            text: 输入文本

        Returns:
            规范化后的文本
        """
        if not self.config.normalize_text:
            return text

        text = " ".join(text.split())
        return text.strip()

    def _generate_cache_key(
        self,
        text: str,
        speed: Optional[float] = None,
        emotion: Optional[str] = None,
    ) -> str:
        """
        为 TTS 请求生成缓存键。

        Args:
            text: 要合成的文本
            speed: 语速
            emotion: 情感参数

        Returns:
            MD5 哈希作为缓存键
        """
        normalized_text = self._normalize_text(text)

        provider = "unknown"
        try:
            if self.new_engine and hasattr(self.new_engine, "settings"):
                settings = getattr(self.new_engine, "settings", None)
                tts_conf = get_config("voice.tts", default=None, settings=settings)
                provider = getattr(tts_conf, "provider", None) or provider
        except Exception as e:
            logger.warning(f"检测 TTS 提供者失败: {e}")
            provider = "unknown"

        key_parts = [
            provider,
            normalized_text,
            str(speed if speed is not None else ""),
            str(emotion if emotion is not None else ""),
        ]
        return hashlib.md5("|".join(key_parts).encode()).hexdigest()

    def _check_disk_space(self) -> None:
        """
        检查是否有足够的磁盘空间。

        Raises:
            TTSDiskSpaceError: 磁盘空间不足时抛出
        """
        _, free_mb = _get_disk_usage(self.TEMP_DIR)
        if free_mb < self.config.min_free_disk_mb:
            raise TTSDiskSpaceError(
                f"磁盘空间不足: 可用 {free_mb}MB, "
                f"至少需要 {self.config.min_free_disk_mb}MB"
            )

    def _check_and_clean_cache(self) -> None:
        """
        检查并清理过期的缓存条目。

        优化：仅在间隔时间到达时运行，而非每次请求。
        """
        current_time = time.time()

        if current_time - self.last_cache_clean < self.config.cleanup_interval_sec:
            return

        with self._lock:
            expired_keys = []
            cache_size_mb = 0

            for key, entry in list(self._tts_cache.items()):
                file_path = entry.get("file_path")

                if current_time - entry["timestamp"] > self.config.entry_ttl_sec:
                    expired_keys.append(key)
                elif file_path and os.path.exists(file_path):
                    try:
                        cache_size_mb += os.path.getsize(file_path) / (1024 * 1024)
                    except Exception:
                        pass

            for key in expired_keys:
                entry = self._tts_cache.pop(key, None)
                if entry:
                    file_path = entry.get("file_path")
                    if file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            logger.debug(f"已删除过期缓存文件: {file_path}")
                        except Exception as e:
                            logger.warning(f"删除过期缓存文件失败: {e}")

            if cache_size_mb > self.config.max_disk_mb:
                logger.warning(
                    f"缓存大小 ({cache_size_mb:.1f}MB) 超出配额 "
                    f"({self.config.max_disk_mb}MB)，强制清理"
                )
                self._evict_by_size(cache_size_mb - self.config.max_disk_mb)

            self.last_cache_clean = current_time

            if expired_keys:
                logger.info(f"已清理 {len(expired_keys)} 个过期缓存条目")

    def _evict_by_size(self, target_mb: float) -> None:
        """
        按大小驱逐缓存条目以释放磁盘空间。

        Args:
            target_mb: 需要释放的空间大小（MB）
        """
        freed_mb = 0.0

        while freed_mb < target_mb and self._tts_cache:
            key, entry = self._tts_cache.popitem(last=False)
            file_path = entry.get("file_path")

            if file_path and os.path.exists(file_path):
                try:
                    size_mb = os.path.getsize(file_path) / (1024 * 1024)
                    os.remove(file_path)
                    freed_mb += size_mb
                except Exception as e:
                    logger.warning(f"驱逐缓存文件失败: {e}")

        logger.info(f"已驱逐缓存条目，释放 {freed_mb:.1f}MB")

    def _cache_get(self, cache_key: str) -> Optional[str]:
        """
        获取缓存的音频文件路径。

        Args:
            cache_key: 缓存键

        Returns:
            缓存命中返回文件路径，否则返回 None
        """
        with self._lock:
            entry = self._tts_cache.get(cache_key)
            if not entry:
                self._cache_misses += 1
                return None

            cached_file = entry.get("file_path")
            if cached_file and os.path.exists(cached_file):
                entry["timestamp"] = time.time()
                try:
                    self._tts_cache.move_to_end(cache_key)
                except Exception:
                    pass

                self._cache_hits += 1
                return cached_file

            self._tts_cache.pop(cache_key, None)
            self._cache_misses += 1
            return None

    def _cache_put(self, cache_key: str, file_path: str) -> None:
        """
        将音频文件放入缓存。

        Args:
            cache_key: 缓存键
            file_path: 音频文件路径
        """
        with self._lock:
            self._tts_cache[cache_key] = {
                "file_path": file_path,
                "timestamp": time.time(),
            }

            try:
                self._tts_cache.move_to_end(cache_key)
            except Exception:
                pass

            while len(self._tts_cache) > self.config.max_entries:
                old_key, old_entry = self._tts_cache.popitem(last=False)
                old_file = (
                    old_entry.get("file_path") if isinstance(old_entry, dict) else None
                )

                if old_file and os.path.exists(old_file):
                    try:
                        os.remove(old_file)
                        logger.debug(f"已驱逐缓存文件: {old_file}")
                    except Exception as e:
                        logger.warning(f"删除被驱逐的缓存文件失败: {e}")

    async def _wait_for_inflight_async(
        self, cache_key: str, timeout: Optional[float] = None
    ) -> str:
        """
        等待进行中的异步请求（带超时）。

        Args:
            cache_key: 缓存键
            timeout: 超时时间（秒）

        Returns:
            生成的音频文件路径

        Raises:
            TTSTimeoutError: 超时时抛出
        """
        timeout = timeout or self.config.synthesis_timeout_sec
        future = self._inflight_async.get(cache_key)

        if not future:
            raise TTSSynthesisError("未找到进行中的 Future")

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            if result and os.path.exists(result):
                return result
            raise TTSSynthesisError("进行中的合产生了无效结果")

        except asyncio.TimeoutError:
            with self._lock:
                self._inflight_async.pop(cache_key, None)
            raise TTSTimeoutError(
                f"合成超时，已等待 {timeout}s，cache_key={cache_key}"
            )

    async def async_text_to_speech(
        self,
        text: str,
        speed: Optional[float] = None,
        emotion: Optional[str] = None,
        voice: Optional[str] = None,
    ) -> str:
        """
        异步将文本转换为语音。

        Args:
            text: 要转换的文本
            speed: 语速（默认 1.0）
            emotion: 情感参数（可选）

        Returns:
            生成的音频文件路径

        Raises:
            ValueError: 文本为空时抛出
            TTSInitializationError: 引擎初始化失败时抛出
            TTSSynthesisError: 合成失败时抛出
            TTSTimeoutError: 合成超时时抛出
            TTSDiskSpaceError: 磁盘空间不足时抛出
        """
        if not text:
            raise ValueError("TTS 需要非空文本输入")

        if self._shutting_down:
            raise TTSSynthesisError("TTS 管理器正在关闭")

        if not self._initialized:
            if not self.new_engine:
                from core.voice.tts_engine import TTSManager as NewTTSManager

                self.new_engine = NewTTSManager()
            await self.new_engine.initialize()
            self._initialized = True

        self._check_disk_space()

        self._check_and_clean_cache()

        cache_key = self._generate_cache_key(text, speed, emotion)

        cached = self._cache_get(cache_key)
        if cached:
            logger.info(f"缓存命中: {text[:50]}...")
            return cached

        is_owner = False
        with self._lock:
            inflight = self._inflight_async.get(cache_key)
            if inflight is None:
                loop = asyncio.get_running_loop()
                inflight = loop.create_future()
                self._inflight_async[cache_key] = inflight
                is_owner = True

        if not is_owner:
            logger.debug(f"等待进行中的合成: {text[:50]}...")
            return await self._wait_for_inflight_async(cache_key)

        filename = f"tts_{cache_key}.wav"
        filepath = os.path.join(self.TEMP_DIR, filename)

        try:
            logger.info(f"正在合成音频: {text[:50]}..., voice={voice}")
            self._synthesis_count += 1

            tts_speed = speed if speed is not None else 1.0
            audio_bytes = None

            if hasattr(self.new_engine, "synthesize_bytes"):
                audio_bytes = await self.new_engine.synthesize_bytes(
                    text, speed=tts_speed, voice=voice
                )

            if audio_bytes:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, _write_bytes_to_file, filepath, audio_bytes
                )
                self._cache_put(cache_key, filepath)

                with self._lock:
                    fut = self._inflight_async.pop(cache_key, None)
                    if fut and not fut.done():
                        fut.set_result(filepath)

                return filepath

            audio_data = await self.new_engine.synthesize(text, speed=tts_speed, voice=voice)

            if audio_data is not None and len(audio_data) > 0:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, lambda: sf.write(filepath, audio_data, 32000)
                )
                self._cache_put(cache_key, filepath)

                with self._lock:
                    fut = self._inflight_async.pop(cache_key, None)
                    if fut and not fut.done():
                        fut.set_result(filepath)

                return filepath

            raise TTSSynthesisError(
                "生成的音频数据为空",
                text=text[:100],
                provider=self._get_provider_name(),
            )

        except Exception as e:
            logger.error(f"TTS 合成失败: {e}")

            with self._lock:
                fut = self._inflight_async.pop(cache_key, None)
                if fut and not fut.done():
                    fut.set_exception(e)

            if isinstance(e, TTSError):
                raise
            raise TTSSynthesisError(
                f"语音合成失败: {str(e)}", text=text[:100]
            ) from e

    def text_to_speech(
        self,
        text: str,
        speed: Optional[float] = None,
        emotion: Optional[str] = None,
        voice: Optional[str] = None,
    ) -> str:
        """
        将文本转换为语音（同步包装器）。

        Args:
            text: 要转换的文本
            speed: 语速（默认 1.0）
            emotion: 情感参数（可选）

        Returns:
            生成的音频文件路径

        Raises:
            ValueError: 文本为空时抛出
            TTSInitializationError: 引擎初始化失败时抛出
            TTSSynthesisError: 合成失败时抛出
            TTSTimeoutError: 合成超时时抛出
        """
        if not text:
            raise ValueError("TTS 需要非空文本输入")

        if self._shutting_down:
            raise TTSSynthesisError("TTS 管理器正在关闭")

        if not self._initialize():
            raise TTSInitializationError("TTS 引擎初始化失败")

        self._check_disk_space()

        self._check_and_clean_cache()

        cache_key = self._generate_cache_key(text, speed, emotion)

        cached = self._cache_get(cache_key)
        if cached:
            logger.info(f"缓存命中: {text[:50]}...")
            return cached

        with self._lock:
            existing = self._inflight_sync.get(cache_key)
            if existing is not None:
                future = existing
                is_owner = False
            else:
                future = concurrent.futures.Future()
                self._inflight_sync[cache_key] = future
                is_owner = True

        if not is_owner:
            try:
                return future.result(timeout=self.config.synthesis_timeout_sec)
            except concurrent.futures.TimeoutError:
                with self._lock:
                    self._inflight_sync.pop(cache_key, None)
                raise TTSTimeoutError(
                    f"合成超时，已等待 {self.config.synthesis_timeout_sec}s"
                )

        filename = f"tts_{cache_key}.wav"
        filepath = os.path.join(self.TEMP_DIR, filename)

        try:
            logger.info(f"正在合成音频: {text[:50]}...")
            self._synthesis_count += 1

            self._ensure_background_loop()
            tts_speed = speed if speed is not None else 1.0
            audio_bytes = None

            if hasattr(self.new_engine, "synthesize_bytes"):
                fut_bytes = asyncio.run_coroutine_threadsafe(
                    self.new_engine.synthesize_bytes(text, speed=tts_speed, voice=voice),
                    self._bg_loop,
                )
                audio_bytes = fut_bytes.result(
                    timeout=self.config.synthesis_timeout_sec
                )

            if audio_bytes:
                with open(filepath, "wb") as f:
                    f.write(audio_bytes)
                self._cache_put(cache_key, filepath)
                future.set_result(filepath)

                with self._lock:
                    self._inflight_sync.pop(cache_key, None)

                return filepath

            fut = asyncio.run_coroutine_threadsafe(
                self.new_engine.synthesize(text, speed=tts_speed, voice=voice),
                self._bg_loop,
            )
            audio_data = fut.result(timeout=self.config.synthesis_timeout_sec)

            if audio_data is not None and len(audio_data) > 0:
                sf.write(filepath, audio_data, 32000)
                self._cache_put(cache_key, filepath)
                future.set_result(filepath)

                with self._lock:
                    self._inflight_sync.pop(cache_key, None)

                return filepath

            error_msg = (
                getattr(self.new_engine, "last_error", None)
                or "生成的音频数据为空"
            )
            raise TTSSynthesisError(
                error_msg,
                text=text[:100],
                provider=self._get_provider_name(),
            )

        except concurrent.futures.TimeoutError:
            error = TTSTimeoutError(
                f"合成超时，已等待 {self.config.synthesis_timeout_sec}s"
            )
            future.set_exception(error)
            with self._lock:
                self._inflight_sync.pop(cache_key, None)
            raise error

        except Exception as e:
            logger.error(f"TTS 合成失败: {e}")
            future.set_exception(e)

            with self._lock:
                self._inflight_sync.pop(cache_key, None)

            if isinstance(e, TTSError):
                raise
            raise TTSSynthesisError(
                f"语音合成失败: {str(e)}", text=text[:100]
            ) from e

    def _get_provider_name(self) -> str:
        """获取当前 TTS 提供者名称"""
        try:
            if self.new_engine and hasattr(self.new_engine, "settings"):
                settings = getattr(self.new_engine, "settings", None)
                tts_conf = get_config("voice.tts", default=None, settings=settings)
                return getattr(tts_conf, "provider", "unknown")
        except Exception:
            pass
        return "unknown"

    def clear_cache(self) -> None:
        """清除 TTS 缓存"""
        with self._lock:
            for entry in self._tts_cache.values():
                if "file_path" in entry and os.path.exists(entry["file_path"]):
                    try:
                        os.remove(entry["file_path"])
                    except Exception as e:
                        logger.warning(f"删除缓存文件失败: {e}")

            self._tts_cache.clear()
            logger.info("TTS 缓存已清除")

    def health_check(self) -> Dict[str, Any]:
        """
        获取健康状态和指标。

        Returns:
            包含健康信息的字典
        """
        cache_hit_rate = 0.0
        total_requests = self._cache_hits + self._cache_misses
        if total_requests > 0:
            cache_hit_rate = self._cache_hits / total_requests

        cache_size_mb = _get_directory_size(self.TEMP_DIR)
        _, free_disk_mb = _get_disk_usage(self.TEMP_DIR)

        return {
            "initialized": self._initialized,
            "shutting_down": self._shutting_down,
            "cache_entries": len(self._tts_cache),
            "cache_size_mb": cache_size_mb,
            "cache_hit_rate": cache_hit_rate,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "synthesis_count": self._synthesis_count,
            "inflight_async": len(self._inflight_async),
            "inflight_sync": len(self._inflight_sync),
            "free_disk_mb": free_disk_mb,
            "provider": self._get_provider_name(),
            "background_loop_running": self._bg_loop is not None
            and self._bg_loop.is_running(),
        }

    async def shutdown(self) -> None:
        """
        优雅关闭 TTS 管理器。

        等待进行中的请求完成（带超时），然后清理资源。
        """
        logger.info("正在关闭 TTS 管理器...")
        self._shutting_down = True

        if self._inflight_async:
            logger.info(
                f"等待 {len(self._inflight_async)} 个进行中的异步请求..."
            )
            try:
                await asyncio.wait(
                    self._inflight_async.values(), timeout=30.0
                )
            except Exception as e:
                logger.warning(f"等待进行中的请求时出错: {e}")
            finally:
                self._inflight_async.clear()

        self.clear_cache()

        if self.new_engine:
            try:
                await self.new_engine.shutdown()
            except Exception as e:
                logger.warning(f"关闭 TTS 引擎时出错: {e}")

        if self._bg_loop and self._bg_loop.is_running():
            try:
                self._bg_loop.call_soon_threadsafe(self._bg_loop.stop)
            except Exception as e:
                logger.warning(f"停止后台循环时出错: {e}")

        if self._bg_thread and self._bg_thread.is_alive():
            try:
                self._bg_thread.join(timeout=5.0)
            except Exception as e:
                logger.warning(f"等待后台线程时出错: {e}")

        self._initialized = False
        logger.info("TTS 管理器关闭完成")

    def close(self) -> None:
        """
        同步清理（向后兼容）。

        优先使用异步 shutdown() 进行优雅清理。
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.shutdown())
            else:
                loop.run_until_complete(self.shutdown())
        except Exception:
            self.clear_cache()
            self._initialized = False

            if self._bg_loop and self._bg_loop.is_running():
                try:
                    self._bg_loop.call_soon_threadsafe(self._bg_loop.stop)
                except Exception:
                    pass


# ============================================================================
# 向后兼容别名
# ============================================================================

TTSManager = TTSCacheManager


# ============================================================================
# 单例管理
# ============================================================================

_tts_manager_instance: Optional[TTSCacheManager] = None
_tts_manager_lock = Lock()


def get_tts_manager(config: Optional[TTSCacheConfig] = None) -> TTSCacheManager:
    """
    获取单例 TTS 管理器实例。

    Args:
        config: 可选配置（仅在首次调用时使用）

    Returns:
        TTSCacheManager 实例
    """
    global _tts_manager_instance

    with _tts_manager_lock:
        if _tts_manager_instance is None:
            _tts_manager_instance = TTSCacheManager(config)

    return _tts_manager_instance


async def cleanup_tts() -> None:
    """清理 TTS 资源（异步）"""
    global _tts_manager_instance

    with _tts_manager_lock:
        if _tts_manager_instance:
            await _tts_manager_instance.shutdown()
            _tts_manager_instance = None


def cleanup_tts_sync() -> None:
    """清理 TTS 资源（同步，向后兼容）"""
    global _tts_manager_instance

    with _tts_manager_lock:
        if _tts_manager_instance:
            _tts_manager_instance.close()
            _tts_manager_instance = None
