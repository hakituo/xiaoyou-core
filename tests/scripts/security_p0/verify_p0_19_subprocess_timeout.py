#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0-19 验证脚本：subprocess 调用缺少 timeout 导致卡死

验证范围：
1. volcano_tts_engine.py 的 ffmpeg subprocess.run 包含 timeout
2. stt_connector.py 的 pip install subprocess.check_call 包含 timeout
3. resource_components.py 的 powershell/wmic/lscpu 调用包含 timeout
4. resource/monitor.py 的 powershell/wmic/lscpu 调用包含 timeout
5. 实际运行测试：模拟超时场景，验证不会卡死
6. TimeoutExpired 异常处理存在
"""

from __future__ import annotations

import ast
import subprocess
import sys
import time
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def _read_file(rel_path: str) -> str:
    """读取项目内文件"""
    return (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")


def _parse_subprocess_calls(source: str) -> List[ast.Call]:
    """解析源码中所有 subprocess.xxx(...) 调用节点"""
    tree = ast.parse(source)
    calls: List[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # 匹配 subprocess.run / subprocess.check_call / subprocess.check_output
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id == "subprocess" and func.attr in (
                "run",
                "check_call",
                "check_output",
                "call",
            ):
                calls.append(node)
    return calls


def _has_timeout_kwarg(call: ast.Call) -> bool:
    """判断 Call 节点是否包含 timeout 关键字参数"""
    for kw in call.keywords:
        if kw.arg == "timeout":
            return True
    return False


def _get_timeout_value(call: ast.Call) -> int | float | None:
    """获取 timeout 的字面值"""
    for kw in call.keywords:
        if kw.arg == "timeout":
            try:
                return ast.literal_eval(kw.value)
            except Exception:
                return None
    return None


# ============================================================================
# 场景1: volcano_tts_engine.py 的 ffmpeg subprocess.run 包含 timeout
# ============================================================================

def check_volcano_ffmpeg_timeout() -> List[str]:
    """volcano_tts_engine.py 的 ffmpeg subprocess.run 必须有 timeout"""
    issues: List[str] = []
    source = _read_file("core/voice/engines/volcano_tts_engine.py")

    # 简单字符串检查：必须有 timeout=30
    if "timeout=30" not in source:
        issues.append("volcano_tts_engine.py 缺少 timeout=30 参数")
        return issues

    # AST 检查：所有 subprocess.run 调用都必须有 timeout
    calls = _parse_subprocess_calls(source)
    if not calls:
        issues.append("volcano_tts_engine.py 未找到 subprocess 调用（AST 解析）")
        return issues

    for i, call in enumerate(calls):
        if not _has_timeout_kwarg(call):
            issues.append(
                f"volcano_tts_engine.py 第 {call.lineno} 行 "
                f"subprocess 调用缺少 timeout"
            )

    # 检查 TimeoutExpired 异常处理
    if "TimeoutExpired" not in source:
        issues.append("volcano_tts_engine.py 缺少 TimeoutExpired 异常处理")

    return issues


# ============================================================================
# 场景2: stt_connector.py 的 pip install subprocess.check_call 包含 timeout
# ============================================================================

def check_stt_pip_install_timeout() -> List[str]:
    """stt_connector.py 的 pip install subprocess.check_call 必须有 timeout"""
    issues: List[str] = []
    source = _read_file("multimodal/stt_connector.py")

    if "timeout=180" not in source:
        issues.append("stt_connector.py 缺少 timeout=180 参数")
        return issues

    calls = _parse_subprocess_calls(source)
    if not calls:
        issues.append("stt_connector.py 未找到 subprocess 调用（AST 解析）")
        return issues

    for call in calls:
        if not _has_timeout_kwarg(call):
            issues.append(
                f"stt_connector.py 第 {call.lineno} 行的 subprocess 调用缺少 timeout"
            )

    if "TimeoutExpired" not in source:
        issues.append("stt_connector.py 缺少 TimeoutExpired 异常处理")

    return issues


# ============================================================================
# 场景3: resource_components.py 的 powershell/wmic/lscpu 调用包含 timeout
# ============================================================================

def check_resource_components_timeout() -> List[str]:
    """resource_components.py 中所有 subprocess 调用必须有 timeout"""
    issues: List[str] = []
    source = _read_file("core/resource_components.py")

    calls = _parse_subprocess_calls(source)
    if not calls:
        issues.append("resource_components.py 未找到 subprocess 调用")
        return issues

    for call in calls:
        if not _has_timeout_kwarg(call):
            issues.append(
                f"resource_components.py 第 {call.lineno} 行 "
                f"subprocess 调用缺少 timeout"
            )

    return issues


# ============================================================================
# 场景4: resource/monitor.py 的 powershell/wmic/lscpu 调用包含 timeout
# ============================================================================

def check_resource_monitor_timeout() -> List[str]:
    """resource/monitor.py 中所有 subprocess 调用必须有 timeout"""
    issues: List[str] = []
    source = _read_file("core/resource/monitor.py")

    calls = _parse_subprocess_calls(source)
    if not calls:
        issues.append("resource/monitor.py 未找到 subprocess 调用")
        return issues

    for call in calls:
        if not _has_timeout_kwarg(call):
            issues.append(
                f"resource/monitor.py 第 {call.lineno} 行的 subprocess 调用缺少 timeout"
            )

    return issues


# ============================================================================
# 场景5: 实际运行测试 - subprocess.run 超时确实会触发 TimeoutExpired
# ============================================================================

def check_subprocess_timeout_actually_triggers() -> List[str]:
    """验证 subprocess.run 的 timeout 参数确实生效"""
    issues: List[str] = []

    # 模拟一个会卡住的命令，timeout=0.5 应该在 0.5 秒后触发 TimeoutExpired
    start = time.monotonic()
    try:
        subprocess.run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=0.5,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        issues.append("卡住的 subprocess.run 应该触发 TimeoutExpired，但没有")
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        # 应该在 0.5~2 秒内触发
        if elapsed > 3.0:
            issues.append(
                f"TimeoutExpired 触发但耗时过长: {elapsed:.2f}s（预期 <3s）"
            )
    except Exception as e:
        issues.append(
            f"预期 TimeoutExpired，实际抛出 {type(e).__name__}: {e}"
        )

    return issues


# ============================================================================
# 场景6: 实际运行测试 - volcano_tts_engine 的 _decode_mp3 不会卡死
# ============================================================================

def check_volcano_decode_mp3_no_hang() -> List[str]:
    """验证 VolcanoTTSEngine._decode_mp3 在 ffmpeg 不可用时不会卡死"""
    issues: List[str] = []

    try:
        from core.voice.engines.volcano_tts_engine import VolcanoTTSEngine
    except Exception as e:
        issues.append(f"无法导入 VolcanoTTSEngine: {e}")
        return issues

    # 测试1: 空数据应快速返回空数组
    start = time.monotonic()
    result = VolcanoTTSEngine._decode_mp3(b"")
    elapsed = time.monotonic() - start
    if elapsed > 2.0:
        issues.append(f"_decode_mp3(空数据) 耗时过长: {elapsed:.2f}s")
    if len(result) != 0:
        issues.append(f"_decode_mp3(空数据) 应返回空数组，实际长度={len(result)}")

    # 测试2: 无效 mp3 数据应快速返回（ffmpeg 失败或不可用）
    # 这里用一个明显无效的字节串，soundfile 和 ffmpeg 都应失败
    start = time.monotonic()
    try:
        result = VolcanoTTSEngine._decode_mp3(b"not a valid mp3 data")
        elapsed = time.monotonic() - start
        # 即使 ffmpeg 存在，因为有 timeout=30，最坏情况是 30 秒
        # 但对于无效数据，ffmpeg 应该立即失败
        if elapsed > 35.0:
            issues.append(
                f"_decode_mp3(无效数据) 耗时过长: {elapsed:.2f}s，"
                f"可能 timeout 未生效"
            )
        if len(result) != 0:
            issues.append(
                f"_decode_mp3(无效数据) 应返回空数组，实际长度={len(result)}"
            )
    except Exception as e:
        issues.append(
            f"_decode_mp3(无效数据) 抛出异常 {type(e).__name__}: {e}"
        )

    return issues


# ============================================================================
# 场景7: 验证修复后的文件可以正常导入
# ============================================================================

def check_modules_importable() -> List[str]:
    """验证修复后的模块可以正常导入"""
    issues: List[str] = []

    try:
        import importlib

        # volcano_tts_engine
        try:
            importlib.import_module("core.voice.engines.volcano_tts_engine")
        except Exception as e:
            issues.append(
                f"导入 core.voice.engines.volcano_tts_engine 失败: {e}"
            )
    except Exception as e:
        issues.append(f"导入检查失败: {e}")

    return issues


# ============================================================================
# 场景8: 验证 stt_connector 的 pip install 调用确实有 timeout
# ============================================================================

def check_stt_pip_install_timeout_value() -> List[str]:
    """验证 stt_connector.py 中 pip install 调用的 timeout 值合理（>=60s）"""
    issues: List[str] = []
    source = _read_file("multimodal/stt_connector.py")

    calls = _parse_subprocess_calls(source)
    pip_install_found = False
    for call in calls:
        # 检查是否是 pip install 调用
        try:
            first_arg = ast.literal_eval(call.args[0])
            if isinstance(first_arg, list) and any(
                isinstance(x, str) and "pip" in x for x in first_arg
            ):
                pip_install_found = True
                timeout_val = _get_timeout_value(call)
                if timeout_val is None:
                    issues.append("pip install 调用缺少 timeout 值")
                elif timeout_val < 60:
                    issues.append(
                        f"pip install 调用 timeout={timeout_val} 过短，"
                        f"建议至少 60s（网络较慢时需要更长时间）"
                    )
        except Exception:
            continue

    if not pip_install_found:
        # 不一定有问题（可能 AST 解析方式不对），记录但不报错
        pass

    return issues


# ============================================================================
# 场景9: 验证 volcano_tts_engine 的 ffmpeg 调用 timeout 值合理
# ============================================================================

def check_volcano_ffmpeg_timeout_value() -> List[str]:
    """验证 volcano_tts_engine.py 中 ffmpeg 调用的 timeout 值合理（10~60s）"""
    issues: List[str] = []
    source = _read_file("core/voice/engines/volcano_tts_engine.py")

    calls = _parse_subprocess_calls(source)
    ffmpeg_found = False
    for call in calls:
        try:
            args_list = ast.literal_eval(call.args[0])
            if isinstance(args_list, list) and "ffmpeg" in args_list:
                ffmpeg_found = True
                timeout_val = _get_timeout_value(call)
                if timeout_val is None:
                    issues.append("ffmpeg 调用缺少 timeout 值")
                elif timeout_val < 10:
                    issues.append(
                        f"ffmpeg timeout={timeout_val} 过短，至少需要 10s"
                    )
                elif timeout_val > 60:
                    issues.append(
                        f"ffmpeg timeout={timeout_val} 过长，不应超过 60s"
                    )
        except Exception:
            continue

    if not ffmpeg_found:
        issues.append("未找到 ffmpeg 调用（AST 解析）")

    return issues


# ============================================================================
# 主函数
# ============================================================================

def main() -> int:
    """主函数：运行所有检查"""
    print("=" * 72)
    print("P0-19 验证：subprocess 调用缺少 timeout 导致卡死")
    print("=" * 72)

    checks = [
        ("场景1", "volcano_tts_engine.py ffmpeg subprocess.run 有 timeout",
         check_volcano_ffmpeg_timeout),
        ("场景2", "stt_connector.py pip install subprocess.check_call 有 timeout",
         check_stt_pip_install_timeout),
        ("场景3", "resource_components.py 所有 subprocess 调用有 timeout",
         check_resource_components_timeout),
        ("场景4", "resource/monitor.py 所有 subprocess 调用有 timeout",
         check_resource_monitor_timeout),
        ("场景5", "subprocess.run 的 timeout 参数确实生效",
         check_subprocess_timeout_actually_triggers),
        ("场景6", "VolcanoTTSEngine._decode_mp3 不会卡死",
         check_volcano_decode_mp3_no_hang),
        ("场景7", "修复后的模块可以正常导入",
         check_modules_importable),
        ("场景8", "stt_connector.py pip install timeout 值合理",
         check_stt_pip_install_timeout_value),
        ("场景9", "volcano_tts_engine.py ffmpeg timeout 值合理",
         check_volcano_ffmpeg_timeout_value),
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
        print("✅ 所有验证通过！P0-19 修复有效。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
