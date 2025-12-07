#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CPU密集型任务处理器 (已弃用)
现在作为 GlobalTaskScheduler 的包装器存在
"""
import asyncio
from typing import Any, Callable, Dict, Optional, TypeVar
from functools import wraps
from contextlib import asynccontextmanager

from core.services.scheduler.task_scheduler import get_global_scheduler, TaskType, TaskStatus
from core.utils.logger import get_logger

logger = get_logger("CPU_PROCESSOR")

T = TypeVar('T')

class CPUTaskProcessor:
    """
    [Deprecated] CPU密集型任务处理器
    建议直接使用 core.task_scheduler.GlobalTaskScheduler
    """
    
    def __init__(self, pool_size: int = 4, max_queue_size: int = 1000, task_timeout: int = 300):
        self._scheduler = get_global_scheduler()
        self._timeout = task_timeout
        logger.warning("CPUTaskProcessor is deprecated, please use GlobalTaskScheduler instead")
        
    async def initialize(self):
        """
        初始化处理器
        """
        # 确保调度器已启动
        await self._scheduler.start()
        logger.info("CPU任务处理器(包装器)初始化完成")
    
    async def shutdown(self):
        """
        关闭处理器
        """
        # 不关闭全局调度器，因为它可能被其他组件使用
        # 让 lifecycle_manager 在适当的时候关闭调度器
        pass
    
    async def submit_task(self, 
                          func: Callable[..., T], 
                          *args, 
                          **kwargs) -> T:
        """
        提交CPU密集型任务
        """
        task_id = await self._scheduler.schedule_cpu_task(func, *args, **kwargs)
        
        # 等待结果
        future = await self._scheduler.get_task_future(task_id)
        if future:
            try:
                return await asyncio.wait_for(future, timeout=self._timeout)
            except asyncio.TimeoutError:
                await self._scheduler.cancel_task(task_id)
                raise TimeoutError(f"CPU任务 {task_id} 超时")
        else:
             # 如果future不存在，可能是任务已经完成（极快）或者出错了
             # 尝试获取任务状态
             status = await self._scheduler.get_task_status(task_id)
             if status:
                if status.status == TaskStatus.COMPLETED:
                    return status.result
                elif status.status == TaskStatus.FAILED:
                    raise Exception(status.error)
                elif status.status == TaskStatus.CANCELLED:
                    raise asyncio.CancelledError()
             
             # 如果仍然无法获取状态，或者状态不是终态，回退到轮询
             start_time = asyncio.get_running_loop().time()
             while True:
                if asyncio.get_running_loop().time() - start_time > self._timeout:
                    await self._scheduler.cancel_task(task_id)
                    raise TimeoutError(f"CPU任务 {task_id} 超时 (polling)")

                status = await self._scheduler.get_task_status(task_id)
                if not status:
                    # 任务可能已被清理
                    raise Exception(f"Task {task_id} not found")
                
                if status.status == TaskStatus.COMPLETED:
                    return status.result
                elif status.status == TaskStatus.FAILED:
                    raise Exception(status.error)
                elif status.status == TaskStatus.CANCELLED:
                    raise asyncio.CancelledError()
                
                await asyncio.sleep(0.1)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取处理器统计信息 (Dummy)
        """
        return {
            "status": "running (wrapper)",
            "scheduler_stats": "See GlobalTaskScheduler"
        }
    
    def is_healthy(self) -> bool:
        return True


# 全局CPU任务处理器实例
_cpu_processor: Optional[CPUTaskProcessor] = None

def get_cpu_processor() -> CPUTaskProcessor:
    """
    获取全局CPU任务处理器实例
    """
    global _cpu_processor
    if _cpu_processor is None:
        _cpu_processor = CPUTaskProcessor()
    return _cpu_processor

async def initialize_cpu_processor():
    """
    初始化全局CPU任务处理器
    """
    processor = get_cpu_processor()
    await processor.initialize()

async def shutdown_cpu_processor():
    """
    关闭全局CPU任务处理器
    """
    global _cpu_processor
    if _cpu_processor:
        await _cpu_processor.shutdown()
        _cpu_processor = None

# 任务装饰器
def cpu_task(func: Callable[..., T]) -> Callable[..., asyncio.Future[T]]:
    """
    CPU密集型任务装饰器
    """
    @wraps(func)
    async def wrapper(*args, **kwargs) -> T:
        processor = get_cpu_processor()
        return await processor.submit_task(func, *args, **kwargs)
    
    # 标记为CPU任务
    wrapper.__is_cpu_task__ = True
    return wrapper

@asynccontextmanager
async def cpu_task_context():
    """
    CPU任务上下文管理器
    """
    try:
        await initialize_cpu_processor()
        yield get_cpu_processor()
    finally:
        await shutdown_cpu_processor()
