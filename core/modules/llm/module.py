"""
LLM模块 - 精简后的主类
负责协调各个子模块处理文本生成任务
"""

import time
import gc
import asyncio
import threading
from typing import Optional

from config.integrated_config import get_settings
from core.utils.logger import get_logger
from core.core_engine.config_manager import ConfigManager
from core.utils.async_locks import LazyAsyncLock

from .utils import get_torch, normalize_local_path
from .inference_utils import (
    build_llama_cpp_chat_kwargs,
    strip_unexpected_llama_cpp_kwargs,
    apply_default_template,
)
from .error_handler import get_error_message

logger = get_logger("LLM_MODULE")


class LLMModule:
    """
    LLM模块，负责处理文本生成任务。
    封装了大语言模型的加载和推理逻辑。
    """

    def __init__(self, config=None):
        """
        初始化LLM模块

        Args:
            config: 模块配置字典，可覆盖全局配置
        """
        self.settings = get_settings()
        self.config = config or {}

        # 优先使用传入的 config，其次是全局 settings
        self.text_model_path = (
            self.config.get("text_model_path")
            or self.settings.model.text_path
            or "./models/qwen"
        )
        self.text_model_path = (
            normalize_local_path(self.text_model_path) or self.text_model_path
        )

        # Device 处理：优先 config，其次 settings
        self.device = self.config.get("device") or self.settings.model.device

        if self.device == "auto" or not self.device:
            torch = get_torch()
            self.device = "cuda" if (torch and torch.cuda.is_available()) else "cpu"

        # 模型相关属性
        self.model = None
        self.llm = None
        self.tokenizer = None
        self.llama_model = None
        self.is_loaded = False
        self.is_gguf = False

        # 锁和同步
        self._lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._thread_lock = threading.Lock()

        # 状态管理
        self.last_used = time.time()
        self._idle_check_task = None
        self._last_load_error: Optional[str] = None
        self._load_future: Optional[asyncio.Future] = None
        self._recovery_task: Optional[asyncio.Task] = None
        self._last_timeout_at: Optional[float] = None
        self._force_cpu_after_timeout = False

        # C++调度器配置
        try:
            cfg = ConfigManager()
            self._use_cpp_scheduler_for_llm = bool(
                cfg.get("scheduler.use_cpp_for_llm", False)
            )
        except Exception:
            self._use_cpp_scheduler_for_llm = False

        # 初始化子模块
        self._init_submodules()

    def _init_submodules(self):
        """初始化子模块（延迟导入避免循环依赖）"""
        pass  # 子模块在需要时动态创建

    def _get_model_loader(self):
        """获取模型加载器"""
        from .model_loader import ModelLoader

        return ModelLoader(self)

    def _get_stream_generator(self):
        """获取流式生成器"""
        from .stream_generator import StreamGenerator

        return StreamGenerator(self)

    def _get_sync_generator(self):
        """获取同步生成器"""
        from .sync_generator import SyncGenerator

        return SyncGenerator(self)

    def _get_gpu_manager(self):
        """获取GPU管理器"""
        from .gpu_manager import GPUManager

        return GPUManager(self)

    async def reload(self):
        """重新加载模型配置和模型"""
        logger.info("Reloading LLMModule...")
        self.settings = get_settings()

        # 检查是否切换到云端模型
        is_cloud_model = self.settings.model.llm.provider != "local"

        if is_cloud_model:
            # 切换到云端模型：卸载本地模型但不重新加载
            logger.info(
                f"Switching to cloud model (provider: {self.settings.model.llm.provider})"
            )
            if self.is_loaded:
                logger.info("Unloading local model to free resources...")
                async with self._lock:
                    await self._unload_model_unsafe()

                # 强制 GC
                gc.collect()
                torch = get_torch()
                if torch and torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.ipc_collect()

                logger.info("Local model unloaded, resources freed for cloud model.")
            else:
                logger.info("No local model loaded, ready for cloud model.")
            return

        # 本地模型：继续原有逻辑
        # 重新获取配置
        new_path = self.settings.model.text_path or "./models/qwen"
        new_path = normalize_local_path(new_path) or new_path

        new_device = self.settings.model.device
        if new_device == "auto" or not new_device:
            torch = get_torch()
            new_device = "cuda" if (torch and torch.cuda.is_available()) else "cpu"

        # 检查是否需要重新加载
        # 规范化当前路径以进行准确比较
        current_path_normalized = (
            normalize_local_path(self.text_model_path) if self.text_model_path else ""
        )
        need_reload = False
        if new_path != current_path_normalized:
            logger.info(f"Model path changed: {current_path_normalized} -> {new_path}")
            self.text_model_path = new_path
            need_reload = True

        if new_device != self.device:
            logger.info(f"Device changed: {self.device} -> {new_device}")
            self.device = new_device
            need_reload = True

        if need_reload and self.is_loaded:
            logger.info("Unloading current model for reload...")
            async with self._lock:
                await self._unload_model_unsafe()

            # 强制 GC
            gc.collect()
            torch = get_torch()
            if torch and torch.cuda.is_available():
                torch.cuda.empty_cache()

            # 重新加载
            await self._load_model()
            logger.info("LLMModule reloaded successfully.")
        elif need_reload:
            logger.info(
                "Configuration updated (model was not loaded, so no reload needed)."
            )
        else:
            logger.info("No configuration changes detected.")

    async def _load_model(self) -> bool:
        """
        加载文本模型 (异步包装)

        Returns:
            是否加载成功
        """
        # [Architecture Compliance] If C++ Scheduler is enabled for LLM,
        # LLMModule should NOT load the model locally.
        scheduler_enabled = False
        try:
            from core.services.scheduler.cpp_scheduler_engine import cpp_scheduler_engine

            scheduler_enabled = bool(getattr(cpp_scheduler_engine, "enabled", False))
        except Exception:
            scheduler_enabled = False

        if (
            scheduler_enabled
            and self._use_cpp_scheduler_for_llm
            and self.text_model_path
            and str(self.text_model_path).lower().endswith(".gguf")
        ):
            logger.info(
                "Scheduler enabled: Skipping local model load in LLMModule (Client Mode)."
            )
            self.is_gguf = True
            self.is_loaded = True
            return True

        # 准备GPU资源
        await self._prepare_resources_for_load()

        # 获取超时配置
        model_load_timeout = None
        try:
            model_load_timeout = float(
                getattr(self.settings.model, "model_load_timeout", 0) or 0
            )
        except Exception:
            model_load_timeout = 0

        # 执行加载
        ok = False
        loader = self._get_model_loader()

        try:
            if self._load_future is not None and not self._load_future.done():
                if model_load_timeout and model_load_timeout > 0:
                    ok = await asyncio.wait_for(
                        asyncio.shield(self._load_future), timeout=model_load_timeout
                    )
                else:
                    ok = await self._load_future
            else:
                self._load_future = asyncio.create_task(
                    asyncio.to_thread(loader.load_sync)
                )
                if model_load_timeout and model_load_timeout > 0:
                    ok = await asyncio.wait_for(
                        asyncio.shield(self._load_future), timeout=model_load_timeout
                    )
                else:
                    ok = await self._load_future

        except asyncio.TimeoutError:
            timeout_seconds = (
                int(model_load_timeout)
                if model_load_timeout and model_load_timeout > 0
                else 0
            )
            self._last_load_error = get_error_message(
                "load_timeout", f"{timeout_seconds}秒" if timeout_seconds > 0 else ""
            )
            logger.error(self._last_load_error)
            return False

        except Exception as e:
            self._last_load_error = get_error_message("load_failed", str(e))
            logger.error(self._last_load_error)
            return False

        finally:
            try:
                if self._load_future is not None and self._load_future.done():
                    self._load_future = None
            except Exception:
                pass

        # 更新资源管理器状态
        try:
            from core.resource_manager import get_resource_manager

            get_resource_manager().mark_model_loaded("llm_engine", bool(ok))
        except Exception:
            pass

        return ok

    async def _load_model_wrapper(self, loader) -> bool:
        """模型加载包装器（供子模块使用）"""
        return await self._load_model()

    async def _prepare_resources_for_load(self):
        """为模型加载准备资源"""
        should_prepare_gpu = True
        try:
            if self.text_model_path and str(self.text_model_path).lower().endswith(
                ".gguf"
            ):
                cfg_layers = self.config.get("n_gpu_layers")
                if cfg_layers is None:
                    cfg_layers = getattr(self.settings.model, "n_gpu_layers", -1)
                try:
                    should_prepare_gpu = int(cfg_layers) != 0
                except Exception:
                    should_prepare_gpu = True
            else:
                should_prepare_gpu = str(self.device).lower() == "cuda"
        except Exception:
            should_prepare_gpu = True

        if should_prepare_gpu:
            try:
                from core.resource_manager import get_resource_manager

                rm = get_resource_manager()

                # [Fix] Proactive Voice Service Offloading
                logger.info(
                    "LLMModule: Proactively offloading voice services for GPU LLM load..."
                )

                # 1. Try specific offload method if available
                if hasattr(rm, "_offload_voice_services"):
                    await rm._offload_voice_services()

                # 2. Call standard preparation
                await rm.prepare_for_heavy_task("llm")

                # 3. Double check TTS specifically
                try:
                    tts_model = rm.get_model("tts_engine")
                    if tts_model and tts_model.is_loaded:
                        logger.info(
                            "LLMModule: Sending explicit release signal to TTS Engine..."
                        )
                        for handler in rm._resource_handlers.get("gpu_memory", []):
                            if asyncio.iscoroutinefunction(handler):
                                await handler("release")
                            else:
                                handler("release")
                except Exception as e:
                    logger.warning(f"LLMModule: Failed to force release TTS: {e}")

            except Exception as e:
                logger.warning(f"Failed to prepare resources for LLM: {e}")

    async def stream_chat(
        self,
        prompt,
        max_tokens=None,
        temperature=None,
        model_path=None,
        first_token_timeout=30,
        conversation_id=None,
        **kwargs,
    ):
        """
        流式生成文本回复

        Args:
            prompt: 提示词或消息列表
            max_tokens: 最大生成token数
            temperature: 温度参数
            model_path: 模型路径
            first_token_timeout: 首token超时时间
            conversation_id: 会话ID
            **kwargs: 其他生成参数

        Yields:
            生成的内容片段
        """
        generator = self._get_stream_generator()
        async for item in generator.generate(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            model_path=model_path,
            first_token_timeout=first_token_timeout,
            conversation_id=conversation_id,
            **kwargs,
        ):
            yield item

    async def chat(
        self,
        prompt,
        max_tokens=None,
        temperature=None,
        model_path=None,
        conversation_id=None,
        **kwargs,
    ):
        """
        生成文本回复（非流式）

        Args:
            prompt: 提示词或消息列表
            max_tokens: 最大生成token数
            temperature: 温度参数
            model_path: 模型路径
            conversation_id: 会话ID
            **kwargs: 其他生成参数

        Returns:
            包含状态和回复的字典
        """
        generator = self._get_sync_generator()
        return await generator.generate(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            model_path=model_path,
            conversation_id=conversation_id,
            **kwargs,
        )

    def get_current_model_name(self):
        """获取当前加载的模型名称或路径"""
        return self.text_model_path

    async def unload_model(self):
        """卸载模型释放资源"""
        async with self._lock:
            await self._unload_model_unsafe()

    async def offload_to_cpu(self):
        """将模型卸载到CPU"""
        await self.release_llm_vram_for_image_gen()

    async def release_llm_vram_for_image_gen(self):
        """为图像生成释放LLM的VRAM"""
        gpu_manager = self._get_gpu_manager()
        await gpu_manager.release_llm_vram_for_image_gen()

    async def restore_llm_to_gpu(self) -> bool:
        """将LLM恢复回GPU"""
        gpu_manager = self._get_gpu_manager()
        return await gpu_manager.restore_llm_to_gpu()

    async def _unload_model_unsafe(self, sleep_s: float = 0.5):
        """
        卸载模型释放资源 (无锁版本，调用者需持有锁)

        Args:
            sleep_s: 卸载后等待的时间（秒）
        """
        logger.info(f"Unloading model: {self.text_model_path}")

        if self.model:
            del self.model
            self.model = None

        if self.tokenizer:
            del self.tokenizer
            self.tokenizer = None

        if self.llama_model:
            # Try to close/delete properly
            try:
                if hasattr(self.llama_model, "close"):
                    self.llama_model.close()
            except Exception as e:
                logger.warning(f"Error closing llama_model: {e}")

            try:
                del self.llama_model
            except Exception as e:
                logger.warning(f"Error deleting llama_model: {e}")
            self.llama_model = None

        # 清理GPU缓存（多次清理确保彻底释放）
        torch = get_torch()
        if torch and torch.cuda.is_available():
            try:
                torch.cuda.empty_cache()
                torch.cuda.synchronize()  # 等待所有CUDA操作完成
                torch.cuda.ipc_collect()
                # 再次清理确保彻底释放
                torch.cuda.empty_cache()
            except Exception as e:
                logger.warning(f"Error clearing CUDA cache: {e}")

        # Force garbage collection (多次GC确保彻底清理)
        gc.collect()
        gc.collect()

        if sleep_s and float(sleep_s) > 0:
            await asyncio.sleep(float(sleep_s))

        self.is_loaded = False
        logger.info("文本模型已卸载，内存已清理")

        # 更新资源管理器状态
        try:
            from core.resource_manager import get_resource_manager

            get_resource_manager().mark_model_loaded("llm_engine", False)
        except Exception:
            pass

    # 向后兼容的委托方法
    def _build_llama_cpp_chat_kwargs(self, **kwargs) -> dict:
        """构建 llama_cpp chat completion 的参数"""
        return build_llama_cpp_chat_kwargs(**kwargs)

    def _strip_unexpected_llama_cpp_kwargs(self, kwargs: dict, error_str: str) -> dict:
        """移除 llama_cpp 不支持的参数"""
        return strip_unexpected_llama_cpp_kwargs(kwargs, error_str)

    def _apply_default_template(self, messages: list) -> str:
        """应用默认聊天模板"""
        return apply_default_template(messages, self.tokenizer)

    def _gpu_health_check(self) -> bool:
        """GPU健康检查"""
        gpu_manager = self._get_gpu_manager()
        return gpu_manager.health_check()


# 向后兼容的别名
_get_torch = get_torch
_normalize_local_path = normalize_local_path


def _patch_llama_cpp_internals():
    return None
