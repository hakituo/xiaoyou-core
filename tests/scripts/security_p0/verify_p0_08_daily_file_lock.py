#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0-08 验证脚本: daily/manager.py 数据竞争加文件锁

验证项：
1. 所有 record_* 方法的 read-modify-write 都包裹在 _with_record_lock 中
2. _with_record_lock 使用 filelock.FileLock 跨进程互斥
3. 实际并发写入测试：两个线程并发 record_meal，最终 meals 数量应等于两次之和
   （无锁时可能丢失一次写入）
4. 锁文件路径与 daily_record.json 同目录
"""
import sys
import os
import json
import shutil
import tempfile
import threading
import time
import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
MANAGER_PATH = ROOT / "core" / "services" / "daily" / "manager.py"


def _install_stubs():
    """预存根依赖。"""
    for pkg_name in ("core", "core.utils", "core.services", "core.services.daily"):
        if pkg_name not in sys.modules:
            pkg = ModuleType(pkg_name)
            pkg.__path__ = []  # type: ignore[attr-defined]
            sys.modules[pkg_name] = pkg

    # core.utils.logger
    if "core.utils.logger" not in sys.modules:
        import logging
        m = ModuleType("core.utils.logger")
        m.get_logger = lambda name: logging.getLogger(name)
        sys.modules["core.utils.logger"] = m

    # core.utils.singleton
    if "core.utils.singleton" not in sys.modules:
        m = ModuleType("core.utils.singleton")

        class SingletonFactory:
            def __init__(self, cls):
                self._cls = cls
                self._instance = None

            def get(self, *args, **kwargs):
                if self._instance is None:
                    self._instance = self._cls(*args, **kwargs)
                return self._instance

        m.SingletonFactory = SingletonFactory
        sys.modules["core.utils.singleton"] = m

    # core.utils.data_paths
    if "core.utils.data_paths" not in sys.modules:
        m = ModuleType("core.utils.data_paths")
        # 默认使用临时目录，可被外部 patch
        _default_dir = tempfile.mkdtemp(prefix="daily_records_")
        m.get_user_daily_records_dir = lambda: _default_dir
        sys.modules["core.utils.data_paths"] = m

    # core.utils.time_utils
    if "core.utils.time_utils" not in sys.modules:
        m = ModuleType("core.utils.time_utils")
        from datetime import datetime
        m.get_diary_target_date_str = lambda: datetime.now().strftime("%Y-%m-%d")
        sys.modules["core.utils.time_utils"] = m


def load_module():
    _install_stubs()

    spec = importlib.util.spec_from_file_location("daily_manager_p0_08", MANAGER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {MANAGER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_source_uses_lock() -> list[str]:
    """检查源码层面所有 record_* 方法都用了 _with_record_lock。"""
    issues = []
    content = MANAGER_PATH.read_text(encoding="utf-8")

    # 必须导入 filelock
    if "from filelock import" not in content:
        issues.append("缺失 `from filelock import` 导入")

    # 必须有 _with_record_lock 上下文管理器
    if "_with_record_lock" not in content:
        issues.append("缺失 _with_record_lock 上下文管理器")

    # 检查每个 record_* 方法的实现体是否包含 _with_record_lock
    record_methods = [
        "record_wakeup",
        "record_sleep",
        "record_meal",
        "upsert_meal",
        "record_drink",
        "record_study",
        "record_activity",
        "record_health",
        "record_mood",
    ]

    for method_name in record_methods:
        # 简单检查：方法定义后到下一个 def 之间应该出现 _with_record_lock
        # 用 split 找方法块
        marker = f"def {method_name}("
        if marker not in content:
            issues.append(f"缺失方法定义: {method_name}")
            continue

        # 找方法定义起点
        start = content.index(marker)
        # 找下一个 def（从 start+10 开始，避免命中自己）
        next_def_pos = content.find("\n    def ", start + 10)
        if next_def_pos == -1:
            method_block = content[start:]
        else:
            method_block = content[start:next_def_pos]

        if "_with_record_lock" not in method_block:
            issues.append(f"方法 {method_name} 未使用 _with_record_lock 保护")

    return issues


def check_concurrent_writes_no_loss(module) -> list[str]:
    """并发写入测试：两个线程同时写 meals，应无丢失。"""
    issues = []

    DailyActivityManager = getattr(module, "DailyActivityManager", None)
    if DailyActivityManager is None:
        issues.append("缺失 DailyActivityManager 类")
        return issues

    # 使用独立的临时目录
    test_dir = tempfile.mkdtemp(prefix="daily_concurrent_test_")
    try:
        with patch.object(module, "get_user_daily_records_dir", lambda: test_dir):
            # 同时 patch core.utils.data_paths.get_user_daily_records_dir
            sys.modules["core.utils.data_paths"].get_user_daily_records_dir = lambda: test_dir
            manager = DailyActivityManager()

            # 用 threading.Barrier 确保两个线程同时进入 read-modify-write
            barrier = threading.Barrier(2)
            errors = []

            def writer(content: str):
                try:
                    barrier.wait(timeout=5.0)  # 同步启动
                    manager.record_meal("test", content)
                except Exception as e:
                    errors.append(e)

            t1 = threading.Thread(target=writer, args=("meal-A",))
            t2 = threading.Thread(target=writer, args=("meal-B",))
            t1.start()
            t2.start()
            t1.join(timeout=10.0)
            t2.join(timeout=10.0)

            if errors:
                issues.append(f"并发写入异常: {errors}")
                return issues

            # 检查最终文件中的 meals 数量
            record = manager.get_record()
            meals = record.get("meals", [])
            meal_contents = [m.get("content") for m in meals if isinstance(m, dict)]
            if len(meals) != 2:
                issues.append(
                    f"并发写入丢失数据: 期望 2 条 meal，实际 {len(meals)} 条: {meal_contents}"
                )
            else:
                if "meal-A" not in meal_contents or "meal-B" not in meal_contents:
                    issues.append(f"并发写入数据错误: {meal_contents}")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)

    return issues


def check_lock_file_created(module) -> list[str]:
    """验证锁文件路径与 daily_record.json 同目录，名为 daily_record.json.lock。"""
    issues = []

    DailyActivityManager = getattr(module, "DailyActivityManager", None)
    if DailyActivityManager is None:
        issues.append("缺失 DailyActivityManager 类")
        return issues

    test_dir = tempfile.mkdtemp(prefix="daily_lock_path_test_")
    try:
        sys.modules["core.utils.data_paths"].get_user_daily_records_dir = lambda: test_dir
        manager = DailyActivityManager()

        lock_path = manager._get_lock_path("2026-07-26")
        # 规范化为正斜杠比较
        normalized_lock = lock_path.replace("\\", "/")
        expected_suffix = "2026/7/26/daily_record.json.lock"
        if not normalized_lock.endswith(expected_suffix):
            issues.append(
                f"锁路径错误: {lock_path}，期望以 {expected_suffix} 结尾"
            )

        # 在持锁期间检查锁文件存在（filelock 在 Windows 释放后会删除锁文件，
        # 因此只能在临界区内验证）
        lock_exists_during_hold = False
        with manager._with_record_lock("2026-07-26"):
            lock_exists_during_hold = os.path.exists(lock_path)

        if not lock_exists_during_hold:
            issues.append(f"持锁期间未发现锁文件: {lock_path}")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)

    return issues


def check_lock_serializes(module) -> list[str]:
    """验证 _with_record_lock 真的会串行化：两个线程进入临界区的时间不重叠。"""
    issues = []

    DailyActivityManager = getattr(module, "DailyActivityManager", None)
    if DailyActivityManager is None:
        issues.append("缺失 DailyActivityManager 类")
        return issues

    test_dir = tempfile.mkdtemp(prefix="daily_serialize_test_")
    try:
        sys.modules["core.utils.data_paths"].get_user_daily_records_dir = lambda: test_dir
        manager = DailyActivityManager()

        # 用一个列表记录进入/退出临界区的时间戳
        events = []
        events_lock = threading.Lock()

        def critical_worker(name: str):
            with manager._with_record_lock():
                with events_lock:
                    events.append(("enter", name, time.time()))
                time.sleep(0.1)  # 模拟工作
                with events_lock:
                    events.append(("exit", name, time.time()))

        threads = [threading.Thread(target=critical_worker, args=(f"w{i}",)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        # 验证任意两个临界区不重叠
        enters = [(name, ts) for ev, name, ts in events if ev == "enter"]
        exits = [(name, ts) for ev, name, ts in events if ev == "exit"]

        # 按 enter 时间排序
        enters.sort(key=lambda x: x[1])
        exits.sort(key=lambda x: x[1])

        # 第 i+1 个 enter 应该在第 i 个 exit 之后
        for i in range(len(enters) - 1):
            _, enter_ts = enters[i + 1]
            _, exit_ts = exits[i]
            if enter_ts < exit_ts - 0.001:  # 允许 1ms 误差
                issues.append(
                    f"临界区重叠: w{i+1} enter @ {enter_ts:.4f} < w{i} exit @ {exit_ts:.4f}"
                )
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)

    return issues


def main() -> int:
    if not MANAGER_PATH.exists():
        print(f"[ERROR] manager.py 不存在: {MANAGER_PATH}")
        return 2

    all_issues: list[str] = []
    all_issues.extend(check_source_uses_lock())

    try:
        module = load_module()
        all_issues.extend(check_concurrent_writes_no_loss(module))
        all_issues.extend(check_lock_file_created(module))
        all_issues.extend(check_lock_serializes(module))
    except Exception as exc:
        all_issues.append(f"模块加载/运行时测试失败: {exc}")

    if all_issues:
        print(f"[FAIL] 共发现 {len(all_issues)} 个问题:")
        for issue in all_issues:
            print(f"  - {issue}")
        return 1

    print("[OK] daily/manager.py 数据竞争已加文件锁保护")
    print("  - 9 个 record_* 方法全部使用 _with_record_lock 保护")
    print("  - 跨进程文件锁基于 filelock.FileLock（Windows/Linux 通用）")
    print("  - 并发写入测试无数据丢失")
    print("  - 锁文件路径 = daily_record.json.lock（同目录）")
    print("  - 多线程临界区串行化验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
