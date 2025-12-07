import os
import time
import logging
import threading
from dataclasses import dataclass
from typing import Dict, Optional, Callable

from config.integrated_config import get_settings

logger = logging.getLogger(__name__)

@dataclass
class ResourceStatus:
    """
    系统资源状态数据类
    """
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    gpu_memory_percent: Optional[float] = None
    gpu_free_gb: Optional[float] = None
    available_memory_gb: float = 0.0
    disk_usage_percent: float = 0.0
    system_load: float = 0.0
    timestamp: float = 0.0
    is_healthy: bool = True

class ResourceMonitor:
    """
    系统资源监控器
    提供实时的系统资源监控、预警和自动降级功能
    """
    
    def __init__(self):
        self._last_check_time = 0
        self._cache_validity = 2.0  # 缓存有效期（秒）
        self._status_cache: Optional[ResourceStatus] = None
        self._downgrade_handlers: Dict[str, Callable] = {}
        
        self.settings = get_settings()
        self._resource_thresholds = {
            "cpu_high": self.settings.monitor.cpu_threshold_high,
            "cpu_medium": self.settings.monitor.cpu_threshold_medium,
            "memory_high": self.settings.monitor.memory_threshold_high,
            "memory_medium": self.settings.monitor.memory_threshold_medium,
            "gpu_high": self.settings.monitor.gpu_memory_threshold_high,
            "gpu_medium": self.settings.monitor.gpu_memory_threshold_medium,
        }
        self._downgrade_level = 0  # 0: 正常, 1: 轻量降级, 2: 深度降级, 3: 紧急模式
        self._downgrade_reasons: Dict[str, bool] = {}
        self._lock = threading.RLock()  # 用于线程安全操作
        
        # 尝试导入必要的模块
        self._psutil_available = False
        self._torch_available = False
        try:
            import psutil
            self._psutil_available = True
        except ImportError:
            logger.warning("psutil未安装，无法进行完整的系统资源监控")
            
        try:
            import torch
            self._torch_available = torch.cuda.is_available()
        except ImportError:
            logger.debug("PyTorch未安装或GPU不可用")
        
        self._setup_downgrade_handlers()
        logger.info("资源监控器初始化完成")
    
    def _setup_downgrade_handlers(self):
        """
        设置不同级别的降级处理函数
        """
        self._downgrade_handlers["lightweight"] = self._lightweight_downgrade
        self._downgrade_handlers["medium"] = self._medium_downgrade
        self._downgrade_handlers["heavy"] = self._heavy_downgrade
        self._downgrade_handlers["emergency"] = self._emergency_downgrade
    
    def get_status(self, force_update: bool = False) -> ResourceStatus:
        """
        获取当前系统资源状态
        
        Args:
            force_update: 是否强制更新状态（忽略缓存）
            
        Returns:
            ResourceStatus: 当前系统资源状态
        """
        current_time = time.time()
        
        # 检查缓存是否有效
        if not force_update and self._status_cache and \
           (current_time - self._last_check_time) < self._cache_validity:
            return self._status_cache
        
        with self._lock:
            status = self._collect_resource_status()
            self._status_cache = status
            self._last_check_time = current_time
            
            # 更新降级级别
            self._update_downgrade_level(status)
            
            return status
    
    def _collect_resource_status(self) -> ResourceStatus:
        """
        收集系统资源状态
        """
        status = ResourceStatus(timestamp=time.time())
        
        # 收集CPU和内存信息
        if self._psutil_available:
            import psutil
            try:
                status.cpu_percent = psutil.cpu_percent(interval=0.1)
                memory_info = psutil.virtual_memory()
                status.memory_percent = memory_info.percent
                status.available_memory_gb = memory_info.available / (1024 ** 3)
                
                # 收集磁盘使用情况
                disk_usage = psutil.disk_usage('/')
                status.disk_usage_percent = disk_usage.percent
                
                # 收集系统负载（在Unix系统上）
                try:
                    load_avg = psutil.getloadavg()
                    status.system_load = load_avg[0]  # 1分钟平均负载
                except (AttributeError, OSError):
                    # Windows不支持getloadavg
                    pass
            except Exception as e:
                logger.error(f"收集系统资源信息失败: {str(e)}")
        
        # 收集GPU信息
        if self._torch_available:
            import torch
            try:
                gpu_properties = torch.cuda.get_device_properties(0)
                gpu_total_mem = gpu_properties.total_memory
                gpu_allocated_mem = torch.cuda.memory_allocated()
                status.gpu_memory_percent = (gpu_allocated_mem / gpu_total_mem) * 100
                status.gpu_free_gb = (gpu_total_mem - gpu_allocated_mem) / (1024 ** 3)
            except Exception as e:
                logger.error(f"收集GPU信息失败: {str(e)}")
        
        # 判断系统是否健康
        status.is_healthy = self._is_system_healthy(status)
        
        return status
    
    def _is_system_healthy(self, status: ResourceStatus) -> bool:
        """
        判断系统资源是否健康
        """
        # 任何资源接近危险阈值都认为不健康
        mem_high = status.memory_percent > self._resource_thresholds["memory_high"]
        gpu_free_ok = status.gpu_free_gb is not None and status.gpu_free_gb >= 1.0
        return not (
            status.cpu_percent > self._resource_thresholds["cpu_high"] or
            (mem_high and not gpu_free_ok) or
            (status.gpu_memory_percent and 
             status.gpu_memory_percent > self._resource_thresholds["gpu_high"]) or
            status.available_memory_gb < 0.5
        )
    
    def _update_downgrade_level(self, status: ResourceStatus):
        """
        根据当前资源状态更新降级级别
        """
        # 重置降级原因
        self._downgrade_reasons = {
            "cpu": False,
            "memory": False,
            "gpu": False,
            "disk": False,
        }
        
        # 检查各级别资源状态
        if status.cpu_percent > self._resource_thresholds["cpu_high"]:
            self._downgrade_reasons["cpu"] = True
        gpu_free_ok = status.gpu_free_gb is not None and status.gpu_free_gb >= 1.0
        if status.memory_percent > self._resource_thresholds["memory_high"] and not gpu_free_ok:
            self._downgrade_reasons["memory"] = True
        if status.gpu_memory_percent and \
           status.gpu_memory_percent > self._resource_thresholds["gpu_high"]:
            self._downgrade_reasons["gpu"] = True
        if status.disk_usage_percent > 95:
            self._downgrade_reasons["disk"] = True
        
        # 计算降级级别
        high_reasons = sum(self._downgrade_reasons.values())
        
        if high_reasons >= 2:
            self._downgrade_level = 3  # 紧急模式
        elif any(self._downgrade_reasons.values()):
            self._downgrade_level = 2  # 深度降级
        elif (status.cpu_percent > self._resource_thresholds["cpu_medium"] or
              ((status.memory_percent > self._resource_thresholds["memory_medium"]) and not gpu_free_ok) or
              (status.gpu_memory_percent and 
               status.gpu_memory_percent > self._resource_thresholds["gpu_medium"])):
            self._downgrade_level = 1  # 轻量降级
        else:
            self._downgrade_level = 0  # 正常模式
        
        # 记录降级状态变化
        if self._downgrade_level > 0:
            active_reasons = [k for k, v in self._downgrade_reasons.items() if v]
            logger.warning(
                f"[系统降级] 当前降级级别: {self._downgrade_level}, 原因: {', '.join(active_reasons)}"
            )
    
    def should_downgrade(self) -> bool:
        """
        判断是否需要进行服务降级
        """
        return self._downgrade_level > 0
    
    def get_downgrade_level(self) -> int:
        """
        获取当前降级级别
        """
        return self._downgrade_level
    
    def get_downgrade_reasons(self) -> Dict[str, bool]:
        """
        获取当前降级原因
        """
        return self._downgrade_reasons.copy()
    
    def perform_downgrade(self, level: Optional[int] = None) -> bool:
        """
        执行降级操作
        
        Args:
            level: 指定降级级别，如果为None则使用当前检测到的级别
            
        Returns:
            bool: 降级操作是否成功
        """
        target_level = level if level is not None else self._downgrade_level
        
        try:
            if target_level == 1:
                return self._lightweight_downgrade()
            elif target_level == 2:
                return self._medium_downgrade()
            elif target_level == 3:
                return self._emergency_downgrade()
            return True  # 无需降级
        except Exception as e:
            logger.error(f"执行降级操作失败: {str(e)}")
            return False
    
    def _lightweight_downgrade(self) -> bool:
        """
        轻量级降级措施
        - 限制批处理大小
        - 减少缓存使用
        - 降低生成参数
        """
        logger.info("[降级执行] 应用轻量级降级措施")
        
        # 设置环境变量作为降级标记
        os.environ["SERVICE_DOWNGRADE_LEVEL"] = "1"
        os.environ["MAX_GENERATION_TOKENS"] = "1024"
        
        # 尝试清理内存
        self.cleanup_resources()
        
        return True
    
    def _medium_downgrade(self) -> bool:
        """
        中度降级措施
        - 强制使用更激进的量化
        - 减少并发请求数
        - 优先使用轻量级响应
        """
        logger.warning("[降级执行] 应用中度降级措施")
        
        # 设置环境变量作为降级标记
        os.environ["SERVICE_DOWNGRADE_LEVEL"] = "2"
        os.environ["MAX_GENERATION_TOKENS"] = "512"
        os.environ["FORCE_QUANTIZATION"] = "4"
        
        # 清理内存并减少缓存
        self.cleanup_resources(aggressive=True)
        
        return True
    
    def _heavy_downgrade(self) -> bool:
        """
        深度降级措施
        - 卸载非关键模型
        - 完全禁用批处理
        - 仅处理关键请求
        """
        logger.warning("[降级执行] 应用深度降级措施")
        
        # 设置环境变量作为降级标记
        os.environ["SERVICE_DOWNGRADE_LEVEL"] = "3"
        os.environ["MAX_GENERATION_TOKENS"] = "256"
        os.environ["DISABLE_BATCH_PROCESSING"] = "1"
        
        # 强制清理所有可能的资源
        self.cleanup_resources(aggressive=True)
        
        return True
    
    def _emergency_downgrade(self) -> bool:
        """
        紧急降级措施
        - 仅提供最小功能集
        - 完全使用轻量级响应
        - 可能暂时拒绝某些请求
        """
        logger.error("[降级执行] 应用紧急降级措施")
        
        # 设置环境变量作为降级标记
        os.environ["SERVICE_DOWNGRADE_LEVEL"] = "4"
        os.environ["EMERGENCY_MODE"] = "1"
        
        # 执行紧急资源清理
        self.cleanup_resources(emergency=True)
        
        return True
    
    def cleanup_resources(self, aggressive: bool = False, emergency: bool = False):
        """
        清理系统资源
        
        Args:
            aggressive: 是否使用激进清理策略
            emergency: 是否为紧急模式清理
        """
        try:
            # 导入必要的库
            import gc
            
            logger.info(f"[资源清理] 开始{'紧急' if emergency else '激进' if aggressive else '常规'}资源清理")
            
            # 强制垃圾回收
            gc.collect()
            logger.info("[资源清理] 垃圾回收已执行")
            
            # 如果可用，清理CUDA缓存
            if self._torch_available:
                import torch
                torch.cuda.empty_cache()
                logger.info("[资源清理] CUDA缓存已清理")
                
                if aggressive or emergency:
                    torch.cuda.ipc_collect()
                    logger.info("[资源清理] CUDA IPC资源已收集")
            
            # 清除大对象缓存（如果服务中使用了缓存）
            if emergency:
                logger.warning("[资源清理] 紧急模式：可能需要手动清除应用程序缓存")
            
            logger.info(f"[资源清理] {'紧急' if emergency else '激进' if aggressive else '常规'}资源清理完成")
            
        except Exception as e:
            logger.error(f"[资源清理] 清理资源失败: {str(e)}")
    
    def get_recommended_max_tokens(self, requested_max_tokens: int) -> int:
        """
        根据当前系统资源状态推荐最大token数
        
        Args:
            requested_max_tokens: 请求的最大token数
            
        Returns:
            int: 推荐的最大token数
        """
        # 根据降级级别调整max_tokens
        if self._downgrade_level == 1:
            # 轻量降级，减少30%
            return max(64, int(requested_max_tokens * 0.7))
        elif self._downgrade_level == 2:
            # 中度降级，减少50%
            return max(64, int(requested_max_tokens * 0.5))
        elif self._downgrade_level >= 3:
            # 深度/紧急降级，减少80%
            return max(32, int(requested_max_tokens * 0.2))
        
        # 正常模式，可能仍然根据资源状态进行微调
        status = self.get_status()
        
        # 根据内存使用情况微调
        if status.memory_percent > 80:
            return max(128, int(requested_max_tokens * 0.8))
        elif status.memory_percent > 70:
            return max(128, int(requested_max_tokens * 0.9))
        
        # 默认返回请求的数量
        return requested_max_tokens

# 创建全局资源监控器实例
resource_monitor = ResourceMonitor()

def get_resource_monitor() -> ResourceMonitor:
    """
    获取全局资源监控器实例
    """
    global resource_monitor
    return resource_monitor
