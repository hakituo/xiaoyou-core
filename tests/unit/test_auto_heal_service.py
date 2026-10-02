"""``core/services/auto_heal/heal_service.py`` 的单元测试。

覆盖重点：

- 初始化 / 关闭生命周期与后台任务调度（含配置读取、禁用、异常降级）
- 异常检测 → 根因分析 → 补丁生成 / 验证 / 应用 的完整分支走向
- 每日 / 单文件配额、受保护文件、auto_apply 三层风险限制
- 历史记录加载 / 保存、事件发布、健康检查注册
- 各条降级 / 失败 / 异常兜底路径

约定：全部下游协作者（detector / analyzer / generator / sandbox /
patch_manager / report_generator / event_bus / websocket / workspace /
self_improvement / health_checker）均替换为内存替身，
**不做任何真实修复动作**，不 sleep、不依赖真实时间，
除 ``tmp_path`` 外不触碰真实文件系统。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

# 注意：heal_service 必须最先导入，避免 event_bus 与 log_sanitizer 之间的循环导入。
import core.services.auto_heal.heal_service as heal_service
import core.core_engine.event_bus as event_bus_module
import core.interfaces.websocket.websocket_manager as ws_module
import core.services.self_improvement.service as si_module
import core.services.workspace.service as ws_service_module
import core.async_monitor as async_monitor_module
import config.integrated_config as integrated_config_module
import core.utils.errors.log_sanitizer as log_sanitizer_module
import core.utils.shared_roots as shared_roots_module

from core.contracts import AnomalySeverity
from core.services.auto_heal.models import (
    AnomalyEvent,
    AnomalyType,
    Patch,
    PatchStatus,
    RootCauseReport,
)

AutoHealService = heal_service.AutoHealService


# --------------------------------------------------------------------------- #
# 替身（全部内存实现，不做真实 IO / 修复动作）
# --------------------------------------------------------------------------- #
class _StubDetector:
    """异常检测器替身。"""

    def __init__(self, anomalies=None, error_stats=None):
        self.anomalies = list(anomalies or [])
        self.error_stats = error_stats or {"errors_last_5m": 0}
        self.flush_calls = 0
        self.raise_on_check = None
        self.raise_on_error = None
        self.received_errors = []

    def check_anomalies(self):
        if self.raise_on_check is not None:
            raise self.raise_on_check
        return list(self.anomalies)

    async def flush_state_async(self, force: bool = False):
        self.flush_calls += 1

    def on_error(self, error_id, error_report):
        if self.raise_on_error is not None:
            raise self.raise_on_error
        self.received_errors.append((error_id, error_report))

    def get_error_stats(self):
        return dict(self.error_stats)


class _StubAnalyzer:
    """根因分析器替身。"""

    def __init__(self, result=None, raise_exc=None):
        self.result = result
        self.raise_exc = raise_exc
        self.calls = []

    async def analyze(self, anomaly, persona_context=None):
        self.calls.append((anomaly, persona_context))
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.result


class _StubGenerator:
    """补丁生成器替身。"""

    def __init__(self, patch=None):
        self.patch = patch
        self.calls = []

    async def generate(self, root_cause, persona_context=None):
        self.calls.append((root_cause, persona_context))
        return self.patch


class _StubSandbox:
    """补丁沙箱替身。"""

    def __init__(self, verification=None):
        self.verification = verification or {"overall_ok": True}
        self.verified_patches = []

    async def verify(self, patch):
        self.verified_patches.append(patch)
        return dict(self.verification)


class _StubPatchManager:
    """补丁管理器替身。"""

    def __init__(self):
        self.patches = {}
        self.heal_count = 0
        self.daily_patch_count = 0
        self.daily_limit_ok = True
        self.file_limit_ok = True
        self.protected = False
        self.save_state_calls = 0
        self.registered = []
        self.apply_result = {"success": False, "message": "not set"}
        self.rollback_result = {"success": False, "message": "not set"}
        self.reject_result = {"success": False, "message": "not set"}
        self.pending = [{"id": "p1"}]
        self.all_patches = [{"id": "p1"}, {"id": "p2"}]
        self.detail = {"id": "p1", "diff": "d"}

    def check_daily_limit(self):
        return self.daily_limit_ok

    def check_file_limit(self, file_path):
        return self.file_limit_ok

    def is_protected_file(self, file_path):
        return self.protected

    def register_patch(self, patch):
        self.registered.append(patch)
        if patch and patch.id:
            self.patches[patch.id] = patch

    async def _save_state_async(self):
        self.save_state_calls += 1

    async def apply_patch(self, patch_id):
        return dict(self.apply_result)

    async def rollback_patch(self, patch_id):
        return dict(self.rollback_result)

    async def reject_patch(self, patch_id):
        return dict(self.reject_result)

    def get_pending_patches(self):
        return list(self.pending)

    def get_all_patches(self, limit=50):
        return list(self.all_patches)

    def get_patch_detail(self, patch_id):
        return self.detail


class _StubReportGenerator:
    """报告生成器替身。"""

    def __init__(self):
        self.reports = []
        self.saved = []
        self.brief = "morning-brief"
        self.kanban = {"columns": {}}
        self.listed = [{"id": "r1"}]
        self.detail = "# detail"

    async def save_report(self, report):
        self.saved.append(report)
        self.reports.append(report)

    def get_morning_brief(self, stats):
        return self.brief

    def get_kanban(self, patches, stats):
        return self.kanban

    def get_reports(self, limit=20, report_type=None):
        return list(self.listed)

    def get_report_detail(self, report_id):
        return self.detail


class _StubEventBus:
    def __init__(self, raise_exc=None):
        self.events = []
        self.raise_exc = raise_exc

    async def publish(self, event_name, **kwargs):
        if self.raise_exc is not None:
            raise self.raise_exc
        self.events.append((event_name, kwargs))
        return {"ok": True}


class _StubWebSocketManager:
    def __init__(self, raise_exc=None):
        self.payloads = []
        self.raise_exc = raise_exc

    async def broadcast(self, payload):
        if self.raise_exc is not None:
            raise self.raise_exc
        self.payloads.append(payload)


class _StubWorkspaceService:
    def __init__(self, raise_exc=None):
        self.memories = []
        self.raise_exc = raise_exc

    async def _append_workspace_memory(self, content, category, topics, metadata):
        if self.raise_exc is not None:
            raise self.raise_exc
        self.memories.append(
            {
                "content": content,
                "category": category,
                "topics": topics,
                "metadata": metadata,
            }
        )


class _FakeLogger:
    """容忍任意 kwargs 的日志替身。

    被测源码若干 debug 分支调用了 ``logger.info(msg, key=value, exc_info=True)``，
    而标准库 ``logging.Logger`` 不接受额外关键字参数。这里用替身承接这些调用，
    以便确定性地覆盖对应分支（该缺陷本身单独在报告中说明，不在测试中断言）。
    """

    def __init__(self):
        self.records = []

    def _record(self, level, msg, *args, **kwargs):
        self.records.append((level, msg, args, kwargs))

    def debug(self, msg, *args, **kwargs):
        self._record("debug", msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._record("info", msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._record("warning", msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._record("error", msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self._record("critical", msg, *args, **kwargs)


class _StubHealthChecker:
    def __init__(self):
        self.registered = {}

    def register_health_checker(self, service_name, checker_func, interval=30.0):
        self.registered[service_name] = (checker_func, interval)


class _StubSelfImprovement:
    def __init__(self, raise_exc=None):
        self.errors = []
        self.raise_exc = raise_exc

    async def log_error(self, **kwargs):
        if self.raise_exc is not None:
            raise self.raise_exc
        self.errors.append(kwargs)


# --------------------------------------------------------------------------- #
# 构造辅助
# --------------------------------------------------------------------------- #
def _make_service():
    """构造一个所有下游协作者均已替换为替身的服务实例。"""
    svc = AutoHealService()
    detector = _StubDetector()
    analyzer = _StubAnalyzer()
    generator = _StubGenerator()
    sandbox = _StubSandbox()
    patch_manager = _StubPatchManager()
    report_generator = _StubReportGenerator()

    svc._detector = detector
    svc._analyzer = analyzer
    svc._generator = generator
    svc._sandbox = sandbox
    svc._patch_manager = patch_manager
    svc._report_generator = report_generator
    return svc


def _make_anomaly(
    severity=AnomalySeverity.MEDIUM,
    auto_fixable=True,
    title="测试异常",
    anomaly_type=AnomalyType.ERROR_CLUSTER,
):
    return AnomalyEvent(
        anomaly_type=anomaly_type,
        severity=severity,
        title=title,
        auto_fixable=auto_fixable,
    )


def _make_root_cause(anomaly, file_path="core/foo.py", confidence=0.9):
    return RootCauseReport(
        anomaly=anomaly,
        file_path=file_path,
        confidence=confidence,
        analysis="根因分析",
        suggested_fix="修复建议",
    )


def _make_patch(file_path="core/foo.py", patched_code="patched", root_cause=None):
    return Patch(
        anomaly_id="anomaly-1",
        file_path=file_path,
        original_code="orig",
        patched_code=patched_code,
        diff="--- a\n+++ b",
        description="补丁描述",
        root_cause=root_cause,
    )


async def _hang():
    """永不返回的协程，用于构造可取消的后台任务。"""
    await asyncio.Event().wait()


def _patch_infrastructure(monkeypatch, event_bus=None, ws_mgr=None):
    """把 event_bus / websocket 替换为替身。"""
    bus = event_bus if event_bus is not None else _StubEventBus()
    mgr = ws_mgr if ws_mgr is not None else _StubWebSocketManager()
    monkeypatch.setattr(event_bus_module, "get_event_bus", lambda: bus)
    monkeypatch.setattr(ws_module, "get_websocket_manager", lambda: mgr)
    return bus, mgr


# --------------------------------------------------------------------------- #
# 构造 / 属性（惰性初始化）
# --------------------------------------------------------------------------- #
def test_init_default_state():
    svc = AutoHealService()
    assert svc._running is False
    assert svc._task is None
    assert svc._detector is None
    assert svc._history == []
    assert svc._check_interval == 30.0
    assert svc._auto_apply is False
    assert svc._suppress_duration == 300.0


def test_lazy_properties_construct_real_collaborators():
    """惰性属性在首次访问时应构造真实协作者并缓存。"""
    svc = AutoHealService()
    detector = svc.detector
    analyzer = svc.analyzer
    generator = svc.generator
    sandbox = svc.sandbox

    assert detector is svc.detector
    assert analyzer is svc.analyzer
    assert generator is svc.generator
    assert sandbox is svc.sandbox
    assert svc._detector is detector
    assert svc._suppress_duration == detector._suppress_duration


# --------------------------------------------------------------------------- #
# initialize
# --------------------------------------------------------------------------- #
def test_initialize_when_already_running_returns_early():
    async def _run():
        svc = _make_service()
        svc._running = True
        await svc.initialize()
        # 已在运行时直接返回，不会调度后台初始化任务
        assert not hasattr(svc, "_bg_init_task")

    asyncio.run(_run())


def test_initialize_background_flow_applies_settings(monkeypatch, tmp_path):
    async def _run():
        svc = _make_service()
        heal_settings = SimpleNamespace(
            check_interval=7.0, auto_apply=True, suppress_duration=11.0, enabled=True
        )
        monkeypatch.setattr(
            integrated_config_module,
            "get_settings",
            lambda: SimpleNamespace(auto_heal=heal_settings),
        )
        monkeypatch.setattr(
            log_sanitizer_module, "register_error_callback", lambda cb: None
        )
        checker = _StubHealthChecker()
        monkeypatch.setattr(
            async_monitor_module, "get_health_checker", lambda: checker
        )
        monkeypatch.setattr(
            shared_roots_module, "get_logs_root", lambda: tmp_path / "logs"
        )
        _patch_infrastructure(monkeypatch)

        await svc.initialize()
        assert svc._running is True
        await svc._bg_init_task

        assert svc._check_interval == 7.0
        assert svc._auto_apply is True
        assert svc._suppress_duration == 11.0
        assert svc._registered_error_callback is True
        assert svc._registered_health_checker is True
        assert "auto_heal_service" in checker.registered
        assert svc._task is not None

        svc._task.cancel()
        await asyncio.gather(svc._task, return_exceptions=True)

    asyncio.run(_run())


def test_initialize_disabled_in_settings(monkeypatch, tmp_path):
    async def _run():
        svc = _make_service()
        monkeypatch.setattr(
            integrated_config_module,
            "get_settings",
            lambda: SimpleNamespace(
                auto_heal=SimpleNamespace(
                    check_interval=30.0,
                    auto_apply=False,
                    suppress_duration=300.0,
                    enabled=False,
                )
            ),
        )
        monkeypatch.setattr(
            shared_roots_module, "get_logs_root", lambda: tmp_path / "logs"
        )
        _patch_infrastructure(monkeypatch)

        await svc.initialize()
        await svc._bg_init_task

        assert svc._running is False
        assert svc._task is None
        assert svc._registered_error_callback is False

    asyncio.run(_run())


def test_initialize_without_heal_settings(monkeypatch, tmp_path):
    """settings 缺少 auto_heal 属性时走默认值分支。"""

    async def _run():
        svc = _make_service()
        monkeypatch.setattr(
            integrated_config_module, "get_settings", lambda: SimpleNamespace()
        )
        monkeypatch.setattr(
            log_sanitizer_module, "register_error_callback", lambda cb: None
        )
        monkeypatch.setattr(
            async_monitor_module,
            "get_health_checker",
            lambda: _StubHealthChecker(),
        )
        monkeypatch.setattr(
            shared_roots_module, "get_logs_root", lambda: tmp_path / "logs"
        )
        _patch_infrastructure(monkeypatch)

        await svc.initialize()
        await svc._bg_init_task

        assert svc._check_interval == 30.0
        assert svc._auto_apply is False
        svc._task.cancel()
        await asyncio.gather(svc._task, return_exceptions=True)

    asyncio.run(_run())


def test_initialize_settings_read_failure_degrades(monkeypatch, tmp_path):
    """读取配置抛异常时应降级为默认值并继续初始化。"""

    async def _run():
        svc = _make_service()
        monkeypatch.setattr(heal_service, "is_debug_enabled", lambda *a, **k: True)

        def _boom():
            raise RuntimeError("config boom")

        monkeypatch.setattr(integrated_config_module, "get_settings", _boom)
        monkeypatch.setattr(
            log_sanitizer_module, "register_error_callback", lambda cb: None
        )
        monkeypatch.setattr(
            async_monitor_module,
            "get_health_checker",
            lambda: _StubHealthChecker(),
        )
        monkeypatch.setattr(
            shared_roots_module, "get_logs_root", lambda: tmp_path / "logs"
        )
        _patch_infrastructure(monkeypatch)

        await svc.initialize()
        await svc._bg_init_task

        assert svc._running is True
        assert svc._check_interval == 30.0
        assert svc._registered_error_callback is True
        svc._task.cancel()
        await asyncio.gather(svc._task, return_exceptions=True)

    asyncio.run(_run())


def test_initialize_reuses_existing_callback_and_checker_registration(
    monkeypatch, tmp_path
):
    """已注册过回调/健康检查时不应重复注册。"""

    async def _run():
        svc = _make_service()
        svc._registered_error_callback = True
        svc._registered_health_checker = True
        monkeypatch.setattr(
            integrated_config_module, "get_settings", lambda: SimpleNamespace()
        )
        register_calls = []

        def _register(cb):
            register_calls.append(cb)

        monkeypatch.setattr(
            log_sanitizer_module, "register_error_callback", _register
        )
        monkeypatch.setattr(
            shared_roots_module, "get_logs_root", lambda: tmp_path / "logs"
        )
        _patch_infrastructure(monkeypatch)

        await svc.initialize()
        await svc._bg_init_task

        assert register_calls == []
        svc._task.cancel()
        await asyncio.gather(svc._task, return_exceptions=True)

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# shutdown
# --------------------------------------------------------------------------- #
def test_shutdown_when_not_running_returns_early():
    async def _run():
        svc = _make_service()
        svc._running = False
        await svc.shutdown()
        assert svc._running is False

    asyncio.run(_run())


def test_shutdown_cancels_task_and_unregisters(monkeypatch, tmp_path):
    async def _run():
        svc = _make_service()
        svc._running = True
        svc._task = asyncio.create_task(_hang())
        svc._registered_error_callback = True
        unregistered = []
        monkeypatch.setattr(
            log_sanitizer_module,
            "unregister_error_callback",
            lambda cb: unregistered.append(cb),
        )
        monkeypatch.setattr(
            shared_roots_module, "get_logs_root", lambda: tmp_path / "logs"
        )
        _patch_infrastructure(monkeypatch)

        await svc.shutdown()

        assert svc._running is False
        assert svc._task is None
        assert svc._registered_error_callback is False
        assert len(unregistered) == 1

    asyncio.run(_run())


def test_shutdown_unregister_failure_is_swallowed(monkeypatch, tmp_path):
    async def _run():
        svc = _make_service()
        svc._running = True
        svc._registered_error_callback = True
        monkeypatch.setattr(heal_service, "is_debug_enabled", lambda *a, **k: True)

        def _boom(cb):
            raise RuntimeError("unregister boom")

        monkeypatch.setattr(log_sanitizer_module, "unregister_error_callback", _boom)
        monkeypatch.setattr(
            shared_roots_module, "get_logs_root", lambda: tmp_path / "logs"
        )
        _patch_infrastructure(monkeypatch)

        await svc.shutdown()
        assert svc._running is False
        assert svc._registered_error_callback is False

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# _on_error_report
# --------------------------------------------------------------------------- #
def test_on_error_report_forwards_to_detector():
    svc = _make_service()
    svc._on_error_report("err-1", {"message": "boom"})
    assert svc._detector.received_errors == [("err-1", {"message": "boom"})]


def test_on_error_report_swallows_detector_failure(monkeypatch):
    svc = _make_service()
    svc._detector.raise_on_error = RuntimeError("detector boom")
    monkeypatch.setattr(heal_service, "is_debug_enabled", lambda *a, **k: True)
    fake_logger = _FakeLogger()
    monkeypatch.setattr(heal_service, "logger", fake_logger)
    # 不应抛出
    svc._on_error_report("err-2", {})
    assert svc._detector.received_errors == []
    assert any(rec[0] == "info" for rec in fake_logger.records)


# --------------------------------------------------------------------------- #
# _loop
# --------------------------------------------------------------------------- #
def test_loop_runs_once_then_stops(monkeypatch):
    async def _run():
        svc = _make_service()
        svc._running = True
        svc._check_interval = 30.0

        async def _fake_sleep(_seconds):
            svc._running = False

        monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
        await svc._loop()
        assert svc._detector.flush_calls == 1
        assert svc._last_check_ts > 0

    asyncio.run(_run())


def test_loop_breaks_on_cancelled_error(monkeypatch):
    async def _run():
        svc = _make_service()
        svc._running = True
        svc._detector.raise_on_check = asyncio.CancelledError()
        # CancelledError 分支会直接 break，不会走到 asyncio.sleep
        await svc._loop()
        assert svc._running is True  # break 而非置 False

    asyncio.run(_run())


def test_loop_swallows_generic_exception(monkeypatch):
    async def _run():
        svc = _make_service()
        svc._running = True
        svc._detector.raise_on_check = RuntimeError("check boom")

        async def _fake_sleep(_seconds):
            svc._running = False

        monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
        await svc._loop()
        assert svc._detector.flush_calls == 0

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# _check_and_heal
# --------------------------------------------------------------------------- #
def test_check_and_heal_without_anomalies(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        await svc._check_and_heal()
        assert svc._last_check_ts > 0
        assert svc._detector.flush_calls == 1
        assert svc._skip_count == 0

    asyncio.run(_run())


def test_check_and_heal_routes_by_severity(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        svc._detector.anomalies = [
            _make_anomaly(AnomalySeverity.HIGH, auto_fixable=False, title="high"),
            _make_anomaly(AnomalySeverity.CRITICAL, auto_fixable=False, title="crit"),
            _make_anomaly(AnomalySeverity.MEDIUM, auto_fixable=True, title="fixable"),
            _make_anomaly(AnomalySeverity.LOW, auto_fixable=False, title="skip"),
        ]
        # analyzer 返回 None → _process_anomaly 走 no_root_cause 后返回
        svc._analyzer.result = None

        await svc._check_and_heal()

        assert svc._skip_count == 1
        assert svc._last_anomaly_ts > 0
        # HIGH / CRITICAL / auto_fixable 共 3 条进入处理
        assert len(svc._analyzer.calls) == 3
        assert svc._history[-1]["action"] == "no_root_cause"

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# _process_anomaly 各分支
# --------------------------------------------------------------------------- #
def test_process_anomaly_daily_limit_reached(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        svc._patch_manager.daily_limit_ok = False
        anomaly = _make_anomaly()
        await svc._process_anomaly(anomaly)
        assert svc._history[-1]["action"] == "daily_limit_reached"
        assert svc._history[-1]["anomaly_id"] == anomaly.id

    asyncio.run(_run())


def test_process_anomaly_no_root_cause(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        svc._analyzer.result = None
        await svc._process_anomaly(_make_anomaly())
        assert svc._history[-1]["action"] == "no_root_cause"

    asyncio.run(_run())


def test_process_anomaly_low_confidence(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        anomaly = _make_anomaly()
        svc._analyzer.result = _make_root_cause(anomaly, confidence=0.1)
        await svc._process_anomaly(anomaly)
        assert svc._history[-1]["action"] == "low_confidence"
        assert svc._history[-1]["confidence"] == 0.1

    asyncio.run(_run())


def test_process_anomaly_no_file_path(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        anomaly = _make_anomaly()
        svc._analyzer.result = _make_root_cause(anomaly, file_path="", confidence=0.9)
        await svc._process_anomaly(anomaly)
        assert svc._history[-1]["action"] == "no_file_path"

    asyncio.run(_run())


def test_process_anomaly_protected_file_generates_suggestion(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        anomaly = _make_anomaly()
        svc._analyzer.result = _make_root_cause(
            anomaly, file_path="core/utils/logger.py"
        )
        svc._patch_manager.protected = True

        await svc._process_anomaly(anomaly)

        assert svc._history[-1]["action"] == "protected_file_suggestion"
        saved = svc._report_generator.saved
        assert len(saved) == 1
        assert saved[0].is_protected is True

    asyncio.run(_run())


def test_process_anomaly_file_limit_reached(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        anomaly = _make_anomaly()
        svc._analyzer.result = _make_root_cause(anomaly)
        svc._patch_manager.file_limit_ok = False
        await svc._process_anomaly(anomaly)
        assert svc._history[-1]["action"] == "file_limit_reached"

    asyncio.run(_run())


def test_process_anomaly_patch_generation_failed(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        anomaly = _make_anomaly()
        svc._analyzer.result = _make_root_cause(anomaly)
        svc._generator.patch = None
        await svc._process_anomaly(anomaly)
        assert svc._history[-1]["action"] == "patch_generation_failed"

    asyncio.run(_run())


def test_process_anomaly_patch_too_large(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        anomaly = _make_anomaly()
        svc._analyzer.result = _make_root_cause(anomaly)
        svc._generator.patch = _make_patch(
            patched_code="a" * (512 * 1024 + 1)
        )
        await svc._process_anomaly(anomaly)
        assert svc._history[-1]["action"] == "patch_too_large"

    asyncio.run(_run())


def test_process_anomaly_verification_failed(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        anomaly = _make_anomaly()
        svc._analyzer.result = _make_root_cause(anomaly)
        svc._generator.patch = _make_patch()
        svc._sandbox.verification = {"overall_ok": False, "errors": ["syntax"]}

        await svc._process_anomaly(anomaly)

        assert svc._history[-1]["action"] == "verification_failed"
        assert svc._generator.patch.status == PatchStatus.FAILED
        assert svc._patch_manager.save_state_calls >= 1

    asyncio.run(_run())


def test_process_anomaly_success_notifies_patch_ready(monkeypatch):
    async def _run():
        svc = _make_service()
        bus, mgr = _patch_infrastructure(monkeypatch)
        ws_service = _StubWorkspaceService()
        monkeypatch.setattr(
            ws_service_module, "get_workspace_service", lambda: ws_service
        )
        anomaly = _make_anomaly(AnomalySeverity.LOW)
        root_cause = _make_root_cause(anomaly)
        svc._analyzer.result = root_cause
        svc._generator.patch = _make_patch(root_cause=root_cause)
        svc._auto_apply = False

        await svc._process_anomaly(anomaly)

        saved = svc._report_generator.saved
        assert len(saved) == 1
        assert saved[0].patch_status == PatchStatus.AWAITING_APPROVAL.value
        assert any(ev[0] == "auto_heal.patch_ready" for ev in bus.events)
        assert len(ws_service.memories) == 1

    asyncio.run(_run())


def test_process_anomaly_auto_apply_allowed(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        monkeypatch.setattr(
            ws_service_module,
            "get_workspace_service",
            lambda: _StubWorkspaceService(),
        )
        si = _StubSelfImprovement()
        monkeypatch.setattr(
            si_module, "get_self_improvement_service", lambda scope=None: si
        )
        anomaly = _make_anomaly(AnomalySeverity.LOW)
        root_cause = _make_root_cause(anomaly, file_path="core/foo.py")
        svc._analyzer.result = root_cause
        svc._generator.patch = _make_patch(
            file_path="core/foo.py", root_cause=root_cause
        )
        svc._auto_apply = True
        svc._patch_manager.apply_result = {"success": True, "message": "ok"}

        await svc._process_anomaly(anomaly)

        # apply_patch 成功 → 记录 patch_applied 并通知自我改进系统
        actions = [e["action"] for e in svc._history]
        assert "patch_applied" in actions
        assert len(si.errors) == 1

    asyncio.run(_run())


def test_process_anomaly_auto_apply_blocked_falls_back(monkeypatch):
    async def _run():
        svc = _make_service()
        bus, _ = _patch_infrastructure(monkeypatch)
        monkeypatch.setattr(
            ws_service_module,
            "get_workspace_service",
            lambda: _StubWorkspaceService(),
        )
        # HIGH 严重程度不允许 auto_apply
        anomaly = _make_anomaly(AnomalySeverity.HIGH)
        root_cause = _make_root_cause(anomaly)
        svc._analyzer.result = root_cause
        svc._generator.patch = _make_patch(root_cause=root_cause)
        svc._auto_apply = True

        await svc._process_anomaly(anomaly)

        assert any(ev[0] == "auto_heal.patch_ready" for ev in bus.events)
        assert "patch_applied" not in [e["action"] for e in svc._history]

    asyncio.run(_run())


def test_process_anomaly_records_processing_error(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        svc._analyzer.raise_exc = RuntimeError("analyze boom")
        await svc._process_anomaly(_make_anomaly())
        assert svc._history[-1]["action"] == "processing_error"
        assert svc._history[-1]["error"] == "analyze boom"

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# apply_patch / rollback_patch / reject_patch
# --------------------------------------------------------------------------- #
def test_apply_patch_success_with_root_cause(monkeypatch):
    async def _run():
        svc = _make_service()
        bus, _ = _patch_infrastructure(monkeypatch)
        si = _StubSelfImprovement()
        monkeypatch.setattr(
            si_module, "get_self_improvement_service", lambda scope=None: si
        )
        anomaly = _make_anomaly()
        root_cause = _make_root_cause(anomaly)
        patch = _make_patch(root_cause=root_cause)
        svc._patch_manager.patches[patch.id] = patch
        svc._patch_manager.apply_result = {"success": True, "message": "ok"}

        result = await svc.apply_patch(patch.id)

        assert result["success"] is True
        assert svc._history[-1]["action"] == "patch_applied"
        assert svc._report_generator.saved[-1].patch_id == patch.id
        assert any(ev[0] == "auto_heal.patch_applied" for ev in bus.events)
        assert len(si.errors) == 1

    asyncio.run(_run())


def test_apply_patch_success_without_root_cause(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        monkeypatch.setattr(
            si_module,
            "get_self_improvement_service",
            lambda scope=None: _StubSelfImprovement(),
        )
        patch = _make_patch(root_cause=None)
        svc._patch_manager.patches[patch.id] = patch
        svc._patch_manager.apply_result = {"success": True, "message": "ok"}

        result = await svc.apply_patch(patch.id)

        assert result["success"] is True
        report = svc._report_generator.saved[-1]
        assert report.anomaly_title == ""
        assert report.confidence == 0.0

    asyncio.run(_run())


def test_apply_patch_success_but_patch_missing(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        svc._patch_manager.apply_result = {"success": True, "message": "ok"}
        result = await svc.apply_patch("not-exist")
        assert result["success"] is True
        assert svc._report_generator.saved == []

    asyncio.run(_run())


def test_apply_patch_self_improvement_failure_is_swallowed(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        patch = _make_patch(root_cause=_make_root_cause(_make_anomaly()))
        svc._patch_manager.patches[patch.id] = patch
        svc._patch_manager.apply_result = {"success": True, "message": "ok"}

        def _boom(scope=None):
            raise RuntimeError("si boom")

        monkeypatch.setattr(si_module, "get_self_improvement_service", _boom)
        result = await svc.apply_patch(patch.id)
        # 自我改进系统失败不影响主流程
        assert result["success"] is True
        assert svc._history[-1]["action"] == "patch_applied"

    asyncio.run(_run())


def test_apply_patch_failure_does_not_record(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        svc._patch_manager.apply_result = {"success": False, "message": "no"}
        result = await svc.apply_patch("p1")
        assert result["success"] is False
        assert svc._history == []

    asyncio.run(_run())


def test_rollback_patch_success_and_missing(monkeypatch):
    async def _run():
        svc = _make_service()
        bus, _ = _patch_infrastructure(monkeypatch)
        patch = _make_patch(root_cause=_make_root_cause(_make_anomaly()))
        svc._patch_manager.patches[patch.id] = patch
        svc._patch_manager.rollback_result = {"success": True}

        result = await svc.rollback_patch(patch.id)
        assert result["success"] is True
        assert svc._history[-1]["action"] == "patch_rolled_back"
        assert any(ev[0] == "auto_heal.patch_rolled_back" for ev in bus.events)

        # success 但补丁不在内存中 → 只返回结果
        result2 = await svc.rollback_patch("ghost")
        assert result2["success"] is True

        # 失败分支
        svc._patch_manager.rollback_result = {"success": False}
        result3 = await svc.rollback_patch(patch.id)
        assert result3["success"] is False

    asyncio.run(_run())


def test_reject_patch_success_and_missing(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        patch = _make_patch(root_cause=_make_root_cause(_make_anomaly()))
        svc._patch_manager.patches[patch.id] = patch
        svc._patch_manager.reject_result = {"success": True}

        result = await svc.reject_patch(patch.id)
        assert result["success"] is True
        assert svc._history[-1]["action"] == "patch_rejected"

        # success 但补丁不在内存中
        assert (await svc.reject_patch("ghost"))["success"] is True

        # 失败分支
        svc._patch_manager.reject_result = {"success": False}
        assert (await svc.reject_patch(patch.id))["success"] is False

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# 委托方法 / 统计 / 看板
# --------------------------------------------------------------------------- #
def test_delegation_methods():
    svc = _make_service()
    assert svc.get_pending_patches() == [{"id": "p1"}]
    assert svc.get_all_patches() == [{"id": "p1"}, {"id": "p2"}]
    assert svc.get_patch_detail("p1") == {"id": "p1", "diff": "d"}


def test_get_stats_aggregates_patch_status():
    svc = _make_service()
    p1 = _make_patch()
    p1.status = PatchStatus.AWAITING_APPROVAL
    p2 = _make_patch()
    p2.status = PatchStatus.APPLIED
    p3 = _make_patch()
    p3.status = PatchStatus.APPLIED
    svc._patch_manager.patches = {p1.id: p1, p2.id: p2, p3.id: p3}
    svc._patch_manager.heal_count = 5
    svc._patch_manager.daily_patch_count = 2
    svc._detector.error_stats = {"errors_last_5m": 3}
    svc._running = True

    stats = svc.get_stats()

    assert stats["running"] is True
    assert stats["heal_count"] == 5
    assert stats["daily_patch_count"] == 2
    assert stats["patches_total"] == 3
    assert stats["patches_by_status"] == {"awaiting_approval": 1, "applied": 2}
    assert stats["pending_patches_count"] == 1
    assert stats["error_stats"] == {"errors_last_5m": 3}


def test_get_morning_brief_and_kanban_and_reports():
    svc = _make_service()
    assert svc.get_morning_brief() == "morning-brief"
    assert svc.get_kanban() == {"columns": {}}
    assert svc.get_reports(limit=5) == [{"id": "r1"}]
    assert svc.get_report_detail("r1") == "# detail"


# --------------------------------------------------------------------------- #
# trigger_check
# --------------------------------------------------------------------------- #
def test_trigger_check_returns_anomaly_summaries(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        svc._detector.anomalies = [
            _make_anomaly(AnomalySeverity.HIGH, title="a1"),
            _make_anomaly(AnomalySeverity.LOW, auto_fixable=False, title="a2"),
        ]
        svc._analyzer.result = None

        results = await svc.trigger_check(persona_context="persona-x")

        assert len(results) == 2
        assert results[0]["severity"] == AnomalySeverity.HIGH.value
        assert results[1]["auto_fixable"] is False
        # persona_context 应透传给分析器
        assert all(call[1] == "persona-x" for call in svc._analyzer.calls)

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# _can_auto_apply
# --------------------------------------------------------------------------- #
def test_can_auto_apply_severity_not_allowed():
    svc = _make_service()
    patch = _make_patch(file_path="core/foo.py")
    assert svc._can_auto_apply(_make_anomaly(AnomalySeverity.HIGH), patch) is False
    assert (
        svc._can_auto_apply(_make_anomaly(AnomalySeverity.CRITICAL), patch) is False
    )


def test_can_auto_apply_blocked_prefix_startswith():
    svc = _make_service()
    patch = _make_patch(file_path="config/settings.py")
    assert svc._can_auto_apply(_make_anomaly(AnomalySeverity.LOW), patch) is False


def test_can_auto_apply_blocked_prefix_embedded_and_windows_sep():
    svc = _make_service()
    patch = _make_patch(file_path="sub\\config\\x.py")
    # 反斜杠归一化后包含 "/config/" → 命中黑名单
    assert svc._can_auto_apply(_make_anomaly(AnomalySeverity.LOW), patch) is False


def test_can_auto_apply_protected_by_patch_manager():
    svc = _make_service()
    svc._patch_manager.protected = True
    patch = _make_patch(file_path="core/foo.py")
    assert svc._can_auto_apply(_make_anomaly(AnomalySeverity.LOW), patch) is False


def test_can_auto_apply_allowed():
    svc = _make_service()
    patch = _make_patch(file_path="core/foo.py")
    assert svc._can_auto_apply(_make_anomaly(AnomalySeverity.LOW), patch) is True
    assert svc._can_auto_apply(_make_anomaly(AnomalySeverity.MEDIUM), patch) is True


# --------------------------------------------------------------------------- #
# _notify_patch_ready
# --------------------------------------------------------------------------- #
def test_notify_patch_ready_writes_workspace_memory(monkeypatch):
    async def _run():
        svc = _make_service()
        bus, _ = _patch_infrastructure(monkeypatch)
        ws_service = _StubWorkspaceService()
        monkeypatch.setattr(
            ws_service_module, "get_workspace_service", lambda: ws_service
        )
        patch = _make_patch()
        await svc._notify_patch_ready(patch)

        assert any(ev[0] == "auto_heal.patch_ready" for ev in bus.events)
        assert ws_service.memories[0]["category"] == "auto_heal"
        assert ws_service.memories[0]["metadata"]["patch_id"] == patch.id

    asyncio.run(_run())


def test_notify_patch_ready_swallows_workspace_failure(monkeypatch):
    async def _run():
        svc = _make_service()
        _patch_infrastructure(monkeypatch)
        monkeypatch.setattr(heal_service, "is_debug_enabled", lambda *a, **k: True)
        monkeypatch.setattr(
            ws_service_module,
            "get_workspace_service",
            lambda: _StubWorkspaceService(raise_exc=RuntimeError("ws boom")),
        )
        # 不应抛出
        await svc._notify_patch_ready(_make_patch())

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# _record_history
# --------------------------------------------------------------------------- #
def test_record_history_optional_fields():
    svc = _make_service()
    anomaly = _make_anomaly()
    root_cause = _make_root_cause(anomaly)
    patch = _make_patch()
    svc._record_history(anomaly, "with_all", root_cause, patch, error="e")
    entry = svc._history[-1]
    assert entry["action"] == "with_all"
    assert entry["error"] == "e"
    assert entry["file_path"] == "core/foo.py"
    assert entry["patch_id"] == patch.id
    assert svc._history_dirty is True

    # 全部可选参数为 None 时只写基础字段
    svc._record_history(None, "minimal")
    minimal = svc._history[-1]
    assert "anomaly_id" not in minimal
    assert "file_path" not in minimal


def test_record_history_trims_to_max_entries():
    svc = _make_service()
    for i in range(heal_service._MAX_HISTORY_ENTRIES + 5):
        svc._record_history(_make_anomaly(title=f"t{i}"), "spam")
    assert len(svc._history) == heal_service._MAX_HISTORY_ENTRIES


# --------------------------------------------------------------------------- #
# _load_history
# --------------------------------------------------------------------------- #
def test_load_history_reads_valid_entries_and_skips_bad_lines(monkeypatch, tmp_path):
    async def _run():
        svc = _make_service()
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        history_file = log_dir / heal_service._HEAL_HISTORY_FILE
        history_file.write_text(
            '{"action": "a1"}\n\n{bad json}\n{"action": "a2"}\n', encoding="utf-8"
        )
        monkeypatch.setattr(heal_service, "is_debug_enabled", lambda *a, **k: True)
        monkeypatch.setattr(heal_service, "logger", _FakeLogger())
        monkeypatch.setattr(
            shared_roots_module, "get_logs_root", lambda: tmp_path / "logs"
        )

        await svc._load_history()

        assert [e["action"] for e in svc._history] == ["a1", "a2"]

    asyncio.run(_run())


def test_load_history_returns_when_file_missing(monkeypatch, tmp_path):
    async def _run():
        svc = _make_service()
        monkeypatch.setattr(
            shared_roots_module, "get_logs_root", lambda: tmp_path / "logs"
        )
        await svc._load_history()
        assert svc._history == []

    asyncio.run(_run())


def test_load_history_root_lookup_failure(monkeypatch):
    async def _run():
        svc = _make_service()
        monkeypatch.setattr(heal_service, "is_debug_enabled", lambda *a, **k: True)

        def _boom():
            raise RuntimeError("root boom")

        monkeypatch.setattr(shared_roots_module, "get_logs_root", _boom)
        await svc._load_history()
        assert svc._history == []

    asyncio.run(_run())


def test_load_history_read_failure_resets_history(monkeypatch, tmp_path):
    """历史路径存在但不是文件（目录）时，读取失败应回退为空列表。"""

    async def _run():
        svc = _make_service()
        svc._history = [{"action": "stale"}]
        log_dir = tmp_path / "logs"
        # 故意把历史文件建成目录，触发 _read 的 IO 异常
        (log_dir / heal_service._HEAL_HISTORY_FILE).mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(
            shared_roots_module, "get_logs_root", lambda: tmp_path / "logs"
        )
        await svc._load_history()
        assert svc._history == []

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# _save_history
# --------------------------------------------------------------------------- #
def test_save_history_skips_when_not_dirty(monkeypatch, tmp_path):
    async def _run():
        svc = _make_service()
        monkeypatch.setattr(
            shared_roots_module, "get_logs_root", lambda: tmp_path / "logs"
        )
        await svc._save_history()
        assert not (tmp_path / "logs" / heal_service._HEAL_HISTORY_FILE).exists()

    asyncio.run(_run())


def test_save_history_writes_file(monkeypatch, tmp_path):
    async def _run():
        svc = _make_service()
        svc._record_history(_make_anomaly(), "persist")
        monkeypatch.setattr(
            shared_roots_module, "get_logs_root", lambda: tmp_path / "logs"
        )
        await svc._save_history()

        path = tmp_path / "logs" / heal_service._HEAL_HISTORY_FILE
        assert path.exists()
        assert '"action": "persist"' in path.read_text(encoding="utf-8")
        assert svc._history_dirty is False

    asyncio.run(_run())


def test_save_history_root_lookup_failure(monkeypatch):
    async def _run():
        svc = _make_service()
        svc._history_dirty = True
        monkeypatch.setattr(heal_service, "is_debug_enabled", lambda *a, **k: True)

        def _boom():
            raise RuntimeError("root boom")

        monkeypatch.setattr(shared_roots_module, "get_logs_root", _boom)
        await svc._save_history()
        assert svc._history_dirty is True

    asyncio.run(_run())


def test_save_history_write_failure_is_swallowed(monkeypatch, tmp_path):
    async def _run():
        svc = _make_service()
        svc._record_history(_make_anomaly(), "persist")
        # 把历史文件建成目录，写入时触发 IO 异常
        (tmp_path / "logs" / heal_service._HEAL_HISTORY_FILE).mkdir(
            parents=True, exist_ok=True
        )
        monkeypatch.setattr(
            shared_roots_module, "get_logs_root", lambda: tmp_path / "logs"
        )
        await svc._save_history()
        assert svc._history_dirty is True

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# _publish_event
# --------------------------------------------------------------------------- #
def test_publish_event_success(monkeypatch):
    async def _run():
        svc = _make_service()
        bus, mgr = _patch_infrastructure(monkeypatch)
        await svc._publish_event("evt", k=1)
        assert bus.events == [("evt", {"k": 1})]
        assert mgr.payloads[0]["event"] == "evt"
        assert mgr.payloads[0]["k"] == 1

    asyncio.run(_run())


def test_publish_event_event_bus_failure(monkeypatch):
    async def _run():
        svc = _make_service()
        monkeypatch.setattr(heal_service, "is_debug_enabled", lambda *a, **k: True)
        monkeypatch.setattr(heal_service, "logger", _FakeLogger())
        bus = _StubEventBus(raise_exc=RuntimeError("bus boom"))
        _, mgr = _patch_infrastructure(monkeypatch, event_bus=bus)
        await svc._publish_event("evt")
        # event_bus 失败后仍应尝试 websocket 广播
        assert len(mgr.payloads) == 1

    asyncio.run(_run())


def test_publish_event_websocket_failure(monkeypatch):
    async def _run():
        svc = _make_service()
        monkeypatch.setattr(heal_service, "is_debug_enabled", lambda *a, **k: True)
        monkeypatch.setattr(heal_service, "logger", _FakeLogger())
        mgr = _StubWebSocketManager(raise_exc=RuntimeError("ws boom"))
        bus, _ = _patch_infrastructure(monkeypatch, ws_mgr=mgr)
        # 不应抛出
        await svc._publish_event("evt")
        assert len(bus.events) == 1

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# _register_health_checker
# --------------------------------------------------------------------------- #
def test_register_health_checker_registers_callable(monkeypatch):
    svc = _make_service()
    checker = _StubHealthChecker()
    monkeypatch.setattr(async_monitor_module, "get_health_checker", lambda: checker)
    svc._running = True

    svc._register_health_checker()

    assert svc._registered_health_checker is True
    func, interval = checker.registered["auto_heal_service"]
    assert interval == 30.0
    details = func()
    assert details["status"] == "healthy"
    assert details["running"] is True

    # 停止状态下 status 变为 stopped
    svc._running = False
    assert func()["status"] == "stopped"


def test_register_health_checker_failure_is_swallowed(monkeypatch):
    svc = _make_service()
    monkeypatch.setattr(heal_service, "is_debug_enabled", lambda *a, **k: True)

    def _boom():
        raise RuntimeError("checker boom")

    monkeypatch.setattr(async_monitor_module, "get_health_checker", _boom)
    svc._register_health_checker()
    assert svc._registered_health_checker is False


# --------------------------------------------------------------------------- #
# 模块级单例与入口函数
# --------------------------------------------------------------------------- #
def test_get_auto_heal_service_is_singleton(monkeypatch):
    monkeypatch.setattr(heal_service, "_auto_heal_instance", None)
    first = heal_service.get_auto_heal_service()
    second = heal_service.get_auto_heal_service()
    assert first is second
    assert isinstance(first, AutoHealService)


def test_initialize_auto_heal_delegates(monkeypatch):
    async def _run():
        stub = _make_service()
        calls = []
        stub.initialize = lambda: calls.append("init") or _completed()
        monkeypatch.setattr(heal_service, "_auto_heal_instance", stub)
        await heal_service.initialize_auto_heal()
        assert calls == ["init"]

    asyncio.run(_run())


def test_shutdown_auto_heal_clears_instance(monkeypatch):
    async def _run():
        stub = _make_service()
        calls = []

        async def _shutdown():
            calls.append("shutdown")

        stub.shutdown = _shutdown
        monkeypatch.setattr(heal_service, "_auto_heal_instance", stub)
        await heal_service.shutdown_auto_heal()
        assert calls == ["shutdown"]
        assert heal_service._auto_heal_instance is None

    asyncio.run(_run())


def test_shutdown_auto_heal_noop_when_instance_missing(monkeypatch):
    async def _run():
        monkeypatch.setattr(heal_service, "_auto_heal_instance", None)
        await heal_service.shutdown_auto_heal()
        assert heal_service._auto_heal_instance is None

    asyncio.run(_run())


async def _completed():
    """返回一个已完成的协程对象（用于替换 initialize 的轻量替身）。"""
    return None
