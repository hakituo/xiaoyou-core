"""请求体 gzip 解压中间件。

回归背景：Android 客户端对聊天请求体做 gzip（body 里带最多 200 条历史，
实测 44-95KB，隧道上传要 0.75s 以上）。Starlette 只有响应侧的 GZipMiddleware，
请求侧必须自己解压，否则下游拿到的是一堆压缩字节。
"""

import gzip
import json

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from core.middleware.gzip_request import GzipRequestBodyMiddleware


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(GzipRequestBodyMiddleware)

    @app.post("/echo")
    async def echo(request: Request):
        body = await request.body()
        return {
            "length": len(body),
            "content_length": request.headers.get("content-length"),
            "content_encoding": request.headers.get("content-encoding"),
        }

    @app.post("/json")
    async def json_ep(payload: dict):
        return {"received": payload}

    return TestClient(app)


def _gzip(payload: bytes) -> bytes:
    return gzip.compress(payload)


def test_gzip_body_is_decompressed_for_downstream(client):
    raw = json.dumps({"text": "你好" * 1000, "stream": True}, ensure_ascii=False).encode()
    response = client.post(
        "/echo",
        content=_gzip(raw),
        headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["length"] == len(raw)
    # content-length 必须换成解压后的长度，否则下游的体积校验看到的是压缩体积
    assert body["content_length"] == str(len(raw))
    assert body["content_encoding"] is None


def test_downstream_json_parsing_sees_decompressed_payload(client):
    raw = json.dumps({"text": "history-override"}).encode()
    response = client.post(
        "/json",
        content=_gzip(raw),
        headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["received"]["text"] == "history-override"


def test_plain_body_passes_through(client):
    raw = b'{"a":1}'
    response = client.post("/echo", content=raw, headers={"Content-Type": "application/json"})
    assert response.status_code == 200
    assert response.json()["length"] == len(raw)


def test_x_gzip_alias_is_accepted(client):
    raw = b'{"a":2}'
    response = client.post("/echo", content=_gzip(raw), headers={"Content-Encoding": "x-gzip"})
    assert response.status_code == 200
    assert response.json()["length"] == len(raw)


def test_broken_gzip_body_returns_400(client):
    response = client.post("/echo", content=b"not-a-gzip-stream", headers={"Content-Encoding": "gzip"})
    assert response.status_code == 400
