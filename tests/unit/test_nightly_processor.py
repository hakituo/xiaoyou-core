"""memory/nightly_processor.py 单元测试。

覆盖范围：
- ``get_memory_distillation_model`` 兼容转发
- ``NightlyProcessor`` 的构造（默认配置、自定义配置合并、是否自动起调度器）
- 惰性服务/任务器缓存（``_get_analysis_service`` / ``_get_task_runner``）
- ``_start_scheduler``：已存活线程的处理、join 失败、正常启动、启动失败
- ``_scheduler_loop``：正常退出、异常兜底
- ``_sleep_aware_scheduler_loop``：日期滚动重置、当日已执行、首次检测到睡觉、
  睡够延迟触发、未睡够、醒来重置、Fallback 兜底、异常兜底
- ``process_all_users``：时间窗口外、已完成、执行中、scope 阶段（跳过已完成/成功/失败/
  返回错误标记）、全局阶段（成功/失败/已完成）、最终完成判定、外层异常与降级释放
- ``process_user_chat_history`` 与一票兼容转发方法
- ``_is_in_time_window`` 的普通窗口与跨零点窗口
- ``update_config`` / ``stop`` / ``get_status`` / ``_get_next_run_time``
- ``if __name__ == "__main__":`` 的三种 CLI 分支

不依赖真实资源：调度线程、运行状态存储、分析服务、任务执行器、时钟全部替换为桩，
不真的开线程、不真的扫盘、不真的跑任务、不真的等待。
"""

from __future__ import annotations

import datetime
import runpy
import sys
import threading
import time
import warnings

import pytest

from memory import nightly_processor as nproc
from memory import nightly as nightly_pkg
from memory import weighted_memory_manager as wmm


# ============================================================
# 桩与代理
# ============================================================

def _capture_logger(monkeypatch, module):
    """替换模块 logger，返回收集到的 (level, text) 列表。

    模块里既有 f-string 日志也有 ``%s`` 惰性格式化日志，这里统一把占位符渲染出来，
    否则断言会看到原始的 ``scope=%s`` 而匹配不上。
    """
    records = []

    class _Logger:
        def __getattr__(self, name):
            def _record(message, *args, **kwargs):
                text = str(message)
                if args:
                    try:
                        text = text % args
                    except (TypeError, ValueError):
                        text = " ".join([text, *(str(a) for a in args)])
                records.append((name, text))

            return _record

    monkeypatch.setattr(module, "logger", _Logger())
    return records


class _DatetimeStub:
    """替身 datetime.datetime：now() 返回受控值，其余透传真实 datetime.datetime。"""

    def __init__(self, now):
        self._now = now

    def now(self, tz=None):
        return self._now

    def __getattr__(self, name):
        return getattr(datetime.datetime, name)


class _DatetimeProxy:
    """替换模块内 datetime 引用：datetime 换成替身，date/timedelta 等透传真实 datetime。"""

    def __init__(self, now):
        self.datetime = _DatetimeStub(now)

    def __getattr__(self, name):
        return getattr(datetime, name)


class _StopEventStub:
    """替身 stop_event：wait() 不真的等待；达到 stop_on_wait 次数后置位并返回 True。"""

    def __init__(self, stop_on_wait=1):
        self._set = False
        self.waits = []
        self._stop_on_wait = stop_on_wait

    def is_set(self):
        return self._set

    def set(self):
        self._set = True

    def clear(self):
        self._set = False

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self._stop_on_wait is not None and len(self.waits) >= self._stop_on_wait:
            self._set = True
        return self._set


class _StartedFlagStub:
    def __init__(self, is_set=True):
        self._is_set = is_set

    def is_set(self):
        return self._is_set


class _ThreadStub:
    """替身线程：不真的跑 target，只记录 start/join 与存活状态。"""

    def __init__(self, target=None, daemon=None, name=None, alive=False, start_exc=None):
        self.target = target
        self.daemon = daemon
        self.name = name
        self.started = False
        self.joined = []
        self._alive = alive
        self._start_exc = start_exc

    def start(self):
        if self._start_exc is not None:
            raise self._start_exc
        self.started = True
        self._alive = True

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        self.joined.append(timeout)
        self._alive = False


class _ThreadWithStartedStub(_ThreadStub):
    """额外带 ``_started`` 启动栅栏（模拟真实 Thread），用于覆盖 join 前置判断。"""

    def __init__(self, started_is_set=True, join_exc=None, **kwargs):
        super().__init__(**kwargs)
        self._started = _StartedFlagStub(started_is_set)
        self._join_exc = join_exc

    def join(self, timeout=None):
        if self._join_exc is not None:
            raise self._join_exc
        super().join(timeout)


class _ThreadingProxy:
    """替换模块内 threading 引用：Thread 换成替身，Event/RLock 等透传真实 threading。"""

    def __init__(self, thread_cls=_ThreadStub):
        self.Thread = thread_cls

    def __getattr__(self, name):
        return getattr(threading, name)


class _RunStateStoreStub:
    """替身运行状态存储：全部状态放内存，不落盘。"""

    def __init__(self, begin_result="started", finish_exc=None):
        self.calls = []
        self.completed_scopes = set()
        self.global_completed = False
        self._begin_result = begin_result
        self._finish_exc = finish_exc

    def begin(self, target_date, trigger_reason):
        self.calls.append(("begin", target_date, trigger_reason))
        return self._begin_result

    def get_completed_scopes(self, target_date):
        return set(self.completed_scopes)

    def is_global_completed(self, target_date):
        return self.global_completed

    def mark_scope_completed(self, target_date, scope):
        self.calls.append(("mark_scope_completed", scope))
        self.completed_scopes.add(scope)

    def mark_scope_failed(self, target_date, scope, error):
        self.calls.append(("mark_scope_failed", scope, error))

    def mark_global_completed(self, target_date):
        self.calls.append(("mark_global_completed",))
        self.global_completed = True

    def mark_global_failed(self, target_date, error):
        self.calls.append(("mark_global_failed", error))

    def finish(self, target_date, *, completed):
        self.calls.append(("finish", completed))
        if self._finish_exc is not None:
            raise self._finish_exc

    def release(self, target_date):
        self.calls.append(("release",))


class _AnalysisServiceStub:
    def __init__(self, config, result=None):
        self.config = config
        self.calls = []
        self._result = result if result is not None else {"ok": True}

    def process_user_chat_history(self, user_id, manager, *, target_date,
                                  run_nightly_async_tasks):
        self.calls.append(("process", user_id, target_date, run_nightly_async_tasks))
        return self._result

    def analyze_message_content(self, messages):
        self.calls.append(("analyze", len(messages)))
        return {"messages": len(messages)}

    def save_analysis_result(self, user_id, result, *, target_date):
        self.calls.append(("save", user_id, target_date))


