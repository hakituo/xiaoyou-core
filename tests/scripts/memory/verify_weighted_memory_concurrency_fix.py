"""验证 weighted_memory_manager 并发迭代修复

修复目标：
1. `memory/weighted_memory_manager.py` 改用 `core.utils.logger.get_logger`，
   使 ERROR 及以上级别日志能进入 `errors_YYYYMMDD.json`。
2. `safe_save_all` 调用链上的 `weighted_memories.values()` 迭代全部加 `list()` 快照，
   防止并发写入触发 `dictionary changed size during iteration`。
3. `_trigger_immediate_distillation` 改用 `get_read_lock`，不再误用 `manager.lock`。

运行：
    venv_core\\Scripts\\python.exe tests/scripts/memory/verify_weighted_memory_concurrency_fix.py
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# 1. 静态检查：源码中关键修复点必须存在
# ---------------------------------------------------------------------------


def _read_source(rel_path: str) -> str:
    return (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")


def check_logger_migration() -> None:
    """weighted_memory_manager.py 必须使用 get_logger，而不是 logging.getLogger"""
    src = _read_source("memory/weighted_memory_manager.py")
    assert "from core.utils.logger import get_logger" in src, (
        "weighted_memory_manager.py 缺少 `from core.utils.logger import get_logger` 导入"
    )
    # 模块级 logger 必须用 get_logger
    assert "logger = get_logger(__name__)" in src, (
        "weighted_memory_manager.py 模块级 logger 应为 `logger = get_logger(__name__)`"
    )
    # 不应再有 logging.getLogger(__name__) 调用
    assert "logging.getLogger(__name__)" not in src, (
        "weighted_memory_manager.py 仍残留 `logging.getLogger(__name__)`，需全部替换为 get_logger"
    )
    print("[OK] weighted_memory_manager.py 已迁移到 get_logger")


def check_iteration_snapshots() -> None:
    """关键迭代点必须用 list() 快照"""
    cases = [
        (
            "memory/core/io_ops.py",
            "for memory in list(manager.weighted_memories.values()):",
            "save_weighted_data_locked",
        ),
        (
            "memory/core/readable_ops.py",
            "for memory in list(manager.weighted_memories.values())",
            "write_readable_history_mirror",
        ),
        (
            "memory/core/record_ops.py",
            "for memory in list(manager.weighted_memories.values()):",
            "build_weighted_readable_views",
        ),
        (
            "memory/core/runtime_ops.py",
            "list(manager.weighted_memories.values())",
            "_trigger_immediate_distillation / update_topic_index",
        ),
    ]
    for rel_path, expected_fragment, func_name in cases:
        src = _read_source(rel_path)
        assert expected_fragment in src, (
            f"{rel_path} 中 `{func_name}` 缺少快照：期望出现 `{expected_fragment}`"
        )
        print(f"[OK] {rel_path} :: {func_name} 已使用 list() 快照")


def check_runtime_ops_lock() -> None:
    """_trigger_immediate_distillation 必须走 get_read_lock，不能用 manager.lock"""
    src = _read_source("memory/core/runtime_ops.py")
    assert "from memory.core.lock_utils import get_read_lock, get_write_lock" in src, (
        "runtime_ops.py 未导入 get_read_lock"
    )
    assert "with get_read_lock(manager):" in src, (
        "runtime_ops.py 未使用 get_read_lock(manager)"
    )
    print("[OK] runtime_ops.py 已使用 get_read_lock 替代 manager.lock")


# ---------------------------------------------------------------------------
# 2. 功能检查：并发触发迭代+写入，不应抛 RuntimeError
# ---------------------------------------------------------------------------


class _FakeManager(SimpleNamespace):
    """最小化的 manager 替身，仅满足被测函数的属性访问"""

    def __init__(self) -> None:
        super().__init__()
        self.user_id = "verify_concurrency"
        self.weighted_memories: Dict[str, Dict[str, Any]] = {}
        self.short_term_memory: List[Dict[str, Any]] = []
        self.topic_weights: Dict[str, float] = {}
        self.emotion_memory_map: Dict[str, Any] = {}
        # 读写锁：复用项目里的 ReadWriteLock
        from memory.core.concurrency_optimized import ReadWriteLock

        self._rw_lock = ReadWriteLock()
        self._use_rw_lock = True
        self.lock = threading.RLock()
        # 占位属性，避免 _compact_weighted_memory_record / normalize 等访问失败
        self._default_encoding = "utf-8"

    def _compact_weighted_memory_record(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        # 直接返回浅拷贝，跳过 normalize 的复杂逻辑
        return dict(memory)

    def _normalize_memory_record(self, record: Dict[str, Any]):
        return record, False

    def _safe_json_dump(self, data: Any, file_path: str) -> None:
        # 不实际写盘，避免污染磁盘
        return

    def _safe_json_dump_atomic(self, data: Any, file_path: Any) -> None:
        return

    def _build_weighted_readable_views(self) -> Dict[str, Any]:
        from memory.core.record_ops import build_weighted_readable_views

        return build_weighted_readable_views(self)


def _spawn_writer(stop_event: threading.Event, manager: _FakeManager) -> None:
    """持续向 weighted_memories 添加条目，模拟 _preserve_removed_to_weighted 等并发写入"""
    from memory.core.lock_utils import get_write_lock

    i = 0
    while not stop_event.is_set():
        with get_write_lock(manager):
            mid = f"concurrent_{i}"
            manager.weighted_memories[mid] = {
                "id": mid,
                "content": f"消息 {i}",
                "category": "uncategorized",
                "weight": 1.0,
                "timestamp": time.time(),
                "topics": [],
                "memory_type": "dialogue",
                "status": "active",
                "is_distilled": False,
            }
            i += 1
            # 偶尔删除，制造 size 变化
            if i % 50 == 0 and len(manager.weighted_memories) > 10:
                oldest = next(iter(manager.weighted_memories))
                manager.weighted_memories.pop(oldest, None)
        time.sleep(0.0005)  # 让出 CPU，让读线程有机会进入


def _run_concurrent_iteration_round(manager: _FakeManager, rounds: int = 200) -> None:
    """反复调用三个修复点，验证并发下不抛 RuntimeError"""
    from memory.core.io_ops import save_weighted_data_locked
    from memory.core.readable_ops import write_readable_history_mirror
    from memory.core.record_ops import build_weighted_readable_views
    from memory.core.runtime_ops import _trigger_immediate_distillation  # type: ignore

    # 临时关闭蒸馏线程，避免真的启动后台 distillation
    manager._distillation_thread = None

    fake_dir = PROJECT_ROOT / "data" / "_verify_concurrency_tmp"
    fake_dir.mkdir(parents=True, exist_ok=True)

    import logging as _logging

    fake_logger = _logging.getLogger("verify_concurrency")

    for _ in range(rounds):
        # 1) save_weighted_data_locked
        save_weighted_data_locked(
            manager,
            weighted_memory_dir=fake_dir,
            logger=fake_logger,
            time_module=time,
        )
        # 2) build_weighted_readable_views
        build_weighted_readable_views(manager)
        # 3) write_readable_history_mirror（内含 list 快照 + build_weighted_readable_views）
        try:
            write_readable_history_mirror(manager)
        except Exception as exc:
            msg = str(exc)
            assert "dictionary changed size" not in msg, (
                f"write_readable_history_mirror 抛出 dict 迭代异常：{exc!r}"
            )
        # 4) _trigger_immediate_distillation 的并发读路径
        try:
            _trigger_immediate_distillation(manager, logger=fake_logger, removed_count=0)
        except Exception as exc:
            msg = str(exc)
            assert "dictionary changed size" not in msg, (
                f"_trigger_immediate_distillation 抛出 dict 迭代异常：{exc!r}"
            )

    # 清理临时目录
    try:
        for p in fake_dir.glob("*"):
            p.unlink()
        fake_dir.rmdir()
    except Exception:
        pass


def check_concurrent_iteration_no_crash() -> None:
    """并发读写 weighted_memories，验证修复后不抛 RuntimeError"""
    manager = _FakeManager()
    # 预填一些数据
    for i in range(50):
        mid = f"seed_{i}"
        manager.weighted_memories[mid] = {
            "id": mid,
            "content": f"种子 {i}",
            "category": "uncategorized",
            "weight": 1.0,
            "timestamp": time.time(),
            "topics": [],
            "memory_type": "dialogue",
            "status": "active",
            "is_distilled": False,
        }

    stop_event = threading.Event()
    writer = threading.Thread(
        target=_spawn_writer, args=(stop_event, manager), name="concurrent-writer", daemon=True
    )
    writer.start()

    try:
        _run_concurrent_iteration_round(manager, rounds=200)
    finally:
        stop_event.set()
        writer.join(timeout=2.0)

    print(
        f"[OK] 并发迭代 200 轮无 RuntimeError（writer 最终写入 {len(manager.weighted_memories)} 条）"
    )


# ---------------------------------------------------------------------------
# 3. 日志通道检查：ERROR 能进入 errors_*.json
# ---------------------------------------------------------------------------


def check_error_logger_channel() -> None:
    """验证 memory.weighted_memory_manager logger 挂了 SafeQueueHandler"""
    import memory.weighted_memory_manager as wmm

    logger = wmm.logger
    handler_types = {type(h).__name__ for h in logger.handlers}
    assert "SafeQueueHandler" in handler_types, (
        f"memory.weighted_memory_manager logger 未挂 SafeQueueHandler，当前 handlers={handler_types}"
    )
    print(f"[OK] logger.handlers = {sorted(handler_types)}，ERROR 将进入 errors_*.json")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def main() -> int:
    print("=" * 70)
    print("验证 weighted_memory_manager 并发迭代修复")
    print("=" * 70)

    failures: List[str] = []

    checks = [
        ("静态检查：logger 迁移", check_logger_migration),
        ("静态检查：迭代点快照", check_iteration_snapshots),
        ("静态检查：runtime_ops 锁修复", check_runtime_ops_lock),
        ("功能检查：并发迭代不崩溃", check_concurrent_iteration_no_crash),
        ("功能检查：ERROR 日志通道", check_error_logger_channel),
    ]
    for label, fn in checks:
        print(f"\n--- {label} ---")
        try:
            fn()
        except AssertionError as exc:
            failures.append(f"[{label}] {exc}")
            print(f"[FAIL] {exc}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"[{label}] 非预期异常: {exc!r}")
            print(f"[ERROR] {exc!r}")

    print("\n" + "=" * 70)
    if failures:
        print(f"验证失败：{len(failures)} 项")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("全部验证通过 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
