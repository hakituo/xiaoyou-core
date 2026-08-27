from core.utils.logger import get_logger
import asyncio

from contextlib import asynccontextmanager

from core.utils.concurrency.async_locks import LazyAsyncLock

logger = get_logger(__name__)


class GlobalResourceLock:
    _instance = None
    _semaphore = None
    _state_lock = None
    _active = 0
    _waiting = 0
    _current_holders = []
    _enabled = True
    _max_concurrent = 1
    _max_waiting = 8
    _acquire_timeout_seconds = 600.0

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GlobalResourceLock, cls).__new__(cls)
            # P2-8: 改用 LazyAsyncLock 避免在模块加载时（无事件循环）创建 asyncio.Lock
            cls._instance._state_lock = LazyAsyncLock()
            cls._instance._current_holders = []
            cls._instance._load_settings()
            cls._instance._semaphore = asyncio.Semaphore(
                int(cls._instance._max_concurrent or 1)
            )
            logger.info(
                "Global GPU Resource Gate initialized (enabled=%s, max_concurrent=%s, max_waiting=%s)",
                bool(cls._instance._enabled),
                int(cls._instance._max_concurrent or 1),
                int(cls._instance._max_waiting or 0),
            )
        return cls._instance

    def _load_settings(self) -> None:
        try:
            from config.integrated_config import get_settings

            settings = get_settings()
            sched = getattr(settings, "scheduler", None)
            self._enabled = bool(getattr(sched, "gpu_gate_enabled", True))
            self._max_concurrent = int(
                getattr(sched, "gpu_gate_max_concurrent", 1) or 1
            )
            self._max_waiting = int(getattr(sched, "gpu_gate_max_waiting", 8) or 0)
            self._acquire_timeout_seconds = float(
                getattr(sched, "gpu_gate_acquire_timeout_seconds", 600.0) or 600.0
            )
        except Exception:
            self._enabled = True
            self._max_concurrent = 1
            self._max_waiting = 8
            self._acquire_timeout_seconds = 600.0

    def get_status(self):
        return {
            "enabled": bool(self._enabled),
            "active": int(self._active or 0),
            "waiting": int(self._waiting or 0),
            "max_concurrent": int(self._max_concurrent or 1),
            "max_waiting": int(self._max_waiting or 0),
            "holders": list(self._current_holders or []),
        }

    @asynccontextmanager
    async def acquire(self, requestor: str, *, reject_if_full: bool = False):
        if not bool(self._enabled):
            yield
            return

        if not self._semaphore:
            self._semaphore = asyncio.Semaphore(int(self._max_concurrent or 1))

        async with self._state_lock:
            if bool(reject_if_full) and int(self._max_waiting or 0) > 0:
                if int(self._waiting or 0) >= int(self._max_waiting or 0):
                    raise RuntimeError("系统繁忙，队列已满，请稍后再试")
            self._waiting += 1

        acquired = False
        try:
            timeout = float(self._acquire_timeout_seconds or 0.0)
            if timeout > 0:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout)
            else:
                await self._semaphore.acquire()
            acquired = True
        except asyncio.TimeoutError as e:
            raise RuntimeError("等待 GPU 资源超时，请稍后再试") from e
        finally:
            async with self._state_lock:
                self._waiting = max(0, int(self._waiting) - 1)

        async with self._state_lock:
            self._active += 1
            if self._current_holders is None:
                self._current_holders = []
            self._current_holders.append(str(requestor))

        try:
            yield
        finally:
            async with self._state_lock:
                self._active = max(0, int(self._active) - 1)
                try:
                    if (
                        self._current_holders
                        and str(requestor) in self._current_holders
                    ):
                        self._current_holders.remove(str(requestor))
                except Exception:
                    pass
            if acquired and self._semaphore:
                try:
                    self._semaphore.release()
                except Exception:
                    pass


_global_lock = GlobalResourceLock()


def get_resource_lock():
    return _global_lock
