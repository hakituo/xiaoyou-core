import asyncio
import threading
import time
from typing import Any, AsyncGenerator

from .inference_stats import record_llm_inference_stats
from .inference_utils import (
    clamp_messages,
    clamp_text,
    conservative_estimate_tokens_from_text,
    messages_to_text,
)
from ..scheduler_wrapper import _get_scheduler_py
from ..utils.resource_utils import resolve_cpp_slot_context

_COMPLETION_POLL_INTERVAL = 0.05


async def submit_cpp_llm_task(
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
    friendly_llm_error,
    logger,
    **kwargs,
) -> AsyncGenerator[Any, None]:
    if not engine.scheduler:
        raise RuntimeError("C++ Scheduler is not running.")

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    received_any = {"value": False}

    def on_token(text: str):
        if text:
            received_any["value"] = True
            loop.call_soon_threadsafe(queue.put_nowait, (text, False))

    start_time = time.time()
    task = None
    task_finished = False
    _scheduler_py = _get_scheduler_py()
    try:
        req = _scheduler_py.LLMInferenceRequest()
        safe_prompt = prompt
        engine_gpu_config = getattr(engine, "_gpu_config", None)
        gpu_config = engine_gpu_config if isinstance(engine_gpu_config, dict) else {}
        slot_context = resolve_cpp_slot_context(
            n_ctx, gpu_config.get("cache_size")
        )
        reserve = max(64, int(slot_context * 0.05))
        token_budget = max(1, slot_context - reserve - 16)
        if isinstance(safe_prompt, list) and n_ctx > 0:
            base_messages = safe_prompt
            chars_budget = max(256, int(token_budget * 3.0))
            clamped_messages = clamp_messages(base_messages, chars_budget)
            safe_prompt = messages_to_text(clamped_messages)

            while (
                conservative_estimate_tokens_from_text(safe_prompt) > token_budget
                and chars_budget > 256
            ):
                chars_budget = max(256, int(chars_budget * 0.85))
                clamped_messages = clamp_messages(base_messages, chars_budget)
                safe_prompt = messages_to_text(clamped_messages)
        elif isinstance(safe_prompt, list):
            safe_prompt = messages_to_text(safe_prompt)
        if not isinstance(safe_prompt, str):
            safe_prompt = str(safe_prompt)
        if max_chars > 0:
            safe_prompt = clamp_text(safe_prompt, max_chars)

        if n_ctx > 0:
            if conservative_estimate_tokens_from_text(safe_prompt) > token_budget:
                chars_budget = max(256, int(token_budget * 3.0))
                safe_prompt = clamp_text(safe_prompt, chars_budget)
                while (
                    conservative_estimate_tokens_from_text(safe_prompt) > token_budget
                    and chars_budget > 256
                ):
                    chars_budget = max(256, int(chars_budget * 0.85))
                    safe_prompt = clamp_text(safe_prompt, chars_budget)
        req.prompt = safe_prompt

        conversation_id = kwargs.get("conversation_id")
        if conversation_id is None:
            conversation_id = ""
        try:
            req.conversationId = str(conversation_id)
        except Exception:
            pass

        if n_ctx > 0:
            prompt_tokens = conservative_estimate_tokens_from_text(safe_prompt)
            available = slot_context - prompt_tokens - 8
            if available <= 0:
                yield {
                    "error": friendly_llm_error(
                        f"exceed C++ slot context window of {slot_context}"
                    ),
                    "done": True,
                }
                return
            max_tokens = min(max_tokens, max(1, int(available)))

        req.maxTokens = max_tokens
        req.temperature = temperature
        try:
            if top_k is not None:
                req.topK = int(top_k)
        except Exception:
            pass
        try:
            if top_p is not None:
                req.topP = float(top_p)
        except Exception:
            pass
        try:
            if repetition_penalty is not None:
                req.repetitionPenalty = float(repetition_penalty)
        except Exception:
            pass

        req.streamOutput = True
        req.onTokenGenerated = on_token

        task = _scheduler_py.LLMTask(req)
        engine.scheduler.submitTask(task)
        try:
            engine._set_active_cpp_task_id(task.getTaskId())
        except Exception:
            engine._set_active_cpp_task_id(None)

        def wait_completion():
            try:
                while True:
                    status = task.getStatus()
                    if status == _scheduler_py.TaskStatus.COMPLETED:
                        resp = task.getResponse()
                        try:
                            stats = record_llm_inference_stats(
                                engine,
                                backend="cpp",
                                generated_tokens=int(
                                    getattr(resp, "generatedTokens", 0) or 0
                                ),
                                inference_time_s=float(
                                    getattr(resp, "inferenceTime", 0.0) or 0.0
                                ),
                            )
                            logger.info(
                                "C++ LLM 推理统计: tokens=%d, time=%.2fs",
                                stats["generated_tokens"],
                                stats["inference_time_s"],
                            )
                        except Exception:
                            pass

                        if not received_any["value"]:
                            loop.call_soon_threadsafe(
                                queue.put_nowait, (resp.generatedText, True)
                            )
                        else:
                            loop.call_soon_threadsafe(queue.put_nowait, ("", True))
                        return
                    if status == _scheduler_py.TaskStatus.FAILED:
                        try:
                            resp = task.getResponse()
                            msg = resp.errorMessage or "LLM 推理失败"
                        except Exception as e:
                            msg = str(e) or "LLM 推理失败"

                        logger.error("C++ LLM Task Failed: %s", msg)
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            (
                                {"error": friendly_llm_error(msg), "done": True},
                                True,
                            ),
                        )
                        return
                    if status == _scheduler_py.TaskStatus.CANCELLED:
                        loop.call_soon_threadsafe(queue.put_nowait, ("任务已取消", True))
                        return
                    time.sleep(_COMPLETION_POLL_INTERVAL)
            except Exception as e:
                loop.call_soon_threadsafe(
                    queue.put_nowait, (str(e) or "任务执行异常", True)
                )

        monitor_thread = threading.Thread(target=wait_completion, daemon=True)
        monitor_thread.start()

        stop_sequences = kwargs.get("stop") or kwargs.get("stop_sequences") or []
        if isinstance(stop_sequences, str):
            stop_sequences = [stop_sequences]
        if not isinstance(stop_sequences, list):
            stop_sequences = []
        stop_sequences = [str(s) for s in stop_sequences if s]
        max_stop_len = max((len(s) for s in stop_sequences), default=0)
        stop_buffer = ""

        first_item = True
        first_token_timeout = kwargs.get("first_token_timeout")
        if not isinstance(first_token_timeout, (int, float)) or first_token_timeout <= 0:
            try:
                from config.integrated_config import get_settings

                first_token_timeout = get_settings().model.first_token_timeout
            except Exception:
                first_token_timeout = 30.0

        while True:
            if first_item:
                try:
                    text, is_finished = await asyncio.wait_for(
                        queue.get(), timeout=first_token_timeout
                    )
                except asyncio.TimeoutError:
                    logger.error(
                        "CPPSchedulerEngine: C++首token超时 %.1f 秒 (等待 %.4f 秒)",
                        first_token_timeout,
                        time.time() - start_time,
                    )
                    try:
                        if engine.scheduler and task is not None:
                            task_id = task.getTaskId()
                            await asyncio.to_thread(engine.scheduler.cancelTask, task_id)
                    except Exception:
                        pass

                    restart_success = False
                    try:
                        logger.warning("C++调度器GPU推理卡死，尝试重启调度器...")
                        restart_success = await engine._restart_scheduler()
                    except Exception as restart_err:
                        logger.error("重启C++调度器时发生异常: %s", restart_err)

                    if restart_success:
                        yield "GPU推理暂时卡死，已自动重启调度器。请重新发送消息继续对话。"
                    else:
                        yield "本地模型在较长时间内没有产生任何输出，请尝试重启模型或缩短输入。"
                    break
                first_item = False
            else:
                text, is_finished = await queue.get()

            if isinstance(text, dict):
                yield text
                if is_finished or text.get("done"):
                    task_finished = True
                    break
                continue

            if text:
                if not isinstance(text, str):
                    text = str(text)
                stop_buffer += text
                stop_hit = False
                stop_idx = -1
                for seq in stop_sequences:
                    idx = stop_buffer.find(seq)
                    if idx != -1 and (stop_idx == -1 or idx < stop_idx):
                        stop_idx = idx
                        stop_hit = True

                if stop_hit:
                    valid_part = stop_buffer[:stop_idx]
                    if valid_part:
                        yield valid_part
                    is_finished = True
                    task_finished = True
                    try:
                        if engine.scheduler and task is not None:
                            task_id = task.getTaskId()
                            await asyncio.to_thread(engine.scheduler.cancelTask, task_id)
                    except Exception:
                        pass
                    break

                if len(stop_buffer) > max_stop_len:
                    safe_len = len(stop_buffer) - max_stop_len
                    to_yield = stop_buffer[:safe_len]
                    stop_buffer = stop_buffer[safe_len:]
                    yield to_yield

            if is_finished:
                if stop_buffer:
                    yield stop_buffer
                task_finished = True
                break
    except Exception as e:
        logger.error("Failed to submit task to C++ Scheduler: %s", e)
        raise
    finally:
        try:
            if not task_finished and engine.scheduler and task is not None:
                task_id = task.getTaskId()
                await asyncio.to_thread(engine.scheduler.cancelTask, task_id)
        except Exception:
            pass

        engine._set_active_cpp_task_id(None)
