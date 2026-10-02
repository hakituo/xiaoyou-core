"""验证请求体 gzip：中间件解压链路 + 真实历史体积的压缩收益。

背景：聊天请求会把最近若干条历史当 history_override 塞进 body，实测 44-95KB。
走 Cloudflare Tunnel 时这段上传要 0.75s 以上（100KB body 比 1KB body 首字节多 0.75s），
客户端因此对请求体做 gzip，后端由 core/middleware/gzip_request.py 解压。

运行：venv_core/Scripts/python.exe tests/scripts/api/verify_gzip_request_body.py
"""

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core.middleware.gzip_request import GzipRequestBodyMiddleware  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def check_middleware() -> None:
    app = FastAPI()
    app.add_middleware(GzipRequestBodyMiddleware)

    @app.post("/echo")
    async def echo(request: Request):
        body = await request.body()
        return {"length": len(body), "content_encoding": request.headers.get("content-encoding")}

    client = TestClient(app)
    raw = json.dumps({"text": "历史" * 3000, "stream": True}, ensure_ascii=False).encode()

    resp = client.post(
        "/echo",
        content=gzip.compress(raw),
        headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.status_code
    assert resp.json()["length"] == len(raw), "下游拿到的不是解压后的 body"
    assert resp.json()["content_encoding"] is None, "content-encoding 未清理"
    print(f"  [OK] gzip 请求体被正确解压：压缩 {len(gzip.compress(raw))}B -> 还原 {len(raw)}B")

    plain = b'{"a":1}'
    resp2 = client.post("/echo", content=plain, headers={"Content-Type": "application/json"})
    assert resp2.status_code == 200 and resp2.json()["length"] == len(plain)
    print("  [OK] 未压缩请求体原样透传")

    resp3 = client.post("/echo", content=b"broken", headers={"Content-Encoding": "gzip"})
    assert resp3.status_code == 400, resp3.status_code
    print("  [OK] 非法 gzip 返回 400")


def check_real_history_ratio() -> None:
    """量一下真实会话的最近 200 条历史压缩收益（只读，不打印内容）。"""
    files = sorted(
        (PROJECT_ROOT / "companion_data").glob("**/chat_history/**/*.jsonl"),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )[:1]
    if not files:
        print("  [跳过] 没找到 chat_history 样本")
        return

    rows = []
    with files[0].open(encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            rows.append({"role": "user", "content": str(event.get("content", ""))})

    window = rows[-200:]
    payload = json.dumps(
        {"text": "hi", "session_id": "x", "model": "default", "stream": True,
         "history_override": window},
        ensure_ascii=False,
    ).encode()
    compressed = gzip.compress(payload, 6)
    print(
        f"  [OK] 真实样本 {files[0].name}：最近 {len(window)} 条 -> 请求体 "
        f"{len(payload) / 1024:.1f}KB，gzip 后 {len(compressed) / 1024:.1f}KB"
        f"（{len(payload) / len(compressed):.1f}x）"
    )


def main() -> None:
    check_middleware()
    check_real_history_ratio()
    print("PASS: 请求体 gzip 链路与收益符合预期")


if __name__ == "__main__":
    main()
