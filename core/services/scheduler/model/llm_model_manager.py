"""
LLM模型管理模块
负责模型的加载、卸载、切换和配置
"""

from core.utils.logger import get_logger
import asyncio
import gc

import os
import time
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor

try:
    from llama_cpp import Llama
except ImportError:
    Llama = None

from core.modules.llm.utils import resolve_use_mmap
from core.utils.async_locks import LazyAsyncLock
from ..utils.resource_utils import (
    check_memory_pressure,
    offload_tts_services,
    get_cuda_free_mb,
)

logger = get_logger(__name__)

_LLAMA_CPP_INTERNALS_PATCHED = False


def _patch_llama_cpp_internals():
    """修补llama_cpp内部实现以避免崩溃"""
    global _LLAMA_CPP_INTERNALS_PATCHED
    if _LLAMA_CPP_INTERNALS_PATCHED:
        return
    try:
        import llama_cpp._internals as _internals

        llama_model_cls = getattr(_internals, "LlamaModel", None)
        if llama_model_cls is not None:
            if hasattr(llama_model_cls, "close"):
                original_close = llama_model_cls.close

                def _safe_close(self):
                    try:
                        if not hasattr(self, "sampler"):
                            setattr(self, "sampler", None)
                        return original_close(self)
                    except AttributeError:
                        return None

                llama_model_cls.close = _safe_close

            if hasattr(llama_model_cls, "__del__"):
                original_del = llama_model_cls.__del__

                def _safe_del(self):
                    try:
                        if not hasattr(self, "sampler"):
                            setattr(self, "sampler", None)
                        return original_del(self)
                    except Exception:
                        try:
                            return getattr(self, "close")()
                        except Exception:
                            return None

                llama_model_cls.__del__ = _safe_del
    except Exception:
        pass
    _LLAMA_CPP_INTERNALS_PATCHED = True


