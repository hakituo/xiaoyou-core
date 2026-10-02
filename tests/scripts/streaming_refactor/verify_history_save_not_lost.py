"""
验证流式对话历史落库不丢失。

背景：08-18 真流式改造把 `asyncio.create_task(_save_conversation_history)` 移到
`yield {"done": True}` 之后，但消费端（stream_orchestrator 收到 done 后 break、
WS 适配器收到 response_done 后 break）会丢弃 async 生成器引用，asyncio 的
asyncgen finalizer 随后调度 aclose()，GeneratorExit 抛在 yield done 处，
yield 之后裸写的保存代码永远不执行 → 正常对话完全不写入短期记忆。

修复：保存调度放入 yield done 的 try/finally，无论消费者完整消费还是
break/aclose，保存任务都一定被调度。

本脚本验证三种路径：
1. 完整消费（生成器自然结束）→ 保存被调度
2. 收到 done 后 break（单层，直接消费 stream_chat_impl）→ 保存被调度
3. 收到 done 后 break（两层转发包装，最接近真实链路）→ 保存被调度

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\streaming_refactor\\verify_history_save_not_lost.py
"""
import asyncio
import gc
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.agents.chat_agent_components.streaming import stream_chat_impl  # noqa: E402

# 记录 _save_conversation_history 是否被调用及入参
SAVE_CALLS = []


class DummyEmotionManager:
    def ingest_life_stats(self, *args, **kwargs):
        return None

    def process_text(self, *args, **kwargs):
        return None

    def build_dialogue_affect_instruction(self, **kwargs):
        return ""


class DummyToolRegistry:
    def get_active_tools(self):
        return []

    def get_openai_tools(self, *args, **kwargs):
        return None

    def get_tool(self, name):
        return None


class SimpleLLM:
    """模拟单轮返回若干 chunk，不触发工具调用"""

    def __init__(self, chunks):
        self.chunks = chunks
        self.call_index = 0

    def get_current_model_name(self):
        return "local"

    async def stream_chat(self, **kwargs):
        turn = self.chunks[min(self.call_index, len(self.chunks) - 1)]
        self.call_index += 1
        for c in turn:
            yield {"content": c}


class DummyAgent:
    def __init__(self, llm):
        self.is_initialized = True
        self.llm_module = llm
        self.dependency_manager = None
        self.tool_registry = DummyToolRegistry()
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
        SAVE_CALLS.append(kwargs)
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


def _new_agent():
    llm = SimpleLLM(["这是一段用于验证落库的回复"])
    return DummyAgent(llm)


async def _consume_normally(agent):
    """路径1：完整消费，不 break"""
    done_count = 0
    async for chunk in stream_chat_impl(
        agent=agent,
        user_id="verify_user",
        message="测试",
        save_history=True,
        model_hint="local",
    ):
        if chunk.get("done"):
            done_count += 1
    return done_count


async def _consume_break(agent):
    """路径2：收到 done 后 break（模拟 stream_orchestrator.py:190 的 break）"""
    done_count = 0
    gen = stream_chat_impl(
        agent=agent,
        user_id="verify_user",
        message="测试",
        save_history=True,
        model_hint="local",
    )
    async for chunk in gen:
        if chunk.get("done"):
            done_count += 1
            break
    return done_count


async def _forwarding_wrapper(agent):
    """转发包装层，模拟 chat_agent.stream_chat / response_generator 的转发链路"""
    async for chunk in stream_chat_impl(
        agent=agent,
        user_id="verify_user",
        message="测试",
        save_history=True,
        model_hint="local",
    ):
        yield chunk


async def _consume_two_layers_break(agent):
    """路径3：两层转发后收到 done 才 break，最接近真实链路"""
    done_count = 0
    async for chunk in _forwarding_wrapper(agent):
        if chunk.get("done"):
            done_count += 1
            break
    return done_count


async def _run_case(name, consumer):
    before = len(SAVE_CALLS)
    done_count = await consumer()
    # 让 asyncgen finalizer 调度的 aclose 任务与保存任务跑完
    gc.collect()
    await asyncio.sleep(0.3)
    after = len(SAVE_CALLS)
    ok = after > before and done_count == 1
    print(f"[{name}] done_chunk={done_count} save_called={'是' if after > before else '否'}")
    if not ok:
        print(f"    ❌ 失败：保存任务未被调度（before={before}, after={after}）")
        return False
    print(f"    ✅ 通过：保存任务已调度（assistant_msg={SAVE_CALLS[-1].get('assistant_msg')!r}）")
    return True


async def main():
    _patch_light_dependencies()

    print("=" * 60)
    print("流式对话历史落库不丢失验证")
    print("=" * 60)

    results = [
        await _run_case("完整消费", lambda: _consume_normally(_new_agent())),
        await _run_case("收到done后break(单层)", lambda: _consume_break(_new_agent())),
        await _run_case("收到done后break(两层转发)", lambda: _consume_two_layers_break(_new_agent())),
    ]

    print("-" * 60)
    if all(results):
        print("✅ 全部通过：三种消费路径下历史保存任务均被调度")
        return 0
    print("❌ 存在失败用例：历史保存可能在生成器被 aclose 时静默丢失")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
