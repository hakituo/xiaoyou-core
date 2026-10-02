# -*- coding: utf-8 -*-
"""peer_chat 协商与单角色周期测试：分工协商 / 角色互聊判定。

覆盖 core/services/active_care/peer_chat/ 下的：
- scheduler_negotiation.py （提醒分工协商、主动关怀时段分工协商、状态简述）
- scheduler_role_cycle.py  （单角色互聊决策、多 QQ 连接缓存、peer QQ 号解析）

设计要点：
- 注册表、执行器、存储、连接解析全部用替身，不读真实磁盘状态；
- 睡眠门禁用预置 phase 固定，避免"看几点跑"；
- 断言集中在"是否触发 / 是否跳过 / 传给执行器的参数"这些确定性质上。

实现说明：这两个 mixin 大量调用宿主方法（_resolve_master_qq_id / is_user_recently_active
/ is_within_idle_window / _executor / _storage / _settings / _decision）。本文件用一个
可编程的最小宿主把它们替换掉，从而无需拉起完整 PeerChatScheduler。
"""

from __future__ import annotations

import asyncio
import time

import pytest

from core.services.active_care.peer_chat.scheduler_negotiation import (
    PeerChatNegotiationMixin,
)
from core.services.active_care.peer_chat.scheduler_role_cycle import (
    PeerChatRoleCycleMixin,
)


# ============================================================
# 替身与宿主
# ============================================================

class _StubRegistry:
    """替身分工注册表：可编程 needs_negotiation，记录状态变更。"""

    def __init__(self, needs=True):
        self._needs = needs
        self.pending = None
        self.status_calls = []

    async def needs_negotiation(self):
        return self._needs

    async def set_pending_reminders(self, reminders):
        self.pending = list(reminders)

    async def mark_negotiation_status(self, status, reason=""):
        self.status_calls.append({"status": status, "reason": reason})


class _FailingRegistry(_StubRegistry):
    """替身注册表：标记状态必失败，用于验证"标记失败本身也失败"时异常被吞掉。"""

    async def mark_negotiation_status(self, status, reason=""):
        raise RuntimeError("注册表写入失败")


def _capture_logs(monkeypatch, module):
    """替换模块 logger，返回收集 info 文本的列表（断言日志确实落了）。"""
    infos = []

    class _Logger:
        def __getattr__(self, name):
            def _record(*args, **kwargs):
                if name == "info":
                    infos.append(" ".join(str(a) for a in args))

            return _record

    monkeypatch.setattr(module, "logger", _Logger())
    return infos


class _StubExecutor:
    """替身 ActiveCareExecutor：记录 generate_peer_script 调用。"""

    def __init__(self, sent=True):
        self._sent = sent
        self.calls = []

    async def generate_peer_script(self, **kwargs):
        self.calls.append(kwargs)
        return self._sent


class _StubStorage:
    """替身存储：内存态 proactive_state，记录 scope 切换。"""

    def __init__(self, state=None):
        self._state = dict(state or {})
        self.scopes = []
        self.saved = []

    def set_runtime_scope(self, scope):
        self.scopes.append(scope)

    async def get_proactive_state(self):
        return dict(self._state)

    async def save_proactive_state(self, data, immediate=True):
        self._state = dict(data)
        self.saved.append(dict(data))


class _StubDecision:
    """替身决策器：可编程 should_send。"""

    def __init__(self, result=None):
        self._result = result or {"should_send": False, "thought": "不聊"}
        self.calls = []

    async def decide_peer_chat(self, context, role_id, peer_name):
        self.calls.append({"context": context, "role_id": role_id, "peer_name": peer_name})
        return dict(self._result)


class _StubLifeSim:
    """替身生命模拟服务：可编程 bio_state。"""

    def __init__(self, bio_state=None):
        self._bio = bio_state or {}

    def get_bio_state(self, role_id):
        return dict(self._bio)


def _make_negotiation_host(
    monkeypatch,
    *,
    registry=None,
    executor=None,
    storage=None,
    connections=None,
    user_active=False,
    sleeping_roles=(),
    failures=(),
    master_qq_id="10001",
    reminders=None,
    life_sim=None,
    brief_states=None,
    use_real_brief=False,
):
    """构造协商 mixin 的可编程宿主。

    Args:
        sleeping_roles: 处于 SLEEPING 的角色 id 集合（固定睡眠状态，防 flaky）
        failures: 调用 registry factory 时要抛异常的注册表名（用于异常路径）
        reminders: _collect_today_reminders 的返回值
        brief_states: 状态简述替身的预置映射 {role_id: brief}，缺省为 "{role_id}-state"
        use_real_brief: 为 True 时不覆盖 _get_persona_state_brief，
            走 scheduler_negotiation.py 的真实实现（生命模拟用 life_sim 替身驱动）
    """
    from core.services.life_simulation.sleep_models import SleepPhase

    class _Host(PeerChatNegotiationMixin, PeerChatRoleCycleMixin):
        def __init__(self):
            self._storage = storage or _StubStorage()
            self._executor = executor or _StubExecutor()
            self._settings = object()
            self._conns = list(connections or [])

        # ---- 宿主方法替身 ----
        def _resolve_master_qq_id(self):
            return master_qq_id

        # 注：这里刻意不替身 _resolve_peer_qq_id，直接继承 scheduler_role_cycle
        # 的真实实现，配合 config.settings_adapters 的替身，避免全局环境变量
        # 串入断言（真实实现是"配置 > 旧 env > 通用 env"回退链）。

        def is_user_recently_active(self, conversation_id):
            return user_active

        async def _is_any_character_sleeping(self, role_ids):
            return any(str(r).strip().lower() in sleeping_roles for r in role_ids)

        async def _collect_today_reminders(self):
            return list(reminders or [])

        if not use_real_brief:
            def _get_persona_state_brief(self, role_id):
                return (brief_states or {}).get(role_id, f"{role_id}-state")

    host = _Host()

    # 注册表工厂
    if registry is not None:
        import core.services.active_care.storage.reminder_assignment_registry as reminder_mod
        import core.services.active_care.storage.proactive_assignment_registry as proactive_mod

        if "reminder" in failures:
            def _boom_reminder():
                raise RuntimeError("提醒注册表不可用")

            monkeypatch.setattr(
                reminder_mod, "get_reminder_assignment_registry", _boom_reminder
            )
        else:
            monkeypatch.setattr(
                reminder_mod, "get_reminder_assignment_registry", lambda: registry
            )

        if "proactive" in failures:
            def _boom_proactive():
                raise RuntimeError("主动关怀注册表不可用")

            monkeypatch.setattr(
                proactive_mod, "get_proactive_assignment_registry", _boom_proactive
            )
        else:
            monkeypatch.setattr(
                proactive_mod,
                "get_proactive_assignment_registry",
                lambda: registry,
            )

    # 在线门禁：默认放行，个别用例可覆写
    import core.services.active_care.core.qq_connection_resolver as resolver

    monkeypatch.setattr(
        resolver,
        "check_peer_chat_participants_online",
        lambda a, b: (True, "ok"),
    )

    # 生命模拟（状态简述用）
    if life_sim is not None:
        import core.services.life_simulation as life_pkg

        monkeypatch.setattr(
            life_pkg, "get_life_simulation_service", lambda: life_sim
        )

    # 睡眠模型显式固定，确保 gate 只依赖 sleeping_roles
    host._SleepPhase = SleepPhase
    return host


