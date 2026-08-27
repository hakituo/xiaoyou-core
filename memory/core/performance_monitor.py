"""
记忆系统性能监控模块

该模块提供记忆操作的运行时性能监控，
包括延迟追踪、吞吐量计算和性能报告生成。

优化内容:
1. 操作延迟追踪
2. 吞吐量计算
3. 性能报告生成
4. 慢操作检测
"""

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TypeVar
from contextlib import contextmanager
import statistics

T = TypeVar('T')


@dataclass
class OperationMetrics:
    """操作指标"""
    count: int = 0
    total_time_ms: float = 0.0
    min_time_ms: float = float('inf')
    max_time_ms: float = 0.0
    latencies: List[float] = field(default_factory=list)
    errors: int = 0
    
    @property
    def avg_time_ms(self) -> float:
        if self.count == 0:
            return 0.0
        return self.total_time_ms / self.count
    
    def add_latency(self, latency_ms: float, is_error: bool = False) -> None:
        self.count += 1
        self.total_time_ms += latency_ms
        self.min_time_ms = min(self.min_time_ms, latency_ms)
        self.max_time_ms = max(self.max_time_ms, latency_ms)
        if is_error:
            self.errors += 1
        self.latencies.append(latency_ms)
        if len(self.latencies) > 1000:
            self.latencies = self.latencies[-500:]
    
    def get_percentiles(self) -> Dict[str, float]:
        if not self.latencies:
            return {"p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0}
        
        sorted_latencies = sorted(self.latencies)
        n = len(sorted_latencies)
        
        return {
            "p50": sorted_latencies[int(n * 0.50)],
            "p90": sorted_latencies[int(n * 0.90)],
            "p95": sorted_latencies[int(n * 0.95)],
            "p99": sorted_latencies[int(n * 0.99)],
        }
    
    def to_dict(self) -> Dict[str, Any]:
        percentiles = self.get_percentiles()
        return {
            "count": self.count,
            "total_time_ms": round(self.total_time_ms, 2),
            "avg_time_ms": round(self.avg_time_ms, 2),
            "min_time_ms": round(self.min_time_ms, 2) if self.min_time_ms != float('inf') else 0.0,
            "max_time_ms": round(self.max_time_ms, 2),
            "errors": self.errors,
            "error_rate": round(self.errors / self.count, 4) if self.count > 0 else 0.0,
            **{k: round(v, 2) for k, v in percentiles.items()},
        }


@dataclass
class MemorySystemStats:
    """记忆系统统计"""
    total_memories: int = 0
    weighted_memories: int = 0
    short_term_memories: int = 0
    category_count: int = 0
    topic_count: int = 0
    index_size: int = 0
    cache_hit_rate: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_memories": self.total_memories,
            "weighted_memories": self.weighted_memories,
            "short_term_memories": self.short_term_memories,
            "category_count": self.category_count,
            "topic_count": self.topic_count,
            "index_size": self.index_size,
            "cache_hit_rate": round(self.cache_hit_rate, 4),
        }