class _TaskRunnerStub:
    def __init__(self, config):
        self.config = config
        self.calls = []

    def run_nightly_async_tasks(self, user_id, manager, execute):
        self.calls.append(("run_nightly_async_tasks", user_id, manager, execute))
        return {"stub": True}

    async def execute_async_tasks(self, user_id, manager, distill):
        self.calls.append(("execute_async_tasks", user_id))
        return {"async": user_id}

    async def execute_scope_tasks(self, user_id, manager, distill):
        self.calls.append(("execute_scope_tasks", user_id))
        return {"scope": user_id}

    async def execute_global_tasks(self, target_date, memory_managers=None):
        self.calls.append(("execute_global_tasks", target_date.isoformat()))
        return {"global": target_date.isoformat()}

    async def distill_memories_async(self, user_id, manager):
        self.calls.append(("distill", user_id))
        return 3

    def generate_distillation_prompt(self, content):
        return [{"role": "user", "content": content}]

    def parse_distillation_response(self, response):
        return ("summary", ["kw"])


class _ScheduleStub:
    def __init__(self, run_pending_exc=None, jobs=None, jobs_exc=None):
        self.run_pending_calls = 0
        self.cleared = 0
        self._run_pending_exc = run_pending_exc
        self._jobs = jobs
        self._jobs_exc = jobs_exc

    def run_pending(self):
        self.run_pending_calls += 1
        if self._run_pending_exc is not None:
            raise self._run_pending_exc

    def clear(self):
        self.cleared += 1

    def get_jobs(self):
        if self._jobs_exc is not None:
            raise self._jobs_exc
        return list(self._jobs or [])


class _JobStub:
    def __init__(self, next_run=None):
        self.next_run = next_run


FIXED_NOW = datetime.datetime(2026, 9, 23, 3, 0, 0)
FIXED_TODAY = datetime.date(2026, 9, 23)


def _make_processor(monkeypatch, config=None, **stub_kwargs):
    """构造一个不自动起调度器的处理器，并把运行状态存储换成桩。

    注意：这里**不能**去 patch ``NightlyProcessor._start_scheduler`` —— 那样会把真正要
    被测的调度器启动逻辑一起换成空实现。改为把 ``enabled``/``auto_run`` 置假，让
    ``__init__`` 自然跳过启动。
    """
    merged = {"enabled": False, "auto_run": False, "start_time": "00:00", "end_time": "23:59"}
    if config:
        merged.update(config)
    processor = nproc.NightlyProcessor(merged)
    monkeypatch.setattr(nproc, "NightlyRunStateStore",
                        lambda *a, **k: _RunStateStoreStub(**stub_kwargs))
    return processor


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    """默认把模块内时钟固定住，需要时用例自行覆盖。"""
    monkeypatch.setattr(nproc, "get_current_time", lambda: FIXED_NOW)
    monkeypatch.setattr(nproc, "get_diary_target_date", lambda: FIXED_NOW)


@pytest.fixture
def processor(monkeypatch):
    return _make_processor(monkeypatch)


def _run_as_main(monkeypatch, argv):
    """以 ``__main__`` 身份重跑模块源码并返回其命名空间。

    ``runpy`` 会提示「模块已在 sys.modules 中」，这是本用法固有的无害警告，明确忽略。
    """
    monkeypatch.setattr(sys, "argv", argv)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return runpy.run_module("memory.nightly_processor", run_name="__main__")


# ============================================================
# 构造与惰性缓存
# ============================================================

class TestConstruction:
    def test_uses_default_config_and_starts_scheduler(self, monkeypatch):
        starts = []
        monkeypatch.setattr(
            nproc.NightlyProcessor, "_start_scheduler", lambda self: starts.append(1)
        )

        proc = nproc.NightlyProcessor()

        assert starts == [1]
        assert proc.config["enabled"] is True
        assert proc.config["auto_run"] is True
        assert proc._is_running is False
        assert proc._last_run_date is None
        assert proc._sleep_detected_time is None
        assert proc._task_executed_today is False
        assert proc._scheduler_thread is None

    def test_custom_config_is_merged_over_defaults(self, monkeypatch):
        monkeypatch.setattr(nproc.NightlyProcessor, "_start_scheduler", lambda self: None)

        proc = nproc.NightlyProcessor({"enabled": False, "start_time": "01:00"})

        assert proc.config["enabled"] is False
        assert proc.config["start_time"] == "01:00"
        # 未覆盖的键保留默认值
        assert proc.config["min_frequency"] == 3

    def test_no_scheduler_when_disabled(self, monkeypatch):
        starts = []
        monkeypatch.setattr(
            nproc.NightlyProcessor, "_start_scheduler", lambda self: starts.append(1)
        )

        nproc.NightlyProcessor({"enabled": False, "auto_run": True})

        assert starts == []

    def test_no_scheduler_when_auto_run_off(self, monkeypatch):
        starts = []
        monkeypatch.setattr(
            nproc.NightlyProcessor, "_start_scheduler", lambda self: starts.append(1)
        )

        nproc.NightlyProcessor({"enabled": True, "auto_run": False})

        assert starts == []


class TestLazyCollaborators:
    def test_analysis_service_is_created_once(self, processor, monkeypatch):
        monkeypatch.setattr(nproc, "NightlyAnalysisService", _AnalysisServiceStub)

        first = processor._get_analysis_service()
        second = processor._get_analysis_service()

        assert isinstance(first, _AnalysisServiceStub)
        assert first is second
        assert first.config is processor.config

    def test_analysis_service_is_recreated_when_config_identity_changes(self, processor, monkeypatch):
        monkeypatch.setattr(nproc, "NightlyAnalysisService", _AnalysisServiceStub)
        first = processor._get_analysis_service()

        processor.config = dict(processor.config)
        second = processor._get_analysis_service()

        assert second is not first
        assert second.config is processor.config

    def test_task_runner_is_created_once(self, processor, monkeypatch):
        monkeypatch.setattr(nproc, "NightlyTaskRunner", _TaskRunnerStub)

        first = processor._get_task_runner()
        second = processor._get_task_runner()

        assert isinstance(first, _TaskRunnerStub)
        assert first is second

    def test_task_runner_is_recreated_when_config_identity_changes(self, processor, monkeypatch):
        monkeypatch.setattr(nproc, "NightlyTaskRunner", _TaskRunnerStub)
        first = processor._get_task_runner()

        processor.config = dict(processor.config)
        second = processor._get_task_runner()

        assert second is not first

    def test_get_memory_distillation_model_delegates(self, monkeypatch):
        monkeypatch.setattr(nproc, "nightly_get_memory_distillation_model", lambda: "model-x")

        assert nproc.get_memory_distillation_model() == "model-x"


