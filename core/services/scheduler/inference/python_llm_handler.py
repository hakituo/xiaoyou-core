import asyncio
import threading
import time
from typing import Any, AsyncGenerator

from .inference_stats import record_llm_inference_stats
from .inference_utils import (
    clamp_text,
    estimate_prompt_tokens,
    fallback_estimate_messages_tokens,
    rough_estimate_tokens_from_text,
    trim_messages_for_ctx,
)

# P1-2: 跟踪推理监控 fire-and-forget 任务，防止被 GC 后超时无法检测
_monitor_tasks: set = set()


def _spawn_monitor_task(coro) -> None:
    """P1-2: 提交推理监控任务并保存引用，完成后自动清理。"""
    task = asyncio.create_task(coro)
    _monitor_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _monitor_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            # 监控任务异常不应影响主流程，仅记录日志
            from core.utils.logger import get_logger as _get_logger
            _get_logger(__name__).error(
                "推理监控任务异常: %r", exc, exc_info=exc
            )

    task.add_done_callback(_on_done)


async def submit_python_llm_task(
    engine: Any,
    prompt: Any,
    *,
    n_ctx: int,
    max_chars: int,
    max_tokens: int,
    temperature: float,
    top_p: Any,
    top_k: Any,
    repetition_penalty: Any,
    min_p: Any,
    prompt_to_text,
    friendly_llm_error,
    logger,
    **kwargs,
) -> AsyncGenerator[Any, None]:
    if not engine._gpu_config:
        raise RuntimeError("LLM 配置缺失，无法执行推理")

    async with engine._llm_setup_lock:
        requested_model_path = kwargs.get("model_path")
        if (
            isinstance(requested_model_path, str)
            and requested_model_path
            and requested_model_path.lower().endswith(".gguf")
            and isinstance(engine._gpu_config, dict)
        ):
            current_model_path = str(engine._gpu_config.get("model_path") or "")
            if current_model_path != requested_model_path:
                engine._gpu_config["model_path"] = requested_model_path
                engine._python_force_cpu = False
                engine._gpu_config.pop("force_cpu", None)
                if engine.llm is not None:
                    engine.llm = None

        if not engine.llm and engine._gpu_config:
            from core.resource_manager import get_resource_manager

            resource_manager = get_resource_manager()
            await resource_manager.prepare_for_heavy_task("llm")
            load_timeout = 60.0
            try:
                from config.integrated_config import get_settings

                load_timeout = float(get_settings().model.model_load_timeout)
            except Exception:
                load_timeout = 60.0

            try:
                cooldown = 20.0
                if engine._last_llm_load_error and (
                    time.time() - engine._last_llm_load_ts
                ) < cooldown:
                    yield friendly_llm_error(engine._last_llm_load_error)
                    return
                await asyncio.wait_for(
                    asyncio.shield(engine._reload_llm()), timeout=load_timeout
                )
            except asyncio.TimeoutError:
                yield "本地模型正在加载中，请稍后再试一次。"
                return

        if (
            engine.llm
            and engine._python_force_cpu
            and isinstance(engine._gpu_config, dict)
            and not engine._gpu_config.get("force_cpu")
            and not kwargs.get("force_cpu")
        ):
            try:
                logger.info("检测到 LLM 运行在 CPU 模式，尝试回迁 GPU 以提升性能...")
                await engine.restore_llm_to_gpu()
            except Exception as e:
                logger.warning(f"尝试回迁 GPU 失败 (将继续使用 CPU): {e}")

        if not engine.llm:
            raise RuntimeError(
                friendly_llm_error(
                    engine._last_llm_load_error or "failed to load model from file"
                )
            )

        from core.resource_manager import get_resource_manager

        resource_manager = get_resource_manager()
        t_prep_start = time.time()
        await resource_manager.prepare_for_heavy_task("llm")
        logger.info(
            "DEBUG: prepare_for_heavy_task took %.4fs",
            time.time() - t_prep_start,
        )

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        start_time = time.time()
        llm_instance = engine.llm
        stop_event = threading.Event()
        engine._set_active_python_stop_event(stop_event)

        try:

            def run_inference():
                try:
                    if isinstance(prompt, list):
                        messages = prompt
                    else:
                        messages = [{"role": "user", "content": str(prompt)}]

                    logger.info("CPPSchedulerEngine: 开始Python侧LLM推理")
                    logger.info(
                        "CPPSchedulerEngine: 推理参数 - max_tokens=%s, temperature=%s, n_ctx=%s",
                        max_tokens,
                        temperature,
                        n_ctx,
                    )
                    logger.info(
                        "CPPSchedulerEngine: 模型状态 - use_mmap=%s, n_gpu_layers=%s",
                        getattr(engine, "_last_llm_use_mmap", None),
                        engine._gpu_config.get("n_gpu_layers")
                        if isinstance(engine._gpu_config, dict)
                        else None,
                    )
                    effective_max_tokens = max_tokens
                    ctx_limit = n_ctx
                    if ctx_limit <= 0 and hasattr(llm_instance, "n_ctx"):
                        try:
                            ctx_limit = int(llm_instance.n_ctx())
                        except Exception:
                            pass

                    if ctx_limit and ctx_limit > 0:
                        reserve = max(256, int(ctx_limit * 0.15))
                        messages = trim_messages_for_ctx(
                            llm_instance, messages, ctx_limit, reserve
                        )

                        prompt_tokens = estimate_prompt_tokens(llm_instance, messages)
                        if prompt_tokens is None:
                            prompt_tokens = fallback_estimate_messages_tokens(messages)

                        if isinstance(prompt_tokens, int) and prompt_tokens >= 0:
                            overhead = 96 + (len(messages) * 16)
                            available = ctx_limit - prompt_tokens - overhead

                            if available < 128:
                                logger.warning(
                                    "Context window tight (available=%s), performing aggressive trimming.",
                                    available,
                                )
                                aggressive_reserve = max(384, int(ctx_limit * 0.25))
                                messages = trim_messages_for_ctx(
                                    llm_instance,
                                    messages,
                                    ctx_limit,
                                    aggressive_reserve,
                                )
                                prompt_tokens = estimate_prompt_tokens(
                                    llm_instance, messages
                                )
                                if prompt_tokens is None:
                                    prompt_tokens = fallback_estimate_messages_tokens(
                                        messages
                                    )
                                overhead = 96 + (len(messages) * 16)
                                available = ctx_limit - prompt_tokens - overhead

                            if available <= 0:
                                loop.call_soon_threadsafe(
                                    queue.put_nowait,
                                    (
                                        {
                                            "error": friendly_llm_error(
                                                f"exceed context window of {ctx_limit}"
                                            ),
                                            "done": True,
                                        },
                                        True,
                                    ),
                                )
                                return

                            effective_max_tokens = min(
                                effective_max_tokens, max(1, int(available))
                            )
                            logger.info(
                                "Final inference: prompt_tokens=%s, overhead=%s, max_tokens=%s",
                                prompt_tokens,
                                overhead,
                                effective_max_tokens,
                            )

                    llama_kwargs = {
                        "max_tokens": effective_max_tokens,
                        "temperature": temperature,
                        "stream": True,
                    }
                    if top_p is not None:
                        llama_kwargs["top_p"] = top_p
                    if top_k is not None:
                        llama_kwargs["top_k"] = top_k
                    if repetition_penalty is not None:
                        llama_kwargs["repeat_penalty"] = repetition_penalty
                    if min_p is not None:
                        llama_kwargs["min_p"] = min_p

                    try:
                        stream = llm_instance.create_chat_completion(
                            messages=messages,
                            **llama_kwargs,
                        )
                    except TypeError as e:
                        lowered = str(e).lower()
                        for key in ("min_p", "top_k"):
                            if (
                                key in llama_kwargs
                                and "unexpected keyword" in lowered
                                and key in lowered
                            ):
                                llama_kwargs.pop(key, None)
                        logger.info(
                            "Calling create_chat_completion with kwargs: %s",
                            list(llama_kwargs.keys()),
                        )
                        t1_infer = time.time()
                        logger.info(
                            "CPPSchedulerEngine: 调用 create_chat_completion，消息数: %s",
                            len(messages),
                        )
                        stream = llm_instance.create_chat_completion(
                            messages=messages,
                            **llama_kwargs,
                        )
                        stream_create_time = time.time() - t1_infer
                        logger.info(
                            "CPPSchedulerEngine: Stream created in %.4fs",
                            stream_create_time,
                        )
                        if stream_create_time > 10.0:
                            logger.warning(
                                "CPPSchedulerEngine: Stream创建耗时过长(%.2fs)，可能存在性能问题",
                                stream_create_time,
                            )

                    count = 0
                    for chunk in stream:
                        if stop_event.is_set():
                            break
                        delta = chunk["choices"][0]["delta"]
                        if "content" not in delta:
                            continue
                        content = delta["content"]
                        if not content:
                            continue
                        if count == 0:
                            logger.info(
                                "CPPSchedulerEngine: 首个token耗时 %.4f 秒",
                                time.time() - start_time,
                            )
                        count += 1
                        loop.call_soon_threadsafe(queue.put_nowait, (content, False))

                    logger.info(
                        "CPPSchedulerEngine: 任务流生成完成，共计 %d 个 token",
                        count,
                    )
                    record_llm_inference_stats(
                        engine,
                        backend="python",
                        generated_tokens=count,
                        inference_time_s=time.time() - start_time,
                        is_cpu_infer=bool(engine._python_force_cpu),
                    )
                    loop.call_soon_threadsafe(queue.put_nowait, (None, True))
                except Exception as e:
                    logger.error(
                        "CPPSchedulerEngine: 推理线程发生异常: %s",
                        str(e),
                        exc_info=True,
                    )
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        ({"error": friendly_llm_error(str(e)), "done": True}, True),
                    )

            inference_start_time = time.time()
            logger.info(
                "CPPSchedulerEngine: 提交推理任务到线程池，开始时间: %.4f",
                inference_start_time,
            )
            future = loop.run_in_executor(engine._llm_executor, run_inference)

            async def monitor_inference(future_ref, start_time_ref):
                check_interval = 5.0
                max_wait = 300.0
                waited = 0.0
                while waited < max_wait:
                    await asyncio.sleep(check_interval)
                    waited += check_interval
                    if future_ref.done():
                        break
                    logger.info(
                        "CPPSchedulerEngine: 推理任务仍在运行中，已耗时: %.2f秒",
                        time.time() - start_time_ref,
                    )
                if not future_ref.done():
                    logger.warning(
                        "CPPSchedulerEngine: 推理任务超时（%.1f秒），可能已卡死",
                        max_wait,
                    )

            _spawn_monitor_task(monitor_inference(future, inference_start_time))

            first_token_timeout = kwargs.get("first_token_timeout")
            if (
                not isinstance(first_token_timeout, (int, float))
                or first_token_timeout <= 0
            ):
                try:
                    from config.integrated_config import get_settings

                    first_token_timeout = get_settings().model.first_token_timeout
                except Exception:
                    first_token_timeout = 30.0

            is_cpu_infer = bool(engine._python_force_cpu)
            if not is_cpu_infer:
                n_gpu_layers_cfg = None
                if isinstance(engine._gpu_config, dict):
                    try:
                        n_gpu_layers_cfg = int(engine._gpu_config.get("n_gpu_layers", -1))
                    except Exception:
                        n_gpu_layers_cfg = None

                if n_gpu_layers_cfg == 0:
                    is_cpu_infer = True
                elif n_gpu_layers_cfg is not None and n_gpu_layers_cfg < 0:
                    try:
                        from llama_cpp import llama_cpp as _llama_cpp

                        supports = getattr(
                            _llama_cpp, "llama_supports_gpu_offload", None
                        )
                        if callable(supports) and not bool(supports()):
                            is_cpu_infer = True
                    except Exception:
                        try:
                            import torch

                            if not torch.cuda.is_available():
                                is_cpu_infer = True
                        except Exception:
                            is_cpu_infer = True

            if is_cpu_infer and float(first_token_timeout) < 20.0:
                logger.info(
                    "检测到 CPU 推理模式，自动将 first_token_timeout 从 %.1fs 放宽到 30.0s",
                    first_token_timeout,
                )
                first_token_timeout = 30.0

            try:
                prompt_text_for_timeout = prompt_to_text(prompt)
                if max_chars > 0:
                    prompt_text_for_timeout = clamp_text(
                        prompt_text_for_timeout, max_chars
                    )
                est_tokens = rough_estimate_tokens_from_text(prompt_text_for_timeout)
                if est_tokens > 0:
                    scaled = 10.0 + (float(est_tokens) / 15.0)
                    if is_cpu_infer:
                        scaled = max(scaled, 30.0 + (float(est_tokens) / 10.0))
                    first_token_timeout = max(
                        float(first_token_timeout),
                        min(120.0, float(scaled)),
                    )
            except Exception:
                pass

            first_item = True
            while True:
                if first_item:
                    try:
                        text, is_finished = await asyncio.wait_for(
                            queue.get(), timeout=first_token_timeout
                        )
                    except asyncio.TimeoutError:
                        logger.error(
                            "CPPSchedulerEngine: 首token超时 %.1f 秒 (等待 %.4f 秒)",
                            first_token_timeout,
                            time.time() - start_time,
                        )
                        try:
                            stop_event.set()
                        except Exception:
                            pass
                        yield {
                            "error": (
                                "本地模型在较长时间内没有产生任何输出，"
                                "请尝试重启模型或缩短输入。"
                            ),
                            "done": True,
                        }
                        break
                    first_item = False
                else:
                    text, is_finished = await queue.get()

                if text:
                    yield text
                if is_finished:
                    break
            return
        finally:
            engine._clear_active_python_stop_event(stop_event)
