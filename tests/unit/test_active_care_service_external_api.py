# -*- coding: utf-8 -*-
"""``core/services/active_care/core/service.py`` 门面层测试（三）：外部接口与模块级单例。

覆盖 check_active_care（未启用/锁超时/perform_check 超时/CancelledError/通用异常/正常）、
get_runtime_status、on_user_interaction、notify_workspace_*、set_sleep_mode、pause、
on_mode_switch、on_assistant_message_sent 各分支，以及单例 get_active_care_service 的
创建/复用/升级路径（含 _on_done 的 cancelled 与 exception 两条回调分支）。
全部纯 mock；不 sleep、随机数一律打桩。
"""
from __future__ import annotations

import asyncio
import random
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import core.services.active_care.core.service as service_mod
from core.services.active_care.core.service import ActiveCareService
import core.services.active_care.storage.storage as storage_mod
import core.services.active_care.core.context as context_mod
import core.services.active_care.scheduling.scheduler_logic as sched_logic_mod
import core.services.active_care.decision.decision as decision_mod
import core.services.active_care.core.executor as executor_mod
import core.services.active_care.core.proactive_checker as checker_mod
import core.services.active_care.peer_chat.peer_chat_scheduler as peer_sched_mod

class _StubLazy:
    """惰性构造替身（consecutive_non_responses 供 setter 读取）。"""
    consecutive_non_responses = 0
    def __init__(self, *a, **k): pass

class _StubLock:
    """可配置 acquire 行为的锁替身。"""
    def __init__(self, acquire_exc=None):
        self.acquire_exc, self._locked = acquire_exc, False
    async def acquire(self):
        if self.acquire_exc is not None:
            raise self.acquire_exc
        self._locked = True
        return True
    def release(self): self._locked = False
    def locked(self): return self._locked

class _StubChecker:
    """覆盖门面所依赖 checker 全部接口的替身。"""
    def __init__(self):
        self.__dict__.update(
            next_decision_ts=0.0, _next_llm_decision_ts=0.0, last_skip_reason=None,
            last_check_phase=None, last_intent="none", perform_check_calls=[],
            perform_check_exc=None, set_next_calls=[], set_next_exc=None,
            _next_decision_ts_by_persona={}, _next_llm_decision_ts_by_persona={},
            _persona_keys=[], _persona_next=0.0, _earliest=0.0,
        )
    async def perform_check(self, is_startup=False):
        self.perform_check_calls.append(is_startup)
        if self.perform_check_exc is not None:
            raise self.perform_check_exc
    async def set_next_decision_ts(self, ts, source=None, persona_filename=None):
        if self.set_next_exc is not None:
            raise self.set_next_exc
        self.set_next_calls.append((ts, source, persona_filename))
    def get_next_decision_ts_for_persona(self, f): return self._persona_next
    def get_all_persona_keys(self): return list(self._persona_keys)
    def _get_earliest_next_decision_ts(self): return self._earliest

class _StubStorage:
    def __init__(self, scope="aveline", raise_get=False, raise_save=False):
        self.scope, self.raise_get = scope, raise_get
        self.raise_save, self.saved = raise_save, []
    async def get_proactive_state(self):
        if self.raise_get:
            raise RuntimeError("get boom")
        return {}
    async def save_proactive_state(self, payload, scope=None):
        if self.raise_save:
            raise RuntimeError("save boom")
        self.saved.append((payload, scope))
    def resolve_scope_from_persona_filename(self, f): return self.scope

class _StubSleep:
    def __init__(self, raise_enter=False):
        self.entered, self.exited, self.raise_enter = [], [], raise_enter
    async def enter_low_disturbance_mode(self, **kw):
        if self.raise_enter:
            raise RuntimeError("enter boom")
        self.entered.append(kw)
    async def exit_low_disturbance_mode(self, **kw): self.exited.append(kw)

class _StubDelayedScheduler:
    def __init__(self, pending=None, raise_pending=False):
        self.pending, self.raise_pending = list(pending or []), raise_pending
    def get_pending_tasks(self):
        if self.raise_pending:
            raise RuntimeError("pending boom")
        return list(self.pending)

class _FalsyExecutor:
    """布尔值为假的 executor 替身（覆盖短路分支）。"""
    def __bool__(self): return False

