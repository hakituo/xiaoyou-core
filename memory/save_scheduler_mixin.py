"""自动保存与调度 Mixin
负责自动保存、异步保存和调度操作
"""
from memory.core.runtime_ops import (
    start_auto_save as start_auto_save_impl,
    start_async_save as start_async_save_impl,
    async_save_loop as async_save_loop_impl,
    process_save_queue as process_save_queue_impl,
    schedule_save as schedule_save_impl,
    schedule_trim as schedule_trim_impl,
    delayed_trim as delayed_trim_impl,
    auto_save_loop as auto_save_loop_impl,
    save_memory as save_memory_impl,
    sync_save_memory as sync_save_memory_impl,
)
from memory.core.lifecycle_ops import safe_save_all as safe_save_all_impl


class SaveSchedulerMixin:
    """自动保存与调度操作 Mixin"""

    def _start_auto_save(self):
        start_auto_save_impl(self, logger=self._logger if hasattr(self, '_logger') else __import__('logging').getLogger(__name__))

    def _start_async_save(self):
        start_async_save_impl(self, logger=self._logger if hasattr(self, '_logger') else __import__('logging').getLogger(__name__))

    def _async_save_loop(self):
        async_save_loop_impl(self, logger=self._logger if hasattr(self, '_logger') else __import__('logging').getLogger(__name__))

    def _process_save_queue(self):
        process_save_queue_impl(self, logger=self._logger if hasattr(self, '_logger') else __import__('logging').getLogger(__name__))

    def _safe_save_all(self):
        safe_save_all_impl(self)

    def _schedule_save(self):
        schedule_save_impl(self)

    def _schedule_trim(self):
        schedule_trim_impl(self, logger=self._logger if hasattr(self, '_logger') else __import__('logging').getLogger(__name__))

    def _delayed_trim(self):
        delayed_trim_impl(self, logger=self._logger if hasattr(self, '_logger') else __import__('logging').getLogger(__name__))

    def _auto_save_loop(self):
        auto_save_loop_impl(self, logger=self._logger if hasattr(self, '_logger') else __import__('logging').getLogger(__name__))

    def save_memory(self):
        save_memory_impl(self)

    def sync_save_memory(self):
        sync_save_memory_impl(self)
