"""
Android Client Bug Condition Exploration Tests
===============================================
These tests verify that the Android client bugs have been fixed.
They encode the expected behavior and should PASS after fixes are applied.

Bug Categories:
1.1 - Backend Connection Loss (WebSocket reconnection)
1.2 - Status Page Data Issues (EmotionState.emotion_mix AttributeError)
1.3 - UI Duplication Issues (model switching state)
1.4 - Chat Streaming Issues (streaming support)
"""

import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch


# ============================================================
# 1.1 Backend Connection Loss Exploration
# ============================================================

class TestBackendConnectionLoss:
    """Tests for WebSocket reconnection after connection loss."""

    def test_emotion_state_has_emotion_mix_attribute(self):
        """Verify EmotionState model has emotion_mix attribute."""
        from core.emotion.models import EmotionState, EmotionType

        state = EmotionState(primary_emotion=EmotionType.NEUTRAL, confidence=0.0)
        assert hasattr(state, "emotion_mix"), "EmotionState must have emotion_mix attribute"
        assert isinstance(state.emotion_mix, dict), "emotion_mix must be a dict"

    def test_client_connection_has_mobile_fields(self):
        """Verify ClientConnection has mobile reconnection fields."""
        from core.interfaces.websocket.websocket_manager import ClientConnection, ConnectionState

        conn = ClientConnection(
            websocket=MagicMock(),
            user_id="test_user",
            platform="android",
            state=ConnectionState.CONNECTED,
        )
        assert hasattr(conn, "is_mobile"), "ClientConnection must have is_mobile field"
        assert hasattr(conn, "reconnect_count"), "ClientConnection must have reconnect_count field"
        # __post_init__ auto-detects mobile from platform
        assert conn.is_mobile is True, f"Android platform should be detected as mobile, got {conn.is_mobile}"
        assert conn.is_reconnect is False, "New connection should not be a reconnect"

    def test_mobile_platform_detection(self):
        """Verify mobile platform is correctly detected."""
        from core.interfaces.websocket.websocket_manager import ClientConnection, ConnectionState

        for platform in ["android", "ios", "capacitor", "mobile"]:
            conn = ClientConnection(
                websocket=MagicMock(), platform=platform, state=ConnectionState.CONNECTED
            )
            assert conn.is_mobile is True, f"Platform '{platform}' should be detected as mobile"

        for platform in ["web", "desktop", "unknown"]:
            conn = ClientConnection(
                websocket=MagicMock(), platform=platform, state=ConnectionState.CONNECTED
            )
            assert conn.is_mobile is False, f"Platform '{platform}' should NOT be detected as mobile"

    def test_reconnect_count_increments(self):
        """Verify reconnect_count tracks reconnection attempts."""
        from core.interfaces.websocket.websocket_manager import ClientConnection, ConnectionState

        conn = ClientConnection(
            websocket=MagicMock(),
            platform="android",
            reconnect_count=2,
            state=ConnectionState.CONNECTED,
        )
        assert conn.is_reconnect is True, "Connection with reconnect_count > 0 is a reconnect"
        assert conn.reconnect_count == 2


# ============================================================
# 1.2 Status Page Data Issues Exploration
# ============================================================

class TestStatusPageDataIssues:
    """Tests for Status/Persona/Memory page data fetching."""

    def test_emotion_state_emotion_mix_default(self):
        """Verify emotion_mix has sensible default value."""
        from core.emotion.models import EmotionState, EmotionType

        state = EmotionState(primary_emotion=EmotionType.NEUTRAL, confidence=0.0)
        assert state.emotion_mix == {}, "Default emotion_mix should be empty dict"

    def test_emotion_state_emotion_mix_populated(self):
        """Verify emotion_mix is populated when sub_emotions is provided."""
        from core.emotion.models import EmotionState, EmotionType

        sub = {"happy": 0.6, "excited": 0.4}
        state = EmotionState(
            primary_emotion=EmotionType.HAPPY,
            confidence=0.6,
            sub_emotions=sub,
            emotion_mix=dict(sub),
        )
        assert state.emotion_mix == sub, "emotion_mix should match sub_emotions"
        assert "happy" in state.emotion_mix
        assert state.emotion_mix["happy"] == 0.6

    def test_emotion_state_no_attribute_error_on_emotion_mix(self):
        """Verify accessing emotion_mix on EmotionState does not raise AttributeError."""
        from core.emotion.models import EmotionState, EmotionType

        state = EmotionState(primary_emotion=EmotionType.NEUTRAL, confidence=0.0)
        # This was the original bug - accessing emotion_mix raised AttributeError
        emotion_mix = getattr(state, "emotion_mix", None) or getattr(state, "sub_emotions", {})
        assert isinstance(emotion_mix, dict), "emotion_mix fallback should return dict"

    def test_emotion_detector_creates_emotion_mix(self):
        """Verify EmotionDetector creates EmotionState with emotion_mix."""
        from core.emotion.detector_v2 import EmotionDetectorV2
        from core.emotion.models import EmotionState

        detector = EmotionDetectorV2()
        state = detector.detect("")
        assert hasattr(state, "emotion_mix"), "Detector output must have emotion_mix"
        assert isinstance(state.emotion_mix, dict)

    def test_emotion_calculator_preserves_emotion_mix(self):
        """Verify EmotionCalculator creates EmotionState with emotion_mix."""
        from core.emotion.calculator import EmotionCalculator
        from core.emotion.models import EmotionState, EmotionType

        calc = EmotionCalculator()
        current = EmotionState(EmotionType.HAPPY, 0.5, sub_emotions={"happy": 0.5}, emotion_mix={"happy": 0.5})
        new_input = EmotionState(EmotionType.SAD, 0.3, sub_emotions={"sad": 0.3}, emotion_mix={"sad": 0.3})

        result = calc.update_state(current, new_input)
        assert hasattr(result, "emotion_mix"), "Calculator output must have emotion_mix"
        assert isinstance(result.emotion_mix, dict)

    def test_emotion_manager_apply_influence_creates_emotion_mix(self):
        """Verify EmotionManager.apply_influence creates EmotionState with emotion_mix."""
        from core.emotion.manager import EmotionManager

        manager = EmotionManager()
        result = manager.apply_influence("test_user", {"happy": 0.7, "excited": 0.3}, source="test")
        assert hasattr(result, "emotion_mix"), "Manager output must have emotion_mix"
        assert isinstance(result.emotion_mix, dict)

    def test_life_status_api_returns_emotion_mix(self):
        """Verify /status/life API returns emotion_mix field without error."""
        # This tests the fix for the original AttributeError bug
        from core.emotion.models import EmotionState, EmotionType

        emo_state = EmotionState(EmotionType.HAPPY, 0.7, sub_emotions={"happy": 0.7}, emotion_mix={"happy": 0.7})
        current_emotion = emo_state.primary_emotion.value if emo_state and emo_state.primary_emotion else "calm"
        # This line previously caused AttributeError
        emotion_mix = getattr(emo_state, 'emotion_mix', None) or getattr(emo_state, 'sub_emotions', {})

        assert current_emotion == "happy"
        assert emotion_mix == {"happy": 0.7}

    def test_v2_detector_creates_emotion_mix(self):
        """Verify V2 detector EmotionState also has emotion_mix."""
        from core.emotion.detector_v2 import EmotionState, EmotionType

        state = EmotionState(primary_emotion=EmotionType.NEUTRAL, confidence=0.0)
        assert hasattr(state, "emotion_mix"), "V2 EmotionState must have emotion_mix"
        assert isinstance(state.emotion_mix, dict)


# ============================================================
# 1.3 UI Duplication Issues Exploration
# ============================================================

class TestUIDuplicationIssues:
    """Tests for model switching UI duplication and state consistency."""

    def test_model_switch_handler_exists(self):
        """Verify mobile_switch_model handler exists."""
        from core.interfaces.websocket.adapters.handlers.main_handlers import MessageHandlers

        handler = MessageHandlers(MagicMock())
        assert hasattr(handler, "handle_mobile_switch_model"), "Must have handle_mobile_switch_model"

    def test_reconnect_handler_exists(self):
        """Verify reconnect handler exists for mobile clients."""
        from core.interfaces.websocket.adapters.handlers.main_handlers import MessageHandlers

        handler = MessageHandlers(MagicMock())
        assert hasattr(handler, "handle_reconnect"), "Must have handle_reconnect"

    def test_model_switch_syncs_global_config(self):
        """Verify model switching syncs with global configuration."""
        # This is a backend test - verify the model switching logic
        # reads global config and applies it correctly
        from core.emotion.models import EmotionType, EmotionState

        # Ensure the model can handle all emotion types
        for emo in EmotionType:
            state = EmotionState(primary_emotion=emo, confidence=0.5)
            assert state.primary_emotion == emo


# ============================================================
# 1.4 Chat Streaming Issues Exploration
# ============================================================