class _UpgradeChecker:
    """升级路径使用的 ProactiveChecker 替身。"""
    behavior = "ok"  # ok | raise | hang
    def __init__(self, **kwargs): self.kwargs = kwargs
    async def initialize(self):
        if type(self).behavior == "raise":
            raise ValueError("upgrade init boom")
        if type(self).behavior == "hang":
            await asyncio.Event().wait()

def _patch_lazy_sources(monkeypatch):
    """把 5 个 __init__ 期间会被访问的惰性源类替换为替身。"""
    monkeypatch.setattr(storage_mod, "ActiveCareStorage", _StubLazy)
    monkeypatch.setattr(context_mod, "ActiveCareContext", _StubLazy)
    monkeypatch.setattr(sched_logic_mod, "ActiveCareSchedulerLogic", _StubLazy)
    monkeypatch.setattr(decision_mod, "ActiveCareDecision", _StubLazy)
    monkeypatch.setattr(executor_mod, "ActiveCareExecutor", _StubLazy)

def _make_service(monkeypatch, *, checker=None, scope="aveline"):
    """构造一个外部接口相关下游全部替换为替身的服务实例。"""
    _patch_lazy_sources(monkeypatch)
    monkeypatch.setattr(peer_sched_mod, "init_peer_chat_scheduler", lambda **kw: MagicMock())
    svc = ActiveCareService()
    svc.checker = checker
    svc._storage = _StubStorage(scope=scope)
    svc._delayed_scheduler = _StubDelayedScheduler()
    svc._user_response_handler = SimpleNamespace(reset_interaction_state=AsyncMock())
    return svc

def _fake_logger(monkeypatch):
    """把门面模块的 logger 换成 MagicMock 并返回。"""
    fake = MagicMock()
    monkeypatch.setattr(service_mod, "logger", fake)
    return fake

def _errors(fake):
    return [str(c) for c in fake.error.call_args_list]

def _executor(ts_by_persona=None):
    """executor 替身（只需 _last_trigger_ts_by_persona）。"""
    return SimpleNamespace(_last_trigger_ts_by_persona=dict(ts_by_persona or {}))

@pytest.fixture()
def reset_singleton(monkeypatch):
    """隔离模块级单例，避免跨用例串味。"""
    monkeypatch.setattr(service_mod, "_active_care_service", None)

def _make_upgrade_target(**overrides):
    """构造升级路径所需的单例对象（SimpleNamespace 版）。"""
    defaults = dict(
        _enable_proactive_checker=False, checker=None, _running=False,
        _pending_init_tasks=set(), storage=object(), context=object(),
        scheduler_logic=object(), decision=object(), executor=object(),
        _peer_chat_scheduler=object(), settings=object(),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)

async def test_check_active_care_all_branches(monkeypatch):
    fake = _fake_logger(monkeypatch)
    # 未启用 checker → 仅告警返回
    await _make_service(monkeypatch, checker=None).check_active_care()
    assert fake.warning.called
    # 获取锁超时 → 不执行 perform_check
    checker = _StubChecker()
    svc = _make_service(monkeypatch, checker=checker)
    svc._proactive_lock = _StubLock(acquire_exc=asyncio.TimeoutError())
    await svc.check_active_care()
    assert checker.perform_check_calls == []
    assert any("获取锁超时" in m for m in _errors(fake))
    # perform_check 超时 → finally 释放锁
    checker = _StubChecker()
    checker.perform_check_exc = asyncio.TimeoutError()
    svc = _make_service(monkeypatch, checker=checker)
    await svc.check_active_care()
    assert checker.perform_check_calls == [False]
    assert svc._proactive_lock.locked() is False
    assert any("perform_check 超时" in m for m in _errors(fake))
    # 通用异常 → 记录 error 不抛出；正常完成 → 透传 is_startup
    checker = _StubChecker()
    checker.perform_check_exc = ValueError("perform boom")
    svc = _make_service(monkeypatch, checker=checker)
    await svc.check_active_care()
    assert _errors(fake)
    checker = _StubChecker()
    svc = _make_service(monkeypatch, checker=checker)
    await svc.check_active_care(is_startup=True)
    assert checker.perform_check_calls == [True]
    # CancelledError：finally 释放一次、外层再释放一次（RuntimeError 被吞）
    checker = _StubChecker()
    checker.perform_check_exc = asyncio.CancelledError()
    svc = _make_service(monkeypatch, checker=checker)
    with pytest.raises(asyncio.CancelledError):
        await svc.check_active_care()
    assert svc._proactive_lock.locked() is False

