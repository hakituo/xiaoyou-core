"""验证 weighted_memory_manager 并发迭代修复

修复目标：
1. `memory/weighted_memory_manager.py` 改用 `core.utils.logger.get_logger`，
   使 ERROR 及以上级别日志能进入 `errors_YYYYMMDD.json`。
2. `safe_save_all` 调用链上的 `weighted_memories.values()` 迭代全部加 `list()` 快照，
   防止并发写入触发 `dictionary changed size during iteration`。
3. `_trigger_immediate_distillation` 改用 `get_read_lock`，不再误用 `manager.lock`。
4. `safe_save_all` 整段序列化必须持读锁，防止 `topic_weights` /
   `emotion_memory_map` 拷贝期间并发写入触发 `dictionary changed size during
   iteration`（异步保存循环上报的 ERROR）。

运行：
    venv_core\\Scripts\\python.exe tests/scripts/memory/verify_weighted_memory_concurrency_fix.py
"""
from __future__ import annotations

import sys
import shutil
import threading
import time
from collections import defaultdict
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


def check_shared_dict_snapshot_iteration() -> None:
    """共享字典的 Python 层迭代必须走 list 快照

    注意：``dict(d)`` / ``list(d.values())`` 是 C 层拷贝，并发写入时**不会**抛异常，
    只有 Python 层迭代（``for k, v in d.items()``、``json.dumps(indent=...)``）才会抛
    "dictionary changed size during iteration"，所以这些点必须显式快照。
    """
    cases = [
        (
            "memory/core/keyword_index.py",
            "for memory_id, memory in list(weighted_memories.items()):",
            "rebuild_keyword_index",
        ),
        (
            "memory/core/preferences.py",
            "for mid, mem in list(weighted_memories.items()):",
            "rebuild_preference_index_locked",
        ),
        (
            "memory/core/record_ops.py",
            "list(manager.weighted_memories.items())",
            "rebuild_memory_indexes_locked",
        ),
        (
            "memory/core/maintenance_ops.py",
            "list(manager.weighted_memories.items())",
            "reclassify_all_memories",
        ),
    ]
    for rel_path, expected_fragment, func_name in cases:
        src = _read_source(rel_path)
        assert expected_fragment in src, (
            f"{rel_path} 中 `{func_name}` 缺少快照：期望出现 `{expected_fragment}`"
        )
        print(f"[OK] {rel_path} :: {func_name} 已使用 list() 快照")


def check_rebuild_keyword_index_snapshot() -> None:
    """遍历过程中向 weighted_memories 插入新条目，rebuild_keyword_index 不得崩溃

    用 extract_keywords 回调在遍历中途插入新键，等价于另一个线程并发写入，
    但不依赖线程时序，结果稳定可复现。
    """
    from memory.core.keyword_index import rebuild_keyword_index

    weighted_memories: Dict[str, Dict[str, Any]] = {}
    for i in range(5):
        mid = f"m{i}"
        weighted_memories[mid] = {
            "id": mid,
            "content": f"内容 {i}",
            "topics": ["daily"],
            "keywords": [],
        }

    injected = {"done": False}

    def _extract_keywords(text: str) -> set:
        if not injected["done"]:
            injected["done"] = True
            weighted_memories["injected"] = {
                "id": "injected",
                "content": "遍历中途插入",
                "topics": ["daily"],
                "keywords": [],
            }
        return set()

    try:
        rebuild_keyword_index(weighted_memories, _extract_keywords)
    except RuntimeError as exc:
        raise AssertionError(
            f"rebuild_keyword_index 在遍历期间被并发写入时崩溃：{exc!r}"
        ) from exc

    assert injected["done"] is True, "回调未执行，用例未真正覆盖并发写入场景"
    print("[OK] rebuild_keyword_index 遍历期间插入新条目不崩溃")