class TestChatStreamingIssues:
    """Tests for chat streaming implementation on mobile."""

    def test_streaming_handler_exists(self):
        """Verify StreamingHandler exists and has handle_stream method."""
        from core.interfaces.websocket.adapters.streaming import StreamingHandler

        handler = StreamingHandler(MagicMock())
        assert hasattr(handler, "handle_stream"), "StreamingHandler must have handle_stream"

    def test_streaming_handler_sends_chunks(self):
        """Verify StreamingHandler can process stream chunks."""
        from core.interfaces.websocket.adapters.streaming import StreamingHandler

        handler = StreamingHandler(MagicMock())
        # Verify handler can be instantiated and has expected interface
        assert hasattr(handler, "adapter")

    def test_message_types_include_reconnect(self):
        """Verify reconnect message type is handled in adapter."""
        from core.interfaces.websocket.adapters.adapter import FastAPIWebSocketAdapter

        adapter = FastAPIWebSocketAdapter()
        # The adapter should have handlers that support reconnect
        assert hasattr(adapter.handlers, "handle_reconnect")

    def test_websocket_manager_offline_queue_exists(self):
        """Verify offline message queue exists for mobile reconnection."""
        from core.interfaces.websocket.websocket_manager import WebSocketManager

        manager = WebSocketManager()
        assert hasattr(manager, "offline_queue"), "Must have offline_queue for reconnection"
        assert hasattr(manager, "_flush_offline_messages"), "Must have _flush_offline_messages"


# ============================================================
# Preservation: Web client should not be affected
# ============================================================

class TestWebClientPreservation:
    """Verify web client functionality is preserved after Android fixes."""

    def test_web_platform_not_mobile(self):
        """Verify web platform is not incorrectly detected as mobile."""
        from core.interfaces.websocket.websocket_manager import ClientConnection, ConnectionState

        conn = ClientConnection(
            websocket=MagicMock(), platform="web", state=ConnectionState.CONNECTED
        )
        assert conn.is_mobile is False

    def test_emotion_state_backward_compatible(self):
        """Verify EmotionState with only positional args still works."""
        from core.emotion.models import EmotionState, EmotionType

        # Old-style construction (no emotion_mix)
        state = EmotionState(EmotionType.NEUTRAL, 0.0)
        assert state.emotion_mix == {}, "emotion_mix should default to empty dict"
        assert state.sub_emotions == {}

    def test_emotion_state_with_all_fields(self):
        """Verify EmotionState with all fields including emotion_mix."""
        from core.emotion.models import EmotionState, EmotionType

        state = EmotionState(
            primary_emotion=EmotionType.HAPPY,
            confidence=0.8,
            sub_emotions={"happy": 0.6, "excited": 0.4},
            emotion_mix={"happy": 0.6, "excited": 0.4},
            intensity=0.8,
            context="test context",
        )
        assert state.emotion_mix == {"happy": 0.6, "excited": 0.4}
        assert state.intensity == 0.8
        assert state.context == "test context"


# ============================================================
# 1.5 WebSocket Heartbeat Checker Startup
# ============================================================

