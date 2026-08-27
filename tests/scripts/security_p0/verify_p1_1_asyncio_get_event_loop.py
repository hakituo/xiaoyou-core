#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
P1-1 验证脚本：修复 asyncio.get_event_loop() 弃用用法

验证目标：
  - core/ 目录下不再有 asyncio.get_event_loop() 的实际调用
  - 仅允许在注释中出现（说明性文字）
  - 所有原调用点已替换为：
    * asyncio.get_running_loop()  （在 async 函数内）
    * asyncio.get_event_loop_policy().get_event_loop()  （在 done_callback 内）
    * time.monotonic() / time.time()  （用于 .time()）
    * asyncio.to_thread()  （替代 run_in_executor(None, fn, ...)）
    * try/except RuntimeError  （在同步函数内判断 loop 是否运行）

验证方法：
  - Grep 扫描 core/ 下所有 asyncio.get_event_loop() 出现位置
  - 区分注释（# 开头）与实际调用
  - 模块导入测试：确保所有修改的模块导入正常
"""

import re
import sys
from pathlib import Path
from typing import List, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 检查 1：扫描 core/ 下所有 asyncio.get_event_loop() 实际调用
# ---------------------------------------------------------------------------
def check_no_actual_calls() -> Tuple[List[str], List[str]]:
    """
    扫描 core/ 下所有 .py 文件，找出 asyncio.get_event_loop() 出现位置。

    返回 (issues, comments_only_hits)：
      - issues: 实际调用（非注释行）的位置
      - comments_only_hits: 仅出现在注释中的位置（允许）
    """
    issues: List[str] = []
    comments_only: List[str] = []

    core_dir = _PROJECT_ROOT / "core"
    if not core_dir.exists():
        issues.append(f"core 目录不存在: {core_dir}")
        return issues, comments_only

    # 递归扫描所有 .py 文件
    for py_file in core_dir.rglob("*.py"):
        rel_path = py_file.relative_to(_PROJECT_ROOT)
        try:
            content = py_file.read_text(encoding="utf-8")
        except Exception:
            continue

        for line_no, line in enumerate(content.splitlines(), start=1):
            if "asyncio.get_event_loop()" not in line:
                continue

            # 去掉行首空白后判断
            stripped = line.lstrip()
            # 注释行（# 开头）
            if stripped.startswith("#"):
                comments_only.append(f"{rel_path}:{line_no} (注释): {line.strip()}")
                continue

            # 行内注释：检查 # 之前是否还有 asyncio.get_event_loop()
            # 如果 # 出现在 asyncio.get_event_loop() 之前，那它是注释
            hash_pos = line.find("#")
            gel_pos = line.find("asyncio.get_event_loop()")
            if hash_pos >= 0 and hash_pos < gel_pos:
                comments_only.append(f"{rel_path}:{line_no} (注释): {line.strip()}")
                continue

            # 实际调用
            issues.append(f"{rel_path}:{line_no}: {line.strip()}")

    return issues, comments_only


# ---------------------------------------------------------------------------
# 检查 2：扫描已知修改文件，验证替换模式存在
# ---------------------------------------------------------------------------
def check_replacement_patterns() -> List[str]:
    """验证修改后的文件包含期望的替换模式"""
    issues: List[str] = []

    expected_patterns = [
        # (相对路径, 期望出现的字符串)
        ("core/core_engine/lifecycle_manager.py", "asyncio.to_thread(importlib.import_module"),
        ("core/image/image_service_client.py", "asyncio.get_running_loop()"),
        ("core/image/_image_models_mixin.py", "asyncio.to_thread(self.forge_client.get_models)"),
        ("core/image/_image_forge_backend_mixin.py", "asyncio.get_running_loop()"),
        ("core/image/prompt_processor.py", "time.time()"),
        ("core/interfaces/websocket/message_sending.py", "time.monotonic()"),
        ("core/voice/engines/qwen3_tts_engine.py", "asyncio.get_running_loop()"),
        ("core/services/scheduler/task/async_task_wrapper.py", "time.monotonic()"),
        ("core/utils/demo_utils.py", "asyncio.get_running_loop()"),
        ("core/utils/log_sanitizer.py", "asyncio.get_running_loop()"),
        ("core/utils/logger.py", "asyncio.get_running_loop()"),
        ("core/services/active_care/goodnight_proactive.py", "asyncio.get_running_loop()"),
        ("core/services/active_care/good_morning_proactive.py", "asyncio.get_running_loop()"),
        ("core/services/active_care/peer_chat/peer_chat_scheduler.py",
         "asyncio.get_event_loop_policy().get_event_loop()"),
        ("core/services/character_daily/engine.py",
         "asyncio.get_event_loop_policy().get_event_loop()"),
        ("core/llm/cloud_router.py", "asyncio.get_running_loop()"),
    ]

    for rel_path, pattern in expected_patterns:
        full_path = _PROJECT_ROOT / rel_path
        if not full_path.exists():
            issues.append(f"文件不存在: {rel_path}")
            continue
        try:
            content = full_path.read_text(encoding="utf-8")
        except Exception as e:
            issues.append(f"读取 {rel_path} 失败: {e}")
            continue
        if pattern not in content:
            issues.append(f"{rel_path} 未找到期望的替换模式: {pattern}")

    return issues


# ---------------------------------------------------------------------------
# 检查 3：模块导入测试
# ---------------------------------------------------------------------------
def check_imports() -> List[str]:
    """验证修改后的模块可以正常导入"""
    issues: List[str] = []

    modules_to_test = [
        "core.core_engine.lifecycle_manager",
        "core.image.image_service_client",
        "core.image._image_models_mixin",
        "core.image._image_forge_backend_mixin",
        "core.image.prompt_processor",
        "core.interfaces.websocket.message_sending",
        "core.voice.engines.qwen3_tts_engine",
        "core.services.scheduler.task.async_task_wrapper",
        "core.utils.demo_utils",
        "core.utils.log_sanitizer",
        "core.utils.logger",
        "core.services.active_care.goodnight_proactive",
        "core.services.active_care.good_morning_proactive",
        "core.services.active_care.peer_chat.peer_chat_scheduler",
        "core.services.character_daily.engine",
        "core.llm.cloud_router",
    ]

    for mod_name in modules_to_test:
        try:
            __import__(mod_name)
        except Exception as e:
            issues.append(f"导入 {mod_name} 失败: {e}")

    return issues


# ---------------------------------------------------------------------------
# 检查 4：运行时验证 asyncio.get_running_loop 行为正确
# ---------------------------------------------------------------------------
def check_runtime_behavior() -> List[str]:
    """验证 asyncio.get_running_loop() 在 async 上下文下能正常工作"""
    issues: List[str] = []
    import asyncio

    async def _test():
        # 验证在 async 函数内 get_running_loop 不抛异常
        try:
            loop = asyncio.get_running_loop()
            if loop is None:
                issues.append("asyncio.get_running_loop() 返回 None")
        except Exception as e:
            issues.append(f"async 函数内 asyncio.get_running_loop() 抛异常: {e}")

        # 验证 asyncio.to_thread 可用
        def _sync_op(x):
            return x * 2
        result = await asyncio.to_thread(_sync_op, 21)
        if result != 42:
            issues.append(f"asyncio.to_thread 返回错误结果: {result}")

        # 验证 get_running_loop().create_future 可用
        future = asyncio.get_running_loop().create_future()
        if not isinstance(future, asyncio.Future):
            issues.append("get_running_loop().create_future() 返回类型错误")

        # 验证 get_running_loop().time 可用
        t = asyncio.get_running_loop().time()
        if not isinstance(t, float):
            issues.append(f"get_running_loop().time() 返回类型错误: {type(t)}")

        # 验证 get_running_loop().call_later 可用并正确触发
        triggered = []
        def _cb():
            triggered.append(True)
        h = asyncio.get_running_loop().call_later(0.01, _cb)
        await asyncio.sleep(0.05)
        if not triggered:
            issues.append("get_running_loop().call_later 回调未被触发")
        h.cancel()

    try:
        asyncio.run(_test())
    except Exception as e:
        issues.append(f"运行时验证异常: {e}")

    # 验证在同步上下文下 asyncio.get_running_loop() 抛 RuntimeError
    try:
        asyncio.get_running_loop()
        issues.append("同步上下文下 asyncio.get_running_loop() 应抛 RuntimeError")
    except RuntimeError:
        pass  # 期望行为

    return issues


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def main() -> int:
    print("=" * 70)
    print("P1-1 验证：修复 asyncio.get_event_loop() 弃用用法")
    print("=" * 70)

    all_issues = []

    print("\n[1/4] 扫描 core/ 下所有 asyncio.get_event_loop() 实际调用 ...")
    issues, comments = check_no_actual_calls()
    all_issues.extend(issues)
    print(f"  -> 实际调用: {len(issues)} 处, 注释中提及: {len(comments)} 处")
    if issues:
        for msg in issues:
            print(f"     - {msg}")

    print("\n[2/4] 验证修改后的文件包含期望的替换模式 ...")
    issues = check_replacement_patterns()
    all_issues.extend(issues)
    print(f"  -> {'PASS' if not issues else 'FAIL'} ({len(issues)} 个问题)")
    for msg in issues:
        print(f"     - {msg}")

    print("\n[3/4] 模块导入测试（16 个模块）...")
    issues = check_imports()
    all_issues.extend(issues)
    print(f"  -> {'PASS' if not issues else 'FAIL'} ({len(issues)} 个问题)")
    for msg in issues:
        print(f"     - {msg}")

    print("\n[4/4] 运行时验证 asyncio.get_running_loop() 行为 ...")
    issues = check_runtime_behavior()
    all_issues.extend(issues)
    print(f"  -> {'PASS' if not issues else 'FAIL'} ({len(issues)} 个问题)")
    for msg in issues:
        print(f"     - {msg}")

    print("\n" + "=" * 70)
    if not all_issues:
        print("✅ 全部检查通过！P1-1 修复验证成功。")
        return 0
    else:
        print(f"❌ 共发现 {len(all_issues)} 个问题")
        return 1


if __name__ == "__main__":
    sys.exit(main())