def test_get_runtime_status_branches(monkeypatch):
    checker = _StubChecker()
    checker.next_decision_ts = time.time() + 500
    checker.last_skip_reason = "throttled"
    checker.last_check_phase = "idle"
    checker.last_intent = "care"
    svc = _make_service(monkeypatch, checker=checker)
    svc._running = True
    svc._delayed_scheduler = _StubDelayedScheduler(pending=[{"id": 1}, {"id": 2}])
    svc._proactive_task = SimpleNamespace(done=lambda: False)
    svc._startup_task = SimpleNamespace(done=lambda: True)
    svc._last_loop_iteration_ts = 1.0
    svc._expected_wakeup_ts = 1.0
    svc._loop_phase = "running"
    svc._loop_phase_started_ts = 1.0
    svc._loop_restart_count = 2
    status = svc.get_runtime_status()
    assert status["running"] is True and status["checker_enabled"] is True
    assert status["enable_proactive_checker"] is False
    assert status["tasks"] == {
        "proactive": True, "startup": False, "maintenance": False, "watchdog": False
    }
    assert (status["last_intent"], status["last_skip_reason"]) == ("care", "throttled")
    assert status["last_check_phase"] == "idle" and status["delayed_tasks_pending"] == 2
    assert status["loop_stuck_seconds"] > 0 and status["sleep_overdue_seconds"] > 0
    assert status["loop_phase"] == "running" and status["loop_phase_seconds"] > 0
    assert status["loop_restart_count"] == 2
    # checker 可选字段为 None → 回退 "none"；待处理任务读取失败 → 0
    svc2 = _make_service(monkeypatch, checker=_StubChecker())
    svc2._delayed_scheduler = _StubDelayedScheduler(raise_pending=True)
    status2 = svc2.get_runtime_status()
    assert status2["last_skip_reason"] == "none"
    assert status2["last_check_phase"] == "none"
    assert status2["delayed_tasks_pending"] == 0
    # 无 checker → fallback 与各时间戳 else 分支
    svc3 = _make_service(monkeypatch, checker=None)
    svc3.last_intent = "fallback"
    status3 = svc3.get_runtime_status()
    assert status3["checker_enabled"] is False and status3["last_intent"] == "fallback"
    assert status3["loop_stuck_seconds"] == 0 and status3["sleep_overdue_seconds"] == 0
    assert status3["expected_wakeup_in_seconds"] == 0
    assert status3["loop_phase_seconds"] == 0

async def test_on_user_interaction_branches(monkeypatch):
    fake = _fake_logger(monkeypatch)
    svc = _make_service(monkeypatch)
    handler = svc._user_response_handler.reset_interaction_state
    # 未运行 → 不委托
    svc._running = False
    await svc.on_user_interaction("p.md")
    assert not handler.await_count
    # 运行中 → 委托（含 persona_filename 透传）
    svc._running = True
    await svc.on_user_interaction("p.md")
    assert handler.await_args.args == (0.0,) and handler.await_args.kwargs == {
        "persona_filename": "p.md"
    }
    # 委托异常 → 记录 error
    svc._user_response_handler.reset_interaction_state = AsyncMock(
        side_effect=RuntimeError("reset boom")
    )
    await svc.on_user_interaction("p.md")
    assert _errors(fake)

async def test_notify_workspace_reminder_and_plan_branches(monkeypatch):
    fake = _fake_logger(monkeypatch)
    checker = _StubChecker()
    svc = _make_service(monkeypatch, checker=checker)
    # 未运行 → 直接返回
    svc._running = False
    await svc.notify_workspace_reminder_updated(trigger_ts=time.time() + 100)
    assert checker.set_next_calls == [] and svc._wakeup_event.is_set() is False
    # 未来时间戳 → 按原值设置
    svc._running = True
    future = time.time() + 10_000
    await svc.notify_workspace_reminder_updated(trigger_ts=future)
    assert checker.set_next_calls == [(future, "workspace_reminder_updated", None)]
    assert svc._wakeup_event.is_set() is True
    # 已过期 → now + 1
    now = time.time()
    await svc.notify_workspace_reminder_updated(trigger_ts=now - 100)
    ts, source, persona = checker.set_next_calls[-1]
    assert source == "workspace_reminder_due_now" and persona is None and ts >= now
    # 兼容入口 → 委托
    await svc.notify_workspace_plan_updated(first_trigger_ts=future)
    assert checker.set_next_calls[-1] == (future, "workspace_reminder_updated", None)
    # 无 checker → 仅置位唤醒事件
    svc_nc = _make_service(monkeypatch, checker=None)
    svc_nc._running = True
    await svc_nc.notify_workspace_reminder_updated(trigger_ts=time.time() + 100)
    assert svc_nc._wakeup_event.is_set() is True
    # set_next_decision_ts 抛异常 → 记录 warning，不置位
    checker.set_next_exc = RuntimeError("set boom")
    svc._wakeup_event.clear()
    await svc.notify_workspace_reminder_updated(trigger_ts=time.time() + 100)
    assert fake.warning.called and svc._wakeup_event.is_set() is False

