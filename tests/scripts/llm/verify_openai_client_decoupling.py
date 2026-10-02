#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证 openai_compat/client.py 的解耦结果

背景：client.py 曾是 openai_compat/ 最大的文件（626 行），且 4 处逻辑写了两遍
（调试落盘、system-order 400 重建、422 判定、重试循环），_process_stream_chunk
内部的闭合块处理也复制了两份。本脚本校验这些重复与隐患已被新模块收敛：

1. dsml_stream / retry / session_mixin / caller_source 四个新模块就位且可导入
2. client.py 不再出现被搬走的重复片段
3. client.py 仍 re-export LLMSessionMixin / _is_sensitive_input_rejection
4. 子类只覆写白名单方法（_build_payload / chat / stream_chat / get_status / __init__）
5. chat 与 stream_chat 共用 request_session + retry_policy（动态 key 不再漏）
6. 调用统计已移出 _build_payload
7. 运行时行为：DSML 跨 chunk 拼接、过滤器实例隔离、重试退避、422 判定、动态 key 临时 session

用法（在项目根目录用 venv_core 运行）：
    venv_core\\python.exe tests\\scripts\\llm\\verify_openai_client_decoupling.py

退出码：0=全部通过；非0=有检查项失败。
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

OPENAI_COMPAT = ROOT / "core" / "llm" / "openai_compat"
CLIENT_PY = OPENAI_COMPAT / "client.py"

# 已经搬走的实现片段，client.py 里不该再出现
MOVED_AWAY = {
    "close_patterns": "DSML 闭合标记列表（已收敛到 dsml_parser.DSML_CLOSE_MARKERS）",
    "minimax_400_payload.json": "调试落盘（已收敛到 error_handling.dump_debug_payload）",
    "0.25 * (attempt + 1)": "重试退避（已收敛到 retry.RetryPolicy）",
    "_dsml_buffer": "DSML 缓冲状态（已收敛到 dsml_stream.DSMLStreamFilter）",
    "is_system_order_error": "system-order 判定（已收敛到 error_handling.classify_error_response）",
    "inspect.stack": "调用来源提取（已收敛到 caller_source.caller_source）",
    "aiohttp.ClientSession(": "session 构造（已收敛到 session_mixin.create_session）",
}

# 子类不得自行实现 / 覆写的成员：它们已经搬到新模块，子类再定义一份就会出现两套行为
MOVED_MEMBERS = {
    "_get_session",
    "_close_session",
    "shutdown",
    "_build_base_status",
    "_process_stream_chunk",
    "_handle_error_response",
}

SUBCLASSES = [
    "aveline_client.py",
    "deepseek_client.py",
    "minimax_client.py",
    "ark_client.py",
    "zhipu_client.py",
]

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  [OK] {message}")
    else:
        print(f"  [FAIL] {message}")
        failures.append(message)


def check_modules() -> None:
    print("[1] 新模块就位")
    from core.llm.openai_compat import caller_source, dsml_stream, retry, session_mixin
    from core.llm.openai_compat.error_handling import classify_error_response

    check(hasattr(dsml_stream, "DSMLStreamFilter"), "dsml_stream 导出 DSMLStreamFilter")
    check(hasattr(retry, "RetryPolicy"), "retry 导出 RetryPolicy")
    check(hasattr(session_mixin, "LLMSessionMixin"), "session_mixin 导出 LLMSessionMixin")
    check(hasattr(session_mixin, "request_session"), "session_mixin 导出 request_session")
    check(hasattr(caller_source, "caller_source"), "caller_source 导出 caller_source")
    check(callable(classify_error_response), "error_handling 导出 classify_error_response")


def check_client_source() -> None:
    print("[2] client.py 不再重复被搬走的逻辑")
    source = CLIENT_PY.read_text(encoding="utf-8")
    for snippet, why in MOVED_AWAY.items():
        check(snippet not in source, f"client.py 已移除 {snippet} —— {why}")

    lines = len(source.splitlines())
    print(f"  [INFO] client.py 当前 {lines} 行（拆分前 626 行）")
    check(lines < 626, "client.py 行数下降")

    print("[3] chat / stream_chat 共用同一套 session 与重试策略")
    check(source.count("request_session(self, api_key)") == 2, "chat 与 stream_chat 都走 request_session")
    check(source.count("retry_policy.max_attempts") >= 2, "重试次数统一取自 retry_policy")
    check(source.count("retry_policy.should_retry") == 2, "重试判定统一取自 retry_policy")
    check("self._log_call_stats(payload" in source, "调用统计在编排层触发")
    build_payload_src = source.split("def _build_payload")[-1]
    check("log_llm_call_stats" not in build_payload_src, "_build_payload 不再带统计副作用")


