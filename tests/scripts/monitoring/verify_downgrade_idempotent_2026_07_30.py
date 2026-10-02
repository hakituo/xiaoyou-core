"""2026-07-30 降级幂等性修复验证脚本

验证紧急降级错误上报修复（err_fa14c1475137）的三项改动是否生效：
1. resource_monitor.perform_downgrade 幂等控制：同级别重复调用不再重复执行/日志
2. resource_monitor._emergency_downgrade 日志级别 error → warning，避免被 ErrorCollectorHandler 当作 LoggedError 上报
3. resource_monitor._clear_downgrade_markers 恢复时清除降级环境变量标记
4. immune.service._apply_resource_response 紧急/中度分支仅在级别变化时调用 perform_downgrade

运行：
    venv_core\\Scripts\\python tests\\scripts\\monitoring\\verify_downgrade_idempotent_2026_07_30.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ==================== 工具函数 ====================

def _ok(label: str, detail: str = "") -> bool:
    print(f"  [PASS] {label}{(' — ' + detail) if detail else ''}")
    return True


def _fail(label: str, detail: str) -> bool:
    print(f"  [FAIL] {label} — {detail}")
    return False


# ==================== 测试 1：perform_downgrade 幂等性 ====================

def test_perform_downgrade_idempotent() -> bool:
    """验证 perform_downgrade 同级别重复调用只执行一次"""
    print("\n[TEST 1] perform_downgrade 幂等性")
    try:
        from core.services.monitoring.resource_monitor import ResourceMonitor
    except ImportError as e:
        return _fail("导入失败", str(e))

    monitor = ResourceMonitor.__new__(ResourceMonitor)
    # 手动初始化必要字段，避免触发全局 settings / torch 探测
    monitor._applied_downgrade_level = 0
    monitor._downgrade_level = 0
    monitor._last_cleanup_ts = 0.0
    monitor._cleanup_cooldown_seconds = 6.0
    monitor._torch_available = False
    monitor._lock = __import__("threading").RLock()

    call_count = {"emergency": 0, "medium": 0, "light": 0, "clear": 0}

    def fake_emergency():
        call_count["emergency"] += 1
        return True

    def fake_medium():
        call_count["medium"] += 1
        return True

    def fake_light():
        call_count["light"] += 1
        return True

    def fake_clear():
        call_count["clear"] += 1

    monitor._emergency_downgrade = fake_emergency
    monitor._medium_downgrade = fake_medium
    monitor._lightweight_downgrade = fake_light
    monitor._clear_downgrade_markers = fake_clear

    # 第一次调用 level=3 应执行
    if not monitor.perform_downgrade(level=3):
        return _fail("首次 level=3", "返回 False")
    if call_count["emergency"] != 1:
        return _fail("首次 level=3", f"emergency 调用次数={call_count['emergency']}，预期 1")

    # 重复调用 level=3 应跳过
    monitor.perform_downgrade(level=3)
    monitor.perform_downgrade(level=3)
    if call_count["emergency"] != 1:
        return _fail("幂等 level=3", f"emergency 调用次数={call_count['emergency']}，预期仍为 1")

    # 切换到 level=2 应执行
    monitor.perform_downgrade(level=2)
    if call_count["medium"] != 1:
        return _fail("切换 level=2", f"medium 调用次数={call_count['medium']}，预期 1")

    # 重复 level=2 应跳过
    monitor.perform_downgrade(level=2)
    if call_count["medium"] != 1:
        return _fail("幂等 level=2", f"medium 调用次数={call_count['medium']}，预期仍为 1")

    # 恢复 level=0 应清除标记
    monitor.perform_downgrade(level=0)
    if call_count["clear"] != 1:
        return _fail("恢复 level=0", f"clear 调用次数={call_count['clear']}，预期 1")

    # 重复 level=0 应跳过
    monitor.perform_downgrade(level=0)
    if call_count["clear"] != 1:
        return _fail("幂等 level=0", f"clear 调用次数={call_count['clear']}，预期仍为 1")

    return _ok("perform_downgrade 幂等", "各级别重复调用均只执行一次")


# ==================== 测试 2：_emergency_downgrade 日志级别 ====================

def test_emergency_log_level_warning() -> bool:
    """验证 _emergency_downgrade 使用 warning 而非 error，避免被 ErrorCollector 当作 LoggedError"""
    print("\n[TEST 2] _emergency_downgrade 日志级别为 WARNING")
    try:
        from core.services.monitoring.resource_monitor import ResourceMonitor
    except ImportError as e:
        return _fail("导入失败", str(e))

    monitor = ResourceMonitor.__new__(ResourceMonitor)
    monitor._last_cleanup_ts = 0.0
    monitor._cleanup_cooldown_seconds = 6.0
    monitor._torch_available = False
    monitor._lock = __import__("threading").RLock()

    # 清理可能存在的环境变量
    for k in ("SERVICE_DOWNGRADE_LEVEL", "EMERGENCY_MODE"):
        os.environ.pop(k, None)

    # 直接 mock 模块级 logger，验证调用的是 warning 而非 error
    with patch("core.services.monitoring.resource_monitor.logger") as mock_logger:
        monitor._emergency_downgrade()

    # _emergency_downgrade 内部会调用 cleanup_resources，后者也会 warning，所以只检查关键断言：
    # 1. emergency 降级消息以 warning 级别输出
    # 2. 全程没有调用 error（否则会被 ErrorCollectorHandler 当作 LoggedError 上报）
    warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
    assert any("[降级执行] 应用紧急降级措施" in c for c in warning_calls), \
        f"未找到紧急降级 warning 调用: {warning_calls}"
    mock_logger.error.assert_not_called()
    return _ok("日志级别为 WARNING", "logger.warning 输出降级消息，logger.error 未被调用")


# ==================== 测试 3：_clear_downgrade_markers 清除环境变量 ====================

def test_clear_downgrade_markers() -> bool:
    """验证 _clear_downgrade_markers 清除所有降级环境变量"""
    print("\n[TEST 3] _clear_downgrade_markers 清除环境变量")
    try:
        from core.services.monitoring.resource_monitor import ResourceMonitor
    except ImportError as e:
        return _fail("导入失败", str(e))

    monitor = ResourceMonitor.__new__(ResourceMonitor)

    # 设置所有降级标记
    os.environ["SERVICE_DOWNGRADE_LEVEL"] = "4"
    os.environ["MAX_GENERATION_TOKENS"] = "256"
    os.environ["FORCE_QUANTIZATION"] = "4"
    os.environ["DISABLE_BATCH_PROCESSING"] = "1"
    os.environ["EMERGENCY_MODE"] = "1"

    monitor._clear_downgrade_markers()

    leftover = [k for k in (
        "SERVICE_DOWNGRADE_LEVEL", "MAX_GENERATION_TOKENS",
        "FORCE_QUANTIZATION", "DISABLE_BATCH_PROCESSING", "EMERGENCY_MODE",
    ) if k in os.environ]
    if leftover:
        return _fail("环境变量残留", f"未清除: {leftover}")
    return _ok("环境变量已清除", "5 个降级标记全部移除")


# ==================== 测试 4：恢复后环境变量不残留（端到端） ====================

def test_recovery_clears_markers_e2e() -> bool:
    """验证 紧急降级 → 恢复 的完整流程后环境变量被清除"""
    print("\n[TEST 4] 紧急降级→恢复 端到端环境变量")
    try:
        from core.services.monitoring.resource_monitor import ResourceMonitor
    except ImportError as e:
        return _fail("导入失败", str(e))

    monitor = ResourceMonitor.__new__(ResourceMonitor)
    monitor._applied_downgrade_level = 0
    monitor._downgrade_level = 0
    monitor._last_cleanup_ts = 0.0
    monitor._cleanup_cooldown_seconds = 6.0
    monitor._torch_available = False
    monitor._lock = __import__("threading").RLock()

    for k in ("SERVICE_DOWNGRADE_LEVEL", "EMERGENCY_MODE"):
        os.environ.pop(k, None)

    # 触发紧急降级
    monitor.perform_downgrade(level=3)
    if os.environ.get("EMERGENCY_MODE") != "1":
        return _fail("紧急降级", "EMERGENCY_MODE 未设置")
    if os.environ.get("SERVICE_DOWNGRADE_LEVEL") != "4":
        return _fail("紧急降级", "SERVICE_DOWNGRADE_LEVEL 未设置为 4")

    # 恢复
    monitor.perform_downgrade(level=0)
    if "EMERGENCY_MODE" in os.environ:
        return _fail("恢复后残留", "EMERGENCY_MODE 未清除")
    if "SERVICE_DOWNGRADE_LEVEL" in os.environ:
        return _fail("恢复后残留", "SERVICE_DOWNGRADE_LEVEL 未清除")
    return _ok("端到端流程", "降级标记设置后恢复清除正确")


# ==================== 测试 5：immune 服务状态转移检查 ====================

def test_immune_transition_check() -> bool:
    """验证 immune._apply_resource_response 在同级别时不重复调用 perform_downgrade"""
    print("\n[TEST 5] immune 服务状态转移检查")
    try:
        from core.services.immune.service import ImmuneSystemService
    except ImportError as e:
        return _fail("导入失败", str(e))

    svc = ImmuneSystemService.__new__(ImmuneSystemService)
    svc._last_downgrade_level = 0
    svc._errors = __import__("collections").deque(maxlen=5000)
    svc._stats = type("S", (), {
        "resource_emergency_count": 0,
        "resource_medium_count": 0,
    })()

    downgrade_calls = []

    class _FakeMonitor:
        def perform_downgrade(self, level=None):
            downgrade_calls.append(level)
            return True
        def cleanup_resources(self, aggressive=False, emergency=False):
            pass

    class _FakePerf:
        def get_current_metrics(self):
            return {"cpu_usage": 99.5, "memory_usage": 97.0}  # 紧急

    svc._thresholds = type("T", (), {
        "memory_medium": 90.0, "memory_emergency": 96.0,
        "cpu_medium": 95.0, "cpu_emergency": 99.0,
        "error_burst_window": 60.0, "error_burst_threshold": 10,
    })()

    import asyncio

    async def _check_busy():
        return False

    svc._check_scheduler_busy = _check_busy
    # performance_monitor 是 property，需设置底层 _performance_monitor 字段
    svc._performance_monitor = _FakePerf()

    async def _run():
        with patch("core.services.monitoring.resource_monitor.get_resource_monitor", return_value=_FakeMonitor()):
            await svc._apply_resource_response()

    # 第一次 tick：从 level 0 → 3，应调用 perform_downgrade(3)
    asyncio.run(_run())
    if downgrade_calls != [3]:
        return _fail("首次紧急 tick", f"perform_downgrade 调用={downgrade_calls}，预期 [3]")

    # 第二、三次 tick：级别未变，不应再调用 perform_downgrade
    asyncio.run(_run())
    asyncio.run(_run())
    if downgrade_calls != [3]:
        return _fail(
            "重复紧急 tick",
            f"perform_downgrade 调用={downgrade_calls}，预期仍为 [3]（幂等）",
        )

    # 恢复：metrics 降到正常
    class _FakePerfNormal:
        def get_current_metrics(self):
            return {"cpu_usage": 30.0, "memory_usage": 50.0}

    svc._performance_monitor = _FakePerfNormal()

    async def _run_normal():
        with patch("core.services.monitoring.resource_monitor.get_resource_monitor", return_value=_FakeMonitor()):
            await svc._apply_resource_response()
    asyncio.run(_run_normal())

    if downgrade_calls != [3, 0]:
        return _fail("恢复 tick", f"perform_downgrade 调用={downgrade_calls}，预期 [3, 0]")

    return _ok("状态转移检查", "同级别不重复调用，级别变化时才调用")


# ==================== 主入口 ====================

def main() -> int:
    print("=" * 70)
    print("降级幂等性修复验证 (err_fa14c1475137)")
    print("=" * 70)

    tests = [
        test_perform_downgrade_idempotent,
        test_emergency_log_level_warning,
        test_clear_downgrade_markers,
        test_recovery_clears_markers_e2e,
        test_immune_transition_check,
    ]

    results = []
    for t in tests:
        try:
            results.append(t())
        except Exception as e:
            print(f"  [FAIL] {t.__name__} 异常: {e}")
            results.append(False)

    print("\n" + "=" * 70)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"结果: {passed}/{total} 通过")
    print("=" * 70)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
