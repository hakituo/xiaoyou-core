import asyncio
import time


class _DummyImmune:
    enabled = True
    interval = 0.01
    restart_window_seconds = 60
    max_restarts_per_window = 1
    min_restart_interval_seconds = 0.0
    memory_medium_threshold = 999.0
    memory_emergency_threshold = 999.0
    cpu_medium_threshold = 999.0
    cpu_emergency_threshold = 999.0


class _DummySettings:
    immune = _DummyImmune()


class _FakeResourceMonitor:
    def __init__(self):
        self.downgrade_calls = []
        self.cleanup_calls = []

    def perform_downgrade(self, level=None):
        self.downgrade_calls.append(level)
        return True

    def cleanup_resources(self, aggressive=False, emergency=False):
        self.cleanup_calls.append({"aggressive": aggressive, "emergency": emergency})
        return None


class _FakePerformanceMonitor:
    def __init__(self, cpu=0.0, memory=0.0):
        self._metrics = {"cpu_usage": cpu, "memory_usage": memory}

    def get_current_metrics(self):
        return self._metrics


class _FakeHealthChecker:
    def __init__(self, services_health):
        self._services_health = services_health

    async def check_all_services(self):
        return self._services_health

    def register_health_checker(self, service_name, checker_func, interval=30.0):
        return None


class _FakeLifecycle:
    def __init__(self, services_initialized, *, manager_initialized=True, manager_shutdown=False):
        self._services_initialized = dict(services_initialized)
        self._manager_initialized = manager_initialized
        self._manager_shutdown = manager_shutdown
        self.restart_calls = []

    def get_status(self):
        return {
            "manager_initialized": self._manager_initialized,
            "manager_shutdown": self._manager_shutdown,
            "services": {
                name: {"initialized": initialized}
                for name, initialized in self._services_initialized.items()
            }
        }

    async def restart_service(self, name):
        self.restart_calls.append(name)
        self._services_initialized[name] = True
        return True


def _make_service(monkeypatch, settings=None, lifecycle=None, health_checker=None, performance_monitor=None):
    import core.services.immune.service as immune_mod

    monkeypatch.setattr(immune_mod, "get_resource_monitor", lambda: _FakeResourceMonitor())

    svc = immune_mod.ImmuneSystemService(
        settings=settings or _DummySettings(),
        lifecycle=lifecycle or _FakeLifecycle({}),
        health_checker=health_checker or _FakeHealthChecker({}),
        performance_monitor=performance_monitor or _FakePerformanceMonitor(),
    )
    svc._refresh_thresholds()
    return svc


def test_restart_unhealthy_services_via_health_checker(monkeypatch):
    import core.services.immune.service as immune_mod

    monkeypatch.setattr(immune_mod, "get_resource_monitor", lambda: _FakeResourceMonitor())

    service = immune_mod.ImmuneSystemService(
        settings=_DummySettings(),
        lifecycle=_FakeLifecycle({"svc_a": True}),
        health_checker=_FakeHealthChecker({"svc_a": {"status": "unhealthy"}}),
        performance_monitor=_FakePerformanceMonitor(),
    )
    service._refresh_thresholds()

    asyncio.run(service._tick())
    assert service.lifecycle.restart_calls == ["svc_a"]


def test_restart_uninitialized_services_via_lifecycle(monkeypatch):
    import core.services.immune.service as immune_mod

    monkeypatch.setattr(immune_mod, "get_resource_monitor", lambda: _FakeResourceMonitor())

    lifecycle = _FakeLifecycle({"svc_b": False})
    service = immune_mod.ImmuneSystemService(
        settings=_DummySettings(),
        lifecycle=lifecycle,
        health_checker=_FakeHealthChecker({}),
        performance_monitor=_FakePerformanceMonitor(),
    )
    service._refresh_thresholds()

    asyncio.run(service._tick())
    assert lifecycle.restart_calls == ["svc_b"]


def test_self_heal_skips_until_lifecycle_initialized(monkeypatch):
    import core.services.immune.service as immune_mod

    monkeypatch.setattr(immune_mod, "get_resource_monitor", lambda: _FakeResourceMonitor())

    lifecycle = _FakeLifecycle({"active_care_service": False}, manager_initialized=False)
    service = immune_mod.ImmuneSystemService(
        settings=_DummySettings(),
        lifecycle=lifecycle,
        health_checker=_FakeHealthChecker(
            {"active_care_service": {"status": "unhealthy"}}
        ),
        performance_monitor=_FakePerformanceMonitor(),
    )
    service._refresh_thresholds()

    asyncio.run(service._tick())
    assert lifecycle.restart_calls == []


def test_self_heal_skips_during_lifecycle_shutdown(monkeypatch):
    import core.services.immune.service as immune_mod

    monkeypatch.setattr(immune_mod, "get_resource_monitor", lambda: _FakeResourceMonitor())

    lifecycle = _FakeLifecycle({"active_care_service": False}, manager_shutdown=True)
    service = immune_mod.ImmuneSystemService(
        settings=_DummySettings(),
        lifecycle=lifecycle,
        health_checker=_FakeHealthChecker(
            {"active_care_service": {"status": "unhealthy"}}
        ),
        performance_monitor=_FakePerformanceMonitor(),
    )
    service._refresh_thresholds()

    asyncio.run(service._tick())
    assert lifecycle.restart_calls == []


