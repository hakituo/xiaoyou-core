import asyncio
import tempfile
from pathlib import Path

from clients.bots.qq.utils import _allowed_emoji_cache, strip_ooc_emoji
from core.agents.chat_agent_components import history as history_mod
from core.agents.chat_agent_components.history import save_conversation_history
from core.services.chat_history_store import ChatHistoryStore


def test_strip_ooc_emoji_filters_all_when_persona_has_no_allowed_emoji():
    _allowed_emoji_cache.clear()
    _allowed_emoji_cache["test_wangling"] = set()

    result = strip_ooc_emoji("好开心🎉 但是也有点😣", "test_wangling")

    assert result == "好开心 但是也有点"
    _allowed_emoji_cache.clear()


def test_strip_ooc_emoji_removes_ellipsis():
    """测试省略号删除：单个省略号和连续省略号。"""
    _allowed_emoji_cache.clear()
    _allowed_emoji_cache["test_wangling"] = set()

    # 单个中文省略号
    result = strip_ooc_emoji("嗯…好的", "test_wangling")
    assert result == "嗯好的"

    # 连续省略号
    result = strip_ooc_emoji("嗯……好的", "test_wangling")
    assert result == "嗯好的"

    # 混合情况：emoji + 省略号
    result = strip_ooc_emoji("好开心🎉……", "test_wangling")
    assert result == "好开心"

    _allowed_emoji_cache.clear()


def test_strip_ooc_emoji_removes_ellipsis_when_persona_load_failed():
    """测试人设加载失败时仍然删除省略号。"""
    _allowed_emoji_cache.clear()

    result = strip_ooc_emoji("嗯…好的……", "missing_persona_for_test")
    # 人设加载失败时，emoji保留，但省略号仍被删除
    assert result == "嗯好的"


def test_strip_ooc_emoji_keeps_text_when_persona_load_failed():
    _allowed_emoji_cache.clear()

    result = strip_ooc_emoji("好开心🎉", "missing_persona_for_test")

    assert result == "好开心🎉"


def test_save_conversation_history_filters_assistant_ooc_emoji():
    class DummyMemoryManager:
        def __init__(self):
            self.calls = []

        def add_memory(self, **kwargs):
            self.calls.append(kwargs)
            return f"mid-{len(self.calls)}"

        def _schedule_save(self):
            return None

    class DummyAgent:
        def __init__(self):
            self.mm = DummyMemoryManager()
            self.llm_module = None

        def _get_memory_manager(self, user_id):
            return self.mm

        def _is_study_mode(self, message, model_hint=None):
            return False

    async def _run():
        _allowed_emoji_cache.clear()
        _allowed_emoji_cache["test_wangling"] = set()

        tmpdir = tempfile.mkdtemp(prefix="wangling-emoji-history-")
        history_mod.get_chat_history_store = lambda: ChatHistoryStore(Path(tmpdir))

        agent = DummyAgent()
        await save_conversation_history(
            agent=agent,
            user_id="debug_user",
            user_msg="测试",
            assistant_msg="好开心🎉",
            message_id="msg-1",
            persona_filename="test_wangling",
        )

        assert agent.mm.calls[1]["content"] == "好开心"
        stored_file = next(Path(tmpdir).rglob("*.jsonl"))
        stored_text = stored_file.read_text(encoding="utf-8")
        assert "好开心🎉" not in stored_text
        assert "好开心" in stored_text
        _allowed_emoji_cache.clear()

    asyncio.run(_run())
