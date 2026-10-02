# -*- coding: utf-8 -*-
"""``core/services/active_care/core/service.py`` 门面层测试（二）：生命周期。

覆盖：``initialize``（状态恢复 dict / 标量两种格式、checker 初始化、延迟任务回调注册、
事件订阅、健康检查注册、4 个后台任务的创建与复用、PeerChatScheduler 启动失败降级、
CharacterDailyEngine 启动 / 无 peer 注入 / 失败降级）；``_setup_event_subscriptions``
（已订阅短路 / 成功 / 失败 / 内部 handler 分支）；``_register_health_checker``
（注册 / 幂等 / 内部 ``_health_check`` 多分支）；``shutdown``（未运行短路 / 完整清理 /
退订失败 / 子模块停止失败 / 无 engine 属性）。

约定：所有下游协作者均替换为内存替身；后台任务一律在用例末尾 cancel + gather，
不 sleep、不依赖真实时间、除 ``tmp_path`` 外不触碰真实文件系统。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core.services.active_care.core.service import ActiveCareService
import core.services.active_care.storage.storage as storage_mod
import core.services.active_care.core.context as context_mod
import core.services.active_care.scheduling.scheduler_logic as sched_logic_mod
import core.services.active_care.decision.decision as decision_mod
import core.services.active_care.core.executor as executor_mod
import core.services.active_care.peer_chat.peer_chat_scheduler as peer_sched_mod
import core.core_engine.event_bus as event_bus_mod
import core.services.character_daily.engine as character_daily_mod


# --------------------------------------------------------------------------- #
# 替身
# --------------------------------------------------------------------------- #
class _StubLazy:
    """惰性构造替身（consecutive_non_responses 供 setter 读取）。"""
    consecutive_non_responses = 0
    def __init__(self, *a, **k):
        pass


class _StubStorage:
    def __init__(self, state=None):
        self._state = dict(state or {})
        self.load_calls = 0
        self.get_calls = 0
    async def load_policy_scores(self):
        self.load_calls += 1
    async def get_proactive_state(self):
        self.get_calls += 1
        return dict(self._state)


class _StubDelayedScheduler:
    def __init__(self):
        self.callback = None
        self.started = 0
        self.stopped = 0
    def set_callback(self, cb):
        self.callback = cb
    async def start(self):
        self.started += 1
    async def stop(self):
        self.stopped += 1


class _StubEventBus:
    def __init__(self, raise_subscribe=False, raise_unsubscribe=False):
        self.subscriptions = []
        self.unsubscriptions = []
        self.raise_subscribe = raise_subscribe
        self.raise_unsubscribe = raise_unsubscribe
    async def subscribe(self, topic, handler):
        if self.raise_subscribe:
            raise RuntimeError("subscribe boom")
        self.subscriptions.append((topic, handler))
    async def unsubscribe(self, topic, handler):
        if self.raise_unsubscribe:
            raise RuntimeError("unsubscribe boom")
        self.unsubscriptions.append((topic, handler))


class _StubHealthChecker:
    def __init__(self):
        self.registered = {}
    def register_health_checker(self, name, func, interval=30.0):
        self.registered[name] = (func, interval)


class _StubChecker:
    def __init__(self):
        self.initialize_calls = 0
    async def initialize(self):
        self.initialize_calls += 1


class _HangHandler:
    """4 个后台循环的替身：永远挂起，便于用例末尾统一 cancel。"""
    async def run_proactive_loop(self):
        await asyncio.Event().wait()
    async def run_startup_check(self):
        await asyncio.Event().wait()
    async def run_maintenance_loop(self):
        await asyncio.Event().wait()
    async def run_watchdog_loop(self):
        await asyncio.Event().wait()


class _StubPeerChat:
    def __init__(self, raise_start=False, raise_stop=False):
        self.started = 0
        self.stopped = 0
        self.raise_start = raise_start
        self.raise_stop = raise_stop
    def start(self):
        if self.raise_start:
            raise RuntimeError("peer start boom")
        self.started += 1
    async def stop(self):
        if self.raise_stop:
            raise RuntimeError("peer stop boom")
        self.stopped += 1


class _StubCharacterDailyEngine:
    def __init__(self, raise_start=False, raise_stop=False):
        self.peer = "unset"
        self.started = 0
        self.stopped = 0
        self.raise_start = raise_start
        self.raise_stop = raise_stop
    def set_peer_chat_scheduler(self, scheduler):
        self.peer = scheduler
    def start(self):
        if self.raise_start:
            raise RuntimeError("cde start boom")
        self.started += 1
    async def stop(self):
        if self.raise_stop:
            raise RuntimeError("cde stop boom")
        self.stopped += 1


# --------------------------------------------------------------------------- #
# 构造辅助
# --------------------------------------------------------------------------- #
def _patch_lazy_sources(monkeypatch):
    """把 5 个 __init__ 期间会被访问的惰性源类替换为替身。"""
    monkeypatch.setattr(storage_mod, "ActiveCareStorage", _StubLazy)
    monkeypatch.setattr(context_mod, "ActiveCareContext", _StubLazy)
    monkeypatch.setattr(sched_logic_mod, "ActiveCareSchedulerLogic", _StubLazy)
    monkeypatch.setattr(decision_mod, "ActiveCareDecision", _StubLazy)
    monkeypatch.setattr(executor_mod, "ActiveCareExecutor", _StubLazy)


def _install_sources(monkeypatch, *, state=None, peer=None, engine=None, bus=None,
                     engine_factory=None):
    """装配 initialize 所需的全部下游替身。"""
    _patch_lazy_sources(monkeypatch)
    monkeypatch.setattr(
        peer_sched_mod, "init_peer_chat_scheduler", lambda **kw: peer or _StubPeerChat()
    )
    monkeypatch.setattr(
        character_daily_mod, "init_character_daily_engine",
        engine_factory or (lambda: engine or _StubCharacterDailyEngine()),
    )
    monkeypatch.setattr(event_bus_mod, "get_event_bus", lambda: bus or _StubEventBus())


def _make_service(monkeypatch, *, state=None, peer=None, engine=None, bus=None,
                  engine_factory=None):
    _install_sources(monkeypatch, state=state, peer=peer, engine=engine, bus=bus,
                     engine_factory=engine_factory)
    svc = ActiveCareService()
    svc._storage = _StubStorage(state=state)
    svc._delayed_scheduler = _StubDelayedScheduler()
    svc._health_checker = _StubHealthChecker()
    svc._loop_runner = _HangHandler()
    svc._startup_handler = _HangHandler()
    svc._watchdog_manager = _HangHandler()
    return svc


async def _cleanup(svc):
    """把 initialize 期间创建的后台任务取消并等待，避免跨用例泄漏。"""
    tasks = [t for t in (svc._proactive_task, svc._startup_task,
                         svc._maintenance_task, svc._watchdog_task) if t is not None]
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


# --------------------------------------------------------------------------- #
# initialize
# --------------------------------------------------------------------------- #
async def test_initialize_full_flow_with_scalar_state(monkeypatch):
    svc = _make_service(monkeypatch, state={"consecutive_non_responses": 3})
    try:
        await svc.initialize()
        assert svc._running is True
        assert svc._storage.load_calls == 1 and svc._storage.get_calls == 1
        # 标量格式 → 通过 setter 写入 executor
        assert svc._executor.consecutive_non_responses == 3
        # 延迟任务回调注册 + 启动
        assert svc._delayed_scheduler.callback == svc._on_delayed_task_trigger
        assert svc._delayed_scheduler.started == 1
        # 事件订阅与健康检查
        assert svc._device_context_subscription_handler is not None
        assert svc._health_checker_registered is True
        # 4 个后台任务均已创建
        assert svc._proactive_task is not None and svc._startup_task is not None
        assert svc._maintenance_task is not None and svc._watchdog_task is not None
    finally:
        await _cleanup(svc)


async def test_initialize_dict_and_missing_state(monkeypatch):
    # dict 格式 → 逐 persona 转换并保留键
    svc = _make_service(
        monkeypatch, state={"consecutive_non_responses": {"a": "2", "b": None}}
    )
    try:
        await svc.initialize()
        assert svc._executor.consecutive_non_responses == {"a": 2, "b": 0}
    finally:
        await _cleanup(svc)
    # 缺少该键 → 默认 0
    svc2 = _make_service(monkeypatch, state={})
    try:
        await svc2.initialize()
        assert svc2._executor.consecutive_non_responses == 0
    finally:
        await _cleanup(svc2)


async def test_initialize_initializes_checker_when_enabled(monkeypatch):
    svc = _make_service(monkeypatch)
    checker = _StubChecker()
    svc.checker = checker
    try:
        await svc.initialize()
        assert checker.initialize_calls == 1
    finally:
        await _cleanup(svc)


async def test_initialize_reuses_existing_background_tasks(monkeypatch):
    svc = _make_service(monkeypatch)
    alive = SimpleNamespace(done=lambda: False)
    svc._proactive_task = alive
    svc._startup_task = alive
    svc._maintenance_task = alive
    svc._watchdog_task = alive
    await svc.initialize()
    # 已存在且未完成 → 不再重复创建
    assert svc._proactive_task is alive and svc._startup_task is alive
    assert svc._maintenance_task is alive and svc._watchdog_task is alive


async def test_initialize_peer_chat_start_failure_degrades(monkeypatch):
    peer = _StubPeerChat(raise_start=True)
    svc = _make_service(monkeypatch, peer=peer)
    try:
        await svc.initialize()
        # 启动失败不影响整体初始化
        assert svc._running is True and peer.started == 0
    finally:
        await _cleanup(svc)


async def test_initialize_character_daily_engine_variants(monkeypatch):
    # 正常：注入 peer scheduler 并启动
    peer = _StubPeerChat()
    engine = _StubCharacterDailyEngine()
    svc = _make_service(monkeypatch, peer=peer, engine=engine)
    try:
        await svc.initialize()
        assert engine.peer is peer and engine.started == 1
        assert svc._character_daily_engine is engine
    finally:
        await _cleanup(svc)
    # 无 peer scheduler → 不注入但启动
    engine2 = _StubCharacterDailyEngine()
    svc2 = _make_service(monkeypatch, engine=engine2)
    svc2._peer_chat_scheduler = None
    try:
        await svc2.initialize()
        assert engine2.peer == "unset" and engine2.started == 1
    finally:
        await _cleanup(svc2)
    # 初始化抛异常 → 降级为 None，整体仍完成
    def _boom():
        raise RuntimeError("cde init boom")
    svc3 = _make_service(monkeypatch, engine_factory=_boom)
    try:
        await svc3.initialize()
        assert svc3._character_daily_engine is None and svc3._running is True
    finally:
        await _cleanup(svc3)


# --------------------------------------------------------------------------- #
# _setup_event_subscriptions
# --------------------------------------------------------------------------- #
async def test_setup_event_subscriptions_success_and_handler_branches(monkeypatch):
    bus = _StubEventBus()
    svc = _make_service(monkeypatch, bus=bus)
    svc._running = True
    await svc._setup_event_subscriptions()
    assert svc._event_bus is bus
    assert bus.subscriptions[0][0] == "device.context_updated"
    handler = svc._device_context_subscription_handler
    assert handler is bus.subscriptions[0][1]
    # handler：带 context → 更新最近设备上下文并置位唤醒事件
    svc._wakeup_event.clear()
    await handler({"device": "phone"})
    assert svc._latest_device_context == {"device": "phone"}
    assert svc._wakeup_event.is_set() is True
    # handler：context 为 None → 只置位唤醒事件
    svc._wakeup_event.clear()
    await handler(None)
    assert svc._wakeup_event.is_set() is True
    # handler：服务未运行 → 直接返回，不置位
    svc._running = False
    svc._wakeup_event.clear()
    await handler({"device": "pc"})
    assert svc._wakeup_event.is_set() is False


async def test_setup_event_subscriptions_short_circuit_and_failure(monkeypatch):
    called = []
    svc = _make_service(monkeypatch)
    monkeypatch.setattr(
        event_bus_mod, "get_event_bus", lambda: called.append(1) or _StubEventBus()
    )
    # 已订阅 → 短路，不再取 event bus
    svc._device_context_subscription_handler = lambda **k: None
    await svc._setup_event_subscriptions()
    assert called == []
    # 订阅失败 → 吞掉异常，但 bus 与 handler 已就绪
    bus = _StubEventBus(raise_subscribe=True)
    svc2 = _make_service(monkeypatch, bus=bus)
    await svc2._setup_event_subscriptions()
    assert svc2._event_bus is bus
    assert svc2._device_context_subscription_handler is not None
    assert bus.subscriptions == []


# --------------------------------------------------------------------------- #
# _register_health_checker
# --------------------------------------------------------------------------- #
def test_register_health_checker_registers_and_is_idempotent(monkeypatch):
    svc = _make_service(monkeypatch)
    svc._running = True
    svc._register_health_checker()
    assert svc._health_checker_registered is True
    func, interval = svc._health_checker.registered["active_care_service"]
    assert interval == 60.0 and callable(func)
    # 已注册 → 幂等，不再写入
    svc._health_checker_registered = True
    svc._health_checker.registered.clear()
    svc._register_health_checker()
    assert svc._health_checker.registered == {}


async def test_health_check_healthy_and_zero_wakeup(monkeypatch):
    svc = _make_service(monkeypatch)
    svc._running = True
    svc._proactive_task = SimpleNamespace(done=lambda: False)
    svc.checker = SimpleNamespace(next_decision_ts=1_000.0)
    svc._last_loop_iteration_ts = 0.0   # 未迭代 → loop_stuck 走 0
    svc._loop_phase_started_ts = 0.0    # 未进入阶段 → loop_phase_seconds 走 else
    svc._expected_wakeup_ts = 0.0       # 未设置 → expected_wakeup_in 走 else
    svc._register_health_checker()
    result = await svc._health_checker.registered["active_care_service"][0]()
    assert result["status"] == "healthy"
    assert result["details"]["running"] is True
    assert result["details"]["proactive_task_alive"] is True
    assert result["details"]["checker_enabled"] is True
    assert result["details"]["loop_stuck_seconds"] == 0
    assert result["details"]["loop_phase_seconds"] == 0
    assert result["details"]["lock_locked"] is False
    assert result["details"]["expected_wakeup_in_seconds"] == 0
    assert result["details"]["sleep_overdue_seconds"] == 0


async def test_health_check_unhealthy_branches(monkeypatch):
    # 主循环未存活 + 时间戳已设置 → 计算 loop_stuck / loop_phase_seconds
    svc = _make_service(monkeypatch)
    svc._running = True
    svc._proactive_task = None
    svc.checker = None
    svc._last_loop_iteration_ts = 1.0
    svc._loop_phase_started_ts = 1.0
    svc._register_health_checker()
    result = await svc._health_checker.registered["active_care_service"][0]()
    assert result["status"] == "unhealthy"
    assert result["details"]["proactive_task_alive"] is False
    assert result["details"]["checker_enabled"] is False
    assert result["details"]["loop_stuck_seconds"] > 0
    assert result["details"]["loop_phase_seconds"] > 0
    # expected_wakeup 远早于 now → overdue > 300 强制 unhealthy
    svc2 = _make_service(monkeypatch)
    svc2._running = True
    svc2._proactive_task = SimpleNamespace(done=lambda: False)
    svc2._expected_wakeup_ts = 1.0
    svc2._loop_phase_started_ts = 1.0
    svc2._register_health_checker()
    result2 = await svc2._health_checker.registered["active_care_service"][0]()
    assert result2["status"] == "unhealthy"
    assert result2["details"]["sleep_overdue_seconds"] > 300
    assert result2["details"]["expected_wakeup_in_seconds"] < 0


# --------------------------------------------------------------------------- #
# shutdown
# --------------------------------------------------------------------------- #
async def test_shutdown_when_not_running_returns_early(monkeypatch):
    svc = _make_service(monkeypatch)
    svc._running = False
    await svc.shutdown()
    assert svc._running is False and svc._delayed_scheduler.stopped == 0


async def test_shutdown_full_flow_cancels_tasks_and_stops_submodules(monkeypatch):
    peer = _StubPeerChat()
    engine = _StubCharacterDailyEngine()
    bus = _StubEventBus()
    svc = _make_service(monkeypatch, peer=peer, engine=engine, bus=bus)
    svc._running = True
    svc._event_bus = bus
    handler = object()
    svc._device_context_subscription_handler = handler
    svc._character_daily_engine = engine
    svc._proactive_task = asyncio.create_task(_HangHandler().run_proactive_loop())
    svc._startup_task = asyncio.create_task(_HangHandler().run_startup_check())
    await svc.shutdown()
    assert svc._running is False
    assert bus.unsubscriptions == [("device.context_updated", handler)]
    assert svc._proactive_task.cancelled() is True
    assert svc._startup_task.cancelled() is True
    assert peer.stopped == 1 and engine.stopped == 1
    assert svc._delayed_scheduler.stopped == 1


async def test_shutdown_failures_are_swallowed(monkeypatch):
    # 退订失败 + 子模块停止失败均被吞掉，delayed_scheduler.stop() 仍执行
    bus = _StubEventBus(raise_unsubscribe=True)
    peer = _StubPeerChat(raise_stop=True)
    engine = _StubCharacterDailyEngine(raise_stop=True)
    svc = _make_service(monkeypatch, peer=peer, engine=engine, bus=bus)
    svc._running = True
    svc._event_bus = bus
    svc._device_context_subscription_handler = object()
    svc._character_daily_engine = engine
    await svc.shutdown()
    assert svc._running is False and svc._delayed_scheduler.stopped == 1
    # 从未 initialize（无 _character_daily_engine 属性）时也不应报错
    svc2 = _make_service(monkeypatch)
    svc2._running = True
    assert not hasattr(svc2, "_character_daily_engine")
    await svc2.shutdown()
    assert svc2._delayed_scheduler.stopped == 1
