# -*- coding: utf-8 -*-
"""``core/services/active_care/core/service.py`` 门面层测试（一）：懒加载 / 构造 / 委托。

覆盖重点：

- ``__init__`` 的两个分支（``enable_proactive_checker`` 真 / 假）与 PeerChatScheduler 初始化失败降级
- 12 个懒加载 property 的「首次 import 构造」与「已缓存直接返回」两条路径
- ``consecutive_non_responses`` getter / setter 的 dict 与标量分支
- ``_set_loop_phase``
- 委托给子模块的薄方法

约定：所有下游协作者（storage/context/.../peer_chat_scheduler）均替换为内存替身，
不触碰真实文件系统、不依赖真实时间。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import core.services.active_care.core.service as service_mod
from core.services.active_care.core.service import ActiveCareService

# 懒加载 property 的 import 源模块（property 在函数体内 from X import Y）
import core.services.active_care.storage.storage as storage_mod
import core.services.active_care.core.context as context_mod
import core.services.active_care.scheduling.scheduler_logic as sched_logic_mod
import core.services.active_care.decision.decision as decision_mod
import core.services.active_care.core.executor as executor_mod
import core.services.active_care.shared.vocabulary as vocab_mod
import core.services.active_care.state as state_mod
import core.services.active_care.scheduling.delayed_scheduler as delayed_sched_mod
import core.emotion as emotion_mod
import core.services.life_simulation.service as life_sim_mod
import core.async_monitor as async_monitor_mod
import core.services.data_ops.bert_analyzer as bert_mod
import core.services.active_care.core.proactive_checker as checker_mod
import core.services.active_care.storage.user_profile_service as profile_mod
import core.services.active_care.peer_chat.peer_chat_scheduler as peer_sched_mod


# --------------------------------------------------------------------------- #
# 替身
# --------------------------------------------------------------------------- #
class _StubLazy:
    """通用惰性构造替身：记录构造参数。"""

    created: list = []

    def __init__(self, *args, **kwargs):
        type(self).created.append((args, kwargs))


class _StubProactiveChecker:
    """ProactiveChecker 替身（仅记录构造参数，initialize 为异步空实现）。"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.initialize_calls = 0

    async def initialize(self):
        self.initialize_calls += 1


class _StubProfileService:
    """UserProfileService 替身。"""

    def __init__(self, storage):
        self.storage = storage


class _StubPeerChatScheduler:
    """PeerChatScheduler 替身。"""

    def __init__(self):
        self.started = 0

    def start(self):
        self.started += 1


def _patch_lazy_sources(monkeypatch):
    """把 5 个会在 ``__init__`` 期间被访问的惰性源类替换为替身。

    ``__init__`` 里 ``init_peer_chat_scheduler(storage=self.storage, ...)``
    会触发 storage/context/decision/executor 四个 property，若不替换会构造真实对象。
    """
    monkeypatch.setattr(storage_mod, "ActiveCareStorage", _StubLazy)
    monkeypatch.setattr(context_mod, "ActiveCareContext", _StubLazy)
    monkeypatch.setattr(sched_logic_mod, "ActiveCareSchedulerLogic", _StubLazy)
    monkeypatch.setattr(decision_mod, "ActiveCareDecision", _StubLazy)
    monkeypatch.setattr(executor_mod, "ActiveCareExecutor", _StubLazy)


def _make_service(monkeypatch, *, enable_checker=False, peer_scheduler=None):
    """构造一个下游全部被替换为替身的服务实例。"""
    _patch_lazy_sources(monkeypatch)
    peer = peer_scheduler if peer_scheduler is not None else _StubPeerChatScheduler()
    monkeypatch.setattr(peer_sched_mod, "init_peer_chat_scheduler", lambda **kw: peer)
    if enable_checker:
        monkeypatch.setattr(checker_mod, "ProactiveChecker", _StubProactiveChecker)
        monkeypatch.setattr(profile_mod, "UserProfileService", _StubProfileService)
    return ActiveCareService(enable_proactive_checker=enable_checker)


