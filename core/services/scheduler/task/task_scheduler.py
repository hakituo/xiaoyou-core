from core.utils.logger import get_logger
import asyncio

import threading
import time
from enum import Enum
from typing import Dict, List, Optional, Callable, Any, Union
import uuid
from dataclasses import dataclass, field
import concurrent.futures
import contextvars
from config.integrated_config import get_settings
from core.utils.config_accessor import get_config
from core.utils.resource_lock import get_resource_lock
from core.utils.async_locks import LazyAsyncLock
from core.contracts import TaskStatus

# 获取日志记录器
logger = get_logger(__name__)


def _get_cpp_engine():
    """延迟导入 cpp_scheduler_engine，避免启动时加载 7~8 秒的依赖链"""
    from ..cpp_scheduler_engine import get_scheduler_engine
    return get_scheduler_engine(auto_start=False)

# 任务上下文
_current_task_id_ctx = contextvars.ContextVar("current_task_id", default=None)


def get_current_task_id() -> Optional[str]:
    """获取当前正在执行的任务ID"""
    return _current_task_id_ctx.get()


class TaskPriority(Enum):
    """任务优先级枚举"""

    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


class TaskType(Enum):
    """任务类型枚举"""

    DEFAULT = "default"  # 默认（IO密集型或普通异步任务）
    CPU_BOUND = "cpu"  # CPU密集型（使用线程池）
    GPU_BOUND = "gpu"  # GPU密集型（使用GPU锁）


@dataclass(order=True)
class TaskInfo:
    """任务信息数据类"""

    task_id: str
    name: str
    priority: TaskPriority = field(compare=False)
    created_at: float = field(compare=False)
    status: TaskStatus = field(compare=False)
    task_type: TaskType = field(default=TaskType.DEFAULT, compare=False)
    result: Optional[Any] = field(default=None, compare=False)
    error: Optional[str] = field(default=None, compare=False)
    start_time: Optional[float] = field(default=None, compare=False)
    end_time: Optional[float] = field(default=None, compare=False)
    cancel_requested: bool = field(default=False, compare=False)


