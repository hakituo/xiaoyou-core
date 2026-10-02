"""流式生成的生产者线程、队列消费与超时恢复（混入 StreamGenerator）。

从 ``core/modules/llm/stream_generator.py`` 拆出：
- ``_do_generate``：起后台线程持线程锁执行生成，用队列回传片段
- ``_consume_queue``：异步消费队列，处理首 token 超时
- ``_trigger_recovery``：超时后卸载模型触发重新加载

⚠️ 模块级 patch 语义：测试会 patch 门面模块的 ``time``（``sg.time``），因此这里
必须在调用期从门面模块取名，不能顶层 from-import 固化；``sg.asyncio`` 的 patch
作用在 ``asyncio`` 模块自身的属性上，直接 ``import asyncio`` 即可。
"""
from __future__ import annotations

import asyncio
import threading

# 循环引用仅为保留「按门面模块打补丁」的语义，调用期才取属性
from core.modules.llm import stream_generator as _facade
from core.utils.logger import get_logger

from .error_handler import get_error_message

logger = get_logger("LLM.STREAM_GENERATOR")


class StreamGeneratorWorkerMixin:
    """后台生成线程与队列消费。"""

    async def _do_generate(
        self,
        prompt,
        max_tokens: int,
        temperature: float,
        min_p,
        repetition_penalty: float,
        top_p: float,
        top_k,
        first_token_timeout: float,
    ):
        """执行实际生成"""
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _producer():
            logger.info(f"Producer thread started. Timestamp: {_facade.time.time()}")

            def _put_threadsafe(payload):
                try:
                    if loop.is_closed():
                        return
                    asyncio.run_coroutine_threadsafe(queue.put(payload), loop)
                except Exception:
                    return

            acquired = False
            try:
                try:
                    timeout_sec = float(first_token_timeout)
                except Exception:
                    timeout_sec = 10.0

                # 获取线程锁
                if self.module._thread_lock.locked():
                    logger.warning(
                        f"检测到线程锁已被占用，尝试等待 {timeout_sec}s 后强制获取..."
                    )
                    lock_wait_start = _facade.time.time()
                    acquired = self.module._thread_lock.acquire(timeout=timeout_sec)
                    if not acquired:
                        logger.error(
                            f"锁获取超时（{_facade.time.time() - lock_wait_start:.1f}s），可能存在死锁"
                        )
                        try:
                            self.module._thread_lock.release()
                            logger.warning("已强制释放线程锁")
                        except Exception:
                            pass
                        acquired = self.module._thread_lock.acquire(timeout=5.0)
                else:
                    acquired = self.module._thread_lock.acquire(
                        timeout=max(0.1, timeout_sec)
                    )

                if not acquired:
                    _put_threadsafe(
                        {
                            "error": get_error_message("thread_lock_timeout"),
                            "done": True,
                        }
                    )
                    return

                logger.info("Acquired thread lock. Starting generation...")
                prompt_value = prompt
                if isinstance(prompt_value, list):
                    prompt_value = list(prompt_value)

                if self.module.is_gguf:
                    self._generate_gguf(
                        prompt_value,
                        max_tokens,
                        temperature,
                        top_p,
                        top_k,
                        repetition_penalty,
                        min_p,
                        _put_threadsafe,
                    )
                else:
                    self._generate_transformers(
                        prompt_value,
                        max_tokens,
                        temperature,
                        top_p,
                        top_k,
                        repetition_penalty,
                        min_p,
                        _put_threadsafe,
                    )

            except Exception as e:
                logger.error(f"Stream generation error: {e}")
                import traceback

                logger.error(traceback.format_exc())
                _put_threadsafe({"error": str(e), "done": True})
            finally:
                if acquired:
                    try:
                        self.module._thread_lock.release()
                    except Exception:
                        pass
                logger.info("Producer thread finishing. Sending sentinel.")
                _put_threadsafe(None)

        threading.Thread(
            target=_producer, daemon=True, name="llm_stream_producer"
        ).start()

        # 消费队列
        async for item in self._consume_queue(queue, first_token_timeout):
            yield item

    async def _consume_queue(self, queue: asyncio.Queue, first_token_timeout: float):
        """消费生成队列"""
        logger.info("Consuming queue...")

        first_item = True
        received_token = False

        while True:
            if first_item:
                start_wait_time = _facade.time.time()
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=1.0)
                        break
                    except asyncio.TimeoutError:
                        elapsed = _facade.time.time() - start_wait_time
                        if elapsed >= first_token_timeout:
                            logger.error(
                                f"LLM stream first token timeout after {first_token_timeout}s"
                            )
                            self.module._last_timeout_at = _facade.time.time()

                            # 触发恢复
                            await self._trigger_recovery()

                            yield {
                                "error": get_error_message(
                                    "first_token_timeout", str(first_token_timeout)
                                ),
                                "done": True,
                            }
                            return
                        else:
                            if int(elapsed) % 2 == 0:
                                logger.info(
                                    f"Still waiting for model generation... ({elapsed:.1f}/{first_token_timeout}s)"
                                )
                first_item = False
            else:
                item = await queue.get()

            if item is None:
                logger.info("Received sentinel. Stream finished.")
                break

            if isinstance(item, dict) and "error" in item:
                logger.error(f"Stream error in queue: {item['error']}")
            if isinstance(item, dict) and item.get("content"):
                received_token = True
            yield item

        if received_token:
            self.module._force_cpu_after_timeout = False
            self.module._last_timeout_at = None

    async def _trigger_recovery(self):
        """触发超时后的恢复"""

        async def _recover():
            try:
                for _ in range(3):
                    acquired = False
                    try:
                        acquired = self.module._thread_lock.acquire(timeout=1.0)
                        if not acquired:
                            await asyncio.sleep(1.0)
                            continue
                        async with self.module._lock:
                            await self.module._unload_model_unsafe()
                            self.module.is_loaded = False
                        return
                    finally:
                        if acquired:
                            try:
                                self.module._thread_lock.release()
                            except Exception:
                                pass
            finally:
                self.module._recovery_task = None

        if self.module._recovery_task and not self.module._recovery_task.done():
            return

        try:
            self.module._recovery_task = asyncio.create_task(_recover())
        except Exception:
            self.module._recovery_task = None

        # 等待恢复完成
        recovery_wait_start = _facade.time.time()
        max_recovery_wait = 30.0
        while self.module._recovery_task and not self.module._recovery_task.done():
            await asyncio.sleep(0.5)
            if _facade.time.time() - recovery_wait_start > max_recovery_wait:
                logger.error("GPU到CPU回退超时")
                break

        self.module._force_cpu_after_timeout = True
        self.module.config["n_gpu_layers"] = 0
