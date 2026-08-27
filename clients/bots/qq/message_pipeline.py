"""消息处理管线。

从 QQAdapter 中提取的专职组件，将原本集中在 _run_message_pipeline 中的
多阶段处理逻辑拆分为独立的处理器，便于测试和扩展。

处理阶段：
- Stage 1: PreprocessProcessor - 预处理（表情/回复/图片/语音归一化）
- Stage 2: CommandRoutingProcessor - 命令路由
- Stage 3: IntentRoutingProcessor - 意图路由（快速路径 + BERT 慢速路径）
- Stage 4: ChatDispatchProcessor - 聊天分发 + 提及对方检测
"""
import asyncio
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from clients.bots.qq.peer_chat import PeerChatManager


@dataclass
class MessageContext:
    """消息处理管线的上下文，在各处理器间传递"""

    session_id: str
    msg_type: str
    user_id: str
    raw_message: str
    self_id: str
    is_at_me: bool
    group_id: str
    session: Any

    # 处理过程中的中间状态
    display_msg: str = ""
    clean_msg: str = ""
    clean_intent_msg: str = ""
    is_master: bool = False
    is_peer_bot: bool = False
    handled: bool = False
    voice_intent_detected: bool = False
    should_process_semantic: bool = False

    # 各阶段耗时（用于日志）
    timings: dict = field(default_factory=dict)


class MessageProcessor(ABC):
    """消息处理器抽象基类"""

    @abstractmethod
    async def process(self, context: MessageContext) -> MessageContext:
        """处理消息上下文，返回更新后的上下文"""


class PreprocessProcessor(MessageProcessor):
    """Stage 1: 预处理（表情/回复/图片/语音归一化）"""

    def __init__(self, face_injector, media_handler, enable_qq_vision: bool, enable_qq_voice: bool):
        self.face_injector = face_injector
        self.media_handler = media_handler
        self.enable_qq_vision = enable_qq_vision
        self.enable_qq_voice = enable_qq_voice

    async def process(self, context: MessageContext) -> MessageContext:
        display_msg = self.face_injector.extract(str(context.raw_message or "").strip())

        try:
            display_msg = await self.media_handler.process_reply_in_message(
                context.raw_message, display_msg
            )
        except Exception:
            pass

        if self.enable_qq_vision:
            try:
                display_msg = await self.media_handler.process_images_in_message(
                    context.raw_message, display_msg
                )
            except Exception:
                pass

        is_voice_input = False
        if self.enable_qq_voice:
            try:
                display_msg, is_voice_input = await self.media_handler.process_audio_in_message(
                    context.raw_message, display_msg
                )
            except Exception:
                is_voice_input = False

        try:
            context.session.is_voice_input = bool(is_voice_input)
        except Exception:
            pass

        context.display_msg = display_msg
        return context


class CommandRoutingProcessor(MessageProcessor):
    """Stage 2: 命令路由

    内置命令解析和分发逻辑，支持 / 和 ／ 作为命令前缀。
    """

    def __init__(self, adapter):
        self.adapter = adapter

    async def process(self, context: MessageContext) -> MessageContext:
        if context.handled:
            return context

        t_start = time.time()
        handled = await self._try_handle_command(context)
        context.timings["cmd"] = time.time() - t_start
        context.handled = bool(handled)
        return context

    async def _try_handle_command(self, ctx: MessageContext) -> bool:
        """解析并分发命令"""
        raw_message = ctx.display_msg
        if not raw_message:
            return False

        m = raw_message.lstrip()
        if not (m.startswith("/") or m.startswith("／")):
            return False

        cmd_line = m.lstrip("/／").strip()
        if not cmd_line:
            await self.adapter.system_handler.show_help(ctx.session_id)
            return True

        parts = cmd_line.split(None, 1)
        cmd = str(parts[0] or "").strip()
        rest = str(parts[1] if len(parts) > 1 else "").strip()

        prefs = await self.adapter.config_handler.get_session_prefs(
            session_id=ctx.session_id, qq_user_id=ctx.user_id
        )
        is_master = self.adapter._is_master(ctx.user_id)

        routed = await self.adapter.command_router.dispatch(
            cmd_lower=cmd.lower(),
            session_id=ctx.session_id,
            msg_type=ctx.msg_type,
            qq_user_id=ctx.user_id,
            group_id=ctx.group_id,
            rest=rest,
            prefs=prefs,
            is_master=is_master,
        )
        if routed is not None:
            return bool(routed)

        # P1-7: 未命中本地命令时，转发后端 Aveline command_handler 处理
        # 而不是直接回复"未识别"，这样 /clear /save /mode 等 Aveline 命令能到达后端
        # 后端 Aveline 也识别不了时，会当普通聊天处理
        return False