# ============================================================
# scheduler_negotiation.py — 提醒分工协商
# ============================================================

CONNECTIONS = [{"role_id": "aveline", "persona_filename": "core_aveline.json"}]


class TestTryNegotiationPeerChat:
    """提醒分工协商：触发条件与各条跳过路径。"""

    async def test_skips_when_registry_says_no_need(self, monkeypatch):
        """注册表说不需要协商时不触发，且不动执行器。"""
        registry = _StubRegistry(needs=False)
        executor = _StubExecutor()
        host = _make_negotiation_host(
            monkeypatch, registry=registry, executor=executor
        )

        assert await host._try_negotiation_peer_chat(CONNECTIONS) is False
        assert executor.calls == []

    async def test_skips_when_any_character_sleeping(self, monkeypatch):
        """任一角色 SLEEPING 时跳过，且保持 pending（不标记 failed）。"""
        registry = _StubRegistry(needs=True)
        executor = _StubExecutor()
        # 睡眠门禁只看 connections 里的角色，所以睡眠角色必须在连接列表中
        connections = [
            {"role_id": "aveline", "persona_filename": "core_aveline.json"},
            {"role_id": "ling", "persona_filename": "core_ling.json"},
        ]
        host = _make_negotiation_host(
            monkeypatch,
            registry=registry,
            executor=executor,
            sleeping_roles=("ling",),
        )

        assert await host._try_negotiation_peer_chat(connections) is False
        assert executor.calls == []
        # 必须保持 pending 等起床后重试，所以不写 failed
        assert registry.status_calls == []

    async def test_marks_completed_when_no_reminders(self, monkeypatch):
        """无待发提醒时标记 completed，避免每轮重复检查。"""
        registry = _StubRegistry(needs=True)
        host = _make_negotiation_host(
            monkeypatch, registry=registry, reminders=[]
        )

        assert await host._try_negotiation_peer_chat(CONNECTIONS) is False
        assert registry.status_calls == [
            {"status": "completed", "reason": "无待发提醒"}
        ]

    async def test_skips_when_user_recently_active(self, monkeypatch):
        """用户正在聊天时不做协商互聊（不打扰）。"""
        registry = _StubRegistry(needs=True)
        executor = _StubExecutor()
        host = _make_negotiation_host(
            monkeypatch,
            registry=registry,
            executor=executor,
            reminders=[{"reminder_id": "r1", "title": "吃药"}],
            user_active=True,
        )

        assert await host._try_negotiation_peer_chat(CONNECTIONS) is False
        assert executor.calls == []

    async def test_triggers_and_updates_state_on_success(self, monkeypatch):
        """成功触发后：写 pending、传 negotiation_reminders、更新 last_peer_chat_ts。"""
        registry = _StubRegistry(needs=True)
        executor = _StubExecutor(sent=True)
        storage = _StubStorage()
        reminders = [{"reminder_id": "r1", "title": "吃药提醒"}]
        # peer_qq_id 走真实的 _resolve_peer_qq_id，所以先隔离配置源再预置 env
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_LING", "222")
        host = _make_negotiation_host(
            monkeypatch,
            registry=registry,
            executor=executor,
            storage=storage,
            reminders=reminders,
        )

        assert await host._try_negotiation_peer_chat(CONNECTIONS) is True

        # pending 列表已写入注册表
        assert registry.pending == reminders
        # 执行器收到协商参数
        assert len(executor.calls) == 1
        call = executor.calls[0]
        assert call["negotiation_reminders"] == reminders
        assert call["topic"] == "提醒分工"
        assert call["role_id"] == "aveline"
        assert call["peer_qq_id"] == "222"
        # 状态已持久化，避免普通 peer chat 紧接着触发
        assert storage.saved
        assert storage.saved[-1]["last_peer_chat_ts"] > 0

    async def test_marks_failed_when_send_fails(self, monkeypatch):
        """发送失败时标记 failed，避免每 2 分钟重复触发。"""
        registry = _StubRegistry(needs=True)
        executor = _StubExecutor(sent=False)
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_LING", "222")
        host = _make_negotiation_host(
            monkeypatch,
            registry=registry,
            executor=executor,
            reminders=[{"reminder_id": "r1", "title": "吃药"}],
        )

        assert await host._try_negotiation_peer_chat(CONNECTIONS) is False
        assert registry.status_calls == [
            {"status": "failed", "reason": "剧本发送失败"}
        ]

    async def test_skips_when_no_peer_capable_role(self, monkeypatch):
        """连接里没有具备互聊对象的角色时跳过（单角色不该被拉进协商）。"""
        registry = _StubRegistry(needs=True)
        executor = _StubExecutor()
        host = _make_negotiation_host(
            monkeypatch,
            registry=registry,
            executor=executor,
            reminders=[{"reminder_id": "r1", "title": "吃药"}],
        )

        # 只给未注册互识关系的单角色连接
        result = await host._try_negotiation_peer_chat(
            [{"role_id": "ye", "persona_filename": "core_ye.json"}]
        )
        assert result is False
        assert executor.calls == []

    async def test_skips_when_peer_qq_id_empty(self, monkeypatch):
        """解析不出 peer QQ 号时跳过（没有真实投递目标）。"""
        registry = _StubRegistry(needs=True)
        executor = _StubExecutor()
        # 配置与环境变量全部隔离为空 → 真实回退链解析出空串
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_LING", "")
        host = _make_negotiation_host(
            monkeypatch,
            registry=registry,
            executor=executor,
            reminders=[{"reminder_id": "r1", "title": "吃药"}],
        )

        assert await host._try_negotiation_peer_chat(CONNECTIONS) is False
        assert executor.calls == []

    async def test_skips_when_participants_offline(self, monkeypatch):
        """双方在线门禁不通过时跳过，不把台词变成离线消息。"""
        import core.services.active_care.core.qq_connection_resolver as resolver

        registry = _StubRegistry(needs=True)
        executor = _StubExecutor()
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_LING", "222")
        host = _make_negotiation_host(
            monkeypatch,
            registry=registry,
            executor=executor,
            reminders=[{"reminder_id": "r1", "title": "吃药"}],
        )
        monkeypatch.setattr(
            resolver,
            "check_peer_chat_participants_online",
            lambda a, b: (False, "对方不在线"),
        )

        assert await host._try_negotiation_peer_chat(CONNECTIONS) is False
        assert executor.calls == []

    async def test_registry_exception_is_swallowed_and_marked_failed(
        self, monkeypatch
    ):
        """注册表工厂异常时捕获并返回 False（不把异常抛给调度主循环）。"""
        host = _make_negotiation_host(
            monkeypatch,
            registry=_StubRegistry(),
            failures=("reminder",),
        )

        assert await host._try_negotiation_peer_chat(CONNECTIONS) is False

    async def test_skips_when_peer_id_list_holds_blank_entry(self, monkeypatch):
        """peer 列表非空但首元素是空串时同样跳过（列表非空 ≠ 有可用目标）。"""
        import core.services.dual_role.personas as personas

        registry = _StubRegistry(needs=True)
        executor = _StubExecutor()
        host = _make_negotiation_host(
            monkeypatch,
            registry=registry,
            executor=executor,
            reminders=[{"reminder_id": "r1", "title": "吃药"}],
        )
        monkeypatch.setattr(personas, "get_peer_role_ids", lambda rid: [""])

        assert await host._try_negotiation_peer_chat(CONNECTIONS) is False
        assert executor.calls == []

    async def test_send_failure_swallows_registry_error(self, monkeypatch):
        """发送失败、且标记 failed 也失败时仍返回 False，不让异常冒泡。"""
        registry = _FailingRegistry(needs=True)
        executor = _StubExecutor(sent=False)
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_LING", "222")
        host = _make_negotiation_host(
            monkeypatch,
            registry=registry,
            executor=executor,
            reminders=[{"reminder_id": "r1", "title": "吃药"}],
        )

        assert await host._try_negotiation_peer_chat(CONNECTIONS) is False

    async def test_outer_exception_marks_failed_and_logs(self, monkeypatch):
        """协商过程抛异常时标记 failed 并记日志，返回 False。"""
        import core.services.active_care.core.qq_connection_resolver as resolver
        from core.services.active_care.peer_chat import (
            scheduler_negotiation as negotiation_module,
        )

        registry = _StubRegistry(needs=True)
        executor = _StubExecutor()
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_LING", "222")
        host = _make_negotiation_host(
            monkeypatch,
            registry=registry,
            executor=executor,
            reminders=[{"reminder_id": "r1", "title": "吃药"}],
        )

        def _boom(a, b):
            raise RuntimeError("在线检查炸了")

        monkeypatch.setattr(resolver, "check_peer_chat_participants_online", _boom)
        infos = _capture_logs(monkeypatch, negotiation_module)

        assert await host._try_negotiation_peer_chat(CONNECTIONS) is False
        # 异常被吞掉，但状态必须落成 failed，否则每 2 分钟会重复触发
        assert registry.status_calls == [
            {"status": "failed", "reason": "协商异常: 在线检查炸了"}
        ]
        assert any("今日不再重试" in text for text in infos)