# ============================================================
# 调度线程启停
# ============================================================

class TestStartScheduler:
    def test_starts_daemon_thread(self, processor, monkeypatch):
        monkeypatch.setattr(nproc, "threading", _ThreadingProxy())
        records = _capture_logger(monkeypatch, nproc)

        processor._start_scheduler()

        thread = processor._scheduler_thread
        assert isinstance(thread, _ThreadStub)
        assert thread.daemon is True
        assert thread.name == "nightly-scheduler"
        assert thread.target == processor._sleep_aware_scheduler_loop
        assert thread.started is True
        assert processor._is_running is True
        assert any("夜间处理调度器已启动" in text for _, text in records)

    def test_replaces_existing_live_thread_with_started_flag(self, processor, monkeypatch):
        old = _ThreadWithStartedStub(started_is_set=True, alive=True)
        processor._scheduler_thread = old
        monkeypatch.setattr(nproc, "threading", _ThreadingProxy())
        records = _capture_logger(monkeypatch, nproc)

        processor._start_scheduler()

        assert any("调度器线程已存在" in text for _, text in records)
        assert old.joined == [3.0]
        assert processor._scheduler_thread is not old

    def test_skips_join_when_started_flag_not_set(self, processor, monkeypatch):
        old = _ThreadWithStartedStub(started_is_set=False, alive=True)
        processor._scheduler_thread = old
        monkeypatch.setattr(nproc, "threading", _ThreadingProxy())
        _capture_logger(monkeypatch, nproc)

        processor._start_scheduler()

        assert old.joined == []

    def test_skips_join_when_thread_has_no_started_attribute(self, processor, monkeypatch):
        old = _ThreadStub(alive=True)  # 没有 _started
        processor._scheduler_thread = old
        monkeypatch.setattr(nproc, "threading", _ThreadingProxy())
        _capture_logger(monkeypatch, nproc)

        processor._start_scheduler()

        assert old.joined == []

    def test_join_failure_is_logged(self, processor, monkeypatch):
        old = _ThreadWithStartedStub(
            started_is_set=True, alive=True, join_exc=RuntimeError("join 失败")
        )
        processor._scheduler_thread = old
        monkeypatch.setattr(nproc, "threading", _ThreadingProxy())
        records = _capture_logger(monkeypatch, nproc)

        processor._start_scheduler()

        assert any("停止旧调度器线程时出错" in text for _, text in records)
        assert processor._scheduler_thread is not old

    def test_start_failure_is_logged_and_flag_cleared(self, processor, monkeypatch):
        monkeypatch.setattr(
            nproc, "threading",
            _ThreadingProxy(lambda **kwargs: _ThreadStub(start_exc=RuntimeError("不能起线程"), **kwargs)),
        )
        records = _capture_logger(monkeypatch, nproc)

        processor._start_scheduler()

        assert processor._is_running is False
        assert any("启动调度器线程失败" in text for _, text in records)


class TestSchedulerLoop:
    def test_loop_breaks_when_stop_event_set_by_wait(self, processor, monkeypatch):
        schedule = _ScheduleStub()
        monkeypatch.setattr(nproc, "schedule", schedule)
        processor._stop_event = _StopEventStub(stop_on_wait=1)
        records = _capture_logger(monkeypatch, nproc)

        processor._scheduler_loop()

        assert schedule.run_pending_calls == 1
        assert processor._stop_event.waits == [60]
        assert processor._is_running is False
        assert any("调度器循环已停止" in text for _, text in records)

    def test_loop_swallows_exception_and_backs_off(self, processor, monkeypatch):
        schedule = _ScheduleStub(run_pending_exc=RuntimeError("调度炸了"))
        monkeypatch.setattr(nproc, "schedule", schedule)
        processor._stop_event = _StopEventStub(stop_on_wait=1)
        records = _capture_logger(monkeypatch, nproc)

        processor._scheduler_loop()

        assert schedule.run_pending_calls == 1
        assert processor._stop_event.waits == [60]
        assert any("调度器循环异常" in text for _, text in records)


class TestSleepAwareSchedulerLoop:
    """逐条覆盖睡眠感知调度循环的分支。"""

    def _run(self, processor, monkeypatch, now, stop_on_wait=1):
        monkeypatch.setattr(nproc, "datetime", _DatetimeProxy(now))
        processor._stop_event = _StopEventStub(stop_on_wait=stop_on_wait)
        records = _capture_logger(monkeypatch, nproc)
        processor._sleep_aware_scheduler_loop()
        return records

    def test_first_sleep_detection_sets_timestamp(self, processor, monkeypatch):
        processor._last_run_date = FIXED_TODAY
        monkeypatch.setattr(processor, "_check_user_sleeping", lambda: True)
        monkeypatch.setattr(processor, "process_all_users", lambda **kwargs: True)

        records = self._run(processor, monkeypatch, datetime.datetime(2026, 9, 23, 1, 0))

        assert processor._sleep_detected_time == datetime.datetime(2026, 9, 23, 1, 0)
        assert any("检测到用户开始睡觉" in text for _, text in records)
        assert processor._is_running is False

    def test_sleep_past_delay_triggers_processing(self, processor, monkeypatch):
        now = datetime.datetime(2026, 9, 23, 1, 0)
        processor._last_run_date = FIXED_TODAY
        processor._sleep_detected_time = now - datetime.timedelta(seconds=3700)
        monkeypatch.setattr(processor, "_check_user_sleeping", lambda: True)
        reasons = []

        def _process(**kwargs):
            reasons.append(kwargs["trigger_reason"])
            return False

        monkeypatch.setattr(processor, "process_all_users", _process)

        records = self._run(processor, monkeypatch, now)

        assert reasons == ["sleep"]
        assert processor._task_executed_today is False
        assert any("开始执行夜间处理" in text for _, text in records)

    def test_sleep_not_yet_due_logs_remaining(self, processor, monkeypatch):
        now = datetime.datetime(2026, 9, 23, 1, 0)
        processor._last_run_date = FIXED_TODAY
        processor._sleep_detected_time = now - datetime.timedelta(seconds=600)
        monkeypatch.setattr(processor, "_check_user_sleeping", lambda: True)
        monkeypatch.setattr(processor, "process_all_users", lambda **kwargs: True)

        records = self._run(processor, monkeypatch, now)

        assert processor._sleep_detected_time == now - datetime.timedelta(seconds=600)
        assert any("还需等待" in text for _, text in records)

    def test_waking_up_resets_detection(self, processor, monkeypatch):
        processor._last_run_date = FIXED_TODAY
        processor._sleep_detected_time = datetime.datetime(2026, 9, 23, 0, 30)
        monkeypatch.setattr(processor, "_check_user_sleeping", lambda: False)
        monkeypatch.setattr(processor, "process_all_users", lambda **kwargs: True)

        records = self._run(processor, monkeypatch, datetime.datetime(2026, 9, 23, 1, 0))

        assert processor._sleep_detected_time is None
        assert any("用户已醒来" in text for _, text in records)

    def test_fallback_window_forces_processing(self, processor, monkeypatch):
        processor._last_run_date = FIXED_TODAY
        monkeypatch.setattr(processor, "_check_user_sleeping", lambda: False)
        reasons = []

        def _process(**kwargs):
            reasons.append(kwargs["trigger_reason"])
            return True

        monkeypatch.setattr(processor, "process_all_users", _process)

        records = self._run(processor, monkeypatch, datetime.datetime(2026, 9, 23, 6, 0))

        assert reasons == ["fallback"]
        assert processor._task_executed_today is True
        assert any("到达 Fallback 时间" in text for _, text in records)

    def test_no_fallback_outside_window(self, processor, monkeypatch):
        processor._last_run_date = FIXED_TODAY
        monkeypatch.setattr(processor, "_check_user_sleeping", lambda: False)
        calls = []
        monkeypatch.setattr(processor, "process_all_users", lambda **kw: calls.append(1))

        records = self._run(processor, monkeypatch, datetime.datetime(2026, 9, 23, 1, 0))

        assert calls == []
        assert not any("到达 Fallback 时间" in text for _, text in records)

    def test_already_executed_today_waits(self, processor, monkeypatch):
        processor._last_run_date = FIXED_TODAY
        processor._task_executed_today = True
        calls = []
        monkeypatch.setattr(processor, "_check_user_sleeping", lambda: calls.append("sleep"))

        self._run(processor, monkeypatch, datetime.datetime(2026, 9, 23, 6, 0))

        assert calls == []  # 当日已执行 → 不再做睡眠检测

    def test_new_day_resets_daily_state(self, processor, monkeypatch):
        processor._last_run_date = FIXED_TODAY - datetime.timedelta(days=1)
        processor._task_executed_today = True
        processor._sleep_detected_time = datetime.datetime(2026, 9, 22, 23, 0)
        monkeypatch.setattr(processor, "_check_user_sleeping", lambda: False)
        monkeypatch.setattr(processor, "process_all_users", lambda **kwargs: True)

        self._run(processor, monkeypatch, datetime.datetime(2026, 9, 23, 1, 0))

        assert processor._last_run_date == FIXED_TODAY
        assert processor._task_executed_today is False
        assert processor._sleep_detected_time is None

    def test_exception_is_logged_and_loop_exits(self, processor, monkeypatch):
        processor._last_run_date = FIXED_TODAY

        def _boom():
            raise RuntimeError("睡眠检测炸了")

        monkeypatch.setattr(processor, "_check_user_sleeping", _boom)

        records = self._run(processor, monkeypatch, datetime.datetime(2026, 9, 23, 1, 0))

        assert any("睡眠感知调度器循环异常" in text for _, text in records)
        assert any("睡眠感知调度器循环已停止" in text for _, text in records)
        assert processor._is_running is False

    def test_already_executed_takes_continue_path(self, processor, monkeypatch):
        """当日已执行且本次 wait 未置位时，走 ``continue`` 回到循环顶部。"""
        processor._last_run_date = FIXED_TODAY
        processor._task_executed_today = True
        checked = []
        monkeypatch.setattr(processor, "_check_user_sleeping", lambda: checked.append(1))

        self._run(processor, monkeypatch, datetime.datetime(2026, 9, 23, 6, 0),
                  stop_on_wait=2)

        assert checked == []
        assert processor._stop_event.waits == [600, 600]

    def test_sleep_trigger_takes_continue_path(self, processor, monkeypatch):
        """睡眠触发后 wait 未置位 → ``continue``；下一轮因当日已执行而退出。"""
        now = datetime.datetime(2026, 9, 23, 1, 0)
        processor._last_run_date = FIXED_TODAY
        processor._sleep_detected_time = now - datetime.timedelta(seconds=3700)
        monkeypatch.setattr(processor, "_check_user_sleeping", lambda: True)
        monkeypatch.setattr(processor, "process_all_users", lambda **kwargs: True)

        self._run(processor, monkeypatch, now, stop_on_wait=2)

        assert processor._task_executed_today is True
        assert processor._stop_event.waits == [600, 600]

    def test_fallback_takes_continue_path(self, processor, monkeypatch):
        """Fallback 触发后 wait 未置位 → ``continue``；下一轮因当日已执行而退出。"""
        processor._last_run_date = FIXED_TODAY
        monkeypatch.setattr(processor, "_check_user_sleeping", lambda: False)
        monkeypatch.setattr(processor, "process_all_users", lambda **kwargs: True)

        self._run(processor, monkeypatch, datetime.datetime(2026, 9, 23, 6, 0),
                  stop_on_wait=2)

        assert processor._task_executed_today is True
        assert processor._stop_event.waits == [600, 600]


# ============================================================
# process_all_users
# ============================================================

class TestProcessAllUsers:
    def test_skips_outside_time_window(self, processor, monkeypatch):
        monkeypatch.setattr(processor, "_is_in_time_window", lambda: False)
        records = _capture_logger(monkeypatch, nproc)

        assert processor.process_all_users() is False
        assert any("当前不在配置的时间窗口内" in text for _, text in records)

    def test_returns_true_when_already_completed(self, processor, monkeypatch):
        store = _RunStateStoreStub(begin_result="completed")
        processor._run_state_store = store
        monkeypatch.setattr(processor, "_is_in_time_window", lambda: True)
        records = _capture_logger(monkeypatch, nproc)

        assert processor.process_all_users() is True
        assert any("夜间任务已完成" in text for _, text in records)
        assert not any(call[0] == "finish" for call in store.calls)

    def test_returns_false_when_already_active(self, processor, monkeypatch):
        store = _RunStateStoreStub(begin_result="active")
        processor._run_state_store = store
        monkeypatch.setattr(processor, "_is_in_time_window", lambda: True)
        records = _capture_logger(monkeypatch, nproc)

        assert processor.process_all_users() is False
        assert any("夜间任务正在执行" in text for _, text in records)

    def test_happy_path_marks_everything_completed(self, processor, monkeypatch):
        store = _RunStateStoreStub()
        processor._run_state_store = store
        monkeypatch.setattr(processor, "_is_in_time_window", lambda: True)
        monkeypatch.setattr(wmm, "_instances", {})
        monkeypatch.setattr(wmm, "_instances_lock", threading.RLock())
        monkeypatch.setattr(nproc, "load_users_from_disk", lambda: {"a": object()})
        monkeypatch.setattr(nproc, "filter_real_users", lambda managers: {"a": managers["a"]})
        monkeypatch.setattr(processor, "process_user_chat_history",
                            lambda *a, **k: {"ok": True})
        monkeypatch.setattr(processor, "_run_nightly_global_tasks", lambda *a, **k: {})
        records = _capture_logger(monkeypatch, nproc)

        assert processor.process_all_users() is True

        assert ("mark_scope_completed", "a") in store.calls
        assert ("mark_global_completed",) in store.calls
        assert ("finish", True) in store.calls
        assert any("夜间处理结束" in text for _, text in records)

    def test_uses_runtime_instances_without_disk_scan(self, processor, monkeypatch):
        store = _RunStateStoreStub()
        processor._run_state_store = store
        monkeypatch.setattr(processor, "_is_in_time_window", lambda: True)
        monkeypatch.setattr(wmm, "_instances", {"live": object()})
        monkeypatch.setattr(wmm, "_instances_lock", threading.RLock())
        disk_calls = []
        monkeypatch.setattr(nproc, "load_users_from_disk", lambda: disk_calls.append(1))
        monkeypatch.setattr(nproc, "filter_real_users", lambda managers: dict(managers))
        monkeypatch.setattr(processor, "process_user_chat_history", lambda *a, **k: {})
        monkeypatch.setattr(processor, "_run_nightly_global_tasks", lambda *a, **k: {})

        assert processor.process_all_users() is True

        assert disk_calls == []
        assert ("mark_scope_completed", "live") in store.calls

    def test_completed_scopes_are_skipped(self, processor, monkeypatch):
        store = _RunStateStoreStub()
        store.completed_scopes = {"done"}
        processor._run_state_store = store
        monkeypatch.setattr(processor, "_is_in_time_window", lambda: True)
        monkeypatch.setattr(wmm, "_instances", {"done": object(), "todo": object()})
        monkeypatch.setattr(wmm, "_instances_lock", threading.RLock())
        monkeypatch.setattr(nproc, "filter_real_users", lambda managers: dict(managers))
        processed = []
        monkeypatch.setattr(processor, "process_user_chat_history",
                            lambda scope_id, manager, **k: processed.append(scope_id) or {})
        monkeypatch.setattr(processor, "_run_nightly_global_tasks", lambda *a, **k: {})
        records = _capture_logger(monkeypatch, nproc)

        assert processor.process_all_users() is True

        assert processed == ["todo"]
        assert any("跳过已完成 scope" in text for _, text in records)

    def test_scope_failure_marks_failed_and_returns_partial(self, processor, monkeypatch):
        store = _RunStateStoreStub()
        processor._run_state_store = store
        monkeypatch.setattr(processor, "_is_in_time_window", lambda: True)
        monkeypatch.setattr(wmm, "_instances", {"bad": object()})
        monkeypatch.setattr(wmm, "_instances_lock", threading.RLock())
        monkeypatch.setattr(nproc, "filter_real_users", lambda managers: dict(managers))

        def _boom(*args, **kwargs):
            raise RuntimeError("scope 处理失败")

        monkeypatch.setattr(processor, "process_user_chat_history", _boom)
        monkeypatch.setattr(processor, "_run_nightly_global_tasks", lambda *a, **k: {})
        records = _capture_logger(monkeypatch, nproc)

        assert processor.process_all_users() is False

        assert ("mark_scope_failed", "bad", "scope 处理失败") in store.calls
        assert ("finish", False) in store.calls
        assert any("处理记忆 scope=bad 时出错" in text for _, text in records)

    def test_scope_error_marker_is_raised_as_failure(self, processor, monkeypatch):
        store = _RunStateStoreStub()
        processor._run_state_store = store
        monkeypatch.setattr(processor, "_is_in_time_window", lambda: True)
        monkeypatch.setattr(wmm, "_instances", {"bad": object()})
        monkeypatch.setattr(wmm, "_instances_lock", threading.RLock())
        monkeypatch.setattr(nproc, "filter_real_users", lambda managers: dict(managers))
        monkeypatch.setattr(
            processor, "process_user_chat_history",
            lambda *a, **k: {"nightly_scope_error": "标记出来的错误"},
        )
        monkeypatch.setattr(processor, "_run_nightly_global_tasks", lambda *a, **k: {})

        assert processor.process_all_users() is False

        assert ("mark_scope_failed", "bad", "标记出来的错误") in store.calls

    def test_global_failure_marks_failed(self, processor, monkeypatch):
        store = _RunStateStoreStub()
        processor._run_state_store = store
        monkeypatch.setattr(processor, "_is_in_time_window", lambda: True)
        monkeypatch.setattr(wmm, "_instances", {})
        monkeypatch.setattr(wmm, "_instances_lock", threading.RLock())
        monkeypatch.setattr(nproc, "load_users_from_disk", lambda: {})
        monkeypatch.setattr(nproc, "filter_real_users", lambda managers: {})
        monkeypatch.setattr(processor, "_run_nightly_global_tasks",
                            lambda *a, **k: {"global_error": "全局失败"})
        records = _capture_logger(monkeypatch, nproc)

        assert processor.process_all_users() is False

        assert ("mark_global_failed", "全局失败") in store.calls
        assert ("finish", False) in store.calls
        assert any("执行全局 nightly 阶段失败" in text for _, text in records)

    def test_global_nightly_error_key_is_also_honoured(self, processor, monkeypatch):
        store = _RunStateStoreStub()
        processor._run_state_store = store
        monkeypatch.setattr(processor, "_is_in_time_window", lambda: True)
        monkeypatch.setattr(wmm, "_instances", {})
        monkeypatch.setattr(wmm, "_instances_lock", threading.RLock())
        monkeypatch.setattr(nproc, "load_users_from_disk", lambda: {})
        monkeypatch.setattr(nproc, "filter_real_users", lambda managers: {})
        monkeypatch.setattr(processor, "_run_nightly_global_tasks",
                            lambda *a, **k: {"_nightly_error": "下划线错误"})

        assert processor.process_all_users() is False
        assert ("mark_global_failed", "下划线错误") in store.calls

    def test_global_stage_skipped_when_already_completed(self, processor, monkeypatch):
        store = _RunStateStoreStub()
        store.global_completed = True
        processor._run_state_store = store
        monkeypatch.setattr(processor, "_is_in_time_window", lambda: True)
        monkeypatch.setattr(wmm, "_instances", {})
        monkeypatch.setattr(wmm, "_instances_lock", threading.RLock())
        monkeypatch.setattr(nproc, "load_users_from_disk", lambda: {})
        monkeypatch.setattr(nproc, "filter_real_users", lambda managers: {})
        called = []
        monkeypatch.setattr(processor, "_run_nightly_global_tasks",
                            lambda *a, **k: called.append(1))
        records = _capture_logger(monkeypatch, nproc)

        assert processor.process_all_users() is True

        assert called == []
        assert any("跳过已完成全局 nightly 阶段" in text for _, text in records)

    def test_incomplete_scopes_make_result_partial(self, processor, monkeypatch):
        """scope 未被标记完成（例如被跳过）时，最终判定为未完成。"""
        store = _RunStateStoreStub()
        processor._run_state_store = store
        monkeypatch.setattr(processor, "_is_in_time_window", lambda: True)
        monkeypatch.setattr(wmm, "_instances", {"a": object()})
        monkeypatch.setattr(wmm, "_instances_lock", threading.RLock())
        monkeypatch.setattr(nproc, "filter_real_users", lambda managers: dict(managers))
        monkeypatch.setattr(processor, "process_user_chat_history", lambda *a, **k: {})
        monkeypatch.setattr(processor, "_run_nightly_global_tasks", lambda *a, **k: {})
        # 模拟 scope 未落地完成标记
        monkeypatch.setattr(store, "mark_scope_completed", lambda *a, **k: None)

        assert processor.process_all_users() is False
        assert ("finish", False) in store.calls

    def test_outer_exception_finishes_as_failed(self, processor, monkeypatch):
        store = _RunStateStoreStub()
        processor._run_state_store = store
        monkeypatch.setattr(processor, "_is_in_time_window", lambda: True)
        monkeypatch.setattr(wmm, "_instances", {})
        monkeypatch.setattr(wmm, "_instances_lock", threading.RLock())
        monkeypatch.setattr(
            nproc, "load_users_from_disk",
            lambda: (_ for _ in ()).throw(RuntimeError("扫盘炸了")),
        )
        records = _capture_logger(monkeypatch, nproc)

        assert processor.process_all_users() is False

        assert ("finish", False) in store.calls
        assert any("夜间处理过程中发生错误" in text for _, text in records)

    def test_outer_exception_falls_back_to_release(self, processor, monkeypatch):
        """finish 也失败时降级为 release，避免状态卡在执行中。"""
        store = _RunStateStoreStub(finish_exc=RuntimeError("finish 也炸了"))
        processor._run_state_store = store
        monkeypatch.setattr(processor, "_is_in_time_window", lambda: True)
        monkeypatch.setattr(wmm, "_instances", {})
        monkeypatch.setattr(wmm, "_instances_lock", threading.RLock())
        monkeypatch.setattr(
            nproc, "load_users_from_disk",
            lambda: (_ for _ in ()).throw(RuntimeError("扫盘炸了")),
        )
        _capture_logger(monkeypatch, nproc)

        assert processor.process_all_users() is False

        assert ("release",) in store.calls

    def test_target_date_datetime_is_normalised(self, processor, monkeypatch):
        store = _RunStateStoreStub()
        processor._run_state_store = store
        monkeypatch.setattr(processor, "_is_in_time_window", lambda: True)
        monkeypatch.setattr(wmm, "_instances", {})
        monkeypatch.setattr(wmm, "_instances_lock", threading.RLock())
        monkeypatch.setattr(nproc, "load_users_from_disk", lambda: {})
        monkeypatch.setattr(nproc, "filter_real_users", lambda managers: {})
        monkeypatch.setattr(processor, "_run_nightly_global_tasks", lambda *a, **k: {})

        processor.process_all_users(target_date=datetime.datetime(2026, 9, 20, 23, 30))

        assert ("begin", "2026-09-20", "manual") in store.calls

    def test_trigger_reason_is_forwarded(self, processor, monkeypatch):
        store = _RunStateStoreStub()
        processor._run_state_store = store
        monkeypatch.setattr(processor, "_is_in_time_window", lambda: True)
        monkeypatch.setattr(wmm, "_instances", {})
        monkeypatch.setattr(wmm, "_instances_lock", threading.RLock())
        monkeypatch.setattr(nproc, "load_users_from_disk", lambda: {})
        monkeypatch.setattr(nproc, "filter_real_users", lambda managers: {})
        monkeypatch.setattr(processor, "_run_nightly_global_tasks", lambda *a, **k: {})

        processor.process_all_users(trigger_reason="fallback")

        assert ("begin", "2026-09-23", "fallback") in store.calls


# ============================================================
# 兼容转发
# ============================================================

class TestCompatibilityDelegation:
    def test_process_user_chat_history_creates_manager_when_missing(self, processor, monkeypatch):
        sentinel = object()
        monkeypatch.setattr(nproc, "get_weighted_memory_manager", lambda user_id: sentinel)
        service = _AnalysisServiceStub(processor.config)
        monkeypatch.setattr(processor, "_get_analysis_service", lambda: service)

        result = processor.process_user_chat_history("u1")

        assert result == {"ok": True}
        assert service.calls[0][0] == "process"
        assert service.calls[0][1] == "u1"
        assert service.calls[0][2] == FIXED_TODAY
        # 传入的 run_nightly_async_tasks 应是处理器的 scope 桥接方法
        assert service.calls[0][3].__self__ is processor

    def test_process_user_chat_history_keeps_given_manager(self, processor, monkeypatch):
        manager = object()
        monkeypatch.setattr(
            nproc, "get_weighted_memory_manager",
            lambda user_id: pytest.fail("不应自行创建 manager"),
        )
        service = _AnalysisServiceStub(processor.config)
        monkeypatch.setattr(processor, "_get_analysis_service", lambda: service)

        processor.process_user_chat_history("u1", manager)

        assert service.calls[0][1] == "u1"

    def test_process_user_chat_history_normalises_datetime(self, processor, monkeypatch):
        service = _AnalysisServiceStub(processor.config)
        monkeypatch.setattr(processor, "_get_analysis_service", lambda: service)

        processor.process_user_chat_history(
            "u1", object(), target_date=datetime.datetime(2026, 9, 20, 23, 30)
        )

        assert service.calls[0][2] == datetime.date(2026, 9, 20)

    def test_process_user_chat_history_keeps_plain_date(self, processor, monkeypatch):
        service = _AnalysisServiceStub(processor.config)
        monkeypatch.setattr(processor, "_get_analysis_service", lambda: service)

        processor.process_user_chat_history("u1", object(), target_date=datetime.date(2026, 9, 19))

        assert service.calls[0][2] == datetime.date(2026, 9, 19)

    def test_run_nightly_scope_tasks_delegates(self, processor, monkeypatch):
        runner = _TaskRunnerStub(processor.config)
        monkeypatch.setattr(processor, "_get_task_runner", lambda: runner)

        assert processor._run_nightly_scope_tasks("u1", None) == {"stub": True}
        assert runner.calls[0][0] == "run_nightly_async_tasks"
        assert runner.calls[0][1] == "u1"
        assert runner.calls[0][3] == processor._execute_scope_tasks

    def test_run_nightly_async_tasks_delegates(self, processor, monkeypatch):
        runner = _TaskRunnerStub(processor.config)
        monkeypatch.setattr(processor, "_get_task_runner", lambda: runner)

        assert processor._run_nightly_async_tasks("u1", None) == {"stub": True}
        assert runner.calls[0][3] == processor._execute_async_tasks

    def test_run_nightly_global_tasks_delegates_with_synthetic_user(self, processor, monkeypatch):
        runner = _TaskRunnerStub(processor.config)
        monkeypatch.setattr(processor, "_get_task_runner", lambda: runner)

        assert processor._run_nightly_global_tasks(FIXED_TODAY, {"a": 1}) == {"stub": True}
        assert runner.calls[0][1] == "global:2026-09-23"
        assert runner.calls[0][2] is None

    def test_run_nightly_global_tasks_execute_closure(self, processor, monkeypatch):
        """把传给任务器的 execute 闭包取出来真正 await 一次，覆盖全局任务入口。"""
        import asyncio

        runner = _TaskRunnerStub(processor.config)
        captured = {}

        def _capture(user_id, manager, execute):
            captured["execute"] = execute
            return {"stub": True}

        monkeypatch.setattr(runner, "run_nightly_async_tasks", _capture)
        monkeypatch.setattr(processor, "_get_task_runner", lambda: runner)

        processor._run_nightly_global_tasks(FIXED_TODAY, {"a": 1})
        result = asyncio.run(captured["execute"]("global:2026-09-23", None))

        assert result == {"global": "2026-09-23"}
        assert ("execute_global_tasks", "2026-09-23") in runner.calls

    def test_execute_async_tasks_delegates(self, processor, monkeypatch):
        import asyncio

        runner = _TaskRunnerStub(processor.config)
        monkeypatch.setattr(processor, "_get_task_runner", lambda: runner)

        assert asyncio.run(processor._execute_async_tasks("u1", None)) == {"async": "u1"}

    def test_execute_scope_tasks_delegates(self, processor, monkeypatch):
        import asyncio

        runner = _TaskRunnerStub(processor.config)
        monkeypatch.setattr(processor, "_get_task_runner", lambda: runner)

        assert asyncio.run(processor._execute_scope_tasks("u1", None)) == {"scope": "u1"}

    def test_distill_memories_async_delegates(self, processor, monkeypatch):
        import asyncio

        runner = _TaskRunnerStub(processor.config)
        monkeypatch.setattr(processor, "_get_task_runner", lambda: runner)

        assert asyncio.run(processor._distill_memories_async("u1", None)) == 3

    def test_generate_distillation_prompt_delegates(self, processor, monkeypatch):
        runner = _TaskRunnerStub(processor.config)
        monkeypatch.setattr(processor, "_get_task_runner", lambda: runner)

        assert processor._generate_distillation_prompt("内容") == [
            {"role": "user", "content": "内容"}
        ]

    def test_parse_distillation_response_delegates(self, processor, monkeypatch):
        runner = _TaskRunnerStub(processor.config)
        monkeypatch.setattr(processor, "_get_task_runner", lambda: runner)

        assert processor._parse_distillation_response("原文") == ("summary", ["kw"])

    def test_analyze_message_content_delegates(self, processor, monkeypatch):
        service = _AnalysisServiceStub(processor.config)
        monkeypatch.setattr(processor, "_get_analysis_service", lambda: service)

        assert processor._analyze_message_content([{}, {}]) == {"messages": 2}

    def test_save_analysis_result_delegates(self, processor, monkeypatch):
        service = _AnalysisServiceStub(processor.config)
        monkeypatch.setattr(processor, "_get_analysis_service", lambda: service)

        processor._save_analysis_result("u1", {"k": 1})

        assert service.calls == [("save", "u1", FIXED_TODAY)]

    def test_check_user_sleeping_delegates(self, processor, monkeypatch):
        monkeypatch.setattr(nproc, "check_user_sleeping", lambda: True)

        assert processor._check_user_sleeping() is True

    def test_load_users_from_disk_delegates(self, processor, monkeypatch):
        monkeypatch.setattr(nproc, "load_users_from_disk", lambda: {"a": 1})

        assert processor._load_users_from_disk() == {"a": 1}


# ============================================================
# 时间窗口 / 配置 / 状态
# ============================================================

class TestTimeWindow:
    @pytest.mark.parametrize(
        "start,end,now,expected",
        [
            ("23:00", "12:00", "03:00", True),    # 跨零点窗口内（凌晨）
            ("23:00", "12:00", "23:30", True),    # 跨零点窗口内（深夜）
            ("23:00", "12:00", "15:00", False),   # 跨零点窗口外
            ("09:00", "17:00", "10:00", True),    # 普通窗口内
            ("09:00", "17:00", "08:00", False),   # 普通窗口外
            ("09:00", "17:00", "09:00", True),    # 左边界闭区间
            ("09:00", "17:00", "17:00", True),    # 右边界闭区间
        ],
    )
    def test_window_membership(self, monkeypatch, start, end, now, expected):
        monkeypatch.setattr(nproc.NightlyProcessor, "_start_scheduler", lambda self: None)
        proc = nproc.NightlyProcessor(
            {"enabled": False, "start_time": start, "end_time": end}
        )
        hour, minute = (int(part) for part in now.split(":"))
        monkeypatch.setattr(
            nproc, "get_current_time",
            lambda: datetime.datetime(2026, 9, 23, hour, minute),
        )

        assert proc._is_in_time_window() is expected


