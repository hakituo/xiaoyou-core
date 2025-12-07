import asyncio
import logging
import time
from enum import Enum
from typing import Dict, List, Optional, Callable, Any, Union
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import concurrent.futures
import contextvars
from mvp_core.utils.trace_context import TraceContext
from mvp_core.utils.logger import logger

# Try to import torch, but don't fail if missing (unless used)
try:
    import torch
except ImportError:
    torch = None

# Task context
_current_task_id_ctx = contextvars.ContextVar("current_task_id", default=None)

def get_current_task_id() -> Optional[str]:
    """Get current task ID"""
    return _current_task_id_ctx.get()

class TaskPriority(Enum):
    """Task Priority Enum"""
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3

class TaskStatus(Enum):
    """Task Status Enum"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskType(Enum):
    """Task Type Enum"""
    DEFAULT = "default"
    CPU_BOUND = "cpu"
    GPU_BOUND = "gpu"

@dataclass(order=True)
class TaskInfo:
    """Task Info Data Class"""
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
    trace_id: str = field(default="system", compare=False)

class GlobalTaskScheduler:
    """
    Unified Global Task Scheduler
    """
    def __init__(self):
        self._tasks: Dict[str, Dict] = {}
        self._task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._worker_count: int = 3
        self._workers: List[asyncio.Task] = []
        self._running: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()
        self._background_tasks: set = set()
        self._next_task_id = 0
        self._task_futures: Dict[str, asyncio.Future] = {}
        
        # Resource management
        self._gpu_lock = asyncio.Lock()
        self._cpu_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

    async def start(self, worker_count: int = 3):
        """Start scheduler"""
        if self._running:
            logger.warning("Scheduler already running")
            return
        
        self._worker_count = worker_count
        self._running = True
        
        for i in range(self._worker_count):
            worker = asyncio.create_task(self._worker_coroutine(f"worker-{i}"))
            self._workers.append(worker)
            self._background_tasks.add(worker)
            worker.add_done_callback(self._background_tasks.discard)
            
        logger.info(f"GlobalTaskScheduler started with {worker_count} workers")

    async def stop(self, timeout: Optional[float] = None):
        """Stop scheduler"""
        if not self._running:
            logger.warning("Scheduler not running")
            return
        
        self._running = False
        
        for worker in self._workers:
            worker.cancel()
            
        try:
            await asyncio.gather(*self._workers, return_exceptions=True)
        except asyncio.CancelledError:
            pass
            
        self._workers.clear()
        async with self._lock:
            self._task_futures.clear()
            
        self._cpu_executor.shutdown(wait=False)
        logger.info("GlobalTaskScheduler stopped")

    async def _execute_task(self, task_func, task_type, *args, **kwargs):
        import inspect

        if task_type == TaskType.GPU_BOUND:
            async with self._gpu_lock:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(
                    None, lambda: task_func(*args, **kwargs)
                )
        elif task_type == TaskType.CPU_BOUND:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                self._cpu_executor, lambda: task_func(*args, **kwargs)
            )
        else:
            if asyncio.iscoroutinefunction(task_func) or inspect.iscoroutinefunction(task_func):
                return await task_func(*args, **kwargs)
            else:
                result = await asyncio.to_thread(task_func, *args, **kwargs)
                if inspect.isawaitable(result):
                    return await result
                return result

    async def _worker_coroutine(self, worker_name: str):
        logger.debug(f"Worker {worker_name} started")
        try:
            while self._running:
                try:
                    priority_val, task_info = await asyncio.wait_for(
                        self._task_queue.get(), 
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Worker {worker_name} error getting task: {str(e)}", exc_info=True)
                    continue

                try:
                    # Set execution context early for logging
                    token = _current_task_id_ctx.set(task_info.task_id)
                    trace_token = TraceContext.set_trace_id(task_info.trace_id)
                    
                    try:
                        if task_info.cancel_requested:
                            logger.debug(f"Task {task_info.task_id} cancelled, skipping")
                            async with self._lock:
                                task_info.status = TaskStatus.CANCELLED
                                fut = self._task_futures.get(task_info.task_id)
                                if fut and not fut.done():
                                    fut.set_exception(asyncio.CancelledError())
                            continue
                            
                        logger.debug(f"Worker {worker_name} executing task {task_info.task_id}")
                        
                        task_func = None
                        task_args = ()
                        task_kwargs = {}
                        
                        async with self._lock:
                            if task_info.task_id in self._tasks:
                                task_info.status = TaskStatus.RUNNING
                                task_info.start_time = time.time()
                                task_data = self._tasks[task_info.task_id]
                                task_func = task_data.get('func')
                                task_args = task_data.get('args', ())
                                task_kwargs = task_data.get('kwargs', {})
                            else:
                                logger.warning(f"Task {task_info.task_id} data missing")
                                continue

                        if task_func is None:
                            logger.error(f"Task {task_info.task_id} function is None")
                            continue
                        
                        try:
                            result = await self._execute_task(
                                task_func, task_info.task_type, *task_args, **task_kwargs
                            )
                            
                            async with self._lock:
                                task_info.status = TaskStatus.COMPLETED
                                task_info.result = result
                                task_info.end_time = time.time()
                                
                                fut = self._task_futures.get(task_info.task_id)
                                if fut and not fut.done():
                                    fut.set_result(result)
                                
                                if task_info.task_id in self._tasks:
                                    self._tasks[task_info.task_id]['func'] = None
                                    self._tasks[task_info.task_id]['args'] = None
                                    self._tasks[task_info.task_id]['kwargs'] = None
                                    
                            logger.debug(f"Task {task_info.task_id} completed")
                            
                        except Exception as e:
                            async with self._lock:
                                task_info.status = TaskStatus.FAILED
                                task_info.error = str(e)
                                task_info.end_time = time.time()
                                
                                fut = self._task_futures.get(task_info.task_id)
                                if fut and not fut.done():
                                    fut.set_exception(e)
                                    
                            logger.error(f"Task {task_info.task_id} failed: {str(e)}", exc_info=True)
                            
                    finally:
                        _current_task_id_ctx.reset(token)
                        TraceContext.reset_trace_id(trace_token)
                    
                except Exception as e:
                    logger.error(f"Worker {worker_name} uncaught exception: {str(e)}", exc_info=True)
                finally:
                    self._task_queue.task_done()
                    
        finally:
            logger.debug(f"Worker {worker_name} stopped")

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        if task_id in self._tasks:
            return self._tasks[task_id]['info']
        return None

    async def schedule_task(
        self,
        func: Callable,
        name: str = "unnamed_task",
        priority: Union[TaskPriority, int] = TaskPriority.MEDIUM,
        task_type: TaskType = TaskType.DEFAULT,
        args: tuple = (),
        kwargs: dict = None,
        trace_id: Optional[str] = None
    ) -> str:
        if not self._running:
            raise RuntimeError("Scheduler not started")
            
        if kwargs is None:
            kwargs = {}
            
        if isinstance(priority, int):
            priority = TaskPriority(priority)
            
        task_id = f"task_{uuid.uuid4().hex[:8]}_{self._next_task_id}"
        self._next_task_id += 1
        
        # Capture current trace_id or generate a new one if this is a root task
        if trace_id:
            # Explicitly provided trace_id
            current_trace = trace_id
            # Ensure context is set for this scope (though it might not propagate back up)
            # TraceContext.set_trace_id(trace_id) 
        else:
            current_trace = TraceContext.get_trace_id()
        
        if current_trace == "system":
             # If we are in 'system' context, we might want to start a new trace for this task
             # But for now, let's respect the caller's context. 
             # If the caller didn't set a context, we generate one if it's an external request, 
             # but here we just use what we have.
             # Ideally, entry points (API handlers) should set the trace_id.
             pass

        task_info = TaskInfo(
            task_id=task_id,
            name=name,
            priority=priority,
            task_type=task_type,
            created_at=time.time(),
            status=TaskStatus.PENDING,
            trace_id=current_trace
        )
        
        async with self._lock:
            self._tasks[task_id] = {
                'info': task_info,
                'func': func,
                'args': args,
                'kwargs': kwargs
            }
            loop = asyncio.get_running_loop()
            self._task_futures[task_id] = loop.create_future()
            
        await self._task_queue.put((-priority.value, task_info))
        logger.debug(f"Task scheduled - ID: {task_id}, Name: {name}")
        return task_id

    async def schedule_gpu_task(self, func: Callable, *args, **kwargs) -> str:
        return await self.schedule_task(
            func, 
            task_type=TaskType.GPU_BOUND, 
            name=kwargs.pop('name', 'gpu_task'),
            priority=kwargs.pop('priority', TaskPriority.HIGH),
            args=args, 
            kwargs=kwargs
        )

    async def schedule_cpu_task(self, func: Callable, *args, **kwargs) -> str:
        return await self.schedule_task(
            func, 
            task_type=TaskType.CPU_BOUND, 
            name=kwargs.pop('name', 'cpu_task'),
            priority=kwargs.pop('priority', TaskPriority.MEDIUM),
            args=args, 
            kwargs=kwargs
        )

    async def cancel_task(self, task_id: str) -> bool:
        async with self._lock:
            if task_id not in self._tasks:
                return False
            task_info = self._tasks[task_id]['info']
            if task_info.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                return False
            if task_info.status == TaskStatus.RUNNING:
                task_info.cancel_requested = True
                return True
            task_info.status = TaskStatus.CANCELLED
            task_info.cancel_requested = True
            fut = self._task_futures.get(task_id)
            if fut and not fut.done():
                fut.set_exception(asyncio.CancelledError())
            return True

    async def get_task_status(self, task_id: str) -> Optional[TaskInfo]:
        async with self._lock:
            if task_id not in self._tasks:
                return None
            return self._tasks[task_id]['info']
    
    async def get_task_info(self, task_id: str) -> Optional[TaskInfo]:
        return await self.get_task_status(task_id)

    async def get_task_future(self, task_id: str) -> Optional[asyncio.Future]:
        async with self._lock:
            return self._task_futures.get(task_id)

    async def get_all_tasks(self) -> Dict[str, TaskInfo]:
        result = {}
        async with self._lock:
            for task_id, task_data in self._tasks.items():
                result[task_id] = task_data['info']
        return result

    async def get_active_tasks(self) -> Dict[str, TaskInfo]:
        result = {}
        async with self._lock:
            for task_id, task_data in self._tasks.items():
                if task_data['info'].status in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                    result[task_id] = task_data['info']
        return result

    async def schedule_periodic_task(
        self,
        func: Callable,
        interval: float,
        name: str = "periodic_task",
        priority: Union[TaskPriority, int] = TaskPriority.LOW,
        args: tuple = (),
        kwargs: dict = None
    ) -> str:
        if kwargs is None:
            kwargs = {}
        async def periodic_wrapper():
            next_run = time.time() + interval
            while self._running:
                wait_time = max(0, next_run - time.time())
                await asyncio.sleep(wait_time)
                next_run = time.time() + interval
                try:
                    await self.schedule_task(
                        func=func,
                        name=f"{name}_run",
                        priority=priority,
                        args=args,
                        kwargs=kwargs
                    )
                except Exception as e:
                    logger.error(f"Periodic task {name} submission failed: {str(e)}", exc_info=True)
        
        periodic_task = asyncio.create_task(periodic_wrapper())
        periodic_task_id = f"periodic_{uuid.uuid4().hex[:8]}"
        self._background_tasks.add(periodic_task)
        periodic_task.add_done_callback(self._background_tasks.discard)
        logger.info(f"Periodic task scheduled - Name: {name}, Interval: {interval}s")
        return periodic_task_id

    async def clean_completed_tasks(self, max_age: float = 3600) -> int:
        cleaned_count = 0
        current_time = time.time()
        async with self._lock:
            expired_task_ids = []
            for task_id, task_data in self._tasks.items():
                task_info = task_data['info']
                if (task_info.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED] and 
                    task_info.end_time and 
                    current_time - task_info.end_time > max_age):
                    expired_task_ids.append(task_id)
            for task_id in expired_task_ids:
                del self._tasks[task_id]
                cleaned_count += 1
        if cleaned_count > 0:
            logger.info(f"Cleaned {cleaned_count} completed tasks")
        return cleaned_count

# Global instance
_global_scheduler: Optional[GlobalTaskScheduler] = None

def get_global_scheduler() -> GlobalTaskScheduler:
    global _global_scheduler
    if _global_scheduler is None:
        _global_scheduler = GlobalTaskScheduler()
    return _global_scheduler

async def initialize_scheduler():
    scheduler = get_global_scheduler()
    await scheduler.start()
    await scheduler.schedule_periodic_task(
        func=scheduler.clean_completed_tasks,
        interval=300,
        name="cleanup_completed_tasks",
        args=(3600,),
    )

async def shutdown_scheduler():
    global _global_scheduler
    if _global_scheduler is not None:
        await _global_scheduler.stop()
        _global_scheduler = None