class TestCollectTodayReminders:
    """待发提醒收集：只保留提醒类意图。"""

    async def test_filters_to_reminder_intents_only(self, monkeypatch):
        """只保留 planned_topic / user_health_reminder 两类候选。"""
        from core.services.active_care.peer_chat import scheduler_negotiation as neg

        class _Host(PeerChatNegotiationMixin):
            pass

        import core.services.active_care.decision.daily_push_priority as priority_mod

        monkeypatch.setattr(
            priority_mod,
            "build_daily_push_priority_candidates",
            lambda **kwargs: [
                {"id": "a", "title": "吃药", "suggested_intent": "user_health_reminder"},
                {"id": "b", "title": "学习计划", "suggested_intent": "planned_topic"},
                {"id": "c", "title": "闲聊", "suggested_intent": "casual_chat"},
            ],
        )

        host = _Host()
        reminders = await host._collect_today_reminders()
        assert [r["reminder_id"] for r in reminders] == ["a", "b"]
        assert reminders[0]["title"] == "吃药"

    async def test_returns_empty_on_exception(self, monkeypatch):
        """候选构造失败时返回空列表，不抛异常。"""
        from core.services.active_care.peer_chat import scheduler_negotiation as neg  # noqa: F401
        import core.services.active_care.decision.daily_push_priority as priority_mod

        def _boom(**kwargs):
            raise RuntimeError("优先级模块不可用")

        monkeypatch.setattr(
            priority_mod, "build_daily_push_priority_candidates", _boom
        )

        class _Host(PeerChatNegotiationMixin):
            pass

        assert await _Host()._collect_today_reminders() == []

    async def test_skips_missing_intent_candidates(self, monkeypatch):
        """没有 suggested_intent 的候选不进入提醒列表。"""
        import core.services.active_care.decision.daily_push_priority as priority_mod

        monkeypatch.setattr(
            priority_mod,
            "build_daily_push_priority_candidates",
            lambda **kwargs: [{"id": "x", "title": "无意图"}],
        )

        class _Host(PeerChatNegotiationMixin):
            pass

        assert await _Host()._collect_today_reminders() == []


# ============================================================
# scheduler_negotiation.py — 主动关怀时段分工协商
# ============================================================

