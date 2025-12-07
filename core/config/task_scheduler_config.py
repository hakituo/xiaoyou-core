from typing import Dict, Any
import os
from dataclasses import dataclass


@dataclass
class TaskSchedulerConfig:
    """
    任务调度器配置类
    定义全局任务调度器的相关配置参数
    """
    # 工作协程数量
    worker_count: int = 3
    
    # 任务清理间隔（秒）
    cleanup_interval: int = 300
    
    # 完成任务最大保留时间（秒）
    completed_task_ttl: int = 3600
    
    # 是否启用任务调度器
    enabled: bool = True
    
    # 任务优先级默认值映射
    default_priorities: Dict[str, int] = None
    
    def __post_init__(self):
        # 初始化默认优先级映射
        if self.default_priorities is None:
            self.default_priorities = {
                "image_processing": 2,  # 高优先级
                "model_inference": 2,   # 高优先级
                "data_processing": 1,   # 中优先级
                "cache_cleanup": 0,     # 低优先级
                "health_check": 1,      # 中优先级
                "logging": 0           # 低优先级
            }
    
    @classmethod
    def from_env(cls):
        """从环境变量创建配置"""
        # 这里可以实现从环境变量读取配置的逻辑
        return cls()

# 默认配置实例
DEFAULT_TASK_SCHEDULER_CONFIG = TaskSchedulerConfig.from_env()