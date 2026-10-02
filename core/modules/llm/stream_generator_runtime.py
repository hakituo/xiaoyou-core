"""流式生成主入口与运行时准备（混入 StreamGenerator）。

从 ``core/modules/llm/stream_generator.py`` 拆出：
- ``generate``：流式生成主入口（GPU 资源闸门 → 模型切换/加载 → 调参 → 生成）
- ``_prepare_gpu_resources``：重量任务前的资源准备
- ``_try_fallback_model``：切换模型失败后回退旧模型

⚠️ 模块级 patch 语义：测试会 patch 门面模块的 ``time`` 与 ``get_resource_lock``
（``monkeypatch.setattr(sg, "get_resource_lock", ...)``），因此这两个名字必须在
调用期从门面模块取名，不能顶层 from-import 固化。
"""
from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Optional

# 循环引用仅为保留「按门面模块打补丁」的语义，调用期才取属性
from core.modules.llm import stream_generator as _facade
from core.utils.logger import get_logger

from .error_handler import get_error_message
from .utils import normalize_local_path

logger = get_logger("LLM.STREAM_GENERATOR")


class StreamGeneratorRuntimeMixin:
    """流式生成主流程与模型/资源准备。"""

    async def generate(
        self,
        prompt,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model_path: Optional[str] = None,
        first_token_timeout: float = 30.0,
        conversation_id: Optional[str] = None,
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

        Yields:
            生成的内容片段
        """
        logger.info(
            f"StreamGenerator.generate called. prompt_len={len(str(prompt))}, model_path={model_path}"
        )
        self.module.last_used = _facade.time.time()

        # 检查云模型路径
        if model_path and str(model_path).startswith("cloud:"):
            logger.error(f"LocalLLMModule received cloud model path: {model_path}")
            yield {
                "error": get_error_message("cloud_model_in_local", model_path),
                "done": True,
            }
            return

        # 解析模型路径（支持模型名称自动补全）
        from .utils import resolve_model_path

        effective_model_path = (
            resolve_model_path(model_path)
            if model_path
            else self.module.text_model_path
        )
        fallback_model_path = None

        from core.services.scheduler.cpp_scheduler_engine import cpp_scheduler_engine

        # 检查是否使用C++调度器
        use_cpp_scheduler = (
            cpp_scheduler_engine.enabled
            and self.module._use_cpp_scheduler_for_llm
            and effective_model_path
            and str(effective_model_path).lower().endswith(".gguf")
        )

        # 确定是否需要GPU资源锁
        need_gpu_gate = False
        try:
            if self.module.is_gguf:
                cfg_layers = self.module.config.get("n_gpu_layers")
                if cfg_layers is None:
                    cfg_layers = getattr(self.module.settings.model, "n_gpu_layers", -1)
                need_gpu_gate = int(cfg_layers) != 0
            else:
                need_gpu_gate = (
                    str(getattr(self.module, "device", "") or "").lower() == "cuda"
                )
        except Exception:
            need_gpu_gate = True

        async with AsyncExitStack() as stack:
            if bool(need_gpu_gate):
                await stack.enter_async_context(
                    _facade.get_resource_lock().acquire("LLM", reject_if_full=True)
                )

            # 使用C++调度器
            if use_cpp_scheduler:
                async for item in self._generate_with_scheduler(
                    prompt,
                    max_tokens,
                    temperature,
                    effective_model_path,
                    first_token_timeout,
                    conversation_id,
                ):
                    yield item
                return

            # 准备GPU资源
            await self._prepare_gpu_resources()

            # 检查是否需要切换模型
            if model_path:
                from .utils import resolve_model_path

                requested_path = resolve_model_path(model_path) or str(model_path)
                current_path = normalize_local_path(self.module.text_model_path) or str(
                    self.module.text_model_path
                )
                if requested_path != current_path:
                    logger.info(
                        f"Model switch requested: {self.module.text_model_path} -> {model_path}"
                    )
                    fallback_model_path = current_path
                    async with self.module._lock:
                        if requested_path != current_path:
                            await self.module._unload_model_unsafe()
                            self.module.text_model_path = requested_path
                            self.module.is_loaded = False

        if self.module.is_loaded and not self._is_local_runtime_ready():
            logger.warning(
                "检测到模型状态不一致（is_loaded=True 但本地推理对象缺失），将触发重新加载"
            )
            self.module.is_loaded = False

        # 确保模型已加载
        if not self.module.is_loaded:
            logger.info("Model not loaded, loading...")
            async with self.module._lock:
                if not self.module.is_loaded:
                    from .model_loader import ModelLoader

                    loader = ModelLoader(self.module)
                    success = await self.module._load_model_wrapper(loader)
                    if not success:
                        if fallback_model_path:
                            success = await self._try_fallback_model(
                                fallback_model_path
                            )
                        if not success:
                            logger.error("Model load failed.")
                            yield {
                                "status": "error",
                                "error": self.module._last_load_error or "模型加载失败",
                                "done": True,
                            }
                            return

        # 获取生成参数
        max_tokens = max_tokens or self.module.settings.model.max_new_tokens or None
        temperature = temperature or self.module.settings.model.temperature or 0.7
        min_p = self.module.settings.model.min_p
        repetition_penalty = self.module.settings.model.repetition_penalty or 1.1
        top_p = self.module.settings.model.top_p or 0.9
        top_k = getattr(self.module.settings.model, "top_k", None)

        # 对GGUF模型限制max_tokens
        if self.module.is_gguf:
            max_tokens = self._clamp_max_tokens_for_gguf(max_tokens)

        # 调整首token超时时间
        first_token_timeout = self._adjust_timeout(prompt, first_token_timeout)

        # 执行生成
        async for item in self._do_generate(
            prompt,
            max_tokens,
            temperature,
            min_p,
            repetition_penalty,
            top_p,
            top_k,
            first_token_timeout,
        ):
            yield item

    async def _prepare_gpu_resources(self):
        """准备GPU资源"""
        should_prepare_gpu = True
        try:
            if self.module.text_model_path and str(
                self.module.text_model_path
            ).lower().endswith(".gguf"):
                cfg_layers = self.module.config.get("n_gpu_layers")
                if cfg_layers is None:
                    cfg_layers = getattr(self.module.settings.model, "n_gpu_layers", -1)
                try:
                    should_prepare_gpu = int(cfg_layers) != 0
                except Exception:
                    should_prepare_gpu = True
            else:
                should_prepare_gpu = str(self.module.device).lower() == "cuda"
        except Exception:
            should_prepare_gpu = True

        if should_prepare_gpu:
            try:
                from core.resource_manager import get_global_resource_manager

                rm = await get_global_resource_manager()
                await rm.prepare_for_heavy_task("llm")
            except Exception as e:
                logger.error(f"Failed to prepare resources: {e}")

    async def _try_fallback_model(self, fallback_path: str) -> bool:
        """尝试回退到旧模型"""
        try:
            logger.warning(
                "模型切换失败，回退到旧模型: %s (错误: %s)",
                fallback_path,
                self.module._last_load_error or "未知",
            )
            await self.module._unload_model_unsafe()
            self.module.text_model_path = fallback_path
            self.module.is_loaded = False

            # 回退时强制禁用 scheduler 模式，确保本地加载
            original_scheduler_flag = self.module._use_cpp_scheduler_for_llm
            self.module._use_cpp_scheduler_for_llm = False

            try:
                from .model_loader import ModelLoader

                loader = ModelLoader(self.module)
                restored = await self.module._load_model_wrapper(loader)
                if restored:
                    logger.info("旧模型回退加载成功")
                return restored
            finally:
                # 恢复原始 scheduler 标志
                self.module._use_cpp_scheduler_for_llm = original_scheduler_flag
        except Exception as e:
            logger.error("旧模型回退失败: %s", e)
            return False