class TestTryProactiveAssignmentNegotiation:
    """主动关怀时段分工协商。"""

    async def test_skips_when_no_need(self, monkeypatch):
        """注册表不需要协商时不触发。"""
        registry = _StubRegistry(needs=False)
        executor = _StubExecutor()
        host = _make_negotiation_host(
            monkeypatch, registry=registry, executor=executor
        )

        assert (
            await host._try_proactive_assignment_negotiation(CONNECTIONS) is False
        )
        assert executor.calls == []

    async def test_skips_when_sleeping(self, monkeypatch):
        """角色睡眠时跳过（与提醒协商一致）。"""
        registry = _StubRegistry(needs=True)
        executor = _StubExecutor()
        host = _make_negotiation_host(
            monkeypatch,
            registry=registry,
            executor=executor,
            sleeping_roles=("aveline",),
        )

        assert (
            await host._try_proactive_assignment_negotiation(CONNECTIONS) is False
        )
        assert executor.calls == []

    async def test_triggers_with_proactive_assignment_mode(self, monkeypatch):
        """触发时必须带 proactive_assignment_mode=True 与各角色状态简述。"""
        registry = _StubRegistry(needs=True)
        executor = _StubExecutor(sent=True)
        storage = _StubStorage()
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_LING", "222")
        host = _make_negotiation_host(
            monkeypatch,
            registry=registry,
            executor=executor,
            storage=storage,
            connections=[{"role_id": "aveline", "persona_filename": "core_aveline.json"},
                         {"role_id": "ling", "persona_filename": "core_ling.json"}],
        )

        result = await host._try_proactive_assignment_negotiation(
            [{"role_id": "aveline", "persona_filename": "core_aveline.json"},
             {"role_id": "ling", "persona_filename": "core_ling.json"}]
        )
        assert result is True
        call = executor.calls[0]
        assert call["proactive_assignment_mode"] is True
        assert call["topic"] == "主动关怀分工"
        assert call["role_states"]["aveline"] == "aveline-state"
        assert call["role_states"]["ling"] == "ling-state"
        # 向后兼容字段
        assert call["aveline_state"] == "aveline-state"
        assert call["ling_state"] == "ling-state"

    async def test_skips_when_user_active(self, monkeypatch):
        """用户活跃时跳过协商。"""
        registry = _StubRegistry(needs=True)
        executor = _StubExecutor()
        host = _make_negotiation_host(
            monkeypatch,
            registry=registry,
            executor=executor,
            user_active=True,
        )

        assert (
            await host._try_proactive_assignment_negotiation(CONNECTIONS) is False
        )
        assert executor.calls == []

    async def test_marks_failed_when_send_fails(self, monkeypatch):
        """发送失败标记 failed。"""
        registry = _StubRegistry(needs=True)
        executor = _StubExecutor(sent=False)
        host = _make_negotiation_host(
            monkeypatch, registry=registry, executor=executor
        )

        assert (
            await host._try_proactive_assignment_negotiation(CONNECTIONS) is False
        )
        assert registry.status_calls[0]["status"] == "failed"

    async def test_skips_when_no_peer_capable_role(self, monkeypatch):
        """连接里没有具备互聊对象的角色时跳过。"""
        registry = _StubRegistry(needs=True)
        executor = _StubExecutor()
        host = _make_negotiation_host(
            monkeypatch, registry=registry, executor=executor
        )

        result = await host._try_proactive_assignment_negotiation(
            [{"role_id": "ye", "persona_filename": "core_ye.json"}]
        )
        assert result is False
        assert executor.calls == []

    async def test_skips_when_peer_id_list_holds_blank_entry(self, monkeypatch):
        """peer 列表非空但首元素是空串时同样跳过。"""
        import core.services.dual_role.personas as personas

        registry = _StubRegistry(needs=True)
        executor = _StubExecutor()
        host = _make_negotiation_host(
            monkeypatch, registry=registry, executor=executor
        )
        monkeypatch.setattr(personas, "get_peer_role_ids", lambda rid: [""])

        assert (
            await host._try_proactive_assignment_negotiation(CONNECTIONS) is False
        )
        assert executor.calls == []

    async def test_skips_when_peer_qq_id_empty(self, monkeypatch):
        """解析不出 peer QQ 号时跳过（没有真实投递目标）。"""
        registry = _StubRegistry(needs=True)
        executor = _StubExecutor()
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_LING", "")
        host = _make_negotiation_host(
            monkeypatch, registry=registry, executor=executor
        )

        assert (
            await host._try_proactive_assignment_negotiation(CONNECTIONS) is False
        )
        assert executor.calls == []

    async def test_skips_when_participants_offline(self, monkeypatch):
        """双方在线门禁不通过时跳过，不把台词变成离线消息。"""
        import core.services.active_care.core.qq_connection_resolver as resolver

        registry = _StubRegistry(needs=True)
        executor = _StubExecutor()
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_LING", "222")
        host = _make_negotiation_host(
            monkeypatch, registry=registry, executor=executor
        )
        monkeypatch.setattr(
            resolver,
            "check_peer_chat_participants_online",
            lambda a, b: (False, "对方不在线"),
        )

        assert (
            await host._try_proactive_assignment_negotiation(CONNECTIONS) is False
        )
        assert executor.calls == []

    async def test_send_failure_swallows_registry_error(self, monkeypatch):
        """发送失败、且标记 failed 也失败时仍返回 False。"""
        registry = _FailingRegistry(needs=True)
        executor = _StubExecutor(sent=False)
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_LING", "222")
        host = _make_negotiation_host(
            monkeypatch, registry=registry, executor=executor
        )

        assert (
            await host._try_proactive_assignment_negotiation(CONNECTIONS) is False
        )

    async def test_outer_exception_marks_failed_and_logs(self, monkeypatch):
        """协商过程抛异常时标记 failed 并记日志，返回 False。"""
        import core.services.active_care.core.qq_connection_resolver as resolver
        from core.services.active_care.peer_chat import (
            scheduler_negotiation as negotiation_module,
        )

        registry = _StubRegistry(needs=True)
        executor = _StubExecutor()
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_LING", "222")
        host = _make_negotiation_host(
            monkeypatch, registry=registry, executor=executor
        )

        def _boom(a, b):
            raise RuntimeError("在线检查炸了")

        monkeypatch.setattr(resolver, "check_peer_chat_participants_online", _boom)
        infos = _capture_logs(monkeypatch, negotiation_module)

        assert (
            await host._try_proactive_assignment_negotiation(CONNECTIONS) is False
        )
        assert registry.status_calls == [
            {"status": "failed", "reason": "协商异常: 在线检查炸了"}
        ]
        assert any("今日不再重试" in text for text in infos)

    async def test_registry_factory_exception_is_swallowed(self, monkeypatch):
        """主动关怀注册表工厂异常时捕获并返回 False（连"标记 failed"也一起失败）。"""
        host = _make_negotiation_host(
            monkeypatch,
            registry=_StubRegistry(),
            failures=("proactive",),
        )

        assert (
            await host._try_proactive_assignment_negotiation(CONNECTIONS) is False
        )


