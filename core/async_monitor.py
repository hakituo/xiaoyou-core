import asyncio
import time
import psutil
from typing import Dict, Any, List
import threading
import json
import os
from datetime import datetime
import logging
from collections import deque

logger = logging.getLogger(__name__)


class PerformanceMonitor:
    """
    异步性能监控器，收集系统资源使用情况和应用性能指标
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.interval = self.config.get("interval", 5.0)  # 监控间隔（秒）
        self.history_size = self.config.get("history_size", 60)  # 历史数据保留条数
        
        # 检查GPU可用性
        self._torch_available = False
        self._pynvml_available = False
        try:
            import torch
            if torch.cuda.is_available():
                self._torch_available = True
        except ImportError:
            pass
            
        try:
            import pynvml
            pynvml.nvmlInit()
            self._pynvml_available = True
            logger.info("pynvml initialized successfully")
        except Exception as e:
            logger.warning(f"pynvml initialization failed: {e}")
        
        # 性能指标历史数据
        self.metrics_history: Dict[str, deque] = {
            "cpu_usage": deque(maxlen=self.history_size),
            "memory_usage": deque(maxlen=self.history_size),
            "gpu_usage": deque(maxlen=self.history_size),
            "async_tasks": deque(maxlen=self.history_size),
            "active_connections": deque(maxlen=self.history_size),
        }
        
        # 当前指标
        self.current_metrics: Dict[str, Any] = {
            "cpu_usage": 0.0,
            "memory_usage": 0.0,
            "gpu_usage": 0.0,
            "async_tasks": 0,
            "active_connections": 0,
            "timestamp": time.time(),
        }
        
        # 监控线程
        self.monitor_thread = None
        self.stop_event = threading.Event()
        
        # 应用特定指标
        self.app_metrics_lock = threading.RLock()
        self.app_metrics = {}
    
    def start(self):
        """
        启动性能监控线程
        """
        if not self.enabled:
            logger.warning("性能监控已禁用")
            return
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            logger.warning("性能监控已经在运行")
            return
        
        self.stop_event.clear()
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        logger.info(f"性能监控已启动，监控间隔: {self.interval}秒")
    
    def stop(self):
        """
        停止性能监控线程
        """
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.stop_event.set()
            self.monitor_thread.join(timeout=5.0)
            logger.info("性能监控已停止")
    
    def _monitor_loop(self):
        """
        监控循环，收集系统和应用指标
        """
        logger.info("PerformanceMonitor: Monitor loop started")
        while not self.stop_event.is_set():
            try:
                self._collect_metrics()
                self._save_history()
                
                # 检查是否需要告警
                self._check_health_thresholds()
            except Exception as e:
                logger.error(f"性能监控出错: {e}")
            
            # 等待下一次监控
            self.stop_event.wait(self.interval)
        logger.info("PerformanceMonitor: Monitor loop stopped")
    
    def _collect_metrics(self):
        """
        收集当前系统和应用指标
        """
        try:
            # 系统CPU使用率
            cpu_usage = psutil.cpu_percent(interval=0.1)
            
            # 系统内存使用率
            memory = psutil.virtual_memory()
            memory_usage = memory.percent
            
            # GPU使用率
            gpu_usage = 0.0
            if self._pynvml_available:
                try:
                    import pynvml
                    handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    gpu_usage = float(util.gpu)
                    
                    # 也可以获取显存使用率
                    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    # memory_usage = (mem.used / mem.total) * 100
                except Exception as e:
                    # logger.warning(f"Failed to get GPU metrics via pynvml: {e}")
                    pass
            elif self._torch_available:
                try:
                    import torch
                    # 使用显存占用作为GPU使用率的近似指标
                    # 注意：这只是显存占用，不是计算利用率
                    gpu_properties = torch.cuda.get_device_properties(0)
                    gpu_total_mem = gpu_properties.total_memory
                    gpu_allocated_mem = torch.cuda.memory_allocated()
                    gpu_usage = (gpu_allocated_mem / gpu_total_mem) * 100
                except Exception:
                    pass
            
            # 异步任务数（近似值）- 安全地获取事件循环
            async_tasks = 0
            try:
                # 在非主线程中，不能直接使用get_event_loop
                # 尝试获取当前运行的循环
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    async_tasks = len(asyncio.all_tasks(loop))
            except RuntimeError:
                # 没有运行中的事件循环
                pass
            except Exception as e:
                 # logger.debug(f"获取异步任务数失败: {e}")
                 pass
            
            # 保存当前指标
            self.current_metrics = {
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "gpu_usage": gpu_usage,
                "async_tasks": async_tasks,
                "active_connections": self.app_metrics.get("active_connections", 0),
                "timestamp": time.time(),
            }
            # logger.info(f"Metrics collected: {self.current_metrics}")
            
            # 合并应用特定指标
            with self.app_metrics_lock:
                self.current_metrics.update(self.app_metrics)
                
        except Exception as e:
            logger.error(f"收集指标失败: {e}")
    
    def _save_history(self):
        """
        保存指标到历史记录
        """
        try:
            timestamp = self.current_metrics["timestamp"]
            
            for metric_name in ["cpu_usage", "memory_usage", "gpu_usage", "async_tasks", "active_connections"]:
                if metric_name in self.current_metrics:
                    self.metrics_history[metric_name].append((timestamp, self.current_metrics[metric_name]))
        except Exception as e:
            logger.error(f"保存历史指标失败: {e}")
    
    def _check_health_thresholds(self):
        """
        检查健康阈值，超过阈值时发出警告
        """
        thresholds = self.config.get("thresholds", {})
        
        # 检查CPU使用率阈值
        cpu_threshold = thresholds.get("cpu_usage", 90.0)
        if self.current_metrics["cpu_usage"] > cpu_threshold:
            logger.warning(f"CPU使用率过高: {self.current_metrics['cpu_usage']}% (阈值: {cpu_threshold}%)")
        
        # 检查内存使用率阈值
        memory_threshold = thresholds.get("memory_usage", 85.0)
        if self.current_metrics["memory_usage"] > memory_threshold:
            logger.warning(f"内存使用率过高: {self.current_metrics['memory_usage']}% (阈值: {memory_threshold}%)")
        
        # 检查异步任务数量阈值
        tasks_threshold = thresholds.get("async_tasks", 1000)
        if self.current_metrics["async_tasks"] > tasks_threshold:
            logger.warning(f"异步任务数量过多: {self.current_metrics['async_tasks']} (阈值: {tasks_threshold})")
    
    def update_app_metrics(self, metrics: Dict[str, Any]):
        """
        更新应用特定指标
        """
        with self.app_metrics_lock:
            self.app_metrics.update(metrics)
    
    def get_current_metrics(self) -> Dict[str, Any]:
        """
        获取当前性能指标
        """
        # 如果当前指标过旧（超过2秒），且监控线程未运行或失效，尝试主动收集一次
        if time.time() - self.current_metrics.get("timestamp", 0) > 2:
            try:
                # 检查线程状态
                if not self.monitor_thread or not self.monitor_thread.is_alive():
                    # 线程未运行，主动收集
                    self._collect_metrics()
            except Exception:
                pass
        return self.current_metrics.copy()
    
    def get_metrics_history(self, metric_name: str, limit: int = None) -> List[tuple]:
        """
        获取指定指标的历史数据
        """
        if metric_name not in self.metrics_history:
            return []
        
        history = list(self.metrics_history[metric_name])
        if limit:
            return history[-limit:]
        return history
    
    def export_metrics(self, file_path: str = None) -> str:
        """
        导出当前性能指标为JSON格式
        """
        metrics_data = {
            "current": self.get_current_metrics(),
            "history": {k: list(v) for k, v in self.metrics_history.items()},
            "export_time": datetime.now().isoformat()
        }
        
        # 如果提供了文件路径，则保存到文件
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(metrics_data, f, ensure_ascii=False, indent=2)
                logger.info(f"性能指标已导出到: {file_path}")
            except Exception as e:
                logger.error(f"导出性能指标失败: {e}")
        
        return json.dumps(metrics_data, ensure_ascii=False, indent=2)


class HealthChecker:
    """
    健康检查器，定期检查各服务组件的健康状态
    """
    
    def __init__(self):
        self.health_checkers = {}
        self.health_status = {}
    
    def register_health_checker(self, service_name: str, checker_func, interval: float = 30.0):
        """
        注册服务健康检查函数
        """
        self.health_checkers[service_name] = {
            "checker": checker_func,
            "interval": interval,
            "last_check": 0
        }
        self.health_status[service_name] = {
            "status": "unknown",
            "details": None,
            "last_update": time.time()
        }
    
    async def check_service_health(self, service_name: str) -> Dict[str, Any]:
        """
        检查特定服务的健康状态
        """
        if service_name not in self.health_checkers:
            return {"status": "unknown", "details": f"未知服务: {service_name}"}
        
        checker_info = self.health_checkers[service_name]
        checker_func = checker_info["checker"]
        
        try:
            # 执行健康检查函数
            if asyncio.iscoroutinefunction(checker_func):
                result = await checker_func()
            else:
                result = await asyncio.to_thread(checker_func)
            
            # 更新健康状态
            health_result = {
                "status": "healthy" if result.get("status", "") == "healthy" else "unhealthy",
                "details": result.get("details", None),
                "last_update": time.time()
            }
            
            self.health_status[service_name] = health_result
            return health_result
        except Exception as e:
            error_result = {
                "status": "error",
                "details": str(e),
                "last_update": time.time()
            }
            self.health_status[service_name] = error_result
            logger.error(f"服务健康检查失败 [{service_name}]: {e}")
            return error_result
    
    async def check_all_services(self) -> Dict[str, Dict[str, Any]]:
        """
        检查所有已注册服务的健康状态
        """
        tasks = []
        for service_name in self.health_checkers.keys():
            tasks.append(self.check_service_health(service_name))
        
        results = await asyncio.gather(*tasks)
        return dict(zip(self.health_checkers.keys(), results))
    
    def get_health_summary(self) -> Dict[str, Any]:
        """
        获取整体健康状态摘要
        """
        all_healthy = all(status["status"] == "healthy" for status in self.health_status.values())
        summary = {
            "overall_status": "healthy" if all_healthy else "degraded",
            "services": self.health_status.copy(),
            "timestamp": time.time()
        }
        return summary


# 全局监控实例
_performance_monitor = None
_health_checker = None
_monitor_lock = threading.RLock()


def get_performance_monitor() -> PerformanceMonitor:
    """
    获取全局性能监控实例
    """
    global _performance_monitor
    with _monitor_lock:
        if _performance_monitor is None:
            _performance_monitor = PerformanceMonitor()
    return _performance_monitor


def get_health_checker() -> HealthChecker:
    """
    获取全局健康检查器实例
    """
    global _health_checker
    with _monitor_lock:
        if _health_checker is None:
            _health_checker = HealthChecker()
    return _health_checker


async def initialize_monitoring(config: Dict[str, Any] = None):
    """
    初始化异步监控系统
    """
    global _performance_monitor
    logger.info("Initializing monitoring system...")
    
    if _performance_monitor is not None:
        logger.info("Monitoring system already initialized, checking status...")
        if not _performance_monitor.monitor_thread or not _performance_monitor.monitor_thread.is_alive():
            logger.info("Monitor thread not running, restarting...")
            _performance_monitor.start()
        return

    try:
        if config is None:
            try:
                from core.core_engine.config_manager import ConfigManager
                config = ConfigManager().get_all_config()
            except Exception as e:
                logger.warning(f"无法加载配置，使用默认配置: {e}")
                config = {}
            
        monitor_config = config.get("performance_monitor", {})
        logger.info(f"Creating PerformanceMonitor with config: {monitor_config}")
        
        _performance_monitor = PerformanceMonitor(monitor_config)
        _performance_monitor.start()
        
        logger.info("异步监控系统初始化完成")
    except Exception as e:
        logger.error(f"初始化监控系统失败: {e}")


async def shutdown_monitoring():
    """
    关闭监控系统
    """
    global _performance_monitor
    
    with _monitor_lock:
        if _performance_monitor:
            _performance_monitor.stop()
            _performance_monitor = None
        
        global _health_checker
        _health_checker = None
        
        logger.info("异步监控系统已关闭")


# 中间件：请求性能监控
async def request_performance_middleware(request, call_next):
    """
    FastAPI中间件，监控每个请求的性能
    """
    start_time = time.time()
    
    # 执行请求
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        
        # 记录请求性能指标
        monitor = get_performance_monitor()
        monitor.update_app_metrics({
            "last_request_process_time": process_time,
            "last_request_path": request.url.path,
            "last_request_status": response.status_code
        })
        
        # 在响应头中添加处理时间
        response.headers["X-Process-Time"] = str(process_time)
        
        # 记录慢请求
        slow_request_threshold = 1.0  # 1秒
        if process_time > slow_request_threshold:
            logger.warning(f"慢请求警告: {request.url.path} 耗时: {process_time:.2f}秒")
        
        return response
    except Exception as e:
        # 记录异常请求
        process_time = time.time() - start_time
        logger.error(f"请求处理异常: {request.url.path} 耗时: {process_time:.2f}秒, 错误: {e}")
        raise


# 日志增强装饰器
def enhanced_logger(func):
    """
    函数日志增强装饰器，记录函数调用、参数、返回值和执行时间
    """
    func_name = func.__qualname__
    
    async def async_wrapper(*args, **kwargs):
        start_time = time.time()
        
        # 记录函数调用和参数
        logger.debug(f"[调用] {func_name} args={args} kwargs={kwargs}")
        
        try:
            # 执行原函数
            result = await func(*args, **kwargs)
            
            # 记录执行时间和返回值
            exec_time = time.time() - start_time
            logger.debug(f"[完成] {func_name} 耗时: {exec_time:.4f}秒 返回: {type(result).__name__}")
            
            return result
        except Exception as e:
            # 记录异常
            exec_time = time.time() - start_time
            logger.error(f"[异常] {func_name} 耗时: {exec_time:.4f}秒 错误: {str(e)}")
            raise
    
    def sync_wrapper(*args, **kwargs):
        start_time = time.time()
        
        # 记录函数调用和参数
        logger.debug(f"[调用] {func_name} args={args} kwargs={kwargs}")
        
        try:
            # 执行原函数
            result = func(*args, **kwargs)
            
            # 记录执行时间和返回值
            exec_time = time.time() - start_time
            logger.debug(f"[完成] {func_name} 耗时: {exec_time:.4f}秒 返回: {type(result).__name__}")
            
            return result
        except Exception as e:
            # 记录异常
            exec_time = time.time() - start_time
            logger.error(f"[异常] {func_name} 耗时: {exec_time:.4f}秒 错误: {str(e)}")
            raise
    
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper