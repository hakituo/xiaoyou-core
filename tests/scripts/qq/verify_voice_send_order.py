"""验证 QQ 语音发送会等待 NapCat 确认后再放行后续文字。

运行：venv_core\\Scripts\\python.exe tests\\scripts\\qq\\verify_voice_send_order.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from clients.bots.qq.transport import NapcatTransport  # noqa: E402


class _FakeNapcatWebSocket:
    """模拟 NapCat：语音 action 延迟确认，普通文字立即记录。"""

    def __init__(self, transport: NapcatTransport) -> None:
        self.transport = transport
        self.events: list[str] = []
        self._tasks: list[asyncio.Task] = []

    async def send(self, raw_payload: str) -> None:
        payload = json.loads(raw_payload)
        message = str(payload.get("params", {}).get("message") or "")
        echo = payload.get("echo")
        if echo:
            self.events.append("voice_submitted")
            self._tasks.append(asyncio.create_task(self._confirm_later(str(echo))))
        elif message == "后续文字":
            self.events.append("text_submitted")

    async def _confirm_later(self, echo: str) -> None:
        await asyncio.sleep(0.05)
        self.events.append("voice_confirmed")
        await self.transport.handle_message(
            json.dumps({"status": "ok", "retcode": 0, "data": {"message_id": 1}, "echo": echo})
        )

    async def finish(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks)


async def _verify() -> None:
    cfg = SimpleNamespace(napcat_ws_url="ws://test", napcat_access_token="")
    transport = NapcatTransport(cfg)
    websocket = _FakeNapcatWebSocket(transport)
    transport.napcat_ws = websocket

    voice_ok = await transport.send_message(
        "private_1",
        "[CQ:record,file=file:///tmp/test.wav]",
        wait_for_result=True,
    )
    if not voice_ok:
        raise AssertionError("语音 action 已成功确认，但 send_message 返回失败")

    text_ok = await transport.send_message("private_1", "后续文字")
    if not text_ok:
        raise AssertionError("后续文字发送失败")

    await websocket.finish()
    expected = ["voice_submitted", "voice_confirmed", "text_submitted"]
    if websocket.events != expected:
        raise AssertionError(f"发送顺序错误: expected={expected}, actual={websocket.events}")

    print("[PASS] NapCat 确认语音投递后才发送后续文字")


if __name__ == "__main__":
    asyncio.run(_verify())
