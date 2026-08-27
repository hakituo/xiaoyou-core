"""P0-11 验证脚本：dashscope_client.stream_chat 真流式实现

验证目标：
1. stream_chat 不再走 chat() 路径（不会一次性拿到完整文本再假装 yield 一次）
2. stream_chat 发起的请求带 X-DashScope-SSE: enable 头
3. payload 中包含 incremental_output: True
4. _parse_dashscope_sse 能正确解析 DashScope 原生 SSE 流（message.content 而非 delta.content）
5. 多个 SSE data: 块能被逐块 yield，而不是合并成一个

修复要点：
- 删除 stream_chat 内部对 chat() 的调用，改为直接发起 SSE 流式请求
- 添加 X-DashScope-SSE: enable 头
- 添加 incremental_output: True 参数（避免每个 chunk 都是完整文本）
- 新增 _parse_dashscope_sse 解析 DashScope 原生格式（message.content + 字符串 "null" finish_reason）
"""
import asyncio
import inspect
import json
import os
import sys
from typing import Any, Dict, List

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ============== 辅助：构造 fake response.content ==============

class _FakeContent:
    """模拟 aiohttp response.content，按给定字节数据序列产出 chunk。"""

    def __init__(self, chunks: List[bytes]):
        self._chunks = chunks
        self._idx = 0

    async def iter_any(self):
        for c in self._chunks:
            yield c


class _FakeResponse:
    def __init__(self, status: int, content_chunks: List[bytes]):
        self.status = status
        self.content = _FakeContent(content_chunks)
        self._text = ""

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeSession:
    """记录 post 调用，返回预设的 _FakeResponse。"""

    # 模拟 aiohttp.ClientSession.closed 属性，避免 _get_session 替换 fake session
    closed = False

    def __init__(self, response: _FakeResponse):
        self._response = response
        self.calls: List[Dict[str, Any]] = []

    def post(self, url, json=None, headers=None, **kwargs):
        self.calls.append({
            "url": url,
            "json": json,
            "headers": headers or {},
            "kwargs": kwargs,
        })
        return self._response


# ============== 检查项 ==============

def check_stream_chat_does_not_call_chat() -> list[str]:
    """场景1：stream_chat 不应通过调用 chat() 实现假流式。"""
    issues: list[str] = []
    from core.llm.dashscope_client import DashScopeClient

    client = DashScopeClient(api_key="test_key")
    client.initialized = True

    chat_called = {"n": 0}
    orig_chat = client.chat

    async def fake_chat(messages, **kwargs):
        chat_called["n"] += 1
        return {"response": "fake", "finish_reason": "stop"}

    client.chat = fake_chat

    # 拦截 session.post，避免真实网络请求
    fake_response = _FakeResponse(200, [b"data:[DONE]\n"])
    fake_session = _FakeSession(fake_response)
    client.session = fake_session

    async def run():
        async for _ in client.stream_chat([{"role": "user", "content": "hi"}]):
            pass

    try:
        asyncio.run(run())
    except Exception as e:
        # 网络相关异常忽略，只看 chat 调用次数
        pass

    if chat_called["n"] > 0:
        issues.append(
            f"stream_chat 内部调用了 chat() {chat_called['n']} 次，仍是假流式实现"
        )

    return issues


def check_stream_chat_sends_sse_headers_and_incremental() -> list[str]:
    """场景2：stream_chat 请求应带 X-DashScope-SSE: enable 头且 payload 含 incremental_output=True。"""
    issues: list[str] = []
    from core.llm.dashscope_client import DashScopeClient

    client = DashScopeClient(api_key="test_key")
    client.initialized = True

    fake_response = _FakeResponse(200, [b"data:[DONE]\n"])
    fake_session = _FakeSession(fake_response)
    client.session = fake_session

    async def run():
        async for _ in client.stream_chat([{"role": "user", "content": "hi"}]):
            pass

    try:
        asyncio.run(run())
    except Exception:
        pass

    if not fake_session.calls:
        issues.append("stream_chat 未发起任何 POST 请求")
        return issues

    call = fake_session.calls[0]
    headers = call.get("headers") or {}
    if headers.get("X-DashScope-SSE") != "enable":
        issues.append(
            f"stream_chat 请求未带 X-DashScope-SSE: enable 头，实际 headers={headers}"
        )

    payload = call.get("json") or {}
    params = payload.get("parameters") or {}
    if params.get("incremental_output") is not True:
        issues.append(
            f"stream_chat payload.parameters.incremental_output 应为 True，实际 {params.get('incremental_output')!r}"
        )

    if params.get("result_format") != "message":
        issues.append(
            f"stream_chat payload.parameters.result_format 应为 'message'，实际 {params.get('result_format')!r}"
        )

    return issues


