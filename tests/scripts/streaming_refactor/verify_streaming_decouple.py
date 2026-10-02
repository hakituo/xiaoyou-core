"""
streaming.py 解耦重构验证脚本
验证 streaming_pipeline 解耦后 stream_chat_impl 行为与重构前一致：
1. 时间戳前缀剥离 + [EMO:]/[TOPIC:] 标签解析
2. <think> 思考内容分离，不泄漏到可见回复
3. [TOOL_USE:] 中间轮次内容丢弃，只输出最终轮次回复
4. done 事件包含 content/emotion/thought 字段

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\streaming_refactor\\verify_streaming_decouple.py
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

# 项目根目录加入 sys.path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


class DummyEmotionManager:
    def ingest_life_stats(self, *args, **kwargs):
        return None

    def process_text(self, *args, **kwargs):
        return None

    def build_dialogue_affect_instruction(self, **kwargs):
        return ""


class EchoTool:
    """记录调用次数的假工具"""
    def __init__(self):
        self.run_count = 0

    def set_runtime_context(self, ctx):
        pass

    async def run(self, **kwargs):
        self.run_count += 1
        return "echo结果"


class DummyToolRegistry:
    def __init__(self, tool=None):
        self._tool = tool

    def get_active_tools(self):
        return []

    def get_openai_tools(self, *args, **kwargs):
        return None

    def get_tool(self, name):
        return self._tool


class ScriptedLLM:
    """按调用次数返回预设 chunk 序列的假 LLM"""
    def __init__(self, turns):
        self.turns = turns
        self.call_index = 0

    def get_current_model_name(self):
        return "local"

    async def stream_chat(self, **kwargs):
        turn = self.turns[min(self.call_index, len(self.turns) - 1)]
        self.call_index += 1
        for chunk in turn:
            yield chunk


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
    """屏蔽 BERT / journal / active care 等重依赖，保持脚本轻量"""
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


async def collect(agent, message):
    from core.agents.chat_agent_components.streaming import stream_chat_impl
    events = []
    async for chunk in stream_chat_impl(
        agent=agent,
        user_id="verify_user",
        message=message,
        save_history=False,
        model_hint="local",
    ):
        events.append(chunk)
        if chunk.get("done") is True:
            break
    return events


def tokens_of(events):
    return "".join(e.get("content", "") for e in events if e.get("type") == "token")


async def case1_timestamp_and_tags():
    """时间戳前缀剥离 + EMO/TOPIC 标签解析"""
    llm = ScriptedLLM([[
        {"content": "[12:34] 你好"},
        {"content": "呀[EMO:开心]"},
        {"content": "[TOPIC:问候]"},
    ]])
    events = await collect(DummyAgent(llm), "在吗")
    done = events[-1]
    assert tokens_of(events) == "你好呀", f"可见token异常: {tokens_of(events)!r}"
    assert done["content"] == "你好呀", f"done content异常: {done['content']!r}"
    assert done["emotion"] == "开心", f"emotion异常: {done['emotion']!r}"
    print("[PASS] case1 时间戳剥离 + EMO/TOPIC 标签解析")


async def case2_think_separation():
    """<think> 思考内容分离（reasoning 字段路径）"""
    # 真实云模型通过 reasoning 字段分离思考内容
    llm = ScriptedLLM([[
        {"reasoning": "内部推理过程"},
        {"content": "正式回复内容"},
    ]])
    events = await collect(DummyAgent(llm), "问题")
    done = events[-1]
    assert done["content"] == "正式回复内容", f"content异常: {done['content']!r}"
    assert done["thought"] == "内部推理过程", f"thought异常: {done['thought']!r}"
    assert "内部推理" not in tokens_of(events), "思考内容泄漏到可见token"
    print("[PASS] case2 <think> 思考内容分离（reasoning 字段）")


async def case3_tool_use_turn_discard():
    """[TOOL_USE:] 中间轮次内容丢弃，只输出最终轮次"""
    tool = EchoTool()
    llm = ScriptedLLM([
        # 第1轮：中间文本 + 工具调用（应被丢弃）
        [{"content": '中间轮文本[TOOL_USE:{"name":"echo","arguments":{}}]'}],
        # 第2轮：最终回复
        [{"content": "基于工具结果的最终回复"}],
    ])
    events = await collect(DummyAgent(llm, tool=tool), "查一下")
    done = events[-1]
    assert tool.run_count == 1, f"工具应执行1次，实际{tool.run_count}次"
    assert done["content"] == "基于工具结果的最终回复", f"content异常: {done['content']!r}"
    assert "中间轮文本" not in tokens_of(events), "中间轮次文本泄漏给用户"
    print("[PASS] case3 [TOOL_USE:] 中间轮次内容丢弃")


async def case4_compat_exports():
    """兼容导出检查：旧引用点仍可用"""
    from core.agents.chat_agent_components.streaming import (
        _extract_image_request_prompt,
        _resolve_model_by_persona,  # noqa: F401
        StreamContextBuilder,  # noqa: F401
        ParallelProcessor,  # noqa: F401
        stream_chat_impl,  # noqa: F401
    )
    prompt = await _extract_image_request_prompt("帮我画一只猫")
    assert prompt and "猫" in prompt, f"图片意图提取异常: {prompt!r}"
    print("[PASS] case4 兼容导出检查")


async def main():
    _patch_light_dependencies()
    await case1_timestamp_and_tags()
    await case2_think_separation()
    await case3_tool_use_turn_discard()
    await case4_compat_exports()
    print("\n全部验证通过：streaming.py 解耦重构行为一致")


if __name__ == "__main__":
    asyncio.run(main())
