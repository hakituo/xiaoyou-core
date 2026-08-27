"""P2-6 验证：DriftGuard 重构（async + 缓存）

验证要点：
1. DriftGuard 类存在 verify_memory_async 异步入口
2. 函数名索引缓存生效（二次调用不再全量扫描）
3. invalidate_cache 能清空缓存
4. 同步 verify_memory 仍可正常工作
5. 文件存在性、配置值缓存生效
6. service.py 暴露 verify_memory_async / invalidate_drift_cache
"""
from __future__ import annotations

import asyncio
import inspect
import sys
import time
from pathlib import Path

# 复用项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 把项目根目录加入 sys.path，确保可以 import core
sys.path.insert(0, str(PROJECT_ROOT))


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def test_async_methods_exist() -> list[str]:
    issues: list[str] = []
    _section("测试 1：DriftGuard 提供 async 入口")

    from core.services.self_improvement.drift_guard import DriftGuard

    if not inspect.iscoroutinefunction(DriftGuard.verify_memory_async):
        issues.append("DriftGuard.verify_memory_async 不是协程函数")
    else:
        _ok("verify_memory_async 是协程函数")

    if not inspect.iscoroutinefunction(DriftGuard.verify_single_async):
        issues.append("DriftGuard.verify_single_async 不是协程函数")
    else:
        _ok("verify_single_async 是协程函数")

    if not hasattr(DriftGuard, "invalidate_cache"):
        issues.append("DriftGuard 缺少 invalidate_cache 方法")
    else:
        _ok("invalidate_cache 方法存在")

    if not issues:
        _ok("所有 async 入口与缓存管理方法齐全")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_function_index_cache() -> list[str]:
    issues: list[str] = []
    _section("测试 2：函数名索引缓存生效（二次调用不再全量扫描）")

    from core.services.self_improvement.drift_guard import DriftGuard

    dg = DriftGuard(PROJECT_ROOT)

    t0 = time.time()
    index1 = dg._ensure_function_index()
    t1 = time.time()
    first_duration = t1 - t0

    if not index1:
        issues.append("首次构建索引返回空集合")
    else:
        _ok(f"首次构建索引成功，包含 {len(index1)} 个函数名，耗时 {first_duration:.3f}s")

    t2 = time.time()
    index2 = dg._ensure_function_index()
    t3 = time.time()
    second_duration = t3 - t2

    if index1 is index2:
        _ok(f"二次调用命中缓存（同一对象），耗时 {second_duration:.6f}s")
    elif second_duration > 0.001:
        issues.append(
            f"二次调用未命中缓存，耗时 {second_duration:.6f}s（应 < 0.001s）"
        )
    else:
        _ok(f"二次调用命中缓存，耗时 {second_duration:.6f}s")

    dg.invalidate_cache()
    if dg._function_index is not None:
        issues.append("invalidate_cache 后 _function_index 未清空")
    else:
        _ok("invalidate_cache 成功清空索引缓存")

    index3 = dg._ensure_function_index()
    if not index3:
        issues.append("invalidate_cache 后重新构建索引返回空集合")
    else:
        _ok(f"invalidate_cache 后重新构建成功，包含 {len(index3)} 个函数名")

    if not issues:
        _ok("函数名索引缓存机制工作正常")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_file_existence_cache() -> list[str]:
    issues: list[str] = []
    _section("测试 3：文件存在性缓存生效")

    from core.services.self_improvement.drift_guard import DriftGuard

    dg = DriftGuard(PROJECT_ROOT)

    result1 = dg._verify_single_file_path("core/utils/logger.py")
    if not result1["passed"]:
        issues.append(f"存在的文件被判定为不存在: {result1}")
    else:
        _ok(f"存在的文件正确判定: {result1['content']}")

    result2 = dg._verify_single_file_path("nonexistent/file.py")
    if result2["passed"]:
        issues.append(f"不存在的文件被判定为存在: {result2}")
    else:
        _ok(f"不存在的文件正确判定: {result2['content']}")

    if "core/utils/logger.py" not in dg._file_existence_cache:
        issues.append("文件存在性缓存未写入")
    else:
        cached = dg._file_existence_cache["core/utils/logger.py"]
        _ok(f"缓存已写入: path=core/utils/logger.py, exists={cached[0]}")

    if not issues:
        _ok("文件存在性缓存工作正常")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_sync_verify_memory_compat() -> list[str]:
    issues: list[str] = []
    _section("测试 4：同步 verify_memory 仍可正常工作")

    from core.services.self_improvement.drift_guard import DriftGuard

    dg = DriftGuard(PROJECT_ROOT)

    content = """
    这个功能在 core/utils/logger.py 文件中实现。
    函数：get_logger 用于获取日志记录器。
    配置：debug=True
    """
    result = dg.verify_memory(content)

    if not isinstance(result, dict):
        issues.append(f"返回类型错误: {type(result)}")
    else:
        required_keys = {"valid", "checks", "warnings"}
        if not required_keys.issubset(result.keys()):
            issues.append(f"返回字典缺少必要字段: {result.keys()}")
        else:
            _ok(f"返回结构正确: valid={result['valid']}, checks={len(result['checks'])}")

    func_checks = [c for c in result["checks"] if c["type"] == "function"]
    if not func_checks:
        issues.append("未找到任何函数验证结果")
    else:
        get_logger_found = any(
            "get_logger" in c["content"] and c["passed"] for c in func_checks
        )
        if not get_logger_found:
            issues.append(f"get_logger 函数未被找到: {func_checks}")
        else:
            _ok("get_logger 函数被正确找到")

    if not issues:
        _ok("同步 verify_memory 工作正常")
    else:
        for it in issues:
            _fail(it)
    return issues


async def _test_async_verify_memory() -> list[str]:
    issues: list[str] = []
    _section("测试 5：异步 verify_memory_async 入口工作正常")

    from core.services.self_improvement.drift_guard import DriftGuard

    dg = DriftGuard(PROJECT_ROOT)

    content = "函数：verify_memory 用于验证记忆。"
    result = await dg.verify_memory_async(content)

    if not isinstance(result, dict):
        issues.append(f"异步返回类型错误: {type(result)}")
    else:
        _ok(f"异步入口返回结构正确: valid={result.get('valid')}")

    t0 = time.time()
    await dg.verify_memory_async(content)
    t1 = time.time()
    if (t1 - t0) > 0.5:
        issues.append(f"二次异步调用耗时过长: {t1 - t0:.3f}s（应 < 0.5s，命中缓存）")
    else:
        _ok(f"二次异步调用命中缓存，耗时 {t1 - t0:.3f}s")

    if not issues:
        _ok("异步 verify_memory_async 工作正常")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_async_verify_memory() -> list[str]:
    return asyncio.run(_test_async_verify_memory())


def test_service_layer_exposes_async() -> list[str]:
    issues: list[str] = []
    _section("测试 6：service.py 暴露 verify_memory_async / invalidate_drift_cache")

    from core.services.self_improvement.service import SelfImprovementService

    if not inspect.iscoroutinefunction(SelfImprovementService.verify_memory_async):
        issues.append("SelfImprovementService.verify_memory_async 不是协程函数")
    else:
        _ok("SelfImprovementService.verify_memory_async 是协程函数")

    if not hasattr(SelfImprovementService, "invalidate_drift_cache"):
        issues.append("SelfImprovementService 缺少 invalidate_drift_cache 方法")
    else:
        _ok("SelfImprovementService.invalidate_drift_cache 方法存在")

    if not issues:
        _ok("service 层 async 入口与缓存管理齐全")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_performance_improvement() -> list[str]:
    issues: list[str] = []
    _section("测试 7：性能对比（索引缓存 vs 旧实现全量扫描）")

    from core.services.self_improvement.drift_guard import DriftGuard

    dg = DriftGuard(PROJECT_ROOT)

    content = """
    函数：get_logger
    函数：verify_memory
    函数：invalidate_cache
    函数：nonexistent_function
    """

    t0 = time.time()
    dg.verify_memory(content)
    t1 = time.time()
    first_duration = t1 - t0

    t2 = time.time()
    result2 = dg.verify_memory(content)
    t3 = time.time()
    second_duration = t3 - t2

    _ok(f"首次调用（含索引构建）: {first_duration:.3f}s")
    _ok(f"二次调用（索引命中缓存）: {second_duration:.3f}s")

    if second_duration >= first_duration:
        issues.append(
            f"二次调用未比首次更快: first={first_duration:.3f}s, second={second_duration:.3f}s"
        )
    else:
        speedup = first_duration / max(second_duration, 0.0001)
        _ok(f"加速比: {speedup:.1f}x")

    func_checks = [c for c in result2["checks"] if c["type"] == "function"]
    if len(func_checks) < 4:
        issues.append(f"函数验证结果数量不足: {len(func_checks)}（应 ≥ 4）")

    if not issues:
        _ok("性能对比验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def main() -> int:
    print("=" * 60)
    print("P2-6 验证：DriftGuard 重构（async + 缓存）")
    print("=" * 60)

    all_issues: list[str] = []
    for test_fn in [
        test_async_methods_exist,
        test_function_index_cache,
        test_file_existence_cache,
        test_sync_verify_memory_compat,
        test_async_verify_memory,
        test_service_layer_exposes_async,
        test_performance_improvement,
    ]:
        try:
            issues = test_fn()
            all_issues.extend(issues)
        except Exception as e:
            all_issues.append(f"{test_fn.__name__} 异常: {e}")
            import traceback

            traceback.print_exc()

    print("\n" + "=" * 60)
    if all_issues:
        print(f"✗ 发现 {len(all_issues)} 个问题:")
        for issue in all_issues:
            print(f"  - {issue}")
        return 1
    else:
        print("✓ 所有测试通过")
        return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
