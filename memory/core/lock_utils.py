"""
共享锁工具 - 统一读写锁策略

所有核心子模块应使用 get_read_lock / get_write_lock 获取锁，
而非直接使用 manager.lock，以充分利用读写锁提升并发性能。

用法:
    from memory.core.lock_utils import get_read_lock, get_write_lock

    with get_read_lock(manager):
        ...

    with get_write_lock(manager):
        ...
"""

from contextlib import contextmanager
from typing import Any


@contextmanager
def get_read_lock(manager: Any):
    """获取读锁，优先使用读写锁以提升并发性能"""
    if getattr(manager, '_use_rw_lock', False) and hasattr(manager, '_rw_lock'):
        with manager._rw_lock.read_lock():
            yield
    else:
        with manager.lock:
            yield


@contextmanager
def get_write_lock(manager: Any):
    """获取写锁，优先使用读写锁以提升并发性能"""
    if getattr(manager, '_use_rw_lock', False) and hasattr(manager, '_rw_lock'):
        with manager._rw_lock.write_lock():
            yield
    else:
        with manager.lock:
            yield
