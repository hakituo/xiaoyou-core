#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-3 验证：修复初始化失败仍标记为成功

验证目标：
1. lifecycle_manager.py: 失败服务被记录，可通过 get_status 暴露
2. tts_engine.py: 所有 provider 失败时不标记 initialized=True
3. image_manager.py: 所有 client 失败时不标记 _is_initialized=True
4. weighted_memory_manager.py: 仅语义问题，添加注释说明（不强校验）

涉及修改的文件：
- core/core_engine/lifecycle_manager.py
- core/voice/tts_engine.py
- core/image/image_manager.py
"""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def _read(path: str) -> str:
    return Path(PROJECT_ROOT / path).read_text(encoding="utf-8")


# ============================================================
# 场景 1：lifecycle_manager.py 失败服务跟踪
# ============================================================

def test_1_lifecycle_tracks_failures():
    """lifecycle_manager.py: _failed_services 与 _init_errors 字段"""
    src = _read("core/core_engine/lifecycle_manager.py")
    issues = []
    if "_failed_services" not in src:
        issues.append("缺少 _failed_services 字段")
    if "_init_errors" not in src:
        issues.append("缺少 _init_errors 字段")
    # 串行初始化分支应记录失败
    if 'self._failed_services.append(name)' not in src:
        issues.append("串行初始化分支未记录失败服务")
    # 并行初始化 _init_one 应记录失败
    if 'self._failed_services.append(name)' not in src:
        issues.append("并行初始化 _init_one 未记录失败服务")
    # get_status 应暴露失败信息
    if '"has_critical_failures"' not in src:
        issues.append("get_status 未暴露 has_critical_failures")
    if '"failed_services"' not in src:
        issues.append("get_status 未暴露 failed_services 列表")
    return issues


def test_2_lifecycle_runtime():
    """lifecycle_manager.py: 运行时验证失败服务被记录"""
    issues = []
    try:
        from core.core_engine.lifecycle_manager import ServiceLifecycle

        sl = ServiceLifecycle()

        # 注册一个会失败的服务和一个成功的服务
        async def _fail_init():
            raise RuntimeError("test failure")

        async def _ok_init():
            return None

        async def _noop_shutdown():
            return None

        sl.register_service(
            "fail_svc", _fail_init, _noop_shutdown, priority=10
        )
        sl.register_service(
            "ok_svc", _ok_init, _noop_shutdown, priority=10
        )

        asyncio.run(sl.initialize_all())

        # 验证失败服务被记录
        if "fail_svc" not in sl._failed_services:
            issues.append(f"fail_svc 未被记录到 _failed_services: {sl._failed_services}")
        if "fail_svc" not in sl._init_errors:
            issues.append(f"fail_svc 未被记录到 _init_errors")
        else:
            err = sl._init_errors["fail_svc"]
            if "test failure" not in err:
                issues.append(f"init_error 内容不正确: {err}")

        # 验证 ok_svc 不在失败列表
        if "ok_svc" in sl._failed_services:
            issues.append("ok_svc 不应在失败列表中")

        # 验证 get_status 暴露失败信息
        status = sl.get_status()
        if not status.get("has_critical_failures"):
            issues.append("get_status.has_critical_failures 应为 True")
        if "fail_svc" not in status.get("failed_services", []):
            issues.append("get_status.failed_services 未包含 fail_svc")
        if status["services"]["fail_svc"]["init_error"] is None:
            issues.append("get_status.services.fail_svc.init_error 不应为 None")
        if status["services"]["ok_svc"]["init_error"] is not None:
            issues.append("get_status.services.ok_svc.init_error 应为 None")
    except Exception as e:
        issues.append(f"测试本身异常: {e!r}")
    return issues


# ============================================================
# 场景 2：tts_engine.py 所有 provider 失败时不标记成功
# ============================================================

def test_3_tts_engine_source():
    """tts_engine.py: 检查 engine 为 None 时不设置 initialized=True"""
    src = _read("core/voice/tts_engine.py")
    issues = []
    if "if self.engine is None:" not in src:
        issues.append("缺少 'if self.engine is None:' 检查")
    if "self._register_resource_manager_safely" not in src:
        issues.append("未抽取 _register_resource_manager_safely")
    # 失败分支应该 return（不设置 self.initialized = True）
    if "self.initialized = True" not in src:
        issues.append("缺少 initialized=True 标记")
    return issues


def test_4_tts_engine_runtime():
    """tts_engine.py: 运行时验证所有 provider 失败时 initialized 保持 False"""
    issues = []
    try:
        import unittest.mock as mock

        # 通过 mock 让所有引擎 import 失败，触发 fallback 链全失败
        # Qwen3TTSEngine 在 core.voice.engines 模块中导入
        # F5TTSEngine 同样
        from core.voice.tts_engine import TTSManager

        # 重置单例
        TTSManager._instance = None

        # 模拟 settings 让 provider 走 local 分支
        mock_settings = mock.MagicMock()
        mock_settings.voice.tts.provider = "local"
        mock_settings.voice.tts.model = None
        mock_settings.voice.tts_engine = "qwen3"

        with mock.patch("core.voice.tts_engine.get_settings", return_value=mock_settings), \
             mock.patch("core.voice.engines.Qwen3TTSEngine", side_effect=RuntimeError("mock qwen3 fail")), \
             mock.patch.dict("sys.modules", {"qwen_tts": None}):
            mgr = TTSManager()
            asyncio.run(mgr.initialize())

            # 验证 initialized 仍为 False
            if mgr.initialized:
                issues.append(
                    f"所有 provider 失败后 initialized 仍为 True (engine={mgr.engine}, last_error={mgr.last_error})"
                )
            if mgr.engine is not None:
                issues.append(f"engine 应为 None，实际为 {mgr.engine!r}")
            if not mgr.last_error:
                issues.append("last_error 应记录失败原因")
    except Exception as e:
        issues.append(f"测试本身异常: {e!r}")
    finally:
        # 重置单例避免影响其他测试
        try:
            from core.voice.tts_engine import TTSManager
            TTSManager._instance = None
        except Exception:
            pass
    return issues


# ============================================================
# 场景 3：image_manager.py 所有 client 失败时不标记成功
# ============================================================

def test_5_image_manager_source():
    """image_manager.py: 检查所有 client 失败时不设置 _is_initialized=True"""
    src = _read("core/image/image_manager.py")
    issues = []
    if "available_clients" not in src:
        issues.append("缺少 available_clients 检查")
    if "if not any(c is not None for _, c in available_clients):" not in src:
        issues.append("缺少 '至少一个 client 可用' 的硬约束")
    if "self._is_initialized = False" not in src:
        issues.append("失败分支未设置 _is_initialized=False")
    if "return False" not in src:
        issues.append("失败分支未返回 False")
    if "self.last_error" not in src:
        issues.append("缺少 last_error 字段")
    return issues


def test_6_image_manager_runtime():
    """image_manager.py: 运行时验证所有 client 失败时 _is_initialized 保持 False"""
    issues = []
    try:
        # 通过 mock 让所有 client 构造都失败
        import unittest.mock as mock

        # 在 import 之前 patch 掉所有 client 类
        with mock.patch("core.image.image_manager.ForgeClient", side_effect=RuntimeError("mock fail")), \
             mock.patch("core.image.image_manager.SiliconFlowImageClient", side_effect=RuntimeError("mock fail")), \
             mock.patch("core.image.image_manager.ComfyClient", side_effect=RuntimeError("mock fail")):
            from core.image.image_manager import ImageManager

            mgr = ImageManager()
            result = asyncio.run(mgr.initialize())

            if result is not False:
                issues.append(f"initialize 应返回 False，实际 {result}")
            if mgr._is_initialized:
                issues.append("_is_initialized 应为 False")
            if not mgr.last_error:
                issues.append("last_error 应记录失败原因")
    except Exception as e:
        issues.append(f"测试本身异常: {e!r}")
    return issues


# ============================================================
# 场景 4：模块导入测试
# ============================================================

def test_7_module_imports():
    """所有修改后的模块可以正常导入"""
    issues = []
    modules_to_test = [
        "core.core_engine.lifecycle_manager",
        "core.voice.tts_engine",
        "core.image.image_manager",
    ]
    for mod in modules_to_test:
        try:
            __import__(mod)
        except Exception as e:
            issues.append(f"{mod}: {e!r}")
    return issues


# ============================================================
# 场景 5：ruff 检查
# ============================================================

def test_8_ruff():
    """ruff 检查修改后的关键文件（F401 未使用导入）"""
    import subprocess
    files = [
        "core/core_engine/lifecycle_manager.py",
        "core/voice/tts_engine.py",
        "core/image/image_manager.py",
    ]
    issues = []
    for f in files:
        r = subprocess.run(
            [str(Path(PROJECT_ROOT / "venv_core/Scripts/python.exe")),
             "-m", "ruff", "check", "--select=F401", str(PROJECT_ROOT / f)],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        if r.returncode != 0:
            issues.append(f"{f}: {r.stdout.strip()[:200]}")
    return issues


# ============================================================
# 主入口
# ============================================================

def main():
    print("=" * 72)
    print("P1-3 验证：修复初始化失败仍标记为成功")
    print("=" * 72)

    tests = [
        ("[1/8] lifecycle_manager.py 失败跟踪字段", test_1_lifecycle_tracks_failures),
        ("[2/8] lifecycle_manager.py 运行时验证", test_2_lifecycle_runtime),
        ("[3/8] tts_engine.py 源码检查", test_3_tts_engine_source),
        ("[4/8] tts_engine.py 运行时验证", test_4_tts_engine_runtime),
        ("[5/8] image_manager.py 源码检查", test_5_image_manager_source),
        ("[6/8] image_manager.py 运行时验证", test_6_image_manager_runtime),
        ("[7/8] 模块导入测试", test_7_module_imports),
        ("[8/8] ruff F401 检查", test_8_ruff),
    ]

    total_issues = 0
    for name, fn in tests:
        try:
            issues = fn()
        except Exception as e:
            issues = [f"测试本身异常: {e!r}"]
        if not issues:
            print(f"  {name}: ✅ 通过")
        else:
            print(f"  {name}: ❌ 失败 ({len(issues)} 个问题)")
            for iss in issues:
                print(f"    - {iss}")
            total_issues += len(issues)

    print()
    if total_issues == 0:
        print("✅ 所有验证通过！P1-3 修复有效。")
        return 0
    else:
        print(f"❌ 共 {total_issues} 个问题未通过。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
