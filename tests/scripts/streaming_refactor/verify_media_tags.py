"""
验证 stream_conversation_events 的媒体标签处理：
1. chunk 发送时剥离 [MEME] 标签文本
2. **按标签位置**推送 image_result 事件：标签挂在哪句话末尾，图就紧跟在那句话之后，
   而不是等整段文字发完才补图（人设提示词对模型的承诺 / QQ 段感知发送的行为）
3. 标签被 token 切开（"[MEM" + "E:anime]"）时不泄漏半个标签，位置同样正确
4. done 事件正常

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
    """模拟 LLM 流式：按给定 token 逐个 yield，最后给一个 done 标记。"""

    def __init__(self, pieces):
        self._pieces = list(pieces)
        self._normalize_conversation_id = lambda cid: cid or "default"
        self._normalize_request_id = lambda rid, fallback=None: rid or fallback or "rid"
        self._conversation_idempotency_cache = None
        self._active_tasks_lock = asyncio.Lock()
        self._active_tasks = {}
        self._resource_monitor = FakeMonitor()

    async def stream_generate_response(self, **kwargs):
        for piece in self._pieces:
            yield {"type": "token", "content": piece, "done": False}
        yield {
            "done": True,
            "content": "".join(self._pieces),
            "emotion": {"primary_emotion": "开心"},
            "model_path": "local",
            "is_cloud": False,
        }


async def _collect_events(pieces) -> list[dict]:
    """跑一遍流式通道，返回全部事件。"""
    from core.services.aveline.stream_orchestrator import stream_conversation_events

    events = []
    async for evt in stream_conversation_events(
        service=FakeService(pieces),
        user_input="测试",
        conversation_id="cid_test",
        request_id="rid_test",
        message_id="mid_test",
        skip_active_care=True,
    ):
        events.append(evt)
    return events


def _text_of(evt: dict) -> str:
    if evt.get("type") == "message" and evt.get("subtype") == "response_chunk":
        return str(evt.get("content") or "")
    return ""


async def _assert_positional(pieces, label: str) -> str:
    """断言：至少一个正文 chunk 在图之前、至少一个在图之后（即"图在句中"）。"""
    events = await _collect_events(pieces)
    merged = "".join(_text_of(evt) for evt in events)
    image_indices = [i for i, evt in enumerate(events) if evt.get("type") == "image_result"]
    text_indices = [i for i, evt in enumerate(events) if _text_of(evt)]

    assert image_indices, f"{label}: 未推送 image_result"
    assert text_indices, f"{label}: 未收到任何正文 chunk"
    first_image = image_indices[0]
    assert [i for i in text_indices if i < first_image], (
        f"{label}: 图之前没有任何正文（图被提前发了）"
    )
    assert [i for i in text_indices if i > first_image], (
        f"{label}: 图之后没有任何正文（图还是被推到整段文字末尾了）"
    )
    assert "MEME" not in merged, f"{label}: 正文泄漏了 [MEME] 标签: {merged!r}"
    return merged


async def main():
    from core.services.aveline.stream_orchestrator import stream_conversation_events

    # 生成一张 1x1 PNG 作为占位图
    fake_png = Path(__file__).parent / "fake_meme.png"
    if not fake_png.exists():
        fake_png.write_bytes(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        ))

    # 让 pick_meme_image 返回占位图（不依赖真实表情包目录）
    import clients.bots.qq.media_tags as mt
    mt.pick_meme_image = lambda cat: fake_png

    published_files: list[Path] = []
    try:
        # ---------- 1. 既有行为：剥离标签 + 推送 image_result + done ----------
        saw_stripped_chunk = False
        saw_raw_label = False
        saw_image_result = False
        saw_done = False
        merged_text = ""

        async for evt in stream_conversation_events(
            service=FakeService(["这是", "一段带", "表情包[MEME:anime]", "的测试", "文本"]),
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
                url = data.get("image_url", "")
                # 表情包改为静态 URL 下发：体积小、保留 GIF、前端可缓存
                assert url.startswith("/output/image/memes/"), (
                    f"image_url 应为静态 URL，实际前 60 字符={url[:60]}"
                )
                assert (ROOT / url.lstrip("/")).is_file(), f"静态文件不存在: {url}"
                assert "thumbnail_base64" not in data, "不应再下发重复的 base64 缩略图"
                published_files.append(ROOT / url.lstrip("/"))
                print(f"  [OK] image_result 推送 source={data.get('source')} url={url}")
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

        # ---------- 2. 图在句中：标签之后还有正文 ----------
        print("\n[2] 表情包按标签位置下发（图在它那句话之后，不是整段文字之后）")
        merged = await _assert_positional(
            ["好呀", "那我", "先忙啦[MEME:anime]", "晚点", "再找你"], "句中插图"
        )
        print(f"  [OK] 正文按顺序拼回: {merged!r}")
        print("  [OK] image_result 之前与之后都有正文（图没被推到末尾）")

        # ---------- 3. 标签被 token 切开：不能泄漏半个标签 ----------
        print("\n[3] 标签被 token 切开时留缓冲，不泄漏 '[MEM'")
        merged = await _assert_positional(["哈哈[MEM", "E:anime]真的", "太好笑了"], "半个标签")
        assert "[" not in merged, f"泄漏了半个标签: {merged!r}"
        print(f"  [OK] 正文按顺序拼回且无残留标签: {merged!r}")

        # ---------- 4. 普通方括号不能被当成"半个标签"扣住 ----------
        print("\n[4] 正文里的普通方括号照常发出（不会被当成半个标签扣住）")
        events = await _collect_events(["（笑）[笑]", "真的吗"])
        merged = "".join(_text_of(evt) for evt in events)
        assert merged == "（笑）[笑]真的吗", f"普通方括号被吞掉或错位: {merged!r}"
        print(f"  [OK] 普通方括号原样保留: {merged!r}")

        print("\n✅ media tag 处理验证通过: 标签已剥离 + 表情包按位置推送 + 半个标签留缓冲")
    finally:
        # 清理占位图与落到 output/image/memes/ 的静态副本。
        # 清理失败不算验证失败（个别环境会把 unlink 重定向到回收站并失败），只提示。
        for f in [fake_png, *published_files]:
            try:
                if f.exists():
                    f.unlink()
            except OSError as cleanup_error:
                print(f"  [WARN] 清理临时文件失败（不影响验证结论）: {f} -> {cleanup_error}")


if __name__ == "__main__":
    asyncio.run(main())
