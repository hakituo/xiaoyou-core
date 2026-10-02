"""``handler.handle_message_impl`` 的专属单元测试。

本文件用**纯替身**驱动非流式主流程，不加载 BERT / 不触网 / 不调真实模型：
- 模块级协作者（life_simulation / execute_tool_call / now_str / 文本处理）直接换掉；
- 函数体内延迟 import 的协作者，按「源模块属性」打桩（``from x import y`` 在调用时才取属性）。

风格与仓库既有测试一致：同步测试 + ``asyncio.run`` 驱动异步代码。
"""
from __future__ import annotations

import asyncio
import importlib
import json
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

from core.agents.chat_agent_components import handler


# --------------------------------------------------------------------------
# 通用替身
# --------------------------------------------------------------------------
class _Recorder:
    """记录调用的可配置替身。"""

    def __init__(self, result: Any = None, raises: Optional[BaseException] = None):
        self.calls: List[tuple] = []
        self.result = result
        self.raises = raises

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.raises is not None:
            raise self.raises
        return self.result


class _AsyncRecorder(_Recorder):
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


class _FakeAnalyzer:
    """替代 BERT 意图分析器。"""

    def __init__(self, env: "_Env"):
        self.env = env

    def analyze_intent(self, message, candidates=None):
        self.env.analyzer_calls.append((message, candidates))
        if self.env.bert_raises:
            raise RuntimeError("bert boom")
        return dict(self.env.bert_result)


class _FakeStatusManager:
    def __init__(self):
        self.statuses: List[dict] = []
        self.added: List[tuple] = []

    def add_status(self, name, description, duration_days=1):
        self.added.append((name, description, duration_days))
        for item in self.statuses:
            if item["name"] == name:
                item["description"] = description
                break
        else:
            self.statuses.append({"name": name, "description": description})
        return f"已记录：{name}"

    def _load_statuses(self):
        return [dict(item) for item in self.statuses]


class _FakeDailyManager:
    def __init__(self):
        self.meals: List[tuple] = []
        self.drinks: List[tuple] = []
        self.meal_raises: Optional[BaseException] = None
        self.drink_raises: Optional[BaseException] = None

    def record_meal(self, meal_type, content):
        if self.meal_raises is not None:
            raise self.meal_raises
        self.meals.append((meal_type, content))

    def record_drink(self, drink_type, content):
        if self.drink_raises is not None:
            raise self.drink_raises
        self.drinks.append((drink_type, content))


class _FakeLifeService:
    def __init__(self):
        self.life_stats = {
            "mood_score": 66.0,
            "shyness_score": 0.4,
            "immune_damage": 0.2,
            "is_sick": True,
            "level": 4,
        }
        self.updates: List[Any] = []
        self.raise_on_update = False
        self.reject_xp_kwarg = False

    def update_interaction(self, xp_gain=None):
        if self.raise_on_update:
            raise RuntimeError("life boom")
        if self.reject_xp_kwarg and xp_gain is not None:
            raise TypeError("no xp_gain")
        self.updates.append(xp_gain)


class _FakeEmotionManager:
    def __init__(self):
        self.ingested: List[tuple] = []
        self.processed: List[tuple] = []
        self.affect_instruction = ""
        self.affect_kwargs: Optional[dict] = None
        self.effective = None
        self.strategy = None
        self.raise_process = False
        self.raise_affect = False
        self.raise_ingest = False

    def ingest_life_stats(self, user_id, stats, intimacy_level=0.0):
        if self.raise_ingest:
            raise RuntimeError("ingest boom")
        self.ingested.append((user_id, stats, intimacy_level))

    def build_dialogue_affect_instruction(self, **kwargs):
        if self.raise_affect:
            raise RuntimeError("affect boom")
        self.affect_kwargs = kwargs
        return self.affect_instruction

    def process_text(self, user_id, text):
        if self.raise_process:
            raise RuntimeError("emotion boom")
        self.processed.append((user_id, text))

    def get_effective_state(self, user_id):
        return self.effective

    def get_response_strategy(self, user_id):
        return self.strategy


class _FakeLLM:
    def __init__(self, responses=None):
        self._responses = list(
            responses or [{"response": "你好呀", "finish_reason": "stop"}]
        )
        self.calls: List[dict] = []
        self.current_model_name = "cloud:openai:gpt-4o"

    async def chat(self, messages, **kwargs):
        self.calls.append({"messages": [dict(m) for m in messages], "kwargs": kwargs})
        if not self._responses:
            return {"response": "", "finish_reason": "stop"}
        item = self._responses.pop(0)
        if callable(item):
            return item(messages, kwargs)
        return item

    def get_current_model_name(self):
        return self.current_model_name


class _FakeToolRegistry:
    def __init__(self, tools=None, active=None):
        self._tools = dict(tools or {})
        self._active = list(active if active is not None else self._tools.keys())
        self.openai_calls: List[list] = []

    def get_active_tools(self):
        return list(self._active)

    def get_openai_tools(self, include_names=None):
        names = list(include_names) if include_names is not None else list(self._active)
        self.openai_calls.append(names)
        return [{"type": "function", "function": {"name": n}} for n in names]

    def get_tool(self, name):
        return self._tools.get(name)


class _FakeSelfImprovement:
    def __init__(self):
        self.turns: List[dict] = []

    async def on_turn_end(self, **kwargs):
        self.turns.append(kwargs)


class _FakeMemoryManager:
    def __init__(self, topic_memories=None):
        self.topic_memories = list(topic_memories or [])

    def get_memories_by_topic(self, topic, limit=1):
        return list(self.topic_memories)


