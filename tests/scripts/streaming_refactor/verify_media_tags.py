"""
验证 stream_conversation_events 的媒体标签处理：
1. chunk 发送时剥离 [MEME] 标签文本
2. 响应结束时推送 image_result 事件（含表情包 base64）
3. done 事件正常

运行：
    venv_core\\Scripts\\python.exe tests\\scripts\\streaming_refactor\\verify_media_tags.py
"""
import asyncio
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


class FakeMonitor:
    def record_metric(self, *args, **kwargs):
        pass


class FakeService:
    def __init__(self):
        self._normalize_conversation_id = lambda cid: cid or "default"
        self._normalize_request_id = lambda rid, fallback=None: rid or fallback or "rid"
        self._conversation_idempotency_cache = None
        self._active_tasks_lock = asyncio.Lock()
        self._active_tasks = {}
        self._resource_monitor = FakeMonitor()

    async def stream_generate_response(self, **kwargs):
        # 模拟 LLM 流式：先文本 + [MEME] 标签，再文本
        for piece in ["这是", "一段带", "表情包[MEME:anime]", "的测试", "文本"]:
            yield {"type": "token", "content": piece, "done": False}
        yield {
            "done": True,
            "content": "这是一段带表情包[MEME:anime]的测试文本",
            "emotion": {"primary_emotion": "开心"},
            "model_path": "local",
            "is_cloud": False,
        }


async def main():
    from core.services.aveline.stream_orchestrator import stream_conversation_events

    service = FakeService()

    # 生成一张 1x1 PNG 作为占位图
    fake_png = Path(__file__).parent / "fake_meme.png"
    if not fake_png.exists():
        fake_png.write_bytes(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        ))

    # 让 pick_meme_image 返回占位图（不依赖真实表情包目录）
    import clients.bots.qq.media_tags as mt
    mt.pick_meme_image = lambda cat: fake_png

    try:
        saw_stripped_chunk = False
        saw_raw_label = False
        saw_image_result = False
        saw_done = False
        merged_text = ""

        async for evt in stream_conversation_events(
            service=service,
            user_input="测试",
            conversation_id="cid_test",
            request_id="rid_test",
            message_id="mid_test",
            skip_active_care=True,
        ):
            if evt.get("type") == "message" and evt.get("subtype") == "response_chunk":
                content = evt.get("content", "")
                merged_text += content
                if "MEME" in content:
                    saw_raw_label = True
                if "表情包" in content:
                    saw_stripped_chunk = True
            elif evt.get("type") == "image_result":
                saw_image_result = True
                data = evt.get("data", {})
                assert data.get("source") == "meme", f"source={data.get('source')}"
                assert data.get("image_url", "").startswith("data:image/jpeg;base64,"), "image_url 应为 base64"
                print(f"  [OK] image_result 推送 source={data.get('source')} url前40={data.get('image_url', '')[:40]}...")
            elif evt.get("type") == "message" and evt.get("subtype") == "response_done":
                saw_done = True

        print(f"  [{'OK' if saw_stripped_chunk else 'FAIL'}] 收到剥离后的文本 chunk (merged={merged_text!r})")
        print(f"  [{'OK' if not saw_raw_label else 'FAIL'}] chunk 文本未泄漏 [MEME] 标签")
        print(f"  [{'OK' if saw_image_result else 'FAIL'}] 收到 image_result 表情包事件")
        print(f"  [{'OK' if saw_done else 'FAIL'}] 收到 response_done")

        assert saw_stripped_chunk, "剥离后文本未发送"
        assert not saw_raw_label, "chunk 文本泄漏了 [MEME] 标签"
        assert saw_image_result, "未推送 image_result"
        assert saw_done, "未收到 done"

        print("\n✅ media tag 处理验证通过: 标签已剥离 + 表情包已推送")
    finally:
        # 清理占位图
        if fake_png.exists():
            fake_png.unlink()


if __name__ == "__main__":
    asyncio.run(main())
