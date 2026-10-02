"""流式生成的 C++ 调度器委派（混入 StreamGenerator）。

从 ``core/modules/llm/stream_generator.py`` 拆出，原样搬移
``_generate_with_scheduler``。
"""
from __future__ import annotations

import asyncio
from typing import Optional

from core.utils.logger import get_logger

logger = get_logger("LLM.STREAM_GENERATOR")


class StreamGeneratorSchedulerMixin:
    """把推理请求交给全局 C++ 调度器执行。"""

    async def _generate_with_scheduler(
        self,
        prompt,
        max_tokens: Optional[int],
        temperature: Optional[float],
        model_path: str,
        first_token_timeout: float,
        conversation_id: Optional[str],
    ):
        """使用C++调度器生成"""
        from core.services.scheduler.task.task_scheduler import get_global_scheduler

        scheduler = get_global_scheduler()
        try:
            if not getattr(scheduler, "_running", False):
                worker_count = 4
                try:
                    worker_count = int(
                        getattr(
                            getattr(self.module.settings, "scheduler", None),
                            "worker_count",
                            4,
                        )
                        or 4
                    )
                except Exception:
                    worker_count = 4
                await scheduler.start(
                    worker_count=worker_count, llm_model_path=model_path
                )
        except Exception as e:
            logger.error(f"全局调度器启动失败: {e}")
            yield {"error": f"全局调度器启动失败: {e}", "done": True}
            return

        logger.info("Delegating inference to C++ Scheduler...")
        try:
            if self.module.is_loaded:
                async with self.module._lock:
                    await self.module._unload_model_unsafe()

            eff_max_tokens = (
                max_tokens or self.module.settings.model.max_new_tokens or None
            )
            eff_temperature = (
                temperature or self.module.settings.model.temperature or 0.7
            )
            eff_top_p = self.module.settings.model.top_p or 0.9
            eff_top_k = getattr(self.module.settings.model, "top_k", None)
            eff_repetition_penalty = (
                self.module.settings.model.repetition_penalty or 1.1
            )
            eff_min_p = getattr(self.module.settings.model, "min_p", None)

            try:
                async for token in get_global_scheduler().submit_llm_task(
                    prompt=prompt,
                    model_path=model_path,
                    max_tokens=eff_max_tokens,
                    temperature=eff_temperature,
                    top_p=eff_top_p,
                    top_k=eff_top_k,
                    repetition_penalty=eff_repetition_penalty,
                    min_p=eff_min_p,
                    first_token_timeout=first_token_timeout,
                    conversation_id=conversation_id,
                ):
                    if isinstance(token, dict):
                        yield token
                        if token.get("done"):
                            return
                        if "error" in token:
                            return
                        continue
                    yield {"content": token}
            except asyncio.CancelledError:
                logger.warning(
                    "Stream chat cancelled. Requesting C++ scheduler to stop inference."
                )
                if hasattr(get_global_scheduler(), "request_stop_current_inference"):
                    await get_global_scheduler().request_stop_current_inference()
                else:
                    from core.services.scheduler.cpp_scheduler_engine import (
                        cpp_scheduler_engine,
                    )

                    if hasattr(cpp_scheduler_engine, "request_stop_current_inference"):
                        await cpp_scheduler_engine.request_stop_current_inference()
                raise
        except Exception as e:
            # 注：这里原先还有一层 `if isinstance(e, asyncio.CancelledError): raise`。
            # 但 asyncio.CancelledError 自 Python 3.8 起继承自 BaseException 而非 Exception，
            # `except Exception` 永远绑不到 BaseException 子类，故该判断恒为 False、恒不执行。
            # 取消信号由上面内层的 `except asyncio.CancelledError` 分支负责请求停止推理并向上冒泡，
            # 行为不受影响。本仓库 requires-python = ">=3.10,<3.15"，该范围内全部成立（2026-09-24 删除）。
            error_msg = f"C++ Scheduler inference failed: {e}"
            logger.error(error_msg)
            yield {
                "error": "本地模型调度服务暂时不可用，请稍后再试或检查后台日志。",
                "done": True,
            }