class _FakeAgent:
    """覆盖 handle_message_impl 所需的全部 agent 面。"""

    def __init__(self, llm=None, tools=None, active=None):
        self._lock = asyncio.Lock()
        self.is_initialized = True
        self.initialize_calls = 0
        self.trigger_response = None
        self.trigger_raises = None
        self.saved: List[dict] = []
        self.config = SimpleNamespace(temperature=0.7, repetition_penalty=1.08)
        self.emotion_manager = _FakeEmotionManager()
        self.llm_module = llm or _FakeLLM()
        self.tool_registry = _FakeToolRegistry(tools, active)
        self.dependency_manager = None
        self._study_mode = False
        self.mode_override = "chat"
        self.history_fallback = False
        self.history_raises = None
        self.memory_manager = _FakeMemoryManager()
        self.memory_manager_raises = None
        self.title_calls: List[tuple] = []
        self.use_async_memory_manager = True
        self.save_raises: Optional[BaseException] = None
        self.determine_mode_raises: Optional[BaseException] = None
        self._is_study_mode = self._study_mode_impl

    def _study_mode_impl(self, message, _unused):
        return self._study_mode

    async def initialize(self):
        self.initialize_calls += 1
        self.is_initialized = True

    async def _check_triggers(self, user_id, message):
        if self.trigger_raises is not None:
            raise self.trigger_raises
        return self.trigger_response

    async def _save_conversation_history(
        self, user_id, message, response, message_id, thought=None
    ):
        if self.save_raises is not None:
            raise self.save_raises
        self.saved.append(
            {
                "user_id": user_id,
                "message": message,
                "response": response,
                "message_id": message_id,
                "thought": thought,
            }
        )

    async def _build_conversation_history(
        self, user_id, message, system_prompt=None, active_tools=None, persona_filename=None
    ):
        if self.history_raises is not None:
            raise self.history_raises
        if self.history_fallback:
            raise RuntimeError("history boom")
        messages: List[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})
        return messages

    def _get_memory_manager(self, cid):
        if self.memory_manager_raises is not None:
            raise self.memory_manager_raises
        return self.memory_manager

    async def get_memory_manager_async(self, cid):
        if self.memory_manager_raises is not None:
            raise self.memory_manager_raises
        return self.memory_manager

    def _determine_mode(self, message):
        if self.determine_mode_raises is not None:
            raise self.determine_mode_raises
        return self.mode_override

    async def _maybe_generate_session_title(self, user_id, message, full_content):
        self.title_calls.append((user_id, message, full_content))


def _default_settings():
    return SimpleNamespace(
        model=SimpleNamespace(
            llm=SimpleNamespace(provider="openai", base_url="https://api.example.com"),
            text_path="",
        )
    )


async def _default_prepare_active_tools(
    agent, message, extra, persona_filename=None, user_id=None
):
    return ["web_search", "generate_image"]


# --------------------------------------------------------------------------
# 环境打桩
# --------------------------------------------------------------------------
class _Env:
    """集中管理 handler 全部外部协作者的替身与可调旋钮。"""

    def __init__(self, monkeypatch):
        self.mp = monkeypatch
        self.now_str_value = "08:30"
        self.bert_result = {"intent": "NONE", "confidence": 0.0}
        self.bert_raises = False
        self.analyzer_calls: List[tuple] = []
        self.status_manager = _FakeStatusManager()
        self.daily_manager = _FakeDailyManager()
        self.persona_filename = "core_aveline.json"
        self.filter_tool_names = _Recorder(result=None)
        self.prefs_mode = "normal"
        self.settings = _default_settings()
        self.web_search_enabled = False
        self.server_side_search = False
        self.self_improvement = _FakeSelfImprovement()
        self.record_request_tools = _Recorder()
        self.observe_learning = _Recorder()
        self.prepare_active_tools = _AsyncRecorder()
        self.life_service = _FakeLifeService()
        self.execute_tool_call = _AsyncRecorder(result="工具输出")
        self.settings_raises = None
        self.web_search_enabled_raises = None
        self.self_improvement_raises = None

    def install(self):
        mp = self.mp
        # 模块级名字
        mp.setattr(handler, "get_life_simulation_service", lambda: self.life_service)
        mp.setattr(handler, "execute_tool_call", self.execute_tool_call)
        mp.setattr(handler, "now_str", lambda fmt="%H:%M": self.now_str_value)

        def _analyzer():
            return _FakeAnalyzer(self)

        def _get_settings():
            if self.settings_raises is not None:
                raise self.settings_raises
            return self.settings

        def _is_web_search_enabled():
            if self.web_search_enabled_raises is not None:
                raise self.web_search_enabled_raises
            return self.web_search_enabled

        def _get_self_improvement(scope="user"):
            if self.self_improvement_raises is not None:
                raise self.self_improvement_raises
            return self.self_improvement

        _patch(mp, "core.services.data_ops.bert_analyzer", "get_bert_analyzer", _analyzer)
        _patch(
            mp,
            "core.services.workspace.status_manager",
            "get_user_status_manager",
            lambda: self.status_manager,
        )
        _patch(
            mp,
            "core.services.daily.manager",
            "get_daily_manager",
            lambda: self.daily_manager,
        )
        _patch(
            mp,
            "core.tools.tool_visibility",
            "resolve_persona_filename",
            lambda persona_filename=None: self.persona_filename,
        )
        _patch(
            mp,
            "core.tools.tool_visibility",
            "filter_tool_names",
            self._filter_tool_names,
        )
        _patch(
            mp,
            "core.agents.chat_agent_components.study",
            "observe_learning_message",
            self.observe_learning,
        )
        _patch(
            mp,
            "core.agents.chat_agent_components.context_persona",
            "prepare_active_tools",
            self._prepare_active_tools,
        )
        _patch(
            mp,
            "core.managers.preference_manager",
            "get_preference_manager",
            lambda: SimpleNamespace(get_mode=lambda: self.prefs_mode),
        )
        _patch(mp, "config.integrated_config", "get_settings", _get_settings)
        _patch(
            mp,
            "config.model_config",
            "is_web_search_enabled",
            _is_web_search_enabled,
        )
        _patch(
            mp,
            "config.model_config",
            "should_use_server_side_web_search",
            lambda provider, model_name="": self.server_side_search,
        )
        _patch(
            mp,
            "core.services.self_improvement.service",
            "get_self_improvement_service",
            _get_self_improvement,
        )
        _patch(
            mp,
            "core.utils.data_paths",
            "resolve_data_scope_from_conversation_id",
            lambda cid, default="user": "user",
        )
        _patch(
            mp,
            "core.tools.tool_carryover",
            "record_request_tools",
            self.record_request_tools,
        )

    def _filter_tool_names(self, names, **kwargs):
        self.filter_tool_names.calls.append((tuple(names), kwargs))
        if self.filter_tool_names.result is not None:
            return list(self.filter_tool_names.result)
        return list(names)

    async def _prepare_active_tools(self, agent, message, extra, **kwargs):
        self.prepare_active_tools.calls.append((agent, message, extra, kwargs))
        if self.prepare_active_tools.raises is not None:
            raise self.prepare_active_tools.raises
        if self.prepare_active_tools.result is not None:
            return list(self.prepare_active_tools.result)
        return await _default_prepare_active_tools(agent, message, extra, **kwargs)


def _patch(monkeypatch, module_path: str, attr: str, value):
    module = importlib.import_module(module_path)
    monkeypatch.setattr(module, attr, value, raising=False)


@pytest.fixture()
def env(monkeypatch):
    e = _Env(monkeypatch)
    e.install()
    return e


def _run(coro):
    """同步驱动协程；跑完主协程后让出一次调度，flush ``create_task`` 的后台任务。"""

    async def _main():
        result = await coro
        await asyncio.sleep(0)
        return result

    return asyncio.run(_main())