class TestGetPersonaStateBrief:
    """角色状态简述（供协商 prompt 注入）。

    注意：本类必须走 scheduler_negotiation 的真实实现，因此统一用
    use_real_brief=True 构造宿主（否则会被替身方法盖掉，测不到真实分支）。
    """

    def test_energy_high_is_described_as_energetic(self, monkeypatch):
        """精力 > 70 → "精力充沛"。"""
        host = _make_negotiation_host(
            monkeypatch,
            life_sim=_StubLifeSim({"energy": 90, "mood": ""}),
            use_real_brief=True,
        )
        assert host._get_persona_state_brief("aveline") == "精力充沛"

    def test_energy_boundary_70_is_not_energetic(self, monkeypatch):
        """精力正好 70 不算充沛（>70 才算），落到"精力尚可"。"""
        host = _make_negotiation_host(
            monkeypatch,
            life_sim=_StubLifeSim({"energy": 70, "mood": ""}),
            use_real_brief=True,
        )
        assert host._get_persona_state_brief("aveline") == "精力尚可"

    def test_energy_mid_is_described_as_ok(self, monkeypatch):
        """40 < 精力 <= 70 → "精力尚可"。"""
        host = _make_negotiation_host(
            monkeypatch,
            life_sim=_StubLifeSim({"energy": 55, "mood": ""}),
            use_real_brief=True,
        )
        assert host._get_persona_state_brief("aveline") == "精力尚可"

    def test_low_energy_is_described_as_tired(self, monkeypatch):
        """精力 <= 40 → "有点累"。"""
        host = _make_negotiation_host(
            monkeypatch,
            life_sim=_StubLifeSim({"energy": 20, "mood": ""}),
            use_real_brief=True,
        )
        assert host._get_persona_state_brief("aveline") == "有点累"

    def test_mood_and_sick_are_appended(self, monkeypatch):
        """心情与生病信息追加在同一条简报里。"""
        host = _make_negotiation_host(
            monkeypatch,
            life_sim=_StubLifeSim({"energy": 90, "mood": "开心", "is_sick": True}),
            use_real_brief=True,
        )
        brief = host._get_persona_state_brief("aveline")
        assert "精力充沛" in brief
        assert "心情开心" in brief
        assert "身体不适" in brief
        # 三段用中文逗号拼接，顺序固定
        assert brief == "精力充沛，心情开心，身体不适"

    def test_zero_energy_is_skipped(self, monkeypatch):
        """精力为 0（未初始化）时不输出精力描述，避免误报"有点累"。"""
        host = _make_negotiation_host(
            monkeypatch,
            life_sim=_StubLifeSim({"energy": 0, "mood": ""}),
            use_real_brief=True,
        )
        assert host._get_persona_state_brief("aveline") == ""

    def test_negative_energy_is_skipped(self, monkeypatch):
        """精力为负（异常值）同样不描述，且不崩。"""
        host = _make_negotiation_host(
            monkeypatch,
            life_sim=_StubLifeSim({"energy": -5, "mood": ""}),
            use_real_brief=True,
        )
        assert host._get_persona_state_brief("aveline") == ""

    def test_mood_only_brief(self, monkeypatch):
        """只有心情（精力为 0）时仍输出心情段。"""
        host = _make_negotiation_host(
            monkeypatch,
            life_sim=_StubLifeSim({"energy": 0, "mood": "低落"}),
            use_real_brief=True,
        )
        assert host._get_persona_state_brief("aveline") == "心情低落"

    def test_returns_empty_when_life_sim_unavailable(self, monkeypatch):
        """生命模拟不可用时返回空串（prompt 少一段而不是报错）。"""
        import core.services.life_simulation as life_pkg

        host = _make_negotiation_host(monkeypatch, use_real_brief=True)
        # 必须在宿主构造之后覆写：_make_negotiation_host 只在传 life_sim 时打补丁
        monkeypatch.setattr(
            life_pkg, "get_life_simulation_service", lambda: None
        )
        assert host._get_persona_state_brief("aveline") == ""

    def test_returns_empty_when_service_raises(self, monkeypatch):
        """生命模拟服务抛异常时返回空串（不能把协商整个带崩）。"""
        import core.services.life_simulation as life_pkg

        def _boom():
            raise RuntimeError("生命模拟未初始化")

        host = _make_negotiation_host(monkeypatch, use_real_brief=True)
        monkeypatch.setattr(life_pkg, "get_life_simulation_service", _boom)
        assert host._get_persona_state_brief("aveline") == ""

    def test_returns_empty_when_bio_state_not_dict(self, monkeypatch):
        """bio_state 不是 dict 时返回空串（防结构变更导致崩溃）。"""

        class _BadLifeSim:
            def get_bio_state(self, role_id):
                return "not-a-dict"

        import core.services.life_simulation as life_pkg

        host = _make_negotiation_host(monkeypatch, use_real_brief=True)
        monkeypatch.setattr(
            life_pkg, "get_life_simulation_service", lambda: _BadLifeSim()
        )
        assert host._get_persona_state_brief("aveline") == ""


# ============================================================
# scheduler_role_cycle.py
# ============================================================

def _make_role_cycle_host(
    monkeypatch,
    *,
    storage=None,
    executor=None,
    decision=None,
    connections=None,
    user_active=False,
    within_idle_window=True,
    sleeping_roles=(),
    master_qq_id="10001",
    peer_online=True,
    peer_has_client=True,
    life_sim=None,
    daily_limit=6,
    min_gap=5400.0,
):
    """构造单角色周期 mixin 的可编程宿主。"""
    from core.services.active_care.peer_chat.scheduler_role_cycle import (
        get_dual_role_config as _unused,  # noqa: F401 - 仅为确认模块可导入
    )

    class _Host(PeerChatRoleCycleMixin):
        def __init__(self):
            self._storage = storage or _StubStorage()
            self._executor = executor or _StubExecutor()
            self._decision = decision or _StubDecision()
            self._settings = object()
            self._cached_connections = []
            self._connections_cache_ts = 0.0
            self._connections_cache_ttl = 120.0
            self._today_count = 0

        def _resolve_master_qq_id(self):
            return master_qq_id

        # 注：刻意不替身 _resolve_peer_qq_id，直接继承 scheduler_role_cycle 的
        # 真实实现（配置 > 旧 env > 通用 env 回退链）。用例只需在调用前用
        # _isolate_peer_qq_config() 把真实配置与宿主机环境变量隔离掉即可。

        def is_user_recently_active(self, conversation_id):
            return user_active

        def is_within_idle_window(self, conversation_id):
            return within_idle_window

        async def _is_either_character_sleeping(self, role_a, role_b):
            return any(
                str(r).strip().lower() in sleeping_roles
                for r in (role_a, role_b)
            )

    host = _Host()

    # 频率限制配置：固定值，不读真实 yaml
    import core.services.active_care.peer_chat.scheduler_role_cycle as cycle_mod

    def _fake_get_dual_role_config(key, default=None, settings=None):
        if key == "peer_chat_daily_limit":
            return daily_limit
        if key == "peer_chat_min_gap_seconds":
            return min_gap
        return default

    monkeypatch.setattr(
        cycle_mod, "get_dual_role_config", _fake_get_dual_role_config
    )

    # 在线门禁与客户端接入门禁
    import core.services.active_care.core.qq_connection_resolver as resolver

    monkeypatch.setattr(
        resolver,
        "check_peer_chat_participants_online",
        lambda a, b: (peer_online, "ok" if peer_online else "对方不在线"),
    )
    monkeypatch.setattr(
        resolver,
        "can_send_proactive_message",
        lambda rid: peer_has_client,
    )

    # 生命模拟
    if life_sim is not None:
        import core.services.life_simulation as life_pkg

        monkeypatch.setattr(
            life_pkg, "get_life_simulation_service", lambda: life_sim
        )

    # 时间冻结，避免 date_key 依赖真实日期导致断言漂移
    import core.services.active_care.peer_chat.scheduler_role_cycle as cycle_mod2

    class _FrozenDateTime:
        @staticmethod
        def strftime(fmt):
            return "2026-09-22" if fmt == "%Y-%m-%d" else "2026-09-22 10:00:00"

    monkeypatch.setattr(
        cycle_mod2, "get_current_time", lambda: _FrozenDateTime()
    )

    return host