class TestUpdateConfigAndStop:
    def test_non_trigger_key_does_not_restart(self, processor, monkeypatch):
        starts = []
        monkeypatch.setattr(processor, "_start_scheduler", lambda: starts.append(1))
        records = _capture_logger(monkeypatch, nproc)

        processor.update_config({"min_frequency": 9})

        assert starts == []
        assert processor.config["min_frequency"] == 9
        assert any("配置已更新" in text for _, text in records)

    def test_trigger_key_restarts_when_enabled(self, processor, monkeypatch):
        starts = []
        monkeypatch.setattr(processor, "_start_scheduler", lambda: starts.append(1))
        _capture_logger(monkeypatch, nproc)

        processor.update_config({"enabled": True, "auto_run": True})

        assert starts == [1]

    def test_trigger_key_stops_when_disabled(self, processor, monkeypatch):
        stops = []
        monkeypatch.setattr(processor, "stop", lambda: stops.append(1))
        _capture_logger(monkeypatch, nproc)

        processor.update_config({"enabled": False})

        assert stops == [1]

    def test_stop_joins_thread_and_clears_schedule(self, processor, monkeypatch):
        alive = _ThreadStub(alive=True)
        processor._scheduler_thread = alive
        schedule = _ScheduleStub()
        monkeypatch.setattr(nproc, "schedule", schedule)
        records = _capture_logger(monkeypatch, nproc)

        processor.stop()

        assert processor._stop_event.is_set() is True
        assert alive.joined == [5.0]
        assert schedule.cleared == 1
        assert processor._is_running is False
        assert any("调度器线程已停止" in text for _, text in records)
        assert any("夜间处理器已停止" in text for _, text in records)

    def test_stop_without_live_thread(self, processor, monkeypatch):
        schedule = _ScheduleStub()
        monkeypatch.setattr(nproc, "schedule", schedule)
        records = _capture_logger(monkeypatch, nproc)

        processor.stop()

        assert schedule.cleared == 1
        assert not any("调度器线程已停止" in text for _, text in records)

    def test_stop_join_failure_is_logged(self, processor, monkeypatch):
        alive = _ThreadStub(alive=True)

        def _bad_join(timeout=None):
            raise RuntimeError("join 失败")

        monkeypatch.setattr(alive, "join", _bad_join)
        processor._scheduler_thread = alive
        monkeypatch.setattr(nproc, "schedule", _ScheduleStub())
        records = _capture_logger(monkeypatch, nproc)

        processor.stop()

        assert any("停止调度器线程时出错" in text for _, text in records)


class TestStatus:
    def test_get_status_shape(self, processor, monkeypatch):
        monkeypatch.setattr(processor, "_get_next_run_time", lambda: "2026-09-23T05:00:00")
        processor._is_running = True

        status = processor.get_status()

        assert status["enabled"] is False
        assert status["running"] is True
        assert status["next_run_time"] == "2026-09-23T05:00:00"
        assert status["config"] == processor.config
        # 返回的是副本，改动不影响原配置
        status["config"]["min_frequency"] = 999
        assert processor.config["min_frequency"] != 999

    def test_next_run_time_without_jobs(self, processor, monkeypatch):
        monkeypatch.setattr(nproc, "schedule", _ScheduleStub(jobs=[]))

        assert processor._get_next_run_time() is None

    def test_next_run_time_with_job(self, processor, monkeypatch):
        next_run = datetime.datetime(2026, 9, 23, 5, 0, 0)
        monkeypatch.setattr(nproc, "schedule", _ScheduleStub(jobs=[_JobStub(next_run)]))

        assert processor._get_next_run_time() == next_run.isoformat()

    def test_next_run_time_with_job_missing_next_run(self, processor, monkeypatch):
        monkeypatch.setattr(nproc, "schedule", _ScheduleStub(jobs=[_JobStub(None)]))

        assert processor._get_next_run_time() is None

    def test_next_run_time_failure_is_logged(self, processor, monkeypatch):
        monkeypatch.setattr(nproc, "schedule", _ScheduleStub(jobs_exc=RuntimeError("取任务失败")))
        records = _capture_logger(monkeypatch, nproc)

        assert processor._get_next_run_time() is None
        assert any("获取下次运行时间时出错" in text for _, text in records)


# ============================================================
# __main__ CLI 入口
# ============================================================

class TestMainBlock:
    """``if __name__ == "__main__":`` 三种分支。

    用 ``runpy`` 以 ``__main__`` 身份重跑模块源码；所有协作对象预先替换为桩，
    保证不真的开调度线程、不真的扫盘、不真的跑任务。
    """

    @pytest.fixture
    def cli_env(self, monkeypatch, tmp_path):
        """把新模块命名空间会读到的模块级名字全部换成桩。"""
        monkeypatch.setattr(nightly_pkg, "ANALYSIS_DIR", str(tmp_path))
        monkeypatch.setattr(
            nightly_pkg, "DEFAULT_NIGHTLY_CONFIG",
            {
                "enabled": False,
                "auto_run": False,
                "start_time": "00:00",
                "end_time": "23:59",
            },
        )
        monkeypatch.setattr(nightly_pkg, "NightlyRunStateStore", _RunStateStoreStub)
        monkeypatch.setattr(nightly_pkg, "NightlyTaskRunner", _TaskRunnerStub)
        monkeypatch.setattr(nightly_pkg, "NightlyAnalysisService", _AnalysisServiceStub)
        monkeypatch.setattr(nightly_pkg, "filter_real_users", lambda managers: {})
        monkeypatch.setattr(nightly_pkg, "load_users_from_disk", lambda: {})
        monkeypatch.setattr(nightly_pkg, "check_user_sleeping", lambda: False)
        monkeypatch.setattr(wmm, "_instances", {})
        monkeypatch.setattr(wmm, "_instances_lock", threading.RLock())
        monkeypatch.setattr(
            wmm, "get_weighted_memory_manager", lambda user_id: object()
        )
        return tmp_path

    def test_no_arguments_processes_all_users(self, monkeypatch, cli_env):
        namespace = _run_as_main(monkeypatch, ["nightly_processor"])

        assert namespace["__name__"] == "__main__"
        assert "NightlyProcessor" in namespace

    def test_user_argument_prints_json(self, monkeypatch, cli_env, capsys):
        _run_as_main(monkeypatch, ["nightly_processor", "--user", "u1"])

        printed = capsys.readouterr().out
        assert '"ok": true' in printed

    def test_auto_argument_exits_on_keyboard_interrupt(self, monkeypatch, cli_env):
        def _interrupt(_seconds):
            raise KeyboardInterrupt

        monkeypatch.setattr(time, "sleep", _interrupt)

        # 不应把 KeyboardInterrupt 抛给调用方
        _run_as_main(monkeypatch, ["nightly_processor", "--auto"])