def test_restart_respects_max_restarts_per_window(monkeypatch):
    import core.services.immune.service as immune_mod

    monkeypatch.setattr(immune_mod, "get_resource_monitor", lambda: _FakeResourceMonitor())

    class _LocalImmune(_DummyImmune):
        max_restarts_per_window = 1

    class _LocalSettings(_DummySettings):
        immune = _LocalImmune()

    lifecycle = _FakeLifecycle({"svc_c": False})
    service = immune_mod.ImmuneSystemService(
        settings=_LocalSettings(),
        lifecycle=lifecycle,
        health_checker=_FakeHealthChecker({}),
        performance_monitor=_FakePerformanceMonitor(),
    )
    service._refresh_thresholds()

    asyncio.run(service._tick())
    lifecycle._services_initialized["svc_c"] = False
    asyncio.run(service._tick())
    assert lifecycle.restart_calls.count("svc_c") == 1


def test_stats_tracking(monkeypatch):
    service = _make_service(monkeypatch)

    stats = service.get_stats()
    assert stats["running"] is False
    assert stats["total_ticks"] == 0

    asyncio.run(service._tick())

    stats = service.get_stats()
    assert stats["total_ticks"] == 1
    assert stats["last_tick_ts"] > 0


def test_resource_emergency_triggers_downgrade(monkeypatch):
    import core.services.immune.service as immune_mod

    fake_monitor = _FakeResourceMonitor()
    monkeypatch.setattr(immune_mod, "get_resource_monitor", lambda: fake_monitor)

    class _HighMemImmune(_DummyImmune):
        memory_emergency_threshold = 50.0

    class _HighMemSettings(_DummySettings):
        immune = _HighMemImmune()

    service = immune_mod.ImmuneSystemService(
        settings=_HighMemSettings(),
        lifecycle=_FakeLifecycle({}),
        health_checker=_FakeHealthChecker({}),
        performance_monitor=_FakePerformanceMonitor(memory=80.0),
    )
    service._refresh_thresholds()

    asyncio.run(service._tick())

    assert 3 in fake_monitor.downgrade_calls
    assert any(c["emergency"] is True for c in fake_monitor.cleanup_calls)
    assert service.get_stats()["resource_emergency_count"] == 1


def test_resource_medium_triggers_downgrade(monkeypatch):
    import core.services.immune.service as immune_mod

    fake_monitor = _FakeResourceMonitor()
    monkeypatch.setattr(immune_mod, "get_resource_monitor", lambda: fake_monitor)

    class _MedMemImmune(_DummyImmune):
        memory_medium_threshold = 50.0
        memory_emergency_threshold = 999.0

    class _MedMemSettings(_DummySettings):
        immune = _MedMemImmune()

    service = immune_mod.ImmuneSystemService(
        settings=_MedMemSettings(),
        lifecycle=_FakeLifecycle({}),
        health_checker=_FakeHealthChecker({}),
        performance_monitor=_FakePerformanceMonitor(memory=60.0),
    )
    service._refresh_thresholds()

    asyncio.run(service._tick())

    assert 2 in fake_monitor.downgrade_calls
    assert any(c["aggressive"] is True for c in fake_monitor.cleanup_calls)
    assert service.get_stats()["resource_medium_count"] == 1


def test_downgrade_recovery(monkeypatch):
    import core.services.immune.service as immune_mod

    fake_monitor = _FakeResourceMonitor()
    monkeypatch.setattr(immune_mod, "get_resource_monitor", lambda: fake_monitor)

    class _MedMemImmune(_DummyImmune):
        memory_medium_threshold = 50.0
        memory_emergency_threshold = 999.0

    class _MedMemSettings(_DummySettings):
        immune = _MedMemImmune()

    service = immune_mod.ImmuneSystemService(
        settings=_MedMemSettings(),
        lifecycle=_FakeLifecycle({}),
        health_checker=_FakeHealthChecker({}),
        performance_monitor=_FakePerformanceMonitor(memory=60.0),
    )
    service._refresh_thresholds()

    asyncio.run(service._tick())
    assert service._last_downgrade_level == 2

    service.performance_monitor = _FakePerformanceMonitor(memory=30.0)
    asyncio.run(service._tick())
    assert service._last_downgrade_level == 0
    assert 0 in fake_monitor.downgrade_calls


def test_error_burst_detection(monkeypatch):
    service = _make_service(monkeypatch)

    for i in range(15):
        service._errors.append((time.time(), "ERROR", f"TestError{i}"))

    assert service._check_error_burst() is True

    service._errors.clear()
    assert service._check_error_burst() is False


def test_collect_unhealthy_services(monkeypatch):
    service = _make_service(
        monkeypatch,
        lifecycle=_FakeLifecycle({"svc_down": False}),
        health_checker=_FakeHealthChecker({"svc_sick": {"status": "unhealthy"}}),
    )

    result = asyncio.run(service._collect_unhealthy_services())
    assert "svc_down" in result
    assert "svc_sick" in result