# --------------------------------------------------------------------------- #
# 构造分支
# --------------------------------------------------------------------------- #
def test_init_disabled_checker_branch(monkeypatch):
    """未启用 checker：checker/user_profile_service 为 None，子模块已实例化。"""
    peer = _StubPeerChatScheduler()
    svc = _make_service(monkeypatch, enable_checker=False, peer_scheduler=peer)

    assert svc._enable_proactive_checker is False
    assert svc.checker is None
    assert svc._user_profile_service is None
    assert svc._running is False
    assert svc._peer_chat_scheduler is peer
    # 5 个委托子模块均为真实实现
    assert isinstance(svc._loop_runner, service_mod.ProactiveLoopRunner)
    assert isinstance(svc._user_response_handler, service_mod.UserResponseHandler)
    assert isinstance(svc._delayed_task_handler, service_mod.DelayedTaskHandler)
    assert isinstance(svc._watchdog_manager, service_mod.WatchdogManager)
    assert isinstance(svc._startup_handler, service_mod.StartupHandler)
    # 运行时状态默认值
    assert svc._proactive_task is None
    assert svc._maintenance_task is None
    assert svc._health_checker_registered is False
    assert svc._pending_init_tasks == set()
    assert svc._loop_phase == "init"
    assert svc.last_intent == "none"


def test_init_enabled_checker_branch(monkeypatch):
    """启用 checker：构造 ProactiveChecker 与 UserProfileService。"""
    svc = _make_service(monkeypatch, enable_checker=True)

    assert svc._enable_proactive_checker is True
    assert isinstance(svc.checker, _StubProactiveChecker)
    assert isinstance(svc._user_profile_service, _StubProfileService)
    # 构造 checker 时透传了下游依赖
    assert svc.checker.kwargs["storage"] is svc._storage
    assert svc.checker.kwargs["context"] is svc._context
    assert svc.checker.kwargs["scheduler_logic"] is svc._scheduler_logic
    assert svc.checker.kwargs["decision"] is svc._decision
    assert svc.checker.kwargs["executor"] is svc._executor
    assert svc.checker.kwargs["user_profile_service"] is svc._user_profile_service


def test_init_peer_chat_scheduler_failure_degrades(monkeypatch):
    """PeerChatScheduler 初始化抛异常时应降级为 None，不中断构造。"""
    _patch_lazy_sources(monkeypatch)

    def _boom(**kw):
        raise RuntimeError("peer chat boom")

    monkeypatch.setattr(peer_sched_mod, "init_peer_chat_scheduler", _boom)
    svc = ActiveCareService()

    assert svc._peer_chat_scheduler is None


# --------------------------------------------------------------------------- #
# 懒加载 property
# --------------------------------------------------------------------------- #
def _reset_lazy(svc, attr):
    """把某个惰性字段重置为 None，以便再次触发 import 构造分支。"""
    setattr(svc, attr, None)


def test_property_storage_lazy_then_cached(monkeypatch):
    svc = _make_service(monkeypatch)
    _reset_lazy(svc, "_storage")
    _StubLazy.created = []
    monkeypatch.setattr(storage_mod, "ActiveCareStorage", _StubLazy)

    first = svc.storage
    assert isinstance(first, _StubLazy)
    assert len(_StubLazy.created) == 1
    # 再次访问命中缓存，不再构造
    assert svc.storage is first
    assert len(_StubLazy.created) == 1


def test_property_storage_cached_returns_sentinel(monkeypatch):
    svc = _make_service(monkeypatch)
    sentinel = object()
    svc._storage = sentinel
    assert svc.storage is sentinel


def test_property_context_lazy_then_cached(monkeypatch):
    svc = _make_service(monkeypatch)
    _reset_lazy(svc, "_context")
    storage_stub = object()
    svc._storage = storage_stub
    _StubLazy.created = []
    monkeypatch.setattr(context_mod, "ActiveCareContext", _StubLazy)

    first = svc.context
    assert isinstance(first, _StubLazy)
    # 构造时把 storage 作为首个参数透传
    assert _StubLazy.created[0][0][0] is storage_stub
    assert svc.context is first


def test_property_scheduler_logic_lazy_then_cached(monkeypatch):
    svc = _make_service(monkeypatch)
    _reset_lazy(svc, "_scheduler_logic")
    _StubLazy.created = []
    monkeypatch.setattr(sched_logic_mod, "ActiveCareSchedulerLogic", _StubLazy)

    first = svc.scheduler_logic
    assert isinstance(first, _StubLazy)
    assert svc.scheduler_logic is first


def test_property_decision_lazy_then_cached(monkeypatch):
    svc = _make_service(monkeypatch)
    _reset_lazy(svc, "_decision")
    storage_stub = object()
    svc._storage = storage_stub
    _StubLazy.created = []
    monkeypatch.setattr(decision_mod, "ActiveCareDecision", _StubLazy)

    first = svc.decision
    assert isinstance(first, _StubLazy)
    assert _StubLazy.created[0][0][0] is storage_stub
    assert svc.decision is first


