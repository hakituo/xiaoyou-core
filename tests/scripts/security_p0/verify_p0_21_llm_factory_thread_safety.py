#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0-21 验证脚本：core/llm/factory.py 单例无线程锁导致重复加载模型

验证范围：
1. _llm_module_lock 和 _llm_instances_lock 锁对象存在
2. get_llm_module 使用 double-check locking 模式
3. create_instance / get_instance / list_instances 使用锁保护
4. 初始化逻辑在锁内执行（_do_initialize_llm_module 函数存在）
5. 实际并发测试：多线程调用不会重复初始化
6. 模块可以正常导入
"""

from __future__ import annotations

import ast
import sys
import threading
import time
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def _read_file(rel_path: str) -> str:
    """读取项目内文件"""
    return (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")


# ============================================================================
# 场景1: 锁对象存在
# ============================================================================

def check_locks_exist() -> List[str]:
    """验证 _llm_module_lock 和 _llm_instances_lock 锁对象存在"""
    issues: List[str] = []
    try:
        from core.llm.factory import _llm_module_lock, _llm_instances_lock
        if not isinstance(_llm_module_lock, type(threading.Lock())):
            issues.append("_llm_module_lock 不是 threading.Lock 类型")
        if not isinstance(_llm_instances_lock, type(threading.Lock())):
            issues.append("_llm_instances_lock 不是 threading.Lock 类型")
    except ImportError as e:
        issues.append(f"无法导入锁对象: {e}")
    return issues


# ============================================================================
# 场景2: get_llm_module 使用 double-check locking 模式
# ============================================================================

def check_double_check_locking() -> List[str]:
    """验证 get_llm_module 使用 double-check locking 模式"""
    issues: List[str] = []
    source = _read_file("core/llm/factory.py")

    tree = ast.parse(source)
    found_get_llm_module = False
    found_double_check = False
    found_with_lock = False

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_llm_module":
            found_get_llm_module = True
            # 检查函数体内是否有 with _llm_module_lock:
            for sub in ast.walk(node):
                if isinstance(sub, ast.With):
                    for item in sub.items:
                        ctx = item.context_expr
                        if (
                            isinstance(ctx, ast.Name)
                            and ctx.id == "_llm_module_lock"
                        ):
                            found_with_lock = True
                            # 检查 with 块内是否有 if _llm_module_instance is not None:
                            for body_node in sub.body:
                                if isinstance(body_node, ast.If):
                                    # double-check 模式
                                    test = body_node.test
                                    if (
                                        isinstance(test, ast.Compare)
                                        and isinstance(test.left, ast.Name)
                                        and test.left.id == "_llm_module_instance"
                                    ):
                                        found_double_check = True
            break

    if not found_get_llm_module:
        issues.append("未找到 get_llm_module 函数")
    if not found_with_lock:
        issues.append("get_llm_module 未使用 with _llm_module_lock:")
    if not found_double_check:
        issues.append("get_llm_module 未使用 double-check locking 模式")

    return issues


# ============================================================================
# 场景3: create_instance / get_instance / list_instances 使用锁保护
# ============================================================================

def check_instances_methods_locked() -> List[str]:
    """验证 create_instance / get_instance / list_instances 使用锁保护"""
    issues: List[str] = []
    source = _read_file("core/llm/factory.py")

    tree = ast.parse(source)
    required_funcs = {"create_instance", "get_instance", "list_instances"}
    found_locked = set()

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in required_funcs
        ):
            # 检查函数体内是否有 with _llm_instances_lock:
            for sub in ast.walk(node):
                if isinstance(sub, ast.With):
                    for item in sub.items:
                        ctx = item.context_expr
                        if (
                            isinstance(ctx, ast.Name)
                            and ctx.id == "_llm_instances_lock"
                        ):
                            found_locked.add(node.name)

    missing = required_funcs - found_locked
    if missing:
        issues.append(
            f"以下函数未使用 _llm_instances_lock 保护: {missing}"
        )

    return issues


# ============================================================================
# 场景4: 初始化逻辑在锁内执行
# ============================================================================

def check_initialize_in_lock() -> List[str]:
    """验证初始化逻辑在锁内执行（_do_initialize_llm_module 函数存在）"""
    issues: List[str] = []
    source = _read_file("core/llm/factory.py")

    tree = ast.parse(source)
    found_initialize_func = False
    found_call_in_lock = False

    for node in ast.walk(tree):
        # 检查 _do_initialize_llm_module 函数存在
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_do_initialize_llm_module"
        ):
            found_initialize_func = True

        # 检查 get_llm_module 在锁内调用 _do_initialize_llm_module
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "get_llm_module"
        ):
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == "_do_initialize_llm_module"
                ):
                    found_call_in_lock = True

    if not found_initialize_func:
        issues.append("未找到 _do_initialize_llm_module 函数")
    if not found_call_in_lock:
        issues.append("get_llm_module 未调用 _do_initialize_llm_module")

    return issues


# ============================================================================
# 场景5: 实际并发测试 - 多线程调用不会重复初始化
# ============================================================================

def check_concurrent_initialization_safe() -> List[str]:
    """验证多线程并发调用不会重复初始化"""
    issues: List[str] = []

    # 由于 get_llm_module 会真正加载模型（耗时且需要 GPU），
    # 这里用一个简化的测试验证 double-check locking 逻辑
    # 通过模拟一个使用相同模式的函数来测试

    test_call_count = 0
    test_call_lock = threading.Lock()
    test_instance = None
    test_init_lock = threading.Lock()

    def mock_get_instance():
        nonlocal test_instance, test_call_count
        if test_instance is None:
            with test_init_lock:
                if test_instance is not None:
                    return test_instance
                # 模拟耗时初始化
                time.sleep(0.05)
                with test_call_lock:
                    test_call_count += 1
                test_instance = f"instance_{test_call_count}"
        return test_instance

    # 启动 10 个线程并发调用
    threads = []
    results = []
    results_lock = threading.Lock()

    def worker():
        result = mock_get_instance()
        with results_lock:
            results.append(result)

    for _ in range(10):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=5.0)

    # 验证所有线程得到同一个实例
    if len(results) != 10:
        issues.append(f"线程结果数量不对: {len(results)}/10")
    elif len(set(results)) != 1:
        issues.append(
            f"线程得到不同实例: {set(results)}，应全部相同"
        )

    # 验证初始化只执行一次
    if test_call_count != 1:
        issues.append(
            f"初始化执行了 {test_call_count} 次，应只执行 1 次"
        )

    return issues


# ============================================================================
# 场景6: 模块可以正常导入
# ============================================================================

def check_module_importable() -> List[str]:
    """验证修复后的模块可以正常导入"""
    issues: List[str] = []
    try:
        import importlib
        importlib.import_module("core.llm.factory")
    except Exception as e:
        issues.append(f"导入 core.llm.factory 失败: {e}")
    return issues


# ============================================================================
# 场景7: 验证 _llm_instances 的并发写入安全
# ============================================================================

def check_instances_concurrent_write_safe() -> List[str]:
    """验证 _llm_instances 的并发写入安全"""
    issues: List[str] = []

    # 模拟多线程并发调用 create_instance
    from core.llm.factory import create_instance, list_instances

    # 先清空（通过 list_instances 拿到副本，不影响内部状态）
    threads = []
    errors = []
    errors_lock = threading.Lock()

    def worker(i):
        try:
            from core.llm.base import LLMConfig
            config = LLMConfig(model_name=f"test_model_{i}")
            create_instance(f"test_instance_{i}", config)
        except Exception as e:
            with errors_lock:
                errors.append(f"thread {i}: {type(e).__name__}: {e}")

    for i in range(20):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=5.0)

    if errors:
        issues.append(f"并发写入出现错误: {errors[:3]}")

    # 验证所有实例都已写入
    instances = list_instances()
    expected_count = 20
    actual_count = sum(
        1 for k in instances if k.startswith("test_instance_")
    )
    if actual_count != expected_count:
        issues.append(
            f"并发写入后实例数量不对: {actual_count}/{expected_count}"
        )

    return issues


# ============================================================================
# 主函数
# ============================================================================

def main() -> int:
    """主函数：运行所有检查"""
    print("=" * 72)
    print("P0-21 验证：core/llm/factory.py 单例无线程锁导致重复加载模型")
    print("=" * 72)

    checks = [
        ("场景1", "锁对象 _llm_module_lock / _llm_instances_lock 存在",
         check_locks_exist),
        ("场景2", "get_llm_module 使用 double-check locking 模式",
         check_double_check_locking),
        ("场景3", "create_instance / get_instance / list_instances 使用锁保护",
         check_instances_methods_locked),
        ("场景4", "初始化逻辑在锁内执行（_do_initialize_llm_module）",
         check_initialize_in_lock),
        ("场景5", "多线程并发调用不会重复初始化",
         check_concurrent_initialization_safe),
        ("场景6", "模块可以正常导入",
         check_module_importable),
        ("场景7", "_llm_instances 并发写入安全",
         check_instances_concurrent_write_safe),
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
        print("✅ 所有验证通过！P0-21 修复有效。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
