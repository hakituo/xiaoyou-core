"""
C++ 调度引擎主模块
负责协调各个子模块，提供统一的调度接口
"""

from core.utils.logger import get_logger
import asyncio

import os
import threading
from typing import Optional, Dict, Any, AsyncGenerator

from .utils.circuit_breaker import (
    breaker_is_open,
    breaker_on_failure,
    breaker_on_success,
    create_breaker_state,
    get_breaker_status as build_breaker_status,
)
from .utils.resource_utils import offload_tts_services
from .scheduler_wrapper import is_cpp_scheduler_available
from core.utils.config_accessor import get_config
from .model.llm_model_manager import LLMModelManager
from .model.gpu_resource_manager import GPUResourceManager
from .lifecycle.scheduler_lifecycle import SchedulerLifecycle
from .inference.inference_executor import InferenceExecutor
from .lifecycle.health_monitor import HealthMonitor
from .bio.bio_system_manager import BioSystemManager
from .inference.inference_stats import get_last_llm_stats as get_last_llm_stats_impl
from core.utils.async_locks import LazyAsyncLock

logger = get_logger(__name__)


class CPPSchedulerEngine:
    """C++ 调度引擎主类（精简后）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CPPSchedulerEngine, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # 基础状态
        self.scheduler = None
        self.bio_system = None
        self._enabled_checked = False
        self._enabled_value = False
        self._initialized = True
        self._started = False
        self._gpu_config = None
        self._llm_backend = None
        self._gpu_worker_ready = False
        self._gpu_llm_worker = None
        self._llm_setup_lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._active_state_lock = threading.Lock()
        self._active_python_stop_event = None
        self._active_cpp_task_id = None

        # Circuit Breaker（断路器）机制
        self._breaker_threshold = int(os.getenv("XIAOYOU_CPP_BREAKER_THRESHOLD", "3") or 3)
        self._breaker_min_cooldown_s = float(os.getenv("XIAOYOU_CPP_BREAKER_MIN_COOLDOWN_S", "5") or 5)
        self._breaker_max_cooldown_s = float(os.getenv("XIAOYOU_CPP_BREAKER_MAX_COOLDOWN_S", "60") or 60)
        self._breaker: Dict[str, Dict[str, Any]] = create_breaker_state(
            self._breaker_min_cooldown_s
        )

        # KV Cache 紧急保存/恢复机制
        self._saved_llm_state: Any = None
        self._saved_llm_state_ts: float = 0.0

        # 推理统计信息
        self._last_llm_stats: Optional[Dict[str, Any]] = None

        # 初始化各个管理器
        self.model_manager = LLMModelManager()
        self.gpu_manager = GPUResourceManager(self.model_manager)
        self.lifecycle = SchedulerLifecycle(self)
        self.inference_executor = InferenceExecutor(self)
        self.health_monitor = HealthMonitor(self)
        self.bio_system_manager = BioSystemManager(self)

        if not self.enabled:
            logger.warning("C++ Scheduler is not available. Engine disabled.")

        # 注册到资源管理器
        should_register_llm = False
        if self.enabled:
            try:
                from config.integrated_config import get_settings

                settings = get_settings()
                sched = getattr(settings, "scheduler", None)
                use_cpp = bool(getattr(sched, "use_cpp", False))
                use_cpp_for_llm = bool(getattr(sched, "use_cpp_for_llm", False))
                text_path = get_config("model.text_path", default=None, settings=settings)
                should_register_llm = bool(
                    use_cpp
                    and use_cpp_for_llm
                    and text_path
                    and str(text_path).lower().endswith(".gguf")
                )
            except Exception:
                should_register_llm = False

        if self.enabled and should_register_llm:
            try:
                from core.resource_manager import get_resource_manager, ResourcePriority

                rm = get_resource_manager()
                rm.register_model(
                    model_id="llm_engine",
                    model_type="llm",
                    priority=ResourcePriority.HIGH,
                    load_func=self._reload_llm,
                    unload_func=self.unload_llm,
                    offload_func=self.offload_llm_to_cpu,
                    instance=self,
                )
            except Exception as e:
                logger.error(
                    f"Failed to register LLM Engine with Resource Manager: {e}"
                )

    @property
    def enabled(self) -> bool:
        """延迟检查 C++ 调度器是否可用"""
        if not self._enabled_checked:
            self._enabled_checked = True
            self._enabled_value = is_cpp_scheduler_available()
        return self._enabled_value

    # ==================== 代理属性 ====================

    @property
    def llm(self):
        """代理到 model_manager.llm"""
        return self.model_manager.llm

    @llm.setter
    def llm(self, value):
        """代理到 model_manager.llm"""
        self.model_manager.llm = value

    # ==================== 断路器方法 ====================

    def _breaker_is_open(self, kind: str) -> bool:
        return breaker_is_open(self._breaker, kind)

    def _breaker_on_success(self, kind: str) -> None:
        breaker_on_success(self._breaker, kind, self._breaker_min_cooldown_s)

    def _breaker_on_failure(self, kind: str) -> None:
        breaker_on_failure(
            self._breaker,
            kind,
            self._breaker_threshold,
            self._breaker_min_cooldown_s,
            self._breaker_max_cooldown_s,
            logger,
        )

    # ==================== 活动状态管理 ====================

    def _set_active_python_stop_event(self, stop_event):
        try:
            with self._active_state_lock:
                self._active_python_stop_event = stop_event
        except Exception as e:
            logger.debug("设置Python停止事件失败: %s", e)

    def _clear_active_python_stop_event(self, stop_event):
        try:
            with self._active_state_lock:
                if self._active_python_stop_event is stop_event:
                    self._active_python_stop_event = None
        except Exception as e:
            logger.debug("清除Python停止事件失败: %s", e)

    def _set_active_cpp_task_id(self, task_id: Optional[str]):
        try:
            with self._active_state_lock:
                self._active_cpp_task_id = task_id
        except Exception as e:
            logger.debug("设置C++任务ID失败: %s", e)

    def is_busy(self) -> bool:
        """Check if the scheduler is currently processing a task."""
        if not self.enabled:
            return False

        try:
            with self._active_state_lock:
                if self._active_python_stop_event is not None:
                    return True
                if self._active_cpp_task_id is not None:
                    return True
        except Exception as e:
            logger.debug("检查调度器忙碌状态失败: %s", e)

        return False

    async def request_stop_current_inference(self):
        stop_event = None
        task_id = None
        try:
            with self._active_state_lock:
                stop_event = self._active_python_stop_event
                task_id = self._active_cpp_task_id
        except Exception as e:
            logger.debug("获取活动状态失败: %s", e)
            stop_event = None
            task_id = None

        if stop_event is not None:
            try:
                stop_event.set()
            except Exception as e:
                logger.debug("设置停止事件失败: %s", e)

        if task_id and self.scheduler:
            try:
                await asyncio.to_thread(self.scheduler.cancelTask, task_id)
            except Exception as e:
                logger.debug("取消C++任务失败: %s", e)

    # ==================== 健康检查 / 自动重启 ====================

    async def _restart_scheduler(self) -> bool:
        """完全重启C++调度器，用于从GPU死锁/推理卡死中恢复。

        复用 HealthMonitor 的重启实现：停止调度器、清理GPU缓存、
        等待资源释放后重新初始化，并恢复GPU工作器。
        """
        return await self.health_monitor.restart_scheduler()

    async def _health_check_gpu_worker(self) -> bool:
        """对GPU工作器执行健康检查（提交简单推理测试）"""
        return await self.health_monitor.health_check_gpu_worker()

    # ==================== 模型切换 ====================

    async def _maybe_switch_cpp_model(
        self, requested_model_path: Optional[str]
    ) -> bool:
        if not self.enabled:
            return False
        if self._llm_backend != "cpp":
            return False
        if not isinstance(self._gpu_config, dict):
            return False
        if not isinstance(requested_model_path, str):
            return False
        if not requested_model_path or not requested_model_path.lower().endswith(
            ".gguf"
        ):
            return False

        from core.modules.llm.utils import normalize_local_path

        current_model_path = str(self._gpu_config.get("model_path") or "")
        current_normalized = (
            normalize_local_path(current_model_path) if current_model_path else ""
        )
        requested_normalized = normalize_local_path(requested_model_path)

        if current_normalized == requested_normalized:
            logger.info(f"Model already loaded: {requested_normalized}")
            return False

        await self.request_stop_current_inference()

        async with self._llm_setup_lock:
            current_model_path = str(self._gpu_config.get("model_path") or "")
            current_normalized = (
                normalize_local_path(current_model_path) if current_model_path else ""
            )
            if current_normalized == requested_normalized:
                return False
            self._gpu_config["model_path"] = requested_model_path
            self._gpu_worker_ready = False
            if self.scheduler:
                await asyncio.to_thread(self._setup_gpu_worker, self._gpu_config)
        return True

    # ==================== 生命周期代理方法 ====================

    def start(
        self,
        worker_count: int = 4,
        gpu_config: Optional[Dict[str, Any]] = None,
        preload_llm: bool = False,
    ):
        """启动调度器"""
        return self.lifecycle.start(worker_count, gpu_config, preload_llm)

    async def apply_llm_config(
        self,
        gpu_config: Optional[Dict[str, Any]],
        worker_count: int = 4,
        preload_llm: bool = False,
    ) -> bool:
        """应用LLM配置"""
        return await self.lifecycle.apply_llm_config(gpu_config, worker_count, preload_llm)

    async def stop(self):
        """停止调度器"""
        return await self.lifecycle.stop()

    def get_status(self) -> Dict[str, Any]:
        """获取调度器状态"""
        return self.lifecycle.get_status()

    # ==================== 模型管理代理方法 ====================

    async def _reload_llm(self):
        """重新加载LLM"""
        if self._gpu_config:
            logger.info("Reloading LLM...")

            await offload_tts_services("CPPScheduler")

            async with self._llm_setup_lock:
                if self._llm_backend == "cpp":
                    if not self._gpu_worker_ready:
                        await asyncio.to_thread(
                            self._setup_gpu_worker, self._gpu_config
                        )
                else:
                    if not self.llm:
                        await asyncio.to_thread(
                            self._setup_python_llm, self._gpu_config
                        )

    async def preload_llm(self):
        """预加载LLM"""
        if not self.enabled:
            return
        if not self._gpu_config:
            return
        await self._reload_llm()

    async def unload_llm(self):
        """卸载LLM"""
        await self.model_manager.unload_llm()

    def _setup_python_llm(
        self, config: Dict[str, Any], return_instance: bool = False
    ) -> Optional[Any]:
        """初始化Python侧Llama实例"""
        return self.model_manager.setup_python_llm(config, return_instance)

    def _setup_gpu_worker(self, config: Dict[str, Any]):
        """设置GPU工作器"""
        try:
            if not self.scheduler:
                raise RuntimeError("C++ Scheduler is not running.")

            from .scheduler_wrapper import _get_scheduler_class

            GPULLMWorker = _get_scheduler_class("GPULLMWorker")

            llm_config = self.model_manager._build_cpp_llm_config(config)

            worker = self._gpu_llm_worker
            add_worker = False
            if worker is None:
                worker = GPULLMWorker("gpu-worker-0")
                self._gpu_llm_worker = worker
                add_worker = True

            try:
                worker.shutdown()
            except Exception:
                pass

            worker.setModelConfig(llm_config)

            logger.info("Initializing GPU Worker (loading model)...")
            if worker.initialize():
                logger.info("GPU Worker initialized successfully.")
                if add_worker:
                    self.scheduler.addWorker(worker)
                self._gpu_worker_ready = True
                try:
                    from core.resource_manager import get_resource_manager

                    get_resource_manager().mark_model_loaded("llm_engine", True)
                except Exception:
                    pass
            else:
                logger.error("Failed to initialize GPU Worker.")
                self._gpu_worker_ready = False

        except Exception as e:
            logger.error(f"Failed to setup GPU worker: {e}")
            self._gpu_worker_ready = False

    # ==================== GPU资源管理代理方法 ====================

    async def offload_llm_to_cpu(self, urgent: bool = False):
        """将LLM迁移到CPU"""
        if self._llm_backend == "cpp":
            await self.release_llm_vram_for_image_gen()
            return
        await self.gpu_manager.offload_llm_to_cpu(urgent)

    async def restore_llm_to_gpu(self) -> bool:
        """将LLM回迁到GPU"""
        if self._llm_backend == "cpp":
            target_gpu = None
            if (
                isinstance(self.gpu_manager._prev_cpp_gpu_device_id, int)
                and self.gpu_manager._prev_cpp_gpu_device_id >= 0
            ):
                target_gpu = int(self.gpu_manager._prev_cpp_gpu_device_id)
            if target_gpu is None and isinstance(self._gpu_config, dict):
                try:
                    cfg_gpu = int(self._gpu_config.get("gpu_device_id", 0))
                    if cfg_gpu >= 0:
                        target_gpu = int(cfg_gpu)
                except Exception:
                    target_gpu = None
            if target_gpu is None:
                target_gpu = 0

            target_draft = -1
            if isinstance(self.gpu_manager._prev_cpp_draft_gpu_device_id, int):
                target_draft = int(self.gpu_manager._prev_cpp_draft_gpu_device_id)
            elif isinstance(self._gpu_config, dict):
                try:
                    target_draft = int(self._gpu_config.get("draft_gpu_device_id", -1))
                except Exception:
                    target_draft = -1

            logger.info(f"C++ LLM Worker 正在切回设备: GPU {target_gpu}")
            ok = await self._switch_cpp_llm_worker_device(target_gpu, target_draft)
            if not ok:
                logger.warning("C++ LLM Worker restore to GPU failed")
            return bool(ok)

        return await self.gpu_manager.restore_llm_to_gpu()

    async def release_llm_vram_for_image_gen(self):
        """为图像生成释放LLM显存"""
        if self._llm_backend == "python":
            await self.offload_llm_to_cpu(urgent=True)
            return

        if self._llm_backend == "cpp":
            if not isinstance(self._gpu_config, dict):
                return
            gpu_id = None
            draft_id = None
            try:
                gpu_id = int(self._gpu_config.get("gpu_device_id", 0))
            except Exception:
                gpu_id = None
            try:
                draft_id = int(self._gpu_config.get("draft_gpu_device_id", -1))
            except Exception:
                draft_id = None

            if gpu_id is not None and gpu_id < 0:
                try:
                    from core.resource_manager import get_resource_manager

                    rm = get_resource_manager()
                    model = rm.models.get("llm_engine")
                    if model:
                        model.device = "CPU"
                        model.vram_usage_mb = 0
                    rm.mark_model_loaded("llm_engine", True)
                except Exception:
                    pass
                return

            if isinstance(gpu_id, int) and gpu_id >= 0:
                self.gpu_manager._prev_cpp_gpu_device_id = int(gpu_id)
            if isinstance(draft_id, int):
                self.gpu_manager._prev_cpp_draft_gpu_device_id = int(draft_id)

            ok = await self._switch_cpp_llm_worker_device(-1, -1)
            if not ok:
                logger.warning("C++ LLM Worker offload to CPU failed")
            return

    async def _switch_cpp_llm_worker_device(
        self, gpu_device_id: int, draft_gpu_device_id: int = -1
    ) -> bool:
        """切换C++ LLM工作器的设备"""
        if self._llm_backend != "cpp" or not self.scheduler:
            return False
        if not isinstance(self._gpu_config, dict):
            return False
        worker = getattr(self, "_gpu_llm_worker", None)
        if not worker:
            return False

        try:
            await self.request_stop_current_inference()
        except Exception:
            pass

        async with self._llm_setup_lock:
            self._gpu_config["gpu_device_id"] = int(gpu_device_id)
            self._gpu_config["draft_gpu_device_id"] = int(draft_gpu_device_id)
            llm_config = self.model_manager._build_cpp_llm_config(self._gpu_config)

            def _do_switch() -> bool:
                try:
                    worker.shutdown()
                except Exception:
                    pass
                worker.setModelConfig(llm_config)
                return bool(worker.initialize())

            ok = await asyncio.to_thread(_do_switch)
            self._gpu_worker_ready = bool(ok)

        try:
            from core.resource_manager import get_resource_manager

            rm = get_resource_manager()
            model = rm.models.get("llm_engine")
            if model:
                if int(gpu_device_id) < 0:
                    model.device = "CPU"
                    model.vram_usage_mb = 0
                    model.memory_usage_mb = max(int(model.memory_usage_mb or 0), 450)
                    model.is_offloaded = True
                else:
                    model.device = "GPU"
                    model.is_offloaded = False
            rm.mark_model_loaded("llm_engine", bool(ok))
        except Exception:
            pass

        return bool(ok)

    async def offload_kv_cache_to_cpu(self) -> bool:
        """将KV Cache迁移到CPU"""
        return await self.gpu_manager.offload_kv_cache_to_cpu()

    async def restore_kv_cache_to_gpu(self) -> bool:
        """将KV Cache回迁到GPU"""
        return await self.gpu_manager.restore_kv_cache_to_gpu()

    async def clear_conversation_cache(self, conversation_id: str) -> bool:
        """清除指定会话在 C++ LLM Worker 中驻留的 KV Cache。"""
        normalized_id = str(conversation_id or "").strip()
        if not normalized_id or self._llm_backend != "cpp":
            return False

        worker = getattr(self, "_gpu_llm_worker", None)
        clear_cache = getattr(worker, "clearConversationCache", None) if worker else None
        if not callable(clear_cache):
            logger.warning(
                "C++ LLM Worker 尚未提供会话 KV Cache 清理接口，请重新编译 scheduler_py"
            )
            return False

        try:
            cleared = bool(await asyncio.to_thread(clear_cache, normalized_id))
            if cleared:
                logger.info("已清除 C++ 会话 KV Cache: %s", normalized_id)
            else:
                logger.warning("C++ 会话 KV Cache 清理未完成: %s", normalized_id)
            return cleared
        except Exception as e:
            logger.warning("清除 C++ 会话 KV Cache 失败 (%s): %s", normalized_id, e)
            return False

    # ==================== 推理任务代理方法 ====================

    async def submit_llm_task(self, prompt: str, **kwargs) -> AsyncGenerator[Any, None]:
        """提交LLM任务"""
        async for token in self.inference_executor.submit_llm_task(prompt, **kwargs):
            yield token

    # ==================== 其他方法 ====================

    def get_biological_system(self):
        """获取生物系统"""
        return self.bio_system_manager.get_biological_system()

    def get_last_llm_stats(self) -> Optional[Dict[str, Any]]:
        """获取最近一次推理统计"""
        return get_last_llm_stats_impl(self)

    def get_breaker_status(self) -> Dict[str, Dict[str, Any]]:
        """获取断路器状态"""
        return build_breaker_status(self._breaker)


# 全局实例（懒加载，避免模块导入时触发C++扩展加载）
_cpp_scheduler_engine_instance: Optional["CPPSchedulerEngine"] = None
_engine_started: bool = False


def get_scheduler_engine(auto_start: bool = True):
    """获取全局 C++ 调度引擎实例（懒加载）
    
    Args:
        auto_start: 是否自动启动引擎（首次调用时）。默认 True。
    """
    global _cpp_scheduler_engine_instance, _engine_started
    if _cpp_scheduler_engine_instance is None:
        _cpp_scheduler_engine_instance = CPPSchedulerEngine()
    
    if auto_start and not _engine_started and _cpp_scheduler_engine_instance.enabled:
        _auto_start_engine(_cpp_scheduler_engine_instance)
    
    return _cpp_scheduler_engine_instance


def _build_gpu_config(settings) -> Optional[Dict[str, Any]]:
    """构建 GPU 配置（从 lifecycle_manager 移植）"""
    try:
        if not (
            getattr(settings, "scheduler", None)
            and settings.scheduler.use_cpp_for_llm
            and settings.model.text_path
            and str(settings.model.text_path).lower().endswith(".gguf")
        ):
            return None

        max_context_size = settings.model.n_ctx or 4096
        max_batch_size = getattr(settings.model, "n_batch", None)
        n_gpu_layers = getattr(settings.model, "n_gpu_layers", -1)

        try:
            max_batch_size = int(max_batch_size)
        except (TypeError, ValueError):
            max_batch_size = 0
        if max_batch_size <= 0:
            max_batch_size = min(512, int(max_context_size))

        try:
            n_gpu_layers = int(n_gpu_layers)
        except (TypeError, ValueError):
            n_gpu_layers = -1

        gpu_total_mb = None
        try:
            import torch
            if torch.cuda.is_available():
                props = torch.cuda.get_device_properties(0)
                gpu_total_mb = int(int(props.total_memory) // (1024 * 1024))
        except Exception:
            gpu_total_mb = None

        if isinstance(gpu_total_mb, int) and gpu_total_mb > 0:
            if gpu_total_mb <= 8192:
                max_context_size = min(int(max_context_size), 2048)
                max_batch_size = min(int(max_batch_size), 256)
                if n_gpu_layers < 0 or n_gpu_layers > 50:
                    n_gpu_layers = 50

        if int(max_batch_size) > int(max_context_size):
            max_batch_size = int(max_context_size)

        return {
            "backend": settings.scheduler.llm_backend,
            "model_path": settings.model.text_path,
            "model_type": "llama",
            "gpu_device_id": 0,
            "n_gpu_layers": n_gpu_layers,
            "max_context_size": int(max_context_size),
            "max_batch_size": int(max_batch_size),
            "temperature": settings.model.temperature or 0.7,
            "top_p": settings.model.top_p or 0.95,
            "top_k": settings.model.top_k or 40,
            "repetition_penalty": settings.model.repetition_penalty or 1.1,
        }
    except Exception:
        return None


def _auto_start_engine(engine: "CPPSchedulerEngine"):
    """自动启动引擎（首次需要时）"""
    global _engine_started
    if _engine_started:
        return
    if getattr(engine, "_auto_start_attempted", False):
        return
    engine._auto_start_attempted = True
    try:
        from config.integrated_config import get_settings
        from core.utils.config_accessor import get_config
        
        settings = get_settings()
        scheduler_settings = getattr(settings, "scheduler", None)
        use_cpp = bool(getattr(scheduler_settings, "use_cpp", False))
        
        if not use_cpp:
            return
        
        worker_count = (
            get_config("scheduler.worker_count", default=4, settings=settings) or 4
        )
        
        gpu_config = _build_gpu_config(settings)
        
        engine.start(worker_count=worker_count, gpu_config=gpu_config)
        _engine_started = True
        logger.info("cpp_scheduler_engine 自动启动完成（懒加载）")
    except Exception as e:
        logger.warning(f"cpp_scheduler_engine 自动启动失败: {e}")


def ensure_scheduler_started():
    """确保调度器已启动（显式调用）"""
    engine = get_scheduler_engine(auto_start=False)
    if engine and engine.enabled:
        _auto_start_engine(engine)
    return engine


# 兼容旧代码的属性访问
def __getattr__(name):
    if name == "cpp_scheduler_engine":
        return get_scheduler_engine()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_scheduler_status() -> Optional[Dict[str, Any]]:
    """安全获取 C++ 调度器状态，失败返回 None"""
    try:
        engine = get_scheduler_engine()
        if engine and getattr(engine, "enabled", False):
            return engine.get_status()
    except Exception:
        pass
    return None