def test_property_executor_lazy_then_cached(monkeypatch):
    svc = _make_service(monkeypatch)
    _reset_lazy(svc, "_executor")
    context_stub = object()
    storage_stub = object()
    svc._context = context_stub
    svc._storage = storage_stub
    _StubLazy.created = []
    monkeypatch.setattr(executor_mod, "ActiveCareExecutor", _StubLazy)

    first = svc.executor
    assert isinstance(first, _StubLazy)
    assert _StubLazy.created[0][0] == (context_stub, storage_stub)
    assert svc.executor is first


def test_property_vocab_lazy_then_cached(monkeypatch):
    svc = _make_service(monkeypatch)
    _reset_lazy(svc, "_vocab")
    storage_stub = object()
    svc._storage = storage_stub
    _StubLazy.created = []
    monkeypatch.setattr(vocab_mod, "ActiveCareVocabulary", _StubLazy)

    first = svc.vocab
    assert isinstance(first, _StubLazy)
    assert _StubLazy.created[0][0][0] is storage_stub
    assert svc.vocab is first


def test_property_state_manager_lazy_then_cached(monkeypatch):
    svc = _make_service(monkeypatch)
    _reset_lazy(svc, "_state_manager")
    sentinel = object()
    monkeypatch.setattr(state_mod, "get_state_manager", lambda: sentinel)

    assert svc.state_manager is sentinel
    assert svc.state_manager is sentinel


def test_property_delayed_scheduler_lazy_then_cached(monkeypatch):
    svc = _make_service(monkeypatch)
    _reset_lazy(svc, "_delayed_scheduler")
    sentinel = object()
    monkeypatch.setattr(delayed_sched_mod, "get_delayed_scheduler", lambda: sentinel)

    assert svc.delayed_scheduler is sentinel
    assert svc.delayed_scheduler is sentinel


def test_property_emotion_manager_lazy_then_cached(monkeypatch):
    svc = _make_service(monkeypatch)
    _reset_lazy(svc, "_emotion_manager")
    sentinel = object()
    monkeypatch.setattr(emotion_mod, "get_emotion_manager", lambda: sentinel)

    assert svc.emotion_manager is sentinel
    assert svc.emotion_manager is sentinel


def test_property_life_sim_service_lazy_then_cached(monkeypatch):
    svc = _make_service(monkeypatch)
    _reset_lazy(svc, "_life_sim_service")
    sentinel = object()
    monkeypatch.setattr(life_sim_mod, "get_life_simulation_service", lambda: sentinel)

    assert svc.life_sim_service is sentinel
    assert svc.life_sim_service is sentinel


def test_property_health_checker_lazy_then_cached(monkeypatch):
    svc = _make_service(monkeypatch)
    _reset_lazy(svc, "_health_checker")
    sentinel = object()
    monkeypatch.setattr(async_monitor_mod, "get_health_checker", lambda: sentinel)

    assert svc.health_checker is sentinel
    assert svc.health_checker is sentinel


def test_property_bert_analyzer_lazy_then_cached(monkeypatch):
    svc = _make_service(monkeypatch)
    _reset_lazy(svc, "_bert_analyzer")
    sentinel = object()
    monkeypatch.setattr(bert_mod, "get_bert_analyzer", lambda: sentinel)

    assert svc.bert_analyzer is sentinel
    assert svc.bert_analyzer is sentinel


def test_property_peer_chat_scheduler_returns_field(monkeypatch):
    svc = _make_service(monkeypatch)
    marker = object()
    svc._peer_chat_scheduler = marker
    assert svc.peer_chat_scheduler is marker


# --------------------------------------------------------------------------- #
# consecutive_non_responses
# --------------------------------------------------------------------------- #
def test_consecutive_non_responses_getter_dict(monkeypatch):
    svc = _make_service(monkeypatch)
    svc._executor = SimpleNamespace(consecutive_non_responses={"a": 1, "b": 3})
    assert svc.consecutive_non_responses == 3


def test_consecutive_non_responses_getter_empty_dict(monkeypatch):
    svc = _make_service(monkeypatch)
    svc._executor = SimpleNamespace(consecutive_non_responses={})
    assert svc.consecutive_non_responses == 0


def test_consecutive_non_responses_getter_scalar(monkeypatch):
    svc = _make_service(monkeypatch)
    svc._executor = SimpleNamespace(consecutive_non_responses=7)
    assert svc.consecutive_non_responses == 7

    svc._executor = SimpleNamespace(consecutive_non_responses=None)
    assert svc.consecutive_non_responses == 0


