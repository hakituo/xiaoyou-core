#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
errors_20260815.json / errors_20260816.json 修复验证脚本

验证三处修复：
1. message_sending._is_disconnect_exception 能识别 Starlette/uvicorn 在连接已关闭后
   再 send 抛出的 "Unexpected ASGI message 'websocket.send'..." RuntimeError，
   不再当作普通错误重试 3 次（errors_20260815.json 的刷屏根因）
2. extractor._call_llm_with_prompt 的异常日志携带 exc_info，且最终汇总日志
   包含最后一次异常与上游错误信息（errors_20260816.json traceback 为空、无法定位根因）
3. memory.nightly_processor / core.utils.singleton 导入正常（errors_20260813.json 的 singleton 污染问题）
运行：
    D:\AI\xiaoyou-core\venv_core\Scripts\python.exe tests\scripts\websocket_errors\verify_debug_20260815_20260816.py
"""

import asyncio
import inspect
import sys
from pathlib import Path

# 让项目根目录可 import
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core.interfaces.websocket.message_sending import MessageSendingMixin  # noqa: E402

passed = 0
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name} {detail}")


# ============================================================
# 1. websocket 断开异常识别（errors_20260815.json）
# ============================================================
mixin = MessageSendingMixin()

# errors_20260815.json 中的原始错误消息（经过 lower() 后匹配）
err15 = (
    "Unexpected ASGI message 'websocket.send', after sending 'websocket.close' "
    "or response already completed."
)
check(
    "识别 'Unexpected ASGI message' 为断开异常",
    mixin._is_disconnect_exception(RuntimeError(err15)),
)

# 兼容其它变体
check(
    "识别 'response already completed' 变体",
    mixin._is_disconnect_exception(
        RuntimeError("Unexpected ASGI message 'websocket.send', response already completed.")
    ),
)

# 原有断开异常仍应识别（回归）
check(
    "原有 ConnectionClosedError 识别（回归）",
    mixin._is_disconnect_exception(RuntimeError("close message has been sent")),
)
check(
    "原有 ConnectionClosedOK 识别（回归）",
    mixin._is_disconnect_exception(RuntimeError("connection closed")),
)

# 非断开异常不应误判
check(
    "普通 RuntimeError 不误判",
    not mixin._is_disconnect_exception(RuntimeError("Some random bug")),
)

# ============================================================
# 2. extractor 日志携带 exc_info + 上游错误（errors_20260816.json）
# ============================================================
from core.character.people import extractor as extractor_mod  # noqa: E402

# 检查 except 分支确实传了 exc_info=True
src = inspect.getsource(extractor_mod.PeopleProfileExtractor._call_llm_with_prompt)
check(
    "LLM 调用失败日志带 exc_info=True",
    "logger.error(\"LLM 调用失败（第 %d 次）: %s\", attempt + 1, exc, exc_info=True)" in src,
)
check(
    "最终汇总日志包含上游错误信息",
    "上游错误" in src and "last_upstream_error" in src,
)
check(
    "记录上游 error chunk",
    'if chunk.get("error"):' in src,
)

# ============================================================
# 3. singleton 导入正常（errors_20260813.json，08-13 重构已修复，回归验证）
# ============================================================
try:
    from core.utils.singleton import singleton, SingletonFactory  # noqa: F401
    check("core.utils.singleton 导入正常", True)
except ImportError as e:
    check("core.utils.singleton 导入正常", False, str(e))

try:
    import memory.nightly_processor  # noqa: F401
    check("memory.nightly_processor 导入正常", True)
except ImportError as e:
    check("memory.nightly_processor 导入正常", False, str(e))

# ============================================================
# 结果
# ============================================================
print()
print(f"通过 {passed} 项，失败 {failed} 项")
if failed:
    sys.exit(1)
print("全部通过")
