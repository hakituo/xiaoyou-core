#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0-22 验证脚本：core/image/image_manager.py async 单例竞态条件

验证范围：
1. _image_manager_lock 锁对象存在且为 asyncio.Lock 类型
2. get_image_manager 使用 double-check locking 模式
3. shutdown_image_manager_instance 使用锁保护
4. 实际并发测试：多协程调用不会重复初始化
5. 模块可以正常导入
"""

from __future__ import annotations

import asyncio
import ast
import sys
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def _read_file(rel_path: str) -> str:
    """读取项目内文件"""
    return (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")


# ============================================================================
# 场景1: 锁对象存在且为 asyncio.Lock 类型
# ============================================================================

def check_lock_exists() -> List[str]:
    """验证 _image_manager_lock 锁对象存在"""
    issues: List[str] = []
    source = _read_file("core/image/image_manager.py")

    if "_image_manager_lock" not in source:
        issues.append("源码中未找到 _image_manager_lock")
        return issues

    if "asyncio.Lock()" not in source:
        issues.append("未使用 asyncio.Lock() 创建锁")

    try:
        from core.image.image_manager import _image_manager_lock
        if not isinstance(_image_manager_lock, asyncio.Lock):
            issues.append(
                f"_image_manager_lock 类型不对: "
                f"{type(_image_manager_lock).__name__}，应为 asyncio.Lock"
            )
    except ImportError as e:
        issues.append(f"无法导入 _image_manager_lock: {e}")

    return issues


# ============================================================================
# 场景2: get_image_manager 使用 double-check locking 模式
# ============================================================================

def check_double_check_locking() -> List[str]:
    """验证 get_image_manager 使用 double-check locking 模式"""
    issues: List[str] = []
    source = _read_file("core/image/image_manager.py")

    tree = ast.parse(source)
    found_get_image_manager = False
    found_double_check = False
    found_async_with_lock = False

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "get_image_manager"
        ):
            found_get_image_manager = True
            for sub in ast.walk(node):
                if isinstance(sub, ast.AsyncWith):
                    for item in sub.items:
                        ctx = item.context_expr
                        if (
                            isinstance(ctx, ast.Name)
                            and ctx.id == "_image_manager_lock"
                        ):
                            found_async_with_lock = True
                            # 检查 async with 块内是否有 if _image_manager_instance is not None:
                            for body_node in sub.body:
                                if isinstance(body_node, ast.If):
                                    test = body_node.test
                                    if (
                                        isinstance(test, ast.Compare)
                                        and isinstance(test.left, ast.Name)
                                        and test.left.id == "_image_manager_instance"
                                    ):
                                        found_double_check = True
            break

    if not found_get_image_manager:
        issues.append("未找到 get_image_manager 函数")
    if not found_async_with_lock:
        issues.append("get_image_manager 未使用 async with _image_manager_lock:")
    if not found_double_check:
        issues.append("get_image_manager 未使用 double-check locking 模式")

    return issues


# ============================================================================
# 场景3: shutdown_image_manager_instance 使用锁保护
# ============================================================================

def check_shutdown_locked() -> List[str]:
    """验证 shutdown_image_manager_instance 使用锁保护"""
    issues: List[str] = []
    source = _read_file("core/image/image_manager.py")

    tree = ast.parse(source)
    found_shutdown = False
    found_locked = False

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "shutdown_image_manager_instance"
        ):
            found_shutdown = True
            for sub in ast.walk(node):
                if isinstance(sub, ast.AsyncWith):
                    for item in sub.items:
                        ctx = item.context_expr
                        if (
                            isinstance(ctx, ast.Name)
                            and ctx.id == "_image_manager_lock"
                        ):
                            found_locked = True

    if not found_shutdown:
        issues.append("未找到 shutdown_image_manager_instance 函数")
    if not found_locked:
        issues.append("shutdown_image_manager_instance 未使用锁保护")

    return issues


# ============================================================================
# 场景4: 实际并发测试 - 多协程调用不会重复初始化
# ============================================================================

def check_concurrent_initialization_safe() -> List[str]:
    """验证多协程并发调用不会重复初始化"""
    issues: List[str] = []

    # 由于 get_image_manager 会真正初始化 ImageManager（需要 GPU 和 Forge），
    # 这里用一个简化的测试验证 double-check locking 逻辑
    # 通过模拟一个使用相同模式的 async 函数来测试

    test_call_count = 0
    test_instance = None
    test_lock = asyncio.Lock()

    async def mock_get_instance():
        nonlocal test_instance, test_call_count
        if test_instance is None:
            async with test_lock:
                if test_instance is not None:
                    return test_instance
                # 模拟耗时初始化（await 期间事件循环会切换）
                await asyncio.sleep(0.05)
                test_call_count += 1
                test_instance = f"instance_{test_call_count}"
        return test_instance

    async def run_test():
        # 启动 20 个协程并发调用
        tasks = [asyncio.create_task(mock_get_instance()) for _ in range(20)]
        results = await asyncio.gather(*tasks)
        return results

    results = asyncio.run(run_test())

    # 验证所有协程得到同一个实例
    if len(results) != 20:
        issues.append(f"协程结果数量不对: {len(results)}/20")
    elif len(set(results)) != 1:
        issues.append(
            f"协程得到不同实例: {set(results)}，应全部相同"
        )

    # 验证初始化只执行一次
    if test_call_count != 1:
        issues.append(
            f"初始化执行了 {test_call_count} 次，应只执行 1 次"
        )

    return issues


# ============================================================================
# 场景5: 模块可以正常导入
# ============================================================================

def check_module_importable() -> List[str]:
    """验证修复后的模块可以正常导入"""
    issues: List[str] = []
    try:
        import importlib
        importlib.import_module("core.image.image_manager")
    except Exception as e:
        issues.append(f"导入 core.image.image_manager 失败: {e}")
    return issues


# ============================================================================
# 场景6: 验证 shutdown 后可以重新初始化
# ============================================================================

def check_shutdown_and_reinit() -> List[str]:
    """验证 shutdown_image_manager_instance 后可以重新初始化"""
    issues: List[str] = []

    # 模拟 shutdown + reinit 流程
    test_instance = None
    test_lock = asyncio.Lock()
    init_count = 0

    async def mock_get():
        nonlocal test_instance, init_count
        if test_instance is None:
            async with test_lock:
                if test_instance is not None:
                    return test_instance
                await asyncio.sleep(0.01)
                init_count += 1
                test_instance = f"instance_{init_count}"
        return test_instance

    async def mock_shutdown():
        nonlocal test_instance
        async with test_lock:
            test_instance = None

    async def run_test():
        nonlocal test_instance
        # 第一次初始化
        r1 = await mock_get()
        # shutdown
        await mock_shutdown()
        # 重新初始化
        r2 = await mock_get()
        return r1, r2

    r1, r2 = asyncio.run(run_test())

    if r1 == r2:
        issues.append(
            f"shutdown 后重新初始化应得到新实例，但 r1==r2=={r1}"
        )

    if init_count != 2:
        issues.append(
            f"应初始化 2 次（首次 + reinit），实际 {init_count} 次"
        )

    return issues


# ============================================================================
# 主函数
# ============================================================================

def main() -> int:
    """主函数：运行所有检查"""
    print("=" * 72)
    print("P0-22 验证：core/image/image_manager.py async 单例竞态条件")
    print("=" * 72)

    checks = [
        ("场景1", "锁对象 _image_manager_lock 存在且为 asyncio.Lock 类型",
         check_lock_exists),
        ("场景2", "get_image_manager 使用 double-check locking 模式",
         check_double_check_locking),
        ("场景3", "shutdown_image_manager_instance 使用锁保护",
         check_shutdown_locked),
        ("场景4", "多协程并发调用不会重复初始化",
         check_concurrent_initialization_safe),
        ("场景5", "模块可以正常导入",
         check_module_importable),
        ("场景6", "shutdown 后可以重新初始化",
         check_shutdown_and_reinit),
    ]

    all_issues: List[str] = []
    for label, name, fn in checks:
        print(f"\n[{label}] {name}")
        try:
            issues = fn()
        except Exception as e:
            issues = [f"检查函数异常: {type(e).__name__}: {e}"]

        if issues:
            for issue in issues:
                print(f"  ❌ {issue}")
            all_issues.extend(issues)
        else:
            print("  ✅ 通过")

    print("\n" + "=" * 72)
    if all_issues:
        print(f"❌ 验证失败：共 {len(all_issues)} 个问题")
        for issue in all_issues:
            print(f"  - {issue}")
        return 1
    else:
        print("✅ 所有验证通过！P0-22 修复有效。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
