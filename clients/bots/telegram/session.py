"""Telegram 适配器会话管理。

每个 chat_id 一个会话（TelegramSession）：
- 通过 WS 长连接到后端 /api/v1/ws
- 发送用户消息（text_input）
- 接收流式回复（chunk/message/response_chunk/response_done）
- 接收主动关怀消息（proactive_message）

职责拆分（解耦）：
- split_utils.py       ：纯函数——conversation_id 构建、文本清洗、断句（保留 markdown）
- stream_editor.py     ：Mixin——流式增量编辑（边收边改同一条消息 + typing + 429 退避）
- response_sender.py   ：Mixin——完整回复分段发送（断句 + 媒体标签 + [WEBM]/[DICE]）
- session.py（本文件） ：TelegramSession 主类——WS 连接循环、接收分发、心跳/去重/匹配
"""
import asyncio
import json
import time

import websockets

from clients.bots.telegram.response_sender import ResponseSenderMixin
from clients.bots.telegram.settings import logger
from clients.bots.telegram.split_utils import build_persona_conversation_id
from clients.bots.telegram.stream_editor import StreamEditMixin

# 向后兼容：外部可能直接 import 这些符号
__all__ = ["TelegramSession", "build_persona_conversation_id"]


class TelegramSession(StreamEditMixin, ResponseSenderMixin):
    """Telegram 会话，维护到后端的 WS 长连接。

    通过多继承组合：
    - StreamEditMixin    ：流式增量编辑相关方法
    - ResponseSenderMixin ：完整回复分段发送相关方法
    """

    def __init__(self, session_id: str, adapter):
        self.session_id = session_id
        self.adapter = adapter
        self.ws = None
        self.running = False
        self.last_activity = time.time()
        self.queue: asyncio.Queue = asyncio.Queue()
        self.task: asyncio.Task | None = None
        self._recent_proactive_messages: dict[str, float] = {}

        # ===== 流式增量编辑状态 =====
        # 收到 response_chunk 时边收边编辑同一条 Telegram 消息，
        # 而不是等 response_done 才一次性发送。
        # _stream_edit_msg_id: 当前正在编辑的 Telegram 消息 ID（None=还没创建）
        # _stream_edit_text:   已编辑到消息里的文本（不含待发送的剩余部分）
        # _stream_edit_buffer: 收到但还没编辑出去的文本
        # _stream_edit_last_ts: 上次编辑的时间戳（节流用）
        # _stream_edit_task:   节流编辑定时任务
        # _stream_edit_first_sent: 首个 chunk 是否已发送
        # _stream_edit_overflowed: 超过单条消息长度限制，停止编辑
        # _stream_edit_interval: 当前动态节流间隔（收到 429 会自动拉长）
        # _stream_edit_typing_task: "正在输入"状态定时任务
        self._stream_edit_msg_id: int | None = None
        self._stream_edit_text: str = ""
        self._stream_edit_buffer: str = ""
        self._stream_edit_last_ts: float = 0.0
        self._stream_edit_task: asyncio.Task | None = None
        self._stream_edit_first_sent: bool = False
        self._stream_edit_overflowed: bool = False
        self._stream_edit_interval: float = 0.0  # 在 start 前由 adapter 注入默认值
        self._stream_edit_typing_task: asyncio.Task | None = None

    async def start(self):
        from clients.bots.telegram.settings import TG_STREAM_EDIT_INTERVAL_SECONDS
        # 注入流式编辑默认节流间隔
        self._stream_edit_interval = TG_STREAM_EDIT_INTERVAL_SECONDS
        self.running = True
        self.task = asyncio.create_task(self._run_loop())

    async def stop(self):
        self.running = False
        await self._reset_stream_edit()
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        if self.task:
            self.task.cancel()
            current = asyncio.current_task()
            if self.task is not current:
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

    @property
    def _cfg(self):
        return self.adapter

    @property
    def _client_id(self) -> str:
        return f"tg_{self.session_id}"

    def _get_current_persona_filename(self) -> str:
        """获取当前会话使用的角色配置文件名。

        只认两个来源（不 fallback 到全局 persona_manager，否则会把后端默认的
        Aveline 强行打到 Telegram 的 conversation_id 上，导致其他平台/人设的
        对话记忆被错误落到 Aveline 文件夹）：
        1. 显式 /切人设 命令设置的 adapter.persona_filename
        2. .env 里的 TELEGRAM_PERSONA_FILENAME
        两者都没有则返回空字符串，由后端按全局人设路由处理。
        """
        fn = str(getattr(self.adapter, "persona_filename", "") or "").strip()
        if fn:
            return fn
        return ""

    async def send_text(self, text: str, *, user_name: str | None = None,
                        is_voice_input: bool = False,
                        model: str | None = None,
                        persona_filename: str | None = None):
        """将用户消息放入队列，由 WS 连接循环发送到后端。

        Args:
            model: 可选，显式指定本次回复使用的模型（cloud:provider:key_alias:model 或 model_name）
            persona_filename: 可选，显式指定本次回复使用的人设文件名
        """
        self.last_activity = time.time()
        payload: dict = {
            "type": "text_input",
            "text": text,
            "content": text,
            "client_id": self._client_id,
            "user_id": self.session_id,
            "platform": "telegram",
            "_send_ts": time.time() * 1000,
        }
        if getattr(self.adapter, "xiaoyou_access_token", ""):
            payload["access_token"] = self.adapter.xiaoyou_access_token

        # 人设：显式传入优先，否则取 adapter 当前人设
        effective_persona = str(persona_filename or "").strip() or self._get_current_persona_filename()
        try:
            payload["conversation_id"] = build_persona_conversation_id(self.session_id, effective_persona)
            if effective_persona:
                payload["persona_filename"] = effective_persona
        except Exception as e:
            logger.warning(f"构建 conversation_id 失败: {e}, 回退到 session_id={self.session_id}")
            payload["conversation_id"] = self.session_id

        # 模型：显式传入优先
        if model:
            payload["model"] = model

        if user_name:
            payload["user_name"] = user_name
        if is_voice_input:
            payload["is_voice_input"] = True

        logger.info(f"[{self.session_id}] 用户消息入队: {text[:50]}...")
        await self.queue.put(payload)

    async def _run_loop(self):
        """主连接循环：连接 WS、收发消息、异常重连。"""
        retry_count = 0
        pending_message: dict | None = None
        try:
            while self.running:
                try:
                    ws_url = (
                        f"{self.adapter.xiaoyou_ws_url}"
                        f"?client_id={self._client_id}"
                        f"&user_id={self.session_id}"
                        f"&platform=telegram"
                    )
                    headers = None
                    if self.adapter.xiaoyou_access_token:
                        headers = {"Authorization": f"Bearer {self.adapter.xiaoyou_access_token}"}

                    t_conn_start = time.time()
                    connect_kwargs = {
                        "open_timeout": 5,
                        "close_timeout": 5,
                        "ping_interval": 20,
                        "ping_timeout": 10,
                    }
                    if headers:
                        # websockets 11 用 extra_headers，12+ 用 additional_headers
                        try:
                            import websockets as _ws_mod
                            if tuple(int(x) for x in _ws_mod.__version__.split(".")[:2]) >= (12, 0):
                                connect_kwargs["additional_headers"] = headers
                            else:
                                connect_kwargs["extra_headers"] = headers
                        except Exception:
                            connect_kwargs["extra_headers"] = headers
                    async with websockets.connect(ws_url, **connect_kwargs) as ws:
                        t_conn = time.time() - t_conn_start
                        self.ws = ws
                        logger.info(f"[{self.session_id}] 已连接到后端 WS (耗时 {t_conn:.3f}s)")
                        retry_count = 0

                        receive_task = asyncio.create_task(self._receive_from_backend())
                        queue_task = None
                        try:
                            while self.running:
                                if pending_message is None:
                                    queue_task = asyncio.create_task(self.queue.get())
                                    done, _ = await asyncio.wait(
                                        {queue_task, receive_task},
                                        return_when=asyncio.FIRST_COMPLETED,
                                    )
                                    if receive_task in done:
                                        # queue 与接收循环可能同时完成；已经出队的消息必须
                                        # 留到重连后重发，不能在关闭旧连接时静默丢弃。
                                        if queue_task in done and not queue_task.cancelled():
                                            pending_message = queue_task.result()
                                        else:
                                            queue_task.cancel()
                                            try:
                                                await queue_task
                                            except asyncio.CancelledError:
                                                pass
                                        queue_task = None
                                        if not self.running:
                                            break
                                        recv_exc = None
                                        if not receive_task.cancelled():
                                            recv_exc = receive_task.exception()
                                        if recv_exc is None:
                                            recv_exc = ConnectionError("接收循环已结束，准备重连")
                                        raise recv_exc

                                    pending_message = queue_task.result()
                                    queue_task = None

                                msg = pending_message
                                real_send_ts = time.time() * 1000
                                orig_ts = msg.get("_send_ts", 0)
                                wait_ms = real_send_ts - orig_ts if orig_ts > 0 else 0
                                logger.info(f"[{self.session_id}] 发送到 WS (队列等待 {wait_ms:.0f}ms)")
                                await ws.send(json.dumps(msg))
                                pending_message = None
                        except asyncio.CancelledError:
                            break
                        except Exception as e:
                            logger.error(f"[{self.session_id}] 连接循环异常: {e}")
                            self.ws = None
                            raise
                        finally:
                            if queue_task is not None:
                                queue_task.cancel()
                                try:
                                    await queue_task
                                except BaseException:
                                    pass
                            receive_task.cancel()
                            try:
                                await receive_task
                            except BaseException:
                                pass
                except Exception as e:
                    err_msg = str(e or "")
                    if not self.running:
                        break
                    logger.error(f"[{self.session_id}] 连接失败: {err_msg}")
                    self.ws = None
                    retry_count += 1
                    # 指数退避
                    delay = min(30.0, 1.0 * (2 ** max(0, retry_count - 1)))
                    if "Connection refused" in err_msg or "WinError 10061" in err_msg:
                        delay = 2.0
                    logger.info(f"[{self.session_id}] {delay:.1f}s 后重连 (第 {retry_count} 次)")
                    await asyncio.sleep(delay)
        finally:
            if self.running:
                self.running = False
                logger.warning(f"[{self.session_id}] 连接循环退出")
            current = self.adapter.sessions.get(self.session_id)
            if current is self:
                del self.adapter.sessions[self.session_id]

    async def _receive_from_backend(self):
        """从 WS 接收消息并按类型分发。"""
        full_response = ""
        full_response_is_proactive = False
        try:
            async for message in self.ws:
                self.last_activity = time.time()
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    subtype = data.get("subtype")

                    # 心跳
                    if msg_type in ("pong", "heartbeat") or await self._handle_heartbeat(data):
                        continue

                    # 流式 chunk（旧格式）
                    if msg_type == "chunk":
                        content = str(data.get("content", "") or "")
                        if content:
                            full_response += content
                            full_response_is_proactive = False
                            await self._on_stream_chunk(content)
                        continue

                    if msg_type == "finish":
                        # 旧版完成信号：做最终发送
                        await self._on_stream_done(
                            full_response,
                            is_proactive=full_response_is_proactive,
                        )
                        full_response = ""
                        full_response_is_proactive = False
                        continue

                    if msg_type == "error":
                        err_msg = (
                            str(data.get("message") or "").strip()
                            or str(data.get("error") or "").strip()
                            or "生成回复时发生错误"
                        )
                        await self._reset_stream_edit()
                        await self.adapter.send_text_to_chat(self.session_id, err_msg)
                        full_response = ""
                        full_response_is_proactive = False
                        continue

                    if msg_type == "message":
                        # 主动关怀消息
                        if data.get("is_proactive"):
                            target_id = str(data.get("conversation_id") or "")
                            if not self._is_target_match(target_id):
                                logger.debug(f"[{self.session_id}] 忽略目标不匹配的主动消息: {target_id}")
                                continue
                            logger.info(f"[{self.session_id}] 接收主动关怀消息")

                        if subtype == "response_chunk":
                            content = str(data.get("content") or "")
                            if content:
                                full_response += content
                                full_response_is_proactive = bool(data.get("is_proactive"))
                                await self._on_stream_chunk(content)
                            continue

                        if subtype == "proactive_notification":
                            content = data.get("content")
                            if content and not await self._is_duplicate_proactive(str(content)):
                                await self._send_full_response_with_split(
                                    str(content), is_proactive=True
                                )
                            continue

                        if subtype == "response_done":
                            logger.info(f"[{self.session_id}] LLM原始回复 ({len(full_response)}字)")
                            if full_response_is_proactive and await self._is_duplicate_proactive(full_response):
                                await self._reset_stream_edit()
                                full_response = ""
                                full_response_is_proactive = False
                                continue
                            await self._on_stream_done(
                                full_response, is_proactive=full_response_is_proactive
                            )
                            full_response = ""
                            full_response_is_proactive = False
                            continue

                        if subtype == "response":
                            content = data.get("content")
                            if content:
                                content_text = str(content)
                                is_pro = bool(data.get("is_proactive"))
                                # response 子类型是完整一次性回复，清理可能残留的流式编辑状态
                                await self._reset_stream_edit()
                                if is_pro and await self._is_duplicate_proactive(content_text):
                                    full_response = ""
                                    full_response_is_proactive = False
                                    continue
                                await self._send_full_response_with_split(
                                    content_text, is_proactive=is_pro
                                )
                                full_response = ""
                                full_response_is_proactive = False
                            continue

                        if not subtype:
                            content = data.get("content")
                            if content:
                                is_pro = bool(data.get("is_proactive"))
                                await self._reset_stream_edit()
                                await self._send_full_response_with_split(
                                    str(content), is_proactive=is_pro
                                )
                                full_response = ""
                                full_response_is_proactive = False
                            continue

                    # 主动消息（proactive_message 类型）
                    if msg_type == "proactive_message":
                        target_id = str(data.get("conversation_id") or "")
                        if not self._is_target_match(target_id):
                            logger.debug(f"[{self.session_id}] 忽略 proactive_message: {target_id}")
                            continue
                        logger.info(f"[{self.session_id}] 接收 proactive_message, target={target_id}")
                        content = data.get("content")
                        if not content or await self._is_duplicate_proactive(str(content)):
                            continue
                        await self._reset_stream_edit()
                        await self._send_full_response_with_split(
                            str(content), is_proactive=True
                        )
                        continue

                    # 图片结果
                    if msg_type == "image_status":
                        d = data.get("data")
                        if d and d.get("status") == "started":
                            prompt = d.get("prompt", "")
                            await self.adapter.send_text_to_chat(
                                self.session_id, f"🎨 正在生成图片: {prompt}"
                            )
                        continue

                    if msg_type == "image_result":
                        d = data.get("data")
                        if d and d.get("success"):
                            image_path = d.get("image_path")
                            if image_path:
                                await self.adapter.send_photo_path_to_chat(self.session_id, image_path)
                        continue

                except json.JSONDecodeError:
                    pass
        except Exception as e:
            logger.error(f"[{self.session_id}] 接收异常: {e}")
            if full_response:
                try:
                    await self._on_stream_done(
                        full_response, is_proactive=full_response_is_proactive
                    )
                except Exception:
                    pass
            raise

    async def _handle_heartbeat(self, data: dict) -> bool:
        """处理服务端心跳。"""
        if data.get("type") == "heartbeat":
            try:
                await self.ws.send(json.dumps({"type": "heartbeat_ack", "timestamp": time.time()}))
            except Exception:
                pass
            return True
        return False

    def _is_target_match(self, target_id: str) -> bool:
        """检查主动消息的目标 conversation_id 是否匹配当前 session。"""
        if not target_id:
            return True
        if target_id == self.session_id:
            return True
        if "__persona__" in target_id:
            base = target_id.split("__persona__", 1)[0]
            return base == self.session_id
        if self.session_id == "default_user" and target_id == "default_user":
            return True
        return False

    async def _is_duplicate_proactive(self, text: str, window_seconds: float = 90.0) -> bool:
        """检测短时间内重复的主动消息。"""
        now = time.time()
        normalized = "".join(str(text or "").split())
        if not normalized:
            return False
        if len(normalized) > 180:
            normalized = normalized[:180]
        last_ts = float(self._recent_proactive_messages.get(normalized) or 0.0)
        if last_ts and (now - last_ts) <= window_seconds:
            return True
        self._recent_proactive_messages[normalized] = now
        # 清理过期
        expired = [k for k, ts in self._recent_proactive_messages.items()
                   if (now - float(ts)) > 120.0]
        for k in expired:
            self._recent_proactive_messages.pop(k, None)
        return False
