"""
验证「视频消息」全链路打通（后端协议 + Android 端接线）。

链路：
    后端 video_result（WS / SSE 两条通道）
      → Android WebSocketMessage.VideoResult / StreamEvent.VideoResult
      → Room messages.videoUrl（v4→v5 迁移）
      → MessageBubble → VideoMessageBubble（ExoPlayer）
    反向：用户在聊天页选视频 → /api/v1/media/upload → output/video/uploads
      → 用户消息以 [视频: url] 发出，本地气泡按 videoUrl 渲染播放器

后端部分做真实运行时断言；Android 部分无法在 CI 里跑 Gradle，
改为对源码做静态接线断言（缺一处就说明链路断了）。

运行：
    venv_core\\Scripts\\python.exe tests\\scripts\\media_video_message\\verify_video_message_pipeline.py
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

ANDROID_ROOT = ROOT / "clients" / "frontend" / "aveline-android" / "android" / "app" / "src" / "main" / "java" / "com" / "aveline" / "ai" / "mobile"

_FAILED: list[str] = []


def check(name: str, fn):
    try:
        fn()
    except Exception as e:  # noqa: BLE001 - 验证脚本需要把所有失败一次性报全
        _FAILED.append(f"{name}: {type(e).__name__}: {e}")
        print(f"  [FAIL] {name}: {e}")
    else:
        print(f"  [ok]   {name}")


def require(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)


# ============================================================
# 1. media_tags：视频静态资源化 + 私密库推送开关
# ============================================================

def check_video_path_to_url():
    from clients.bots.qq import media_tags

    tmp_dir = ROOT / "output" / "video"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_dir / "_verify_source_video.mp4"
    try:
        src.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        url = media_tags.video_path_to_url(src)
        require(url is not None, "视频转静态 URL 返回 None")
        require(url.startswith("/output/video/"), f"URL 前缀不对: {url}")
        require(url.endswith(".mp4"), f"URL 未保留扩展名: {url}")
        require((ROOT / url.lstrip("/")).is_file(), f"静态文件不存在: {url}")

        # 同一个源重复调用应返回同一 URL（按源路径哈希，不重复落盘）
        require(media_tags.video_path_to_url(src) == url, "同一视频两次调用返回了不同 URL")
    finally:
        src.unlink(missing_ok=True)


def check_video_path_to_url_rejects_junk():
    from clients.bots.qq import media_tags

    (ROOT / "output" / "video").mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "output" / "video" / "_verify_not_video.txt"
    try:
        tmp.write_text("not a video")
        require(
            media_tags.video_path_to_url(tmp) is None,
            "非视频扩展名不该被复制进对外静态目录",
        )
    finally:
        tmp.unlink(missing_ok=True)

    require(
        media_tags.video_path_to_url(ROOT / "output" / "__missing__.mp4") is None,
        "文件不存在时应返回 None 而不是发坏地址给前端",
    )


def check_private_video_gate_default_on():
    from clients.bots.qq import media_tags

    saved = os.environ.pop("XIAOYOU_PUSH_PRIVATE_VIDEO", None)
    try:
        require(
            media_tags.private_video_push_enabled() is True,
            "私密视频默认必须开启推送（用户自己的后端 + 自建 App 闭环）",
        )
        os.environ["XIAOYOU_PUSH_PRIVATE_VIDEO"] = "0"
        require(media_tags.private_video_push_enabled() is False, "显式关闭后应为 False")
        os.environ["XIAOYOU_PUSH_PRIVATE_VIDEO"] = "1"
        require(media_tags.private_video_push_enabled() is True, "显式开启后应为 True")
    finally:
        os.environ.pop("XIAOYOU_PUSH_PRIVATE_VIDEO", None)
        if saved is not None:
            os.environ["XIAOYOU_PUSH_PRIVATE_VIDEO"] = saved


def check_video_tag_parsed():
    from clients.bots.qq.media_tags import extract_media_segments

    segments = extract_media_segments("看看这个[VIDEO]")
    require(any(seg.video_count > 0 for seg in segments), "[VIDEO] 没被解析成 video_count")


# ============================================================
# 2. WebSocket 通道：video_result 出口
# ============================================================

class _FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload):
        self.sent.append(payload)


def check_ws_video_result_payload():
    from core.interfaces.websocket.adapters.streaming import StreamingHandler

    (ROOT / "output" / "video").mkdir(parents=True, exist_ok=True)
    src = ROOT / "output" / "video" / "_verify_ws_video.mp4"
    try:
        src.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        ws = _FakeWebSocket()
        asyncio.run(
            StreamingHandler(adapter=None)._send_media_video_result(
                ws,
                src,
                source="video",
                msg_id="m1",
                conversation_id="c1",
                request_id="r1",
            )
        )
        require(len(ws.sent) == 1, f"期望推送 1 条，实际 {len(ws.sent)} 条")
        payload = ws.sent[0]
        require(payload["type"] == "video_result", f"type 不对: {payload.get('type')}")
        video_url = payload["data"]["video_url"]
        require(video_url.startswith("/output/video/"), f"video_url 不对: {video_url}")
        require(payload["data"]["success"] is True, "success 字段应为 True")
        # 消息体积必须小：只发 URL，绝不把视频字节塞进 WS
        require(len(str(payload)) < 1024, "video_result 消息过大，疑似把视频内容塞进去了")
    finally:
        src.unlink(missing_ok=True)


def check_ws_video_result_skips_bad_path():
    from core.interfaces.websocket.adapters.streaming import StreamingHandler

    ws = _FakeWebSocket()
    asyncio.run(
        StreamingHandler(adapter=None)._send_media_video_result(
            ws,
            ROOT / "output" / "__missing__.mp4",
            source="video",
            msg_id="m1",
            conversation_id="c1",
            request_id="r1",
        )
    )
    require(not ws.sent, "文件不存在时不应推送任何 video_result")


def check_media_tag_strip_covers_video():
    from core.interfaces.websocket.adapters.streaming import _MEDIA_TAG_STRIP_RE
    from core.services.aveline.stream_orchestrator import _MEDIA_TAG_STRIP_RE as SSE_RE

    for name, regex in (("WS", _MEDIA_TAG_STRIP_RE), ("SSE", SSE_RE)):
        require(
            regex.sub("", "看看这个[VIDEO]").strip() == "看看这个",
            f"{name} 通道没剥离 [VIDEO] 标签，前端会显示裸标签",
        )
        require(
            regex.sub("", "哈哈[MEME]").strip() == "哈哈",
            f"{name} 通道剥离 [MEME] 的既有行为被改坏了",
        )


# ============================================================
# 3. SSE 通道：video_result 事件
# ============================================================

def _run_sse_video_events(text: str) -> list[dict]:
    """跑一遍 SSE 通道的媒体切分，返回事件列表（含正文 chunk 与 video_result）。"""
    from core.services.aveline import stream_orchestrator as so

    async def _collect():
        events, _pending = await so._drain_media_stream(None, text, "c1", "r1", "m1", final=True)
        return events

    return asyncio.run(_collect())


def _video_events(events: list[dict]) -> list[dict]:
    return [evt for evt in events if evt.get("type") == "video_result"]


def check_sse_video_gate_off_switch():
    saved = os.environ.pop("XIAOYOU_PUSH_PRIVATE_VIDEO", None)
    try:
        os.environ["XIAOYOU_PUSH_PRIVATE_VIDEO"] = "0"
        require(
            _video_events(_run_sse_video_events("看看这个[VIDEO]")) == [],
            "显式关闭时 SSE 通道不应产出 video_result",
        )
    finally:
        os.environ.pop("XIAOYOU_PUSH_PRIVATE_VIDEO", None)
        if saved is not None:
            os.environ["XIAOYOU_PUSH_PRIVATE_VIDEO"] = saved


def check_sse_video_result_event():
    from clients.bots.qq import media_tags

    saved = os.environ.pop("XIAOYOU_PUSH_PRIVATE_VIDEO", None)
    src_dir = Path(media_tags.VIDEO_ROOT) if str(media_tags.VIDEO_ROOT) else None
    if src_dir is None or not src_dir.is_dir():
        raise AssertionError(
            "本地视频库未配置（sensitive_paths.VIDEO_ROOT），无法验证推送；"
            "这是环境限制，不是代码问题"
        )
    try:
        # 默认开启，不需要额外设环境变量
        events = _run_sse_video_events("看看这个[VIDEO]")
        videos = _video_events(events)
        require(bool(videos), "默认开启时 SSE 通道应产出 video_result")
        require(videos[0]["type"] == "video_result", f"type 不对: {videos[0].get('type')}")
        require(
            videos[0]["data"]["video_url"].startswith("/output/video/"),
            f"video_url 不对: {videos[0]['data'].get('video_url')}",
        )
    finally:
        os.environ.pop("XIAOYOU_PUSH_PRIVATE_VIDEO", None)
        if saved is not None:
            os.environ["XIAOYOU_PUSH_PRIVATE_VIDEO"] = saved


def check_sse_media_positional_order():
    """媒体按标签位置下发：标签之前有正文、之后也有正文，而不是等整段文字发完再补。

    旧实现是响应结束后统一补发（`_emit_media_results`），图永远落在整段文字末尾；
    现在改为流式过程中按标签位置切分（`_drain_media_stream`），这里钉住新行为。
    """
    events = _run_sse_video_events("先说这句[VIDEO]再说这句")
    kinds = [
        "text" if evt.get("type") == "message" else str(evt.get("type"))
        for evt in events
    ]
    require("video_result" in kinds, f"未产出 video_result: {kinds}")
    first_media = kinds.index("video_result")
    require(
        any(k == "text" for k in kinds[:first_media]),
        f"媒体之前没有正文（媒体被提前发了）: {kinds}",
    )
    require(
        any(k == "text" for k in kinds[first_media + 1:]),
        f"媒体之后没有正文（媒体仍被推到整段文字末尾）: {kinds}",
    )


# ============================================================
# 4. 上传接口：视频落到 output/video/uploads
# ============================================================

class _FakeUploadFile:
    def __init__(self, filename: str, content_type: str, content: bytes):
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self):
        return self._content


def check_upload_routes_video():
    from routers.v1.media import upload_file

    result = asyncio.run(
        upload_file(_FakeUploadFile("clip.mp4", "video/mp4", b"\x00\x00\x00\x18ftypmp42"))
    )
    require(result.get("status") == "success", f"上传失败: {result}")
    rel = result["data"]["file_url"]
    require("/video/uploads/" in rel, f"视频未落到 output/video/uploads: {rel}")
    require(rel.startswith("output/") or rel.startswith("/output/"), f"路径格式不对: {rel}")
    # /output 已被静态挂载，Android 端 ExoPlayer 拼后端地址后可直接拉
    require((ROOT / rel.lstrip("/")).is_file(), f"上传文件不存在: {rel}")


def check_upload_still_routes_audio():
    from routers.v1.media import upload_file

    result = asyncio.run(upload_file(_FakeUploadFile("a.wav", "audio/wav", b"RIFF")))
    rel = result["data"]["file_url"]
    require("voice/uploads" in rel, f"音频落盘位置被改坏: {rel}")


# ============================================================
# 5. Android 端接线（静态断言，Gradle 由用户在 Android Studio 里跑）
# ============================================================

def _read(rel_path: str) -> str:
    path = ANDROID_ROOT / rel_path
    require(path.is_file(), f"文件不存在: {path}")
    return path.read_text(encoding="utf-8")


def check_android_room_migration():
    db = _read("data/local/database/AvelineDatabase.kt")
    require("version = 5" in db, "Room 版本号未升到 5")
    require("MIGRATION_4_5" in db, "缺少 MIGRATION_4_5")
    require("videoUrl TEXT" in db, "migration 未加 videoUrl 列")

    entity = _read("data/local/database/entity/MessageEntity.kt")
    require("videoUrl" in entity, "MessageEntity 缺 videoUrl")

    module = _read("di/DatabaseModule.kt")
    require("MIGRATION_4_5" in module, "DatabaseModule 未注册 MIGRATION_4_5（会导致启动崩溃）")


def check_android_domain_and_repository():
    model = _read("domain/models/Message.kt")
    require("videoUrl" in model, "领域模型 Message 缺 videoUrl")

    repo = _read("data/repository/ChatRepositoryImpl.kt")
    require(repo.count("videoUrl = videoUrl") >= 1, "ChatRepositoryImpl 未映射 videoUrl")
    # 双向映射 + DTO 映射，三处都要有
    require(repo.count("videoUrl") >= 3, "videoUrl 映射不完整（entity/domain 双向 + DTO）")


def check_android_protocol_parsing():
    ws_msg = _read("data/remote/api/WebSocketMessage.kt")
    require("data class VideoResult" in ws_msg, "WebSocketMessage 缺 VideoResult")

    ws_mgr = _read("data/remote/api/WebSocketManager.kt")
    require('"video_result"' in ws_mgr, "WebSocketManager 未解析 video_result")
    require(
        "video_result 缺少视频地址" in ws_mgr,
        "空地址未做保护，会渲染出加载失败的气泡",
    )

    stream = _read("data/remote/api/StreamEvent.kt")
    require("data class VideoResult" in stream, "StreamEvent 缺 VideoResult")
    require('"video_result"' in stream, "SseParser 未解析 video_result")


def check_android_dispatch_and_persist():
    observer = _read("presentation/chat/ChatSessionObserver.kt")
    require("WebSocketMessage.VideoResult" in observer, "WS 事件未分发 VideoResult")

    handler = _read("presentation/chat/ChatIncomingMessageHandler.kt")
    require("handleVideoResultMessage" in handler, "未实现 handleVideoResultMessage")
    require('messageType = "video"' in handler, "视频消息未打 video 类型")

    sender = _read("presentation/chat/ChatSendController.kt")
    require("StreamEvent.VideoResult" in sender, "SSE 通道未处理 VideoResult")
    require("videoUrl: String?" in sender, "发送入口未支持 videoUrl")


def check_android_rendering():
    bubble = _read("presentation/components/MessageBubble.kt")
    require("videoUrl" in bubble, "MessageData 缺 videoUrl")
    require("VideoMessageBubble(" in bubble, "气泡未接入 VideoMessageBubble")

    player = _read("presentation/components/VideoMessageBubble.kt")
    require("ExoPlayer.Builder" in player, "播放器组件未使用 ExoPlayer")
    require("MediaUrlResolver.resolve" in player, "播放器未补全相对地址（会加载失败）")
    require("player.release()" in player, "播放器未释放资源")

    screen = _read("presentation/chat/ChatScreen.kt")
    require("videoUrl = message.videoUrl" in screen, "ChatScreen 未把 videoUrl 传给气泡")
    require("pendingVideoUrl" in screen, "ChatScreen 未渲染待发送视频")

    resolver = _read("utils/MediaUrlResolver.kt")
    require("fun resolve" in resolver, "MediaUrlResolver 缺失")
    image_resolver = _read("utils/ImageUrlResolver.kt")
    require("MediaUrlResolver.resolve" in image_resolver, "ImageUrlResolver 未委托到统一实现")


def check_android_user_send_video():
    uploader = _read("services/FileUploadManager.kt")
    require("UploadKind.VIDEO" in uploader, "FileUploadManager 未支持视频类型")
    require("isSupportedVideoType" in uploader, "缺少视频 MIME 白名单校验")

    helper = _read("presentation/chat/ChatUploadHelper.kt")
    require("sendVideoMessage" in helper, "ChatUploadHelper 未实现发送视频")
    require("UploadKind.VIDEO" in helper, "上传未走 VIDEO 分类")

    state = _read("presentation/chat/ChatUiState.kt")
    require("pendingVideoUrl" in state, "ChatUiState 缺 pendingVideoUrl")

    vm = _read("presentation/chat/ChatViewModel.kt")
    require("sendVideoMessage" in vm, "ViewModel 未暴露发送视频")
    require("pendingVideoUrl" in vm, "sendPendingOrText 未处理待发送视频")

    text = _read("presentation/chat/VideoMessageText.kt")
    require("[视频: " in text, "视频消息文本口径缺失")


def check_android_preview_and_tag_strip():
    preview = _read("presentation/chat/ChatPreviewBuilder.kt")
    require("[视频]" in preview, "会话列表预览未支持视频")
    require("VIDEO" in preview, "预览未剥离 [VIDEO] 标签")

    bubble = _read("presentation/components/MessageBubble.kt")
    require("MEME|IMG|BM|VOICE|VIDEO" in bubble, "气泡未剥离 [VIDEO] 标签")


def check_room_schema_exported():
    schema = (
        ROOT
        / "clients/frontend/aveline-android/android/app/schemas"
        / "com.aveline.ai.mobile.data.local.database.AvelineDatabase"
        / "5.json"
    )
    if not schema.is_file():
        print(
            "  [warn] 缺 Room schema 5.json（由 Gradle 构建自动生成）。"
            "请在 Android Studio 跑一次构建后把它提交进仓库，保持 schema 链完整。"
        )
        return
    content = schema.read_text(encoding="utf-8")
    require("videoUrl" in content, "5.json 里没有 videoUrl")


def main() -> int:
    print("== media_tags ==")
    check("视频静态资源化", check_video_path_to_url)
    check("非视频/缺失文件不落静态目录", check_video_path_to_url_rejects_junk)
    check("私密视频推送默认开启", check_private_video_gate_default_on)
    check("[VIDEO] 标签解析", check_video_tag_parsed)

    print("== WebSocket 通道 ==")
    check("video_result 报文", check_ws_video_result_payload)
    check("坏路径不推送", check_ws_video_result_skips_bad_path)
    check("媒体标签剥离覆盖 VIDEO", check_media_tag_strip_covers_video)

    print("== SSE 通道 ==")
    check("关闭开关生效", check_sse_video_gate_off_switch)
    check("默认产出 video_result", check_sse_video_result_event)
    check("媒体按标签位置下发", check_sse_media_positional_order)

    print("== 上传接口 ==")
    check("视频落到 output/video/uploads", check_upload_routes_video)
    check("音频落盘位置未被改坏", check_upload_still_routes_audio)

    print("== Android 接线（静态） ==")
    check("Room 迁移", check_android_room_migration)
    check("领域模型与仓储映射", check_android_domain_and_repository)
    check("协议解析", check_android_protocol_parsing)
    check("事件分发与落库", check_android_dispatch_and_persist)
    check("气泡渲染", check_android_rendering)
    check("用户发视频", check_android_user_send_video)
    check("预览与标签剥离", check_android_preview_and_tag_strip)
    check("Room schema 导出", check_room_schema_exported)

    print()
    if _FAILED:
        print(f"FAILED {len(_FAILED)} 项：")
        for item in _FAILED:
            print(f"  - {item}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
