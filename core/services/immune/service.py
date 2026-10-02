import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional, Tuple

from config.integrated_config import get_settings
from core.utils.logger import get_logger


logger = get_logger("IMMUNE_SYSTEM")


@dataclass
class _ThresholdConfig:
    """缓存免疫系统的阈值配置，避免每次 tick 重复 getattr"""

    memory_medium: float = 90.0
    memory_emergency: float = 96.0
    cpu_medium: float = 95.0
    cpu_emergency: float = 99.0
    restart_window_s: int = 600
    max_restarts_per_window: int = 2
    min_restart_interval: float = 30.0
    interval: float = 10.0
    error_burst_window: float = 60.0
    error_burst_threshold: int = 10


@dataclass
class _ImmuneStats:
    """免疫系统运行指标，用于监控和诊断"""

    total_ticks: int = 0
    resource_emergency_count: int = 0
    resource_medium_count: int = 0
    service_restarts_attempted: int = 0
    service_restarts_success: int = 0
    service_restarts_skipped: int = 0
    error_burst_detected: int = 0
    last_tick_ts: float = 0.0


class ImmuneSystemService:
    def __init__(
        self,
        *,
        settings=None,
        lifecycle=None,
        health_checker=None,
        performance_monitor=None,
    ):
        self.settings = settings or get_settings()

        self._lifecycle = lifecycle
        self._health_checker = health_checker
        self._performance_monitor = performance_monitor

        self._running = False
        self._task: Optional[asyncio.Task] = None

        self._errors: Deque[Tuple[float, str, str]] = deque(maxlen=5000)
        self._restart_history: Dict[str, Deque[float]] = {}
        self._last_restart_ts: Dict[str, float] = {}
        self._registered_error_callback = False

        self._thresholds = _ThresholdConfig()
        self._stats = _ImmuneStats()
        self._last_downgrade_level: int = 0

    @property
    def lifecycle(self):
        if self._lifecycle is None:
            from core.core_engine.lifecycle_manager import get_lifecycle_manager
            self._lifecycle = get_lifecycle_manager()
        return self._lifecycle

    @property
    def health_checker(self):
        if self._health_checker is None:
            from core.async_monitor import get_health_checker
            self._health_checker = get_health_checker()
        return self._health_checker

    @property
    def performance_monitor(self):
        if self._performance_monitor is None:
            from core.async_monitor import get_performance_monitor
            self._performance_monitor = get_performance_monitor()
        return self._performance_monitor

    def _refresh_thresholds(self) -> _ThresholdConfig:
        """从配置刷新阈值缓存，仅在 initialize 时调用一次"""
        immune_settings = getattr(self.settings, "immune", None)
        if immune_settings is None:
            return self._thresholds

        t = self._thresholds
        t.memory_medium = float(
            getattr(immune_settings, "memory_medium_threshold", t.memory_medium)
        )
        t.memory_emergency = float(
            getattr(immune_settings, "memory_emergency_threshold", t.memory_emergency)
        )
        t.cpu_medium = float(
            getattr(immune_settings, "cpu_medium_threshold", t.cpu_medium)
        )
        t.cpu_emergency = float(
            getattr(immune_settings, "cpu_emergency_threshold", t.cpu_emergency)
        )
        t.restart_window_s = int(
            getattr(immune_settings, "restart_window_seconds", t.restart_window_s)
        )
        t.max_restarts_per_window = int(
            getattr(
                immune_settings, "max_restarts_per_window", t.max_restarts_per_window
            )
        )
        t.min_restart_interval = float(
            getattr(
                immune_settings,
                "min_restart_interval_seconds",
                t.min_restart_interval,
            )
        )
        t.interval = float(
            getattr(immune_settings, "interval", t.interval)
        )
        return t

    async def initialize(self):
        if self._running:
            return

        immune_settings = getattr(self.settings, "immune", None)
        if immune_settings is not None and not getattr(
            immune_settings, "enabled", True
        ):
            logger.info("免疫系统已禁用")
            return

        self._refresh_thresholds()
        self._running = True

        if not self._registered_error_callback:
            from core.utils.errors.log_sanitizer import register_error_callback
            register_error_callback(self._on_error_report)
            self._registered_error_callback = True

        self._register_health_checker()

        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

        logger.info("免疫系统初始化完成")

    async def shutdown(self):
        if not self._running:
            return

        self._running = False

        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

        if self._registered_error_callback:
            try:
                from core.utils.errors.log_sanitizer import unregister_error_callback
                unregister_error_callback(self._on_error_report)
            except Exception:
                pass
            self._registered_error_callback = False

        logger.info("免疫系统已关闭")

    def get_stats(self) -> Dict[str, Any]:
        """获取免疫系统运行指标"""
        return {
            "running": self._running,
            "total_ticks": self._stats.total_ticks,
            "resource_emergency_count": self._stats.resource_emergency_count,
            "resource_medium_count": self._stats.resource_medium_count,
            "service_restarts_attempted": self._stats.service_restarts_attempted,
            "service_restarts_success": self._stats.service_restarts_success,
            "service_restarts_skipped": self._stats.service_restarts_skipped,
            "error_burst_detected": self._stats.error_burst_detected,
            "last_tick_ts": self._stats.last_tick_ts,
            "recent_errors": len(self._errors),
            "current_downgrade_level": self._last_downgrade_level,
        }

    def _register_health_checker(self):
        async def _health_check():
            return {
                "status": "healthy" if self._running else "unhealthy",
                "details": self.get_stats(),
            }

        try:
            self.health_checker.register_health_checker(
                "immune_system", _health_check, interval=30.0
            )
        except Exception:
            pass

    def _on_error_report(self, error_id: str, error_report: Dict[str, Any]):
        try:
            now = time.time()
            error_type = str(error_report.get("error_type", "UnknownError"))
            severity = str(error_report.get("severity", "ERROR"))
            self._errors.append((now, severity, error_type))
        except Exception:
            pass

    def _check_error_burst(self) -> bool:
        """检测错误是否在短时间内暴增"""
        now = time.time()
        window = self._thresholds.error_burst_window
        threshold = self._thresholds.error_burst_threshold
        recent_count = sum(1 for ts, _, _ in self._errors if (now - ts) < window)
        return recent_count >= threshold

    async def _loop(self):
        interval = self._thresholds.interval

        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"免疫系统循环异常: {e}", exc_info=True)
            await asyncio.sleep(max(1.0, interval))

    async def _tick(self):
        self._stats.total_ticks += 1
        self._stats.last_tick_ts = time.time()
        await self._apply_resource_response()
        await self._apply_service_self_heal()

    async def _apply_resource_response(self):
        t = self._thresholds

        metrics = self.performance_monitor.get_current_metrics()
        cpu_usage = float(metrics.get("cpu_usage", 0.0) or 0.0)
        memory_usage = float(metrics.get("memory_usage", 0.0) or 0.0)

        monitor = None
        try:
            from core.services.monitoring.resource_monitor import get_resource_monitor
            monitor = get_resource_monitor()
        except Exception:
            pass

        is_emergency = memory_usage >= t.memory_emergency or cpu_usage >= t.cpu_emergency
        is_medium = memory_usage >= t.memory_medium or cpu_usage >= t.cpu_medium

        if is_emergency or is_medium:
            is_busy = await self._check_scheduler_busy()

            if is_emergency:
                self._stats.resource_emergency_count += 1
                # 仅在级别变化时执行降级，避免每 tick 重复调用（perform_downgrade 内部已幂等，
                # 此处提前判断减少不必要的函数调用与日志）
                if monitor and self._last_downgrade_level != 3:
                    monitor.perform_downgrade(level=3)
                self._last_downgrade_level = 3
                if not is_busy:
                    if monitor:
                        monitor.cleanup_resources(emergency=True)
                else:
                    logger.warning(
                        "资源紧急但系统繁忙，使用安全清理"
                    )
                    if monitor:
                        monitor.cleanup_resources(aggressive=False)
            else:
                self._stats.resource_medium_count += 1
                if monitor and self._last_downgrade_level != 2:
                    monitor.perform_downgrade(level=2)
                self._last_downgrade_level = 2
                if not is_busy:
                    if monitor:
                        monitor.cleanup_resources(aggressive=True)
        else:
            if self._last_downgrade_level > 0:
                self._last_downgrade_level = 0
                if monitor:
                    monitor.perform_downgrade(level=0)
                logger.info("资源恢复正常，已解除降级")

            if self._check_error_burst():
                self._stats.error_burst_detected += 1
                logger.warning(
                    "检测到错误暴增，执行预防性资源清理"
                )
                if monitor:
                    monitor.cleanup_resources(aggressive=False)

    async def _check_scheduler_busy(self) -> bool:
        try:
            from core.services.scheduler.task.task_scheduler import get_global_scheduler
            scheduler = get_global_scheduler()
            active_tasks = await scheduler.get_active_tasks()
            if active_tasks:
                logger.debug(
                    f"系统繁忙，有 {len(active_tasks)} 个活跃任务，跳过激进清理"
                )
                return True
        except Exception as e:
            logger.warning(f"检查调度器状态失败: {e}")
        return False

    async def _apply_service_self_heal(self):
        t = self._thresholds

        unhealthy_services = await self._collect_unhealthy_services()

        for service_name in sorted(unhealthy_services):
            now = time.time()
            last_restart = self._last_restart_ts.get(service_name, 0.0)
            if (now - last_restart) < t.min_restart_interval:
                self._stats.service_restarts_skipped += 1
                continue

            history = self._restart_history.get(service_name)
            if history is None:
                history = deque()
                self._restart_history[service_name] = history

            while history and (now - history[0]) > t.restart_window_s:
                history.popleft()

            if len(history) >= t.max_restarts_per_window:
                self._stats.service_restarts_skipped += 1
                continue

            self._stats.service_restarts_attempted += 1
            ok = await self.lifecycle.restart_service(service_name)
            if ok:
                history.append(now)
                self._last_restart_ts[service_name] = now
                self._stats.service_restarts_success += 1

    async def _collect_unhealthy_services(self) -> set:
        """收集所有不健康的服务名称"""
        unhealthy_services: set = set()

        try:
            lifecycle_status = self.lifecycle.get_status()
            if (
                not bool(lifecycle_status.get("manager_initialized", False))
                or bool(lifecycle_status.get("manager_shutdown", False))
            ):
                return unhealthy_services
        except Exception:
            lifecycle_status = {}

        try:
            services_health = await self.health_checker.check_all_services()
        except Exception:
            services_health = {}

        for service_name, status in services_health.items():
            state = str(status.get("status", "unknown"))
            if state in {"unhealthy", "error"}:
                unhealthy_services.add(service_name)

        try:
            services_status = lifecycle_status.get("services", {})
            for service_name, svc in services_status.items():
                if not bool(svc.get("initialized", False)):
                    unhealthy_services.add(service_name)
        except Exception:
            pass

        return unhealthy_services


_immune_service_instance: Optional[ImmuneSystemService] = None
_immune_lock = threading.Lock()


def get_immune_system_service() -> ImmuneSystemService:
    global _immune_service_instance
    with _immune_lock:
        if _immune_service_instance is None:
            _immune_service_instance = ImmuneSystemService()
    return _immune_service_instance


async def initialize_immune_system():
    await get_immune_system_service().initialize()


async def shutdown_immune_system():
    global _immune_service_instance
    with _immune_lock:
        if _immune_service_instance is not None:
            await _immune_service_instance.shutdown()
            _immune_service_instance = None
