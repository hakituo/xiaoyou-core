"""Telegram 适配器主协调器。

参照 QQ 适配器架构，通过 WS 长连接到后端，支持：
- 文本对话（流式回复 + 断句发送）
- 人设系统（persona_filename）
- 记忆系统（通过 conversation_id）
- 主动关怀（proactive_message）
- 视觉（图片识别）
- 语音（STT）
- 情绪更新

架构说明（mixin 拆分）：
- MediaSenderMixin：所有媒体发送方法（文本/图片/表情包/动画/视频/语音/骰子）
- CommandHandlersMixin：所有命令处理和路由
- 本文件：初始化、生命周期、消息接收分发
"""
import asyncio
import base64
import os
import time

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from clients.bots.telegram.command_handlers import CommandHandlersMixin
from clients.bots.telegram.http_client import HttpClient, HealthChecker
from clients.bots.telegram.media_sender import MediaSenderMixin
from clients.bots.telegram.session import TelegramSession
from clients.bots.telegram.settings import (
    ENABLED,
    ENABLE_TELEGRAM_VOICE,
    ENABLE_TELEGRAM_VISION,
    HTTP_TIMEOUT_SECONDS,
    MASTER_USER_ID,
    PERSONA_FILENAME,
    SESSION_TIMEOUT_MINUTES,
    STRIP_MARKDOWN,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_PROXY_URL,
    XIAOYOU_ACCESS_TOKEN,
    XIAOYOU_HTTP_BASE_URL,
    XIAOYOU_WS_URL,
    logger,
)


