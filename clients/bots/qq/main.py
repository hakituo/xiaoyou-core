"""QQ 适配器协调器。

职责已委托到各专职组件：
- HttpClient / HealthChecker / BionicProfileService: HTTP 通信与健康检查
- VoiceService: 语音处理
- ConfigManager: 配置同步
- MessagePipeline + MessageDispatcher: 消息处理管线与分发
- SessionMonitor: 主会话监控
- FaceProcessor: 表情处理
- NapcatTransport: 传输层
"""
import asyncio
import logging
import os
import re

from clients.bots.qq.config import QQAdapterConfig
from clients.bots.qq.emotion import EmotionManager, FaceProcessor
from clients.bots.qq.face import QQFaceInjector
from clients.bots.qq.http_client import BionicProfileService, HealthChecker, HttpClient
from clients.bots.qq.intent import SemanticIntentRecognizer
from clients.bots.qq.config_manager import ConfigManager
from clients.bots.qq.voice_service import VoiceService
from clients.bots.qq.message_pipeline import (
    ChatDispatchProcessor, CommandRoutingProcessor, IntentRoutingProcessor,
    MessageContext, MessageDispatcher, MessagePipeline, PreprocessProcessor,
)
from clients.bots.qq.peer_chat import PeerChatManager
from clients.bots.qq.aggregator import MessageAggregator
from clients.bots.qq.transport import NapcatTransport
from clients.bots.qq.session.monitor import SessionMonitor
from clients.bots.qq.settings import CONFIG_FILE, PROJECT_ROOT, logger

from clients.bots.handlers.dashboard import DashboardHandler
from clients.bots.handlers.resources import ResourceHandler
from clients.bots.handlers.food import FoodHandler
from clients.bots.handlers.system import SystemHandler
from clients.bots.handlers.media import MediaHandler
from clients.bots.handlers.config import ConfigHandler
from clients.bots.handlers.lifecycle import LifecycleHandler
from clients.bots.handlers.openclaw import OpenClawHandler
from clients.bots.handlers.meme import MemeHandler
from clients.bots.handlers.command_router import CommandRouter
from clients.bots.handlers.intent import IntentHandler
from core.utils.async_locks import LazyAsyncLock


class _PrefixLogAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"{self.extra.get('prefix', '')}{msg}", kwargs


