"""QQ 适配器会话薄壳门面（Facade）。

本文件原为 1095 行的单体类，已按职责拆分为 5 个子模块：
- qq_adapter_session_heartbeat.py  心跳处理
- qq_adapter_session_state.py      状态/打字延迟/仿生
- qq_adapter_session_message.py    消息断句/发送/去重
- qq_adapter_session_connection.py WS 连接/重连/诊断
- qq_adapter_session_receiver.py   消息接收分发

XiaoyouSession 作为门面保留，外部 API 完全兼容，原方法委托到各子模块。
保留 asyncio / random 导入以兼容测试中的 patch 路径。
"""
import asyncio
import random  # noqa: F401  保留以兼容测试 patch 路径 clients.bots.qq_adapter_session.random
import time

from clients.bots.qq.settings import logger
from clients.bots.qq.utils import build_persona_conversation_id
from clients.bots.qq.session.heartbeat import SessionHeartbeatHandler
from clients.bots.qq.session.state import SessionStateManager
from clients.bots.qq.session.message import SessionMessageHandler
from clients.bots.qq.session.connection import SessionConnectionManager
from clients.bots.qq.session.receiver import SessionReceiver


class XiaoyouSession:
    """QQ 适配器会话门面类，委托各子模块完成实际工作。"""

    _global_proactive_messages = {}
    _global_proactive_lock = None

    def __init__(self, session_id, adapter):
        self.session_id = session_id
        self.adapter = adapter
        self.ws = None
        self.running = False
        self.last_activity = time.time()
        self.queue = asyncio.Queue()
        self.task = None
        self.debug_mode = False
        self.is_voice_input = False
        self._force_full_response = False
        self._surprise_delay_used = False
        self._bionic_profile = {}
        self._bionic_profile_expire_ts = 0.0
        self._recent_proactive_messages = {}
        self._recent_outbound_full_responses = {}
        self._in_smart_sleep = False
        self._connection_state = "disconnected"
        self._last_connected_at = 0.0
        self._connection_failure_since = 0.0
        self._split_disabled = False  # 断句开关：True 表示禁用断句
        self._start_time = time.time()  # 记录启动时间，用于延迟报错

        # 创建各职责子模块，注入 session 实例
        self._heartbeat_handler = SessionHeartbeatHandler(self)
        self._state_manager = SessionStateManager(self)
        self._message_handler = SessionMessageHandler(self)
        self._connection_manager = SessionConnectionManager(self)
        self._receiver = SessionReceiver(self)

    @property
    def _cfg(self):
        return self.adapter.cfg

    @property
    def _client_id(self) -> str:
        """统一的 WebSocket client_id，multi_qq 模式下包含 role_id 区分不同 adapter"""
        role_prefix = f"{self._cfg.role_id}_" if getattr(self._cfg, "role_id", "") else ""
        return f"qq_{role_prefix}{self.session_id}"

    def _get_current_persona_filename(self) -> str:
        """获取当前会话使用的角色配置文件名"""
        # 1. 优先使用 session prefs
        prefs = self.adapter._session_prefs.get(self.session_id) if isinstance(getattr(self.adapter, "_session_prefs", None), dict) else {}
        if isinstance(prefs, dict):
            fn = str(prefs.get("persona_filename") or "").strip()
            if fn:
                return fn
        # 2. 回退到 adapter 配置
        fn = str(getattr(self._cfg, "persona_filename", "") or "").strip()
        if fn:
            return fn
        # 3. 回退到全局 PersonaManager
        try:
            from core.character.managers.persona_manager import get_persona_manager
            pm = get_persona_manager()
            fn = str(pm.get_current_filename() or "").strip()
            if fn:
                return fn
        except Exception:
            pass
        return ""

    @classmethod
    def _get_global_proactive_lock(cls):
        if cls._global_proactive_lock is None:
            cls._global_proactive_lock = asyncio.Lock()
        return cls._global_proactive_lock

    async def _is_duplicate_proactive_global(self, text: str, window_seconds: float = 90.0) -> bool:
        now = time.time()
        normalized = "".join(str(text or "").split())
        if not normalized:
            return False
        if len(normalized) > 180:
            normalized = normalized[:180]
        async with self._get_global_proactive_lock():
            expired_keys = [
                k
                for k, ts in XiaoyouSession._global_proactive_messages.items()
                if (now - float(ts)) > max(120.0, window_seconds * 2)
            ]
            for k in expired_keys:
                XiaoyouSession._global_proactive_messages.pop(k, None)
            last_ts = float(XiaoyouSession._global_proactive_messages.get(normalized) or 0.0)
            if last_ts and (now - last_ts) <= window_seconds:
                return True
            XiaoyouSession._global_proactive_messages[normalized] = now
            return False

    async def start(self):
        self.running = True
        self.task = asyncio.create_task(self._run_loop())

    async def stop(self):
        self.running = False
        if self.ws:
            await self.ws.close()
        if self.task:
            self.task.cancel()
            current_task = asyncio.current_task()
            if self.task is not current_task:
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass

    async def send_text(self, text, model=None, peer_role_context=None, sender_identity_context=None):
        self.last_activity = time.time()
        self._surprise_delay_used = False
        self._bionic_profile = {}
        self._bionic_profile_expire_ts = 0.0
        if self._cfg.qq_stream_split:
            self._force_full_response = len(str(text or "")) >= self._cfg.qq_stream_long_threshold
        payload = {
            "type": "text_input",
            "text": text,
            "content": text,
            "client_id": self._client_id,
            "user_id": self.session_id,
            "platform": "qq",
            "_send_ts": time.time() * 1000,
        }
        if bool(getattr(self._cfg, "qq_skip_backend_merge_wait", True)):
            payload["skip_merge_wait"] = True
        if model:
            payload["model"] = str(model)
        else:
            # 如果没有显式指定模型，尝试从 session_prefs 中获取
            try:
                prefs = self.adapter._session_prefs.get(self.session_id)
                if prefs:
                    chat_model = prefs.get("chat_model")
                    if chat_model:
                        payload["model"] = str(chat_model)
            except Exception:
                pass
        try:
            # 1. 优先使用 session prefs（用户可能通过 /切人设 命令切换过）
            current_persona = ""
            prefs = self.adapter._session_prefs.get(self.session_id) or {}
            current_persona = str(prefs.get("persona_filename") or "").strip()
            persona_source = "session_prefs"

            # 2. 回退到 adapter 自身配置的 persona_filename（双QQ等per-connection场景）
            if not current_persona:
                current_persona = str(self._cfg.persona_filename or "").strip()
                persona_source = "adapter_cfg"

            # 3. 最后回退到全局 PersonaManager
            if not current_persona:
                try:
                    from core.character.managers.persona_manager import get_persona_manager
                    pm = get_persona_manager()
                    current_persona = str(pm.get_current_filename() or "").strip()
                    persona_source = "global_persona_manager"
                except Exception:
                    persona_source = "none"

            # [DEBUG] 关键日志：定位 persona_filename 在 send_text 中的来源
            logger.info(
                f"[send_text] session={self.session_id}, adapter_role_id={getattr(self._cfg, 'role_id', '')!r}, "
                f"adapter_persona={getattr(self._cfg, 'persona_filename', '')!r}, "
                f"prefs_persona={prefs.get('persona_filename')!r}, "
                f"final_persona={current_persona!r}, source={persona_source}"
            )

            payload["conversation_id"] = build_persona_conversation_id(self.session_id, current_persona)
            logger.info(f"QQ Adapter built conversation_id: {payload['conversation_id']} from persona={current_persona}, session={self.session_id}")
            if current_persona:
                payload["persona_filename"] = current_persona
        except Exception as e:
            logger.warning(f"Failed to build persona conversation_id: {e}, fallback to session_id={self.session_id}")
            payload["conversation_id"] = self.session_id

        if getattr(self, "debug_mode", False):
            payload["save_history"] = False
        if isinstance(peer_role_context, dict) and peer_role_context:
            payload["peer_role_context"] = dict(peer_role_context)
        if isinstance(sender_identity_context, dict) and sender_identity_context:
            payload["sender_identity_context"] = dict(sender_identity_context)

        logger.info(f"[{self.session_id}] [{payload['_send_ts']:.0f}ms] Putting msg into queue")
        await self.queue.put(payload)

    # ===== 以下为委托方法，转发到各子模块 =====

    # --- 连接管理委托 ---
    async def _run_loop(self):
        await self._connection_manager.run_loop()

    def _extract_host_port(self, ws_url: str):
        return self._connection_manager.extract_host_port(ws_url)

    def _is_conn_refused(self, err: Exception) -> bool:
        return self._connection_manager.is_conn_refused(err)

    def _probe_tcp_port(self, host: str, port: int, timeout_s: float = 0.3) -> bool:
        return self._connection_manager.probe_tcp_port(host, port, timeout_s)

    async def _notify_connection_issue(self, ws_url: str, err: Exception):
        await self._connection_manager.notify_connection_issue(ws_url, err)

    # --- 状态管理委托 ---
    async def _load_bionic_profile(self):
        await self._state_manager.load_bionic_profile()

    def _resolve_comma_split_probability(self) -> float:
        return self._state_manager.resolve_comma_split_probability()

    def _calc_typing_delay(
        self,
        sentence: str,
        is_last_chunk: bool = False,
        allow_surprise_delay: bool = False,
    ) -> float:
        return self._state_manager.calc_typing_delay(
            sentence, is_last_chunk=is_last_chunk, allow_surprise_delay=allow_surprise_delay
        )

    async def _smart_sleep(self, seconds: float):
        await self._state_manager.smart_sleep(seconds)

    # --- 消息处理委托 ---
    async def _process_stream_buffer(self, buffer: str) -> tuple[str, bool]:
        return await self._message_handler.process_stream_buffer(buffer)

    async def _send_full_response_with_split(
        self,
        full_response: str,
        *,
        enable_surprise_delay: bool = False,
    ):
        await self._message_handler.send_full_response_with_split(
            full_response, enable_surprise_delay=enable_surprise_delay
        )

    def _extract_voice_tag(self, text: str):
        return self._message_handler.extract_voice_tag(text)

    def _is_duplicate_full_response(self, text: str, window_seconds: float = 8.0) -> bool:
        return self._message_handler.is_duplicate_full_response(text, window_seconds)

    def _compress_repeated_chunks(self, chunks: list[str]) -> list[str]:
        return self._message_handler.compress_repeated_chunks(chunks)

    async def _send_response(self, content: str, allow_session_tts: bool = True):
        await self._message_handler.send_response(content, allow_session_tts=allow_session_tts)

    # --- 心跳处理委托 ---
    async def _handle_server_heartbeat(self, data: dict) -> bool:
        return await self._heartbeat_handler.handle_server_heartbeat(data)

    # --- 接收处理委托 ---
    async def _receive_from_xiaoyou(self):
        await self._receiver.receive_from_xiaoyou()