ROLE_CONN = {"role_id": "aveline", "persona_filename": "core_aveline.json"}

# peer_qq_id 解析相关的环境变量键：逐个清空，避免宿主机 .env / 真实配置串入断言
_PEER_QQ_ENV_KEYS = (
    "XIAOYOU_QQ_BOT_NUMBER",
    "XIAOYOU_QQ_BOT_NUMBER_LING",
    "XIAOYOU_QQ_BOT_NUMBER_YE",
)


def _isolate_peer_qq_config(monkeypatch, role_cfg=None):
    """隔离 peer_qq_id 的真实数据源（必须在设置环境变量之前调用）。

    真实回退链是"配置 > 旧 env > 通用 env"，其中配置来自
    config.settings_adapters.get_multi_qq_role_config() → get_multi_qq_config()，
    后者会读 clients/bots/multi_qq_config.json，并在进程内缓存
    （靠 reset_adapter_settings_cache() 清）。因此这里：
    1. 先重置适配器缓存 —— 清掉可能被前面用例（或启动流程）灌进去的真实配置，
       否则用例读到的是宿主机真实 QQ 号，断言全成"看本机配了啥"；
    2. 再把 get_multi_qq_role_config 固定成 role_cfg（默认 None）；
    3. 清空相关环境变量。

    顺序不可颠倒：若先重置缓存，会重新从文件加载真实配置进缓存。
    """
    import config.settings_adapters as adapters

    adapters.reset_adapter_settings_cache()

    if role_cfg is None:
        monkeypatch.setattr(
            adapters, "get_multi_qq_role_config", lambda rid: None
        )
    elif isinstance(role_cfg, type):
        # 传进来的是配置类（如 _Cfg）时，视为"所有角色都用这个配置对象"
        monkeypatch.setattr(
            adapters, "get_multi_qq_role_config", lambda rid: role_cfg()
        )
    elif callable(role_cfg):
        monkeypatch.setattr(adapters, "get_multi_qq_role_config", role_cfg)
    else:
        monkeypatch.setattr(
            adapters, "get_multi_qq_role_config", lambda rid: role_cfg
        )
    for key in _PEER_QQ_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)