async def test_set_sleep_mode_pause_and_mode_switch(monkeypatch):
    fake = _fake_logger(monkeypatch)
    checker = _StubChecker()
    sleep = _StubSleep()
    svc = _make_service(monkeypatch, checker=checker)
    svc._state_manager = SimpleNamespace(sleep=sleep)
    # 进入 / 退出睡眠模式
    assert await svc.set_sleep_mode(True, delay_next_check_seconds=7200) is True
    assert sleep.entered[0]["source"] == "user_message"
    assert checker.set_next_calls[0][1] == "set_sleep_mode"
    assert checker.set_next_calls[0][2] is None
    assert await svc.set_sleep_mode(False) is True
    assert sleep.exited[0]["source"] == "user_message"
    assert checker.set_next_calls[1][1] == "clear_sleep_mode"
    # 无 checker 且状态读取异常 → 仍返回 True；enter 抛异常 → 返回 False
    sleep2 = _StubSleep()
    svc2 = _make_service(monkeypatch, checker=None)
    svc2._state_manager = SimpleNamespace(sleep=sleep2)
    svc2._storage = _StubStorage(raise_get=True)
    assert await svc2.set_sleep_mode(True) is True and len(sleep2.entered) == 1
    svc2._state_manager = SimpleNamespace(sleep=_StubSleep(raise_enter=True))
    assert await svc2.set_sleep_mode(True) is False and _errors(fake)
    # pause：有 / 无 checker / 失败
    assert await svc.pause(3600) is True
    assert checker.set_next_calls[-1][1] == "user_pause"
    assert await _make_service(monkeypatch, checker=None).pause() is True
    checker.set_next_exc = RuntimeError("pause boom")
    assert await svc.pause() is False and _errors(fake)
    # 模式切换仅记录日志
    await svc.on_mode_switch("work", "rest")
    assert fake.info.called

def _patch_assistant_env(monkeypatch, gap=600):
    """固定随机数与 min_gap 配置，保证断言确定性。"""
    monkeypatch.setattr(service_mod, "get_active_care_config", lambda *a, **k: gap)
    monkeypatch.setattr(random, "randint", lambda a, b: 120)

async def test_on_assistant_message_sent_with_persona(monkeypatch):
    _patch_assistant_env(monkeypatch)
    # 推进 + 跨 persona 错开 + 回写最早时间戳
    checker = _StubChecker()
    checker._persona_keys = ["aveline", "ye"]
    checker._next_decision_ts_by_persona = {"ye": 0.0}
    checker._next_llm_decision_ts_by_persona = {"ye": 0.0}
    checker._earliest = 5000.0
    svc = _make_service(monkeypatch, checker=checker, scope="aveline")
    svc._executor = _executor({"aveline": 1.0})
    await svc.on_assistant_message_sent(timestamp=100.0, persona_filename="aveline.md")
    # executor 时间戳更新到当前 persona 与全局空键
    assert svc._executor._last_trigger_ts_by_persona == {"aveline": 100.0, "": 100.0}
    # 当前 persona 正常推迟 min_gap；其他 persona 以 stagger 错开（当前 scope 被跳过）
    assert (700.0, "assistant_message_sent", "aveline.md") in checker.set_next_calls
    assert (checker._next_decision_ts_by_persona["ye"] > 0
            and checker._next_decision_ts_by_persona["ye"]
            == checker._next_llm_decision_ts_by_persona["ye"])
    assert checker.next_decision_ts == 5000.0
    assert checker._next_llm_decision_ts == 5000.0
    # persona 存档 + 全局存档各一次
    assert [s[1] for s in svc._storage.saved] == ["aveline", None]
    # 已更晚 → 不推进，stagger 也不推进
    checker2 = _StubChecker()
    checker2._persona_next = 10_000.0
    checker2._persona_keys = ["aveline", "ye"]
    checker2._next_decision_ts_by_persona = {"ye": 1e18}
    checker2._next_llm_decision_ts_by_persona = {"ye": 1e18}
    checker2._earliest = 1e18
    svc2 = _make_service(monkeypatch, checker=checker2, scope="aveline")
    svc2._executor = _executor({"aveline": 1.0})
    await svc2.on_assistant_message_sent(timestamp=100.0, persona_filename="aveline.md")
    assert checker2.set_next_calls == []
    assert checker2._next_decision_ts_by_persona["ye"] == 1e18

