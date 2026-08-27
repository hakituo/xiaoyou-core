"""
模型管理器
使用单例模式集中管理所有模型的加载、卸载和检查
防止重复加载和内存溢出
增强支持量化加载选项和显存/资源检测
"""

import gc
import os
import threading
import time
from typing import Dict, List, Any, Tuple, Optional

try:
    import torch
except Exception:
    torch = None
import psutil

from config.debug_config import is_debug_enabled
from core.contracts import DeviceType, ModelRuntimeState
from core.utils.logger import get_logger

try:
    from watchdog.observers import Observer as _Observer
    from watchdog.events import FileSystemEventHandler as _FSEH
except Exception:
    _Observer = None
    _FSEH = object

logger = get_logger(__name__)


class ModelInfo:
    """模型信息类，存储每个模型的元数据和状态"""

    def __init__(self, model_name: str, model_type: str, model_path: str):
        self.model_name = model_name
        self.model_type = model_type
        self.model_path = model_path
        self.load_time: Optional[float] = None
        self.last_used_time: Optional[float] = None
        self.is_loaded: bool = False
        self.is_offloaded: bool = False
        self.model_obj: Any = None
        self.tokenizer_obj: Any = None
        self.quantized: bool = False
        self.quantization_config: Optional[Dict] = None
        self.device: Optional[str] = None
        self.memory_used: Optional[float] = None
        self.torch_dtype: Any = None
        self.load_options: Dict = {}

    @property
    def runtime_state(self) -> ModelRuntimeState:
        if self.is_loaded:
            if self.is_offloaded:
                return ModelRuntimeState.OFFLOADED
            return ModelRuntimeState.LOADED
        return ModelRuntimeState.UNLOADED

    @property
    def device_type(self) -> DeviceType:
        d = str(self.device or "").strip().lower()
        if d in {"gpu", "cuda"}:
            return DeviceType.GPU
        if d in {"cpu"}:
            return DeviceType.CPU
        return DeviceType.UNKNOWN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.model_name,
            "name": self.model_name,
            "type": self.model_type,
            "path": self.model_path,
            "state": self.runtime_state.value,
            "device": self.device_type.value,
            "is_loaded": self.is_loaded,
            "quantized": self.quantized,
            "load_time": self.load_time,
            "last_used_time": self.last_used_time,
        }

    def to_contract_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_name,
            "model_type": self.model_type,
            "model_path": self.model_path,
            "state": self.runtime_state.value,
            "device": self.device_type.value,
            "quantized": bool(self.quantized),
            "load_time": float(self.load_time or 0.0) if self.load_time else None,
            "last_used_time": float(self.last_used_time or 0.0)
            if self.last_used_time
            else None,
        }