class IntentRoutingProcessor(MessageProcessor):
    """Stage 3: 意图路由（快速路径 + BERT 慢速路径）"""

    def __init__(self, semantic_recognizer, intent_handler, reply_mode: str, enable_llm_intent_router: bool, logger):
        self.semantic_recognizer = semantic_recognizer
        self.intent_handler = intent_handler
        self.reply_mode = reply_mode
        self.enable_llm_intent_router = enable_llm_intent_router
        self.logger = logger

    @staticmethod
    def _should_process_message(context: MessageContext, reply_mode: str) -> bool:
        """判断消息是否应进入后端处理。"""
        if context.msg_type == "private":
            return True
        return (reply_mode == "all") or bool(context.is_at_me)

    async def process(self, context: MessageContext) -> MessageContext:
        if context.handled:
            return context

        # 私聊默认进入后端，群聊再根据 reply_mode / @ 状态判断。
        context.should_process_semantic = self._should_process_message(
            context, self.reply_mode
        )

        # 清理消息：移除 @ 标记
        context.clean_msg = context.display_msg.replace(
            f"[CQ:at,qq={context.self_id}]", ""
        ).strip()

        # 意图匹配使用不含 Vision 描述的文本，防止图片描述关键词误触发意图
        context.clean_intent_msg = context.clean_msg
        vision_prefix_match = re.match(r"(【你看到了[^】]*】[\s]*)+", context.clean_msg)
        if vision_prefix_match:
            context.clean_intent_msg = context.clean_msg[vision_prefix_match.end():].strip()

        if not context.should_process_semantic:
            self.logger.info(
                f"[{context.session_id}] 跳过后端处理: "
                f"msg_type={context.msg_type}, reply_mode={self.reply_mode}, is_at_me={context.is_at_me}"
            )
            return context

        t_intent_start = time.time()

        # 快速路径：语义意图识别
        intent_result = self.semantic_recognizer.match(context.clean_intent_msg)
        if intent_result:
            self.logger.info(
                f"[{context.session_id}] Fast Path Intent: {intent_result.get('intent')}"
            )
            if str(intent_result.get("intent") or "").strip().upper() == "SEND_VOICE":
                context.voice_intent_detected = True
            handled = await self.intent_handler.handle_semantic_intent(
                context.session_id, context.user_id, intent_result, context.clean_intent_msg
            )
            context.handled = bool(handled)

        # 慢速路径：BERT 意图分类
        if not context.handled and self.enable_llm_intent_router:
            if len(context.clean_intent_msg) > 1 and any(
                c.isalnum() or "\u4e00" <= c <= "\u9fff" for c in context.clean_intent_msg
            ):
                self.logger.info(
                    f"[{context.session_id}] Slow Path Intent (BERT): {context.clean_intent_msg[:30]}..."
                )
                intent_result = await self.intent_handler.classify_intent(
                    context.clean_intent_msg, context.session_id
                )
                t_intent = time.time() - t_intent_start
                context.timings["intent"] = t_intent
                if intent_result:
                    self.logger.info(
                        f"[{context.session_id}] BERT Intent: {intent_result.get('intent')} (took {t_intent:.3f}s)"
                    )
                    if str(intent_result.get("intent") or "").strip().upper() == "SEND_VOICE":
                        context.voice_intent_detected = True
                    handled = await self.intent_handler.handle_semantic_intent(
                        context.session_id, context.user_id, intent_result, context.clean_intent_msg
                    )
                    context.handled = bool(handled)
                else:
                    self.logger.debug(f"[{context.session_id}] BERT Intent returned None")

        return context


class ChatDispatchProcessor(MessageProcessor):
    """Stage 4: 聊天分发 + Stage 5: 提及对方检测"""

    def __init__(self, adapter, logger):
        self.adapter = adapter
        self.logger = logger

    async def process(self, context: MessageContext) -> MessageContext:
        if context.handled or not context.should_process_semantic:
            return context

        t_chat_start = time.time()

        if not context.clean_msg:
            context.clean_msg = "在呢"

        # 构建上下文
        peer_role_context = None
        if context.is_peer_bot:
            peer_role_context = self.adapter._build_peer_role_context()
        sender_identity_context = self.adapter._build_sender_identity_context(
            is_master=context.is_master,
            is_peer_bot=context.is_peer_bot,
            peer_qq_id=context.user_id if context.is_peer_bot else "",
        )

        prefs = await self.adapter.config_handler.get_session_prefs(
            session_id=context.session_id, qq_user_id=context.user_id
        )

        # 发送聊天消息
        if isinstance(prefs, dict) and context.voice_intent_detected:
            prefs["reply_voice_once"] = True

        await context.session.send_text(
            context.clean_msg,
            model=prefs.get("chat_model") or None if isinstance(prefs, dict) else None,
            peer_role_context=peer_role_context,
            sender_identity_context=sender_identity_context,
        )
        context.timings["chat"] = time.time() - t_chat_start

        # Stage 5: 检测是否提及对方角色
        await self._check_peer_mention(context)

        return context

    async def _check_peer_mention(self, context: MessageContext) -> None:
        """检测是否提及对方角色，如果是则触发给对方发消息"""
        if not (context.is_master and not context.is_peer_bot):
            return

        try:
            role_id = str(self.adapter.cfg.role_id or "").strip().lower()
            if role_id not in ("aveline", "ling"):
                return

            peer_mentioned = PeerChatManager.detect_peer_mention(context.clean_msg, role_id)
            if not peer_mentioned:
                return

            self.logger.info(
                f"检测到提及对方: {peer_mentioned}，准备触发给对方发消息"
            )
            asyncio.create_task(
                PeerChatManager.trigger_peer_mention(
                    role_id=role_id,
                    adapter=self.adapter,
                    master_qq_id=context.user_id,
                    context=None,
                    topic="主人提到了你",
                )
            )
        except Exception as e:
            self.logger.debug(f"提及对方检测失败: {e}")


