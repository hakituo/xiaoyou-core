"""用 mock SSE 流验证 stream_chat 的 usage 全链路。

步骤：
1) 构造 DeepSeekClient（不发真实请求，只初始化）
2) mock aiohttp 响应：最后一个 SSE chunk 是无 choices 的 usage 块（含 prompt_cache_hit_tokens /
   prompt_cache_miss_tokens），格式就是 DeepSeek v4 真实结尾：
   data: {"usage": {"prompt_tokens": 416, "prompt_cache_hit_tokens": 384, "prompt_cache_miss_tokens": 32, ...}}
   data: [DONE]
3) 调用 stream_chat，断言 prompt_cache_stats.log 追加了一条 mode=stream 记录且 level=S/A。

注意：本脚本不动真实网络，但需要 aiohttp 依赖（项目已有）。
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, r"D:\AI\xiaoyou-core")


def _build_sse_bytes() -> bytes:
    """模拟流式响应，按 DeepSeek v4 include_usage=true 的实际顺序。"""
    chunks = []
    # 几个 content delta
    tokens = ["你", "好", "，", "我", "是", "Aveline", "。"]
    for i, tok in enumerate(tokens):
        chunks.append(b"data: " + json.dumps({
            "id": "chatcmpl-test",
            "choices": [{"index": 0, "delta": {"role": "assistant"} if i == 0 else {"content": tok}, "finish_reason": None}],
        }).encode("utf-8"))
    # finish chunk（没有 delta.content，只有 finish_reason）
    chunks.append(b"data: " + json.dumps({
        "id": "chatcmpl-test",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }).encode("utf-8"))
    # 单独的 usage 块（无 choices）——这就是 include_usage=true 时最后一个数据块
    chunks.append(b"data: " + json.dumps({
        "id": "chatcmpl-test",
        "choices": [],
        "usage": {
            "prompt_tokens": 416,
            "completion_tokens": 8,
            "total_tokens": 424,
            "prompt_cache_hit_tokens": 384,
            "prompt_cache_miss_tokens": 32,
        },
    }).encode("utf-8"))
    chunks.append(b"data: [DONE]")
    return b"\n\n".join(chunks) + b"\n\n"


async def _run() -> int:
    import tempfile
    from core.llm.openai_compat import DeepSeekClient
    from core.llm import llm_logger

    # 临时日志文件，避免污染真实 logs/prompt_cache_stats.log
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_log = Path(tmpdir) / "prompt_cache_stats.log"
        with patch.object(llm_logger, "_prompt_cache_stats_log", tmp_log):
            client = DeepSeekClient(
                api_key="placeholder-not-a-real-key",
                base_url="http://127.0.0.1:9999",
                model="deepseek-v4-flash",
            )
            # 不发真实请求，mock ClientSession.post 直接返回 mock aiohttp Response
            sse_bytes = _build_sse_bytes()

            class _FakeContent:
                def __init__(self, data: bytes):
                    self._pieces = [data[: len(data)//3], data[len(data)//3 : 2*len(data)//3], data[2*len(data)//3 :]]

                async def iter_any(self):
                    for p in self._pieces:
                        if p:
                            yield p

            class _FakeResponse:
                status = 200

                def __init__(self):
                    self.content = _FakeContent(sse_bytes)

                async def text(self):
                    return ""

                async def release(self):
                    pass

            fake_resp = _FakeResponse()

            async def _fake_post(*args, **kwargs):
                # 断言 stream_options 被注入
                payload = kwargs.get("json") or {}
                print(f"[assert] stream={payload.get('stream')!r} stream_options={payload.get('stream_options')!r}")
                assert payload.get("stream") is True
                assert payload.get("stream_options") == {"include_usage": True}, \
                    f"stream_options 未正确注入: {payload.get('stream_options')}"
                return fake_resp

            fake_session = MagicMock()
            fake_session.post = _fake_post
            # 让 client._session 属性返回这个 mock session（DeepSeekClient 在 initialized=True 时用）
            client._initialized = True
            client._session = fake_session

            messages = [{"role": "user", "content": "你好"}]
            produced: list = []
            async for chunk in client.stream_chat(messages):
                produced.append(chunk)

            print(f"[result] 收到 chunk 数: {len(produced)}；内容: {' '.join(c for c in produced if isinstance(c, str))[:50]}")

            # 读临时 stats log
            if not tmp_log.exists():
                print("[FAIL] prompt_cache_stats.log 未被写入")
                return 1

            lines = tmp_log.read_text(encoding="utf-8").strip().splitlines()
            print(f"[result] stats log 行数: {len(lines)}")
            if not lines:
                print("[FAIL] 日志为空")
                return 1
            last = json.loads(lines[-1])
            print(f"[result] 最后一条 stats: {json.dumps(last, ensure_ascii=False)[:300]}")
            if last.get("mode") != "stream":
                print(f"[FAIL] mode 不是 stream: {last.get('mode')}")
                return 1
            if last.get("level") not in ("S", "A", "B", "C", "D"):
                print(f"[FAIL] level 无效: {last.get('level')}")
                return 1
            print("[OK] stream usage 全链路通过")
            return 0


if __name__ == "__main__":
    rc = asyncio.run(_run())
    sys.exit(rc)
