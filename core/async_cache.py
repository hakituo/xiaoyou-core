#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步缓存管理器
提供线程安全的异步LRU缓存实现
"""
import asyncio
import time
import logging
from typing import Any, Dict, Optional, Callable, TypeVar, Generic
from collections import OrderedDict
import threading

logger = logging.getLogger(__name__)

T = TypeVar('T')


class AsyncLRUCache(Generic[T]):
    """
    异步LRU缓存实现
    使用OrderedDict作为底层存储，并提供线程安全的异步接口
    """
    
    def __init__(self, 
                 max_size: int = 1000, 
                 default_ttl: int = 3600,
                 cleanup_interval: int = 60):
        """
        初始化异步LRU缓存
        
        Args:
            max_size: 缓存最大条目数
            default_ttl: 默认过期时间(秒)
            cleanup_interval: 定期清理间隔(秒)
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.cleanup_interval = cleanup_interval
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._lock = threading.RLock()  # 可重入锁，保证线程安全
        self._running = False
        self._cleanup_task: Optional[asyncio.Task] = None
        
    async def initialize(self):
        """
        初始化缓存，启动定期清理任务
        """
        if self._running:
            return
        
        logger.info(f"初始化异步LRU缓存: max_size={self.max_size}, default_ttl={self.default_ttl}s")
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("异步LRU缓存初始化完成")
    
    async def shutdown(self):
        """
        关闭缓存，取消清理任务
        """
        if not self._running:
            return
        
        logger.info("正在关闭异步LRU缓存...")
        self._running = False
        
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # 清空缓存
        with self._lock:
            self._cache.clear()
        
        logger.info("异步LRU缓存已关闭")
    
    async def _cleanup_loop(self):
        """
        定期清理过期缓存的任务
        """
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self.cleanup()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"缓存清理任务错误: {str(e)}", exc_info=True)
    
    async def cleanup(self):
        """
        清理过期的缓存条目
        """
        current_time = time.time()
        expired_keys = []
        
        with self._lock:
            for key, value_info in self._cache.items():
                if value_info['expire_at'] < current_time:
                    expired_keys.append(key)
            
            # 删除过期条目
            for key in expired_keys:
                del self._cache[key]
        
        if expired_keys:
            logger.debug(f"清理了 {len(expired_keys)} 个过期缓存条目")
    
    async def get(self, key: str) -> Optional[T]:
        """
        获取缓存值
        
        Args:
            key: 缓存键
            
        Returns:
            缓存值，如果不存在或已过期则返回None
        """
        current_time = time.time()
        
        with self._lock:
            if key not in self._cache:
                return None
            
            value_info = self._cache[key]
            
            # 检查是否过期
            if value_info['expire_at'] < current_time:
                del self._cache[key]  # 删除过期条目
                return None
            
            # 更新访问顺序（LRU策略）
            self._cache.move_to_end(key)
            return value_info['value']
    
    async def set(self, 
                 key: str, 
                 value: T, 
                 ttl: Optional[int] = None) -> None:
        """
        设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间(秒)，None则使用默认值
        """
        expire_at = time.time() + (ttl if ttl is not None else self.default_ttl)
        
        with self._lock:
            # 如果缓存已满，删除最久未使用的条目
            if key not in self._cache and len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)  # 删除第一个条目（最久未使用）
            
            # 设置缓存值
            self._cache[key] = {
                'value': value,
                'expire_at': expire_at,
                'created_at': time.time()
            }
            
            # 更新访问顺序
            self._cache.move_to_end(key)
    
    async def delete(self, key: str) -> bool:
        """
        删除缓存条目
        
        Args:
            key: 缓存键
            
        Returns:
            是否成功删除
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    async def exists(self, key: str) -> bool:
        """
        检查缓存键是否存在且未过期
        
        Args:
            key: 缓存键
            
        Returns:
            是否存在且未过期
        """
        current_time = time.time()
        
        with self._lock:
            if key not in self._cache:
                return False
            
            if self._cache[key]['expire_at'] < current_time:
                del self._cache[key]  # 惰性删除
                return False
            
            return True
    
    async def clear(self) -> None:
        """
        清空所有缓存
        """
        with self._lock:
            self._cache.clear()
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            统计信息字典
        """
        current_time = time.time()
        valid_count = 0
        expired_count = 0
        total_size = 0
        
        with self._lock:
            for value_info in self._cache.values():
                if value_info['expire_at'] > current_time:
                    valid_count += 1
                else:
                    expired_count += 1
                
                # 估算缓存大小
                try:
                    total_size += len(str(value_info['value']))
                except:
                    pass
        
        return {
            'max_size': self.max_size,
            'current_size': valid_count + expired_count,
            'valid_entries': valid_count,
            'expired_entries': expired_count,
            'estimated_memory_bytes': total_size,
            'default_ttl': self.default_ttl,
            'cleanup_interval': self.cleanup_interval
        }
    
    def is_healthy(self) -> bool:
        """
        检查缓存是否健康运行
        """
        return self._running