def _handle(agent, message="你好", **kwargs):
    return handler.handle_message_impl(
        agent, kwargs.pop("user_id", "u1"), message, **kwargs
    )


# --------------------------------------------------------------------------
# 纯函数：_expand_discovered_tool_schemas
# --------------------------------------------------------------------------
def test_expand_skips_non_search_tools():
    agent = _FakeAgent()
    names, schemas = handler._expand_discovered_tool_schemas(
        agent, "other_tool", "{}", ["a"], ["a"]
    )
    assert names == ["a"]
    assert schemas is None


def test_expand_handles_invalid_json():
    agent = _FakeAgent()
    names, schemas = handler._expand_discovered_tool_schemas(
        agent, "search_tools", "not-json", ["a"], ["a"]
    )
    assert names == ["a"]
    assert schemas is None


def test_expand_returns_none_when_no_allowed_candidates():
    agent = _FakeAgent()
    payload = json.dumps({"tools": [{"name": "secret"}, "not-a-dict"]})
    names, schemas = handler._expand_discovered_tool_schemas(
        agent, "search_tools", payload, ["allowed"], ["allowed"]
    )
    assert names == ["allowed"]
    assert schemas is None


def test_expand_builds_schemas_for_allowed_candidates():
    agent = _FakeAgent()
    payload = json.dumps(
        {"tools": [{"name": "web_search"}, {"name": "web_search"}, {"name": "blocked"}]}
    )
    names, schemas = handler._expand_discovered_tool_schemas(
        agent, "search_tools", payload, ["web_search"], ["native"]
    )
    assert names == ["native", "web_search"]
    assert schemas == [{"type": "function", "function": {"name": "native"}}, {"type": "function", "function": {"name": "web_search"}}]


# --------------------------------------------------------------------------
# 纯函数：_is_internal_trigger_message
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        (None, False),
        ("", False),
        ("普通聊天", False),
        ("[WAKE_TRIGGER] 起床", True),
        ("前缀 [LAST_USER_MESSAGE]: 你好", True),
        ("[ACTIVE_CARE_CONTEXT_CONTINUATION] x", True),
        ("[NOTIFICATION_TRIGGER] x", True),
        ("[SYSTEM EVENT] x", True),
    ],
)
def test_is_internal_trigger_message(text, expected):
    assert handler._is_internal_trigger_message(text) is expected


# --------------------------------------------------------------------------
# 纯函数：_is_meal_or_drink_self_report
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        (None, False),
        ("   ", False),
        ("[WAKE_TRIGGER] 我吃了饭", False),
        ("我吃了吗？", False),
        ("我吃了拉面", True),
        ("刚刚喝了水", True),
        ("i just ate a burger", True),
        ("I drank some water", True),
        ("今天天气不错", False),
    ],
)
def test_is_meal_or_drink_self_report(text, expected):
    assert handler._is_meal_or_drink_self_report(text) is expected


# --------------------------------------------------------------------------
# 触发词短路
# --------------------------------------------------------------------------
def test_trigger_response_short_circuits_and_saves(env):
    agent = _FakeAgent()
    agent.trigger_response = "早上好呀"
    result = _run(_handle(agent, "早", message_id=None))
    assert result["response"] == "早上好呀"
    assert result["conversation_id"] == "u1"
    assert result["emotion"] == "happy"
    assert len(agent.saved) == 1
    assert agent.saved[0]["response"] == "早上好呀"
    assert agent.saved[0]["message_id"].startswith("msg_u1_")
    # 触发词短路后不应调用 LLM
    assert agent.llm_module.calls == []


def test_trigger_response_skips_save_when_skip_memory(env):
    agent = _FakeAgent()
    agent.trigger_response = "提醒内容"
    result = _run(_handle(agent, "提醒", message_id="m1", skip_memory_storage=True))
    assert result["response"] == "提醒内容"
    assert agent.saved == []


def test_trigger_response_save_failure_is_swallowed(env, monkeypatch):
    agent = _FakeAgent()

    async def _boom(*args, **kwargs):
        raise RuntimeError("save boom")

    monkeypatch.setattr(agent, "_save_conversation_history", _boom)
    agent.trigger_response = "hi"
    result = _run(_handle(agent, "hi", message_id="m2"))
    assert result["response"] == "hi"


# --------------------------------------------------------------------------
# 初始化 / 生命模拟
# --------------------------------------------------------------------------
def test_initialize_called_when_not_initialized(env):
    agent = _FakeAgent()
    agent.is_initialized = False
    result = _run(_handle(agent))
    assert agent.initialize_calls == 1
    assert result["success"] is True


def test_life_simulation_update_failure_is_ignored(env):
    env.life_service.raise_on_update = True
    agent = _FakeAgent()
    result = _run(_handle(agent))
    assert result["success"] is True


def test_life_simulation_typeerror_falls_back_to_no_arg(env):
    env.life_service.reject_xp_kwarg = True
    agent = _FakeAgent()
    result = _run(_handle(agent))
    assert result["success"] is True
    # 第一次无参成功、带 xp_gain 的调用抛 TypeError 后回退到无参调用
    assert env.life_service.updates == [None, None]


# --------------------------------------------------------------------------
# BERT 状态记录分支
# --------------------------------------------------------------------------
def test_bert_internal_trigger_message_skips_status(env):
    env.bert_result = {"intent": "RECORD_WAKEUP", "confidence": 0.99}
    agent = _FakeAgent()
    result = _run(_handle(agent, "[WAKE_TRIGGER] 我醒了"))
    assert env.status_manager.added == []
    assert result["success"] is True


def test_bert_wakeup_recorded_and_skips_memory(env):
    env.bert_result = {"intent": "RECORD_WAKEUP", "confidence": 0.95}
    agent = _FakeAgent()
    result = _run(_handle(agent, "我醒了"))
    assert env.status_manager.added[0][0] == "今日起床"
    assert "08:30" in env.status_manager.added[0][1]
    # 琐事记录自动跳过长期记忆存储
    assert agent.saved == []
    assert result["success"] is True


def test_bert_wakeup_false_positive_ignored(env):
    env.bert_result = {"intent": "RECORD_WAKEUP", "confidence": 0.95}
    agent = _FakeAgent()
    result = _run(_handle(agent, "今天天气不错"))
    assert env.status_manager.added == []
    assert result["success"] is True