def check_safe_save_all_read_lock() -> None:
    """safe_save_all 必须在读锁内完成序列化（topic_weights/emotion_memory_map 拷贝）"""
    src = _read_source("memory/core/lifecycle_ops.py")
    assert "from memory.core.lock_utils import get_read_lock" in src, (
        "lifecycle_ops.py 未导入 get_read_lock"
    )
    start = src.index("def safe_save_all(")
    end = src.find("\ndef ", start)
    body = src[start : end if end != -1 else len(src)]
    assert "with get_read_lock(manager):" in body, (
        "lifecycle_ops.safe_save_all 未在读锁内序列化内存数据，"
        "并发写入 topic_weights/emotion_memory_map 时会抛 "
        "'dictionary changed size during iteration'"
    )
    print("[OK] lifecycle_ops.safe_save_all 已在读锁内序列化内存数据")


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
        # 生产环境是 defaultdict：写入新键会触发 dict 扩容，
        # 这正是 "dictionary changed size during iteration" 的触发条件
        self.topic_weights: Dict[str, float] = defaultdict(float)
        self.emotion_memory_map: Dict[str, Any] = defaultdict(list)
        # 读写锁：复用项目里的 ReadWriteLock
        from memory.core.concurrency_optimized import ReadWriteLock

        self._rw_lock = ReadWriteLock()
        self._use_rw_lock = True
        self.lock = threading.RLock()
        # 占位属性，避免 _compact_weighted_memory_record / normalize 等访问失败
        self._default_encoding = "utf-8"
        self.memory_dir = PROJECT_ROOT / ".tmp" / "verify_weighted_memory_concurrency"
        self.readable_history_root = self.memory_dir / "readable_history"
        self.weighted_memory_dir = self.memory_dir / "weighted"
        self.short_term_dir = self.memory_dir / "short_term"
        self.sensitive_dir = self.memory_dir / "sensitive"
        self.last_save_time = 0.0
        self.enable_readable_history_mirror = False

    def _compact_weighted_memory_record(
        self,
        memory: Dict[str, Any],
        *,
        keep_embedding: bool = False,
    ) -> Dict[str, Any]:
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

    def _build_short_term_disk_records(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        from memory.core.readable_ops import build_short_term_disk_records

        return build_short_term_disk_records(self, messages)

    def _normalize_category_dir(self, category: str) -> str:
        return str(category or "uncategorized").strip().lower() or "uncategorized"

    def _save_weighted_data_locked(self) -> None:
        import logging as _logging

        from memory.core.io_ops import save_weighted_data_locked

        save_weighted_data_locked(
            self,
            weighted_memory_dir=self.weighted_memory_dir,
            logger=_logging.getLogger("verify_concurrency"),
            time_module=time,
        )

    def _save_important_prompts_locked(self) -> None:
        import logging as _logging

        from memory.core.io_ops import save_important_prompts_locked

        save_important_prompts_locked(
            self,
            weighted_memory_dir=self.weighted_memory_dir,
            default_encoding=self._default_encoding,
            logger=_logging.getLogger("verify_concurrency"),
        )


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
                # 验证目标是并发迭代，不应启动真实夜间蒸馏线程。
                "is_distilled": True,
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
        shutil.rmtree(manager.memory_dir, ignore_errors=True)
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
            # 验证目标是并发迭代，不应启动真实夜间蒸馏线程。
            "is_distilled": True,
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


def _spawn_index_writer(stop_event: threading.Event, manager: _FakeManager) -> None:
    """模拟不持锁的写入方（后台加载线程等）持续改动共享字典

    ``topic_weights`` / ``emotion_memory_map`` 是 defaultdict，插入新键会改变
    dict 大小；``weighted_memories`` 也会被插入/删除。写入方故意**不**走读写锁，
    用来验证保存链路即使面对绕过锁的写入也不会抛
    "dictionary changed size during iteration"。
    """
    # 键名取模复用：字典规模保持有界，避免测试越跑越慢
    i = 0
    while not stop_event.is_set():
        slot = i % 2000
        manager.topic_weights[f"live_topic_{slot}"] = float(i)
        manager.emotion_memory_map[f"live_emotion_{slot}"] = [
            {"memory_id": f"m{slot}", "relevance_score": 0.8}
        ]
        manager.weighted_memories[f"live_mem_{slot}"] = {
            "id": f"live_mem_{slot}",
            "content": f"并发写入 {slot}",
            "category": "uncategorized",
            "weight": 1.0,
            "timestamp": time.time(),
            "topics": [],
            "memory_type": "dialogue",
            "status": "active",
            "is_distilled": True,
        }
        i += 1
        if i % 500 == 0:
            # 制造 size 收缩，覆盖插入与清空两种 size 变化
            manager.topic_weights.clear()
            manager.emotion_memory_map.clear()
        time.sleep(0)


def check_concurrent_safe_save_all_no_crash() -> None:
    """并发写入索引字典时调用 safe_save_all，不应抛 RuntimeError"""
    from memory.core.lifecycle_ops import safe_save_all

    manager = _FakeManager()
    manager.short_term_memory = [
        {
            "id": f"short_{i}",
            "content": f"短期消息 {i}",
            "role": "user",
            "timestamp": time.time(),
        }
        for i in range(20)
    ]
    # 预填足够多的键，让 dict 拷贝耗时足以被线程切换打断；规模保持有界
    for i in range(3000):
        manager.topic_weights[f"topic_{i}"] = float(i)
        manager.emotion_memory_map[f"emotion_{i}"] = [
            {"memory_id": f"m{i}", "relevance_score": 0.8}
        ]

    origin_switchinterval = sys.getswitchinterval()
    stop_event = threading.Event()
    writer = threading.Thread(
        target=_spawn_index_writer,
        args=(stop_event, manager),
        name="concurrent-index-writer",
        daemon=True,
    )
    writer.start()
    # 缩小线程切换间隔，提高竞态复现概率（与被测逻辑无关，仅为测试灵敏度）
    sys.setswitchinterval(1e-5)
    # 硬超时兜底：无论发生什么都必须结束，避免验证脚本卡死
    deadline = time.time() + 30.0
    rounds = 0
    try:
        while rounds < 40 and time.time() < deadline:
            try:
                safe_save_all(manager)
            except RuntimeError as exc:
                raise AssertionError(f"safe_save_all 抛出并发迭代异常：{exc!r}") from exc
            rounds += 1
    finally:
        sys.setswitchinterval(origin_switchinterval)
        stop_event.set()
        writer.join(timeout=5.0)
        shutil.rmtree(manager.memory_dir, ignore_errors=True)

    assert rounds > 0, "safe_save_all 一轮都没跑完"
    assert manager.last_save_time > 0, "safe_save_all 未更新 last_save_time"
    print(f"[OK] 并发写入索引字典时 safe_save_all {rounds} 轮无 RuntimeError")


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
        ("静态检查：safe_save_all 读锁", check_safe_save_all_read_lock),
        ("静态检查：共享字典快照迭代", check_shared_dict_snapshot_iteration),
        ("功能检查：关键词索引重建快照", check_rebuild_keyword_index_snapshot),
        ("功能检查：并发迭代不崩溃", check_concurrent_iteration_no_crash),
        ("功能检查：并发保存不崩溃", check_concurrent_safe_save_all_no_crash),
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
