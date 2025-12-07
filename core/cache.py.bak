import time
import threading
import logging
from collections import OrderedDict, defaultdict
from enum import Enum
from typing import Any, Dict, Optional, Callable, Tuple, Union

# Configure logging
logger = logging.getLogger(__name__)


class CacheStrategy(Enum):
    """缓存策略枚举"""
    LRU = "LRU"  # 最近最少使用
    MRU = "MRU"  # 最近最多使用
    FIFO = "FIFO"  # 先进先出
    LFU = "LFU"  # 最少使用频率


class EnhancedCacheManager:
    """增强的缓存管理器，支持多种缓存策略和完善的过期管理"""
    
    def __init__(self, 
                 max_size: int = 100, 
                 ttl: int = 3600, 
                 strategy: CacheStrategy = CacheStrategy.LRU,
                 item_size_limit: Optional[int] = None,  # 单条缓存大小限制（字节）
                 stats_enabled: bool = True):
        """
        初始化增强缓存管理器
        
        Args:
            max_size: 最大缓存项数量
            ttl: 默认缓存过期时间（秒）
            strategy: 缓存替换策略
            item_size_limit: 单条缓存大小限制（字节），None表示不限制
            stats_enabled: 是否启用统计功能
        """
        self.max_size = max_size
        self.ttl = ttl
        self.strategy = strategy
        self.item_size_limit = item_size_limit
        self.stats_enabled = stats_enabled
        
        # 存储缓存数据
        self.cache: Dict[str, Tuple[Any, float, int, Optional[int]]] = {}  # key -> (value, timestamp, access_count, item_ttl)
        
        # 根据策略选择合适的数据结构
        if strategy == CacheStrategy.LRU or strategy == CacheStrategy.MRU:
            self.order = OrderedDict()
        elif strategy == CacheStrategy.FIFO:
            self.order = OrderedDict()
        elif strategy == CacheStrategy.LFU:
            self.freq = defaultdict(int)  # key -> access frequency
        
        # 线程锁确保线程安全
        self.lock = threading.RLock()  # 使用可重入锁
        
        # 统计信息
        if stats_enabled:
            self.hits = 0
            self.misses = 0
            self.evictions = 0
            self.expirations = 0
            self.last_stats_reset = time.time()
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存项，如果过期则返回None
        
        Args:
            key: 缓存键
            
        Returns:
            缓存的值，如果不存在或已过期则返回None
        """
        with self.lock:
            if key not in self.cache:
                if self.stats_enabled:
                    self.misses += 1
                return None
            
            value, timestamp, access_count, item_ttl = self.cache[key]
            
            # 检查是否过期，使用项特定的TTL或默认TTL
            ttl_to_use = item_ttl if item_ttl is not None else self.ttl
            if time.time() - timestamp > ttl_to_use:
                self._remove_key(key)
                if self.stats_enabled:
                    self.misses += 1
                    self.expirations += 1
                return None
            
            # 更新访问计数
            access_count += 1
            self.cache[key] = (value, timestamp, access_count, item_ttl)
            
            # 根据策略更新缓存顺序
            if self.strategy == CacheStrategy.LRU:
                self.order.move_to_end(key)
            elif self.strategy == CacheStrategy.MRU:
                # MRU策略，保持在最近使用位置
                self.order.move_to_end(key)
            elif self.strategy == CacheStrategy.LFU:
                self.freq[key] = access_count
            
            if self.stats_enabled:
                self.hits += 1
            
            return value
    
    def set(self, key: str, value: Any, custom_ttl: Optional[int] = None) -> bool:
        """
        设置缓存项，自动管理大小限制和过期时间
        
        Args:
            key: 缓存键
            value: 缓存值
            custom_ttl: 自定义过期时间（秒），None使用默认值
            
        Returns:
            是否成功设置缓存
        """
        try:
            # 检查单条缓存大小限制
            if self.item_size_limit:
                # 简单估算大小
                size = len(str(value))
                if size > self.item_size_limit:
                    logger.warning(f"缓存项大小超过限制: {size} > {self.item_size_limit} bytes")
                    return False
            
            with self.lock:
                # 如果缓存已满且不是更新现有项，则需要驱逐
                if len(self.cache) >= self.max_size and key not in self.cache:
                    self._evict_item()
                
                # 记录时间戳和初始访问计数
                timestamp = time.time()
                access_count = 1
                
                # 存储缓存项，包括自定义TTL
                self.cache[key] = (value, timestamp, access_count, custom_ttl)
                
                # 更新顺序信息
                if self.strategy == CacheStrategy.LRU or self.strategy == CacheStrategy.MRU or self.strategy == CacheStrategy.FIFO:
                    # 对于FIFO，只有新项才添加到末尾
                    if key in self.order:
                        if self.strategy != CacheStrategy.FIFO:  # FIFO不更新顺序
                            self.order.move_to_end(key)
                    else:
                        self.order[key] = True
                elif self.strategy == CacheStrategy.LFU:
                    self.freq[key] = access_count
                
                return True
        except Exception as e:
            logger.error(f"设置缓存时出错: {str(e)}")
            return False
    
    def delete(self, key: str) -> bool:
        """
        删除指定缓存项
        
        Args:
            key: 要删除的缓存键
            
        Returns:
            是否成功删除
        """
        with self.lock:
            if key in self.cache:
                self._remove_key(key)
                return True
            return False
    
    def clear(self) -> None:
        """清空所有缓存"""
        with self.lock:
            self.cache.clear()
            if self.strategy == CacheStrategy.LRU or self.strategy == CacheStrategy.MRU or self.strategy == CacheStrategy.FIFO:
                self.order.clear()
            elif self.strategy == CacheStrategy.LFU:
                self.freq.clear()
            
            # 重置统计
            if self.stats_enabled:
                self.hits = 0
                self.misses = 0
                self.evictions = 0
                self.expirations = 0
                self.last_stats_reset = time.time()
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            包含统计数据的字典
        """
        with self.lock:
            if not self.stats_enabled:
                return {"error": "统计功能未启用"}
            
            total_accesses = self.hits + self.misses
            hit_rate = (self.hits / total_accesses * 100) if total_accesses > 0 else 0
            
            return {
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": hit_rate,
                "size": len(self.cache),
                "max_size": self.max_size,
                "evictions": self.evictions,
                "expirations": self.expirations,
                "strategy": self.strategy.value,
                "ttl": self.ttl,
                "uptime": time.time() - self.last_stats_reset
            }
    
    def _remove_key(self, key: str) -> None:
        """
        移除指定键并更新所有相关数据结构
        """
        if key in self.cache:
            del self.cache[key]
            
        if self.strategy == CacheStrategy.LRU or self.strategy == CacheStrategy.MRU or self.strategy == CacheStrategy.FIFO:
            if key in self.order:
                del self.order[key]
        elif self.strategy == CacheStrategy.LFU:
            if key in self.freq:
                del self.freq[key]
    
    def _evict_item(self) -> None:
        """
        根据缓存策略驱逐一个项
        """
        if not self.cache:
            return
            
        evict_key = None
        
        if self.strategy == CacheStrategy.LRU:
            # 驱逐最久未使用的项（OrderedDict的第一项）
            evict_key, _ = self.order.popitem(last=False)
        elif self.strategy == CacheStrategy.MRU:
            # 驱逐最近使用的项（OrderedDict的最后一项）
            evict_key, _ = self.order.popitem(last=True)
        elif self.strategy == CacheStrategy.FIFO:
            # 驱逐最先进入的项（OrderedDict的第一项）
            evict_key, _ = self.order.popitem(last=False)
        elif self.strategy == CacheStrategy.LFU:
            # 驱逐使用频率最低的项
            if self.freq:
                evict_key = min(self.freq.items(), key=lambda x: x[1])[0]
        
        if evict_key:
            self._remove_key(evict_key)
            if self.stats_enabled:
                self.evictions += 1
    
    def update_config(self, **kwargs) -> Dict[str, Any]:
        """
        动态更新缓存配置
        
        Args:
            **kwargs: 要更新的配置项
            
        Returns:
            更新后的配置
        """
        with self.lock:
            if 'max_size' in kwargs:
                new_size = kwargs['max_size']
                self.max_size = new_size
                # 如果新大小小于当前缓存数量，需要驱逐
                while len(self.cache) > self.max_size:
                    self._evict_item()
            
            if 'ttl' in kwargs:
                self.ttl = kwargs['ttl']
                # 不立即清理过期项，而是在下次访问时处理
            
            if 'strategy' in kwargs:
                # 更改策略时需要重建顺序结构
                old_strategy = self.strategy
                self.strategy = kwargs['strategy']
                
                if old_strategy != self.strategy:
                    # 根据新策略初始化数据结构
                    if self.strategy == CacheStrategy.LRU or self.strategy == CacheStrategy.MRU or self.strategy == CacheStrategy.FIFO:
                        self.order = OrderedDict()
                        # 重建顺序（简单使用当前键的顺序）
                        for key in list(self.cache.keys()):
                            self.order[key] = True
                    elif self.strategy == CacheStrategy.LFU:
                        self.freq = defaultdict(int)
                        # 重建频率统计
                        for key, (_, _, access_count) in self.cache.items():
                            self.freq[key] = access_count
            
            if 'item_size_limit' in kwargs:
                self.item_size_limit = kwargs['item_size_limit']
            
            if 'stats_enabled' in kwargs:
                self.stats_enabled = kwargs['stats_enabled']
                if self.stats_enabled:
                    # 重置统计
                    self.hits = 0
                    self.misses = 0
                    self.evictions = 0
                    self.expirations = 0
                    self.last_stats_reset = time.time()
            
            return {
                "max_size": self.max_size,
                "ttl": self.ttl,
                "strategy": self.strategy.value,
                "item_size_limit": self.item_size_limit,
                "stats_enabled": self.stats_enabled
            }