def test_consecutive_non_responses_setter_dict_fills_all_personas(monkeypatch):
    svc = _make_service(monkeypatch)
    state = {"a": 9, "b": 0}
    svc._executor = SimpleNamespace(consecutive_non_responses=state)

    svc.consecutive_non_responses = 4

    # 所有已知 persona 被覆盖，并补充默认空键
    assert state == {"a": 4, "b": 4, "": 4}


def test_consecutive_non_responses_setter_dict_keeps_existing_empty_key(monkeypatch):
    svc = _make_service(monkeypatch)
    state = {"": 1}
    svc._executor = SimpleNamespace(consecutive_non_responses=state)

    svc.consecutive_non_responses = 2

    assert state == {"": 2}


def test_consecutive_non_responses_setter_dict_none_value(monkeypatch):
    svc = _make_service(monkeypatch)
    state = {"a": 5}
    svc._executor = SimpleNamespace(consecutive_non_responses=state)

    svc.consecutive_non_responses = None

    assert state == {"a": 0, "": 0}


def test_consecutive_non_responses_setter_scalar(monkeypatch):
    svc = _make_service(monkeypatch)
    svc._executor = SimpleNamespace(consecutive_non_responses=0)

    svc.consecutive_non_responses = 11

    assert svc._executor.consecutive_non_responses == 11


# --------------------------------------------------------------------------- #
# _set_loop_phase
# --------------------------------------------------------------------------- #
def test_set_loop_phase_updates_phase_and_timestamp(monkeypatch):
    svc = _make_service(monkeypatch)
    assert svc._loop_phase_started_ts == 0.0

    svc._set_loop_phase("running")

    assert svc._loop_phase == "running"
    assert svc._loop_phase_started_ts > 0.0


# --------------------------------------------------------------------------- #
# 委托薄方法
# --------------------------------------------------------------------------- #
class _DelegatingHandler:
    """同时扮演 5 个子模块的替身，记录被调用的方法。"""

    def __init__(self):
        self.calls = []

    async def on_delayed_task_trigger(self, *a, **k):
        self.calls.append(("on_delayed_task_trigger", a, k))

    def resolve_delayed_task_action(self, *a, **k):
        self.calls.append(("resolve_delayed_task_action", a, k))
        return ("action", {"k": 1})

    async def run_startup_check(self):
        self.calls.append(("run_startup_check", (), {}))

    async def run_proactive_loop(self):
        self.calls.append(("run_proactive_loop", (), {}))

    async def process_user_response(self):
        self.calls.append(("process_user_response", (), {}))

    async def reset_interaction_state(self, *a, **k):
        self.calls.append(("reset_interaction_state", a, k))

    async def run_maintenance_loop(self):
        self.calls.append(("run_maintenance_loop", (), {}))

    async def run_watchdog_loop(self):
        self.calls.append(("run_watchdog_loop", (), {}))


async def test_delegation_thin_methods_forward_to_handlers(monkeypatch):
    svc = _make_service(monkeypatch)
    handler = _DelegatingHandler()
    svc._delayed_task_handler = handler
    svc._startup_handler = handler
    svc._loop_runner = handler
    svc._user_response_handler = handler
    svc._watchdog_manager = handler

    await svc._on_delayed_task_trigger("t1", "type", {"c": 1}, "msg", "hint")
    result = svc._resolve_delayed_task_action("type", {"c": 1}, "hint")
    await svc._startup_check()
    await svc._proactive_loop()
    await svc._process_user_response()
    await svc._reset_interaction_state(1.5, persona_filename="p.md")
    await svc._maintenance_loop()
    await svc._watchdog_loop()

    assert result == ("action", {"k": 1})
    names = [c[0] for c in handler.calls]
    assert names == [
        "on_delayed_task_trigger",
        "resolve_delayed_task_action",
        "run_startup_check",
        "run_proactive_loop",
        "process_user_response",
        "reset_interaction_state",
        "run_maintenance_loop",
        "run_watchdog_loop",
    ]
    # 参数透传校验
    reset_call = next(c for c in handler.calls if c[0] == "reset_interaction_state")
    assert reset_call[1] == (1.5,)
    assert reset_call[2] == {"persona_filename": "p.md"}


def test_delegation_methods_are_async_callables(monkeypatch):
    """委托方法本身必须是可 await 的协程函数（防止被误改成同步）。"""
    svc = _make_service(monkeypatch)
    for name in (
        "_on_delayed_task_trigger",
        "_startup_check",
        "_proactive_loop",
        "_process_user_response",
        "_reset_interaction_state",
        "_maintenance_loop",
        "_watchdog_loop",
    ):
        assert asyncio.iscoroutinefunction(getattr(svc, name))
    assert not asyncio.iscoroutinefunction(svc._resolve_delayed_task_action)