class MessagePipeline:
    """消息处理管线，管理处理器的执行顺序"""

    def __init__(self, processors: list[MessageProcessor], logger):
        self.processors = processors
        self.logger = logger

    async def process(self, context: MessageContext) -> MessageContext:
        """按顺序执行所有处理器，直到消息被处理"""
        for processor in self.processors:
            context = await processor.process(context)
            if context.handled:
                break
        return context


class MessageDispatcher:
    """消息分发器，处理消息接收、分类和分发（合并自 message_dispatcher.py）。"""

    def __init__(self, adapter):
        self.adapter = adapter
        self.logger = adapter.logger

    async def process_post_message(self, data: dict[str, Any], self_id: str):
        """处理从 NapCat 接收的消息"""
        msg_type = data.get("message_type")
        user_id = str(data.get("user_id", ""))

        if user_id == self_id:
            return
        is_master = self.adapter._is_master(user_id)
        is_peer_bot = bool(self.adapter.cfg.peer_qq_id and user_id == self.adapter.cfg.peer_qq_id)
        if is_peer_bot:
            return
        if msg_type in ("private", "group") and not is_master:
            return
        if msg_type == "group" and self.adapter.cfg.group_id:
            if str(data.get("group_id", "")) != self.adapter.cfg.group_id:
                return

        raw_message = data.get("raw_message", "")
        is_at_me = (msg_type == "private") or (f"[CQ:at,qq={self_id}]" in raw_message)
        self.logger.info(f"[{time.time() * 1000:.0f}ms] QQ Msg [{msg_type}] {user_id}: {raw_message}")

        session_id = self._resolve_session_id(msg_type, data, user_id, is_peer_bot)
        if not session_id:
            return

        from clients.bots.qq.aggregator import MessageAggregator
        msg_category = MessageAggregator.classify_message(raw_message)

        if msg_category == "sticker":
            self.logger.debug(f"[{session_id}] 跳过纯表情/贴纸消息: {raw_message[:60]}")
            return

        if msg_category == "command":
            await self._dispatch_message(session_id, raw_message, data, self_id, msg_type, user_id, is_at_me)
            return

        async def flush_callback(sid, messages):
            merged, ctx_msgs = self.adapter.aggregator.get_merged_message(messages)
            if merged:
                if len(ctx_msgs) > 1:
                    self.logger.info(f"[{sid}] 聚合 {len(ctx_msgs)} 条消息: {merged[:80]}...")
                await self._dispatch_message(sid, merged, data, self_id, msg_type, user_id, is_at_me)

        await self.adapter.aggregator.buffer_message(session_id, raw_message, flush_callback)

    @staticmethod
    def _resolve_session_id(msg_type: str, data: dict, user_id: str, is_peer_bot: bool) -> str | None:
        if msg_type == "group":
            return f"group_{data.get('group_id')}_{user_id}"
        if msg_type == "private":
            return f"peer_{user_id}" if is_peer_bot else f"private_{user_id}"
        return None

    async def _dispatch_message(self, session_id, raw_message, data, self_id, msg_type, user_id, is_at_me):
        """确保会话存在后调用消息处理管线"""
        from clients.bots.qq.session.session import XiaoyouSession
        session = self.adapter.sessions.get(session_id)
        if not session or not session.running:
            session = XiaoyouSession(session_id, self.adapter)
            self.adapter.sessions[session_id] = session
            await session.start()

        await self.adapter._run_message_pipeline(
            session_id=session_id, msg_type=msg_type, user_id=user_id, raw_message=raw_message,
            self_id=self_id, is_at_me=is_at_me,
            group_id=str(data.get("group_id") or "") if msg_type == "group" else "",
            session=session,
        )