# 创建默认缓存实例
default_cache = EnhancedCacheManager(
    max_size=100,
    ttl=1800,  # 30分钟
    strategy=CacheStrategy.LRU,
    stats_enabled=True
)


def get_default_cache() -> EnhancedCacheManager:
    """
    获取默认缓存实例
    
    Returns:
        默认的缓存管理器实例
    """
    return default_cache


def cache_decorator(max_size: int = 50, ttl: int = 1800, strategy: CacheStrategy = CacheStrategy.LRU):
    """
    缓存装饰器，用于缓存函数结果
    
    Args:
        max_size: 最大缓存项数量
        ttl: 缓存过期时间（秒）
        strategy: 缓存策略
        
    Returns:
        装饰后的函数
    """
    # 为每个装饰的函数创建独立的缓存实例
    local_cache = EnhancedCacheManager(max_size=max_size, ttl=ttl, strategy=strategy)
    
    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            # 生成缓存键
            key = _generate_cache_key(func, args, kwargs)
            
            # 尝试从缓存获取结果
            result = local_cache.get(key)
            if result is not None:
                return result
            
            # 执行函数
            result = await func(*args, **kwargs)
            
            # 存入缓存
            local_cache.set(key, result)
            
            return result
        
        def sync_wrapper(*args, **kwargs):
            # 生成缓存键
            key = _generate_cache_key(func, args, kwargs)
            
            # 尝试从缓存获取结果
            result = local_cache.get(key)
            if result is not None:
                return result
            
            # 执行函数
            result = func(*args, **kwargs)
            
            # 存入缓存
            local_cache.set(key, result)
            
            return result
        
        # 根据被装饰函数的类型返回相应的包装器
        if hasattr(func, '__code__') and func.__code__.co_flags & 0x80:  # 检查是否为协程函数
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def _generate_cache_key(func, args, kwargs) -> str:
    """
    生成缓存键
    
    Args:
        func: 函数对象
        args: 位置参数
        kwargs: 关键字参数
        
    Returns:
        缓存键字符串
    """
    import hashlib
    
    # 使用函数名、模块和参数生成键
    key_parts = [
        func.__module__ or '',
        func.__name__
    ]
    
    # 添加位置参数的字符串表示（仅前3个参数）
    for arg in args[:3]:
        try:
            # 尝试获取对象的唯一标识
            if hasattr(arg, '__dict__'):
                # 对于复杂对象，只使用其类型和ID
                key_parts.append(f"{type(arg).__name__}:{id(arg)}")
            else:
                # 对于简单类型，使用其字符串表示
                key_parts.append(str(arg))
        except:
            # 出现异常时使用类型名称
            key_parts.append(str(type(arg)))
    
    # 添加关键字参数（仅前3个）
    for k, v in sorted(kwargs.items())[:3]:
        key_parts.append(f"{k}:{v}")
    
    # 生成哈希值作为最终键
    key_str = ':'.join(key_parts)
    return hashlib.md5(key_str.encode()).hexdigest()