class GlobalTaskScheduler:
    """
    统一全局任务调度器
    管理所有后台任务，提供任务提交、取消、查询等功能
    整合了CPU和GPU任务调度能力
    """

    def __init__(self):
        self._tasks: Dict[str, Dict] = {}
        self._task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._worker_count: int = 3
        self._workers: List[asyncio.Task] = []
        self._running: bool = False
        self._lock: LazyAsyncLock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._background_tasks: set = set()
        self._next_task_id = 0
        self._next_task_id_lock = threading.Lock()
        self._task_futures: Dict[str, asyncio.Future] = {}

        # 资源管理
        self._cpu_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

    @staticmethod
    def _resolve_gpu_layers(settings: Any, backend: str) -> int:
        auto_layers = getattr(settings.model, "n_gpu_layers", -1)
        try:
            auto_layers = int(auto_layers)
        except Exception:
            auto_layers = -1

        if auto_layers < 0 and backend == "python":
            try:
                import torch
                if not torch.cuda.is_available():
                    auto_layers = 0
            except Exception:
                auto_layers = 0

        if auto_layers == 0 and backend == "python":
            try:
                import torch
                if torch.cuda.is_available():
                    auto_layers = -1
            except Exception:
                pass

        return auto_layers

    @staticmethod
    def _resolve_batch_size(settings: Any, auto_layers: int, backend: str) -> int:
        max_batch_size = 512
        try:
            ctx_val = int(settings.model.n_ctx or 4096)
            safe_slot_batch = ctx_val // 10

            cfg_batch = getattr(settings.model, "n_batch", None)
            try:
                cfg_batch = int(cfg_batch)
            except Exception:
                cfg_batch = 0

            if cfg_batch and cfg_batch > 0:
                max_batch_size = min(cfg_batch, safe_slot_batch)
            elif auto_layers != 0:
                max_batch_size = int(min(safe_slot_batch, 2048, max(512, ctx_val)))
            else:
                max_batch_size = int(min(safe_slot_batch, 512, max(128, ctx_val)))

            max_batch_size = max(32, max_batch_size)
        except Exception:
            max_batch_size = 128

        try:
            ctx_val = int(settings.model.n_ctx or 4096)
        except Exception:
            ctx_val = 4096

        max_batch_size = int(min(max_batch_size, ctx_val))

        if backend == "python":
            cap = 256 if auto_layers == 0 else 512
            max_batch_size = int(min(max_batch_size, cap))

        return max_batch_size

    @staticmethod
    def _resolve_draft_config(settings: Any) -> tuple:
        draft_model_path = getattr(
            settings.model_adapter.text_model, "draft_model_path", None
        )
        draft_gpu_device_id = getattr(
            settings.model_adapter.text_model, "draft_gpu_device_id", -1
        )
        try:
            draft_gpu_device_id = int(draft_gpu_device_id)
        except Exception:
            draft_gpu_device_id = -1

        if draft_gpu_device_id < 0 or not draft_model_path or draft_model_path == "":
            draft_model_path = None
            draft_gpu_device_id = -1

        return draft_model_path, draft_gpu_device_id

    def _build_llm_gpu_config(
        self, settings: Any, llm_model_path: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        try:
            resolved_llm_path = llm_model_path or settings.model.text_path
            if not (
                getattr(settings, "scheduler", None)
                and settings.scheduler.use_cpp_for_llm
                and resolved_llm_path
                and str(resolved_llm_path).lower().endswith(".gguf")
            ):
                return None

            backend = "cpp"
            auto_layers = self._resolve_gpu_layers(settings, backend)
            max_batch_size = self._resolve_batch_size(settings, auto_layers, backend)

            enable_flash_attn = bool(getattr(settings.model, "flash_attn", False))
            if auto_layers == 0:
                enable_flash_attn = False

            draft_model_path, draft_gpu_device_id = self._resolve_draft_config(settings)

            return {
                "backend": backend,
                "model_path": resolved_llm_path,
                "model_type": "llama",
                "gpu_device_id": 0,
                "n_gpu_layers": auto_layers,
                "max_context_size": settings.model.n_ctx or 4096,
                "max_batch_size": max_batch_size,
                "n_ubatch": max_batch_size,
                "flash_attn": bool(enable_flash_attn),
                "offload_kqv": bool(getattr(settings.model, "offload_kqv", False))
                and auto_layers != 0,
                "temperature": settings.model.temperature or 0.7,
                "top_p": settings.model.top_p or 0.95,
                "top_k": settings.model.top_k or 40,
                "repetition_penalty": settings.model.repetition_penalty or 1.1,
                "draft_model_path": draft_model_path or "",
                "draft_gpu_device_id": draft_gpu_device_id,
            }
        except Exception:
            return None

    async def _ensure_cpp_llm_ready(self, llm_model_path: Optional[str]) -> None:
        _cpp = _get_cpp_engine()
        if not _cpp.enabled:
            return

        if not _cpp.scheduler:
            await self.start(
                worker_count=self._worker_count, llm_model_path=llm_model_path
            )
            return

        if getattr(_cpp, "_gpu_config", None):
            return

        settings = get_settings()
        if not get_config("scheduler.use_cpp", default=False, settings=settings):
            return

        gpu_config = self._build_llm_gpu_config(settings, llm_model_path)
        if not gpu_config:
            return

        await _cpp.apply_llm_config(
            gpu_config,
            worker_count=self._worker_count,
            preload_llm=False,
        )

    async def start(self, worker_count: int = 3, llm_model_path: Optional[str] = None):
        """
        启动任务调度器
        Args:
            worker_count: 工作协程数量
        """
        if self._running:
            logger.warning("调度器已经在运行中")
            return

        self._worker_count = worker_count
        self._running = True

        # 启动 C++ 调度器引擎（仅在配置了 use_cpp 时）
        _cpp = _get_cpp_engine()
        if _cpp and _cpp.enabled:
            try:
                from config.integrated_config import get_settings
                from core.utils.config_accessor import get_config as _get_config
                settings = get_settings()
                if _get_config("scheduler.use_cpp", default=False, settings=settings):
                    gpu_config = self._build_llm_gpu_config(settings, llm_model_path)
                    await asyncio.to_thread(
                        _cpp.start,
                        worker_count=worker_count,
                        gpu_config=gpu_config,
                    )
            except Exception as e:
                logger.warning(f"cpp_scheduler 启动跳过: {e}")

        # 启动工作协程
        for i in range(self._worker_count):
            worker = asyncio.create_task(self._worker_coroutine(f"worker-{i}"))
            self._workers.append(worker)
            self._background_tasks.add(worker)
            worker.add_done_callback(self._background_tasks.discard)

        logger.info(f"全局任务调度器已启动，工作协程数量: {worker_count}")

    async def stop(self, timeout: Optional[float] = None):
        """
        停止任务调度器
        Args:
            timeout: 等待超时时间
        """
        if not self._running:
            logger.warning("调度器未在运行")
            return

        self._running = False

        # 取消所有工作协程
        for worker in self._workers:
            worker.cancel()

        # 等待工作协程结束
        try:
            await asyncio.gather(*self._workers, return_exceptions=True)
        except asyncio.CancelledError:
            pass

        # 清除任务列表
        self._workers.clear()
        async with self._lock:
            self._task_futures.clear()

        # 关闭线程池
        self._cpu_executor.shutdown(wait=False)

        # 停止 C++ 调度器
        _cpp = _get_cpp_engine()
        if _cpp.enabled:
            await _cpp.stop()

        logger.info("全局任务调度器已停止")

    async def _execute_task(self, task_func, task_type, *args, **kwargs):
        """
        执行任务的具体逻辑
        Args:
            task_func: 任务函数
            task_type: 任务类型
            args: 位置参数
            kwargs: 关键字参数
        Returns:
            任务执行结果
        """
        import inspect

        if task_type == TaskType.GPU_BOUND:
            async with get_resource_lock().acquire(
                "TaskScheduler_GPU", reject_if_full=True
            ):
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(
                    None, lambda: task_func(*args, **kwargs)
                )
        elif task_type == TaskType.CPU_BOUND:
            # CPU任务：使用线程池
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                self._cpu_executor, lambda: task_func(*args, **kwargs)
            )
        else:
            # 默认任务
            if asyncio.iscoroutinefunction(task_func) or inspect.iscoroutinefunction(
                task_func
            ):
                return await task_func(*args, **kwargs)
            else:
                # 如果不是协程函数，在线程中运行
                result = await asyncio.to_thread(task_func, *args, **kwargs)

                # 如果结果是协程（说明func是一个返回协程的普通函数，或者判断失败），需要await
                if inspect.isawaitable(result):
                    return await result

                return result

    def _spawn_worker(self, worker_name: str):
        """动态增加一个工作协程"""
        if not self._running:
            return
        worker = asyncio.create_task(self._worker_coroutine(worker_name))
        self._workers.append(worker)
        self._background_tasks.add(worker)
        worker.add_done_callback(self._background_tasks.discard)
        logger.info(f"动态增加工作协程: {worker_name}")

    async def _worker_coroutine(self, worker_name: str):
        """
        工作协程，负责从队列中获取任务并执行
        Args:
            worker_name: 工作协程名称
        """
        logger.debug(f"工作协程 {worker_name} 已启动")
        try:
            while self._running:
                try:
                    # 从队列获取任务，设置超时以便定期检查调度器状态
                    priority_val, task_info = await asyncio.wait_for(
                        self._task_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(
                        f"工作协程 {worker_name} 获取任务时出错: {str(e)}",
                        exc_info=True,
                    )
                    continue

                try:
                    # 检查任务是否被取消
                    if task_info.cancel_requested:
                        logger.debug(f"任务 {task_info.task_id} 已被取消，跳过执行")
                        async with self._lock:
                            task_info.status = TaskStatus.CANCELLED
                            # 确保Future被设置，防止等待者永久挂起
                            fut = self._task_futures.get(task_info.task_id)
                            if fut and not fut.done():
                                fut.set_exception(asyncio.CancelledError())
                        continue

                    # 执行任务
                    logger.debug(
                        f"工作协程 {worker_name} 开始执行任务 {task_info.task_id} ({task_info.task_type.value})"
                    )

                    # 获取任务执行所需数据
                    task_func = None
                    task_args = ()
                    task_kwargs = {}

                    async with self._lock:
                        # 再次检查任务是否存在（可能被并发清理）
                        if task_info.task_id in self._tasks:
                            task_info.status = TaskStatus.RUNNING
                            task_info.start_time = time.time()
                            task_data = self._tasks[task_info.task_id]
                            task_func = task_data.get("func")
                            task_args = task_data.get("args", ())
                            task_kwargs = task_data.get("kwargs", {})
                        else:
                            logger.warning(
                                f"任务 {task_info.task_id} 数据丢失，跳过执行"
                            )
                            continue

                    if task_func is None:
                        logger.error(f"任务 {task_info.task_id} 函数为空")
                        continue

                    # 执行任务
                    try:
                        # 设置当前任务上下文
                        token = _current_task_id_ctx.set(task_info.task_id)
                        try:
                            result = await self._execute_task(
                                task_func,
                                task_info.task_type,
                                *task_args,
                                **task_kwargs,
                            )
                        finally:
                            # 重置上下文
                            _current_task_id_ctx.reset(token)

                        # 更新任务状态为完成
                        async with self._lock:
                            task_info.status = TaskStatus.COMPLETED
                            task_info.result = result
                            task_info.end_time = time.time()

                            fut = self._task_futures.get(task_info.task_id)
                            if fut and not fut.done():
                                fut.set_result(result)

                            # 释放引用以节省内存（可选，保留info但清除执行参数）
                            if task_info.task_id in self._tasks:
                                self._tasks[task_info.task_id]["func"] = None
                                self._tasks[task_info.task_id]["args"] = None
                                self._tasks[task_info.task_id]["kwargs"] = None

                        logger.debug(f"任务 {task_info.task_id} 执行成功")

                    except Exception as e:
                        # 更新任务状态为失败
                        async with self._lock:
                            task_info.status = TaskStatus.FAILED
                            task_info.error = str(e)
                            task_info.end_time = time.time()

                            fut = self._task_futures.get(task_info.task_id)
                            if fut and not fut.done():
                                fut.set_exception(e)

                        logger.error(
                            f"任务 {task_info.task_id} 执行失败: {str(e)}",
                            exc_info=True,
                        )

                except Exception as e:
                    logger.error(
                        f"工作协程 {worker_name} 处理任务时发生未捕获异常: {str(e)}",
                        exc_info=True,
                    )
                finally:
                    # 确保任务被标记为完成，无论是否成功或被取消
                    self._task_queue.task_done()

        finally:
            logger.debug(f"工作协程 {worker_name} 已停止")

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """获取任务信息"""
        if task_id in self._tasks:
            return self._tasks[task_id]["info"]
        return None

    async def schedule_task(
        self,
        func: Callable,
        name: str = "unnamed_task",
        priority: Union[TaskPriority, int] = TaskPriority.MEDIUM,
        task_type: TaskType = TaskType.DEFAULT,
        args: tuple = (),
        kwargs: dict = None,
    ) -> str:
        """
        调度一个新任务
        Args:
            func: 要执行的函数
            name: 任务名称
            priority: 任务优先级
            task_type: 任务类型 (DEFAULT, CPU_BOUND, GPU_BOUND)
            args: 函数位置参数
            kwargs: 函数关键字参数
        Returns:
            任务ID
        """
        if not self._running:
            raise RuntimeError("调度器未启动")

        if kwargs is None:
            kwargs = {}

        # 转换优先级为枚举类型
        if isinstance(priority, int):
            priority = TaskPriority(priority)

        # 创建任务信息
        task_id = f"task_{uuid.uuid4().hex[:8]}_{self._next_task_id}"
        with self._next_task_id_lock:
            self._next_task_id += 1

        task_info = TaskInfo(
            task_id=task_id,
            name=name,
            priority=priority,
            task_type=task_type,
            created_at=time.time(),
            status=TaskStatus.PENDING,
        )

        # 存储任务信息
        async with self._lock:
            self._tasks[task_id] = {
                "info": task_info,
                "func": func,
                "args": args,
                "kwargs": kwargs,
            }
            loop = asyncio.get_running_loop()
            self._task_futures[task_id] = loop.create_future()

        # 将任务放入优先级队列
        # 使用负优先级值使得优先级高的任务排在前面
        await self._task_queue.put((-priority.value, task_info))

        logger.debug(
            f"任务已调度 - ID: {task_id}, 名称: {name}, 优先级: {priority.name}, 类型: {task_type.name}"
        )
        return task_id

    async def submit_llm_task(self, prompt: str, **kwargs):
        """
        提交 LLM 推理任务 (支持云端和本地模型路由)
        Args:
            prompt: 提示词
            **kwargs: 其他参数 (max_tokens, temperature 等)
        Yields:
            生成的 token
        """
        settings = get_settings()
        provider = str(getattr(settings.model.llm, "provider", "local") or "local").strip().lower()
        is_cloud_provider = provider not in ("local", "")

        # 将 model_hint 映射为 stream_chat 能识别的 model_path
        if "model_hint" in kwargs and "model_path" not in kwargs:
            kwargs["model_path"] = kwargs.pop("model_hint")
        elif "model_hint" in kwargs:
            kwargs.pop("model_hint")

        if is_cloud_provider:
            try:
                from core.llm import get_llm_module

                llm_module = get_llm_module()
                messages = prompt
                if isinstance(prompt, str):
                    messages = [{"role": "user", "content": prompt}]

                async for chunk in llm_module.stream_chat(messages, **kwargs):
                    if isinstance(chunk, dict):
                        # 透传错误信号（含 non_retryable 标识），让上层能识别并跳过重试
                        if chunk.get("error"):
                            yield chunk
                            continue
                        content = chunk.get("content") or chunk.get("text") or ""
                        if content:
                            yield content
                    elif isinstance(chunk, str):
                        yield chunk
                return
            except Exception as e:
                logger.error(f"云端 LLM 调用失败: {e}")
                yield f"云端服务暂时不可用: {e}"
                return

        desired_model_path = kwargs.get("model_path")
        if not isinstance(
            desired_model_path, str
        ) or not desired_model_path.lower().endswith(".gguf"):
            desired_model_path = None

        _cpp = _get_cpp_engine()
        if _cpp.enabled:
            try:
                await self._ensure_cpp_llm_ready(desired_model_path)
            except Exception as e:
                logger.warning(f"尝试自动准备 C++ 调度器失败: {e}")

        if _cpp.enabled and getattr(
            _cpp, "_gpu_config", None
        ):
            try:
                async for token in _cpp.submit_llm_task(
                    prompt, **kwargs
                ):
                    yield token
                return
            except Exception as e:
                logger.error(f"C++ 调度器 LLM 任务失败: {e}")
                yield f"系统繁忙，请稍后再试 (Scheduler Error: {e})"
                return

        logger.error(
            "C++ Scheduler not enabled or unavailable. Fallback to local python execution is disabled by architecture policy."
        )
        yield "服务未就绪 (Scheduler Unavailable)"
        return

    async def get_biological_system(self):
        """获取生物系统实例"""
        _cpp = _get_cpp_engine()
        if _cpp.enabled:
            return _cpp.get_biological_system()
        return None

    async def schedule_gpu_task(self, func: Callable, *args, **kwargs) -> str:
        """快捷调度GPU任务"""
        return await self.schedule_task(
            func,
            task_type=TaskType.GPU_BOUND,
            name=kwargs.pop("name", "gpu_task"),
            priority=kwargs.pop("priority", TaskPriority.HIGH),
            args=args,
            kwargs=kwargs,
        )

    async def schedule_cpu_task(self, func: Callable, *args, **kwargs) -> str:
        """快捷调度CPU任务"""
        return await self.schedule_task(
            func,
            task_type=TaskType.CPU_BOUND,
            name=kwargs.pop("name", "cpu_task"),
            priority=kwargs.pop("priority", TaskPriority.MEDIUM),
            args=args,
            kwargs=kwargs,
        )

    async def cancel_task(self, task_id: str) -> bool:
        """
        取消一个任务
        Args:
            task_id: 任务ID
        Returns:
            是否成功取消
        """
        async with self._lock:
            if task_id not in self._tasks:
                logger.warning(f"取消任务失败: 任务 {task_id} 不存在")
                return False
            task_info = self._tasks[task_id]["info"]
            # 如果任务已完成或失败，无法取消
            if task_info.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                logger.warning(f"取消任务失败: 任务 {task_id} 已完成或失败")
                return False
            # 如果任务正在运行，标记为请求取消
            if task_info.status == TaskStatus.RUNNING:
                logger.warning(f"任务 {task_id} 正在运行，标记为请求取消")
                task_info.cancel_requested = True
                return True
            # 如果任务处于等待状态，标记为已取消
            task_info.status = TaskStatus.CANCELLED
            task_info.cancel_requested = True
            fut = self._task_futures.get(task_id)
            if fut and not fut.done():
                fut.set_exception(asyncio.CancelledError())
            logger.info(f"任务 {task_id} 已取消")
            return True

    async def get_task_status(self, task_id: str) -> Optional[TaskInfo]:
        """
        获取任务状态
        Args:
            task_id: 任务ID
        Returns:
            任务信息，如果任务不存在返回None
        """
        async with self._lock:
            if task_id not in self._tasks:
                return None
            return self._tasks[task_id]["info"]

    async def get_task_info(self, task_id: str) -> Optional[TaskInfo]:
        """
        获取任务信息（与get_task_status功能相同，为向后兼容添加）
        Args:
            task_id: 任务ID
        Returns:
            任务信息，如果任务不存在返回None
        """
        return await self.get_task_status(task_id)

    async def get_task_future(self, task_id: str) -> Optional[asyncio.Future]:
        async with self._lock:
            return self._task_futures.get(task_id)

    async def get_all_tasks(self) -> Dict[str, TaskInfo]:
        """
        获取所有任务的信息
        Returns:
            任务ID到任务信息的映射
        """
        result = {}
        async with self._lock:
            for task_id, task_data in self._tasks.items():
                result[task_id] = task_data["info"]
        return result

    async def get_active_tasks(self) -> Dict[str, TaskInfo]:
        """
        获取所有活跃任务（正在运行或等待中的任务）
        Returns:
            活跃任务ID到任务信息的映射
        """
        result = {}
        async with self._lock:
            for task_id, task_data in self._tasks.items():
                if task_data["info"].status in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                    result[task_id] = task_data["info"]
        return result

    async def schedule_periodic_task(
        self,
        func: Callable,
        interval: float,
        name: str = "periodic_task",
        priority: Union[TaskPriority, int] = TaskPriority.LOW,
        args: tuple = (),
        kwargs: dict = None,
    ) -> str:
        """
        调度一个周期性任务
        Args:
            func: 要执行的函数
            interval: 执行间隔（秒）
            name: 任务名称
            priority: 任务优先级
            args: 函数位置参数
            kwargs: 函数关键字参数
        Returns:
            周期性任务ID
        """
        if kwargs is None:
            kwargs = {}

        # 创建周期性任务的包装函数
        async def periodic_wrapper():
            next_run = time.time() + interval
            while self._running:
                # 等待到下次执行时间
                wait_time = max(0, next_run - time.time())
                await asyncio.sleep(wait_time)
                # 计算下次执行时间
                next_run = time.time() + interval
                # 提交单次任务执行
                try:
                    await self.schedule_task(
                        func=func,
                        name=f"{name}_run",
                        priority=priority,
                        args=args,
                        kwargs=kwargs,
                    )
                except Exception as e:
                    logger.error(f"周期性任务 {name} 提交失败: {str(e)}", exc_info=True)

        # 创建周期性任务的协程
        periodic_task = asyncio.create_task(periodic_wrapper())
        periodic_task_id = f"periodic_{uuid.uuid4().hex[:8]}"
        # 保存到后台任务集合
        self._background_tasks.add(periodic_task)
        periodic_task.add_done_callback(self._background_tasks.discard)
        logger.info(f"周期性任务已调度 - 名称: {name}, 间隔: {interval}秒")
        return periodic_task_id

    async def clean_completed_tasks(self, max_age: float = 3600) -> int:
        """
        清理已完成的旧任务
        Args:
            max_age: 最大保留时间（秒）
        Returns:
            清理的任务数量
        """
        cleaned_count = 0
        current_time = time.time()
        async with self._lock:
            expired_task_ids = []
            for task_id, task_data in self._tasks.items():
                task_info = task_data["info"]
                # 检查任务是否已完成、失败或取消，并且已经超过保留时间
                if (
                    task_info.status
                    in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]
                    and task_info.end_time
                    and current_time - task_info.end_time > max_age
                ):
                    expired_task_ids.append(task_id)
            # 移除过期任务
            for task_id in expired_task_ids:
                del self._tasks[task_id]
                cleaned_count += 1
        if cleaned_count > 0:
            logger.info(f"清理了 {cleaned_count} 个已完成的旧任务")
        return cleaned_count


# 创建全局任务调度器实例
_global_scheduler: Optional[GlobalTaskScheduler] = None


def get_global_scheduler() -> GlobalTaskScheduler:
    """
    获取全局任务调度器实例
    Returns:
        全局任务调度器实例
    """
    global _global_scheduler
    if _global_scheduler is None:
        _global_scheduler = GlobalTaskScheduler()
    return _global_scheduler


async def initialize_scheduler():
    """
    初始化全局调度器
    """
    scheduler = get_global_scheduler()
    await scheduler.start()
    # 调度定期清理任务
    await scheduler.schedule_periodic_task(
        func=scheduler.clean_completed_tasks,
        interval=300,  # 每5分钟清理一次
        name="cleanup_completed_tasks",
        args=(3600,),  # 清理1小时前的任务
    )


async def shutdown_scheduler():
    """
    关闭全局调度器
    """
    global _global_scheduler
    if _global_scheduler is not None:
        await _global_scheduler.stop()
        _global_scheduler = None


# 便捷函数
