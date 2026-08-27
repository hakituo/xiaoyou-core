#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0-09 验证脚本: reminder_service.py 自死锁回调移到锁外

验证项：
1. schedule_message: 回调 (_append_workspace_memory) 与 active_care 通知在锁外执行
2. delete_message: 回调在锁外执行
3. 回调内部尝试重新获取同一把锁时不会死锁（关键场景）
4. 业务数据一致性保留（schedule/delete 仍然写入 store）
"""
import sys
import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, AsyncMock

ROOT = Path(__file__).resolve().parents[3]
SERVICE_PATH = ROOT / "core" / "services" / "workspace" / "reminder_service.py"


def _install_stubs():
    """预存根依赖。"""
    for pkg_name in ("core", "core.services", "core.services.workspace"):
        if pkg_name not in sys.modules:
            pkg = ModuleType(pkg_name)
            pkg.__path__ = []  # type: ignore[attr-defined]
            sys.modules[pkg_name] = pkg

    # core.services.workspace.models - ScheduledMessage
    if "core.services.workspace.models" not in sys.modules:
        from pydantic import BaseModel
        from typing import Any, Dict
        models_mod = ModuleType("core.services.workspace.models")

        class ScheduledMessage(BaseModel):
            id: str
            trigger_ts: float
            message: str
            message_type: str = "text"
            status: str = "pending"
            metadata: Dict[str, Any] = {}
            triggered_at: float | None = None

        models_mod.ScheduledMessage = ScheduledMessage
        sys.modules["core.services.workspace.models"] = models_mod

    # core.services.workspace.reminder_store - WorkspaceReminderStore
    if "core.services.workspace.reminder_store" not in sys.modules:
        store_mod = ModuleType("core.services.workspace.reminder_store")

        class WorkspaceReminderStore:
            def __init__(self):
                self._data = []

            async def read(self):
                return list(self._data)

            async def write(self, data):
                self._data = list(data)

        store_mod.WorkspaceReminderStore = WorkspaceReminderStore
        sys.modules["core.services.workspace.reminder_store"] = store_mod


def load_module():
    _install_stubs()

    spec = importlib.util.spec_from_file_location("reminder_service_p0_09", SERVICE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {SERVICE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_source_callbacks_outside_lock() -> list[str]:
    """检查源码层面：回调不在 async with self._lock 块内。"""
    issues = []
    content = SERVICE_PATH.read_text(encoding="utf-8")

    # 简单检查：_append_workspace_memory 不应出现在 async with self._lock 块内
    # 通过逐行解析，跟踪锁的缩进上下文
    lines = content.splitlines()
    in_lock = False
    lock_indent = -1
    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        # 进入锁块：检测 "async with self._lock:"
        if "async with self._lock:" in stripped:
            in_lock = True
            lock_indent = indent
            continue

        # 退出锁块：遇到缩进 <= lock_indent 的非空行
        if in_lock and stripped and indent <= lock_indent:
            in_lock = False

        # 在锁块内出现回调调用
        if in_lock and "_append_workspace_memory" in stripped:
            issues.append(f"第 {i} 行: _append_workspace_memory 在锁块内调用: {stripped}")
        if in_lock and "notify_workspace_reminder_updated" in stripped:
            issues.append(f"第 {i} 行: notify_workspace_reminder_updated 在锁块内调用: {stripped}")

    return issues


def _make_callback_that_reacquires_lock(lock):
    """构造一个会尝试重新获取同一把锁的回调（模拟自死锁场景）。"""
    call_log = []

    async def _callback(*args, **kwargs):
        call_log.append(("called", args, kwargs))
        # 尝试重新获取锁（如果回调在锁内执行，会死锁）
        try:
            async with lock:
                call_log.append(("reacquired",))
        except Exception as e:
            call_log.append(("error", str(e)))
            raise

    return _callback, call_log


def check_no_deadlock_when_callback_reacquires(module) -> list[str]:
    """关键测试：回调内部重新获取同一把锁时不应死锁。"""
    issues = []

    WorkspaceReminderService = getattr(module, "WorkspaceReminderService", None)
    if WorkspaceReminderService is None:
        issues.append("缺失 WorkspaceReminderService 类")
        return issues

    # 准备依赖
    from core.services.workspace.reminder_store import WorkspaceReminderStore

    lock = asyncio.Lock()
    store = WorkspaceReminderStore()

    callback, call_log = _make_callback_that_reacquires_lock(lock)

    service = WorkspaceReminderService(
        store=store,
        lock=lock,
        append_workspace_memory=callback,
    )

    # 测试 schedule_message：如果回调在锁内执行，会死锁超时
    try:
        asyncio.run(asyncio.wait_for(
            service.schedule_message(
                message="test",
                trigger_ts=9999999999.0,
                message_type="text",
            ),
            timeout=3.0,
        ))
    except asyncio.TimeoutError:
        issues.append("schedule_message 死锁：回调在锁内执行导致重新获取锁超时")
        return issues
    except Exception as e:
        issues.append(f"schedule_message 异常: {e}")
        return issues

    # 检查回调是否被调用，以及是否成功重新获取锁
    if not any(entry[0] == "called" for entry in call_log):
        issues.append("schedule_message 未调用回调")
    if not any(entry[0] == "reacquired" for entry in call_log):
        issues.append("回调未能重新获取锁（可能死锁被吞掉）")

    # 测试 delete_message
    call_log.clear()
    # 先添加一条记录
    asyncio.run(service.schedule_message(
        message="to-delete",
        trigger_ts=9999999999.0,
    ))
    call_log.clear()

    try:
        asyncio.run(asyncio.wait_for(
            service.delete_message(msg_id="non-existent"),
            timeout=3.0,
        ))
    except asyncio.TimeoutError:
        issues.append("delete_message 死锁")

    # 应该没有回调（因为消息不存在，没删除）
    if any(entry[0] == "called" for entry in call_log):
        issues.append("delete_message 在未实际删除时调用了回调")

    return issues


def check_data_consistency_preserved(module) -> list[str]:
    """业务数据一致性保留：schedule/delete 仍然正确写入 store。"""
    issues = []

    WorkspaceReminderService = getattr(module, "WorkspaceReminderService", None)
    if WorkspaceReminderService is None:
        issues.append("缺失 WorkspaceReminderService 类")
        return issues

    from core.services.workspace.reminder_store import WorkspaceReminderStore

    lock = asyncio.Lock()
    store = WorkspaceReminderStore()

    async def _noop_callback(*args, **kwargs):
        pass

    service = WorkspaceReminderService(
        store=store,
        lock=lock,
        append_workspace_memory=_noop_callback,
    )

    async def _run():
        # schedule
        msg_id = await service.schedule_message(
            message="hello",
            trigger_ts=1000.0,
            message_type="text",
        )

        # 验证 store 中有这条记录
        all_msgs = await store.read()
        if not any(m.get("id") == msg_id for m in all_msgs):
            issues.append("schedule 后 store 中未找到记录")
            return

        # get_pending_messages 应返回这条
        pending = await service.get_pending_messages()
        if not any(m.id == msg_id for m in pending):
            issues.append("get_pending_messages 未返回新加的记录")

        # delete
        deleted = await service.delete_message(msg_id)
        if not deleted:
            issues.append("delete_message 应返回 True")
            return

        # store 中应不再有这条记录
        all_msgs = await store.read()
        if any(m.get("id") == msg_id for m in all_msgs):
            issues.append("delete 后 store 中仍存在记录")

    try:
        asyncio.run(_run())
    except Exception as e:
        issues.append(f"数据一致性测试异常: {e}")

    return issues


def check_callback_failure_does_not_lose_data(module) -> list[str]:
    """回调失败不应影响业务数据一致性。"""
    issues = []

    WorkspaceReminderService = getattr(module, "WorkspaceReminderService", None)
    if WorkspaceReminderService is None:
        issues.append("缺失 WorkspaceReminderService 类")
        return issues

    from core.services.workspace.reminder_store import WorkspaceReminderStore

    lock = asyncio.Lock()
    store = WorkspaceReminderStore()

    async def _failing_callback(*args, **kwargs):
        raise RuntimeError("callback intentionally failed")

    service = WorkspaceReminderService(
        store=store,
        lock=lock,
        append_workspace_memory=_failing_callback,
    )

    async def _run():
        msg_id = await service.schedule_message(
            message="will-fail-callback",
            trigger_ts=2000.0,
        )
        # 即使回调失败，数据应该已经写入 store
        all_msgs = await store.read()
        if not any(m.get("id") == msg_id for m in all_msgs):
            issues.append("回调失败导致 schedule 数据丢失")

    try:
        asyncio.run(_run())
    except Exception as e:
        issues.append(f"回调失败场景异常（应被吞掉）: {e}")

    return issues


def main() -> int:
    if not SERVICE_PATH.exists():
        print(f"[ERROR] reminder_service.py 不存在: {SERVICE_PATH}")
        return 2

    all_issues: list[str] = []
    all_issues.extend(check_source_callbacks_outside_lock())

    try:
        module = load_module()
        all_issues.extend(check_no_deadlock_when_callback_reacquires(module))
        all_issues.extend(check_data_consistency_preserved(module))
        all_issues.extend(check_callback_failure_does_not_lose_data(module))
    except Exception as exc:
        all_issues.append(f"模块加载/运行时测试失败: {exc}")

    if all_issues:
        print(f"[FAIL] 共发现 {len(all_issues)} 个问题:")
        for issue in all_issues:
            print(f"  - {issue}")
        return 1

    print("[OK] reminder_service.py 自死锁问题已修复")
    print("  - schedule_message: 回调与 active_care 通知移到锁外")
    print("  - delete_message: 回调移到锁外")
    print("  - 回调内部重新获取同一把锁时不再死锁（关键场景验证）")
    print("  - 业务数据一致性保留（schedule/delete 正确写入 store）")
    print("  - 回调失败不影响业务数据一致性")
    return 0


if __name__ == "__main__":
    sys.exit(main())
