#!/usr/bin/env python3
"""验证清除短期记忆会同步清除 C++ 会话 KV Cache。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def verify_cpp_contract() -> None:
    worker_header = _read("cpp_modules/cpp_scheduler/workers/gpu_llm_worker.h")
    worker_source = _read("cpp_modules/cpp_scheduler/workers/gpu_llm_worker.cpp")
    llama_header = _read("cpp_modules/cpp_scheduler/workers/llama_model_impl.h")
    llama_inference = _read("cpp_modules/cpp_scheduler/workers/llama_model_impl.cpp")
    llama_cache = _read("cpp_modules/cpp_scheduler/workers/llama_model_cache.cpp")
    llama_lifecycle = _read(
        "cpp_modules/cpp_scheduler/workers/llama_model_lifecycle.cpp"
    )
    llama_runtime = _read("cpp_modules/cpp_scheduler/workers/llama_model_runtime.cpp")
    bindings = _read("cpp_modules/cpp_scheduler/bindings/python_bindings.cpp")

    assert "clearConversationCache" in worker_header
    assert "GPULLMWorker::clearConversationCache" in worker_source
    assert "clearConversationCache(const std::string& conversationId) override" in llama_header
    assert "LlamaCppModel::clearConversationCache" in llama_cache
    assert '.def("clearConversationCache"' in bindings

    # llama.cpp 明确允许局部删除失败；失败时必须整条清空并从位置 0 重算。
    assert "const bool partial_removed = llama_memory_seq_rm" in llama_inference
    assert "if (partial_removed)" in llama_inference
    assert "cached_tokens->clear();" in llama_inference
    assert "common = 0;" in llama_inference

    # 防止生命周期、会话缓存和运行时辅助重新回流到单个实现文件。
    assert "LlamaCppModel::initialize" in llama_lifecycle
    assert "LlamaCppModel::getSeqId" in llama_cache
    assert "LlamaCppModel::decodeWithTimeout" in llama_runtime
    assert "LlamaCppModel::generate" in llama_inference
    assert len(llama_inference.splitlines()) < 650


async def verify_python_bridge() -> None:
    from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

    class FakeWorker:
        def __init__(self) -> None:
            self.cleared_ids: list[str] = []

        def clearConversationCache(self, conversation_id: str) -> bool:
            self.cleared_ids.append(conversation_id)
            return True

    engine = object.__new__(CPPSchedulerEngine)
    engine._llm_backend = "cpp"
    engine._gpu_llm_worker = FakeWorker()

    assert await engine.clear_conversation_cache(" private_123 ") is True
    assert engine._gpu_llm_worker.cleared_ids == ["private_123"]
    assert await engine.clear_conversation_cache("") is False


def verify_history_hook() -> None:
    history_source = _read("core/agents/chat_agent_components/history.py")
    delete_swap_index = history_source.index("delete_kvswap_file")
    clear_runtime_index = history_source.index("clear_conversation_cache")
    assert delete_swap_index < clear_runtime_index


def main() -> None:
    verify_cpp_contract()
    asyncio.run(verify_python_bridge())
    verify_history_hook()
    print("PASS: 短期记忆清理已接通 C++ 会话 KV Cache，并包含 M-RoPE 回退。")


if __name__ == "__main__":
    main()