async def test_on_assistant_message_sent_without_persona(monkeypatch):
    _patch_assistant_env(monkeypatch)
    # 推进分支：所有 persona 时间戳统一更新，仅全局存档
    checker = _StubChecker()
    svc = _make_service(monkeypatch, checker=checker)
    svc._executor = _executor({"aveline": 5.0, "ye": 2.0})
    await svc.on_assistant_message_sent(timestamp=100.0)
    assert svc._executor._last_trigger_ts_by_persona == {"aveline": 100.0, "ye": 100.0}
    assert checker.set_next_calls == [(700.0, "assistant_message_sent", None)]
    assert [s[1] for s in svc._storage.saved] == [None]
    # 不推进分支 + 空 dict（old_ts 走 0.0）
    checker2 = _StubChecker()
    checker2.next_decision_ts = 10_000.0
    svc2 = _make_service(monkeypatch, checker=checker2)
    svc2._executor = _executor({})
    await svc2.on_assistant_message_sent(timestamp=100.0)
    assert checker2.set_next_calls == []
    assert svc2._executor._last_trigger_ts_by_persona == {}

async def test_on_assistant_message_sent_skips_gap_and_save_failure(monkeypatch):
    _patch_assistant_env(monkeypatch)
    fake = _fake_logger(monkeypatch)
    # 无 _last_trigger_ts_by_persona 属性 → 跳过 executor 分支
    svc = _make_service(monkeypatch, checker=None)
    svc._executor = SimpleNamespace()
    await svc.on_assistant_message_sent(timestamp=100.0)
    assert svc._storage.saved == [
        ({"last_sent_ts": 100.0, "last_attempt_ts": 100.0}, None)
    ]
    # executor 为假值 → 短路跳过（再追加一次全局存档）
    svc._executor = _FalsyExecutor()
    await svc.on_assistant_message_sent(timestamp=100.0)
    assert len(svc._storage.saved) == 2
    # 配置返回 None → 回退默认 600；timestamp=0 → 使用真实 now
    monkeypatch.setattr(service_mod, "get_active_care_config", lambda *a, **k: None)
    checker = _StubChecker()
    svc2 = _make_service(monkeypatch, checker=checker)
    svc2._executor = _executor({})
    await svc2.on_assistant_message_sent(timestamp=100.0)
    assert checker.set_next_calls == [(700.0, "assistant_message_sent", None)]
    svc3 = _make_service(monkeypatch, checker=_StubChecker())
    svc3._executor = _executor({})
    await svc3.on_assistant_message_sent(timestamp=0.0)
    assert svc3._storage.saved[0][0]["last_sent_ts"] > 0
    # 存档失败 → 记录 warning（scope 为空 → 不再补全局存档）
    checker2 = _StubChecker()
    checker2._persona_keys = []
    svc4 = _make_service(monkeypatch, checker=checker2, scope="")
    svc4._executor = _executor({"": 1.0})
    svc4._storage = _StubStorage(scope="", raise_save=True)
    await svc4.on_assistant_message_sent(timestamp=100.0, persona_filename="x.md")
    assert svc4._storage.saved == [] and fake.warning.called

def test_get_active_care_service_creates_and_early_return(monkeypatch, reset_singleton):
    _patch_lazy_sources(monkeypatch)
    monkeypatch.setattr(peer_sched_mod, "init_peer_chat_scheduler", lambda **kw: MagicMock())
    first = service_mod.get_active_care_service()
    second = service_mod.get_active_care_service()
    assert isinstance(first, ActiveCareService)
    assert first is second and first._enable_proactive_checker is False
    # 已存在 checker → 升级短路，不改变 enable 标志
    existing = _make_upgrade_target(checker=object())
    monkeypatch.setattr(service_mod, "_active_care_service", existing)
    result = service_mod.get_active_care_service(enable_proactive_checker=True)
    assert result is existing and existing._enable_proactive_checker is False