class ModelManager:
    """模型管理器（单例模式），负责所有模型的生命周期管理"""

    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ModelManager, cls).__new__(cls)
            return cls._instance

    def __init__(self):
        if ModelManager._initialized:
            return
        ModelManager._initialized = True

        self._models: Dict[str, ModelInfo] = {}
        self._registered_models: Dict[str, Dict] = {}
        self._processors: Dict[str, Any] = {}
        self._model_locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.RLock()
        self._max_models = int(os.environ.get("MAX_MODELS", 5))
        self._memory_threshold = float(os.environ.get("MODEL_MEMORY_THRESHOLD", 0.7))
        self._gpu_memory_threshold = float(os.environ.get("GPU_MEMORY_THRESHOLD", 0.8))
        self._pinned_models = set()

        self.system_resources = self._detect_hardware_resources()
        logger.info(
            f"初始化模型管理器，最大模型数: {self._max_models}, 内存阈值: {self._memory_threshold}"
        )
        logger.info(f"系统资源: {self.system_resources}")

        self.scan_models()

    def scan_models(self):
        """扫描本地模型"""
        try:
            root_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            models_dir = os.path.join(root_dir, "models")

            logger.info(f"正在扫描模型目录: {models_dir}")

            if os.path.exists(models_dir):
                self._scan_llm_models(models_dir)
                self._scan_image_models(models_dir)

            self._register_cloud_clients_from_llm_module()

            env_path = os.environ.get("XIAOYOU_TEXT_MODEL_PATH")
            if env_path and os.path.exists(env_path):
                if os.path.isfile(env_path):
                    name = os.path.splitext(os.path.basename(env_path))[0]
                else:
                    name = os.path.basename(env_path)

                if name not in self._models:
                    self.register_model(name, "llm", env_path)

        except Exception as e:
            logger.error(f"扫描模型失败: {e}")

    def _scan_llm_models(self, models_dir: str):
        """扫描 LLM 模型目录"""
        llm_dir = os.path.join(models_dir, "llm")
        if not os.path.exists(llm_dir):
            return

        for name in os.listdir(llm_dir):
            path = os.path.join(llm_dir, name)
            if os.path.isfile(path) and name.endswith(".gguf"):
                model_name = os.path.splitext(name)[0]
                if model_name not in self._models:
                    logger.info(f"发现本地 LLM 模型: {model_name}")
                    self.register_model(model_name, "llm", path)
            elif os.path.isdir(path) and os.path.exists(
                os.path.join(path, "config.json")
            ):
                if name not in self._models:
                    logger.info(f"发现本地 LLM 模型: {name}")
                    self.register_model(name, "llm", path)

    def _scan_image_models(self, models_dir: str):
        """扫描图像模型目录"""
        img_dir = None
        for dirname in ("Image", "image", "img"):
            candidate = os.path.join(models_dir, dirname)
            if os.path.exists(candidate):
                img_dir = candidate
                break

        if not img_dir:
            return

        ckpt_dir = os.path.join(img_dir, "check_point")
        if os.path.exists(ckpt_dir):
            for name in os.listdir(ckpt_dir):
                path = os.path.join(ckpt_dir, name)
                if os.path.isfile(path) and (
                    name.endswith(".safetensors") or name.endswith(".ckpt")
                ):
                    model_name = os.path.splitext(name)[0]
                    if model_name not in self._models:
                        logger.info(f"发现本地图像模型: {model_name}")
                        self.register_model(model_name, "image_gen", path)

        lora_dir = os.path.join(img_dir, "lora")
        if os.path.exists(lora_dir):
            for name in os.listdir(lora_dir):
                path = os.path.join(lora_dir, name)
                if os.path.isfile(path) and name.endswith(".safetensors"):
                    model_name = os.path.splitext(name)[0]
                    if model_name not in self._models:
                        logger.info(f"发现本地 LORA 模型: {model_name}")
                        self.register_model(model_name, "lora", path)

    def _register_cloud_clients_from_llm_module(self):
        """从 LLM 模块获取已配置的云端客户端并注册模型

        支持两种注册方式：
        1. 传统方式：从环境变量读取API key，注册到 cloud:provider:model
        2. 多API key方式：从 settings.model.cloud_provider_keys 读取配置，注册到 cloud:provider:key_alias:model
        """
        try:
            debug_enabled = is_debug_enabled("model_manager")
            cloud_models: List[Dict[str, str]] = []
            queued_model_names = set(self._models)

            def queue_cloud_model(
                name: str,
                provider: str,
                model: str,
                key_alias: str = "default",
            ) -> None:
                """将云端模型加入候选队列，在注册前统一去重。"""
                if name in queued_model_names:
                    if debug_enabled:
                        logger.info("模型候选已存在，跳过重复来源: %s", name)
                    return
                queued_model_names.add(name)
                cloud_models.append(
                    {
                        "name": name,
                        "provider": provider,
                        "model": model,
                        "key_alias": key_alias,
                    }
                )

            if debug_enabled:
                env_names = (
                    "DEEPSEEK_API_KEY",
                    "SILICONFLOW_API_KEY",
                    "ARK_API_KEY",
                    "MINIMAX_API_KEY",
                    "AVELINE_API_KEY",
                )
                env_status = {name: bool(os.getenv(name)) for name in env_names}
                logger.info("模型注册环境变量状态（仅显示是否存在）: %s", env_status)

            # 方式1：传统方式（向后兼容）
            if os.getenv("DEEPSEEK_API_KEY"):
                if debug_enabled:
                    logger.info("加入 DeepSeek 兼容模型候选")
                queue_cloud_model("deepseek-v4-flash", "deepseek", "deepseek-v4-flash")
                queue_cloud_model("deepseek-v4-pro", "deepseek", "deepseek-v4-pro")

            if os.getenv("SILICONFLOW_API_KEY"):
                if debug_enabled:
                    logger.info("加入 SiliconFlow 兼容模型候选")
                queue_cloud_model(
                    "Kimi-K2.6", "siliconflow", "Pro/moonshotai/Kimi-K2.6"
                )
                queue_cloud_model(
                    "DeepSeek-V3.2(sf)",
                    "siliconflow",
                    "Pro/deepseek-ai/DeepSeek-V3.2",
                )
                queue_cloud_model(
                    "MiniMax-M2.5(sf)",
                    "siliconflow",
                    "MiniMaxAI/MiniMax-M2.5",
                )
                queue_cloud_model(
                    "Qwen3-VL-32B",
                    "siliconflow",
                    "Qwen/Qwen3-VL-32B-Instruct",
                )

            if os.getenv("ARK_API_KEY"):
                if debug_enabled:
                    logger.info("加入 Ark 兼容模型候选")
                queue_cloud_model(
                    "Doubao-Seed-2.0", "ark", "doubao-seed-2-0-lite-260215"
                )

            if os.getenv("AVELINE_API_KEY"):
                if debug_enabled:
                    logger.info("加入 Aveline 兼容模型候选")
                aveline_models_str = os.getenv("AVELINE_MODEL") or "nalang-xl-0826-16k"
                for aveline_model in [
                    model_name.strip()
                    for model_name in aveline_models_str.split(",")
                    if model_name.strip()
                ]:
                    queue_cloud_model(aveline_model, "aveline", aveline_model)

            if os.getenv("MINIMAX_API_KEY"):
                if debug_enabled:
                    logger.info("加入 MiniMax 兼容模型候选")
                queue_cloud_model("MiniMax-M2.5", "minimax", "MiniMax-M2.5")
                queue_cloud_model("MiniMax-M2-her", "minimax", "M2-her")

            # 方式2：多API key方式（新功能）
            try:
                from config.integrated_config import get_settings

                settings = get_settings()
                cloud_provider_keys = getattr(settings.model, "cloud_provider_keys", {})

                if debug_enabled:
                    safe_config_summary = {
                        provider: {
                            key_alias: list(getattr(key_config, "models", []) or [])
                            for key_alias, key_config in key_configs.items()
                        }
                        for provider, key_configs in cloud_provider_keys.items()
                    }
                    logger.info(
                        "多 API Key 模型配置（已脱敏）: %s", safe_config_summary
                    )

                if cloud_provider_keys:
                    if debug_enabled:
                        logger.info(
                            "发现多 API Key 供应商: %s",
                            list(cloud_provider_keys.keys()),
                        )

                    for provider, key_configs in cloud_provider_keys.items():
                        for key_alias, key_config in key_configs.items():
                            # 为每个key的每个模型注册
                            for model_name in key_config.models:
                                # 生成显示名称（包含key别名）
                                if key_alias == "default":
                                    display_name = model_name
                                else:
                                    display_name = f"{model_name} ({key_alias})"

                                queue_cloud_model(
                                    display_name,
                                    provider,
                                    model_name,
                                    key_alias,
                                )
            except Exception as e:
                logger.warning(f"加载多API key配置失败: {e}")

            # 注册所有模型
            if debug_enabled:
                logger.info("准备注册 %d 个云端模型", len(cloud_models))
            for cm in cloud_models:
                model_name = cm["name"]
                provider = cm["provider"]
                model = cm["model"]
                key_alias = cm.get("key_alias", "default")

                if model_name not in self._models:
                    # 生成模型路径
                    if key_alias == "default":
                        # 传统格式：cloud:provider:model
                        model_path = f"cloud:{provider}:{model}"
                    else:
                        # 新格式：cloud:provider:key_alias:model
                        model_path = f"cloud:{provider}:{key_alias}:{model}"

                    if debug_enabled:
                        logger.info(
                            "注册云端模型: %s (path=%s)", model_name, model_path
                        )
                    self.register_model(model_name, "llm", model_path)
                else:
                    if debug_enabled:
                        logger.info("模型 %s 已存在，跳过注册", model_name)

        except Exception as e:
            logger.error(f"从 LLM 模块注册云端模型失败: {e}")

    def _detect_hardware_resources(self) -> Dict[str, Any]:
        """检测硬件资源（仅关注 CPU/GPU/内存等硬件指标）"""
        cpu_usage = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()

        gpu_usage = 0
        gpu_info = {}
        is_jetson = False

        try:
            with open("/proc/device-tree/model", "r") as f:
                model_str = f.read().lower()
                if "nvidia" in model_str and (
                    "jetson" in model_str or "orin" in model_str or "xavier" in model_str
                ):
                    is_jetson = True
        except (FileNotFoundError, OSError):
            pass

        has_gpu = bool(torch and torch.cuda.is_available())
        if has_gpu:
            try:
                props = torch.cuda.get_device_properties(0)
                gpu_info = {
                    "name": props.name,
                    "total_memory_gb": props.total_memory / (1024**3),
                    "is_jetson": is_jetson,
                }

                try:
                    import pynvml

                    pynvml.nvmlInit()
                    handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    gpu_usage = util.gpu
                    pynvml.nvmlShutdown()
                except (ImportError, Exception):
                    pass
            except Exception as e:
                logger.warning(f"获取GPU信息失败: {e}")

        return {
            "cpu_count": psutil.cpu_count(),
            "cpu_usage": cpu_usage,
            "memory_total_gb": memory.total / (1024**3),
            "memory_available_gb": memory.available / (1024**3),
            "memory_usage": memory.percent,
            "gpu_usage": gpu_usage,
            "has_gpu": has_gpu,
            "gpu": gpu_info,
        }

    def _get_model_stats(self) -> Dict[str, Any]:
        """获取模型统计信息（与硬件资源分离）"""
        models_total = 0
        models_loaded = 0
        image_models_total = 0
        active_model = "None"
        voices_total = 0

        try:
            try:
                from core.voice import _tts_manager_instance

                if (
                    _tts_manager_instance
                    and hasattr(_tts_manager_instance, "engine")
                    and _tts_manager_instance.engine
                ):
                    voices_total = 4
                else:
                    voices_total = 4
            except Exception:
                voices_total = 0

            with self._global_lock:
                all_models = list(self._models.values())
                llm_models = [
                    m for m in all_models if m.model_type in ["llm", "dashscope", "siliconflow"]
                ]
                image_models = [
                    m for m in all_models if m.model_type in ["image_gen", "lora"]
                ]
                loaded_llms = [m for m in llm_models if m.is_loaded]

                models_total = len(llm_models)
                models_loaded = len(loaded_llms)
                image_models_total = len(image_models)

                if loaded_llms:
                    active_model = loaded_llms[0].model_name

                if active_model == "None" or models_loaded == 0:
                    active_model, models_loaded = self._detect_active_llm(
                        active_model, models_loaded
                    )
        except Exception as e:
            logger.warning(f"获取模型统计信息失败: {e}")

        return {
            "models_total": models_total,
            "models_loaded": models_loaded,
            "active_model": active_model,
            "image_models_total": image_models_total,
            "voices_total": voices_total,
        }

    def _detect_active_llm(self, active_model: str, models_loaded: int) -> Tuple[str, int]:
        """从 C++ 调度器或 LLM 模块检测活跃模型"""
        try:
            from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

            cpp_engine = CPPSchedulerEngine()
            if cpp_engine.enabled:
                if (
                    getattr(cpp_engine, "_gpu_worker_ready", False)
                    or cpp_engine.llm is not None
                ):
                    models_loaded = max(models_loaded, 1)
                    if hasattr(cpp_engine, "_gpu_config") and cpp_engine._gpu_config:
                        active_model = cpp_engine._gpu_config.get("model_path") or active_model

            from core.llm import get_llm_module

            llm = get_llm_module()
            if llm:
                status = llm.get_status()
                if status.get("type") == "hybrid":
                    for sub_key in ("local", "cloud"):
                        sub_status = status.get(sub_key, {})
                        init_state = sub_status.get("init_state") or sub_status.get("status") or ""
                        if str(init_state) == "initialized":
                            models_loaded = max(models_loaded, 1)
                            active_model = sub_status.get("model_path") or active_model
                            break
                else:
                    init_state = status.get("init_state") or status.get("status") or ""
                    if str(init_state) == "initialized":
                        models_loaded = max(models_loaded, 1)
                        active_model = status.get("model_path") or active_model

                if hasattr(llm, "get_current_model_name"):
                    current_name = llm.get_current_model_name()
                    if current_name and current_name != "unknown":
                        active_model = current_name
                        models_loaded = max(models_loaded, 1)
        except Exception:
            pass

        return active_model, models_loaded

    def detect_system_resources(self) -> Dict[str, Any]:
        """检测系统资源（硬件 + 模型统计合并）"""
        resources = self._detect_hardware_resources()
        model_stats = self._get_model_stats()
        resources.update(model_stats)
        return resources

    def register_model(self, model_name: str, model_type: str, model_path: str):
        """注册模型"""
        with self._global_lock:
            if model_name not in self._models:
                self._models[model_name] = ModelInfo(model_name, model_type, model_path)
                if model_path.endswith(".gguf"):
                    self._models[model_name].quantized = True
                if is_debug_enabled("model_manager"):
                    logger.info("模型已注册: %s (%s)", model_name, model_type)

    def _get_model_lock(self, model_name: str) -> threading.Lock:
        """获取指定模型的独立加载锁（调用方需持有 _global_lock）。

        每个模型有独立的锁，避免不同模型加载时互相阻塞，
        同时保证同一模型的并发加载请求会被串行化。
        """
        if model_name not in self._model_locks:
            self._model_locks[model_name] = threading.Lock()
        return self._model_locks[model_name]

    def load_model(self, model_name: str, **kwargs) -> Any:
        """加载模型。

        使用双重检查锁定（double-checked locking）消除 TOCTOU 竞态：
        1. 在全局锁内快速检查是否已加载（命中即返回）
        2. 取出该模型的独立锁，释放全局锁
        3. 在模型锁内再次检查是否已加载（防止等待期间已被其他线程加载）
        4. 真正执行加载并在全局锁内更新状态
        这样既能避免同一模型被并发加载两次，又不会因为加载耗时长而阻塞其他模型操作。
        """
        # 第一次检查：在全局锁内确认状态并取出模型锁
        with self._global_lock:
            if model_name not in self._models:
                raise ValueError(f"模型未注册: {model_name}")

            model_info = self._models[model_name]

            if model_info.is_loaded and model_info.is_offloaded:
                logger.info(f"正在将 Offloaded 模型 {model_name} 移回 CPU...")
                try:
                    device = "cpu"
                    if hasattr(model_info.model_obj, "to"):
                        model_info.model_obj.to(device)
                        model_info.is_offloaded = False
                        model_info.last_used_time = time.time()
                        logger.info(f"模型 {model_name} 已成功移回 {device}")
                        return model_info.model_obj
                except Exception as e:
                    logger.error(f"将模型 {model_name} 移回 CPU 失败: {e}，将重新加载")
                    self.unload_model(model_name)

            if model_info.is_loaded:
                model_info.last_used_time = time.time()
                return model_info.model_obj

            # 取出该模型专属的加载锁（需在全局锁内创建以保证唯一性）
            model_lock = self._get_model_lock(model_name)

        # 第二次检查：在模型锁内再次确认，避免等待期间被其他线程加载
        with model_lock:
            with self._global_lock:
                if model_info.is_loaded and model_info.is_offloaded:
                    # 等待期间被其他流程 offload，按原逻辑移回 CPU
                    logger.info(f"正在将 Offloaded 模型 {model_name} 移回 CPU...")
                    try:
                        device = "cpu"
                        if hasattr(model_info.model_obj, "to"):
                            model_info.model_obj.to(device)
                            model_info.is_offloaded = False
                            model_info.last_used_time = time.time()
                            logger.info(f"模型 {model_name} 已成功移回 {device}")
                            return model_info.model_obj
                    except Exception as e:
                        logger.error(f"将模型 {model_name} 移回 CPU 失败: {e}，将重新加载")
                        self.unload_model(model_name)

                if model_info.is_loaded:
                    # 等待期间已被其他线程加载完成，直接复用
                    model_info.last_used_time = time.time()
                    return model_info.model_obj

            logger.info(f"正在加载模型: {model_name}")
            try:
                model, tokenizer = self._load_model_by_type(model_name, **kwargs)
                with self._global_lock:
                    model_info.model_obj = model
                    model_info.tokenizer_obj = tokenizer
                    model_info.is_loaded = True
                    model_info.load_time = time.time()
                    model_info.last_used_time = time.time()
                logger.info(f"模型加载成功: {model_name}")
                return model
            except Exception as e:
                logger.error(f"加载模型失败 {model_name}: {e}")
                raise

    def unload_model(self, model_name: str):
        """卸载模型"""
        with self._global_lock:
            if model_name in self._models:
                model_info = self._models[model_name]
                if model_info.is_loaded:
                    model_info.model_obj = None
                    model_info.tokenizer_obj = None
                    model_info.is_loaded = False
                    model_info.is_offloaded = False
                    gc.collect()
                    if torch and torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    logger.info(f"模型已卸载: {model_name}")

    def offload_model(self, model_name: str):
        """将模型移动到 CPU (Offload)"""
        with self._global_lock:
            if model_name in self._models:
                model_info = self._models[model_name]
                if model_info.is_loaded and not model_info.is_offloaded:
                    if model_info.model_obj is not None:
                        logger.info(f"正在 Offload 模型到 CPU: {model_name}")
                        try:
                            if hasattr(model_info.model_obj, "to"):
                                model_info.model_obj.to("cpu")
                                model_info.is_offloaded = True
                                if torch and torch.cuda.is_available():
                                    torch.cuda.empty_cache()
                                logger.info(f"模型已 Offload 到 CPU: {model_name}")
                            else:
                                logger.warning(
                                    f"模型 {model_name} 不支持 .to('cpu')，执行卸载"
                                )
                                self.unload_model(model_name)
                        except Exception as e:
                            logger.error(f"Offload 模型 {model_name} 失败: {e}")
                            self.unload_model(model_name)

    def get_loaded_models(self) -> List[str]:
        """获取已加载的模型列表"""
        return [name for name, info in self._models.items() if info.is_loaded]

    def list_models(self, model_type: str = None) -> List[Dict[str, Any]]:
        """获取所有注册的模型列表

        Args:
            model_type: 可选，按模型类型筛选
        """
        with self._global_lock:
            result = []
            for info in self._models.values():
                if model_type and info.model_type != model_type:
                    continue
                result.append(info.to_dict())
            
            # 调试日志(降为 debug 级别,避免每次 list_models 都刷屏)
            logger.debug(f"list_models(model_type={model_type}): 共 {len(result)} 个模型")
            if model_type == "llm":
                logger.debug(f"所有注册的模型: {list(self._models.keys())}")
                llm_models = [name for name, info in self._models.items() if info.model_type == "llm"]
                logger.debug(f"LLM类型模型: {llm_models}")
            
            return result

    def _load_model_by_type(self, model_name: str, **kwargs):
        """根据模型类型加载模型"""
        model_info = self._models[model_name]
        model_type = model_info.model_type
        model_path = model_info.model_path

        if model_type == "llm":
            return self._load_transformers_model(
                model_path, kwargs, "AutoModelForCausalLM"
            )
        elif model_type in ("vision", "vl"):
            return self._load_transformers_model(
                model_path, kwargs, "AutoModelForVision2Seq"
            )
        elif model_type == "image_gen":
            return self._load_image_gen_model(model_path, kwargs)
        else:
            raise ValueError(f"不支持的模型类型: {model_type}")

    def _load_transformers_model(
        self, model_path: str, kwargs: Dict, model_class_name: str
    ) -> Tuple[Any, Any]:
        """通用 Transformers 模型加载（LLM 和 Vision 共用）"""
        # 直接从子模块导入，绕过 transformers 5.x _LazyModule 延迟加载的线程安全问题
        from transformers.models.auto.tokenization_auto import AutoTokenizer

        import importlib
        model_module = importlib.import_module("transformers")
        model_class = getattr(model_module, model_class_name)

        tokenizer = AutoTokenizer.from_pretrained(
            model_path, trust_remote_code=True, local_files_only=True
        )

        model_kwargs = kwargs.get("model_kwargs", {})
        raw_device = str(kwargs.get("device", "auto") or "auto").strip().lower()
        target_device = "cpu"

        model = model_class.from_pretrained(model_path, **model_kwargs)
        if hasattr(model, "to"):
            model = model.to(target_device)

        if raw_device in {"cuda", "gpu", "auto"}:
            logger.warning(
                "检测到请求使用 CUDA/auto，本地 transformers 直连 GPU 已禁用，将强制使用 CPU"
            )
        return model, tokenizer

    def _load_image_gen_model(self, model_path: str, kwargs: Dict) -> Tuple[Any, None]:
        """加载图像生成模型"""
        from diffusers import StableDiffusionPipeline

        model_kwargs = kwargs.get("model_kwargs", {})
        if torch is None:
            raise ImportError("未安装 torch，无法加载图像生成模型")

        torch_dtype = kwargs.get("torch_dtype") or torch.float16

        pipe_kwargs = {
            "local_files_only": True,
            "torch_dtype": torch_dtype,
        }
        pipe_kwargs.update(model_kwargs)

        if os.path.isfile(model_path):
            pipe = self._load_image_gen_single_file(model_path, pipe_kwargs, kwargs)
        else:
            pipe = StableDiffusionPipeline.from_pretrained(model_path, **pipe_kwargs)

        return pipe, None

    def _load_image_gen_single_file(
        self, model_path: str, pipe_kwargs: Dict, kwargs: Dict
    ) -> Any:
        """从单个文件加载图像生成模型"""
        from diffusers import StableDiffusionPipeline
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[2]

        sd15_candidates = [
            project_root / "models" / "stable-diffusion-webui-forge-main" / "backend" / "huggingface" / "runwayml" / "stable-diffusion-v1-5",
            project_root / "models" / "img" / "sdxl" / "stable-diffusion-webui-forge-main" / "backend" / "huggingface" / "runwayml" / "stable-diffusion-v1-5",
        ]
        sdxl_candidates = [
            project_root / "models" / "stable-diffusion-webui-forge-main" / "backend" / "huggingface" / "stabilityai" / "stable-diffusion-xl-base-1.0",
            project_root / "models" / "img" / "sdxl" / "stable-diffusion-webui-forge-main" / "backend" / "huggingface" / "stabilityai" / "stable-diffusion-xl-base-1.0",
        ]

        sd15_local = next((str(p) for p in sd15_candidates if p.exists()), "")
        sdxl_local = next((str(p) for p in sdxl_candidates if p.exists()), "")

        if hasattr(StableDiffusionPipeline, "from_single_file"):
            loader = StableDiffusionPipeline.from_single_file
            pipe_kwargs["safety_checker"] = None

            if "original_config_file" not in pipe_kwargs:
                self._find_local_config(model_path, pipe_kwargs)

            is_sdxl = ("sdxl" in os.path.basename(model_path).lower()) or (
                "xl" in os.path.basename(model_path).lower()
            )
            if not is_sdxl and sd15_local:
                pipe_kwargs["config"] = sd15_local
            elif is_sdxl and sdxl_local:
                pipe_kwargs["config"] = sdxl_local
        else:
            loader = StableDiffusionPipeline.from_ckpt

        logger.info(f"Calling loader with pipe_kwargs keys: {list(pipe_kwargs.keys())}")
        pipe = loader(model_path, **pipe_kwargs)

        if (
            torch
            and torch.cuda.is_available()
            and "device_map" not in pipe_kwargs
            and kwargs.get("device") != "cpu"
        ):
            try:
                if hasattr(pipe, "enable_model_cpu_offload"):
                    pipe.enable_model_cpu_offload()
                    logger.info("Enabled model cpu offload")
                else:
                    pipe.enable_sequential_cpu_offload()
                    logger.info("Enabled sequential cpu offload")
            except Exception as e:
                logger.warning(f"Failed to enable CPU offload: {e}")

        return pipe

    @staticmethod
    def _find_local_config(model_path: str, pipe_kwargs: Dict):
        """查找本地配置文件"""
        dir_path = os.path.dirname(model_path)
        default_config = os.path.join(dir_path, "v1-inference.yaml")
        if os.path.exists(default_config):
            pipe_kwargs["original_config_file"] = default_config
            return

        base_name = os.path.splitext(model_path)[0]
        same_name_config = base_name + ".yaml"
        if os.path.exists(same_name_config):
            pipe_kwargs["original_config_file"] = same_name_config


_model_manager = None


def get_model_manager() -> ModelManager:
    """获取单例 ModelManager 实例"""
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager
