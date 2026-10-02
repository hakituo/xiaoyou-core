# -*- coding: utf-8 -*-
"""peer_chat 调度器 mixin 测试：健康追踪 / 生命周期 / 睡眠门禁。

覆盖 core/services/active_care/peer_chat/ 下的：
- scheduler_health.py      （成功失败计数、指数退避、健康快照、手动触发）
- scheduler_lifecycle.py   （启动/停止/幂等保活）
- scheduler_sleep_gate.py  （角色与用户睡眠门禁、主人 QQ 号解析）

设计要点：
- 退避逻辑断言的是**区间与相对关系**，不依赖真实时间流逝；
- 时间戳场景用 monkeypatch 冻结 time.time，不用 sleep；
- 睡眠门禁通过 monkeypatch get_sleep_manager 固定状态，避免"看几点跑"的 flaky。

实现说明：这些 mixin 的宿主方法（is_user_recently_active 等）由其所属的
PeerChatScheduler 提供；但本文件测试的行为都不调用宿主方法，故可直接用
`type("Fake", (Mixin,), {...})` 造一个最小宿主，无需拉起完整调度器。
"""

from __future__ import annotations

import asyncio
import time

import pytest

from core.services.active_care.peer_chat.scheduler_health import PeerChatHealthMixin
from core.services.active_care.peer_chat.scheduler_lifecycle import (
    PeerChatLifecycleMixin,
)
from core.services.active_care.peer_chat.scheduler_sleep_gate import (
    PeerChatSleepGateMixin,
)


# ============================================================
# 最小宿主构造器
# ============================================================

def _make_health_host():
    """构造只带健康追踪字段的最小宿主。"""

    class _Host(PeerChatHealthMixin):
        def __init__(self):
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
            # 退避参数：直接给固定值，不读 config，保证断言确定
            self._check_interval = 1800.0
            self._backoff_threshold = 3
            self._backoff_base_seconds = 1800.0
            self._backoff_max_seconds = 14400.0
            self._user_activity = None

    return _Host()


class _StubUserActivity:
    """替身用户活跃追踪器，只提供健康快照需要的 latest_ts()。"""

    def __init__(self, ts: float = 0.0):
        self._ts = ts

    def latest_ts(self) -> float:
        return self._ts


@pytest.fixture()
def health_host():
    host = _make_health_host()
    host._user_activity = _StubUserActivity()
    return host


# ============================================================
# scheduler_health.py
# ============================================================

class TestPeerChatHealthMixin:
    """成功/失败计数、退避间隔、健康快照。"""

    def test_record_success_resets_failure_counter(self, health_host):
        """成功一次必须把连续失败计数清零 —— 否则退避会永久卡在高档。"""
        health_host._record_failure("e1")
        health_host._record_failure("e2")
        assert health_host._consecutive_failures == 2
        health_host._record_success()
        assert health_host._consecutive_failures == 0
        assert health_host._total_successes == 1
        assert health_host._last_success_ts > 0

    def test_record_failure_increments_and_truncates_error(self, health_host):
        """失败计数递增，且 last_error 截断到 500 字符（避免状态文件被日志撑爆）。"""
        health_host._record_failure("x" * 900)
        assert health_host._consecutive_failures == 1
        assert len(health_host._last_error) == 500

    def test_record_failure_keeps_latest_error(self, health_host):
        """last_error 保留最近一次错误，便于健康快照定位问题。"""
        health_host._record_failure("first")
        health_host._record_failure("second")
        assert health_host._last_error == "second"

    def test_interval_is_base_below_threshold(self, health_host):
        """未达退避阈值时，间隔就是常规 check_interval，不做退避。"""
        health_host._consecutive_failures = 0
        assert health_host._compute_next_interval() == 1800.0
        health_host._consecutive_failures = 2  # threshold=3
        assert health_host._compute_next_interval() == 1800.0

    def test_interval_doubles_at_threshold(self, health_host):
        """恰好达到阈值时指数为 0 → base * 2^0 = base。"""
        health_host._consecutive_failures = 3
        assert health_host._compute_next_interval() == 1800.0

    def test_interval_grows_exponentially(self, health_host):
        """超过阈值后按 base * 2^(failures-threshold) 指数增长。"""
        health_host._consecutive_failures = 4
        assert health_host._compute_next_interval() == 3600.0
        health_host._consecutive_failures = 5
        assert health_host._compute_next_interval() == 7200.0

    def test_interval_is_capped_at_max(self, health_host):
        """指数项上限为 4，且结果被 backoff_max_seconds 封顶 —— 不能无限退避。"""
        health_host._consecutive_failures = 3 + 4  # exponent 恰好到上限
        assert health_host._compute_next_interval() == 14400.0
        # 再多失败也不涨
        health_host._consecutive_failures = 50
        assert health_host._compute_next_interval() == 14400.0

    def test_interval_never_exceeds_max_for_any_failure_count(self, health_host):
        """遍历一批失败次数，确认返回值恒在 [interval, max] 区间内。"""
        for failures in range(0, 20):
            health_host._consecutive_failures = failures
            interval = health_host._compute_next_interval()
            assert 1800.0 <= interval <= 14400.0

    def test_health_status_shape_and_defaults(self, health_host):
        """健康快照必须含全部对外字段，且未运行时的 -1 哨兵值正确。"""
        status = health_host.get_health_status()
        for key in (
            "running",
            "task_alive",
            "last_run_ts",
            "last_run_ago_seconds",
            "last_success_ts",
            "last_success_ago_seconds",
            "consecutive_failures",
            "last_error",
            "today_count",
            "total_runs",
            "total_successes",
            "next_check_ts",
            "next_check_in_seconds",
            "check_interval",
            "user_last_activity_ts",
            "peer_chat_metrics",
        ):
            assert key in status, f"健康快照缺少字段 {key}"

        # 从未运行/从未成功/从未安排下次检查 → -1 哨兵
        assert status["last_run_ago_seconds"] == -1
        assert status["last_success_ago_seconds"] == -1
        assert status["next_check_in_seconds"] == -1
        assert status["running"] is False
        assert status["task_alive"] is False
        assert status["check_interval"] == 1800.0

    def test_health_status_elapsed_seconds_are_frozen_time_safe(self, health_host):
        """冻结时间后校验 ago 秒数换算 —— 不依赖真实时间流逝。"""
        frozen_now = 1_800_000_000.0
        original = time.time
        try:
            time.time = lambda: frozen_now
            health_host._last_run_ts = frozen_now - 120
            health_host._last_success_ts = frozen_now - 300
            health_host._next_check_ts = frozen_now + 60
            status = health_host.get_health_status()
            assert status["last_run_ago_seconds"] == 120
            assert status["last_success_ago_seconds"] == 300
            assert status["next_check_in_seconds"] == 60
        finally:
            time.time = original

    def test_health_status_next_check_never_negative(self, health_host):
        """下次检查时刻已过期时，剩余秒数被 clamp 到 0 而不是负数。"""
        frozen_now = 1_800_000_000.0
        original = time.time
        try:
            time.time = lambda: frozen_now
            health_host._next_check_ts = frozen_now - 999
            assert health_host.get_health_status()["next_check_in_seconds"] == 0
        finally:
            time.time = original

    def test_health_status_task_alive_true_for_running_task(self, health_host):
        """有未完成 task 时 task_alive 为 True。"""

        async def _long():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise

        async def _scenario():
            task = asyncio.ensure_future(_long())
            try:
                health_host._task = task
                assert health_host.get_health_status()["task_alive"] is True
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

        asyncio.run(_scenario())

    def test_health_status_task_alive_false_for_finished_task(self, health_host):
        """task 已结束时 task_alive 为 False（供 ensure_running 判断重启）。"""

        async def _quick():
            return None

        async def _scenario():
            task = asyncio.ensure_future(_quick())
            await task
            health_host._task = task
            assert health_host.get_health_status()["task_alive"] is False

        asyncio.run(_scenario())

    def test_health_status_includes_peer_chat_metrics(self, health_host):
        """互聊效果指标必须内联进健康快照（供 API/前端读）。"""
        status = health_host.get_health_status()
        assert isinstance(status["peer_chat_metrics"], dict)
        # 单例存在时至少含 scripts_generated 这类已知键
        assert "scripts_generated" in status["peer_chat_metrics"]

    def test_run_single_check_success_path(self, health_host):
        """手动触发成功：返回 success=True 且带健康快照。"""

        async def _ok():
            return None

        health_host._run_single_cycle = _ok

        async def _scenario():
            return await health_host.run_single_check()

        result = asyncio.run(_scenario())
        assert result["success"] is True
        assert result["sent"] is True
        assert result["message"]
        assert isinstance(result["health"], dict)

    def test_run_single_check_failure_path(self, health_host):
        """手动触发失败：捕获异常并如实回传 error，不向上抛（API 端点不应 500）。"""

        async def _boom():
            raise RuntimeError("模拟周期异常")

        health_host._run_single_cycle = _boom

        async def _scenario():
            return await health_host.run_single_check()

        result = asyncio.run(_scenario())
        assert result["success"] is False
        assert result["sent"] is False
        assert "模拟周期异常" in result["error"]
        assert isinstance(result["health"], dict)

    def test_metrics_snapshot_degrades_to_empty_dict(self, health_host, monkeypatch):
        """指标模块不可用时 peer_chat_metrics 降级为空 dict，不让健康快照整体炸掉。"""
        from core.services.active_care.peer_chat import peer_chat_metrics

        def _boom():
            raise RuntimeError("指标模块不可用")

        monkeypatch.setattr(peer_chat_metrics, "get_peer_chat_metrics", _boom)

        assert health_host._get_peer_chat_metrics_snapshot() == {}


# ============================================================
# scheduler_lifecycle.py
# ============================================================

def _make_lifecycle_host():
    """构造生命周期宿主：不真正起循环，用替身记录 start/stop 行为。"""

    class _Host(PeerChatLifecycleMixin):
        def __init__(self):
            self._running = False
            self._task = None
            self._check_interval = 1800.0
            self.run_loop_calls = 0
            # 供测试覆写：默认认为 CharacterDailyEngine 未接管
            self.character_daily_active = False

        def _is_character_daily_active(self):  # 覆写基类实现，绕开真实引擎
            return self.character_daily_active

        async def _run_loop(self):
            self.run_loop_calls += 1
            await asyncio.sleep(3600)

    return _Host()


class TestPeerChatLifecycleMixin:
    """启动 / 停止 / 幂等保活。"""

    def test_start_when_character_daily_takes_over_skips_loop(self):
        """CharacterDailyEngine 已接管时不启独立循环，但必须标记 running。

        标记 running 是为了让 ensure_running 不再反复尝试启动 —— 否则每轮心跳都会
        重新走一遍 start()，日志被刷屏。
        """
        host = _make_lifecycle_host()
        host.character_daily_active = True

        assert host.start() is True
        assert host._running is True
        assert host._task is None
        assert host.run_loop_calls == 0

    def test_start_creates_task_when_not_taken_over(self):
        """未接管时真正起 asyncio task，并把 _running 置为 True。"""

        async def _scenario():
            host = _make_lifecycle_host()
            assert host.start() is True
            assert host._running is True
            assert host._task is not None
            # 让 task 真正跑一次循环体
            await asyncio.sleep(0)
            assert host.run_loop_calls == 1
            await host.stop()

        asyncio.run(_scenario())

    def test_start_is_idempotent_for_running_task(self):
        """已在运行且 task 未结束 → start() 直接返回 True，不重复起 task。"""

        async def _scenario():
            host = _make_lifecycle_host()
            host.start()
            first_task = host._task
            assert host.start() is True
            assert host._task is first_task
            await asyncio.sleep(0)
            assert host.run_loop_calls == 1
            await host.stop()

        asyncio.run(_scenario())

    def test_stop_cancels_task_and_clears_running(self):
        """stop() 取消 task 并把 _running 置 False。"""

        async def _scenario():
            host = _make_lifecycle_host()
            host.start()
            task = host._task
            await host.stop()
            assert host._running is False
            assert task.cancelled() or task.done()

        asyncio.run(_scenario())

    def test_stop_without_task_is_safe(self):
        """从未启动过就 stop() 不得抛异常（关闭流程会无脑调用）。"""

        async def _scenario():
            host = _make_lifecycle_host()
            await host.stop()
            assert host._running is False

        asyncio.run(_scenario())

    def test_ensure_running_returns_true_when_taken_over(self):
        """CharacterDailyEngine 接管时 ensure_running 直接 True，不起循环。"""
        host = _make_lifecycle_host()
        host.character_daily_active = True
        assert host.ensure_running() is True
        assert host.run_loop_calls == 0

    def test_ensure_running_starts_when_not_running(self):
        """未运行时 ensure_running 触发 start()。"""

        async def _scenario():
            host = _make_lifecycle_host()
            assert host.ensure_running() is True
            assert host._running is True
            assert host._task is not None
            await host.stop()

        asyncio.run(_scenario())

    def test_ensure_running_restarts_when_task_finished(self):
        """task 已结束（循环异常退出）时 ensure_running 必须重启。"""

        async def _scenario():
            host = _make_lifecycle_host()
            host._running = True
            host._task = asyncio.ensure_future(asyncio.sleep(0))
            await host._task  # 让它结束
            assert host._task.done()

            assert host.ensure_running() is True
            # 已经起了新 task
            assert host._task is not None
            assert not host._task.done()
            await host.stop()

        asyncio.run(_scenario())

    def test_ensure_running_noop_when_healthy(self):
        """正常运行中 ensure_running 是纯查询，不产生新 task。"""

        async def _scenario():
            host = _make_lifecycle_host()
            host.start()
            task = host._task
            assert host.ensure_running() is True
            assert host._task is task
            await host.stop()

        asyncio.run(_scenario())

    def test_is_character_daily_active_defaults_false_on_error(self, monkeypatch):
        """真实 _is_character_daily_active 在引擎不可用时返回 False（不抛异常）。"""
        # 注意：基类实现是 @staticmethod，不能 __get__ 绑定出实例方法，
        # 直接通过类访问（Python 3 下 staticmethod 访问即普通函数）。
        host = _make_lifecycle_host()
        real_impl = PeerChatLifecycleMixin._is_character_daily_active

        def _boom():
            raise RuntimeError("引擎未初始化")

        import core.services.character_daily.engine as engine_module

        monkeypatch.setattr(engine_module, "get_character_daily_engine", _boom)
        assert real_impl() is False

    def test_is_character_daily_active_true_when_engine_running(self, monkeypatch):
        """引擎 _running 为 True 时判定为已接管（调度权应移交）。"""
        real_impl = PeerChatLifecycleMixin._is_character_daily_active
        import core.services.character_daily.engine as engine_module

        class _Engine:
            _running = True

        monkeypatch.setattr(
            engine_module, "get_character_daily_engine", lambda: _Engine()
        )
        assert real_impl() is True

    def test_is_character_daily_active_false_when_engine_none(self, monkeypatch):
        """引擎实例为 None 时判定为未接管。"""
        real_impl = PeerChatLifecycleMixin._is_character_daily_active
        import core.services.character_daily.engine as engine_module

        monkeypatch.setattr(
            engine_module, "get_character_daily_engine", lambda: None
        )
        assert real_impl() is False

    def test_loop_crash_logs_and_schedules_restart(self, monkeypatch):
        """调度循环异常退出时记 error，并在 60s 后自动重启（未被接管时）。

        重启走 done_callback，那里可能不在协程上下文，所以实现用
        `asyncio.get_event_loop_policy().get_event_loop().call_later`；
        这里把模块内 asyncio 换成代理，只截获 call_later，不真等 60 秒。
        """
        from core.services.active_care.peer_chat import (
            scheduler_lifecycle as lifecycle_module,
        )

        errors = []

        class _Logger:
            def __getattr__(self, name):
                def _record(*args, **kwargs):
                    if name == "error":
                        errors.append(args)

                return _record

        monkeypatch.setattr(lifecycle_module, "logger", _Logger())

        scheduled = []

        class _Loop:
            def call_later(self, delay, cb):
                scheduled.append((delay, cb))

        class _Policy:
            def get_event_loop(self):
                return _Loop()

        class _AsyncioProxy:
            def __getattr__(self, name):
                if name == "get_event_loop_policy":
                    return lambda: _Policy()
                return getattr(asyncio, name)

        monkeypatch.setattr(lifecycle_module, "asyncio", _AsyncioProxy())

        host = _make_lifecycle_host()
        host.character_daily_active = False

        async def _crash():
            raise RuntimeError("循环炸了")

        host._run_loop = _crash

        async def _scenario():
            assert host.start() is True
            await asyncio.wait([host._task])
            # done_callback 由事件循环在任务结束后调度，多让几步确保跑完
            for _ in range(5):
                await asyncio.sleep(0)

        asyncio.run(_scenario())

        assert any("调度循环异常退出" in str(args) for args in errors)
        assert [delay for delay, _ in scheduled] == [60]


# ============================================================
# scheduler_sleep_gate.py
# ============================================================

class _StubSleepState:
    def __init__(self, phase):
        self.phase = phase


class _StubSleepManager:
    """替身睡眠管理器：按 role_id 返回预置 phase。"""

    def __init__(self, phases_by_role):
        self._phases = dict(phases_by_role)

    def get_state(self, role_id):
        return _StubSleepState(self._phases.get(role_id))


def _make_sleep_gate_host(monkeypatch, phases_by_role=None, connections=None, state=None):
    """构造睡眠门禁宿主，并把 get_sleep_manager 固定成替身。

    固定状态是防 flaky 的关键：真实 get_sleep_manager 会按当前**真实时间**推算
    phase，白天是 fully_awake 时门禁提前 return False，测试就变成"看几点跑"。
    """
    from core.services.active_care.peer_chat import scheduler_sleep_gate as gate_module
    from core.services.life_simulation import sleep_models

    if phases_by_role is not None:
        stub_manager = _StubSleepManager(phases_by_role)
        monkeypatch.setattr(
            gate_module, "get_sleep_manager", lambda: stub_manager, raising=False
        )
        # mixin 内部是函数体内 import，因此必须 patch 包级导出
        import core.services.life_simulation as life_pkg

        monkeypatch.setattr(life_pkg, "get_sleep_manager", lambda: stub_manager)

    class _Storage:
        def __init__(self, payload):
            self._payload = dict(payload or {})
            self.scopes = []

        def set_runtime_scope(self, scope):
            self.scopes.append(scope)

        async def get_proactive_state(self):
            return dict(self._payload)

        async def save_proactive_state(self, data, immediate=True):
            self._payload = dict(data)

    class _Host(PeerChatSleepGateMixin):
        def __init__(self):
            self._storage = _Storage(state or {})
            self._connections = list(connections or [])

        async def _get_multi_qq_connections(self):
            return list(self._connections)

    host = _Host()
    host._sleep_models = sleep_models
    return host


class TestPeerChatSleepGateMixin:
    """角色 / 用户睡眠门禁。"""

    def test_either_character_sleeping_when_first_is_sleeping(self, monkeypatch):
        """任一角色 SLEEPING 即命中门禁（peer_chat 需双方都参与）。"""
        from core.services.life_simulation.sleep_models import SleepPhase

        host = _make_sleep_gate_host(
            monkeypatch,
            phases_by_role={
                "aveline": SleepPhase.SLEEPING,
                "ling": SleepPhase.FULLY_AWAKE,
            },
        )

        async def _scenario():
            return await host._is_either_character_sleeping("aveline", "ling")

        assert asyncio.run(_scenario()) is True

    def test_either_character_sleeping_when_second_is_sleeping(self, monkeypatch):
        """第二个角色睡眠同样命中 —— 不能只查发起方。"""
        from core.services.life_simulation.sleep_models import SleepPhase

        host = _make_sleep_gate_host(
            monkeypatch,
            phases_by_role={
                "aveline": SleepPhase.FULLY_AWAKE,
                "ling": SleepPhase.SLEEPING,
            },
        )

        async def _scenario():
            return await host._is_either_character_sleeping("aveline", "ling")

        assert asyncio.run(_scenario()) is True

    def test_both_awake_passes_gate(self, monkeypatch):
        """双方都不在 SLEEPING 时放行。"""
        from core.services.life_simulation.sleep_models import SleepPhase

        host = _make_sleep_gate_host(
            monkeypatch,
            phases_by_role={
                "aveline": SleepPhase.FULLY_AWAKE,
                "ling": SleepPhase.FULLY_AWAKE,
            },
        )

        async def _scenario():
            return await host._is_either_character_sleeping("aveline", "ling")

        assert asyncio.run(_scenario()) is False

    def test_night_awake_does_not_block_gate(self, monkeypatch):
        """NIGHT_AWAKE（被叫醒后的清醒态）不得被拦 —— 只拦 SLEEPING。"""
        from core.services.life_simulation.sleep_models import SleepPhase

        host = _make_sleep_gate_host(
            monkeypatch,
            phases_by_role={
                "aveline": SleepPhase.NIGHT_AWAKE,
                "ling": SleepPhase.NIGHT_AWAKE,
            },
        )

        async def _scenario():
            return await host._is_either_character_sleeping("aveline", "ling")

        assert asyncio.run(_scenario()) is False

    def test_preparing_sleep_does_not_block_gate(self, monkeypatch):
        """PREPARING_SLEEP（准备入睡）只拦 SLEEPING，不拦准备态。"""
        from core.services.life_simulation.sleep_models import SleepPhase

        host = _make_sleep_gate_host(
            monkeypatch,
            phases_by_role={
                "aveline": SleepPhase.PREPARING_SLEEP,
                "ling": SleepPhase.FULLY_AWAKE,
            },
        )

        async def _scenario():
            return await host._is_either_character_sleeping("aveline", "ling")

        assert asyncio.run(_scenario()) is False

    def test_gate_fails_open_when_manager_unavailable(self, monkeypatch):
        """睡眠管理器不可用时门禁必须 fail-open（返回 False），不得因异常拦住互聊。"""
        import core.services.life_simulation as life_pkg

        def _boom():
            raise RuntimeError("生命模拟未启动")

        monkeypatch.setattr(life_pkg, "get_sleep_manager", _boom)
        host = _make_sleep_gate_host(monkeypatch)  # 不给 phases → 不装替身

        async def _scenario():
            return await host._is_either_character_sleeping("aveline", "ling")

        assert asyncio.run(_scenario()) is False

    def test_any_character_sleeping_detects_first_sleeper(self, monkeypatch):
        """N 角色版本：遍历列表，任一 SLEEPING 即 True。"""
        from core.services.life_simulation.sleep_models import SleepPhase

        host = _make_sleep_gate_host(
            monkeypatch,
            phases_by_role={
                "aveline": SleepPhase.FULLY_AWAKE,
                "ling": SleepPhase.SLEEPING,
                "ye": SleepPhase.FULLY_AWAKE,
            },
        )

        async def _scenario():
            return await host._is_any_character_sleeping(["aveline", "ling", "ye"])

        assert asyncio.run(_scenario()) is True

    def test_any_character_sleeping_false_when_none_sleeping(self, monkeypatch):
        """全都不在 SLEEPING 时返回 False。"""
        from core.services.life_simulation.sleep_models import SleepPhase

        host = _make_sleep_gate_host(
            monkeypatch,
            phases_by_role={
                "aveline": SleepPhase.FULLY_AWAKE,
                "ling": SleepPhase.WAKING_UP,
            },
        )

        async def _scenario():
            return await host._is_any_character_sleeping(["aveline", "ling"])

        assert asyncio.run(_scenario()) is False

    def test_any_character_sleeping_with_empty_list(self, monkeypatch):
        """空列表视为无人睡眠（不得误判为命中门禁）。"""
        host = _make_sleep_gate_host(monkeypatch, phases_by_role={})

        async def _scenario():
            return await host._is_any_character_sleeping([])

        assert asyncio.run(_scenario()) is False

    def test_any_character_sleeping_fails_open_on_error(self, monkeypatch):
        """N 角色版本同样 fail-open。"""
        import core.services.life_simulation as life_pkg

        def _boom():
            raise RuntimeError("生命模拟未启动")

        monkeypatch.setattr(life_pkg, "get_sleep_manager", _boom)
        host = _make_sleep_gate_host(monkeypatch)

        async def _scenario():
            return await host._is_any_character_sleeping(["aveline", "ling"])

        assert asyncio.run(_scenario()) is False


class TestIsUserSleeping:
    """用户睡眠判定：reduced_mode 与 sleep_session 两条规则。"""

    def test_reduced_mode_with_goodnight_reason_means_sleeping(self, monkeypatch):
        """reduced_mode_active + reason=goodnight → 用户已睡。"""
        host = _make_sleep_gate_host(
            monkeypatch,
            connections=[{"role_id": "aveline"}],
            state={
                "reduced_mode_active": True,
                "reduced_mode_reason": "goodnight",
            },
        )

        async def _scenario():
            return await host.is_user_sleeping()

        assert asyncio.run(_scenario()) is True

    def test_reduced_mode_with_sleep_hint_reason_means_sleeping(self, monkeypatch):
        """reason=sleep_hint 同样算睡眠。"""
        host = _make_sleep_gate_host(
            monkeypatch,
            connections=[{"role_id": "ling"}],
            state={
                "reduced_mode_active": True,
                "reduced_mode_reason": "sleep_hint",
            },
        )

        async def _scenario():
            return await host.is_user_sleeping()

        assert asyncio.run(_scenario()) is True

    def test_reduced_mode_with_unrelated_reason_is_not_sleeping(self, monkeypatch):
        """reduced_mode 原因是 focus/user_away 时不算睡眠（别把专注模式当睡觉）。"""
        host = _make_sleep_gate_host(
            monkeypatch,
            connections=[{"role_id": "aveline"}],
            state={
                "reduced_mode_active": True,
                "reduced_mode_reason": "focus_session",
            },
        )

        async def _scenario():
            return await host.is_user_sleeping()

        assert asyncio.run(_scenario()) is False

    def test_reduced_mode_inactive_is_not_sleeping(self, monkeypatch):
        """reduced_mode 未开启时，即便 reason 是 goodnight 也不算睡眠。"""
        host = _make_sleep_gate_host(
            monkeypatch,
            connections=[{"role_id": "aveline"}],
            state={
                "reduced_mode_active": False,
                "reduced_mode_reason": "goodnight",
            },
        )

        async def _scenario():
            return await host.is_user_sleeping()

        assert asyncio.run(_scenario()) is False

    def test_sleep_session_active_when_goodnight_after_goodmorning(self, monkeypatch):
        """last_goodnight_ts 晚于 last_goodmorning_ts → 会话内已道晚安，用户在睡。"""
        host = _make_sleep_gate_host(
            monkeypatch,
            connections=[{"role_id": "aveline"}],
            state={
                "last_goodnight_ts": 1_700_000_000.0,
                "last_goodmorning_ts": 1_699_000_000.0,
            },
        )

        async def _scenario():
            return await host.is_user_sleeping()

        assert asyncio.run(_scenario()) is True

    def test_sleep_session_ended_after_goodmorning(self, monkeypatch):
        """道过早安之后（goodmorning > goodnight）不再算睡眠。"""
        host = _make_sleep_gate_host(
            monkeypatch,
            connections=[{"role_id": "aveline"}],
            state={
                "last_goodnight_ts": 1_699_000_000.0,
                "last_goodmorning_ts": 1_700_000_000.0,
            },
        )

        async def _scenario():
            return await host.is_user_sleeping()

        assert asyncio.run(_scenario()) is False

    def test_no_history_is_not_sleeping(self, monkeypatch):
        """从未有过晚安/早安记录（全 0）时不算睡眠。"""
        host = _make_sleep_gate_host(
            monkeypatch,
            connections=[{"role_id": "aveline"}],
            state={},
        )

        async def _scenario():
            return await host.is_user_sleeping()

        assert asyncio.run(_scenario()) is False

    def test_no_connections_is_not_sleeping(self, monkeypatch):
        """没有可参与互聊的连接时直接返回 False（不过度推断用户在睡）。"""
        host = _make_sleep_gate_host(monkeypatch, connections=[], state={})

        async def _scenario():
            return await host.is_user_sleeping()

        assert asyncio.run(_scenario()) is False

    def test_single_scope_storage_failure_is_skipped(self, monkeypatch):
        """某个角色读状态失败时只跳过该角色，不能让整个判定崩掉。

        这是多角色遍历里的 `except Exception: continue`：一个角色的存储出问题，
        不应连带影响其他角色的睡眠判定。
        """
        class _FlakyStorage:
            """aveline 读状态抛异常，ling 正常返回晚安态。"""

            def __init__(self):
                self.scopes = []

            def set_runtime_scope(self, scope):
                self.scopes.append(scope)

            async def get_proactive_state(self):
                if self.scopes[-1] == "aveline":
                    raise RuntimeError("该角色状态不可读")
                return {"last_goodnight_ts": 200.0, "last_goodmorning_ts": 100.0}

        class _Host(PeerChatSleepGateMixin):
            def __init__(self):
                self._storage = _FlakyStorage()

            async def _get_multi_qq_connections(self):
                return [{"role_id": "aveline"}, {"role_id": "ling"}]

        host = _Host()

        async def _scenario():
            return await host.is_user_sleeping()

        # aveline 读取失败被跳过，ling 的晚安态仍然命中
        assert asyncio.run(_scenario()) is True
        assert host._storage.scopes == ["aveline", "ling"]

    def test_connection_lookup_failure_degrades_to_false(self, monkeypatch):
        """连接列表获取本身失败时降级为 False 并记 warning，不抛给调度器。"""
        from core.services.active_care.peer_chat import (
            scheduler_sleep_gate as gate_module,
        )

        warnings = []

        class _Logger:
            def __getattr__(self, name):
                def _record(*args, **kwargs):
                    warnings.append((name, args))

                return _record

        monkeypatch.setattr(gate_module, "logger", _Logger())

        class _Host(PeerChatSleepGateMixin):
            def __init__(self):
                self._storage = None

            async def _get_multi_qq_connections(self):
                raise RuntimeError("QQ 适配器不可用")

        async def _scenario():
            return await _Host().is_user_sleeping()

        assert asyncio.run(_scenario()) is False
        assert any(name == "warning" for name, _ in warnings)

    def test_resolve_master_qq_id_reads_first_active_instance(self, monkeypatch):
        """从活跃 QQ 实例里取第一个有效 QQ 号；无 cfg 的实例被跳过。"""
        import clients.bots.qq.main as qq_main

        class _Cfg:
            qq_id = "123456"

        class _Adapter:
            cfg = _Cfg()

        monkeypatch.setattr(
            qq_main.QQAdapter,
            "get_active_instances",
            classmethod(
                lambda cls: [{"adapter": _Adapter()}, {"adapter": None}]
            ),
        )

        host = _make_sleep_gate_host(monkeypatch)
        assert host._resolve_master_qq_id() == "123456"

    def test_resolve_master_qq_id_returns_empty_when_lookup_fails(
        self, monkeypatch
    ):
        """活跃实例查询抛异常时返回空串，不把异常抛给调度器。"""
        import clients.bots.qq.main as qq_main

        def _boom(cls):
            raise RuntimeError("QQ 未启动")

        monkeypatch.setattr(
            qq_main.QQAdapter, "get_active_instances", classmethod(_boom)
        )

        host = _make_sleep_gate_host(monkeypatch)
        assert host._resolve_master_qq_id() == ""
