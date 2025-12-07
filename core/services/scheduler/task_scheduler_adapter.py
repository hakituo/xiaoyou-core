#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务调度器适配器
适配现有的GlobalTaskScheduler到新的异步接口
"""
import logging
import asyncio
from typing import Optional, Dict, Any, Callable, Awaitable, List, TypeVar
from functools import wraps
import time

# 先定义logger
logger = logging.getLogger(__name__)

# 移到模块级别的导入
try:
    from core.services.scheduler.task_scheduler import GlobalTaskScheduler, TaskPriority
except ImportError:
    logger.warning("未能导入TaskPriority，将使用默认优先级")
    # 创建一个简单的替代枚举
    class TaskPriority:
        LOW = 0
        MEDIUM = 1
        HIGH = 2

T = TypeVar('T')


class TaskSchedulerAdapter:
    """
    任务调度器适配器
    封装现有的GlobalTaskScheduler以提供统一的接口
    """
    def __init__(self):
        self._scheduler = None
        self._initialized = False
    
    async def initialize(self):
        """
        初始化适配器，连接到现有的GlobalTaskScheduler
        """
        if not self._initialized:
            try:
                # 导入现有的GlobalTaskScheduler（如果需要）
                from core.services.scheduler.task_scheduler import get_global_scheduler
                
                # 获取全局调度器实例（单例）
                self._scheduler = get_global_scheduler()
                
                # 启动调度器
                await self._scheduler.start(worker_count=4)  # 设置4个工作协程
                
                self._initialized = True
                logger.info("任务调度器适配器初始化完成")
                
            except Exception as e:
                logger.error(f"初始化任务调度器适配器失败: {str(e)}", exc_info=True)
                raise
    
    async def run_cpu_task(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        运行CPU密集型任务
        适配到现有调度器的同步任务执行
        """
        if not self._initialized:
            await self.initialize()
        
        timeout = kwargs.pop("timeout", 30.0)
        
        async def execute_task():
            task_id = await self._scheduler.schedule_task(
                func=func,
                name=func.__name__,
                priority=TaskPriority.HIGH,
                args=args,
                kwargs=kwargs
            )
            fut = await self._scheduler.get_task_future(task_id)
            try:
                return await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                await self._scheduler.cancel_task(task_id)
                raise asyncio.TimeoutError(f"任务执行超时: {timeout}秒")
        return await execute_task()
    
    def run_async_task(self, func: Callable[..., Awaitable[T]], *args, **kwargs) -> asyncio.Task[T]:
        """
        运行异步I/O任务
        适配到现有调度器的异步任务执行
        增强版：添加超时处理、更健壮的错误捕获和任务取消机制
        """
        # 获取超时设置，优先从参数获取，默认从配置文件读取，再默认120秒
        timeout = kwargs.pop("timeout", None)
        if timeout is None:
            try:
                from core.core_engine.config_manager import ConfigManager
                config_manager = ConfigManager()
                # 增加默认超时时间到300秒，防止长对话或TTS生成时被杀
                timeout = config_manager.get("limits.message_timeout", 300.0)
            except Exception:
                timeout = 300.0  # 默认使用300秒
        
        if not self._initialized:
            # 如果未初始化，创建带超时的任务
            async def wrapped_func():
                try:
                    # 使用超时执行原始函数
                    return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
                except asyncio.TimeoutError:
                    raise asyncio.TimeoutError(f"任务执行超时: {timeout}秒")
                except Exception as e:
                    logger.error(f"任务执行失败: {str(e)}")
                    raise
            
            return asyncio.create_task(wrapped_func())
        
        # 创建一个包装函数来跟踪任务完成
        async def task_wrapper():
            task_id = None
            try:
                task_id = await self._scheduler.schedule_task(
                    func=func,
                    name=func.__name__,
                    priority=TaskPriority.MEDIUM,
                    args=args,
                    kwargs=kwargs
                )
                # self._current_task_id = task_id  # Removed unsafe state
                fut = await self._scheduler.get_task_future(task_id)
                return await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                if task_id:
                    try:
                        await self._scheduler.cancel_task(task_id)
                    except Exception as e:
                        logger.error(f"取消超时任务时出错: {str(e)}")
                raise asyncio.TimeoutError(f"任务执行超时: {timeout}秒")
            except asyncio.CancelledError:
                if task_id:
                    try:
                        await self._scheduler.cancel_task(task_id)
                    except Exception as e:
                        logger.error(f"取消任务时出错: {str(e)}")
                raise
            except Exception as e:
                logger.error(f"任务执行过程中发生错误: {str(e)}", exc_info=True)
                raise
        
        # 创建并返回任务
        return asyncio.create_task(task_wrapper())
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取任务调度器统计信息
        """
        if self._initialized and self._scheduler:
            # 尝试获取现有调度器的统计信息
            try:
                # 这里需要根据现有调度器的实际方法来获取统计
                # 假设现有调度器有get_stats方法
                if hasattr(self._scheduler, 'get_stats'):
                    return self._scheduler.get_stats()
                else:
                    # 返回基本信息
                    return {
                        "status": "running",
                        "adapter": "TaskSchedulerAdapter"
                    }
            except Exception as e:
                logger.error(f"获取任务统计信息失败: {str(e)}")
        
        return {
            "status": "not_initialized"
        }
    
    async def shutdown(self):
        """
        关闭适配器
        """
        if self._initialized and self._scheduler:
            try:
                # 停止现有调度器
                await self._scheduler.stop()
                self._initialized = False
                logger.info("任务调度器适配器已关闭")
            except Exception as e:
                logger.error(f"关闭任务调度器适配器时出错: {str(e)}")


# 全局适配器实例
_adapter: Optional[TaskSchedulerAdapter] = None
_adapter_lock = asyncio.Lock()  # 添加锁以确保线程安全


async def initialize_scheduler() -> TaskSchedulerAdapter:
    """
    初始化任务调度器
    增强版：添加锁以确保线程安全，支持重试初始化
    """
    global _adapter
    async with _adapter_lock:
        if _adapter is None:
            max_retries = 3
            retry_count = 0
            last_error = None
            
            while retry_count < max_retries:
                try:
                    _adapter = TaskSchedulerAdapter()
                    await _adapter.initialize()
                    logger.info(f"任务调度器初始化成功")
                    return _adapter
                except Exception as e:
                    last_error = e
                    retry_count += 1
                    wait_time = 0.5 * (2 ** (retry_count - 1))  # 指数退避
                    logger.error(f"任务调度器初始化失败 (尝试 {retry_count}/{max_retries}): {str(e)}")
                    
                    if retry_count < max_retries:
                        logger.info(f"{wait_time}秒后重试...")
                        await asyncio.sleep(wait_time)
            
            # 所有重试都失败
            logger.critical(f"任务调度器初始化失败，已达到最大重试次数: {str(last_error)}")
            raise Exception(f"任务调度器初始化失败: {str(last_error)}")
        
        # 检查现有实例是否正常
        try:
            stats = _adapter.get_stats()
            if stats.get("status") != "not_initialized":
                return _adapter
        except Exception as e:
            logger.warning(f"现有任务调度器状态检查失败: {str(e)}，重新初始化...")
            
        # 如果现有实例不正常，重新初始化
        try:
            await _adapter.shutdown()
        except:
            pass  # 忽略关闭时的错误
        
        _adapter = TaskSchedulerAdapter()
        await _adapter.initialize()
        return _adapter


def get_task_scheduler() -> Optional[TaskSchedulerAdapter]:
    """
    获取任务调度器实例
    """
    return _adapter


async def shutdown_scheduler():
    """
    关闭任务调度器
    增强版：添加错误处理和资源清理
    """
    global _adapter
    async with _adapter_lock:
        if _adapter:
            try:
                await _adapter.shutdown()
                logger.info("任务调度器已成功关闭")
            except Exception as e:
                logger.error(f"关闭任务调度器时出错: {str(e)}")
            finally:
                _adapter = None  # 确保无论如何都重置_adapter


# CPU任务装饰器
def cpu_task(timeout: Optional[float] = None):
    """
    装饰器，将同步函数标记为CPU密集型任务
    """
    def decorator(func: Callable[..., T]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            scheduler = get_task_scheduler()
            if not scheduler:
                # 如果调度器未初始化，使用asyncio.to_thread
                return await asyncio.to_thread(func, *args, **kwargs)
            
            if timeout is not None:
                kwargs["timeout"] = timeout
            
            return await scheduler.run_cpu_task(func, *args, **kwargs)
        return wrapper
    return decorator


# I/O任务装饰器
def io_task(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """
    装饰器，将异步函数标记为I/O密集型任务
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        scheduler = get_task_scheduler()
        if not scheduler:
            # 如果调度器未初始化，直接执行
            return await func(*args, **kwargs)
        
        # 运行任务并等待结果
        task = scheduler.run_async_task(func, *args, **kwargs)
        return await task
    return wrapper