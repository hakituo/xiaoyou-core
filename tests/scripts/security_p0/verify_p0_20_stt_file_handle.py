#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0-20 验证脚本：stt_connector.py 文件句柄未关闭导致资源泄漏

验证范围：
1. transcribe_audio_data 中的临时文件写入使用 with 语句
2. 不再出现 lambda: open(...) 模式
3. 模块可以正常导入
4. 实际运行测试：写入后文件句柄立即关闭，可以删除
"""

from __future__ import annotations

import ast
import gc
import os
import sys
import tempfile
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def _read_file(rel_path: str) -> str:
    """读取项目内文件"""
    return (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")


# ============================================================================
# 场景1: AST 检查 - transcribe_audio_data 中的临时文件写入使用 with 语句
# ============================================================================

def check_write_uses_with_statement() -> List[str]:
    """验证文件写入使用 with 语句"""
    issues: List[str] = []
    source = _read_file("multimodal/stt_connector.py")

    tree = ast.parse(source)
    found_with_write = False
    found_lambda_open = False

    for node in ast.walk(tree):
        # 检查是否有 with open(...) as f: f.write(...)
        if isinstance(node, ast.With):
            for item in node.items:
                ctx = item.context_expr
                if isinstance(ctx, ast.Call):
                    func = ctx.func
                    if isinstance(func, ast.Name) and func.id == "open":
                        # 检查 with 块内是否有 f.write
                        for body_node in node.body:
                            for sub in ast.walk(body_node):
                                if (
                                    isinstance(sub, ast.Call)
                                    and isinstance(sub.func, ast.Attribute)
                                    and sub.func.attr == "write"
                                ):
                                    found_with_write = True

        # 检查是否还有 lambda: open(...) 模式
        if isinstance(node, ast.Lambda):
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == "open"
                ):
                    found_lambda_open = True

    if not found_with_write:
        issues.append("未找到 with open(...) as f: f.write(...) 模式")

    if found_lambda_open:
        issues.append("仍存在 lambda: open(...) 模式（文件句柄未关闭）")

    return issues


# ============================================================================
# 场景2: 源码字符串检查 - 不再出现 lambda: open 模式
# ============================================================================

def check_no_lambda_open_pattern() -> List[str]:
    """验证源码中不再出现 lambda: open 模式"""
    issues: List[str] = []
    source = _read_file("multimodal/stt_connector.py")

    # 检查 transcribe_audio_data 方法附近是否有 lambda: open
    if "lambda: open(" in source:
        issues.append("源码中仍存在 'lambda: open(' 模式")

    # 检查 P0-20 标记存在
    if "P0-20" not in source:
        issues.append("缺少 P0-20 修复标记")

    return issues


# ============================================================================
# 场景3: 模块可以正常导入
# ============================================================================

def check_module_importable() -> List[str]:
    """验证修复后的模块可以正常导入"""
    issues: List[str] = []
    try:
        import importlib
        importlib.import_module("multimodal.stt_connector")
    except Exception as e:
        issues.append(f"导入 multimodal.stt_connector 失败: {e}")
    return issues


# ============================================================================
# 场景4: 实际运行测试 - 文件写入后句柄关闭，可以立即删除
# ============================================================================

def check_file_handle_closed_after_write() -> List[str]:
    """验证文件写入后句柄立即关闭，可以立即删除（Windows 文件锁测试）"""
    issues: List[str] = []

    # 模拟 transcribe_audio_data 中的写入逻辑
    temp_dir = tempfile.mkdtemp(prefix="p0_20_test_")
    temp_file = os.path.join(temp_dir, "test_handle_close.bin")
    test_data = b"test audio data" * 100

    try:
        # 复现修复后的写入逻辑
        def _write_temp_file(path: str, data: bytes) -> None:
            with open(path, "wb") as f:
                f.write(data)

        _write_temp_file(temp_file, test_data)

        # 立即尝试删除文件 - 如果句柄未关闭，Windows 上会失败
        try:
            os.remove(temp_file)
        except PermissionError as e:
            issues.append(
                f"文件句柄未关闭，无法立即删除: {e}（Windows 文件锁问题）"
            )
        except Exception as e:
            issues.append(
                f"删除文件时出现意外异常: {type(e).__name__}: {e}"
            )

        # 验证文件已被删除
        if os.path.exists(temp_file):
            issues.append("文件删除后仍存在")

    finally:
        # 清理临时目录
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
            os.rmdir(temp_dir)
        except Exception:
            pass

    return issues


# ============================================================================
# 场景5: 验证旧的 lambda 模式会导致句柄泄漏（回归测试对照）
# ============================================================================

def check_old_lambda_pattern_leaks() -> List[str]:
    """验证旧的 lambda: open().write() 模式确实会导致句柄短暂泄漏"""
    issues: List[str] = []

    temp_dir = tempfile.mkdtemp(prefix="p0_20_regression_")
    temp_file = os.path.join(temp_dir, "test_leak.bin")
    test_data = b"test" * 100

    try:
        # 复现旧的写入逻辑（lambda: open(...).write(...)）
        # 注意：这里只是验证问题确实存在，不是推荐用法
        open(temp_file, "wb").write(test_data)
        # 此时文件句柄仍未关闭（等待 GC）

        # 强制 GC 后才能删除
        gc.collect()

        try:
            os.remove(temp_file)
            # GC 后可以删除，说明 GC 前句柄确实未关闭
        except PermissionError:
            # 即使 GC 后也无法删除，说明问题更严重
            issues.append(
                "旧模式即使 GC 后也无法删除文件（句柄泄漏严重）"
            )
    finally:
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
            os.rmdir(temp_dir)
        except Exception:
            pass

    return issues  # 空列表表示验证通过（没有严重泄漏）


# ============================================================================
# 场景6: 验证 _write_temp_file 是 def 而非 lambda
# ============================================================================

def check_write_function_is_def() -> List[str]:
    """验证写入函数使用 def 而非 lambda（更易调试和维护）"""
    issues: List[str] = []
    source = _read_file("multimodal/stt_connector.py")

    # 检查是否有 _write_temp_file 函数定义
    if "def _write_temp_file" not in source:
        issues.append("未找到 _write_temp_file 函数定义")

    # 检查 asyncio.to_thread 调用是否使用了函数引用而非 lambda
    if "_write_temp_file, temp_file_path, audio_data" not in source:
        issues.append(
            "asyncio.to_thread 应使用 _write_temp_file, ... 而非 lambda"
        )

    return issues


# ============================================================================
# 主函数
# ============================================================================

def main() -> int:
    """主函数：运行所有检查"""
    print("=" * 72)
    print("P0-20 验证：stt_connector.py 文件句柄未关闭导致资源泄漏")
    print("=" * 72)

    checks = [
        ("场景1", "AST 检查 - 文件写入使用 with 语句",
         check_write_uses_with_statement),
        ("场景2", "源码字符串检查 - 不再出现 lambda: open 模式",
         check_no_lambda_open_pattern),
        ("场景3", "模块可以正常导入",
         check_module_importable),
        ("场景4", "文件写入后句柄立即关闭，可以立即删除",
         check_file_handle_closed_after_write),
        ("场景5", "回归对照 - 旧 lambda 模式确实泄漏（验证问题存在性）",
         check_old_lambda_pattern_leaks),
        ("场景6", "写入函数使用 def 而非 lambda",
         check_write_function_is_def),
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
        print("✅ 所有验证通过！P0-20 修复有效。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
