"""
真流式验证脚本：验证 stream_chat_impl 在短 chunk 逐块到达时，
token 事件是否实时逐块 yield（而非积压到最后一次性吐出）。

模拟 LLM 每 0.3 秒吐出 3 个字符，共 10 个 chunk（30 字符）。
若为真流式：每个 chunk 到达后立即有对应 token yield；
若为伪流式：所有 token 积压到最后一次 yield。

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\streaming_refactor\\verify_true_streaming.py
"""
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


class DummyEmotionManager:
    def ingest_life_stats(self, *args, **kwargs):
        return None

    def process_text(self, *args, **kwargs):
        return None

    def build_dialogue_affect_instruction(self, **kwargs):
        return ""


class DummyToolRegistry:
    def __init__(self, tool=None):
        self._tool = tool

    def get_active_tools(self):
        return []

    def get_openai_tools(self, *args, **kwargs):
        return None

    def get_tool(self, name):
        return self._tool


class SlowLLM:
    """模拟真流式：每 interval 秒 yield 一个短 dict chunk（与真实 LLM 客户端一致）"""
    def __init__(self, chunks, interval=0.3):
        self.chunks = chunks
        self.interval = interval
        self.call_index = 0

    def get_current_model_name(self):
        return "local"

    async def stream_chat(self, **kwargs):
        turn = self.chunks[min(self.call_index, len(self.chunks) - 1)]
        self.call_index += 1
        for c in turn:
            await asyncio.sleep(self.interval)
            yield {"content": c}


class DummyAgent:
    def __init__(self, llm, tool=None):
        self.is_initialized = True
        self.llm_module = llm
        self.dependency_manager = None
        self.tool_registry = DummyToolRegistry(tool)
        self.emotion_manager = DummyEmotionManager()

    async def initialize(self):
        self.is_initialized = True

    async def _build_conversation_history(self, user_id, message, model_hint=None, **kwargs):
        return [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": str(message)},
        ]

    async def _check_daily_routine(self, user_id):
        return None

    async def _save_conversation_history(self, **kwargs):
        return None


def _patch_light_dependencies():
    from core.agents.chat_agent_components import streaming as sm
    import core.services.journal.service as journal_module
    import core.services.active_care.shared.reminder_injection as reminder_module

    async def fake_detect_sensitive_mode(*args, **kwargs):
        return False

    sm.StreamContextBuilder.detect_sensitive_mode = staticmethod(fake_detect_sensitive_mode)
    sm.StreamContextBuilder.detect_wants_long = staticmethod(lambda msg: False)

    async def fake_process_all(*args, **kwargs):
        return {
            "life_stats": {},
            "sensory_feedback": None,
            "behavior_chain": None,
            "dep_result": {"new_unlocks": []},
            "triggered_defects": [],
        }

    sm.ParallelProcessor.process_all = staticmethod(fake_process_all)

    async def _none(*args, **kwargs):
        return None

    journal_module.get_journal_service = lambda: SimpleNamespace(
        get_tomorrow_tone=_none,
        get_plan=_none,
        format_plan_for_injection=lambda plan: "",
    )

    class _EmptyStore:
        async def get_and_clear(self):
            return None

    reminder_module.get_reminder_injection_store = lambda: _EmptyStore()


async def verify_true_streaming():
    from core.agents.chat_agent_components.streaming import stream_chat_impl

    # 模拟 10 个短 chunk，每 3 字符，间隔 0.3s
    chunks = ["这是", "一段", "流式", "输出", "的测", "试文", "本，", "用于", "验证", "时序"]
    EXPECTED_TOTAL = sum(len(c) for c in chunks)
    llm = SlowLLM([chunks], interval=0.3)
    agent = DummyAgent(llm)

    print("=" * 60)
    print("真流式时序验证（每个 chunk 间隔 0.3s）")
    print("=" * 60)

    t0 = time.time()
    token_count = 0
    yield_windows = {}  # 记录每个时间窗口产出的 token

    async for chunk in stream_chat_impl(
        agent=agent,
        user_id="verify_user",
        message="测试",
        save_history=False,
        model_hint="local",
    ):
        elapsed = time.time() - t0
        if chunk.get("type") == "token":
            token_count += 1
            window = round(elapsed * 2) / 2  # 0.5s 粒度窗口
            yield_windows.setdefault(window, []).append(chunk["content"])
            print(f"[+{elapsed:5.2f}s] token={chunk['content']!r}")
        elif chunk.get("type") == "response_reset":
            print(f"[+{elapsed:5.2f}s] *** response_reset ***")
        elif chunk.get("done"):
            print(f"[+{elapsed:5.2f}s] done content={chunk.get('content', '')!r}")

    print("-" * 60)
    print(f"总 token 数: {token_count}")
    print(f"token 分布（按0.5s窗口）: {dict((k, ''.join(v)) for k, v in sorted(yield_windows.items()))}")
    total_time = time.time() - t0
    print(f"总耗时: {total_time:.2f}s")

    # 判定：若 token 分布在多个时间窗口（>2个窗口）则为真流式
    n_windows = len(yield_windows)
    if n_windows >= 3:
        print(f"\n✅ 真流式生效: token 分散在 {n_windows} 个时间窗口逐块产出")
    elif n_windows == 2:
        print(f"\n⚠️ 部分流式: token 集中在 {n_windows} 个窗口，仍有明显积压")
    else:
        print(f"\n❌ 仍是伪流式: 所有 token 在 {n_windows} 个窗口内一次性产出")
        print("   排查: [TT] 日志中 _consume_pending hold/release 是否异常扣留")
    print("=" * 60)

    assert token_count == EXPECTED_TOTAL, f"应产出{EXPECTED_TOTAL}个token，实际{token_count}"


async def main():
    _patch_light_dependencies()
    await verify_true_streaming()
    print("\n验证完成")


if __name__ == "__main__":
    asyncio.run(main())
