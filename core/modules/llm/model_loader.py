"""
LLM模块模型加载器
负责GGUF和Transformers模型的加载逻辑
"""

import os
import time
import gc

try:
    import psutil
except Exception:
    psutil = None

try:
    from transformers.models.auto.modeling_auto import AutoModelForCausalLM
    from transformers.models.auto.tokenization_auto import AutoTokenizer
except ImportError:
    AutoModelForCausalLM = None
    AutoTokenizer = None

try:
    from llama_cpp import Llama
except ImportError:
    Llama = None

from core.utils.logger import get_logger
from .utils import get_torch, patch_llama_cpp_internals, resolve_use_mmap
from .error_handler import (
    is_oom_error,
    is_cuda_backend_error,
    is_invalid_vector_subscript_error,
    is_model_load_error,
    expand_gpu_layer_candidates,
    get_error_message,
)

logger = get_logger("LLM.MODEL_LOADER")


class ModelLoader:
    """模型加载器，负责加载GGUF和Transformers模型"""

    def __init__(self, module):
        """
        初始化模型加载器

        Args:
            module: 所属的LLMModule实例
        """
        self.module = module

    def _get_memory_block_threshold(self) -> float:
        """获取内存阻塞阈值"""
        value = None
        try:
            value = getattr(
                self.module.settings.immune, "llm_load_memory_block_threshold", None
            )
        except Exception:
            value = None

        if value is None:
            try:
                value = getattr(
                    self.module.settings.immune, "memory_emergency_threshold", 96.0
                )
            except Exception:
                value = 97.0

        try:
            return float(value)
        except Exception:
            return 97.0

    def _check_memory_pressure(self) -> tuple[bool, float]:
        """
        检查内存压力

        Returns:
            (是否有内存压力, 当前内存占用百分比)
        """
        try:
            if psutil is not None:
                mem_percent = float(psutil.virtual_memory().percent)
                mem_emergency = self._get_memory_block_threshold()
                return bool(mem_percent >= mem_emergency), mem_percent
        except Exception:
            pass
        return False, 0.0

    def _verify_gguf_header(self, path: str) -> tuple[bool, str]:
        """
        验证GGUF文件头

        Returns:
            (是否有效, 错误消息)
        """
        try:
            with open(path, "rb") as f:
                header = f.read(4)
            if header != b"GGUF":
                return False, get_error_message("invalid_gguf_header", f"{header}")
            return True, ""
        except Exception as e:
            return False, get_error_message("gguf_read_error", str(e))

    def _calculate_thread_count(self) -> int:
        """计算最佳线程数"""
        desired_n_threads = 0
        try:
            desired_n_threads = int(self.module.config.get("n_threads") or 0)
        except Exception:
            desired_n_threads = 0

        if desired_n_threads <= 0:
            try:
                cpu_count = int(os.cpu_count() or 0)
            except Exception:
                cpu_count = 0
            if cpu_count > 0:
                # 优化：物理核心数 - 2 是 CPU 推理的最佳平衡点
                desired_n_threads = max(1, cpu_count - 2)
            else:
                desired_n_threads = 4

        return desired_n_threads

    def _get_model_params(self) -> dict:
        """获取模型加载参数"""
        # flash_attn
        if (
            "flash_attn" in self.module.config
            and self.module.config.get("flash_attn") is not None
        ):
            flash_attn = bool(self.module.config.get("flash_attn"))
        else:
            flash_attn = bool(getattr(self.module.settings.model, "flash_attn", False))

        # offload_kqv
        if (
            "offload_kqv" in self.module.config
            and self.module.config.get("offload_kqv") is not None
        ):
            offload_kqv = bool(self.module.config.get("offload_kqv"))
        else:
            offload_kqv = bool(
                getattr(self.module.settings.model, "offload_kqv", False)
            )

        # n_gpu_layers
        n_gpu_layers = self.module.config.get("n_gpu_layers")
        if n_gpu_layers is None:
            n_gpu_layers = getattr(self.module.settings.model, "n_gpu_layers", -1)

        # 检查是否强制使用CPU推理
        force_cpu = False
        try:
            force_cpu = bool(
                getattr(self.module.settings.model, "force_cpu_inference", False)
            )
        except Exception:
            pass

        if force_cpu:
            logger.info("检测到 force_cpu_inference=True，强制使用CPU推理模式")
            n_gpu_layers = 0
            self.module.config["n_gpu_layers"] = 0

        # n_ctx
        n_ctx = (
            self.module.config.get("n_ctx")
            or getattr(self.module.settings.model, "n_ctx", None)
            or 4096
        )
        if n_ctx > 8192:
            logger.warning(f"Detected n_ctx={n_ctx}, capping to 8192 to prevent OOM")
            n_ctx = 8192

        # n_batch
        n_batch = self.module.config.get("n_batch")
        if n_batch is None:
            n_batch = getattr(self.module.settings.model, "n_batch", 512)
            if n_batch is None or n_batch <= 0:
                n_batch = min(512, int(n_ctx))
        else:
            n_batch = int(n_batch)

        if n_batch > n_ctx:
            n_batch = n_ctx

        return {
            "flash_attn": flash_attn,
            "offload_kqv": offload_kqv,
            "n_gpu_layers": n_gpu_layers,
            "n_ctx": n_ctx,
            "n_batch": n_batch,
            "force_cpu": force_cpu,
        }

    def load_sync(self) -> bool:
        """
        同步加载模型

        Returns:
            是否加载成功
        """
        try:
            self.module._last_load_error = None
            logger.info(f"正在加载文本模型: {self.module.text_model_path}")
            self.module.is_gguf = bool(
                self.module.text_model_path
                and str(self.module.text_model_path).lower().endswith(".gguf")
            )

            if not os.path.exists(self.module.text_model_path):
                self.module._last_load_error = get_error_message(
                    "model_not_found", self.module.text_model_path
                )
                logger.error(self.module._last_load_error)
                return False

            # GGUF模型加载
            if self.module.is_gguf:
                return self._load_gguf_model()

            # Transformers模型加载
            return self._load_transformers_model()

        except Exception as e:
            msg = str(e)
            if is_invalid_vector_subscript_error(msg):
                self.module._last_load_error = get_error_message(
                    "invalid_vector_subscript", msg
                )
            else:
                self.module._last_load_error = get_error_message("load_failed", msg)
            logger.error(self.module._last_load_error)
            return False

    def _load_gguf_model(self) -> bool:
        """加载GGUF模型"""
        if Llama is None:
            logger.error(get_error_message("llama_cpp_not_installed"))
            return False

        patch_llama_cpp_internals()

        # 检查内存压力
        mem_pressure, mem_percent = self._check_memory_pressure()
        mem_emergency = self._get_memory_block_threshold()

        if mem_pressure:
            self.module._last_load_error = get_error_message(
                "memory_pressure", f"{mem_percent:.1f}%，阈值 {mem_emergency:.1f}%"
            )
            logger.error(self.module._last_load_error)
            return False

        # 验证文件头
        valid, error_msg = self._verify_gguf_header(self.module.text_model_path)
        if not valid:
            self.module._last_load_error = error_msg
            logger.error(self.module._last_load_error)
            return False

        logger.info("检测到GGUF模型，使用llama_cpp加载...")
        self.module.is_gguf = True

        # 获取模型参数
        params = self._get_model_params()
        flash_attn = params["flash_attn"]
        offload_kqv = params["offload_kqv"]
        n_gpu_layers = params["n_gpu_layers"]
        n_ctx = params["n_ctx"]
        n_batch = params["n_batch"]

        # 内存压力下降低配置
        if mem_pressure:
            n_ctx = min(int(n_ctx), 2048)
            n_batch = min(int(n_batch), 128)
            n_batch = min(int(n_batch), 256)  # 有GPU时限制batch以节省显存

        # 计算线程数
        desired_n_threads = self._calculate_thread_count()

        # 构建候选配置列表
        candidates = []
        gpu_layer_candidates = expand_gpu_layer_candidates(int(n_gpu_layers))
        for layers in gpu_layer_candidates:
            candidates.append((int(n_ctx), int(layers), int(n_batch)))
            if int(n_ctx) > 2048:
                candidates.append((2048, int(layers), min(int(n_batch), 256)))

        candidates.append((min(int(n_ctx), 2048), 0, 128))

        logger.info(
            f"Initializing Llama model with n_ctx={n_ctx}, n_batch={n_batch}, n_gpu_layers={n_gpu_layers}"
        )
        try:
            import llama_cpp

            logger.info(
                f"llama-cpp-python version: {llama_cpp.__version__}, file: {llama_cpp.__file__}"
            )
        except Exception as version_err:
            logger.warning(f"无法获取 llama-cpp-python 版本信息: {version_err}")

        load_start_time = time.time()
        last_error = None
        tried = set()
        force_cpu_only = False
        loaded_ok = False

        # 确定use_mmap候选值
        use_mmap_from_config = None
        try:
            use_mmap_from_config = getattr(self.module.settings.model, "use_mmap", None)
        except Exception:
            pass

        ram_mirror_offload = False
        try:
            ram_mirror_offload = bool(
                getattr(self.module.settings.model, "ram_mirror_offload", False)
            )
        except Exception:
            ram_mirror_offload = False

        if use_mmap_from_config is not None:
            use_mmap_candidates = (bool(use_mmap_from_config),)
        else:
            use_mmap_candidates = (True,)
            try:
                if psutil is not None and float(psutil.virtual_memory().percent) < 90.0:
                    use_mmap_candidates = (True, False)
            except Exception:
                pass

        # 尝试加载模型
        for try_n_ctx, try_n_gpu_layers, try_n_batch in candidates:
            if force_cpu_only and int(try_n_gpu_layers) != 0:
                continue

            for use_mmap in use_mmap_candidates:
                effective_use_mmap = resolve_use_mmap(
                    use_mmap, ram_mirror_offload, try_n_gpu_layers
                )
                key = (
                    int(try_n_ctx),
                    int(try_n_gpu_layers),
                    int(try_n_batch),
                    bool(effective_use_mmap),
                )
                if key in tried:
                    continue
                tried.add(key)

                try:
                    logger.info(
                        f"Trying GGUF load: n_ctx={try_n_ctx}, n_batch={try_n_batch}, "
                        f"n_gpu_layers={try_n_gpu_layers}, use_mmap={effective_use_mmap}"
                    )

                    init_kwargs = {
                        "model_path": self.module.text_model_path,
                        "n_ctx": int(try_n_ctx),
                        "n_gpu_layers": int(try_n_gpu_layers),
                        "n_batch": int(try_n_batch),
                        "n_ubatch": int(try_n_batch),
                        "n_threads": int(desired_n_threads),
                        "n_threads_batch": int(desired_n_threads),
                        "use_mmap": bool(effective_use_mmap),
                        "use_mlock": False,
                        "offload_kqv": bool(offload_kqv),
                        "flash_attn": bool(flash_attn and int(try_n_gpu_layers) != 0),
                        "verbose": True,
                    }

                    # 尝试初始化，处理不支持的参数
                    while True:
                        try:
                            logger.info(
                                f"Starting Llama initialization with kwargs: "
                                f"n_ctx={init_kwargs.get('n_ctx')}, n_gpu_layers={init_kwargs.get('n_gpu_layers')}"
                            )
                            load_start = time.time()
                            self.module.llama_model = Llama(**init_kwargs)
                            load_time = time.time() - load_start
                            logger.info(f"Llama模型初始化完成，耗时: {load_time:.2f}秒")

                            # 验证GPU层数
                            if int(try_n_gpu_layers) != 0:
                                try:
                                    actual_gpu_layers = int(
                                        self.module.llama_model.n_gpu_layers()
                                    )
                                    logger.info(
                                        f"模型GPU层数验证 - 配置: {try_n_gpu_layers}, 实际: {actual_gpu_layers}"
                                    )
                                    if actual_gpu_layers == 0:
                                        logger.error(
                                            "严重问题：配置了GPU推理但模型实际未加载到GPU！"
                                        )
                                except Exception as verify_err:
                                    logger.warning(f"无法验证GPU层数: {verify_err}")
                            break

                        except TypeError as te:
                            lowered_te = str(te).lower()
                            removed = False
                            for key in (
                                "flash_attn",
                                "offload_kqv",
                                "n_threads_batch",
                                "n_ubatch",
                                "n_threads",
                                "n_batch",
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

                    # 保存成功配置
                    self.module.config["n_ctx"] = int(try_n_ctx)
                    self.module.config["n_batch"] = int(try_n_batch)
                    self.module.config["n_gpu_layers"] = int(try_n_gpu_layers)
                    loaded_ok = True
                    break

                except Exception as e:
                    msg = str(e)

                    if is_invalid_vector_subscript_error(msg):
                        self.module._last_load_error = get_error_message(
                            "invalid_vector_subscript", str(e)
                        )
                        logger.error(self.module._last_load_error)
                        return False

                    last_error = e

                    # 清理资源
                    try:
                        self.module.llama_model = None
                    except Exception:
                        pass

                    torch = get_torch()
                    if torch and torch.cuda.is_available():
                        try:
                            torch.cuda.empty_cache()
                            torch.cuda.ipc_collect()
                        except Exception:
                            pass
                    gc.collect()

                    # CUDA错误时强制CPU
                    if int(try_n_gpu_layers) != 0 and is_cuda_backend_error(msg):
                        force_cpu_only = True
                        self.module.config["n_gpu_layers"] = 0
                        break

                    if is_oom_error(msg):
                        continue

                    if is_model_load_error(msg):
                        logger.warning(f"GGUF模型加载失败，继续尝试其他参数: {e}")
                        continue

            if loaded_ok:
                break

        if not loaded_ok:
            self.module._last_load_error = get_error_message(
                "gguf_load_failed", str(last_error)
            )
            logger.error(self.module._last_load_error)
            return False

        load_cost = time.time() - load_start_time
        logger.info(f"GGUF模型加载完成，耗时: {load_cost:.2f}秒")

        # GPU健康检查
        cfg_layers = self.module.config.get("n_gpu_layers", -1)
        if cfg_layers is None:
            cfg_layers = getattr(self.module.settings.model, "n_gpu_layers", -1)

        if int(cfg_layers) != 0:
            logger.info("执行GPU健康检查...")
            try:
                from .gpu_manager import GPUManager

                gpu_manager = GPUManager(self.module)
                health_check_passed = gpu_manager.health_check()
                if not health_check_passed:
                    logger.warning("GPU健康检查失败，将回退到CPU模式")
                    self.module.config["n_gpu_layers"] = 0
                    # 重新加载模型到CPU
                    try:
                        self.module.llama_model = None
                        gc.collect()
                        torch = get_torch()
                        if torch and torch.cuda.is_available():
                            torch.cuda.empty_cache()
                    except Exception:
                        pass

                    self.module.config["n_gpu_layers"] = 0
                    if not self.load_sync():
                        logger.error("CPU模式重新加载失败")
                        return False
                    logger.info("已成功回退到CPU模式")
            except Exception as health_err:
                logger.warning(f"GPU健康检查异常: {health_err}")

        self.module.is_loaded = True
        logger.info("GGUF模型加载成功")
        return True

    def _load_transformers_model(self) -> bool:
        """加载Transformers模型"""
        if AutoModelForCausalLM is None:
            logger.error(get_error_message("transformers_not_installed"))
            return False

        torch = get_torch()
        if torch is None:
            logger.error(get_error_message("torch_not_installed"))
            return False

        model_kwargs = {
            "low_cpu_mem_usage": True,
            "local_files_only": True,
            "torch_dtype": torch.float32,
        }

        self.module.is_gguf = False

        self.module.tokenizer = AutoTokenizer.from_pretrained(
            self.module.text_model_path, local_files_only=True
        )
        self.module.model = AutoModelForCausalLM.from_pretrained(
            self.module.text_model_path, **model_kwargs
        )
        self.module.model = self.module.model.to("cpu")

        self.module.is_loaded = True
        logger.info("文本模型加载成功")
        return True
