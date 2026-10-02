"""
调度器生命周期管理模块
负责调度器的初始化、启动、停止和状态查询
"""

from core.utils.logger import get_logger
import asyncio

import threading
import time
from typing import Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..cpp_scheduler_engine import CPPSchedulerEngine

logger = get_logger(__name__)


class SchedulerLifecycle:
    """调度器生命周期管理器"""

    def __init__(self, engine: "CPPSchedulerEngine"):
        self.engine = engine
        self._start_lock = threading.Lock()

    def start(
        self,
        worker_count: int = 4,
        gpu_config: Optional[Dict[str, Any]] = None,
        preload_llm: bool = False,
    ):
        """
        Initialize and start the C++ scheduler.
        """
        if not self.engine.enabled:
            return

        with self._start_lock:
            if self.engine._started:
                return

            try:
                _t0 = time.perf_counter()
                logger.info("Initializing C++ Resource Isolation Scheduler...")
                from ..scheduler_wrapper import _get_scheduler_class

                _t1 = time.perf_counter()
                ResourceIsolationScheduler = _get_scheduler_class("ResourceIsolationScheduler")
                logger.info("_get_scheduler_class: %.3fs", time.perf_counter() - _t1)
                if ResourceIsolationScheduler is None:
                    raise RuntimeError("C++ scheduler bindings not available")

                _t2 = time.perf_counter()
                self.engine.scheduler = ResourceIsolationScheduler()
                self.engine._gpu_worker_ready = False
                logger.info("ResourceIsolationScheduler(): %.3fs", time.perf_counter() - _t2)

                _t3 = time.perf_counter()
                success = self.engine.scheduler.initialize(worker_count)
                logger.info("scheduler.initialize(%d): %.3fs", worker_count, time.perf_counter() - _t3)
                if not success:
                    raise RuntimeError("Failed to initialize scheduler system")

                if gpu_config:
                    self.engine._gpu_config = gpu_config
                    from ..utils.startup_config import resolve_llm_backend

                    self.engine._llm_backend = resolve_llm_backend(gpu_config, logger)

                    if preload_llm:
                        _t4 = time.perf_counter()
                        if self.engine._llm_backend == "cpp":
                            self.engine._setup_gpu_worker(gpu_config)
                        else:
                            self.engine._setup_python_llm(gpu_config)
                        logger.info("LLM预加载: %.3fs", time.perf_counter() - _t4)

                self.engine.bio_system = self.engine.scheduler.getBiologicalSystem()
                from ..utils.startup_config import apply_biological_config
                from ..scheduler_wrapper import _get_scheduler_py

                apply_biological_config(self.engine.bio_system, _get_scheduler_py(), logger)

                self.engine._started = True
                logger.info("C++ Scheduler initialized successfully (%.3fs)", time.perf_counter() - _t0)
            except Exception as e:
                logger.error(f"Failed to start C++ Scheduler: {e}", exc_info=True)
                self.engine.scheduler = None
                self.engine._enabled_value = False

    async def apply_llm_config(
        self,
        gpu_config: Optional[Dict[str, Any]],
        worker_count: int = 4,
        preload_llm: bool = False,
    ) -> bool:
        if not self.engine.enabled:
            return False
        if not gpu_config:
            return False
        if not self.engine.scheduler:
            await asyncio.to_thread(
                self.start,
                worker_count=worker_count,
                gpu_config=gpu_config,
                preload_llm=preload_llm,
            )
            return bool(self.engine.scheduler)

        from ..utils.startup_config import resolve_llm_backend

        backend = resolve_llm_backend(gpu_config, logger)

        async with self.engine._llm_setup_lock:
            self.engine._gpu_config = gpu_config
            self.engine._llm_backend = backend

        if preload_llm:
            if self.engine._llm_backend == "cpp":
                await asyncio.to_thread(self.engine._setup_gpu_worker, gpu_config)
            else:
                await asyncio.to_thread(self.engine._setup_python_llm, gpu_config)
        return True

    async def stop(self):
        """Stop the C++ scheduler and release all resources."""
        if not self.engine.enabled:
            return

        logger.info("Stopping C++ Scheduler Engine...")

        if self.engine.llm:
            logger.info("Releasing Python LLM instance...")
            try:
                await asyncio.to_thread(
                    lambda: self.engine.llm.close()
                    if hasattr(self.engine.llm, "close")
                    else None
                )
            except Exception as e:
                logger.error(f"Error closing Python LLM: {e}")
            self.engine.llm = None

        worker = getattr(self.engine, "_gpu_llm_worker", None)
        if worker:
            try:
                await asyncio.to_thread(worker.shutdown)
            except Exception:
                pass
            self.engine._gpu_llm_worker = None

        if self.engine.scheduler:
            try:
                await asyncio.to_thread(self.engine.scheduler.shutdown)
            except Exception as e:
                logger.error("Failed to shutdown C++ Scheduler cleanly: %s", e)
            self.engine.scheduler = None

        self.engine.bio_system = None
        self.engine._started = False
        self.engine._gpu_worker_ready = False

        # P2-11: 关闭 LLMModelManager 的内部 ThreadPoolExecutor，避免线程泄漏
        try:
            self.engine.model_manager.shutdown()
        except Exception as e:
            logger.debug("Failed to shutdown LLMModelManager executor: %s", e)

        try:
            from core.resource_manager import get_resource_manager

            get_resource_manager().mark_model_loaded("llm_engine", False)
        except Exception:
            pass

        try:
            import gc

            gc.collect()
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass

        logger.info("C++ Scheduler Engine stopped and resources released.")

    def get_status(self) -> Dict[str, Any]:
        """获取调度器和生物系统的完整状态"""
        if not self.engine.enabled or not self.engine.scheduler:
            return {"enabled": False}

        status = {
            "enabled": True,
            "started": self.engine._started,
            "llm_backend": self.engine._llm_backend,
            "gpu_worker_ready": self.engine._gpu_worker_ready,
            "active_cpp_task_id": self.engine._active_cpp_task_id,
        }

        if self.engine.bio_system:
            try:
                from ..bio.bio_state import build_biological_status

                biological = build_biological_status(self.engine.bio_system)
                if isinstance(biological, dict):
                    status["biological"] = biological
            except Exception as e:
                logger.error(f"获取生物系统状态失败: {e}")

        try:
            if hasattr(self.engine.scheduler, "getSystemStatus"):
                sys_status = self.engine.scheduler.getSystemStatus()

                status["tasks"] = {
                    "total": int(sys_status.totalTasks),
                    "pending": int(sys_status.pendingTasks),
                    "running": int(sys_status.runningTasks),
                    "completed": int(sys_status.completedTasks),
                    "failed": int(sys_status.failedTasks),
                }

                status["scheduler"] = {
                    "total_tasks": int(sys_status.totalTasks),
                    "pending_tasks": int(sys_status.pendingTasks),
                    "running_tasks": int(sys_status.runningTasks),
                    "completed_tasks": int(sys_status.completedTasks),
                    "failed_tasks": int(sys_status.failedTasks),
                }

            if hasattr(self.engine.scheduler, "getResourceUsage"):
                res_usage = self.engine.scheduler.getResourceUsage()

                gpu_total_mb = 0
                try:
                    import torch

                    if torch.cuda.is_available():
                        gpu_total_mb = int(
                            torch.cuda.get_device_properties(0).total_memory
                            / (1024 * 1024)
                        )
                except Exception:
                    pass

                status["resources"] = {
                    "cpu_load": float(res_usage.cpuUsage),
                    "gpu_mem_used": int(res_usage.gpuMemoryUsage),
                    "gpu_mem_total": gpu_total_mb,
                    "cpu_usage": float(res_usage.cpuUsage),
                    "gpu_usage": float(res_usage.gpuUsage),
                    "memory_mb": int(res_usage.memoryUsage),
                    "gpu_memory_mb": int(res_usage.gpuMemoryUsage),
                }

            status["worker_count"] = 4

        except Exception:
            pass

        return status