class TestCheckAndTriggerForRole:
    """单角色互聊触发判定。"""

    async def test_skips_when_role_has_no_peer(self, monkeypatch):
        """未注册互识关系的单角色直接跳过（不猜一个 peer）。"""
        executor = _StubExecutor()
        host = _make_role_cycle_host(monkeypatch, executor=executor)

        result = await host._check_and_trigger_for_role("ye", ROLE_CONN, [ROLE_CONN])
        assert result is False
        assert executor.calls == []

    async def test_skips_when_daily_limit_reached(self, monkeypatch):
        """全局每日上限已达时跳过，且不调决策 LLM。"""
        storage = _StubStorage({"peer_chat_global_count_2026-09-22": 6})
        decision = _StubDecision({"should_send": True})
        host = _make_role_cycle_host(
            monkeypatch, storage=storage, decision=decision, daily_limit=6
        )

        result = await host._check_and_trigger_for_role(
            "aveline", ROLE_CONN, [ROLE_CONN]
        )
        assert result is False
        assert decision.calls == []

    async def test_skips_when_min_gap_not_elapsed(self, monkeypatch):
        """距上次互聊未满最小间隔时跳过（冻结时间保证确定性）。"""
        # get_current_time 已冻结为 2026-09-22 10:00，取一个"刚刚"的时间戳
        now = time.time()
        storage = _StubStorage({"last_peer_chat_ts": now - 60.0})
        decision = _StubDecision({"should_send": True})
        host = _make_role_cycle_host(
            monkeypatch,
            storage=storage,
            decision=decision,
            min_gap=5400.0,
        )

        result = await host._check_and_trigger_for_role(
            "aveline", ROLE_CONN, [ROLE_CONN]
        )
        assert result is False
        assert decision.calls == []

    async def test_skips_when_user_recently_active(self, monkeypatch):
        """用户最近活跃时跳过。"""
        decision = _StubDecision({"should_send": True})
        host = _make_role_cycle_host(
            monkeypatch, decision=decision, user_active=True
        )

        result = await host._check_and_trigger_for_role(
            "aveline", ROLE_CONN, [ROLE_CONN]
        )
        assert result is False
        assert decision.calls == []

    async def test_skips_when_outside_idle_window(self, monkeypatch):
        """不在空闲窗口内时跳过。"""
        decision = _StubDecision({"should_send": True})
        host = _make_role_cycle_host(
            monkeypatch, decision=decision, within_idle_window=False
        )

        result = await host._check_and_trigger_for_role(
            "aveline", ROLE_CONN, [ROLE_CONN]
        )
        assert result is False
        assert decision.calls == []

    async def test_skips_when_peer_has_no_client(self, monkeypatch):
        """peer 没有客户端接入时跳过（Frost/Coco不应被拉进互聊）。"""
        decision = _StubDecision({"should_send": True})
        host = _make_role_cycle_host(
            monkeypatch, decision=decision, peer_has_client=False
        )

        result = await host._check_and_trigger_for_role(
            "aveline", ROLE_CONN, [ROLE_CONN]
        )
        assert result is False
        assert decision.calls == []

    async def test_skips_when_peer_offline(self, monkeypatch):
        """双方在线门禁不通过时跳过。"""
        decision = _StubDecision({"should_send": True})
        host = _make_role_cycle_host(
            monkeypatch, decision=decision, peer_online=False
        )

        result = await host._check_and_trigger_for_role(
            "aveline", ROLE_CONN, [ROLE_CONN]
        )
        assert result is False
        assert decision.calls == []

    async def test_skips_when_either_character_sleeping(self, monkeypatch):
        """任一角色睡眠时跳过（peer_chat 需双方参与）。"""
        decision = _StubDecision({"should_send": True})
        host = _make_role_cycle_host(
            monkeypatch, decision=decision, sleeping_roles=("ling",)
        )

        result = await host._check_and_trigger_for_role(
            "aveline", ROLE_CONN, [ROLE_CONN]
        )
        assert result is False
        assert decision.calls == []

    async def test_skips_when_peer_qq_id_empty(self, monkeypatch):
        """解析不出对方 QQ 号时跳过（真实回退链全空 → 空串 → 无投递目标）。"""
        decision = _StubDecision({"should_send": True})
        # 配置与环境变量全部隔离为空，_resolve_peer_qq_id 真实返回 ""
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_LING", "")
        host = _make_role_cycle_host(monkeypatch, decision=decision)

        result = await host._check_and_trigger_for_role(
            "aveline", ROLE_CONN, [ROLE_CONN]
        )
        assert result is False
        assert decision.calls == []

    async def test_skips_when_decision_says_no_send(self, monkeypatch):
        """LLM 决策 should_send=False 时不生成剧本。"""
        executor = _StubExecutor()
        decision = _StubDecision({"should_send": False, "thought": "今天不聊"})
        host = _make_role_cycle_host(
            monkeypatch, executor=executor, decision=decision
        )

        result = await host._check_and_trigger_for_role(
            "aveline", ROLE_CONN, [ROLE_CONN]
        )
        assert result is False
        assert len(decision.calls) == 1
        assert executor.calls == []

    async def test_triggers_script_and_updates_counters_on_success(
        self, monkeypatch
    ):
        """决策放行且发送成功时：调执行器、累加全局与 per-role 计数、记录 topic。"""
        storage = _StubStorage()
        executor = _StubExecutor(sent=True)
        decision = _StubDecision(
            {
                "should_send": True,
                "topic": "周末安排",
                "situation": "周六下午",
                "opening_idea": "问要不要出门",
                "avoid": ["别提工作"],
            }
        )
        # peer_qq_id 走真实回退链，先隔离配置源再预置 env
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_LING", "222")
        host = _make_role_cycle_host(
            monkeypatch, storage=storage, executor=executor, decision=decision
        )

        result = await host._check_and_trigger_for_role(
            "aveline", ROLE_CONN, [ROLE_CONN]
        )
        assert result is True
        assert len(executor.calls) == 1
        call = executor.calls[0]
        assert call["topic"] == "周末安排"
        assert call["peer_qq_id"] == "222"
        assert call["avoid"] == ["别提工作"]

        # 状态持久化：全局计数 + per-role + 时间戳 + topics
        saved = storage.saved[-1]
        assert saved["peer_chat_global_count_2026-09-22"] == 1
        assert saved["peer_chat_count_2026-09-22"] == 1
        assert saved["last_peer_chat_ts"] > 0
        assert saved["recent_peer_chat_topics"] == ["周末安排"]
        assert host._today_count == 1

    async def test_no_state_update_when_send_fails(self, monkeypatch):
        """发送失败时不累加计数、不写状态（避免把失败算成已发）。"""
        storage = _StubStorage()
        executor = _StubExecutor(sent=False)
        decision = _StubDecision({"should_send": True, "topic": "话题"})
        host = _make_role_cycle_host(
            monkeypatch, storage=storage, executor=executor, decision=decision
        )

        result = await host._check_and_trigger_for_role(
            "aveline", ROLE_CONN, [ROLE_CONN]
        )
        assert result is False
        assert storage.saved == []

    async def test_recent_topics_are_capped_at_five(self, monkeypatch):
        """recent_peer_chat_topics 只保留最近 5 条（防状态文件无限增长）。"""
        old_topics = [f"旧话题{i}" for i in range(5)]
        storage = _StubStorage({"recent_peer_chat_topics": old_topics})
        executor = _StubExecutor(sent=True)
        decision = _StubDecision({"should_send": True, "topic": "新话题"})
        host = _make_role_cycle_host(
            monkeypatch, storage=storage, executor=executor, decision=decision
        )

        await host._check_and_trigger_for_role("aveline", ROLE_CONN, [ROLE_CONN])
        topics = storage.saved[-1]["recent_peer_chat_topics"]
        assert len(topics) == 5
        assert topics[-1] == "新话题"
        assert "旧话题0" not in topics

    async def test_peer_name_resolved_from_personas(self, monkeypatch):
        """传给决策器的 peer 名必须是 personas 的权威中文名。"""
        decision = _StubDecision({"should_send": False})
        host = _make_role_cycle_host(monkeypatch, decision=decision)

        await host._check_and_trigger_for_role("aveline", ROLE_CONN, [ROLE_CONN])
        assert decision.calls[0]["peer_name"] == "Ling"

    async def test_skip_paths_log_when_debug_enabled(self, monkeypatch):
        """debug.peer_chat 打开时，各条跳过路径都要落日志（排查"为什么没触发"）。"""
        import core.services.active_care.peer_chat.scheduler_role_cycle as cycle_mod

        monkeypatch.setattr(cycle_mod, "is_debug_enabled", lambda key: True)
        infos = _capture_logs(monkeypatch, cycle_mod)

        # 1) 全局每日上限已达
        host = _make_role_cycle_host(
            monkeypatch,
            storage=_StubStorage({"peer_chat_global_count_2026-09-22": 6}),
            daily_limit=6,
        )
        assert (
            await host._check_and_trigger_for_role("aveline", ROLE_CONN, [ROLE_CONN])
            is False
        )

        # 2) 距上次互聊未满最小间隔
        host = _make_role_cycle_host(
            monkeypatch,
            storage=_StubStorage({"last_peer_chat_ts": time.time() - 60.0}),
            min_gap=5400.0,
        )
        assert (
            await host._check_and_trigger_for_role("aveline", ROLE_CONN, [ROLE_CONN])
            is False
        )

        # 3) 用户最近活跃
        host = _make_role_cycle_host(monkeypatch, user_active=True)
        assert (
            await host._check_and_trigger_for_role("aveline", ROLE_CONN, [ROLE_CONN])
            is False
        )

        # 4) 不在用户空闲窗口内
        host = _make_role_cycle_host(monkeypatch, within_idle_window=False)
        assert (
            await host._check_and_trigger_for_role("aveline", ROLE_CONN, [ROLE_CONN])
            is False
        )

        # 5) peer 在睡眠中（peer 遍历时跳过）
        host = _make_role_cycle_host(monkeypatch, sleeping_roles=("ling",))
        assert (
            await host._check_and_trigger_for_role("aveline", ROLE_CONN, [ROLE_CONN])
            is False
        )

        joined = "\n".join(infos)
        assert "全局已达上限" in joined
        assert "间隔不足" in joined
        assert "用户最近活跃" in joined
        assert "不在用户空闲窗口内" in joined
        assert "角色在睡眠中" in joined

    async def test_peer_name_falls_back_to_role_id_when_persona_missing(
        self, monkeypatch
    ):
        """personas 里查不到 peer 时，peer_name 退回 role_id（不崩、不留空）。"""
        import core.services.dual_role.personas as personas

        decision = _StubDecision({"should_send": False})
        host = _make_role_cycle_host(monkeypatch, decision=decision)
        monkeypatch.setattr(personas, "get_persona", lambda role_id: None)

        await host._check_and_trigger_for_role("aveline", ROLE_CONN, [ROLE_CONN])
        assert decision.calls[0]["peer_name"] == "ling"

    async def test_life_sim_failure_is_swallowed(self, monkeypatch):
        """生命模拟不可用时降级为空 bio_state，不影响后续决策。"""
        import core.services.life_simulation as life_pkg

        decision = _StubDecision({"should_send": False})
        host = _make_role_cycle_host(monkeypatch, decision=decision)

        def _boom():
            raise RuntimeError("生命模拟未初始化")

        monkeypatch.setattr(life_pkg, "get_life_simulation_service", _boom)

        await host._check_and_trigger_for_role("aveline", ROLE_CONN, [ROLE_CONN])
        # 决策仍被调用 → 异常被吞掉、流程继续
        assert decision.calls