# 缓存管理器，用于管理多个缓存实例
class CacheManager:
    """
    缓存管理器
    管理多个不同用途的缓存实例
    """
    
    def __init__(self):
        self._caches: Dict[str, AsyncLRUCache] = {}
        self._lock = threading.RLock()
    
    async def initialize(self):
        """
        初始化所有缓存
        """
        with self._lock:
            for name, cache in self._caches.items():
                await cache.initialize()
    
    async def shutdown(self):
        """
        关闭所有缓存
        """
        with self._lock:
            for name, cache in self._caches.items():
                await cache.shutdown()
            self._caches.clear()
    
    def get_cache(self, 
                  name: str = "default", 
                  max_size: int = 1000,
                  default_ttl: int = 3600) -> AsyncLRUCache:
        """
        获取或创建缓存实例
        
        Args:
            name: 缓存名称
            max_size: 最大大小
            default_ttl: 默认过期时间
            
        Returns:
            缓存实例
        """
        with self._lock:
            if name not in self._caches:
                self._caches[name] = AsyncLRUCache(
                    max_size=max_size,
                    default_ttl=default_ttl
                )
            return self._caches[name]
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        获取所有缓存的统计信息
        """
        stats = {}
        with self._lock:
            for name, cache in self._caches.items():
                stats[name] = await cache.get_stats()
        return stats


# 全局缓存管理器实例
_cache_manager: Optional[CacheManager] = None


def get_cache_manager() -> CacheManager:
    """
    获取全局缓存管理器实例
    """
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager


# 获取默认缓存
def get_cache() -> AsyncLRUCache:
    """
    获取默认缓存实例
    """
    from core.core_engine.config_manager import ConfigManager
    config = ConfigManager().get_config()
    cache_config = config.get("cache", {})
    
    manager = get_cache_manager()
    return manager.get_cache(
        name="default",
        max_size=cache_config.get("max_size", 1000),
        default_ttl=cache_config.get("ttl", 3600)
    )


# 异步缓存装饰器
def async_cache(*, 
               ttl: Optional[int] = None,
               cache_name: str = "default",
               key_generator: Optional[Callable[..., str]] = None):
    """
    异步函数缓存装饰器
    
    Args:
        ttl: 缓存过期时间
        cache_name: 缓存名称
        key_generator: 自定义键生成器
        
    Returns:
        装饰后的函数
    """
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @asyncio.coroutine
        async def wrapper(*args, **kwargs):
            # 生成缓存键
            if key_generator:
                cache_key = key_generator(*args, **kwargs)
            else:
                # 默认键生成策略
                key_parts = [func.__qualname__]
                key_parts.extend(str(arg) for arg in args)
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = ":".join(key_parts)
            
            # 获取缓存
            cache = get_cache_manager().get_cache(name=cache_name)
            cached_result = await cache.get(cache_key)
            
            if cached_result is not None:
                logger.debug(f"缓存命中: {cache_key}")
                return cached_result
            
            # 执行函数
            result = await func(*args, **kwargs)
            
            # 缓存结果
            await cache.set(cache_key, result, ttl=ttl)
            logger.debug(f"缓存设置: {cache_key}")
            
            return result
        
        return wrapper
    
    return decorator


# 初始化和关闭函数
async def initialize_cache():
    """
    初始化缓存系统
    """
    manager = get_cache_manager()
    await manager.initialize()
    logger.info("缓存系统初始化完成")


async def shutdown_cache():
    """
    关闭缓存系统
    """
    manager = get_cache_manager()
    await manager.shutdown()
    logger.info("缓存系统已关闭")