def test_bert_meal_recorded(env):
    env.bert_result = {"intent": "RECORD_MEAL", "confidence": 0.9}
    agent = _FakeAgent()
    result = _run(_handle(agent, "我吃了拉面"))
    name, desc, days = env.status_manager.added[0]
    assert name in {"早餐", "午餐", "晚餐", "夜宵", "零食/加餐", "用餐记录"}
    assert "拉面" in desc
    assert days == 1
    assert env.daily_manager.meals
    assert result["success"] is True


def test_bert_meal_snack_detected(env):
    env.bert_result = {"intent": "RECORD_MEAL", "confidence": 0.9}
    agent = _FakeAgent()
    _run(_handle(agent, "我吃了薯片"))
    assert env.status_manager.added[0][0] == "零食/加餐"


def test_bert_meal_unspecified_food(env):
    env.bert_result = {"intent": "RECORD_MEAL", "confidence": 0.9}
    agent = _FakeAgent()
    # "我吃" 剥离关键词后无剩余内容，且兜底正则也无从匹配 -> 落到「未说明具体食物」
    _run(_handle(agent, "我吃"))
    assert "未说明具体食物" in env.status_manager.added[0][1]


def test_bert_meal_not_self_report_ignored(env):
    env.bert_result = {"intent": "RECORD_MEAL", "confidence": 0.9}
    agent = _FakeAgent()
    _run(_handle(agent, "他吃了饭"))
    assert env.status_manager.added == []


def test_bert_drink_recorded_accumulates_total(env):
    env.bert_result = {"intent": "RECORD_DRINK", "confidence": 0.9}
    env.status_manager.statuses = [
        {"name": "其他状态", "description": "x"},
        {"name": "今日饮水", "description": "已喝 100ml"},
    ]
    agent = _FakeAgent()
    result = _run(_handle(agent, "我喝了300ml水"))
    added = [item for item in env.status_manager.added if item[0] == "今日饮水"]
    assert added and "400ml" in added[0][1]
    assert env.daily_manager.drinks
    assert result["success"] is True


def test_bert_drink_cup_unit_conversion(env):
    env.bert_result = {"intent": "RECORD_DRINK", "confidence": 0.9}
    agent = _FakeAgent()
    _run(_handle(agent, "我喝了2杯水"))
    added = env.status_manager.added[0]
    assert "500ml" in added[1]


def test_bert_drink_not_self_report_ignored(env):
    env.bert_result = {"intent": "RECORD_DRINK", "confidence": 0.9}
    agent = _FakeAgent()
    _run(_handle(agent, "他喝水了"))
    assert env.status_manager.added == []


def test_bert_exception_is_logged_and_ignored(env):
    env.bert_raises = True
    agent = _FakeAgent()
    result = _run(_handle(agent))
    assert result["success"] is True


# --------------------------------------------------------------------------
# 历史构建 / 学习信号
# --------------------------------------------------------------------------
def test_history_build_failure_uses_fallback(env):
    agent = _FakeAgent()
    agent.history_fallback = True
    result = _run(_handle(agent))
    assert result["success"] is True
    assert agent.llm_module.calls[0]["messages"] == [{"role": "user", "content": "你好"}]


def test_observe_learning_failure_ignored(env):
    env.observe_learning.raises = RuntimeError("learning boom")
    agent = _FakeAgent()
    result = _run(_handle(agent))
    assert result["success"] is True


def test_prepare_active_tools_failure_uses_fallback(env):
    env.prepare_active_tools.raises = RuntimeError("tools boom")
    agent = _FakeAgent()
    result = _run(_handle(agent))
    assert result["success"] is True


def test_study_mode_skips_soft_reply_limit(env):
    agent = _FakeAgent()
    agent._study_mode = True
    agent.mode_override = "study"
    result = _run(_handle(agent, "讲讲数学"))
    assert result["success"] is True
    # study 模式不设软字数上限
    assert agent.emotion_manager.affect_kwargs["soft_reply_char_limit"] is None


def test_missing_optional_agent_hooks_default_gracefully(env, monkeypatch):
    """agent 没有 _is_study_mode / _determine_mode 时应回落到 chat。"""
    agent = _FakeAgent()
    monkeypatch.delattr(agent, "_is_study_mode", raising=False)
    monkeypatch.delattr(_FakeAgent, "_determine_mode", raising=False)
    result = _run(_handle(agent, "你好"))
    assert result["success"] is True
    # 默认 mode=chat 且短消息 -> 软字数上限 80
    assert agent.emotion_manager.affect_kwargs["soft_reply_char_limit"] == 80


# --------------------------------------------------------------------------
# 敏感模式判定
# --------------------------------------------------------------------------
def test_sensitive_mode_from_privacy_preference(env):
    env.prefs_mode = "privacy"
    agent = _FakeAgent()
    result = _run(_handle(agent))
    assert agent.llm_module.calls[0]["kwargs"]["repetition_penalty"] == pytest.approx(1.15)
    assert result["success"] is True


def test_sensitive_mode_from_local_gguf_provider(env):
    env.settings.model.llm.provider = "local"
    env.settings.model.text_path = "models/foo.gguf"
    agent = _FakeAgent()
    result = _run(_handle(agent))
    assert agent.llm_module.calls[0]["kwargs"]["repetition_penalty"] == pytest.approx(1.15)
    assert result["success"] is True


def test_sensitive_mode_from_local_provider_without_gguf(env):
    env.settings.model.llm.provider = "local"
    env.settings.model.text_path = "models/foo.bin"
    agent = _FakeAgent()
    _run(_handle(agent))
    assert agent.llm_module.calls[0]["kwargs"]["repetition_penalty"] == pytest.approx(1.15)


def test_sensitive_mode_from_memory_topic(env):
    agent = _FakeAgent()
    agent.memory_manager = _FakeMemoryManager(
        [{"content": "SENSITIVE_MODE_ON"}]
    )
    _run(_handle(agent))
    assert agent.llm_module.calls[0]["kwargs"]["repetition_penalty"] == pytest.approx(1.15)


def test_memory_manager_lookup_failure_ignored(env):
    agent = _FakeAgent()
    agent.memory_manager_raises = RuntimeError("mm boom")
    result = _run(_handle(agent))
    assert result["success"] is True


@pytest.mark.parametrize(
    "message",
    ["/sensitive 你好", "请开启nsfw", "[private] 在吗", "/nsfw", "开启sensitive"],
)
def test_sensitive_mode_from_message_keywords(env, message):
    agent = _FakeAgent()
    _run(_handle(agent, message))
    assert agent.llm_module.calls[0]["kwargs"]["repetition_penalty"] == pytest.approx(1.15)


def test_not_sensitive_uses_configured_penalty(env):
    agent = _FakeAgent()
    _run(_handle(agent))
    assert agent.llm_module.calls[0]["kwargs"]["repetition_penalty"] == pytest.approx(1.08)


