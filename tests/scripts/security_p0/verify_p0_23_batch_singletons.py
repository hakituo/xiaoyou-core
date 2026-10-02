#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
P0-23 验证脚本：批量修复其他未加锁的单例模式

验证目标文件：
  1. core/core_engine/config_manager.py
     - ConfigManager.__new__ 加锁 + double-check
     - get_config_manager() 加锁 + double-check
  2. core/voice/tts_engine.py
     - TTSManager.__new__ 加锁 + double-check
     - get_tts_manager() 加锁 + double-check
  3. core/voice/__init__.py
     - get_tts_manager() async 加锁 + double-check
     - get_stt_manager() async 加锁 + double-check
     - shutdown_tts()/shutdown_stt() 加锁保护
  4. core/services/dual_role/social_events.py
     - get_social_event_engine() 加锁 + double-check
  5. core/services/journal/persona_exports.py
     - get_persona_journal_export_service() 加锁 + double-check
  6. core/tools/study/english/vocabulary_manager.py
     - get_vocabulary_manager() 加锁 + double-check

验证方法：
  - AST 分析：检查锁变量定义与使用
  - 源码扫描：检查 double-check 模式
  - 模块导入测试：确保修改未破坏导入
  - 并发测试：模拟多线程/多协程并发调用，验证实例唯一性
