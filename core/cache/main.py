import time
import threading
import logging
import functools
import hashlib
import sys
from collections import OrderedDict, defaultdict
from enum import Enum
from typing import Any, Dict, Optional, Callable, Union, List, Tuple
# 配置日志
logger = logging.getLogger(__name__)
class CacheStrategy(Enum):
    """缓存策略枚举"""
    LRU = "LRU"  # 最近最少使用
    MRU = "MRU"  # 最近最多使用
    FIFO = "FIFO"  # 先进先出
    LFU = "LFU"  # 最少使用频率
class EnhancedCacheManager:
    """增强的缓存管理器，支持多种缓存策略和完善的过期管理"""
    def __init__(
        self,
        max_size: int = 100,
        ttl: int = 3600,
        strategy: CacheStrategy = CacheStrategy.LRU,
        item_size_limit: Optional[int] = None,  # 单条缓存大小限制（字节）
        stats_enabled: bool = True,
    ):
        """
        初始化增强缓存管理器
        Args:
            max_size: 最大缓存项数量
            ttl: 默认缓存过期时间（秒）
            strategy: 缓存替换策略
            item_size_limit: 单条缓存大小限制（字节），None表示不限制
            stats_enabled: 是否启用统计功能
        """
        # 参数验证
        if max_size <= 0:
            raise ValueError("缓存最大大小必须为正整数")
        if ttl <= 0:
            raise ValueError("TTL必须为正整数")
        self.max_size = max_size
        self.ttl = ttl
        self.strategy = strategy
        self.item_size_limit = item_size_limit
        self.stats_enabled = stats_enabled
        # 存储缓存数据
        self.cache: Dict[str, Tuple[Any, float, int, Optional[int]]] = (
            {}
        )  # key -> (value, timestamp, access_count, item_ttl)
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
            # 保留统计信息
    def _remove_key(self, key: str) -> None:
        """
        内部方法：移除键
        Args:
            key: 要移除的键
        """
        if key in self.cache:
            del self.cache[key]
        if hasattr(self, 'order') and key in self.order:
            del self.order[key]
        if hasattr(self, 'freq') and key in self.freq:
            del self.freq[key]
    def _evict_one(self) -> None:
        """
        内部方法：驱逐一个缓存项
        """
        if not self.cache:
            return
        evict_key = None
        if self.strategy == CacheStrategy.LRU:
            # 驱逐最旧的项（OrderedDict的第一个项）
            evict_key, _ = next(iter(self.order.items()))
        elif self.strategy == CacheStrategy.MRU:
            # 驱逐最新的项（OrderedDict的最后一个项）
            evict_key, _ = next(reversed(self.order.items()))
        elif self.strategy == CacheStrategy.FIFO:
            # 驱逐最早加入的项
            evict_key, _ = next(iter(self.order.items()))
        elif self.strategy == CacheStrategy.LFU:
            # 驱逐使用频率最低的项
            min_freq = min(self.freq.values())
            # 找出所有使用频率最低的键
            min_freq_keys = [k for k, v in self.freq.items() if v == min_freq]
            # 如果有多个，选择最早加入的
            evict_key = min_freq_keys[0]
        if evict_key:
            self._remove_key(evict_key)
            if self.stats_enabled:
                self.evictions += 1
    def _estimate_size(self, obj: Any) -> int:
        """
        估算对象大小（字节）
        Args:
            obj: 要估算大小的对象
        Returns:
            估算的大小（字节）
        """
        try:
            # 对于常见类型进行简单估算
            if isinstance(obj, (int, float, bool)):
                return sys.getsizeof(obj)
            elif isinstance(obj, str):
                return len(obj.encode('utf-8'))
            elif isinstance(obj, (list, tuple)):
                return sum(self._estimate_size(item) for item in obj)
            elif isinstance(obj, dict):
                return sum(
                    self._estimate_size(k) + self._estimate_size(v)
                    for k, v in obj.items()
                )
            elif hasattr(obj, '__dict__'):
                # 对于自定义对象，估算其属性的大小
                return sum(
                    self._estimate_size(k) + self._estimate_size(v)
                    for k, v in obj.__dict__.items()
                )
            else:
                # 默认返回一个合理的估计值
                return 100
        except Exception as e:
            logger.error(f"估算对象大小时出错: {e}")
            return 100
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值
        
        Args:
            key: 缓存键
            
        Returns:
            缓存值，如果不存在或已过期则返回None
        """
        with self.lock:
            if key not in self.cache:
                if self.stats_enabled:
                    self.misses += 1
                return None
            
            # 获取缓存项: (value, timestamp, access_count, item_ttl)
            value, timestamp, access_count, item_ttl = self.cache[key]
            current_time = time.time()
            
            # 检查是否过期
            ttl_to_use = item_ttl if item_ttl is not None else self.ttl
            if current_time - timestamp > ttl_to_use:
                # 已过期，移除
                self._remove_key(key)
                if self.stats_enabled:
                    self.expirations += 1
                    self.misses += 1
                return None
            
            # 更新访问计数和访问时间
            self.cache[key] = (value, current_time, access_count + 1, item_ttl)
            
            # 更新策略相关的数据结构
            if self.strategy == CacheStrategy.LRU or self.strategy == CacheStrategy.MRU:
                # 移动到末尾（最近使用）
                if key in self.order:
                    del self.order[key]
                self.order[key] = True
            elif self.strategy == CacheStrategy.LFU:
                # 增加访问频率
                self.freq[key] += 1
            
            if self.stats_enabled:
                self.hits += 1
            
            return value
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），None使用默认TTL
            
        Returns:
            bool: 是否成功设置
        """
        with self.lock:
            current_time = time.time()
            item_ttl = ttl if ttl is not None else self.ttl
            
            # 检查单条缓存大小限制
            if self.item_size_limit is not None:
                item_size = self._estimate_size(value)
                if item_size > self.item_size_limit:
                    logger.warning(f"缓存项大小 {item_size} 超过限制 {self.item_size_limit}")
                    return False
            
            # 如果键已存在，更新它
            if key in self.cache:
                self.cache[key] = (value, current_time, 0, item_ttl)
            else:
                # 检查缓存大小限制
                if len(self.cache) >= self.max_size:
                    self._evict_one()
                
                # 添加新项
                self.cache[key] = (value, current_time, 0, item_ttl)
            
            # 更新策略相关的数据结构
            if self.strategy == CacheStrategy.LRU or self.strategy == CacheStrategy.MRU:
                if key in self.order:
                    del self.order[key]
                self.order[key] = True
            elif self.strategy == CacheStrategy.FIFO:
                if key not in self.order:
                    self.order[key] = True
            elif self.strategy == CacheStrategy.LFU:
                self.freq[key] = 1
            
            return True
    
    def delete(self, key: str) -> bool:
        """
        删除缓存项
        
        Args:
            key: 缓存键
            
        Returns:
            bool: 是否成功删除
        """
        with self.lock:
            if key in self.cache:
                self._remove_key(key)
                return True
            return False
    
    def clear(self) -> None:
        """
        清空所有缓存
        """
        with self.lock:
            self.cache.clear()
            if hasattr(self, 'order'):
                self.order.clear()
            if hasattr(self, 'freq'):
                self.freq.clear()
            if self.stats_enabled:
                self.hits = 0
                self.misses = 0
                self.evictions = 0
                self.expirations = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            统计信息字典
        """
        with self.lock:
            if not self.stats_enabled:
                return {}
            
            total_requests = self.hits + self.misses
            hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0
            
            return {
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
                "expirations": self.expirations,
                "hit_rate": hit_rate,
                "size": len(self.cache),
                "max_size": self.max_size
            }

# 全局缓存管理器实例
_global_cache_manager = EnhancedCacheManager()

def get_cache_manager() -> EnhancedCacheManager:
    """
    获取全局缓存管理器实例
    Returns:
        EnhancedCacheManager实例
    """
    global _global_cache_manager
    if _global_cache_manager is None:
        _global_cache_manager = EnhancedCacheManager()
    return _global_cache_manager

def cache_decorator(
    key_func: Optional[Callable] = None,
    ttl: Optional[int] = None,
    cache_manager: Optional[EnhancedCacheManager] = None
):
    """
    缓存装饰器 - 为函数添加缓存功能
    
    Args:
        key_func: 自定义缓存键生成函数
        ttl: 自定义缓存过期时间（秒），None使用缓存管理器默认值
        cache_manager: 指定使用的缓存管理器，None使用全局缓存管理器
    
    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        nonlocal cache_manager
        if cache_manager is None:
            cache_manager = get_cache_manager()
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 生成缓存键
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # 简单的缓存键生成策略
                args_str = str(args)
                kwargs_str = str(sorted(kwargs.items()))
                func_str = func.__name__
                cache_key = f"{func_str}:{args_str}:{kwargs_str}"
                
            # 尝试从缓存获取
            result = cache_manager.get(cache_key)
            if result is not None:
                return result
            
            # 执行函数
            result = func(*args, **kwargs)
            
            # 存入缓存
            cache_manager.set(cache_key, result, ttl)
            
            return result
        
        return wrapper
    
    return decorator