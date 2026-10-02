#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务调度器适配器
适配现有的GlobalTaskScheduler到新的异步接口
"""


from core.utils.logger import get_logger
import asyncio
from typing import Optional, Dict, Any, Callable, Awaitable, TypeVar
from functools import wraps
from core.services.scheduler.client.cpp_client import CPPSchedulerClient
from core.core_engine.config_manager import ConfigManager
from core.contracts import ModuleInitState

# 先定义logger
logger = get_logger(__name__)

# 移到模块级别的导入
try:
    from .task_scheduler import TaskPriority, TaskType
except ImportError:
    logger.warning("未能导入TaskPriority/TaskType，将使用默认值")

    class TaskPriority:
        LOW = 0
        MEDIUM = 1
        HIGH = 2

    class TaskType:
        DEFAULT = "default"
        CPU_BOUND = "cpu"
        GPU_BOUND = "gpu"


T = TypeVar("T")


class TaskSchedulerAdapter:
    """
    任务调度器适配器
    封装现有的GlobalTaskScheduler以提供统一的接口
    支持无缝切换到 C++ 资源隔离调度器 (cpp_scheduler)
    """

    def __init__(self):
        self._scheduler = None
        self._cpp_client: Optional[CPPSchedulerClient] = None
        self._initialized = False
        self._use_cpp_scheduler = False
        self._base_worker_count = 4
        self._max_worker_count = 8
        self._monitor_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """
        初始化适配器，连接到现有的GlobalTaskScheduler或C++调度器
        """
        if not self._initialized:
            try:
                # 读取配置
                config_manager = ConfigManager()
                self._use_cpp_scheduler = config_manager.get(
                    "scheduler.cpp_http.enabled", False
                )
                cpp_host = config_manager.get("scheduler.cpp_http.host", "127.0.0.1")
                cpp_port = config_manager.get("scheduler.cpp_http.port", 8080)

                if self._use_cpp_scheduler:
                    logger.info(
                        f"正在连接 C++ 资源隔离调度器 ({cpp_host}:{cpp_port})..."
                    )
                    self._cpp_client = CPPSchedulerClient(host=cpp_host, port=cpp_port)
                    connected = await self._cpp_client.connect()
                    if connected:
                        logger.info("C++ 调度器连接成功")
                    else:
                        logger.error("C++ 调度器连接失败，将降级到本地调度器")
                        self._use_cpp_scheduler = False

                # 无论是否使用 C++，都初始化本地调度器作为后备或非AI任务处理
                # 导入现有的GlobalTaskScheduler（如果需要）
                from .task_scheduler import get_global_scheduler

                # 获取全局调度器实例（单例）
                self._scheduler = get_global_scheduler()

                # 启动调度器
                self._base_worker_count = int(
                    config_manager.get("scheduler.worker_count", 4)
                )
                self._max_worker_count = self._base_worker_count * 2

                logger.info(
                    f"TaskSchedulerAdapter: Initializing with {self._base_worker_count} base workers"
                )
                await self._scheduler.start(worker_count=self._base_worker_count)

                # 启动动态负载监控循环
                self._monitor_task = asyncio.create_task(self._dynamic_worker_monitor())

                self._initialized = True
                logger.info("任务调度器适配器初始化完成")

            except Exception as e:
                logger.error(f"初始化任务调度器适配器失败: {str(e)}", exc_info=True)
                raise

    async def _dynamic_worker_monitor(self):
        """动态工作协程监控循环"""
        while True:
            try:
                await asyncio.sleep(5)  # 每 5 秒检查一次

                if not self._scheduler:
                    continue

                queue_size = (
                    self._scheduler._task_queue.qsize()
                    if hasattr(self._scheduler, "_task_queue")
                    else 0
                )
                current_workers = (
                    len(self._scheduler._workers)
                    if hasattr(self._scheduler, "_workers")
                    else 0
                )

                # 扩容逻辑：队列积压且未达上限
                if queue_size > 5 and current_workers < self._max_worker_count:
                    new_worker_id = f"dynamic-worker-{current_workers}"
                    logger.info(
                        f"TaskSchedulerAdapter: Queue backlog ({queue_size}), spawning {new_worker_id}"
                    )
                    # 注意：需要确保 _scheduler 暴露了增加 worker 的内部接口
                    if hasattr(self._scheduler, "_spawn_worker"):
                        self._scheduler._spawn_worker(new_worker_id)

            except Exception as e:
                logger.error(f"Dynamic worker monitor error: {e}")

    async def schedule_llm_task(
        self, prompt: str, model: str = "default", **kwargs
    ) -> Dict[str, Any]:
        """
        提交 LLM 推理任务
        优先使用 C++ 调度器，否则需要调用方处理本地逻辑
        """
        if not self._initialized:
            await self.initialize()

        if self._use_cpp_scheduler and self._cpp_client:
            return await self._cpp_client.submit_llm_task(prompt, model, **kwargs)

        # 如果不使用 C++ 调度器，返回 None，由调用方（如 LLMModule）决定如何处理（通常是本地执行）
        return None

    async def schedule_tts_task(
        self, text: str, voice_id: str, **kwargs
    ) -> Dict[str, Any]:
        """
        提交 TTS 合成任务
        """
        if not self._initialized:
            await self.initialize()

        if self._use_cpp_scheduler and self._cpp_client:
            return await self._cpp_client.submit_tts_task(text, voice_id, **kwargs)

        return None

    async def schedule_image_task(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        提交图像生成任务
        """
        if not self._initialized:
            await self.initialize()

        if self._use_cpp_scheduler and self._cpp_client:
            return await self._cpp_client.submit_image_task(prompt, **kwargs)

        return None

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
                kwargs=kwargs,
            )
            fut = await self._scheduler.get_task_future(task_id)
            try:
                return await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                await self._scheduler.cancel_task(task_id)
                raise asyncio.TimeoutError(f"任务执行超时: {timeout}秒")

        return await execute_task()

    async def run_gpu_task(self, func: Callable[..., T], *args, **kwargs) -> T:
        if not self._initialized:
            await self.initialize()

        timeout = kwargs.pop("timeout", 300.0)

        async def execute_task():
            task_id = await self._scheduler.schedule_task(
                func=func,
                name=func.__name__,
                priority=TaskPriority.HIGH,
                task_type=TaskType.GPU_BOUND,
                args=args,
                kwargs=kwargs,
            )
            fut = await self._scheduler.get_task_future(task_id)
            try:
                return await asyncio.wait_for(fut, timeout=timeout)
            except asyncio.TimeoutError:
                await self._scheduler.cancel_task(task_id)
                raise asyncio.TimeoutError(f"任务执行超时: {timeout}秒")

        return await execute_task()

    def run_async_task(
        self, func: Callable[..., Awaitable[T]], *args, **kwargs
    ) -> asyncio.Task[T]:
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
                    return await asyncio.wait_for(
                        func(*args, **kwargs), timeout=timeout
                    )
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
                    kwargs=kwargs,
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
                if hasattr(self._scheduler, "get_stats"):
                    return self._scheduler.get_stats()
                else:
                    # 返回基本信息
                    return {
                        "status": "running",
                        "init_state": ModuleInitState.INITIALIZED.value,
                        "adapter": "TaskSchedulerAdapter",
                    }
            except Exception as e:
                logger.error(f"获取任务统计信息失败: {str(e)}")

        return {
            "status": ModuleInitState.NOT_INITIALIZED.value,
            "init_state": ModuleInitState.NOT_INITIALIZED.value,
        }

    async def shutdown(self):
        """
        关闭适配器
        """
        if self._initialized and self._scheduler:
            try:
                # 停止动态监控
                if self._monitor_task:
                    self._monitor_task.cancel()

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
                    logger.info("任务调度器初始化成功")
                    return _adapter
                except Exception as e:
                    last_error = e
                    retry_count += 1
                    wait_time = 0.5 * (2 ** (retry_count - 1))  # 指数退避
                    logger.error(
                        f"任务调度器初始化失败 (尝试 {retry_count}/{max_retries}): {str(e)}"
                    )

                    if retry_count < max_retries:
                        logger.info(f"{wait_time}秒后重试...")
                        await asyncio.sleep(wait_time)

            # 所有重试都失败
            logger.critical(
                f"任务调度器初始化失败，已达到最大重试次数: {str(last_error)}"
            )
            raise Exception(f"任务调度器初始化失败: {str(last_error)}")

        # 检查现有实例是否正常
        try:
            stats = _adapter.get_stats()
            st = str(stats.get("init_state") or stats.get("status") or "")
            if st != ModuleInitState.NOT_INITIALIZED.value:
                return _adapter
        except Exception as e:
            logger.warning(f"现有任务调度器状态检查失败: {str(e)}，重新初始化...")

        # 如果现有实例不正常，重新初始化
        try:
            await _adapter.shutdown()
        except Exception:
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


def gpu_task(timeout: Optional[float] = None):
    def decorator(func: Callable[..., T]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            scheduler = get_task_scheduler()
            if not scheduler:
                return await asyncio.to_thread(func, *args, **kwargs)

            if timeout is not None:
                kwargs["timeout"] = timeout

            return await scheduler.run_gpu_task(func, *args, **kwargs)

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
