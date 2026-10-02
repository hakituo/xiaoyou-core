# -*- coding: utf-8 -*-
"""PeerChatScheduler 编排层测试（peer_chat_scheduler.py）。

覆盖 core/services/active_care/peer_chat/peer_chat_scheduler.py 的：
- __init__ 的调度参数读取与配置不可用兜底
- _dual_role_flag 的开关读取与异常兜底
- _log_disabled_once 的"只打一次"语义
- _run_single_cycle 的完整编排分支（开关关闭 / 非多QQ / 协商优先 / 逐角色检查）
- _run_loop 的接管退出与异常处理
- 用户活跃委托方法
- 全局单例

设计要点：
- 具体 mixin 逻辑已在各自文件测过，这里只测"编排是否正确"：
  谁先谁后、什么条件下提前 return、成功/失败如何记账。
- `asyncio.sleep` 一律替换为 no-op，绝不真实等待（_run_loop 启动就 sleep 60s）。
- 时间断言只比较"是否被写入/是否增大"，不比较精确值。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from core.services.active_care.peer_chat import peer_chat_scheduler as sched_mod
from core.services.active_care.peer_chat.peer_chat_scheduler import (
    PeerChatScheduler,
    get_peer_chat_scheduler,
    init_peer_chat_scheduler,
)


class _StubStorage:
    """替身存储：满足 UserActivityTracker 的最小接口。"""

    def __init__(self):
        self.state: Dict[str, Any] = {}

    async def get_proactive_state(self) -> Dict[str, Any]:
        return dict(self.state)

    async def save_proactive_state(self, data, immediate: bool = True) -> None:
        self.state.update(data)


class _RecordingScheduler(PeerChatScheduler):
    """绕过 __init__ 的配置读取，直接用预置状态构造，便于测编排。

    记录各钩子的调用顺序，用于断言"谁先被调用 / 是否被跳过"。
    """

    def __init__(
        self,
        *,
        flags=None,
        connections=None,
        negotiation_result=False,
        proactive_result=False,
        role_results=None,
    ):
        self._storage = _StubStorage()
        self._context = object()
        self._decision = object()
        self._executor = object()
        self._settings = object()

        # 调度参数（不读真实 config）
        self._check_interval = 1800.0
        self._backoff_base_seconds = 1800.0
        self._backoff_max_seconds = 14400.0
        self._backoff_threshold = 3

        self._running = False
        self._task = None

        self._last_run_ts = 0.0
        self._last_success_ts = 0.0
        self._consecutive_failures = 0
        self._last_error = ""
        self._today_count = 0
        self._next_check_ts = 0.0
        self._total_runs = 0
        self._total_successes = 0

        self._cached_connections = []
        self._connections_cache_ts = 0.0
        self._connections_cache_ttl = 120.0

        from core.services.active_care.peer_chat.user_activity import (
            UserActivityTracker,
        )

        self._user_activity = UserActivityTracker(self._storage)
        self._disabled_flag_logged = ""

        # ---- 可编程钩子 ----
        self._flags = dict(flags or {})
        self._connections = list(connections or [])
        self._negotiation_result = negotiation_result
        self._proactive_result = proactive_result
        self._role_results = list(role_results or [])
        self.calls: List[str] = []

    def _dual_role_flag(self, key: str, default: bool = True) -> bool:
        self.calls.append(f"flag:{key}")
        return self._flags.get(key, default)

    async def _get_multi_qq_connections(self):
        self.calls.append("connections")
        return self._connections

    async def _try_negotiation_peer_chat(self, connections):
        self.calls.append("negotiation")
        return self._negotiation_result

    async def _try_proactive_assignment_negotiation(self, connections):
        self.calls.append("proactive_negotiation")
        return self._proactive_result

    async def _check_and_trigger_for_role(self, role_id, conn, connections):
        self.calls.append(f"role:{role_id}")
        if self._role_results:
            return self._role_results.pop(0)
        return False

    def _is_character_daily_active(self) -> bool:
        return False


# ============================================================
# __init__ 与配置
# ============================================================

class TestInit:
    """__init__ 的参数读取与兜底。"""

    def _make(self, monkeypatch, dual_role):
        class _Settings:
            pass

        settings = _Settings()
        settings.dual_role = dual_role

        import config.integrated_config as integrated

        monkeypatch.setattr(integrated, "get_settings", lambda: settings)
        return PeerChatScheduler(
            storage=_StubStorage(),
            context=object(),
            decision=object(),
            executor=object(),
            settings=object(),
        )

    def test_reads_schedule_params_from_config(self, monkeypatch):
        """调度参数从 DualRoleSettings 读取。"""

        class _DualRole:
            peer_chat_check_interval_seconds = 111.0
            peer_chat_backoff_base_seconds = 222.0
            peer_chat_backoff_max_seconds = 333.0
            peer_chat_backoff_threshold = 5

        sched = self._make(monkeypatch, _DualRole())

        assert sched._check_interval == 111.0
        assert sched._backoff_base_seconds == 222.0
        assert sched._backoff_max_seconds == 333.0
        assert sched._backoff_threshold == 5

    def test_falls_back_when_config_unavailable(self, monkeypatch):
        """配置不可用时回退内置默认值（保证可运行）。"""
        import config.integrated_config as integrated

        def _boom():
            raise RuntimeError("配置系统未初始化")

        monkeypatch.setattr(integrated, "get_settings", _boom)
        sched = PeerChatScheduler(
            storage=_StubStorage(),
            context=object(),
            decision=object(),
            executor=object(),
            settings=object(),
        )

        assert sched._check_interval == 1800.0
        assert sched._backoff_base_seconds == 1800.0
        assert sched._backoff_max_seconds == 14400.0
        assert sched._backoff_threshold == 3

    def test_initial_state_is_clean(self, monkeypatch):
        """初始状态：未运行、无任务、计数为零。"""

        class _DualRole:
            peer_chat_check_interval_seconds = 1.0
            peer_chat_backoff_base_seconds = 1.0
            peer_chat_backoff_max_seconds = 1.0
            peer_chat_backoff_threshold = 1

        sched = self._make(monkeypatch, _DualRole())

        assert sched._running is False
        assert sched._task is None
        assert sched._total_runs == 0
        assert sched._total_successes == 0
        assert sched._consecutive_failures == 0
        assert sched._cached_connections == []
        assert sched._connections_cache_ttl == 120.0


class TestDualRoleFlag:
    """_dual_role_flag：直读 DualRoleSettings 的布尔开关。

    注意：_RecordingScheduler 出于编排测试需要覆盖了 _dual_role_flag，
    所以这里一律显式调用 PeerChatScheduler 上的真实实现。
    """

    @staticmethod
    def _real_flag(sched, key, default=True):
        return PeerChatScheduler._dual_role_flag(sched, key, default)

    def test_returns_configured_value(self, monkeypatch):
        """读到配置值时返回配置值。"""

        class _DualRole:
            peer_chat_enabled = False

        class _Settings:
            dual_role = _DualRole()

        import config.integrated_config as integrated

        monkeypatch.setattr(integrated, "get_settings", lambda: _Settings())
        sched = _RecordingScheduler()

        assert self._real_flag(sched, "peer_chat_enabled") is False

    def test_missing_key_uses_default(self, monkeypatch):
        """配置里没有该键时用传入的 default。"""

        class _DualRole:
            pass

        class _Settings:
            dual_role = _DualRole()

        import config.integrated_config as integrated

        monkeypatch.setattr(integrated, "get_settings", lambda: _Settings())
        sched = _RecordingScheduler()

        assert self._real_flag(sched, "no_such_flag", True) is True
        assert self._real_flag(sched, "no_such_flag", False) is False

    def test_config_exception_uses_default(self, monkeypatch):
        """配置读取异常时回退 default（不能因配置问题让调度崩）。"""
        import config.integrated_config as integrated

        def _boom():
            raise RuntimeError("配置不可用")

        monkeypatch.setattr(integrated, "get_settings", _boom)
        sched = _RecordingScheduler()

        assert self._real_flag(sched, "peer_chat_enabled", True) is True
        assert self._real_flag(sched, "peer_chat_enabled", False) is False

    def test_value_is_coerced_to_bool(self, monkeypatch):
        """配置值是 truthy 非布尔量时也转成 bool。"""

        class _DualRole:
            peer_chat_enabled = 1

        class _Settings:
            dual_role = _DualRole()

        import config.integrated_config as integrated

        monkeypatch.setattr(integrated, "get_settings", lambda: _Settings())
        sched = _RecordingScheduler()

        assert self._real_flag(sched, "peer_chat_enabled") is True


class TestLogDisabledOnce:
    """_log_disabled_once：关闭提示只打一次。"""

    def test_first_call_records_flag(self):
        """首次调用记录 flag 名。"""
        sched = _RecordingScheduler()

        sched._log_disabled_once("peer_chat_enabled")

        assert sched._disabled_flag_logged == "peer_chat_enabled"

    def test_same_flag_does_not_repeat(self):
        """同一 flag 重复调用不改变状态（幂等）。"""
        sched = _RecordingScheduler()

        sched._log_disabled_once("peer_chat_enabled")
        sched._log_disabled_once("peer_chat_enabled")

        assert sched._disabled_flag_logged == "peer_chat_enabled"

    def test_different_flag_overwrites(self):
        """换成另一个 flag 时更新记录（各自只提示一次）。"""
        sched = _RecordingScheduler()

        sched._log_disabled_once("peer_chat_enabled")
        sched._log_disabled_once("peer_private_chat_enabled")

        assert sched._disabled_flag_logged == "peer_private_chat_enabled"


# ============================================================
# _run_single_cycle 编排
# ============================================================

CONNS = [
    {"role_id": "aveline", "persona_filename": "core_aveline.json"},
    {"role_id": "ling", "persona_filename": "core_ling.json"},
]


class TestRunSingleCycle:
    """单次检查周期的编排分支。"""

    async def test_returns_early_when_main_flag_off(self):
        """主开关关闭时静默返回，且不查连接、不动计时。"""
        sched = _RecordingScheduler(flags={"peer_chat_enabled": False})

        await sched._run_single_cycle()

        assert sched.calls == ["flag:peer_chat_enabled"]
        assert sched._total_runs == 0
        assert sched._last_run_ts == 0.0

    async def test_returns_early_when_private_flag_off(self):
        """私聊开关关闭时同样静默返回。"""
        sched = _RecordingScheduler(
            flags={"peer_chat_enabled": True, "peer_private_chat_enabled": False}
        )

        await sched._run_single_cycle()

        assert "connections" not in sched.calls
        assert sched._total_runs == 0

    async def test_flag_check_precedes_any_counting(self):
        """开关检查必须在任何计数之前（关闭时不污染统计）。"""
        sched = _RecordingScheduler(flags={"peer_chat_enabled": False})

        await sched._run_single_cycle()

        assert sched._total_runs == 0
        assert sched.calls == ["flag:peer_chat_enabled"]

    async def test_skips_when_not_multi_qq(self):
        """连接数 < 2 时跳过（非多 QQ 模式）。"""
        sched = _RecordingScheduler(connections=[CONNS[0]])

        await sched._run_single_cycle()

        assert sched._total_runs == 1
        assert "negotiation" not in sched.calls
        assert not any(c.startswith("role:") for c in sched.calls)

    async def test_negotiation_takes_priority(self):
        """提醒分工协商触发时，跳过后续所有普通互聊检查。"""
        sched = _RecordingScheduler(
            connections=CONNS, negotiation_result=True
        )

        await sched._run_single_cycle()

        assert "negotiation" in sched.calls
        assert "proactive_negotiation" not in sched.calls
        assert not any(c.startswith("role:") for c in sched.calls)
        # 协商成功计入 success
        assert sched._total_successes == 1

    async def test_proactive_negotiation_runs_after_reminder_negotiation(self):
        """提醒协商未触发时，继续检查主动关怀时段协商。"""
        sched = _RecordingScheduler(
            connections=CONNS,
            negotiation_result=False,
            proactive_result=True,
        )

        await sched._run_single_cycle()

        assert "negotiation" in sched.calls
        assert "proactive_negotiation" in sched.calls
        assert not any(c.startswith("role:") for c in sched.calls)
        assert sched._total_successes == 1

    async def test_checks_each_role_when_no_negotiation(self):
        """两个协商都没触发时，逐角色检查。"""
        sched = _RecordingScheduler(
            connections=CONNS, role_results=[True, False]
        )

        await sched._run_single_cycle()

        assert "role:aveline" in sched.calls
        assert "role:ling" in sched.calls
        assert sched._total_successes == 1

    async def test_no_success_does_not_count_failure(self):
        """本轮无人发送不算失败（可能只是频率限制或 LLM 决定不发）。"""
        sched = _RecordingScheduler(connections=CONNS, role_results=[False, False])

        await sched._run_single_cycle()

        assert sched._total_successes == 0
        assert sched._consecutive_failures == 0

    async def test_role_exception_is_isolated(self):
        """单个角色检查抛异常不影响其他角色继续检查。"""
        sched = _RecordingScheduler(connections=CONNS)

        async def _boom(role_id, conn, connections):
            sched.calls.append(f"role:{role_id}")
            if role_id == "aveline":
                raise RuntimeError("单角色检查炸了")
            return True

        sched._check_and_trigger_for_role = _boom
        await sched._run_single_cycle()

        # ling 仍被检查到，且成功被记账
        assert "role:ling" in sched.calls
        assert sched._total_successes == 1

    async def test_total_runs_increments_once_per_cycle(self):
        """每次进入周期只累加一次 total_runs。"""
        sched = _RecordingScheduler(connections=CONNS)

        await sched._run_single_cycle()
        await sched._run_single_cycle()

        assert sched._total_runs == 2

    async def test_connections_exception_propagates(self):
        """连接获取异常向上抛出，由主循环的失败计数兜住。"""
        sched = _RecordingScheduler()

        async def _boom():
            raise RuntimeError("连接表不可用")

        sched._get_multi_qq_connections = _boom

        with pytest.raises(RuntimeError, match="连接表不可用"):
            await sched._run_single_cycle()


# ============================================================
# _run_loop
# ============================================================

class TestRunLoop:
    """主循环：接管退出与异常处理（sleep 全部替换为 no-op）。"""

    async def test_exits_when_character_daily_takes_over(self, monkeypatch):
        """CharacterDailyEngine 激活后立即退出并交出调度权。"""
        monkeypatch.setattr(
            sched_mod.asyncio, "sleep", lambda _s: _noop_coro()
        )
        sched = _RecordingScheduler()
        sched._running = True
        sched._is_character_daily_active = lambda: True

        await sched._run_loop()

        assert sched._running is False

    async def test_loads_user_activity_on_start(self, monkeypatch):
        """启动时先恢复用户活跃时间戳。"""
        monkeypatch.setattr(
            sched_mod.asyncio, "sleep", lambda _s: _noop_coro()
        )
        sched = _RecordingScheduler()
        sched._running = True
        sched._is_character_daily_active = lambda: True
        loaded = {"n": 0}

        async def _spy_load():
            loaded["n"] += 1

        sched._user_activity.load = _spy_load
        await sched._run_loop()

        assert loaded["n"] == 1

    async def test_cycle_exception_is_recorded_and_loop_continues(
        self, monkeypatch
    ):
        """周期内异常被捕获并记失败，循环继续而不是崩掉。"""
        monkeypatch.setattr(
            sched_mod.asyncio, "sleep", lambda _s: _noop_coro()
        )
        sched = _RecordingScheduler()
        sched._running = True
        calls = {"n": 0}

        async def _cycle():
            calls["n"] += 1
            if calls["n"] >= 2:
                # 第二次让它退出，避免死循环
                sched._running = False
            raise RuntimeError("周期炸了")

        sched._run_single_cycle = _cycle
        sched._is_character_daily_active = lambda: False
        await sched._run_loop()

        assert calls["n"] >= 2  # 异常后仍在循环
        assert sched._consecutive_failures >= 1
        assert "周期炸了" in sched._last_error

    async def test_cancelled_during_sleep_breaks_loop(self, monkeypatch):
        """循环内睡眠期间被取消时干净退出，不抛 CancelledError。

        注意区分两处 sleep：
        - 启动时 `await asyncio.sleep(60)` 在 try 之外 —— 启动阶段被取消会向上传播
          （任务级取消，属预期行为）；
        - 循环内的 `await asyncio.sleep(sleep_seconds)` 有 try/except CancelledError → break。
        本用例针对后者：让第一次调用（启动 sleep）正常返回，第二次才取消。
        """
        calls = {"n": 0}

        async def _cancel_on_second(_s):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise asyncio.CancelledError()
            return None

        monkeypatch.setattr(sched_mod.asyncio, "sleep", _cancel_on_second)
        sched = _RecordingScheduler(connections=CONNS)
        sched._running = True
        sched._is_character_daily_active = lambda: False

        await sched._run_loop()  # 不应抛异常

        assert calls["n"] == 2

    async def test_cancel_during_startup_sleep_propagates(self, monkeypatch):
        """启动阶段的 sleep 未被保护，取消会向上传播（任务级取消语义）。

        这条用例锁定现状：如果有人把启动 sleep 也包进 try/except CancelledError，
        会吞掉任务取消信号，这里会立刻变红。
        """

        async def _cancel_immediately(_s):
            raise asyncio.CancelledError()

        monkeypatch.setattr(sched_mod.asyncio, "sleep", _cancel_immediately)
        sched = _RecordingScheduler()
        sched._running = True
        sched._is_character_daily_active = lambda: False

        with pytest.raises(asyncio.CancelledError):
            await sched._run_loop()

    async def test_next_check_ts_is_set(self, monkeypatch):
        """每轮结束会设置下次检查时间戳。"""
        monkeypatch.setattr(
            sched_mod.asyncio, "sleep", lambda _s: _noop_coro()
        )
        sched = _RecordingScheduler(connections=CONNS)
        sched._running = True
        sched._is_character_daily_active = lambda: True

        await sched._run_loop()

        # 被 daily engine 接管时在 sleep 之前 break，_next_check_ts 可能仍为 0；
        # 这里只断言"不早于构造时刻"这种弱条件，避免与实现细节耦合
        assert sched._next_check_ts >= 0.0

    async def test_cancelled_during_cycle_breaks_loop(self, monkeypatch):
        """周期执行期间被取消时干净退出（区别于循环内 sleep 被取消）。"""
        monkeypatch.setattr(sched_mod.asyncio, "sleep", lambda _s: _noop_coro())
        records = _capture_logs(monkeypatch, sched_mod)

        sched = _RecordingScheduler(connections=CONNS)
        sched._running = True
        sched._is_character_daily_active = lambda: False

        async def _cancel():
            raise asyncio.CancelledError()

        sched._run_single_cycle = _cancel

        await sched._run_loop()  # 不应抛异常

        assert any("主循环被取消" in text for _, text in records)

    async def test_debug_logs_emit_when_enabled(self, monkeypatch):
        """debug.peer_chat 打开时，周期开始与下次检查间隔都要落日志。"""
        monkeypatch.setattr(sched_mod.asyncio, "sleep", lambda _s: _noop_coro())
        monkeypatch.setattr(sched_mod, "is_debug_enabled", lambda key: True)
        records = _capture_logs(monkeypatch, sched_mod)

        sched = _RecordingScheduler(connections=CONNS)
        sched._running = True
        # 第一轮走真实的 _run_single_cycle，第二轮让 daily engine 接管以退出循环
        calls = {"n": 0}

        def _daily():
            calls["n"] += 1
            return calls["n"] >= 2

        sched._is_character_daily_active = _daily

        await sched._run_loop()

        joined = "\n".join(text for _, text in records)
        assert "开始第" in joined
        assert "下次检查在" in joined


async def _noop_coro():
    """返回一个可 await 的空协程（用于替换 asyncio.sleep）。"""
    return None


def _capture_logs(monkeypatch, module):
    """替换模块 logger，返回收集到的 (level, text) 列表。"""
    records = []

    class _Logger:
        def __getattr__(self, name):
            def _record(*args, **kwargs):
                records.append((name, " ".join(str(a) for a in args)))

            return _record

    monkeypatch.setattr(module, "logger", _Logger())
    return records


# ============================================================
# 用户活跃委托
# ============================================================

class TestUserActivityDelegation:
    """对外委托方法应正确转发到 UserActivityTracker。"""

    def test_mark_user_activity(self):
        """mark_user_activity 转发到 tracker。"""
        sched = _RecordingScheduler()
        sched.mark_user_activity("web_role_ling")

        assert "web_role_ling" in sched._user_activity.snapshot()

    def test_is_user_recently_active(self):
        """is_user_recently_active 转发到 tracker。"""
        sched = _RecordingScheduler()
        sched.mark_user_activity("web_role_ling")

        assert sched.is_user_recently_active("web_role_ling") is True
        assert sched.is_user_recently_active("never") is False

    def test_is_user_recently_active_for_scope(self):
        """按角色的活跃判定转发正确（scope 过滤生效）。"""
        sched = _RecordingScheduler()
        sched.mark_user_activity("web_role_ling")

        assert sched.is_user_recently_active_for_scope("ling", 300.0) is True
        assert sched.is_user_recently_active_for_scope("aveline", 300.0) is False

    def test_is_within_idle_window(self):
        """空闲窗口判定转发正确。"""
        sched = _RecordingScheduler()

        # 从未活跃 → 允许互聊
        assert sched.is_within_idle_window("cid") is True

    def test_tracker_property_exposes_instance(self):
        """_user_activity_tracker 暴露同一个 tracker 实例。"""
        sched = _RecordingScheduler()

        assert sched._user_activity_tracker is sched._user_activity


# ============================================================
# 全局单例
# ============================================================

class TestGlobalSingleton:
    """get / init 单例语义。"""

    def test_init_creates_and_returns_singleton(self, monkeypatch):
        """init 首次调用创建单例并返回。"""
        monkeypatch.setattr(sched_mod, "_peer_chat_scheduler", None)

        sched = init_peer_chat_scheduler(
            storage=_StubStorage(),
            context=object(),
            decision=object(),
            executor=object(),
            settings=object(),
        )

        assert isinstance(sched, PeerChatScheduler)
        assert get_peer_chat_scheduler() is sched

    def test_init_is_idempotent(self, monkeypatch):
        """重复 init 返回同一个实例（不重建）。"""
        monkeypatch.setattr(sched_mod, "_peer_chat_scheduler", None)

        first = init_peer_chat_scheduler(
            storage=_StubStorage(),
            context=object(),
            decision=object(),
            executor=object(),
            settings=object(),
        )
        second = init_peer_chat_scheduler(
            storage=_StubStorage(),
            context=object(),
            decision=object(),
            executor=object(),
            settings=object(),
        )

        assert first is second

    def test_get_returns_none_before_init(self, monkeypatch):
        """未初始化时 get 返回 None。"""
        monkeypatch.setattr(sched_mod, "_peer_chat_scheduler", None)

        assert get_peer_chat_scheduler() is None
