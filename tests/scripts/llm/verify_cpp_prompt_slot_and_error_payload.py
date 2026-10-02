"""验证 C++ 提示按真实槽位裁剪，且结构化错误不会参与字符串拼接。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _Logger:
    def info(self, *_args) -> None:
        return None

    def error(self, *_args) -> None:
        return None

    def warning(self, *_args) -> None:
        return None


class _Request:
    pass


class _TaskStatus:
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class _Task:
    latest_request = None

    def __init__(self, request) -> None:
        type(self).latest_request = request

    def getTaskId(self) -> str:
        return "verify-task"

    def getStatus(self):
        return _TaskStatus.FAILED

    def getResponse(self):
        return SimpleNamespace(errorMessage="Prompt too long for context")


class _Scheduler:
    def submitTask(self, _task) -> None:
        return None

    def cancelTask(self, _task_id) -> None:
        return None


class _Engine:
    scheduler = _Scheduler()
    _gpu_config = {"max_context_size": 4096}

    def _set_active_cpp_task_id(self, _task_id) -> None:
        return None


async def _run_case() -> int:
    from core.services.scheduler.inference import cpp_llm_handler
    from core.services.scheduler.inference.inference_utils import (
        conservative_estimate_tokens_from_text,
    )
    from core.services.scheduler.utils.resource_utils import (
        resolve_cpp_slot_context,
    )

    fake_bindings = SimpleNamespace(
        LLMInferenceRequest=_Request,
        LLMTask=_Task,
        TaskStatus=_TaskStatus,
    )
    original_get_bindings = cpp_llm_handler._get_scheduler_py
    cpp_llm_handler._get_scheduler_py = lambda: fake_bindings
    try:
        chunks = []
        async for chunk in cpp_llm_handler.submit_cpp_llm_task(
            _Engine(),
            [
                {"role": "system", "content": "你" * 5000},
                {"role": "user", "content": "请回复我" * 500},
            ],
            n_ctx=4096,
            max_chars=0,
            max_tokens=2048,
            temperature=0.7,
            top_p=None,
            top_k=None,
            repetition_penalty=None,
            friendly_llm_error=lambda message: message,
            logger=_Logger(),
            first_token_timeout=2,
        ):
            chunks.append(chunk)
    finally:
        cpp_llm_handler._get_scheduler_py = original_get_bindings

    slot_context = resolve_cpp_slot_context(4096)
    if slot_context != 2044:
        print(f"FAIL: 4096 上下文的 C++ 槽位计算错误: {slot_context}")
        return 1

    request = _Task.latest_request
    if request is None:
        print("FAIL: 验证任务未提交")
        return 2

    prompt_tokens = conservative_estimate_tokens_from_text(request.prompt)
    safe_budget = slot_context - max(64, int(slot_context * 0.05)) - 16
    if prompt_tokens > safe_budget:
        print(
            "FAIL: 提示未按 C++ 单槽位裁剪: "
            f"estimate={prompt_tokens}, budget={safe_budget}"
        )
        return 3

    expected_error = {"error": "Prompt too long for context", "done": True}
    if chunks != [expected_error]:
        print(f"FAIL: 结构化错误未被原样返回: {chunks!r}")
        return 4

    print("PASS: C++ 提示按真实槽位裁剪，结构化错误可安全返回")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run_case()))