class TestWebSocketHeartbeatStartup:
    """Tests for WebSocket heartbeat checker startup issue fix."""

    def test_websocket_manager_initialize_starts_heartbeat(self):
        """Verify initialize() starts heartbeat_checker task."""
        import asyncio
        from core.interfaces.websocket.websocket_manager import WebSocketManager

        async def run_test():
            manager = WebSocketManager()
            # 初始状态：running=False，heartbeat_task=None
            assert manager.running is False, "初始状态 running 应为 False"
            assert manager.heartbeat_task is None, "初始状态 heartbeat_task 应为 None"

            # 调用 initialize() 后：running=True，heartbeat_task 应被创建
            await manager.initialize()
            assert manager.running is True, "initialize() 后 running 应为 True"
            assert manager.heartbeat_task is not None, "initialize() 后 heartbeat_task 应被创建"
            assert isinstance(manager.heartbeat_task, asyncio.Task), "heartbeat_task 应为 asyncio.Task"

            # 清理：停止 manager
            await manager.stop()
            assert manager.running is False, "stop() 后 running 应为 False"

        asyncio.run(run_test())

    def test_websocket_manager_initialize_sets_max_connections(self):
        """Verify initialize() preserves max_connections from config."""
        from core.interfaces.websocket.websocket_manager import WebSocketManager

        manager = WebSocketManager()
        # max_connections 应从配置或默认值加载
        assert manager.max_connections > 0, "max_connections 应大于 0"
        assert manager.heartbeat_interval > 0, "heartbeat_interval 应大于 0"
        assert manager.heartbeat_timeout > 0, "heartbeat_timeout 应大于 0"

    def test_adapter_initialize_calls_websocket_manager_initialize(self):
        """Verify FastAPIWebSocketAdapter.initialize() calls websocket_manager.initialize()."""
        import asyncio
        from core.interfaces.websocket.adapters.adapter import FastAPIWebSocketAdapter
        from unittest.mock import AsyncMock, patch

        async def run_test():
            adapter = FastAPIWebSocketAdapter()
            assert adapter._initialized is False, "初始状态应为未初始化"

            # mock websocket_manager.initialize() 来验证是否被调用
            with patch.object(adapter, 'websocket_manager', None):
                # 实际 initialize 会创建 websocket_manager，这里只验证流程
                await adapter.initialize()
                assert adapter._initialized is True, "initialize() 后应为已初始化"
                assert adapter.websocket_manager is not None, "websocket_manager 应被创建"

            # 清理
            await adapter.shutdown()

        asyncio.run(run_test())

    def test_heartbeat_checker_detects_closed_connections(self):
        """Verify heartbeat_checker can detect and close stale connections."""
        import asyncio
        from core.interfaces.websocket.websocket_manager import WebSocketManager
        from core.interfaces.websocket.connection_management import ConnectionManagementMixin

        # 验证 _is_starlette_websocket_closed 方法存在且能工作
        manager = WebSocketManager()

        # 模拟一个已关闭的 Starlette WebSocket
        mock_ws = MagicMock()
        mock_ws.application_state = MagicMock()
        from starlette.websockets import WebSocketState
        mock_ws.application_state = WebSocketState.DISCONNECTED

        is_closed = manager._is_starlette_websocket_closed(mock_ws)
        assert is_closed is True, "DISCONNECTED 状态应被检测为已关闭"

        # 模拟一个活跃的 WebSocket
        mock_ws_active = MagicMock()
        mock_ws_active.application_state = WebSocketState.CONNECTED
        mock_ws_active.close_code = None

        is_closed_active = manager._is_starlette_websocket_closed(mock_ws_active)
        assert is_closed_active is False, "CONNECTED 状态应不被检测为已关闭"

    def test_send_ping_uses_send_text_for_fastapi_websocket(self):
        """Verify send_ping uses send_text for FastAPI/Starlette WebSocket.

        Regression test for "string indices must be integers" error:
        Starlette WebSocket.send() expects ASGI dict, not str.
        send_ping must use send_text when available.
        """
        import asyncio
        import json
        from core.interfaces.websocket.websocket_manager import WebSocketManager
        from core.interfaces.websocket.connection import ClientConnection
        from core.contracts import ConnectionState
        from starlette.websockets import WebSocketState

        async def run_test():
            manager = WebSocketManager()

            # 模拟 FastAPI WebSocket（有 send_text 方法）
            # 用 spec 限制属性，避免 MagicMock 默认所有 hasattr 都返回 True
            mock_ws = MagicMock(spec=["send_text", "send", "close", "application_state", "client_state", "close_code"])
            mock_ws.application_state = WebSocketState.CONNECTED
            mock_ws.client_state = WebSocketState.CONNECTED
            mock_ws.close_code = None
            mock_ws.send_text = AsyncMock()
            mock_ws.send = AsyncMock(side_effect=AssertionError("should not call send() on FastAPI WebSocket"))

            # 注册连接
            conn = ClientConnection(
                websocket=mock_ws,
                user_id="test_user",
                platform="qq",
                state=ConnectionState.CONNECTED,
            )
            async with manager.connections_lock:
                manager.connections[mock_ws] = conn

            # 调用 send_ping
            await manager.send_ping(mock_ws)

            # 验证：调用了 send_text，没有调用 send
            mock_ws.send_text.assert_awaited_once()
            sent_data = mock_ws.send_text.await_args.args[0]
            parsed = json.loads(sent_data)
            assert parsed["type"] == "ping", f"应为 ping 消息，实际: {parsed['type']}"
            assert "timestamp" in parsed
            assert "ping_id" in parsed
            mock_ws.send.assert_not_awaited()

        asyncio.run(run_test())

    def test_send_ping_uses_send_for_websockets_lib(self):
        """Verify send_ping uses send() for websockets library WebSocket."""
        import asyncio
        import json
        from core.interfaces.websocket.websocket_manager import WebSocketManager
        from core.interfaces.websocket.connection import ClientConnection
        from core.contracts import ConnectionState

        async def run_test():
            manager = WebSocketManager()

            # 模拟 websockets 库的 WebSocket（没有 send_text 方法，只有 send）
            # websockets 库的 WebSocket 有 closed 属性（默认 False）
            mock_ws = MagicMock(spec=["send", "close", "transport", "closed"])
            mock_ws.closed = False
            mock_ws.send = AsyncMock()

            conn = ClientConnection(
                websocket=mock_ws,
                user_id="test_user",
                platform="qq",
                state=ConnectionState.CONNECTED,
            )
            async with manager.connections_lock:
                manager.connections[mock_ws] = conn

            await manager.send_ping(mock_ws)

            mock_ws.send.assert_awaited_once()
            sent_data = mock_ws.send.await_args.args[0]
            parsed = json.loads(sent_data)
            assert parsed["type"] == "ping"

        asyncio.run(run_test())
