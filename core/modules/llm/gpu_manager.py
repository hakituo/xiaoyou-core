"""
LLM模块GPU资源管理
负责GPU/CPU资源切换、健康检查和显存管理
"""

import os
import time
import asyncio
import queue as queue_module
import threading
from typing import Optional

from core.utils.logger import get_logger
from .utils import get_torch
from .inference_utils import build_llama_cpp_chat_kwargs

logger = get_logger("LLM.GPU_MANAGER")


class GPUManager:
    """GPU资源管理器，负责LLM的GPU/CPU切换和显存管理"""

    def __init__(self, module):
        """
        初始化GPU管理器

        Args:
            module: 所属的LLMModule实例
        """
        self.module = module
        self._prev_n_gpu_layers: Optional[int] = None
        self._prev_n_ctx: Optional[int] = None
        self._prev_n_batch: Optional[int] = None

    async def release_llm_vram_for_image_gen(self):
        """
        为图像生成释放LLM的VRAM
        将模型从GPU卸载到CPU
        """
        schedule_cpu_load = False
        async with self.module._lock:
            if not self.module.is_loaded:
                return

            try:
                if self.module.is_gguf and self.module.llama_model is not None:
                    cfg_layers = self.module.config.get("n_gpu_layers")
                    if cfg_layers is None:
                        cfg_layers = getattr(
                            self.module.settings.model, "n_gpu_layers", -1
                        )
                    try:
                        cfg_layers_int = int(cfg_layers)
                    except Exception:
                        cfg_layers_int = -1

                    if cfg_layers_int == 0:
                        return

                    # 保存当前配置以便恢复
                    try:
                        self._prev_n_gpu_layers = int(cfg_layers_int)
                    except Exception:
                        self._prev_n_gpu_layers = None

                    try:
                        cur_ctx = self.module.config.get("n_ctx")
                        if cur_ctx is None:
                            cur_ctx = getattr(self.module.settings.model, "n_ctx", None)
                        if cur_ctx is None and hasattr(
                            self.module.llama_model, "n_ctx"
                        ):
                            try:
                                cur_ctx = int(self.module.llama_model.n_ctx())
                            except Exception:
                                cur_ctx = None
                        if cur_ctx is not None:
                            self._prev_n_ctx = int(cur_ctx)
                    except Exception:
                        pass

                    try:
                        cur_batch = self.module.config.get("n_batch")
                        if cur_batch is None:
                            cur_batch = getattr(
                                self.module.settings.model, "n_batch", None
                            )
                        if cur_batch is not None:
                            self._prev_n_batch = int(cur_batch)
                    except Exception:
                        pass

                    # 获取CPU模式的目标配置
                    try:
                        target_ctx = int(
                            os.getenv("XIAOYOU_DEMO_CPU_LLM_N_CTX", "2048") or 2048
                        )
                    except Exception:
                        target_ctx = 2048
                    try:
                        target_batch = int(
                            os.getenv("XIAOYOU_DEMO_CPU_LLM_N_BATCH", "256") or 256
                        )
                    except Exception:
                        target_batch = 256

                    # 切换到CPU配置
                    self.module.config["n_gpu_layers"] = 0
                    try:
                        if self.module.config.get("n_ctx") is not None:
                            self.module.config["n_ctx"] = max(
                                256,
                                min(
                                    int(self.module.config.get("n_ctx") or target_ctx),
                                    target_ctx,
                                ),
                            )
                        else:
                            self.module.config["n_ctx"] = int(target_ctx)
                    except Exception:
                        self.module.config["n_ctx"] = int(target_ctx)
                    try:
                        if self.module.config.get("n_batch") is not None:
                            self.module.config["n_batch"] = max(
                                16,
                                min(
                                    int(
                                        self.module.config.get("n_batch")
                                        or target_batch
                                    ),
                                    target_batch,
                                ),
                            )
                        else:
                            self.module.config["n_batch"] = int(target_batch)
                    except Exception:
                        self.module.config["n_batch"] = int(target_batch)

                    # 卸载模型
                    await self.module._unload_model_unsafe(sleep_s=0.0)
                    schedule_cpu_load = True
                    return

                # Transformers模型处理
                torch = get_torch()
                if (
                    torch
                    and torch.cuda.is_available()
                    and str(self.module.device).lower() == "cuda"
                ):
                    try:
                        if self.module.model is not None and hasattr(
                            self.module.model, "to"
                        ):
                            self.module.model.to("cpu")
                        if self.module.tokenizer is not None:
                            pass
                        torch.cuda.empty_cache()
                        torch.cuda.ipc_collect()
                    except Exception:
                        pass
            except Exception:
                return

        # 异步重新加载CPU模型
        if schedule_cpu_load:

            async def _ensure_cpu_loaded():
                try:
                    async with self.module._lock:
                        if self.module.is_loaded:
                            return
                        ok = await asyncio.to_thread(self.module._load_model_sync)
                        self.module.is_loaded = bool(ok)
                        try:
                            from core.resource_manager import get_resource_manager

                            get_resource_manager().mark_model_loaded(
                                "llm_engine", bool(ok)
                            )
                        except Exception:
                            pass
                except Exception:
                    return

            try:
                task = asyncio.create_task(_ensure_cpu_loaded())
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=1.5)
                except asyncio.TimeoutError:
                    pass
                except Exception:
                    pass
            except Exception:
                pass

    async def restore_llm_to_gpu(self) -> bool:
        """
        将LLM恢复回GPU模式

        Returns:
            是否成功恢复
        """
        async with self.module._lock:
            if not self.module.is_loaded:
                return False

            if self.module.is_gguf:
                # 检查当前是否已经是GPU模式
                try:
                    cur_layers = self.module.config.get("n_gpu_layers")
                    cur_layers_int = int(cur_layers) if cur_layers is not None else None
                except Exception:
                    cur_layers_int = None

                if cur_layers_int is not None and int(cur_layers_int) != 0:
                    return True

                # 确定目标GPU层数
                target_layers = self._prev_n_gpu_layers
                if target_layers is None:
                    try:
                        target_layers = int(
                            getattr(self.module.settings.model, "n_gpu_layers", -1)
                        )
                    except Exception:
                        target_layers = -1

                try:
                    target_layers = int(target_layers)
                except Exception:
                    target_layers = -1

                if target_layers == 0:
                    return False

                # 恢复配置
                try:
                    self.module.config["n_gpu_layers"] = int(target_layers)
                    if isinstance(self._prev_n_ctx, int) and self._prev_n_ctx > 0:
                        self.module.config["n_ctx"] = int(self._prev_n_ctx)
                    if isinstance(self._prev_n_batch, int) and self._prev_n_batch > 0:
                        self.module.config["n_batch"] = int(self._prev_n_batch)
                except Exception:
                    pass

                # 重新加载到GPU
                await self.module._unload_model_unsafe(sleep_s=0.0)
                ok = await asyncio.to_thread(self.module._load_model_sync)
                self.module.is_loaded = bool(ok)
                try:
                    from core.resource_manager import get_resource_manager

                    get_resource_manager().mark_model_loaded("llm_engine", bool(ok))
                except Exception:
                    pass
                return bool(ok)

            # Transformers模型处理
            if str(self.module.device).lower() != "cuda":
                return False

            torch = get_torch()
            if not (torch and torch.cuda.is_available()):
                return False

            try:
                if self.module.model is not None and hasattr(self.module.model, "to"):
                    await asyncio.to_thread(self.module.model.to, "cuda")
                try:
                    from core.resource_manager import get_resource_manager

                    get_resource_manager().mark_model_loaded("llm_engine", True)
                except Exception:
                    pass
                return True
            except Exception:
                return False

    def health_check(self) -> bool:
        """
        GPU健康检查：执行简单的推理测试验证GPU是否真正可用

        Returns:
            True表示GPU正常工作，False表示GPU推理卡死
        """
        if not self.module.llama_model:
            logger.warning("GPU健康检查：模型未加载")
            return False

        try:
            result_queue = queue_module.Queue()

            def _health_check_task():
                try:
                    # 执行一个简单的推理测试
                    test_messages = [{"role": "user", "content": "Hi"}]
                    test_kwargs = build_llama_cpp_chat_kwargs(
                        max_tokens=4,
                        temperature=0.1,
                        top_p=0.9,
                        repetition_penalty=1.0,
                        stream=False,
                    )

                    start_time = time.time()
                    response = self.module.llama_model.create_chat_completion(
                        messages=test_messages,
                        **test_kwargs,
                    )
                    elapsed = time.time() - start_time

                    # 检查响应是否有效
                    if (
                        response
                        and "choices" in response
                        and len(response["choices"]) > 0
                    ):
                        content = (
                            response["choices"][0].get("message", {}).get("content", "")
                        )
                        result_queue.put(("success", elapsed, content))
                    else:
                        result_queue.put(("invalid_response", elapsed, None))
                except Exception as e:
                    result_queue.put(("error", 0, str(e)))

            # 在单独线程中执行健康检查
            check_thread = threading.Thread(target=_health_check_task, daemon=True)
            check_thread.start()
            check_thread.join(timeout=10.0)  # 最多等待10秒

            if check_thread.is_alive():
                # 线程仍在运行，说明GPU推理卡死
                logger.error("GPU健康检查超时（10秒），GPU推理可能卡死")
                return False

            # 获取结果
            try:
                status, elapsed, content = result_queue.get(timeout=1.0)
                if status == "success":
                    logger.info(
                        f"GPU健康检查通过，耗时: {elapsed:.2f}秒，响应: {content[:20] if content else 'empty'}"
                    )
                    return True
                elif status == "error":
                    logger.error(f"GPU健康检查失败: {content}")
                    return False
                else:
                    logger.warning("GPU健康检查返回无效响应")
                    return False
            except queue_module.Empty:
                logger.error("GPU健康检查无法获取结果")
                return False

        except Exception as e:
            logger.error(f"GPU健康检查异常: {e}")
            return False

    def get_gpu_info(self) -> dict:
        """
        获取当前GPU信息

        Returns:
            包含GPU状态信息的字典
        """
        info = {
            "cuda_available": False,
            "gpu_name": None,
            "gpu_memory_total_gb": 0,
            "gpu_memory_used_gb": 0,
            "gpu_memory_reserved_gb": 0,
            "n_gpu_layers_config": 0,
            "n_gpu_layers_actual": 0,
        }

        try:
            import torch

            if torch.cuda.is_available():
                info["cuda_available"] = True
                info["gpu_name"] = torch.cuda.get_device_name(0)
                info["gpu_memory_total_gb"] = torch.cuda.get_device_properties(
                    0
                ).total_memory / (1024**3)
                info["gpu_memory_used_gb"] = torch.cuda.memory_allocated(0) / (1024**3)
                info["gpu_memory_reserved_gb"] = torch.cuda.memory_reserved(0) / (
                    1024**3
                )
        except Exception:
            pass

        # 获取配置的GPU层数
        try:
            cfg_layers = self.module.config.get("n_gpu_layers")
            if cfg_layers is None:
                cfg_layers = getattr(self.module.settings.model, "n_gpu_layers", -1)
            info["n_gpu_layers_config"] = (
                int(cfg_layers) if cfg_layers is not None else -1
            )
        except Exception:
            pass

        # 获取实际的GPU层数
        if self.module.llama_model and hasattr(self.module.llama_model, "n_gpu_layers"):
            try:
                info["n_gpu_layers_actual"] = int(
                    self.module.llama_model.n_gpu_layers()
                )
            except Exception:
                pass

        return info

    def log_gpu_status(self, prefix: str = ""):
        """记录GPU状态日志"""
        info = self.get_gpu_info()
        msg = f"{prefix}GPU状态 - CUDA可用: {info['cuda_available']}"
        if info["cuda_available"]:
            msg += (
                f", GPU: {info['gpu_name']}"
                f", 显存: {info['gpu_memory_used_gb']:.2f}/"
                f"{info['gpu_memory_total_gb']:.2f}GB"
                f", 配置层数: {info['n_gpu_layers_config']}"
                f", 实际层数: {info['n_gpu_layers_actual']}"
            )
        logger.info(msg)