def test_sensitive_mode_uses_sync_memory_manager(env, monkeypatch):
    agent = _FakeAgent()
    monkeypatch.delattr(_FakeAgent, "get_memory_manager_async", raising=False)
    result = _run(_handle(agent))
    assert result["success"] is True


# --------------------------------------------------------------------------
# 软回复长度 / 生命状态
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "message,expected_limit",
    [("你好", 80), ("今天天气怎么样", 120), ("帮我看看这个文件内容对不对", 180), ("详细说说", None)],
)
def test_soft_reply_char_limit_branches(env, message, expected_limit):
    agent = _FakeAgent()
    _run(_handle(agent, message))
    assert agent.emotion_manager.affect_kwargs["soft_reply_char_limit"] == expected_limit


def test_life_stats_and_dependency_intimacy(env):
    agent = _FakeAgent()
    agent.dependency_manager = SimpleNamespace(get_intimacy_level=lambda: 0.77)
    _run(_handle(agent))
    kwargs = agent.emotion_manager.affect_kwargs
    assert kwargs["life_level"] == 4
    assert kwargs["mood_score"] == pytest.approx(66.0)
    assert kwargs["shyness_score"] == pytest.approx(0.4)
    assert kwargs["is_sick"] is True
    assert kwargs["intimacy_level"] == pytest.approx(0.77)
    assert agent.emotion_manager.ingested


def test_affect_instruction_inserted_after_system(env):
    agent = _FakeAgent()
    agent.emotion_manager.affect_instruction = "[AFFECT]"
    _run(_handle(agent, "你好", system_prompt_override="SYS"))
    messages = agent.llm_module.calls[0]["messages"]
    assert messages[0]["content"] == "SYS"
    assert messages[1]["content"] == "[AFFECT]"


def test_affect_instruction_inserted_at_front_without_system(env):
    agent = _FakeAgent()
    agent.emotion_manager.affect_instruction = "[AFFECT]"
    _run(_handle(agent))
    messages = agent.llm_module.calls[0]["messages"]
    assert messages[0]["content"] == "[AFFECT]"
    assert messages[1]["role"] == "user"


def test_affect_instruction_failure_is_ignored(env):
    agent = _FakeAgent()
    agent.emotion_manager.raise_affect = True
    result = _run(_handle(agent))
    assert result["success"] is True


# --------------------------------------------------------------------------
# 工具注册表 / 服务端搜索
# --------------------------------------------------------------------------
def test_tool_registry_registers_openai_tools(env):
    agent = _FakeAgent()
    result = _run(_handle(agent))
    kwargs = agent.llm_module.calls[0]["kwargs"]
    assert kwargs["tool_choice"] == "auto"
    assert [t["function"]["name"] for t in kwargs["tools"]] == [
        "web_search",
        "generate_image",
    ]
    assert result["success"] is True


def test_server_side_search_removes_web_search_and_enables_flag(env):
    env.web_search_enabled = True
    env.server_side_search = True
    agent = _FakeAgent()
    _run(_handle(agent))
    kwargs = agent.llm_module.calls[0]["kwargs"]
    assert kwargs["web_search_enabled"] is True
    names = [t["function"]["name"] for t in kwargs["tools"]]
    assert "web_search" not in names
    assert "generate_image" in names


def test_no_tool_registry_skips_native_tools(env, monkeypatch):
    agent = _FakeAgent()
    monkeypatch.setattr(agent, "tool_registry", None)
    result = _run(_handle(agent))
    assert "tools" not in agent.llm_module.calls[0]["kwargs"]
    assert result["success"] is True


# --------------------------------------------------------------------------
# LLM 响应解析
# --------------------------------------------------------------------------
def test_llm_error_status_and_reasoning_content(env):
    agent = _FakeAgent(
        llm=_FakeLLM(
            [
                {
                    "response": "结果",
                    "finish_reason": "stop",
                    "status": "error",
                    "error": "boom",
                    "reasoning_content": "思考中",
                }
            ]
        )
    )
    result = _run(_handle(agent))
    assert result["thought"] == "思考中"
    assert result["content"] == "结果"


def test_llm_non_dict_response_is_stringified(env):
    agent = _FakeAgent(llm=_FakeLLM(["纯文本回复"]))
    result = _run(_handle(agent))
    assert result["success"] is True
    assert "纯文本回复" in result["full_content"]


def test_think_blocks_are_extracted(env):
    agent = _FakeAgent(llm=_FakeLLM([{"response": "先说 <think>内部推理</think> 再说", "finish_reason": "stop"}]))
    result = _run(_handle(agent))
    assert result["thought"] == "内部推理"
    assert "<think>" not in result["full_content"]


def test_unclosed_think_block_is_extracted(env):
    agent = _FakeAgent(llm=_FakeLLM([{"response": "正文<think>没闭合的推理", "finish_reason": "stop"}]))
    result = _run(_handle(agent))
    assert result["thought"] == "没闭合的推理"
    assert result["full_content"] == "正文"


def test_empty_response_then_placeholder(env):
    agent = _FakeAgent(
        llm=_FakeLLM(
            [
                {"response": "", "finish_reason": "stop", "reasoning_content": "t1"},
                {"response": "", "finish_reason": "stop", "reasoning_content": "t2"},
            ]
        )
    )
    result = _run(_handle(agent, message_id="m9"))
    # 兜底文案会被 enforce_dialogue_style 加上开头语气词/去掉句末标点，故按片段断言
    assert "我在。" in result["full_content"]
    assert "刚刚处理了一下上下文" in result["full_content"]
    # placeholder 响应不落库
    assert agent.saved == []


def test_finish_reason_length_triggers_continuation(env):
    agent = _FakeAgent(
        llm=_FakeLLM(
            [
                {"response": "前半段", "finish_reason": "length"},
                {"response": "后半段", "finish_reason": "stop"},
            ]
        )
    )
    result = _run(_handle(agent))
    assert len(agent.llm_module.calls) == 2
    # 截断续写：第二轮把首段作为 assistant 消息 + 一条续写 system 提示带回
    second_messages = agent.llm_module.calls[1]["messages"]
    assert any(m.get("role") == "assistant" and m.get("content") == "前半段" for m in second_messages)
    assert any(m.get("role") == "system" and "截断" in str(m.get("content")) for m in second_messages)
    # 每轮 response_content 会重置，最终返回的是最后一轮内容
    assert result["full_content"] == "后半段"