def check_exports_and_subclasses() -> None:
    print("[4] 兼容契约")
    from core.llm.openai_compat import client as client_module
    from core.llm.openai_compat.session_mixin import LLMSessionMixin

    check(client_module.LLMSessionMixin is LLMSessionMixin, "client 仍 re-export LLMSessionMixin")
    check(
        client_module._is_sensitive_input_rejection(422, "new_sensitive") is True,
        "client 仍 re-export _is_sensitive_input_rejection",
    )

    import ast

    for name in SUBCLASSES:
        tree = ast.parse((OPENAI_COMPAT / name).read_text(encoding="utf-8"))
        defined = {
            node.name
            for cls in ast.walk(tree)
            if isinstance(cls, ast.ClassDef)
            for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        # 子类仍可自由新增自己的私有助手（如 MiniMax._strip_names），
        # 但搬走的公共成员不能再被复制一份，否则会出现两套行为
        redeclared = defined & MOVED_MEMBERS
        check(not redeclared, f"{name} 未重复实现已搬走的成员（越界: {sorted(redeclared)}）")


def check_runtime() -> None:
    print("[5] 运行时行为")
    from unittest.mock import AsyncMock, patch

    from core.llm.openai_compat import OpenAIClient
    from core.llm.openai_compat.dsml_parser import DSML_CLOSE_MARKERS, DSML_START_MARKERS
    from core.llm.openai_compat.dsml_stream import DSMLStreamFilter
    from core.llm.openai_compat.error_handling import classify_error_response
    from core.llm.openai_compat.retry import RetryPolicy

    start, close = DSML_START_MARKERS[0], DSML_CLOSE_MARKERS[0]
    prefix = start[1 : -len("tool_calls>")]
    block = (
        f"{start}<{prefix}invoke name=\"get_weather\">"
        f"<{prefix}parameter name=\"city\" string=\"true\">上海</{prefix}parameter>"
        f"</{prefix}invoke>{close}"
    )

    dsml_filter = DSMLStreamFilter()
    head = dsml_filter.filter_chunk({"content": "开始" + block[:40]})
    tail = dsml_filter.filter_chunk({"content": block[40:] + "结束"})
    check(head == [{"content": "开始"}], "DSML 未闭合时只吐前文、不泄漏 token")
    check(
        tail[0].get("tool_calls") and tail[1] == {"finish_reason": "tool_calls"},
        "DSML 跨 chunk 闭合后解析出 tool_calls",
    )
    check(tail[-1] == {"content": "结束"}, "闭合后的剩余文本继续下发")

    f1, f2 = DSMLStreamFilter(), DSMLStreamFilter()
    f1.filter_chunk({"content": block[:40]})
    out2 = f2.filter_chunk({"content": block})
    check(f1.active and not f2.active, "两个过滤器缓冲互不干扰（并发流式不串味）")
    check(bool(out2[0].get("tool_calls")), "第二个过滤器独立解析成功")

    policy = RetryPolicy()
    check(policy.delay(0) == 0.25 and policy.delay(1) == 0.5, "退避序列保持 0.25 / 0.5")
    check(
        policy.should_retry(ConnectionResetError("connection reset"), 0)
        and not policy.should_retry(ValueError("bad"), 0)
        and not policy.should_retry(ConnectionResetError("connection reset"), 2),
        "只有瞬时错误且未用尽次数才重试",
    )

    info_422 = classify_error_response(422, "input new_sensitive (1026)")
    check(info_422.non_retryable and info_422.retry_payload is None, "422 敏感输入判定为不可重试")
    info_400 = classify_error_response(
        400,
        "system message must be at the beginning",
        payload={"messages": [{"role": "user", "content": "hi"}]},
        attempt=0,
    )
    check(info_400.retry_payload is not None, "system-order 400 返回重建后的 payload")

    # 动态 key：stream_chat 与 chat 一样建临时 session
    class _Resp:
        status = 599

        def __init__(self):
            self._body = "boom"

        async def text(self):
            return self._body

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

    class _Session:
        def __init__(self, headers):
            self.headers = headers
            self.closed = False

        def post(self, *_a, **_kw):
            return _Resp()

        async def close(self):
            self.closed = True

    created = []

    def session_factory(**kwargs):
        session = _Session(kwargs.get("headers", {}))
        created.append(session)
        return session

    client = object.__new__(OpenAIClient)
    client.initialized = True
    client.base_url = "http://example.invalid/v1/chat/completions"
    client.api_key = "static"
    client.timeout = 5
    client.proxy = None
    client._route_vision_if_needed = AsyncMock(return_value=([{"role": "user", "content": "x"}], ""))
    client._build_payload = lambda *_a, **_kw: {"model": "m"}
    client._get_session = AsyncMock(return_value=_Session({}))

    async def collect(**kwargs):
        return [chunk async for chunk in client.stream_chat([], **kwargs)]

    with patch("aiohttp.ClientSession", side_effect=session_factory):
        chunks = asyncio.run(collect(api_key="dynamic"))
    check(chunks == [{"error": "API returned 599"}], "非 200 流式分支输出不变")
    check(
        len(created) == 1 and created[0].headers["Authorization"] == "Bearer dynamic",
        "stream_chat 动态 key 走临时 session（原来只发默认 key）",
    )
    check(client._get_session.await_count == 0, "动态 key 未复用常驻 session")

    created.clear()
    with patch("aiohttp.ClientSession", side_effect=session_factory):
        asyncio.run(collect())
    check(not created and client._get_session.await_count == 1, "默认 key 仍复用常驻 session")


def main() -> int:
    check_modules()
    check_client_source()
    check_exports_and_subclasses()
    check_runtime()

    if failures:
        print(f"\n结果: {len(failures)} 项失败")
        return 1
    print("\n结果: openai_compat/client.py 解耦契约全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