class PerformanceMonitor:
    """
    性能监控器
    
    追踪记忆系统的操作性能，生成性能报告
    """
    
    _instance: Optional['PerformanceMonitor'] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> 'PerformanceMonitor':
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._metrics: Dict[str, OperationMetrics] = defaultdict(OperationMetrics)
                cls._instance._metrics_lock = threading.RLock()
                cls._instance._slow_threshold_ms = 100.0
                cls._instance._slow_ops: List[Dict[str, Any]] = []
                cls._instance._slow_ops_lock = threading.Lock()
                cls._instance._start_time = time.time()
        return cls._instance
    
    def set_slow_threshold(self, threshold_ms: float) -> None:
        """设置慢操作阈值"""
        self._slow_threshold_ms = threshold_ms
    
    @contextmanager
    def track_operation(self, operation: str):
        """
        追踪操作性能的上下文管理器
        
        Args:
            operation: 操作名称
            
        Yields:
            None
        """
        start = time.time()
        is_error = False
        
        try:
            yield
        except Exception:
            is_error = True
            raise
        finally:
            elapsed_ms = (time.time() - start) * 1000
            
            with self._metrics_lock:
                self._metrics[operation].add_latency(elapsed_ms, is_error)
            
            if elapsed_ms > self._slow_threshold_ms:
                with self._slow_ops_lock:
                    self._slow_ops.append({
                        "operation": operation,
                        "latency_ms": round(elapsed_ms, 2),
                        "timestamp": time.time(),
                        "is_error": is_error,
                    })
                    if len(self._slow_ops) > 100:
                        self._slow_ops = self._slow_ops[-50:]
    
    def track(self, operation: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
        """
        装饰器方式追踪操作性能
        
        Args:
            operation: 操作名称
            
        Returns:
            装饰器函数
        """
        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            def wrapper(*args, **kwargs) -> T:
                with self.track_operation(operation):
                    return func(*args, **kwargs)
            return wrapper
        return decorator
    
    def get_metrics(self, operation: Optional[str] = None) -> Dict[str, Any]:
        """
        获取指标
        
        Args:
            operation: 操作名称，None 表示获取所有
            
        Returns:
            Dict[str, Any]: 指标数据
        """
        with self._metrics_lock:
            if operation:
                return self._metrics.get(operation, OperationMetrics()).to_dict()
            return {k: v.to_dict() for k, v in self._metrics.items()}
    
    def get_slow_operations(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取慢操作列表"""
        with self._slow_ops_lock:
            return sorted(
                self._slow_ops,
                key=lambda x: x["latency_ms"],
                reverse=True
            )[:limit]
    
    def get_summary(self) -> Dict[str, Any]:
        """获取性能摘要"""
        with self._metrics_lock:
            total_ops = sum(m.count for m in self._metrics.values())
            total_errors = sum(m.errors for m in self._metrics.values())
            total_time = sum(m.total_time_ms for m in self._metrics.values())
            
            ops_per_second = 0.0
            uptime = time.time() - self._start_time
            if uptime > 0:
                ops_per_second = total_ops / uptime
            
            return {
                "uptime_seconds": round(uptime, 2),
                "total_operations": total_ops,
                "total_errors": total_errors,
                "error_rate": round(total_errors / total_ops, 4) if total_ops > 0 else 0.0,
                "total_time_ms": round(total_time, 2),
                "operations_per_second": round(ops_per_second, 2),
                "slow_threshold_ms": self._slow_threshold_ms,
                "slow_operations_count": len(self._slow_ops),
                "operations": {k: v.to_dict() for k, v in self._metrics.items()},
            }
    
    def reset(self) -> None:
        """重置所有指标"""
        with self._metrics_lock:
            self._metrics.clear()
        with self._slow_ops_lock:
            self._slow_ops.clear()
        self._start_time = time.time()
    
    def record_system_stats(
        self,
        total_memories: int,
        weighted_memories: int,
        short_term_memories: int,
        category_count: int,
        topic_count: int,
        index_size: int,
        cache_hit_rate: float,
    ) -> None:
        """记录系统统计"""
        self._system_stats = MemorySystemStats(
            total_memories=total_memories,
            weighted_memories=weighted_memories,
            short_term_memories=short_term_memories,
            category_count=category_count,
            topic_count=topic_count,
            index_size=index_size,
            cache_hit_rate=cache_hit_rate,
        )
    
    def get_system_stats(self) -> Dict[str, Any]:
        """获取系统统计"""
        if hasattr(self, '_system_stats'):
            return self._system_stats.to_dict()
        return {}


def get_performance_monitor() -> PerformanceMonitor:
    """获取性能监控器单例"""
    return PerformanceMonitor()


def track_memory_operation(operation: str):
    """
    记忆操作性能追踪装饰器
    
    Args:
        operation: 操作名称
        
    Returns:
        装饰器函数
    """
    monitor = get_performance_monitor()
    return monitor.track(operation)


class PerformanceReport:
    """性能报告生成器"""
    
    @staticmethod
    def generate_report() -> str:
        """生成性能报告"""
        monitor = get_performance_monitor()
        summary = monitor.get_summary()
        slow_ops = monitor.get_slow_operations()
        
        lines = [
            "=" * 60,
            "Memory System Performance Report",
            "=" * 60,
            "",
            f"Uptime: {summary['uptime_seconds']:.2f} seconds",
            f"Total Operations: {summary['total_operations']}",
            f"Total Errors: {summary['total_errors']}",
            f"Error Rate: {summary['error_rate'] * 100:.2f}%",
            f"Operations/Second: {summary['operations_per_second']:.2f}",
            "",
            "-" * 60,
            "Operation Metrics:",
            "-" * 60,
        ]
        
        for op, metrics in summary["operations"].items():
            lines.extend([
                f"  {op}:",
                f"    Count: {metrics['count']}",
                f"    Avg: {metrics['avg_time_ms']:.2f}ms",
                f"    Min: {metrics['min_time_ms']:.2f}ms",
                f"    Max: {metrics['max_time_ms']:.2f}ms",
                f"    P50: {metrics['p50']:.2f}ms",
                f"    P95: {metrics['p95']:.2f}ms",
                f"    P99: {metrics['p99']:.2f}ms",
                "",
            ])
        
        if slow_ops:
            lines.extend([
                "-" * 60,
                f"Slow Operations (>{summary['slow_threshold_ms']}ms):",
                "-" * 60,
            ])
            for op in slow_ops[:10]:
                lines.append(
                    f"  {op['operation']}: {op['latency_ms']:.2f}ms "
                    f"{'(ERROR)' if op['is_error'] else ''}"
                )
        
        lines.append("")
        lines.append("=" * 60)
        
        return "\n".join(lines)