# --------------------------------------------------------------------------
# 原生 tool_calls 分支
# --------------------------------------------------------------------------
def test_native_tool_calls_executed_and_expanded(env):
    tool = object()
    agent = _FakeAgent(
        llm=_FakeLLM(
            [
                {
                    "response": "<think>先找工具</think>正在搜索",
                    "finish_reason": "tool_calls",
                    "tool_calls": [
                        {
                            "id": "tc1",
                            "function": {
                                "name": "search_tools",
                                "arguments": json.dumps({"q": "x"}),
                            },
                        }
                    ],
                },
                {"response": "已找到工具", "finish_reason": "stop"},
            ]
        ),
        tools={"search_tools": tool},
        active=["search_tools", "read_file"],
    )
    env.execute_tool_call.result = json.dumps(
        {"tools": [{"name": "read_file"}, {"name": "blocked"}]}
    )
    result = _run(_handle(agent))
    assert env.execute_tool_call.calls
    assert env.execute_tool_call.calls[0][1]["tool_name"] == "search_tools"
    # 工具发现后 schema 扩展，下一轮带上 read_file
    second_names = [t["function"]["name"] for t in agent.llm_module.calls[1]["kwargs"]["tools"]]
    assert "read_file" in second_names
    messages = agent.llm_module.calls[1]["messages"]
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "tc1" for m in messages)
    # reasoning_content 被带进 assistant 工具消息
    assistant_tool_msg = next(m for m in messages if m.get("role") == "assistant" and m.get("tool_calls"))
    assert assistant_tool_msg["reasoning_content"] == "先找工具"
    assert result["full_content"] == "已找到工具"


def test_native_tool_call_unknown_tool(env):
    agent = _FakeAgent(
        llm=_FakeLLM(
            [
                {
                    "response": "",
                    "finish_reason": "tool_calls",
                    "tool_calls": [{"id": "tc2", "function": {"name": "ghost", "arguments": "{}"}}],
                },
                {"response": "好的", "finish_reason": "stop"},
            ]
        )
    )
    result = _run(_handle(agent))
    assert env.execute_tool_call.calls == []
    assert result["full_content"] == "好的"


def test_native_tool_call_bad_arguments_json(env):
    tool = object()
    agent = _FakeAgent(
        llm=_FakeLLM(
            [
                {
                    "response": "",
                    "finish_reason": "tool_calls",
                    "tool_calls": [{"id": "tc3", "function": {"name": "web_search", "arguments": "{bad"}}],
                },
                {"response": "兜住了", "finish_reason": "stop"},
            ]
        ),
        tools={"web_search": tool},
    )
    result = _run(_handle(agent))
    assert env.execute_tool_call.calls == []
    assert result["full_content"] == "兜住了"


def test_native_tool_call_study_data_highlight(env):
    tool = object()
    payload = json.dumps({"type": "study_data_highlight", "data": {"filePath": "/a/b.md"}})
    agent = _FakeAgent(
        llm=_FakeLLM(
            [
                {
                    "response": "",
                    "finish_reason": "tool_calls",
                    "tool_calls": [
                        {"id": "tc4", "function": {"name": "study_tool", "arguments": "{}"}}
                    ],
                },
                {"response": "已展示", "finish_reason": "stop"},
            ]
        ),
        tools={"study_tool": tool},
    )
    env.execute_tool_call.result = payload
    result = _run(_handle(agent))
    assert result["studyData"] == {"filePath": "/a/b.md"}


# --------------------------------------------------------------------------
# [TOOL_USE: ...] 分支
# --------------------------------------------------------------------------
def test_tool_use_tag_executed_and_image_collected(env):
    tool = object()
    agent = _FakeAgent(
        llm=_FakeLLM(
            [
                {
                    "response": '[TOOL_USE: {"name": "generate_image", "arguments": {"prompt": "cat"}}]',
                    "finish_reason": "stop",
                },
                {"response": "图好了", "finish_reason": "stop"},
            ]
        ),
        tools={"generate_image": tool},
    )
    env.execute_tool_call.result = "[GEN_IMG: 一只猫]"
    result = _run(_handle(agent))
    assert env.execute_tool_call.calls[0][1]["tool_name"] == "generate_image"
    assert result["image_prompt"] == "一只猫"
    assert result["full_content"] == "图好了"


def test_tool_use_tag_unknown_tool(env):
    agent = _FakeAgent(
        llm=_FakeLLM(
            [
                {"response": '[TOOL_USE: {"name": "ghost", "arguments": {}}]', "finish_reason": "stop"},
                {"response": "结束", "finish_reason": "stop"},
            ]
        )
    )
    result = _run(_handle(agent))
    assert env.execute_tool_call.calls == []
    assert result["full_content"] == "结束"


def test_tool_use_tag_parse_error(env):
    agent = _FakeAgent(
        llm=_FakeLLM(
            [
                {"response": "[TOOL_USE: {bad json}]", "finish_reason": "stop"},
                {"response": "结束", "finish_reason": "stop"},
            ]
        )
    )
    result = _run(_handle(agent))
    assert result["full_content"] == "结束"
    assert env.execute_tool_call.calls == []


# --------------------------------------------------------------------------
# 文本后处理
# --------------------------------------------------------------------------
def test_tool_call_tag_is_unwrapped(env):
    agent = _FakeAgent(
        llm=_FakeLLM([{"response": '[TOOL_CALL]\n--text "你好呀"\n[/TOOL_CALL]', "finish_reason": "stop"}])
    )
    result = _run(_handle(agent))
    assert "你好呀" in result["content"]
    assert "[TOOL_CALL]" not in result["content"]


def test_tool_call_tag_cleaned_when_no_text(env):
    agent = _FakeAgent(
        llm=_FakeLLM([{"response": "[TOOL_CALL]--other x[/TOOL_CALL] 正文", "finish_reason": "stop"}])
    )
    result = _run(_handle(agent))
    assert "正文" in result["content"]
    assert "[TOOL_CALL]" not in result["content"]


def test_ai_timestamp_is_stripped(env):
    agent = _FakeAgent(
        llm=_FakeLLM([{"response": "你好[23:10] 在吗", "finish_reason": "stop"}])
    )
    result = _run(_handle(agent))
    assert "[23:10]" not in result["content"]
    assert "你好" in result["content"]


def test_gen_img_tag_extracted(env):
    agent = _FakeAgent(
        llm=_FakeLLM([{"response": "[GEN_IMG: 落日] 好看吗", "finish_reason": "stop"}])
    )
    result = _run(_handle(agent))
    assert result["image_prompt"] == "落日"
    assert "[GEN_IMG" not in result["content"]


def test_voice_tag_sets_message_type(env):
    agent = _FakeAgent(
        llm=_FakeLLM([{"response": "[VOICE: v-9] 我在听", "finish_reason": "stop"}])
    )
    result = _run(_handle(agent))
    assert result["message_type"] == "voice"
    assert result["voice_id"] == "v-9"
    assert "[VOICE" not in result["content"]