def test_get_active_care_service_upgrade_creates_checker(monkeypatch, reset_singleton):
    monkeypatch.setattr(checker_mod, "ProactiveChecker", _UpgradeChecker)
    # 未运行 → 只创建 checker，不建任务
    existing = _make_upgrade_target(_running=False)
    monkeypatch.setattr(service_mod, "_active_care_service", existing)
    result = service_mod.get_active_care_service(enable_proactive_checker=True)
    assert result is existing and existing._enable_proactive_checker is True
    assert isinstance(existing.checker, _UpgradeChecker)
    assert existing._pending_init_tasks == set()
    # 运行中但无事件循环 → RuntimeError 分支，不建任务
    fake = _fake_logger(monkeypatch)
    existing2 = _make_upgrade_target(_running=True)
    monkeypatch.setattr(service_mod, "_active_care_service", existing2)
    service_mod.get_active_care_service(enable_proactive_checker=True)
    assert existing2._pending_init_tasks == set()
    assert any("无事件循环" in str(c) for c in fake.warning.call_args_list)

async def test_get_active_care_service_upgrade_task_callbacks(monkeypatch, reset_singleton):
    """有事件循环时创建初始化任务；cancelled 与 exception 两条 _on_done 分支。"""
    monkeypatch.setattr(checker_mod, "ProactiveChecker", _UpgradeChecker)
    fake = _fake_logger(monkeypatch)
    # cancelled：初始化协程挂起 → 取消
    existing = _make_upgrade_target(_running=True)
    monkeypatch.setattr(service_mod, "_active_care_service", existing)
    monkeypatch.setattr(_UpgradeChecker, "behavior", "hang")
    service_mod.get_active_care_service(enable_proactive_checker=True)
    pending = list(existing._pending_init_tasks)
    assert len(pending) == 1
    pending[0].cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    assert existing._pending_init_tasks == set()
    # exception：初始化抛异常 → _on_done 记录 error
    existing2 = _make_upgrade_target(_running=True)
    monkeypatch.setattr(service_mod, "_active_care_service", existing2)
    monkeypatch.setattr(_UpgradeChecker, "behavior", "raise")
    service_mod.get_active_care_service(enable_proactive_checker=True)
    pending2 = list(existing2._pending_init_tasks)
    assert len(pending2) == 1
    await asyncio.gather(*pending2, return_exceptions=True)
    assert existing2._pending_init_tasks == set() and fake.error.called

def test_get_active_care_service_upgrade_peer_chat_branches(monkeypatch, reset_singleton):
    monkeypatch.setattr(checker_mod, "ProactiveChecker", _UpgradeChecker)
    fake = _fake_logger(monkeypatch)
    peer = MagicMock()
    monkeypatch.setattr(peer_sched_mod, "init_peer_chat_scheduler", lambda **kw: peer)
    # 未运行 → 初始化但不启动；运行中 → 初始化并启动
    existing = _make_upgrade_target(_running=False, _peer_chat_scheduler=None)
    monkeypatch.setattr(service_mod, "_active_care_service", existing)
    service_mod.get_active_care_service(enable_proactive_checker=True)
    assert existing._peer_chat_scheduler is peer and peer.start.call_count == 0
    existing2 = _make_upgrade_target(_running=True, _peer_chat_scheduler=None)
    monkeypatch.setattr(service_mod, "_active_care_service", existing2)
    service_mod.get_active_care_service(enable_proactive_checker=True)
    assert existing2._peer_chat_scheduler is peer and peer.start.call_count == 1
    # 初始化失败 → 记录 warning，保持 None
    def _boom(**kw):
        raise RuntimeError("peer upgrade boom")
    monkeypatch.setattr(peer_sched_mod, "init_peer_chat_scheduler", _boom)
    existing3 = _make_upgrade_target(_running=False, _peer_chat_scheduler=None)
    monkeypatch.setattr(service_mod, "_active_care_service", existing3)
    service_mod.get_active_care_service(enable_proactive_checker=True)
    assert existing3._peer_chat_scheduler is None and fake.warning.called
