import asyncio
import logging
from typing import Any, Callable, Optional
import concurrent.futures
import torch

from core.services.scheduler.task_scheduler import get_global_scheduler, TaskType, TaskStatus
from core.utils.logger import get_logger
import time

logger = get_logger("AsyncScheduler")

class AsyncScheduler:
    """
    [Deprecated] 异步调度器
    
    这是一个兼容性包装器，底层使用 core.task_scheduler.GlobalTaskScheduler。
    建议直接使用 core.task_scheduler.get_global_scheduler()。
    """

    def __init__(self):
        self._scheduler = get_global_scheduler()
        logger.warning("AsyncScheduler is deprecated, please use core.task_scheduler.GlobalTaskScheduler instead")
        self._timeout = 60.0

    @property
    def loop(self):
        return asyncio.get_running_loop()

    async def run_cpu(self, fn: Callable, *args, **kwargs) -> Any:
        """
        在CPU线程池中执行任务
        """
        logger.debug(f"AsyncScheduler.run_cpu: {fn.__name__ if hasattr(fn, '__name__') else str(fn)}")
        task_id = await self._scheduler.schedule_cpu_task(fn, *args, **kwargs)
        
        # 等待任务完成
        future = await self._scheduler.get_task_future(task_id)
        if future:
            try:
                return await asyncio.wait_for(future, timeout=self._timeout)
            except asyncio.TimeoutError:
                await self._scheduler.cancel_task(task_id)
                raise TimeoutError(f"CPU task {task_id} timed out")
        else:
            # 如果获取不到future，轮询状态
            start_time = time.time()
            while time.time() - start_time < self._timeout:
                status = await self._scheduler.get_task_status(task_id)
                if not status:
                    raise Exception(f"Task {task_id} not found")
                
                if status.status == TaskStatus.COMPLETED:
                    return status.result
                elif status.status == TaskStatus.FAILED:
                    raise Exception(status.error)
                elif status.status == TaskStatus.CANCELLED:
                    raise asyncio.CancelledError()
                
                await asyncio.sleep(0.1)
            
            await self._scheduler.cancel_task(task_id)
            raise TimeoutError(f"CPU task {task_id} timed out")

    async def run_gpu(self, fn: Callable, *args, **kwargs) -> Any:
        """
        在GPU锁保护下执行任务
        """
        logger.debug(f"AsyncScheduler.run_gpu: {fn.__name__ if hasattr(fn, '__name__') else str(fn)}")
        task_id = await self._scheduler.schedule_gpu_task(fn, *args, **kwargs)
        
        # 等待任务完成
        future = await self._scheduler.get_task_future(task_id)
        if future:
            try:
                return await asyncio.wait_for(future, timeout=self._timeout)
            except asyncio.TimeoutError:
                await self._scheduler.cancel_task(task_id)
                raise TimeoutError(f"GPU task {task_id} timed out")
        else:
            start_time = time.time()
            while time.time() - start_time < self._timeout:
                status = await self._scheduler.get_task_status(task_id)
                if not status:
                    raise Exception(f"Task {task_id} not found")
                
                if status.status == TaskStatus.COMPLETED:
                    return status.result
                elif status.status == TaskStatus.FAILED:
                    raise Exception(status.error)
                elif status.status == TaskStatus.CANCELLED:
                    raise asyncio.CancelledError()
                
                await asyncio.sleep(0.1)
            
            await self._scheduler.cancel_task(task_id)
            raise TimeoutError(f"GPU task {task_id} timed out")

    async def submit_task(self, fn: Callable, *args, priority=None, **kwargs) -> Any:
        """
        提交任务
        """
        # 默认行为：如果是协程则直接执行，否则作为CPU任务执行
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        else:
            return await self.run_cpu(fn, *args, **kwargs)

    async def wait_for_all_tasks(self):
        """
        等待所有任务完成 (不完全支持，仅作兼容)
        """
        logger.warning("wait_for_all_tasks is not fully supported in the wrapper")
        pass
        
    async def get_resource_stats(self) -> dict:
        """
        获取资源统计信息
        """
        # 这里只能返回一些基础信息，无法完全模拟旧的行为
        return {
            "cpu": {
                "active_workers": 0, # 难以获取准确值
                "max_workers": 4,
            },
            "gpu": {
                "available": torch.cuda.is_available() if 'torch' in globals() else False
            }
        }

# 创建全局实例
global_async_scheduler = AsyncScheduler()

def get_global_scheduler() -> AsyncScheduler:
    """
    获取全局异步调度器实例
    注意：这返回的是AsyncScheduler包装器，不是GlobalTaskScheduler
    """
    return global_async_scheduler

def get_global_async_scheduler() -> AsyncScheduler:
    return global_async_scheduler

# 简单的并行任务执行示例
async def run_parallel_tasks(cpu_func, gpu_func):
    """
    并行执行CPU和GPU任务
    """
    cpu_task = get_global_async_scheduler().run_cpu(cpu_func)
    gpu_task = get_global_async_scheduler().run_gpu(gpu_func)
    return await asyncio.gather(cpu_task, gpu_task)