def test_fullwidth_voice_tag(env):
    agent = _FakeAgent(
        llm=_FakeLLM([{"response": "［VOICE］ 你好", "finish_reason": "stop"}])
    )
    result = _run(_handle(agent))
    assert result["message_type"] == "voice"
    assert result["voice_id"] is None


# --------------------------------------------------------------------------
# 情绪 / 存储 / 硬件
# --------------------------------------------------------------------------
def test_emotion_state_overrides_label_and_strategy(env):
    agent = _FakeAgent()
    agent.emotion_manager.effective = SimpleNamespace(
        primary_emotion=SimpleNamespace(value="happy"),
        sub_emotions=["joy"],
    )
    agent.emotion_manager.strategy = SimpleNamespace(metadata={"vibration_pattern": "soft"})
    result = _run(_handle(agent))
    assert result["emotion"] == "happy"
    assert result["emotion_internal"] == ["joy"]
    assert result["hardware"] == {"vibration_pattern": "soft"}


def test_hardware_intent_to_dict(env):
    agent = _FakeAgent()
    agent.emotion_manager.strategy = SimpleNamespace(
        metadata={"hardware_intent": SimpleNamespace(to_dict=lambda: {"v": 1})}
    )
    result = _run(_handle(agent))
    assert result["hardware"] == {"v": 1}


def test_emotion_manager_failure_is_ignored(env):
    agent = _FakeAgent()
    agent.emotion_manager.raise_process = True
    result = _run(_handle(agent))
    assert result["success"] is True


def test_history_saved_with_thought(env):
    agent = _FakeAgent(llm=_FakeLLM([{"response": "答案", "finish_reason": "stop", "reasoning_content": "推理"}]))
    result = _run(_handle(agent, message_id="m5"))
    assert agent.saved[0]["thought"] == "推理"
    assert agent.saved[0]["response"] == "答案"
    assert result["message_id"] == "m5"


def test_skip_memory_storage_skips_save(env):
    agent = _FakeAgent()
    result = _run(_handle(agent, message_id="m6", skip_memory_storage=True))
    assert agent.saved == []
    assert result["success"] is True


def test_self_improvement_invoked(env):
    agent = _FakeAgent()
    _run(_handle(agent))
    assert env.self_improvement.turns
    assert env.self_improvement.turns[0]["user_text"] == "你好"


def test_session_title_scheduled(env):
    agent = _FakeAgent()
    _run(_handle(agent))
    assert agent.title_calls
    assert agent.title_calls[0][0] == "u1"


def test_record_request_tools_called(env):
    agent = _FakeAgent()
    _run(_handle(agent))
    assert env.record_request_tools.calls


def test_record_request_tools_failure_ignored(env):
    env.record_request_tools.raises = RuntimeError("carryover boom")
    agent = _FakeAgent()
    result = _run(_handle(agent))
    assert result["success"] is True


# --------------------------------------------------------------------------
# 外层异常兜底
# --------------------------------------------------------------------------
def test_outer_exception_returns_error_payload(env):
    class _BoomLLM(_FakeLLM):
        async def chat(self, messages, **kwargs):
            raise RuntimeError("llm boom")

    agent = _FakeAgent(llm=_BoomLLM())
    result = _run(_handle(agent, message_id="m7"))
    assert result == {
        "success": False,
        "error": "llm boom",
        "message_id": "m7",
        "user_id": "u1",
    }
    # 异常路径也会提交工具延续状态
    assert env.record_request_tools.calls


def test_trigger_exception_propagates(env):
    """_check_triggers 在 try 块之外，异常会向上抛出（记录既有行为，非本次改动）。"""
    agent = _FakeAgent()
    agent.trigger_raises = RuntimeError("trigger boom")
    with pytest.raises(RuntimeError, match="trigger boom"):
        _run(_handle(agent, message_id="m8"))


# --------------------------------------------------------------------------
# 补齐：BERT 餐名时段 / 单位换算 / 同步失败
# --------------------------------------------------------------------------
class _FrozenDateTime:
    """固定 ``datetime.now()`` 的替身，用于覆盖按小时分支。"""

    _fixed = None

    @classmethod
    def now(cls):
        return cls._fixed


@pytest.mark.parametrize(
    "hour,expected",
    [(8, "早餐"), (12, "午餐"), (18, "晚餐"), (23, "夜宵"), (3, "夜宵")],
)
def test_bert_meal_name_by_hour(env, monkeypatch, hour, expected):
    import datetime as _dt

    env.bert_result = {"intent": "RECORD_MEAL", "confidence": 0.9}

    class _Frozen(_FrozenDateTime):
        _fixed = _dt.datetime(2025, 1, 1, hour, 0, 0)

    monkeypatch.setattr(handler, "datetime", _Frozen)
    agent = _FakeAgent()
    _run(_handle(agent, "我吃了拉面"))
    assert env.status_manager.added[0][0] == expected


def test_bert_meal_regex_fallback_extracts_food(env):
    env.bert_result = {"intent": "RECORD_MEAL", "confidence": 0.9}
    agent = _FakeAgent()
    # "我吃点饭" 剥离关键词后只剩单字，走兜底正则抽取
    _run(_handle(agent, "我吃点饭"))
    assert "饭" in env.status_manager.added[0][1]


def test_bert_meal_daily_sync_failure_ignored(env):
    env.bert_result = {"intent": "RECORD_MEAL", "confidence": 0.9}
    env.daily_manager.meal_raises = RuntimeError("daily boom")
    agent = _FakeAgent()
    result = _run(_handle(agent, "我吃了拉面"))
    assert result["success"] is True


def test_bert_drink_liter_unit_conversion(env):
    env.bert_result = {"intent": "RECORD_DRINK", "confidence": 0.9}
    agent = _FakeAgent()
    _run(_handle(agent, "我喝了1升水"))
    assert "1000ml" in env.status_manager.added[0][1]


def test_bert_drink_mouthful_unit_conversion(env):
    env.bert_result = {"intent": "RECORD_DRINK", "confidence": 0.9}
    agent = _FakeAgent()
    _run(_handle(agent, "我喝了3口水"))
    assert "50ml" in env.status_manager.added[0][1]


def test_bert_drink_daily_sync_failure_ignored(env):
    env.bert_result = {"intent": "RECORD_DRINK", "confidence": 0.9}
    env.daily_manager.drink_raises = RuntimeError("daily boom")
    agent = _FakeAgent()
    result = _run(_handle(agent, "我喝了300ml水"))
    assert result["success"] is True