def _make_sse_chunks(events: List[Dict[str, Any]]) -> List[bytes]:
    """把一组事件 dict 序列化为 DashScope SSE 字节块。"""
    chunks: List[bytes] = []
    for ev in events:
        chunks.append(b"data:" + json.dumps(ev, ensure_ascii=False).encode("utf-8") + b"\n")
    chunks.append(b"data:[DONE]\n")
    return chunks


def check_parse_sse_yields_incremental_content() -> list[str]:
    """场景3：_parse_dashscope_sse 能从多个 SSE 块中逐块 yield 增量 content。"""
    issues: list[str] = []
    from core.llm.dashscope_client import DashScopeClient

    client = DashScopeClient(api_key="test_key")

    events = [
        {
            "output": {
                "choices": [
                    {"message": {"content": "Hello", "role": "assistant"}, "finish_reason": "null"}
                ]
            },
            "usage": {},
        },
        {
            "output": {
                "choices": [
                    {"message": {"content": " world", "role": "assistant"}, "finish_reason": "null"}
                ]
            },
            "usage": {},
        },
        {
            "output": {
                "choices": [
                    {"message": {"content": "!", "role": "assistant"}, "finish_reason": "stop"}
                ]
            },
            "usage": {"total_tokens": 10},
        },
    ]

    fake_response = _FakeResponse(200, _make_sse_chunks(events))
    fake_session = _FakeSession(fake_response)
    client.session = fake_session
    client.initialized = True

    collected: List[Dict[str, Any]] = []

    async def run():
        async for chunk in client.stream_chat([{"role": "user", "content": "hi"}]):
            collected.append(chunk)

    try:
        asyncio.run(run())
    except Exception as e:
        issues.append(f"stream_chat 抛异常: {e}")
        return issues

    content_chunks = [c for c in collected if "content" in c]
    finish_chunks = [c for c in collected if "finish_reason" in c]

    if len(content_chunks) != 3:
        issues.append(
            f"应收到 3 个 content chunk，实际 {len(content_chunks)}：{content_chunks}"
        )
    else:
        # 拼接后应是 "Hello world!"
        combined = "".join(c["content"] for c in content_chunks)
        if combined != "Hello world!":
            issues.append(f"增量 content 拼接错误：期望 'Hello world!'，实际 {combined!r}")

    if not finish_chunks:
        issues.append("未收到 finish_reason chunk")
    else:
        if finish_chunks[-1].get("finish_reason") != "stop":
            issues.append(
                f"finish_reason 应为 'stop'，实际 {finish_chunks[-1].get('finish_reason')!r}"
            )

    return issues


def check_parse_sse_handles_null_finish_reason() -> list[str]:
    """场景4：finish_reason 字符串 'null' 不应被当作结束信号 yield。"""
    issues: list[str] = []
    from core.llm.dashscope_client import DashScopeClient

    client = DashScopeClient(api_key="test_key")

    events = [
        {
            "output": {
                "choices": [
                    {"message": {"content": "片段1", "role": "assistant"}, "finish_reason": "null"}
                ]
            },
            "usage": {},
        },
        {
            "output": {
                "choices": [
                    {"message": {"content": "片段2", "role": "assistant"}, "finish_reason": "null"}
                ]
            },
            "usage": {},
        },
        {
            "output": {
                "choices": [
                    {"message": {"content": "", "role": "assistant"}, "finish_reason": "stop"}
                ]
            },
            "usage": {"total_tokens": 5},
        },
    ]

    fake_response = _FakeResponse(200, _make_sse_chunks(events))
    fake_session = _FakeSession(fake_response)
    client.session = fake_session
    client.initialized = True

    collected: List[Dict[str, Any]] = []

    async def run():
        async for chunk in client.stream_chat([{"role": "user", "content": "hi"}]):
            collected.append(chunk)

    try:
        asyncio.run(run())
    except Exception as e:
        issues.append(f"stream_chat 抛异常: {e}")
        return issues

    finish_chunks = [c for c in collected if "finish_reason" in c]
    if len(finish_chunks) != 1:
        issues.append(
            f"应仅 yield 1 次 finish_reason（'null' 应被跳过），实际 {len(finish_chunks)}：{finish_chunks}"
        )

    # 不应有 content chunk 的值为 "null"
    for c in collected:
        if c.get("content") == "null":
            issues.append("不应把 'null' finish_reason 当作 content yield")

    return issues