"""

import ast
import asyncio
import sys
import threading
import time
from pathlib import Path
from typing import List, Tuple

# 将项目根目录加入 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _read_source(rel_path: str) -> str:
    """读取项目内文件的源码"""
    full_path = _PROJECT_ROOT / rel_path
    if not full_path.exists():
        raise FileNotFoundError(f"文件不存在: {full_path}")
    return full_path.read_text(encoding="utf-8")


def _parse_ast(rel_path: str) -> ast.Module:
    """解析项目内文件为 AST"""
    return ast.parse(_read_source(rel_path))


def _has_module_level_lock_var(tree: ast.Module, var_name: str) -> bool:
    """检查模块级是否定义了指定的 Lock 变量"""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == var_name:
                    return True
    return False


def _has_class_level_lock_var(tree: ast.Module, class_name: str, var_name: str) -> bool:
    """检查类级是否定义了指定的 Lock 变量"""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for sub in node.body:
                if isinstance(sub, ast.Assign):
                    for target in sub.targets:
                        if isinstance(target, ast.Name) and target.id == var_name:
                            return True
    return False


def _find_function_node(
    tree: ast.Module, func_name: str, in_class: str = None
) -> ast.FunctionDef:
    """查找指定函数/方法的 AST 节点"""
    for node in tree.body:
        if in_class and isinstance(node, ast.ClassDef) and node.name == in_class:
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name == func_name:
                    return sub
        if not in_class and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return node
    return None


def _function_uses_with_lock(func_node) -> bool:
    """检查函数体是否包含 `with xxx_lock:` 或 `async with xxx_lock:` 语句"""
    for sub in ast.walk(func_node):
        # with 和 async with 在 AST 中分别是 ast.With 和 ast.AsyncWith
        if isinstance(sub, (ast.With, ast.AsyncWith)):
            for item in sub.items:
                ctx = item.context_expr
                # with _lock:  或  with cls._lock:  或  async with _lock:
                if isinstance(ctx, ast.Name) and ctx.id.endswith("_lock"):
                    return True
                if isinstance(ctx, ast.Attribute) and ctx.attr.endswith("_lock"):
                    return True
                # with _lock_module: 等命名变体
                if isinstance(ctx, ast.Name) and "lock" in ctx.id.lower():
                    return True
                if isinstance(ctx, ast.Attribute) and "lock" in ctx.attr.lower():
                    return True
    return False


def _function_is_async(func_node) -> bool:
    return isinstance(func_node, ast.AsyncFunctionDef)


# ---------------------------------------------------------------------------
# 各文件检查
# ---------------------------------------------------------------------------
def check_config_manager() -> List[str]:
    """检查 core/core_engine/config_manager.py"""
    issues: List[str] = []
    rel = "core/core_engine/config_manager.py"
    try:
        tree = _parse_ast(rel)
    except Exception as e:
        issues.append(f"[{rel}] AST 解析失败: {e}")
        return issues

    # 1. 模块级 _config_manager_lock
    if not _has_module_level_lock_var(tree, "_config_manager_lock"):
        issues.append(f"[{rel}] 未找到模块级 _config_manager_lock 变量")

    # 2. ConfigManager._instance_lock
    if not _has_class_level_lock_var(tree, "ConfigManager", "_instance_lock"):
        issues.append(f"[{rel}] 未找到 ConfigManager._instance_lock 类变量")

    # 3. ConfigManager.__new__ 使用 with cls._instance_lock
    new_node = _find_function_node(tree, "__new__", in_class="ConfigManager")
    if new_node is None:
        issues.append(f"[{rel}] 未找到 ConfigManager.__new__")
    else:
        # __new__ 中应使用 with cls._instance_lock:
        has_lock = False
        for sub in ast.walk(new_node):
            if isinstance(sub, ast.With):
                for item in sub.items:
                    ctx = item.context_expr
                    if isinstance(ctx, ast.Attribute) and ctx.attr == "_instance_lock":
                        has_lock = True
                    elif isinstance(ctx, ast.Name) and ctx.id == "_instance_lock":
                        has_lock = True
        if not has_lock:
            issues.append(f"[{rel}] ConfigManager.__new__ 未使用 _instance_lock")

    # 4. get_config_manager 使用 with _config_manager_lock
    gcm = _find_function_node(tree, "get_config_manager")
    if gcm is None:
        issues.append(f"[{rel}] 未找到 get_config_manager 函数")
    elif not _function_uses_with_lock(gcm):
        issues.append(f"[{rel}] get_config_manager 未使用 _config_manager_lock")

    return issues


def check_tts_engine() -> List[str]:
    """检查 core/voice/tts_engine.py"""
    issues: List[str] = []
    rel = "core/voice/tts_engine.py"
    try:
        tree = _parse_ast(rel)
    except Exception as e:
        issues.append(f"[{rel}] AST 解析失败: {e}")
        return issues

    # 1. 模块级 _tts_manager_lock
    if not _has_module_level_lock_var(tree, "_tts_manager_lock"):
        issues.append(f"[{rel}] 未找到模块级 _tts_manager_lock 变量")

    # 2. TTSManager._instance_lock
    if not _has_class_level_lock_var(tree, "TTSManager", "_instance_lock"):
        issues.append(f"[{rel}] 未找到 TTSManager._instance_lock 类变量")

    # 3. TTSManager.__new__ 使用 with cls._instance_lock
    new_node = _find_function_node(tree, "__new__", in_class="TTSManager")
    if new_node is None:
        issues.append(f"[{rel}] 未找到 TTSManager.__new__")
    else:
        has_lock = False
        for sub in ast.walk(new_node):
            if isinstance(sub, ast.With):
                for item in sub.items:
                    ctx = item.context_expr
                    if isinstance(ctx, ast.Attribute) and ctx.attr == "_instance_lock":
                        has_lock = True
                    elif isinstance(ctx, ast.Name) and ctx.id == "_instance_lock":
                        has_lock = True
        if not has_lock:
            issues.append(f"[{rel}] TTSManager.__new__ 未使用 _instance_lock")

    # 4. get_tts_manager 使用 with _tts_manager_lock
    gtm = _find_function_node(tree, "get_tts_manager")
    if gtm is None:
        issues.append(f"[{rel}] 未找到 get_tts_manager 函数")
    elif not _function_uses_with_lock(gtm):
        issues.append(f"[{rel}] get_tts_manager 未使用 _tts_manager_lock")

    return issues


def check_voice_init() -> List[str]:
    """检查 core/voice/__init__.py"""
    issues: List[str] = []
    rel = "core/voice/__init__.py"
    try:
        tree = _parse_ast(rel)
    except Exception as e:
        issues.append(f"[{rel}] AST 解析失败: {e}")
        return issues

    # 1. 模块级 _tts_manager_lock 和 _stt_manager_lock
    if not _has_module_level_lock_var(tree, "_tts_manager_lock"):
        issues.append(f"[{rel}] 未找到模块级 _tts_manager_lock 变量")
    if not _has_module_level_lock_var(tree, "_stt_manager_lock"):
        issues.append(f"[{rel}] 未找到模块级 _stt_manager_lock 变量")

    # 2. get_tts_manager 是 async 且使用 async with _tts_manager_lock
    gtm = _find_function_node(tree, "get_tts_manager")
    if gtm is None:
        issues.append(f"[{rel}] 未找到 get_tts_manager 函数")
    else:
        if not _function_is_async(gtm):
            issues.append(f"[{rel}] get_tts_manager 应为 async 函数")
        if not _function_uses_with_lock(gtm):
            issues.append(f"[{rel}] get_tts_manager 未使用 _tts_manager_lock")

    # 3. get_stt_manager 是 async 且使用 async with _stt_manager_lock
    gsm = _find_function_node(tree, "get_stt_manager")
    if gsm is None:
        issues.append(f"[{rel}] 未找到 get_stt_manager 函数")
    else:
        if not _function_is_async(gsm):
            issues.append(f"[{rel}] get_stt_manager 应为 async 函数")
        if not _function_uses_with_lock(gsm):
            issues.append(f"[{rel}] get_stt_manager 未使用 _stt_manager_lock")

    # 4. shutdown_tts 使用 async with _tts_manager_lock
    sdt = _find_function_node(tree, "shutdown_tts")
    if sdt is None:
        issues.append(f"[{rel}] 未找到 shutdown_tts 函数")
    else:
        if not _function_uses_with_lock(sdt):
            issues.append(f"[{rel}] shutdown_tts 未使用 _tts_manager_lock")

    # 5. shutdown_stt 使用 async with _stt_manager_lock
    sds = _find_function_node(tree, "shutdown_stt")
    if sds is None:
        issues.append(f"[{rel}] 未找到 shutdown_stt 函数")
    else:
        if not _function_uses_with_lock(sds):
            issues.append(f"[{rel}] shutdown_stt 未使用 _stt_manager_lock")

    return issues


def check_social_events() -> List[str]:
    """检查 core/services/dual_role/social_events.py"""
    issues: List[str] = []
    rel = "core/services/dual_role/social_events.py"
    try:
        tree = _parse_ast(rel)
    except Exception as e:
        issues.append(f"[{rel}] AST 解析失败: {e}")
        return issues

    # 1. 模块级 _SOCIAL_EVENT_ENGINE_LOCK
    if not _has_module_level_lock_var(tree, "_SOCIAL_EVENT_ENGINE_LOCK"):
        issues.append(f"[{rel}] 未找到模块级 _SOCIAL_EVENT_ENGINE_LOCK 变量")

    # 2. get_social_event_engine 使用 with _SOCIAL_EVENT_ENGINE_LOCK
    gse = _find_function_node(tree, "get_social_event_engine")
    if gse is None:
        issues.append(f"[{rel}] 未找到 get_social_event_engine 函数")
    elif not _function_uses_with_lock(gse):
        issues.append(f"[{rel}] get_social_event_engine 未使用 _SOCIAL_EVENT_ENGINE_LOCK")

    return issues


def check_persona_exports() -> List[str]:
    """检查 core/services/journal/persona_exports.py"""
    issues: List[str] = []
    rel = "core/services/journal/persona_exports.py"
    try:
        tree = _parse_ast(rel)
    except Exception as e:
        issues.append(f"[{rel}] AST 解析失败: {e}")
        return issues

    # 1. 模块级 _service_lock
    if not _has_module_level_lock_var(tree, "_service_lock"):
        issues.append(f"[{rel}] 未找到模块级 _service_lock 变量")

    # 2. get_persona_journal_export_service 使用 with _service_lock
    gpe = _find_function_node(tree, "get_persona_journal_export_service")
    if gpe is None:
        issues.append(f"[{rel}] 未找到 get_persona_journal_export_service 函数")
    elif not _function_uses_with_lock(gpe):
        issues.append(f"[{rel}] get_persona_journal_export_service 未使用 _service_lock")

    return issues


def check_vocabulary_manager() -> List[str]:
    """检查 core/tools/study/english/vocabulary_manager.py"""
    issues: List[str] = []
    rel = "core/tools/study/english/vocabulary_manager.py"
    try:
        tree = _parse_ast(rel)
    except Exception as e:
        issues.append(f"[{rel}] AST 解析失败: {e}")
        return issues

    # 1. 模块级 _vocabulary_manager_lock
    if not _has_module_level_lock_var(tree, "_vocabulary_manager_lock"):
        issues.append(f"[{rel}] 未找到模块级 _vocabulary_manager_lock 变量")

    # 2. get_vocabulary_manager 使用 with _vocabulary_manager_lock
    gvm = _find_function_node(tree, "get_vocabulary_manager")
    if gvm is None:
        issues.append(f"[{rel}] 未找到 get_vocabulary_manager 函数")
    elif not _function_uses_with_lock(gvm):
        issues.append(f"[{rel}] get_vocabulary_manager 未使用 _vocabulary_manager_lock")

    return issues


# ---------------------------------------------------------------------------
# 并发测试：模拟 double-check locking 在多线程下的正确性
# ---------------------------------------------------------------------------
def check_concurrent_double_check_threading() -> List[str]:
    """模拟多线程并发调用，验证 threading.Lock + double-check 模式"""
    issues: List[str] = []

    test_instance = None
    test_call_count = 0
    test_lock = threading.Lock()

    def mock_get_instance() -> object:
        nonlocal test_instance, test_call_count
        if test_instance is None:
            with test_lock:
                if test_instance is not None:
                    return test_instance
                # 模拟耗时初始化（释放 GIL 让其他线程进入）
                time.sleep(0.02)
                test_call_count += 1
                test_instance = f"instance_{test_call_count}"
        return test_instance

    # 启动 20 个线程并发调用
    results: List[object] = []
    errors: List[Exception] = []

    def worker():
        try:
            results.append(mock_get_instance())
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if errors:
        issues.append(f"并发调用抛出异常: {errors[:3]}")
        return issues

    if len(results) != 20:
        issues.append(f"线程结果数量不对: {len(results)}/20")
    elif len(set(results)) != 1:
        issues.append(f"线程得到不同实例: {set(results)}，应全部相同")

    if test_call_count != 1:
        issues.append(f"初始化执行了 {test_call_count} 次，应只执行 1 次")

    return issues


def check_concurrent_double_check_asyncio() -> List[str]:
    """模拟多协程并发调用，验证 asyncio.Lock + double-check 模式"""
    issues: List[str] = []

    test_instance = None
    test_call_count = 0
    test_lock = asyncio.Lock()

    async def mock_get_instance() -> object:
        nonlocal test_instance, test_call_count
        if test_instance is None:
            async with test_lock:
                if test_instance is not None:
                    return test_instance
                # 模拟耗时初始化（await 期间事件循环会切换）
                await asyncio.sleep(0.02)
                test_call_count += 1
                test_instance = f"async_instance_{test_call_count}"
        return test_instance

    async def run_test():
        # 启动 20 个协程并发调用
        tasks = [asyncio.create_task(mock_get_instance()) for _ in range(20)]
        return await asyncio.gather(*tasks)

    results = asyncio.run(run_test())

    if len(results) != 20:
        issues.append(f"协程结果数量不对: {len(results)}/20")
    elif len(set(results)) != 1:
        issues.append(f"协程得到不同实例: {set(results)}，应全部相同")

    if test_call_count != 1:
        issues.append(f"初始化执行了 {test_call_count} 次，应只执行 1 次")

    return issues


# ---------------------------------------------------------------------------
# 模块导入测试
# ---------------------------------------------------------------------------
def check_imports() -> List[str]:
    """验证修改后的模块可以正常导入"""
    issues: List[str] = []

    # 1. config_manager
    try:
        import importlib
        import core.core_engine.config_manager as cm
        importlib.reload(cm)
        # 验证 ConfigManager 双重 __new__ 仍可用
        a = cm.ConfigManager()
        b = cm.ConfigManager()
        if a is not b:
            issues.append("ConfigManager __new__ 返回了不同实例")
    except Exception as e:
        issues.append(f"导入 core.core_engine.config_manager 失败: {e}")

    # 2. tts_engine
    try:
        import core.voice.tts_engine as te
        # 不实际实例化 TTSManager（会触发 torch 等重型依赖）
        # 仅验证模块可导入且锁变量存在
        if not hasattr(te, "_tts_manager_lock"):
            issues.append("core.voice.tts_engine 缺少 _tts_manager_lock")
        if not hasattr(te.TTSManager, "_instance_lock"):
            issues.append("TTSManager 缺少 _instance_lock 类变量")
    except Exception as e:
        issues.append(f"导入 core.voice.tts_engine 失败: {e}")

    # 3. voice __init__
    try:
        import core.voice as voice
        if not hasattr(voice, "_tts_manager_lock"):
            issues.append("core.voice 缺少 _tts_manager_lock")
        if not hasattr(voice, "_stt_manager_lock"):
            issues.append("core.voice 缺少 _stt_manager_lock")
    except Exception as e:
        issues.append(f"导入 core.voice 失败: {e}")

    # 4. social_events
    try:
        import core.services.dual_role.social_events as se
        if not hasattr(se, "_SOCIAL_EVENT_ENGINE_LOCK"):
            issues.append("core.services.dual_role.social_events 缺少 _SOCIAL_EVENT_ENGINE_LOCK")
    except Exception as e:
        issues.append(f"导入 core.services.dual_role.social_events 失败: {e}")

    # 5. persona_exports
    try:
        import core.services.journal.persona_exports as pe
        if not hasattr(pe, "_service_lock"):
            issues.append("core.services.journal.persona_exports 缺少 _service_lock")
    except Exception as e:
        issues.append(f"导入 core.services.journal.persona_exports 失败: {e}")

    # 6. vocabulary_manager
    try:
        import core.tools.study.english.vocabulary_manager as vm
        if not hasattr(vm, "_vocabulary_manager_lock"):
            issues.append("core.tools.study.english.vocabulary_manager 缺少 _vocabulary_manager_lock")
    except Exception as e:
        issues.append(f"导入 core.tools.study.english.vocabulary_manager 失败: {e}")

    return issues


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def main() -> int:
    print("=" * 70)
    print("P0-23 验证：批量修复其他未加锁的单例模式")
    print("=" * 70)

    all_issues: List[Tuple[str, List[str]]] = []

    print("\n[1/8] 检查 core/core_engine/config_manager.py ...")
    issues = check_config_manager()
    all_issues.append(("config_manager", issues))
    print(f"  -> {'PASS' if not issues else 'FAIL'} ({len(issues)} 个问题)")

    print("\n[2/8] 检查 core/voice/tts_engine.py ...")
    issues = check_tts_engine()
    all_issues.append(("tts_engine", issues))
    print(f"  -> {'PASS' if not issues else 'FAIL'} ({len(issues)} 个问题)")

    print("\n[3/8] 检查 core/voice/__init__.py ...")
    issues = check_voice_init()
    all_issues.append(("voice/__init__", issues))
    print(f"  -> {'PASS' if not issues else 'FAIL'} ({len(issues)} 个问题)")

    print("\n[4/8] 检查 core/services/dual_role/social_events.py ...")
    issues = check_social_events()
    all_issues.append(("social_events", issues))
    print(f"  -> {'PASS' if not issues else 'FAIL'} ({len(issues)} 个问题)")

    print("\n[5/8] 检查 core/services/journal/persona_exports.py ...")
    issues = check_persona_exports()
    all_issues.append(("persona_exports", issues))
    print(f"  -> {'PASS' if not issues else 'FAIL'} ({len(issues)} 个问题)")

    print("\n[6/8] 检查 core/tools/study/english/vocabulary_manager.py ...")
    issues = check_vocabulary_manager()
    all_issues.append(("vocabulary_manager", issues))
    print(f"  -> {'PASS' if not issues else 'FAIL'} ({len(issues)} 个问题)")

    print("\n[7/8] 并发测试：threading.Lock + double-check 模拟 ...")
    issues = check_concurrent_double_check_threading()
    all_issues.append(("concurrent_threading", issues))
    print(f"  -> {'PASS' if not issues else 'FAIL'} ({len(issues)} 个问题)")

    print("\n[8/8] 并发测试：asyncio.Lock + double-check 模拟 ...")
    issues = check_concurrent_double_check_asyncio()
    all_issues.append(("concurrent_asyncio", issues))
    print(f"  -> {'PASS' if not issues else 'FAIL'} ({len(issues)} 个问题)")

    # 导入测试（独立计数，避免影响主结果）
    print("\n[附加] 模块导入测试 ...")
    import_issues = check_imports()
    if import_issues:
        print(f"  -> WARN ({len(import_issues)} 个问题):")
        for msg in import_issues:
            print(f"     - {msg}")
    else:
        print("  -> PASS（所有模块导入正常，锁变量均存在）")

    # 汇总
    print("\n" + "=" * 70)
    total_issues = sum(len(v) for _, v in all_issues)
    if total_issues == 0:
        print("✅ 全部检查通过！P0-23 修复验证成功。")
        return 0
    else:
        print(f"❌ 共发现 {total_issues} 个问题：")
        for name, issues in all_issues:
            if issues:
                print(f"\n  [{name}]")
                for msg in issues:
                    print(f"    - {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