# --------------------------------------------------------------------------
# 补齐：各层 except 兜底
# --------------------------------------------------------------------------
def test_settings_lookup_failure_ignored(env):
    env.settings_raises = RuntimeError("settings boom")
    agent = _FakeAgent()
    result = _run(_handle(agent))
    assert result["success"] is True


def test_determine_mode_failure_defaults_to_chat(env):
    agent = _FakeAgent()
    agent.determine_mode_raises = RuntimeError("mode boom")
    result = _run(_handle(agent, "你好"))
    assert result["success"] is True
    assert agent.emotion_manager.affect_kwargs["soft_reply_char_limit"] == 80


def test_dependency_intimacy_failure_ignored(env):
    agent = _FakeAgent()

    def _boom():
        raise RuntimeError("intimacy boom")

    agent.dependency_manager = SimpleNamespace(get_intimacy_level=_boom)
    _run(_handle(agent))
    assert agent.emotion_manager.affect_kwargs["intimacy_level"] == pytest.approx(0.1)


def test_ingest_life_stats_failure_ignored(env):
    agent = _FakeAgent()
    agent.emotion_manager.raise_ingest = True
    result = _run(_handle(agent))
    assert result["success"] is True


def test_web_search_flag_lookup_failure_ignored(env):
    env.web_search_enabled_raises = RuntimeError("ws boom")
    agent = _FakeAgent()
    result = _run(_handle(agent))
    assert result["success"] is True


def test_main_save_history_failure_ignored(env):
    agent = _FakeAgent()
    agent.save_raises = RuntimeError("save boom")
    result = _run(_handle(agent, message_id="m10"))
    assert result["success"] is True


def test_self_improvement_lookup_failure_ignored(env):
    env.self_improvement_raises = RuntimeError("si boom")
    agent = _FakeAgent()
    result = _run(_handle(agent))
    assert result["success"] is True


def test_outer_exception_with_carryover_failure(env):
    class _BoomLLM(_FakeLLM):
        async def chat(self, messages, **kwargs):
            raise RuntimeError("llm boom")

    env.record_request_tools.raises = RuntimeError("carryover boom")
    agent = _FakeAgent(llm=_BoomLLM())
    result = _run(_handle(agent, message_id="m11"))
    assert result["success"] is False
    assert result["error"] == "llm boom"


# --------------------------------------------------------------------------
# 补齐：think 合并到既有 thought
# --------------------------------------------------------------------------
def test_think_block_merged_into_existing_thought(env):
    agent = _FakeAgent(
        llm=_FakeLLM(
            [
                {
                    "response": "正文<think>标签推理</think>",
                    "finish_reason": "stop",
                    "reasoning_content": "字段推理",
                }
            ]
        )
    )
    result = _run(_handle(agent))
    assert result["thought"] == "字段推理\n标签推理"


def test_unclosed_think_merged_into_existing_thought(env):
    agent = _FakeAgent(
        llm=_FakeLLM(
            [{"response": "正文<think>未闭合", "finish_reason": "stop", "reasoning_content": "字段推理"}]
        )
    )
    result = _run(_handle(agent))
    assert result["thought"] == "字段推理\n未闭合"


# --------------------------------------------------------------------------
# 补齐：工具发现 / study_data_highlight（原生与文本两条路径）
# --------------------------------------------------------------------------
def test_native_tool_call_study_data_highlight_parse_failure(env):
    tool = object()
    agent = _FakeAgent(
        llm=_FakeLLM(
            [
                {
                    "response": "",
                    "finish_reason": "tool_calls",
                    "tool_calls": [
                        {"id": "tc5", "function": {"name": "study_tool", "arguments": "{}"}}
                    ],
                },
                {"response": "完成", "finish_reason": "stop"},
            ]
        ),
        tools={"study_tool": tool},
    )
    env.execute_tool_call.result = '{"type": "study_data_highlight", 坏掉的 json'
    result = _run(_handle(agent))
    assert result["studyData"] is None
    assert result["success"] is True


def test_tool_use_search_tools_expands_schemas(env):
    tool = object()
    agent = _FakeAgent(
        llm=_FakeLLM(
            [
                {
                    "response": '[TOOL_USE: {"name": "search_tools", "arguments": {}}]',
                    "finish_reason": "stop",
                },
                {"response": "好了", "finish_reason": "stop"},
            ]
        ),
        tools={"search_tools": tool},
        active=["search_tools", "read_file"],
    )
    env.execute_tool_call.result = json.dumps({"tools": [{"name": "read_file"}]})
    result = _run(_handle(agent))
    second_names = [t["function"]["name"] for t in agent.llm_module.calls[1]["kwargs"]["tools"]]
    assert "read_file" in second_names
    assert result["full_content"] == "好了"


def test_tool_use_study_data_highlight_success(env):
    tool = object()
    agent = _FakeAgent(
        llm=_FakeLLM(
            [
                {
                    "response": '[TOOL_USE: {"name": "study_tool", "arguments": {}}]',
                    "finish_reason": "stop",
                },
                {"response": "已展示", "finish_reason": "stop"},
            ]
        ),
        tools={"study_tool": tool},
    )
    env.execute_tool_call.result = json.dumps(
        {"type": "study_data_highlight", "data": {"filePath": "/p/q.md"}}
    )
    result = _run(_handle(agent))
    assert result["studyData"] == {"filePath": "/p/q.md"}


def test_tool_use_study_data_highlight_parse_failure(env):
    tool = object()
    agent = _FakeAgent(
        llm=_FakeLLM(
            [
                {
                    "response": '[TOOL_USE: {"name": "study_tool", "arguments": {}}]',
                    "finish_reason": "stop",
                },
                {"response": "已展示", "finish_reason": "stop"},
            ]
        ),
        tools={"study_tool": tool},
    )
    env.execute_tool_call.result = '{"type": "study_data_highlight", 坏掉的 json'
    result = _run(_handle(agent))
    assert result["studyData"] is None


# --------------------------------------------------------------------------
# 补齐：短句 + 非中性情绪 的自动语音启发式
# --------------------------------------------------------------------------
def test_short_non_neutral_reply_enters_voice_heuristic(env):
    # emotion_label 在语音启发式之前来自回复内的 [happy] 标签，而非情绪管理器
    agent = _FakeAgent(llm=_FakeLLM([{"response": "[happy]在呢", "finish_reason": "stop"}]))
    agent.emotion_manager.effective = SimpleNamespace(
        primary_emotion=SimpleNamespace(value="happy"),
        sub_emotions=None,
    )
    result = _run(_handle(agent))
    # 目前该启发式分支为空实现，仅需走到并保持 text 类型
    assert result["message_type"] == "text"
    assert result["emotion"] == "happy"
    assert "happy" not in result["content"]
