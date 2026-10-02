import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.llm.siliconflow_client import SiliconFlowClient


def _build_client(chunks):
    """构造一个返回指定 SSE 分片的 SiliconFlow 客户端"""

    async def iter_any():
        for chunk in chunks:
            yield chunk

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.content = MagicMock()
    mock_response.content.iter_any = iter_any

    mock_post_ctx = AsyncMock()
    mock_post_ctx.__aenter__.return_value = mock_response
    mock_post_ctx.__aexit__.return_value = None

    mock_session = MagicMock()
    mock_session.post.return_value = mock_post_ctx

    client = SiliconFlowClient(api_key="fake")
    client._get_session = AsyncMock(return_value=mock_session)
    client.initialized = True
    return client


def _sse(payload: dict) -> bytes:
    import json

    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")


@pytest.mark.asyncio
async def test_siliconflow_reasoning_content_is_streamed_separately():
    """推理内容以独立 reasoning 事件透出，不再混入正文"""
    chunks = [
        _sse({"choices": [{"delta": {"reasoning_content": "Deep"}}]}),
        _sse({"choices": [{"delta": {"reasoning_content": "Seek"}}]}),
        _sse({"choices": [{"delta": {"content": "Hello"}}]}),
        b"data: [DONE]\n\n",
    ]

    client = _build_client(chunks)

    reasoning_parts = []
    content_parts = []
    async for chunk in client.stream_chat([{"role": "user", "content": "hi"}]):
        assert "error" not in chunk, f"不应产生错误分片: {chunk}"
        if "reasoning" in chunk:
            reasoning_parts.append(chunk["reasoning"])
        if "content" in chunk:
            content_parts.append(chunk["content"])

    assert "".join(reasoning_parts) == "DeepSeek"
    assert "".join(content_parts) == "Hello"


@pytest.mark.asyncio
async def test_siliconflow_stream_handles_malformed_chunk():
    """无法解析的分片不应中断后续流式输出"""
    chunks = [
        b"data: {not a json}\n\n",
        _sse({"choices": [{"delta": {"content": "Hi"}}]}),
        b"data: [DONE]\n\n",
    ]

    client = _build_client(chunks)

    collected = []
    async for chunk in client.stream_chat([{"role": "user", "content": "hi"}]):
        if "content" in chunk:
            collected.append(chunk["content"])

    assert collected == ["Hi"]


@pytest.mark.asyncio
async def test_siliconflow_stream_reports_http_error():
    """非 200 响应返回错误分片而不是抛异常"""
    mock_response = MagicMock()
    mock_response.status = 401
    mock_response.text = AsyncMock(return_value="unauthorized")

    mock_post_ctx = AsyncMock()
    mock_post_ctx.__aenter__.return_value = mock_response
    mock_post_ctx.__aexit__.return_value = None

    mock_session = MagicMock()
    mock_session.post.return_value = mock_post_ctx

    client = SiliconFlowClient(api_key="fake")
    client._get_session = AsyncMock(return_value=mock_session)
    client.initialized = True

    chunks = []
    async for chunk in client.stream_chat([{"role": "user", "content": "hi"}]):
        chunks.append(chunk)

    assert chunks and "error" in chunks[0]
    assert "401" in chunks[0]["error"]


if __name__ == "__main__":
    asyncio.run(test_siliconflow_reasoning_content_is_streamed_separately())