class QQAdapter:
    """QQ 适配器协调器，委托所有职责到专职组件。"""

    # 实例注册表（内联自 instance_registry.py）
    _instances: dict[str, "QQAdapter"] = {}

    def __init__(self, adapter_config=None):
        self.cfg = adapter_config or QQAdapterConfig.from_env()
        self._register_instance()

        self.logger = self._init_logger()

        # 核心服务
        self.http_client = HttpClient(self.cfg.xiaoyou_http_base_url, self.cfg.xiaoyou_access_token,
                                      self.cfg.http_timeout_seconds, self.logger)
        self.health_checker = HealthChecker(self.http_client, self.logger)
        self.config_manager = ConfigManager(self.http_client, self.cfg, self.logger)
        self.voice_service = VoiceService(self.http_client, str(self.cfg.role_id or "").strip(),
                                          self.cfg.role_name or "", self.cfg.xiaoyou_access_token, self.logger)
        self.bionic_profile_service = BionicProfileService(self.http_client, self.cfg, self.logger)

        # 兼容旧代码的属性
        self._http_session = None
        self._http_session_lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._config_lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._session_prefs = {}
        self._user_overrides = dict(self.cfg.user_overrides)
        self._project_root = PROJECT_ROOT
        self._pending_message_tasks = set()
        self._bionic_profile_cache = {}
        self._list_cache = {}
        self._conn_issue_notified = {}
        self.reply_mode = self.cfg.reply_mode
        self.reply_voice_only = self.cfg.reply_voice_only
        self._cleanup_task = None
        self._master_monitor_task = None

        # 子模块
        self.sessions = {}
        self.face_injector = QQFaceInjector(enabled=self.cfg.enable_qq_face_injection)
        self.semantic_recognizer = SemanticIntentRecognizer()
        self.emotion_manager = EmotionManager()
        self.peer_chat_manager = PeerChatManager()
        self.aggregator = MessageAggregator(
            buffer_window=max(0.0, float(getattr(self.cfg, "qq_message_buffer_window_seconds", 0.35) or 0.0)),
            buffer_max=max(1, int(getattr(self.cfg, "qq_message_buffer_max", 8) or 8)),
        )
        self.transport = NapcatTransport(self.cfg)
        self.face_processor = FaceProcessor(self.emotion_manager, self.face_injector)

        # Handlers
        self.dashboard_handler = DashboardHandler(self)
        self.resource_handler = ResourceHandler(self)
        self.food_handler = FoodHandler(self)
        self.system_handler = SystemHandler(self)
        self.media_handler = MediaHandler(self)
        self.config_handler = ConfigHandler(self)
        self.lifecycle_handler = LifecycleHandler(self)
        self.openclaw_handler = OpenClawHandler(self)
        self.meme_handler = MemeHandler(self)
        self.command_router = CommandRouter(self)
        self.intent_handler = IntentHandler(self)

        # 分发器、监控器、消息管线
        self.message_dispatcher = MessageDispatcher(self)
        self.session_monitor = SessionMonitor(self)
        self.message_pipeline = MessagePipeline([
            PreprocessProcessor(self.face_injector, self.media_handler,
                                self.cfg.enable_qq_vision, self.cfg.enable_qq_voice),
            CommandRoutingProcessor(self),
            IntentRoutingProcessor(self.semantic_recognizer, self.intent_handler,
                                   self.reply_mode, self.cfg.enable_llm_intent_router, self.logger),
            ChatDispatchProcessor(self, self.logger),
        ], self.logger)

    # ===== 日志/注册表 =====

    def _init_logger(self):
        prefix = f"[{self.cfg.role_name}] " if self.cfg.role_name else (
            f"[{self.cfg.role_id}] " if self.cfg.role_id else "")
        return _PrefixLogAdapter(logger, {"prefix": prefix}) if prefix else logger

    def _register_instance(self):
        key = str(self.cfg.role_id or self.cfg.persona_filename or id(self)).strip()
        if key:
            QQAdapter._instances[key] = self

    @classmethod
    def get_active_instances(cls) -> list[dict[str, str]]:
        result = []
        for adapter in list(cls._instances.values()):
            transport = getattr(adapter, "transport", None)
            if not transport or not getattr(transport, "running", False):
                continue
            result.append({
                "role_id": str(adapter.cfg.role_id or "").strip(),
                "persona_filename": str(adapter.cfg.persona_filename or "").strip(),
                "master_qq_id": str(adapter.cfg.master_qq_id or "").strip(),
                "napcat_ws_url": str(adapter.cfg.napcat_ws_url or "").strip(),
            })
        return result

    @classmethod
    def _unregister_instance(cls, adapter):
        cls._instances = {k: v for k, v in cls._instances.items() if v is not adapter}

    # ===== 配置/身份 =====

    def _is_master(self, user_id: str) -> bool:
        return str(user_id) == str(self.cfg.master_qq_id)

    def _is_peer_private_chat_enabled(self) -> bool:
        try:
            from config.integrated_config import get_settings
            return bool(getattr(get_settings().dual_role, "peer_private_chat_enabled", True))
        except Exception:
            return True

    def _build_sender_identity_context(self, *, is_master, is_peer_bot, peer_qq_id=""):
        return PeerChatManager.build_sender_identity_context(
            role_id=str(self.cfg.role_id or "").strip(), is_master=is_master,
            is_peer_bot=is_peer_bot, peer_qq_id=peer_qq_id)

    def _build_peer_role_context(self):
        return PeerChatManager.build_peer_role_context(
            str(self.cfg.role_id or "").strip(), str(self.cfg.role_name or "").strip())

    # ===== 情绪/表情 =====

    def update_emotion(self, session_id, emotion_data):
        self.emotion_manager.update_emotion(session_id, emotion_data)

    def _select_face_label_from_emotion(self, session_id):
        return self.emotion_manager.select_face_label_from_emotion(session_id)

    def _augment_face_label(self, session_id, content):
        return self.emotion_manager.augment_face_label(session_id, content)

    def _extract_emo_label(self, content):
        return EmotionManager.extract_emo_label(content)

    # ===== 语音（委托 VoiceService）=====

    def _wants_voice_reply(self, text):
        return self.voice_service.wants_voice_reply(text)

    async def _send_voice_response(self, session_id, text, reference_audio=None):
        async def _send(sid, cq_code):
            # NapCat 收到 record CQ 码后还要异步转码。这里必须等待 action
            # 返回，避免下一段文字在语音真正投递前抢先发出。
            return await self.transport.send_message(
                sid,
                cq_code,
                master_qq_id=self.cfg.master_qq_id,
                peer_qq_id=self.cfg.peer_qq_id,
                strip_markdown=self.cfg.qq_strip_markdown,
                wait_for_result=True,
            )
        return await self.voice_service.send_voice_response(session_id, text, reference_audio, send_callback=_send)

    async def _should_reply_voice_only(self, session_id, content):
        return await self.voice_service.should_reply_voice_only(
            content, get_prefs=lambda: self._session_prefs.get(session_id),
            default_voice_only=bool(getattr(self, "reply_voice_only", False)))

    # ===== 消息发送 =====

    async def send_to_napcat(self, session_id, content):
        if not self.transport.is_connected():
            return
        if self.cfg.peer_qq_id and session_id in (
            f"private_{self.cfg.peer_qq_id}", f"peer_{self.cfg.peer_qq_id}"
        ) and not self._is_peer_private_chat_enabled():
            self.logger.info(f"双角色私聊已关闭，阻止发送给对方bot: {session_id}")
            return

        content, emo_label = self._extract_emo_label(content)
        content = re.sub(r"。\.{3,}", "......", content.strip())
        content = re.sub(r"。…+", "……", content)

        # 语音回复检查
        try:
            prefs = self._session_prefs.get(session_id) if isinstance(self._session_prefs, dict) else None
            if isinstance(prefs, dict) and bool(prefs.get("reply_voice_once")):
                prefs["reply_voice_once"] = False
                if await self._send_voice_response(session_id, content, prefs.get("reference_audio")):
                    return
            if await self._should_reply_voice_only(session_id, content):
                ref = prefs.get("reference_audio") if isinstance(prefs, dict) else None
                if await self._send_voice_response(session_id, content, ref):
                    return
        except Exception:
            pass

        await self.transport.send_message(
            session_id, content, master_qq_id=self.cfg.master_qq_id,
            peer_qq_id=self.cfg.peer_qq_id, strip_markdown=self.cfg.qq_strip_markdown,
            face_processor=self.face_processor.build_processor(session_id, emo_label))

    async def _send_friendly_error(self, session_id, context_msg, error_detail=None):
        await self.transport.send_friendly_error(session_id, context_msg, error_detail)

    # ===== 消息处理（委托 MessageDispatcher / MessagePipeline）=====

    def _track_pending_task(self, task):
        self._pending_message_tasks.add(task)
        task.add_done_callback(self._pending_message_tasks.discard)

    async def _process_post_message(self, data, self_id):
        await self.message_dispatcher.process_post_message(data, self_id)

    async def _run_message_pipeline(self, *, session_id, msg_type, user_id, raw_message,
                                    self_id, is_at_me, group_id, session):
        import time
        start = time.time()
        ctx = MessageContext(
            session_id=session_id, msg_type=msg_type, user_id=user_id, raw_message=raw_message,
            self_id=self_id, is_at_me=is_at_me, group_id=group_id, session=session,
            is_master=self._is_master(user_id),
            is_peer_bot=bool(self.cfg.peer_qq_id and str(user_id) == str(self.cfg.peer_qq_id)))
        ctx = await self.message_pipeline.process(ctx)
        elapsed = time.time() - start
        if elapsed > 0.1:
            t = ctx.timings
            self.logger.info(f"[{session_id}] 消息处理耗时: {elapsed:.3f}s "
                             f"(指令={t.get('cmd', 0):.3f}s 意图={t.get('intent', 0):.3f}s 发送={t.get('chat', 0):.3f}s)")

    async def _try_handle_command(self, session_id, msg_type, qq_user_id, raw_message, group_id):
        """命令处理兼容方法（委托给 CommandRoutingProcessor，供旧测试调用）"""
        ctx = MessageContext(session_id=session_id, msg_type=msg_type, user_id=qq_user_id,
                            raw_message=raw_message, self_id="", is_at_me=False, group_id=group_id,
                            session=None, display_msg=raw_message)
        return await self.message_pipeline.processors[1]._try_handle_command(ctx)

    # ===== HTTP（委托 HttpClient，兼容旧代码）=====

    async def _get_http_session(self):
        session = await self.http_client.get_session()
        self._http_session = session
        return session

    async def _api_request(self, method, path, json_body=None, params=None, timeout_seconds=None):
        return await self.http_client.request(method, path, json_body, params, timeout_seconds)

    async def get_bionic_delay_profile(self, session_id, force_refresh=False):
        return await self.bionic_profile_service.get_profile(session_id, force_refresh)

    # ===== 连接/生命周期 =====

    async def connect_napcat(self):
        async def message_handler(message):
            data = await self.transport.handle_message(message)
            if data:
                task = asyncio.create_task(self._process_post_message(data, str(data.get("self_id", ""))))
                self._track_pending_task(task)

        if not self._cleanup_task:
            self._cleanup_task = asyncio.create_task(self.lifecycle_handler.cleanup_loop())
        if not self._master_monitor_task:
            self._master_monitor_task = asyncio.create_task(self.session_monitor.monitor_master_session())
        try:
            await self.session_monitor.ensure_master_private_session()
        except Exception:
            pass
        await self.transport.connect(message_handler)

    async def call_napcat_action(self, action, params=None, timeout_seconds=8.0):
        return await self.transport.call_action(action, params, timeout_seconds)

    async def handle_napcat_message(self, message):
        data = await self.transport.handle_message(message)
        if data:
            task = asyncio.create_task(self._process_post_message(data, str(data.get("self_id", ""))))
            self._track_pending_task(task)

    async def _preflight_check(self):
        await self.health_checker.preflight_check(
            config_file=CONFIG_FILE, napcat_ws_url=self.cfg.napcat_ws_url,
            xiaoyou_ws_url=self.cfg.xiaoyou_ws_url, xiaoyou_http_base_url=self.cfg.xiaoyou_http_base_url)

    async def _sync_config_from_backend(self):
        await self.config_manager.sync_from_backend(
            get_reference_audio=self.resource_handler._get_persona_audio,
            persist_config=self.config_handler.persist_user_override,
            on_config_updated=self._session_prefs.clear)

    # ===== 入口 =====

    async def run(self):
        try:
            await self._preflight_check()
            await self._sync_config_from_backend()
            await self.connect_napcat()
        finally:
            self._unregister_instance(self)
            for task in (self._master_monitor_task, self._cleanup_task):
                if task:
                    try:
                        task.cancel()
                    except Exception:
                        pass
            await self.http_client.close()


if __name__ == "__main__":
    adapter = QQAdapter()
    try:
        asyncio.run(adapter.run())
    except KeyboardInterrupt:
        logger.info("QQ Adapter stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        if os.name == "nt":
            input("Press Enter to exit...")
