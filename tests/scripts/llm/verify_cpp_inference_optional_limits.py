"""验证 C++ 推理入口会归一化可选生成参数。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _BioSystemManager:
    async def apply_bio_before_infer(self, _prompt: str) -> None:
        return None


class _Engine:
    enabled = True
    _llm_backend = "cpp"
    _gpu_config = {"max_context_size": 4096}
    _gpu_worker_ready = True
    bio_system_manager = _BioSystemManager()

    async def _maybe_switch_cpp_model(self, _model_path) -> bool:
        return False


async def _run_case() -> int:
    from core.services.scheduler.inference import cpp_llm_handler
    from core.services.scheduler.inference.inference_executor import (
        InferenceExecutor,
    )

    captured = SimpleNamespace(max_tokens=None, temperature=None)
    original = cpp_llm_handler.submit_cpp_llm_task

    async def _fake_submit(_engine, _prompt, **kwargs):
        captured.max_tokens = kwargs["max_tokens"]
        captured.temperature = kwargs["temperature"]
        yield "ok"

    cpp_llm_handler.submit_cpp_llm_task = _fake_submit
    try:
        chunks = []
        executor = InferenceExecutor(_Engine())
        async for chunk in executor._submit_llm_task_cpp(
            "hello",
            max_tokens=None,
            temperature=None,
        ):
            chunks.append(chunk)
    finally:
        cpp_llm_handler.submit_cpp_llm_task = original

    if chunks != ["ok"]:
        print(f"FAIL: 推理调用未完成: {chunks!r}")
        return 1
    if captured.max_tokens != 2048:
        print(f"FAIL: max_tokens=None 未归一化: {captured.max_tokens!r}")
        return 2
    if captured.temperature != 0.7:
        print(f"FAIL: temperature=None 未归一化: {captured.temperature!r}")
        return 3

    print("PASS: C++ 推理可安全接收 max_tokens/temperature=None")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run_case()))