class TestGetMultiQqConnections:
    """多 QQ 连接列表与缓存。"""

    async def test_filters_connections_without_persona_filename(self, monkeypatch):
        """只保留配了 persona_filename 的连接（没配的无法路由）。"""
        host = _make_role_cycle_host(monkeypatch)

        class _Exec:
            @staticmethod
            def _get_qq_connections():
                return [
                    {"role_id": "aveline", "persona_filename": "core_aveline.json"},
                    {"role_id": "ling", "persona_filename": ""},
                    {"role_id": "ye"},
                ]

        host._executor = _Exec()
        result = await host._get_multi_qq_connections()
        assert len(result) == 1
        assert result[0]["role_id"] == "aveline"

    async def test_cache_reuse_within_ttl(self, monkeypatch):
        """TTL 内复用缓存，避免频繁扫描连接表。"""
        calls = {"n": 0}

        class _Exec:
            @staticmethod
            def _get_qq_connections():
                calls["n"] += 1
                return [{"role_id": "aveline", "persona_filename": "a.json"}]

        host = _make_role_cycle_host(monkeypatch)
        host._executor = _Exec()

        await host._get_multi_qq_connections()
        await host._get_multi_qq_connections()
        assert calls["n"] == 1

    async def test_cache_expires_after_ttl(self, monkeypatch):
        """超过 TTL 后重新拉取（冻结时间推进，不 sleep）。"""
        calls = {"n": 0}

        class _Exec:
            @staticmethod
            def _get_qq_connections():
                calls["n"] += 1
                return [{"role_id": "aveline", "persona_filename": "a.json"}]

        host = _make_role_cycle_host(monkeypatch)
        host._executor = _Exec()
        host._connections_cache_ttl = 10.0

        await host._get_multi_qq_connections()
        assert calls["n"] == 1

        # 直接把缓存时间戳往前推，等效于"过了 TTL"
        host._connections_cache_ts = time.time() - 3600.0
        await host._get_multi_qq_connections()
        assert calls["n"] == 2


class TestResolvePeerQqId:
    """对方 QQ 号解析回退链（配置 > 旧 env > 通用 env）。

    每个用例都先隔离真实数据源：multi_qq_config.json 里的真实配置与
    宿主机环境变量都不能参与断言，否则会变成"看本机配了啥"的 flaky 测试。
    """

    def test_config_value_wins(self, monkeypatch):
        """强类型配置里的 peer_qq_id 优先于环境变量。"""

        class _Cfg:
            peer_qq_id = "555"

        _isolate_peer_qq_config(monkeypatch, _Cfg)
        host = _make_role_cycle_host(monkeypatch)
        assert host._resolve_peer_qq_id("ling") == "555"

    def test_legacy_env_for_aveline(self, monkeypatch):
        """配置缺失时 aveline 走旧变量名 XIAOYOU_QQ_BOT_NUMBER。"""
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER", "777")
        host = _make_role_cycle_host(monkeypatch)
        assert host._resolve_peer_qq_id("aveline") == "777"

    def test_legacy_env_for_ling(self, monkeypatch):
        """配置缺失时 ling 走旧变量名 XIAOYOU_QQ_BOT_NUMBER_LING。"""
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_LING", "888")
        host = _make_role_cycle_host(monkeypatch)
        assert host._resolve_peer_qq_id("ling") == "888"

    def test_generic_env_fallback(self, monkeypatch):
        """N 角色通用回退 XIAOYOU_QQ_BOT_NUMBER_{ROLE_ID_UPPER}。"""
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_YE", "999")
        host = _make_role_cycle_host(monkeypatch)
        assert host._resolve_peer_qq_id("ye") == "999"

    def test_returns_empty_when_unresolvable(self, monkeypatch):
        """全都解析不出时返回空串（调用方据此跳过）。"""
        _isolate_peer_qq_config(monkeypatch)
        host = _make_role_cycle_host(monkeypatch)
        assert host._resolve_peer_qq_id("ye") == ""

    def test_blank_config_falls_through(self, monkeypatch):
        """配置值只有空白时继续走环境变量回退。"""

        class _Cfg:
            peer_qq_id = "   "

        _isolate_peer_qq_config(monkeypatch, _Cfg)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_YE", "999")
        host = _make_role_cycle_host(monkeypatch)
        assert host._resolve_peer_qq_id("ye") == "999"

    def test_legacy_env_takes_precedence_over_generic(self, monkeypatch):
        """旧 env 名优先于通用 env 名（aveline 同时配了两个时取旧的）。"""
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER", "777")
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_AVELINE", "666")
        host = _make_role_cycle_host(monkeypatch)
        assert host._resolve_peer_qq_id("aveline") == "777"

    def test_blank_legacy_env_falls_through_to_generic(self, monkeypatch):
        """旧 env 名为空白时继续走通用 env 名。"""
        _isolate_peer_qq_config(monkeypatch)
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER", "   ")
        monkeypatch.setenv("XIAOYOU_QQ_BOT_NUMBER_AVELINE", "666")
        host = _make_role_cycle_host(monkeypatch)
        assert host._resolve_peer_qq_id("aveline") == "666"