class TelegramAdapter(MediaSenderMixin, CommandHandlersMixin):
    """Telegram 机器人适配器（参照 QQ 适配器架构）。

    通过 mixin 模式组合功能：
    - MediaSenderMixin：媒体发送能力
    - CommandHandlersMixin：命令处理能力
    """

    _instance: "TelegramAdapter | None" = None

    def __init__(self):
        self.application: Application | None = None
        self.running = False
        self.logger = logger
        self.ready_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._stop_requested = False
        self._cleanup_lock = asyncio.Lock()
        self._session_cleanup_task: asyncio.Task | None = None
        self.last_error: Exception | None = None

        # 后端连接配置
        self.xiaoyou_http_base_url = XIAOYOU_HTTP_BASE_URL
        self.xiaoyou_ws_url = XIAOYOU_WS_URL
        self.xiaoyou_access_token = XIAOYOU_ACCESS_TOKEN
        self.persona_filename = PERSONA_FILENAME

        # 功能开关
        self.enable_voice = ENABLE_TELEGRAM_VOICE
        self.enable_vision = ENABLE_TELEGRAM_VISION
        self.strip_markdown = STRIP_MARKDOWN
        self.master_user_id = MASTER_USER_ID
        self.session_timeout_seconds = max(0.0, float(SESSION_TIMEOUT_MINUTES) * 60.0)

        # HTTP 客户端（复用会话）
        self.http_client = HttpClient(
            base_url=XIAOYOU_HTTP_BASE_URL,
            access_token=XIAOYOU_ACCESS_TOKEN,
            timeout=float(HTTP_TIMEOUT_SECONDS),
            logger=logger,
        )
        self.health_checker = HealthChecker(self.http_client, logger)

        # 会话管理（每个 chat_id 一个 WS session）
        self.sessions: dict[str, TelegramSession] = {}
        self._session_lock = asyncio.Lock()

        # 列表缓存：供 /切模型 /切人设 按序号选择
        self._list_cache: dict[str, dict] = {}

        # 标记为单例
        TelegramAdapter._instance = self

    @classmethod
    def get_instance(cls) -> "TelegramAdapter | None":
        return cls._instance

    @property
    def is_ready(self) -> bool:
        """轮询器已启动且适配器可接收 Telegram 更新。"""
        updater = self.application.updater if self.application else None
        return bool(
            self.ready_event.is_set()
            and self.application
            and self.application.running
            and updater
            and updater.running
        )

    # ===== 身份/权限 =====

    def _is_master(self, user_id: int | str) -> bool:
        if not self.master_user_id:
            return True  # 未配置 master 则响应所有人
        return str(user_id) == str(self.master_user_id)

    # ===== 会话管理 =====

    async def _get_or_create_session(self, chat_id: int, user_id: int | str,
                                     user_name: str | None = None) -> TelegramSession:
        session_id = f"tg_{chat_id}"
        async with self._session_lock:
            session = self.sessions.get(session_id)
            if not session or not session.running:
                session = TelegramSession(session_id, self)
                self.sessions[session_id] = session
                await session.start()
                logger.info(f"[{session_id}] 创建新会话 (user={user_id})")
            return session

    # ===== Telegram Bot 初始化 =====

    async def initialize(self):
        """初始化 Telegram Application。"""
        try:
            builder = Application.builder().token(TELEGRAM_BOT_TOKEN)

            # 设置代理（国内访问 Telegram API 需要）
            if TELEGRAM_PROXY_URL:
                self.logger.info(f"使用代理: {TELEGRAM_PROXY_URL}")
                builder = builder.proxy(TELEGRAM_PROXY_URL)
                builder = builder.get_updates_proxy(TELEGRAM_PROXY_URL)

            self.application = builder.build()

            # 命令处理器
            self.application.add_handler(CommandHandler("start", self.handle_start))
            self.application.add_handler(CommandHandler("help", self.handle_help))
            self.application.add_handler(CommandHandler("status", self.handle_status))

            # Inline 按钮回调处理器（/模型 /人设 列表的按钮点击）
            self.application.add_handler(CallbackQueryHandler(self.handle_callback))

            # 同一 handler group 每个 update 只执行首个匹配项，因此媒体必须先于文本。
            # filters.TEXT 会包含命令文本；未由上方 CommandHandler 捕获的中文命令，
            # 继续交给 handle_message 内部的命令路由处理。
            self.application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
            if self.enable_voice:
                self.application.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
            self.application.add_handler(MessageHandler(filters.TEXT, self.handle_message))

            logger.info("Telegram Adapter 初始化完成")
        except Exception as e:
            logger.error(f"初始化 Telegram Adapter 失败: {e}", exc_info=True)
            raise

    # ===== 消息接收分发 =====

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理文本消息（含 / 开头的命令，由 _try_handle_command 路由）。"""
        user = update.effective_user
        chat_id = update.effective_chat.id
        # filters.ALL 会匹配非文本消息（sticker/audio 等），text 可能为 None
        message_text = update.message.text if update.message else None
        if not message_text:
            return

        if not self._is_master(user.id):
            return

        logger.info(f"收到消息 [chat={chat_id}, user={user.id}]: {message_text[:50]}...")

        # 命令路由：/ 或 ／ 开头走命令系统，命中则不进入聊天
        try:
            handled = await self._try_handle_command(str(chat_id), message_text, user.id)
            if handled:
                return
        except Exception as e:
            logger.error(f"命令处理异常: {e}", exc_info=True)
            await self.send_text_to_chat(str(chat_id), f"命令处理失败: {e}")
            return

        session = await self._get_or_create_session(chat_id, user.id, user.username)
        user_name = user.username or user.first_name or str(user.id)

        # 发送"正在输入..."指示器，让用户知道 bot 在处理
        await self._send_typing_action(str(chat_id))

        try:
            await session.send_text(message_text, user_name=user_name)
        except Exception as e:
            logger.error(f"处理消息失败: {e}", exc_info=True)
            await self.send_text_to_chat(str(chat_id), f"处理消息失败: {e}")

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理图片消息：下载 → base64 → 调用后端视觉接口 → 将描述作为用户消息发送。"""
        if not self.enable_vision:
            return
        user = update.effective_user
        chat_id = update.effective_chat.id
        if not self._is_master(user.id):
            return

        logger.info(f"收到图片 [chat={chat_id}, user={user.id}]")
        try:
            # 获取最高质量的图片
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            # 下载图片
            photo_bytes = await self.http_client.download_file(file.file_path)
            if not photo_bytes:
                await self.send_text_to_chat(str(chat_id), "下载图片失败")
                return
            # base64 编码
            image_b64 = base64.b64encode(photo_bytes).decode("utf-8")

            # 调用后端视觉接口
            status, data = await self.http_client.request(
                "POST", "/api/v1/vision/describe",
                json_body={"image_base64": image_b64, "prompt": "描述这张图片的内容"},
                timeout_seconds=60.0,
            )
            if status != 200 or not isinstance(data, dict) or data.get("status") != "success":
                err = data.get("message", "视觉处理失败") if isinstance(data, dict) else "视觉处理失败"
                await self.send_text_to_chat(str(chat_id), f"图片识别失败: {err}")
                return

            description = str(data.get("description") or "").strip()
            if not description:
                await self.send_text_to_chat(str(chat_id), "图片识别结果为空")
                return

            # 将图片描述作为用户消息发给后端（让 AI 基于图片内容回复）
            session = await self._get_or_create_session(chat_id, user.id, user.username)
            user_msg = f"[图片描述] {description}"
            await session.send_text(user_msg, user_name=user.username or str(user.id))

        except Exception as e:
            logger.error(f"处理图片失败: {e}", exc_info=True)
            await self.send_text_to_chat(str(chat_id), f"处理图片失败: {e}")

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理语音消息：下载 → 上传到后端 STT → 将识别结果作为用户消息发送。"""
        if not self.enable_voice:
            return
        user = update.effective_user
        chat_id = update.effective_chat.id
        if not self._is_master(user.id):
            return

        logger.info(f"收到语音 [chat={chat_id}, user={user.id}]")
        try:
            voice = update.message.voice
            file = await context.bot.get_file(voice.file_id)
            # 下载语音文件
            audio_bytes = await self.http_client.download_file(file.file_path)
            if not audio_bytes:
                await self.send_text_to_chat(str(chat_id), "下载语音失败")
                return

            # 上传到后端 STT 接口（model_size 是 query 参数）
            status, data = await self.http_client.upload_file(
                "/api/v1/media/stt?model_size=base",
                audio_bytes,
                filename=f"voice_{int(time.time())}.ogg",
                timeout_seconds=60.0,
            )
            if status != 200 or not isinstance(data, dict) or data.get("status") != "success":
                err = data.get("message", "语音识别失败") if isinstance(data, dict) else "语音识别失败"
                await self.send_text_to_chat(str(chat_id), f"语音识别失败: {err}")
                return

            text = str(data.get("text") or "").strip()
            if not text:
                await self.send_text_to_chat(str(chat_id), "语音识别结果为空")
                return

            logger.info(f"语音识别结果: {text[:50]}...")
            # 将识别结果作为用户消息发给后端
            session = await self._get_or_create_session(chat_id, user.id, user.username)
            await session.send_text(text, user_name=user.username or str(user.id), is_voice_input=True)

        except Exception as e:
            logger.error(f"处理语音失败: {e}", exc_info=True)
            await self.send_text_to_chat(str(chat_id), f"处理语音失败: {e}")

    # ===== 会话回收 =====

    async def _cleanup_idle_sessions_once(self, *, now: float | None = None) -> int:
        """回收超过配置时限未活动的 Telegram WebSocket 会话。"""
        if self.session_timeout_seconds <= 0:
            return 0
        current_time = time.time() if now is None else float(now)
        stale: list[TelegramSession] = []
        async with self._session_lock:
            for session_id, session in list(self.sessions.items()):
                if current_time - float(session.last_activity) < self.session_timeout_seconds:
                    continue
                if self.sessions.get(session_id) is session:
                    self.sessions.pop(session_id, None)
                    stale.append(session)
        for session in stale:
            await session.stop()
            logger.info(f"[{session.session_id}] 空闲超时，会话已回收")
        return len(stale)

    async def _session_cleanup_loop(self):
        check_interval = max(5.0, min(60.0, self.session_timeout_seconds / 2.0))
        try:
            while self.running and not self._stop_requested:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=check_interval
                    )
                    break
                except asyncio.TimeoutError:
                    await self._cleanup_idle_sessions_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Telegram 会话回收循环异常: {e}", exc_info=True)

    # ===== 生命周期 =====

    async def run(self):
        """持续运行 Telegram 适配器；异常退出时自动退避重启。"""
        # 总开关来自 app.yaml 的 telegram.enabled。
        if not ENABLED:
            logger.info("Telegram 适配器已在配置中禁用（enabled=false），跳过启动")
            return
        if not TELEGRAM_BOT_TOKEN:
            logger.error("未配置 TELEGRAM_BOT_TOKEN，无法启动")
            return

        self._stop_requested = False
        self._stop_event.clear()
        retry_count = 0
        while not self._stop_requested:
            try:
                await self._run_once()
                if self._stop_requested:
                    break
                raise RuntimeError("Telegram 轮询意外结束")
            except asyncio.CancelledError:
                self._stop_requested = True
                self._stop_event.set()
                raise
            except Exception as e:
                self.last_error = e
                if self._stop_requested:
                    break
                retry_count += 1
                delay = min(30.0, 2.0 * (2 ** max(0, retry_count - 1)))
                logger.error(
                    f"Telegram 适配器运行失败，{delay:.1f}s 后重启（第 {retry_count} 次）: {e}",
                    exc_info=True,
                )
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass

    async def _run_once(self):
        """执行一次完整的初始化、轮询和清理周期。"""
        self.running = True
        self.ready_event.clear()
        logger.info("正在启动 Telegram Adapter...")
        try:
            ok = await self.health_checker.prelight_check(
                self.xiaoyou_http_base_url, self.xiaoyou_ws_url
            )
            if not ok:
                logger.warning("后端健康检查未通过，仍尝试启动")

            await self.initialize()
            if self.application is None:
                raise RuntimeError("Telegram Application 初始化结果为空")
            await self.application.initialize()
            await self.application.start()
            if not self.application.updater:
                raise RuntimeError("Telegram Application 没有 updater")
            await self.application.updater.start_polling()
            self.last_error = None
            self.ready_event.set()
            logger.info("Telegram 轮询已启动，正在监听消息")

            if self.session_timeout_seconds > 0:
                self._session_cleanup_task = asyncio.create_task(
                    self._session_cleanup_loop(), name="telegram_session_cleanup"
                )

            while self.running and not self._stop_requested:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
        finally:
            await self._cleanup_runtime()

    async def _cleanup_runtime(self):
        """幂等释放本轮 Telegram 运行资源。"""
        async with self._cleanup_lock:
            self.running = False
            self.ready_event.clear()

            cleanup_task = self._session_cleanup_task
            self._session_cleanup_task = None
            if cleanup_task and cleanup_task is not asyncio.current_task():
                cleanup_task.cancel()
                try:
                    await cleanup_task
                except asyncio.CancelledError:
                    pass

            async with self._session_lock:
                sessions = list(self.sessions.values())
                self.sessions.clear()
            for session in sessions:
                await session.stop()

            application = self.application
            self.application = None
            if application:
                try:
                    if application.updater and application.updater.running:
                        await application.updater.stop()
                    if application.running:
                        await application.stop()
                    await application.shutdown()
                except Exception as e:
                    logger.warning(f"停止 Telegram Application 异常: {e}")

            await self.http_client.close()

    async def stop(self):
        """停止适配器及自动重启监督循环。"""
        logger.info("正在停止 Telegram Adapter...")
        self._stop_requested = True
        self._stop_event.set()
        self.running = False
        await self._cleanup_runtime()
        logger.info("Telegram Adapter 已停止")


def run_adapter():
    """启动 Telegram 适配器（独立运行入口）。"""
    adapter = TelegramAdapter()
    try:
        asyncio.run(adapter.run())
    except KeyboardInterrupt:
        logger.info("Telegram Adapter 被用户停止")
    except Exception as e:
        logger.error(f"致命错误: {e}", exc_info=True)
        if os.name == "nt":
            input("按回车键退出...")


if __name__ == "__main__":
    run_adapter()