class LLMModelManager:
    """LLM模型管理器"""

    def __init__(self):
        self.llm = None
        self._gpu_config: Optional[Dict[str, Any]] = None
        self._llm_setup_lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._python_force_cpu = False
        self._prev_n_gpu_layers: Optional[int] = None
        self._prev_n_ctx: Optional[int] = None
        self._prev_n_batch: Optional[int] = None
        self._prev_offload_kqv: Optional[bool] = None
        self._last_llm_use_mmap: Optional[bool] = None
        self._last_llm_load_error: Optional[str] = None
        self._last_llm_load_ts: float = 0.0

        # 使用单线程 Executor 保证 LLM 操作都在同一个线程执行
        self._llm_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="LLMWorker"
        )

    def set_config(self, config: Dict[str, Any]):
        """设置GPU配置"""
        self._gpu_config = config

    def get_config(self) -> Optional[Dict[str, Any]]:
        """获取当前配置"""
        return self._gpu_config

    async def reload_llm(self):
        """从存储的配置重新加载LLM"""
        if not self._gpu_config:
            return

        logger.info("Reloading LLM...")

        await offload_tts_services("LLMModelManager")

        async with self._llm_setup_lock:
            if not self.llm:
                await asyncio.to_thread(self.setup_python_llm, self._gpu_config)

    async def unload_llm(self):
        """卸载LLM以释放显存"""
        async with self._llm_setup_lock:
            await self._unload_llm_locked()

    async def _unload_llm_locked(self):
        """内部卸载方法（已加锁）"""
        if not self.llm:
            return

        logger.info("Unloading LLM to free VRAM...")

        def _do_unload():
            if self.llm:
                try:
                    if hasattr(self.llm, "close"):
                        self.llm.close()
                except Exception:
                    pass
                self.llm = None
            gc.collect()

        await asyncio.get_running_loop().run_in_executor(self._llm_executor, _do_unload)

        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except ImportError:
            pass

        try:
            from core.resource_manager import get_resource_manager

            get_resource_manager().mark_model_loaded("llm_engine", False)
        except Exception:
            pass

        logger.info("LLM Unloaded.")

    def _get_cuda_free_mb_sync(self) -> Optional[int]:
        """同步获取CUDA可用显存（MB）"""
        return get_cuda_free_mb()

    def shutdown(self) -> None:
        """P2-11: 关闭内部 ThreadPoolExecutor，避免进程退出时线程泄漏。"""
        executor = getattr(self, "_llm_executor", None)
        if executor is not None:
            try:
                executor.shutdown(wait=False)
            except Exception:
                pass
            self._llm_executor = None

    def setup_python_llm(
        self, config: Dict[str, Any], return_instance: bool = False
    ) -> Optional[Any]:
        """
        初始化Python侧Llama实例
        支持资源自适应、容错和热切换
        """
        if not Llama:
            logger.error("llama_cpp not installed, cannot initialize LLM.")
            return None

        _patch_llama_cpp_internals()

        try:
            if not return_instance:
                try:
                    from core.resource_manager import get_resource_manager

                    get_resource_manager().mark_model_loaded("llm_engine", False)
                except Exception:
                    pass

            model_path = config.get("model_path")
            self._last_llm_load_error = None
            self._last_llm_load_ts = time.time()

            if not model_path or not isinstance(model_path, str):
                self._last_llm_load_error = "本地模型路径为空"
                logger.error("Python侧Llama模型加载失败：model_path为空")
                if not return_instance:
                    self.llm = None
                return None

            model_path = str(model_path)
            if not os.path.exists(model_path):
                self._last_llm_load_error = f"本地模型文件不存在: {model_path}"
                logger.error(
                    "Python侧Llama模型加载失败：模型文件不存在: %s", model_path
                )
                if not return_instance:
                    self.llm = None
                return None

            # 验证GGUF文件格式
            if model_path.lower().endswith(".gguf"):
                try:
                    with open(model_path, "rb") as f:
                        header = f.read(4)
                    if header != b"GGUF":
                        self._last_llm_load_error = "本地模型文件不是有效的GGUF格式（文件头不是GGUF），请确认下载完整且未损坏"
                        logger.error(
                            "Python侧Llama模型加载失败：GGUF文件头异常 (%s): %s",
                            header,
                            model_path,
                        )
                        if not return_instance:
                            self.llm = None
                        return None
                except Exception as e:
                    self._last_llm_load_error = f"读取本地模型文件失败: {e}"
                    logger.error("Python侧Llama模型加载失败：无法读取模型文件: %s", e)
                    if not return_instance:
                        self.llm = None
                    return None

            # 检查内存压力
            mem_result = check_memory_pressure()

            if mem_result.is_pressure:
                if mem_result.has_gpu:
                    logger.warning(
                        "系统内存使用率过高(%.1f%%, 阈值 %.1f%%)，但检测到 GPU 可用，优先使用 GPU 加载以减轻内存压力",
                        mem_result.percent,
                        mem_result.threshold,
                    )
                else:
                    logger.warning(
                        "系统内存使用率过高(%.1f%%, 阈值 %.1f%%)且无可用 GPU，尝试以保守参数加载本地模型",
                        mem_result.percent,
                        mem_result.threshold,
                    )

            if mem_result.is_pressure:
                self._last_llm_load_error = (
                    f"系统内存占用过高({mem_result.percent:.1f}%，阈值 {mem_result.threshold:.1f}%)，"
                    "已阻止加载本地模型，请释放内存后重试。"
                )
                logger.error("Python侧Llama模型加载失败：%s", self._last_llm_load_error)
                if not return_instance:
                    self.llm = None
                return None

            # 获取配置参数
            desired_n_ctx = int(
                config.get("max_context_size") or config.get("n_ctx") or 4096
            )
            desired_n_batch = int(config.get("max_batch_size", 1024) or 1024)
            desired_n_gpu_layers = int(config.get("n_gpu_layers", -1) or -1)

            # 检查是否强制使用CPU推理
            force_cpu_inference = False
            try:
                from config.integrated_config import get_settings as _get_settings

                settings = _get_settings()
                force_cpu_inference = bool(
                    getattr(settings.model, "force_cpu_inference", False)
                )
            except Exception:
                pass

            if force_cpu_inference:
                logger.info("检测到 force_cpu_inference=True，强制使用CPU推理模式")
                desired_n_gpu_layers = 0

            if self._python_force_cpu or bool(config.get("force_cpu")):
                desired_n_gpu_layers = 0

            # 检查是否跳过内存检查
            skip_memory_check = False
            try:
                from config.integrated_config import get_settings as _get_settings

                settings = _get_settings()
                skip_memory_check = bool(
                    getattr(settings.model, "skip_memory_check_on_llm_load", False)
                )
            except Exception:
                pass

            if mem_result.is_pressure and not skip_memory_check:
                if not mem_result.has_gpu:
                    desired_n_ctx = min(desired_n_ctx, 2048)
                    desired_n_batch = min(desired_n_batch, 256)
                    desired_n_gpu_layers = 0
                else:
                    desired_n_batch = min(desired_n_batch, 512)
            elif mem_result.is_pressure and skip_memory_check:
                logger.warning(
                    f"检测到内存压力({mem_result.percent:.1f}%)，但已配置跳过内存检查，"
                    "继续使用GPU推理。如果出现OOM，请降低内存占用或禁用 skip_memory_check_on_llm_load"
                )

            if mem_result.percent >= 90.0:
                desired_n_batch = min(desired_n_batch, 256)

            # 优化线程数
            cpu_count = os.cpu_count() or 4
            desired_n_threads = max(1, cpu_count - 2)

            flash_attn = bool(config.get("flash_attn", True))
            offload_kqv = bool(config.get("offload_kqv", True))
            desired_n_ubatch = int(
                config.get("n_ubatch", desired_n_batch) or desired_n_batch
            )

            # 获取use_mmap配置
            try:
                use_mmap = bool(config.get("use_mmap"))
                if use_mmap is None:
                    try:
                        from config.integrated_config import (
                            get_settings as _get_settings,
                        )

                        settings = _get_settings()
                        use_mmap = bool(getattr(settings.model, "use_mmap", False))
                    except Exception:
                        use_mmap = False
            except Exception:
                use_mmap = False

            ram_mirror_offload = False
            try:
                from config.integrated_config import get_settings as _get_settings

                settings = _get_settings()
                ram_mirror_offload = bool(
                    getattr(settings.model, "ram_mirror_offload", False)
                )
            except Exception:
                ram_mirror_offload = False

            # 动态KV Cache卸载
            vram_reserve_mb = 0
            tts_gpu_min_free_mb = 1200
            dynamic_kv_offload = True
            try:
                from config.integrated_config import get_settings as _get_settings

                settings = _get_settings()
                model_settings = getattr(settings, "model", None)
                if model_settings is not None:
                    vram_reserve_mb = int(
                        getattr(model_settings, "vram_reserve_mb", 0) or 0
                    )
                    tts_gpu_min_free_mb = int(
                        getattr(model_settings, "tts_gpu_min_free_mb", 1200) or 1200
                    )
                    dynamic_kv_offload = bool(
                        getattr(model_settings, "dynamic_kv_offload", True)
                    )
            except Exception:
                vram_reserve_mb = int(config.get("vram_reserve_mb", 0) or 0)
                tts_gpu_min_free_mb = int(
                    config.get("tts_gpu_min_free_mb", 1200) or 1200
                )
                dynamic_kv_offload = bool(config.get("dynamic_kv_offload", True))

            gpu_free_mb = self._get_cuda_free_mb_sync() if mem_result.has_gpu else None
            if (
                dynamic_kv_offload
                and mem_result.has_gpu
                and int(desired_n_gpu_layers) != 0
                and bool(offload_kqv)
                and isinstance(gpu_free_mb, int)
                and gpu_free_mb < max(int(vram_reserve_mb), int(tts_gpu_min_free_mb))
            ):
                offload_kqv = False
                logger.info(
                    "检测到显存余量不足(%sMB)，自动将 KV Cache 放到 CPU (offload_kqv=False)",
                    gpu_free_mb,
                )

            def _expand_gpu_layer_candidates(raw_value: int) -> list[int]:
                if raw_value == 0:
                    return [0]
                if raw_value < 0:
                    return [-1, 64, 48, 32, 24, 16, 8, 0]
                return [raw_value, max(raw_value // 2, 1), 0]

            # 生成候选配置
            candidates = []
            for layers in _expand_gpu_layer_candidates(desired_n_gpu_layers):
                candidates.append((desired_n_ctx, int(layers), desired_n_batch))
                if desired_n_ctx > 2048:
                    candidates.append((2048, int(layers), min(desired_n_batch, 256)))

            candidates.append((1024, 0, 128))  # 兜底

            logger.info("正在尝试加载 Llama 模型 (Python)...")
            tried = set()
            last_error = None

            for n_ctx, n_gpu_layers, n_batch in candidates:
                attempt_key = (n_ctx, n_gpu_layers, n_batch)
                if attempt_key in tried:
                    continue
                tried.add(attempt_key)

                try:
                    logger.info(
                        "尝试初始化 llama_cpp: n_ctx=%s, n_gpu_layers=%s, n_batch=%s",
                        n_ctx,
                        n_gpu_layers,
                        n_batch,
                    )

                    effective_use_mmap = resolve_use_mmap(
                        use_mmap, ram_mirror_offload, n_gpu_layers
                    )

                    base_kwargs: Dict[str, Any] = {
                        "model_path": model_path,
                        "n_ctx": int(n_ctx),
                        "n_gpu_layers": int(n_gpu_layers),
                        "n_batch": int(n_batch),
                        "n_ubatch": int(min(desired_n_ubatch, n_batch)),
                        "n_threads": int(desired_n_threads),
                        "verbose": False,
                        "offload_kqv": bool(offload_kqv),
                        "flash_attn": bool(flash_attn and int(n_gpu_layers) != 0),
                        "use_mmap": bool(effective_use_mmap),
                    }

                    init_kwargs = dict(base_kwargs)
                    new_inst = None
                    while True:
                        try:
                            new_inst = Llama(**init_kwargs)
                            break
                        except TypeError as te:
                            lowered_te = str(te).lower()
                            removed = False
                            for key in (
                                "flash_attn",
                                "offload_kqv",
                                "n_ubatch",
                                "n_threads",
                                "use_mmap",
                            ):
                                if (
                                    key in init_kwargs
                                    and "unexpected keyword" in lowered_te
                                    and key in lowered_te
                                ):
                                    init_kwargs.pop(key, None)
                                    removed = True
                                    break
                            if not removed:
                                raise

                    if not return_instance:
                        self.llm = new_inst

                    if isinstance(self._gpu_config, dict):
                        self._gpu_config["max_context_size"] = int(n_ctx)
                        self._gpu_config["n_gpu_layers"] = int(n_gpu_layers)
                        self._gpu_config["max_batch_size"] = int(n_batch)

                    try:
                        if int(n_gpu_layers) != 0:
                            self._prev_n_gpu_layers = int(n_gpu_layers)
                    except Exception:
                        pass

                    logger.info("Python Llama model loaded successfully.")
                    self._last_llm_use_mmap = bool(effective_use_mmap)
                    if not return_instance:
                        try:
                            from core.resource_manager import get_resource_manager

                            get_resource_manager().mark_model_loaded("llm_engine", True)
                        except Exception:
                            pass
                    return new_inst

                except Exception as e:
                    msg = str(e)
                    logger.warning("模型加载尝试失败 (%s): %s", attempt_key, e)
                    last_error = e
                    self._last_llm_load_error = msg

                    from ..utils.error_utils import is_cuda_backend_error, is_oom_error

                    if is_cuda_backend_error(msg) and int(n_gpu_layers) != 0:
                        logger.warning("检测到 CUDA 后端错误，切换到 CPU 模式")
                        self._python_force_cpu = True
                        if isinstance(self._gpu_config, dict):
                            self._gpu_config["n_gpu_layers"] = 0
                        break

                    if is_oom_error(msg):
                        continue

                    # 非资源类错误直接跳出
                    break

            self.llm = None
            if last_error:
                self._last_llm_load_error = str(last_error)
                logger.error("Failed to load Python Llama model: %s", last_error)
        except Exception as e:
            self._last_llm_load_error = str(e)
            logger.error(f"Failed to load Python Llama model: {e}")

        return None

    def _build_cpp_llm_config(self, config: Dict[str, Any]) -> Any:
        """构建C++ LLM配置（委托给CPPConfigBuilder）"""
        from ..client.cpp_config_builder import CPPConfigBuilder

        return CPPConfigBuilder.build_llm_config(config)