def check_parse_sse_handles_error_response() -> list[str]:
    """场景5：SSE 错误响应（带 code 字段，无 output）应被识别为 error。"""
    issues: list[str] = []
    from core.llm.dashscope_client import DashScopeClient

    client = DashScopeClient(api_key="test_key")

    error_event = {
        "code": "InvalidApiKey",
        "message": "Invalid API-key provided.",
        "request_id": "xxx",
    }

    fake_response = _FakeResponse(200, [b"data:" + json.dumps(error_event).encode() + b"\n", b"data:[DONE]\n"])
    fake_session = _FakeSession(fake_response)
    client.session = fake_session
    client.initialized = True

    collected: List[Dict[str, Any]] = []

    async def run():
        async for chunk in client.stream_chat([{"role": "user", "content": "hi"}]):
            collected.append(chunk)

    try:
        asyncio.run(run())
    except Exception as e:
        issues.append(f"stream_chat 抛异常: {e}")
        return issues

    if not collected:
        issues.append("未收到任何 chunk，应至少 yield 一个 error")
    elif "error" not in collected[0]:
        issues.append(f"第一个 chunk 应包含 error 字段，实际 {collected[0]}")
    elif "DashScope Error" not in str(collected[0].get("error", "")):
        issues.append(f"error 内容未包含 'DashScope Error' 前缀，实际 {collected[0]}")

    return issues


def check_stream_chat_is_async_generator() -> list[str]:
    """场景6：stream_chat 必须是 async generator（用 yield 而非 return 单次结果）。"""
    issues: list[str] = []
    from core.llm.dashscope_client import DashScopeClient

    sig = inspect.signature(DashScopeClient.stream_chat)
    ret = sig.return_annotation
    # 返回类型注解应包含 AsyncGenerator
    ret_str = str(ret)
    if "AsyncGenerator" not in ret_str and "AsyncIterator" not in ret_str:
        # 即便没标注，也得是 generator function
        if not inspect.isasyncgenfunction(DashScopeClient.stream_chat):
            issues.append(
                f"stream_chat 应为 async generator function，实际返回注解={ret_str}"
            )

    if not inspect.isasyncgenfunction(DashScopeClient.stream_chat):
        issues.append("stream_chat 不是 async generator function（缺少 yield）")

    return issues


def main() -> int:
    print("=" * 70)
    print("P0-11 验证：dashscope_client.stream_chat 真流式实现")
    print("=" * 70)

    all_issues: list[str] = []
    checks = [
        ("stream_chat 不再调用 chat() 假装流式", check_stream_chat_does_not_call_chat),
        ("请求带 X-DashScope-SSE 头 + incremental_output=True", check_stream_chat_sends_sse_headers_and_incremental),
        ("SSE 多块增量 content 被逐块 yield", check_parse_sse_yields_incremental_content),
        ("字符串 'null' finish_reason 不被当作结束信号", check_parse_sse_handles_null_finish_reason),
        ("SSE 错误响应被识别为 error", check_parse_sse_handles_error_response),
        ("stream_chat 是 async generator function", check_stream_chat_is_async_generator),
    ]

    for name, fn in checks:
        print(f"\n[检查] {name}")
        try:
            issues = fn()
        except Exception as e:
            issues = [f"检查本身抛异常: {type(e).__name__}: {e}"]

        if issues:
            for i in issues:
                print(f"  FAIL: {i}")
            all_issues.extend(issues)
        else:
            print("  PASS")

    print("\n" + "=" * 70)
    if all_issues:
        print(f"结果：失败（{len(all_issues)} 项问题）")
        return 1
    print("结果：通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
