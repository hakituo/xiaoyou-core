import json
import time
import asyncio
import logging
from typing import Any, Dict, Optional
from collections import defaultdict

from core.server.connection_manager import ConnectionManager

# Import ChatAgent
try:
    from core.agents.chat_agent import get_default_chat_agent
    CHAT_AGENT_AVAILABLE = True
except ImportError:
    logging.warning("ChatAgent not found. Using fallback.")
    CHAT_AGENT_AVAILABLE = False

logger = logging.getLogger(__name__)

# --- Mock Implementations (Fallback) ---
class TRMAdapterMock:
    async def query_llm_async(self, user_id, prompt, history):
        await asyncio.sleep(1.5)
        return f"这是对'{prompt[:20]}...'的异步回复。"
    
    async def transcribe_audio_async(self, audio_data):
        await asyncio.sleep(1)
        return "这是模拟的语音转录结果。"

class TTSManagerMock:
    def synthesize_and_play(self, text: str):
        logging.info(f"🎤 [TTS模拟] 正在合成'{text[:30]}...'(阻塞方式，2秒)。")
        time.sleep(2)
        logging.info("🔊 [TTS模拟] 播放完成。")

class MemoryManagerMock:
    def __init__(self, user_id, max_length=50, auto_save_interval=300):
        self.user_id = user_id
        self.history = []
        self.max_length = max_length
        self.auto_save_interval = auto_save_interval
        self.last_save_time = time.time()
    
    def add_message(self, role, content):
        self.history.append({"role": role, "content": content})
        if len(self.history) > self.max_length:
            self.history = self.history[-self.max_length:]
    
    def get_history(self):
        return self.history
    
    def save_memory(self):
        logging.info(f"💾 [同步I/O] 已保存用户 {self.user_id} 的记忆。")
        self.last_save_time = time.time()
    
    def should_auto_save(self):
        return time.time() - self.last_save_time > self.auto_save_interval

class WebSocketHandler:
    def __init__(self, connection_manager: ConnectionManager):
        self.connection_manager = connection_manager
        
        # Initialize User Memory Map
        try:
            from memory.memory_manager import MemoryManager
            self.MemoryManagerClass = MemoryManager
        except ImportError:
            logging.warning("MemoryManager not found. Using mock.")
            self.MemoryManagerClass = MemoryManagerMock
            
        self.user_memory_map = defaultdict(
            lambda: self.MemoryManagerClass(user_id="default", max_length=50, auto_save_interval=300)
        )
        
        # Initialize Adapters
        self.trm_adapter = self._get_trm_adapter()
        self.tts_manager = self._get_tts_manager()
        
        self.system_status = {
            "total_queries": 0
        }
        
        # Initialize ChatAgent
        if CHAT_AGENT_AVAILABLE:
            self.chat_agent = get_default_chat_agent()
        else:
            self.chat_agent = None

    def _get_trm_adapter(self):
        try:
            from core.trm_adapter import TRMAdapter
            return TRMAdapter()
        except ImportError:
            logging.warning("TRMAdapter not found. Using mock.")
            return TRMAdapterMock()

    def _get_tts_manager(self):
        try:
            from multimodal.tts_manager import get_tts_manager
            return get_tts_manager()
        except ImportError:
            try:
                from tts_manager import get_tts_manager
                return get_tts_manager()
            except ImportError:
                logging.warning("TTSManager not found. Using mock.")
                return TTSManagerMock()

    async def handle(self, websocket: Any):
        """Handle a new WebSocket connection."""
        if not await self.connection_manager.connect(websocket):
            await websocket.close(code=1008, reason="Server at max capacity")
            return

        user_id = f"user_{id(websocket)}"
        user_memory = self.user_memory_map[user_id]
        user_memory.user_id = user_id
        
        logger.info(f"🔗 New connection from {getattr(websocket, 'remote_address', 'unknown')}, ID: {user_id}")
        
        try:
            await websocket.send(json.dumps({
                "type": "system", 
                "content": f"Xiaoyou Core Connected. ID: {user_id}. Type 'mock 5s' to test I/O."
            }))

            async for message in websocket:
                self.connection_manager.update_heartbeat(websocket)
                await self._process_message(websocket, message, user_id, user_memory)

        except Exception as e:
            logger.error(f"Error handling connection {user_id}: {e}")
        finally:
            self.connection_manager.disconnect(websocket)
            self.user_memory_map.pop(user_id, None)
            logger.info(f"🧹 Cleaned up {user_id}")

    async def _process_message(self, websocket, message, user_id, user_memory):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return
            
        msg_type = data.get("type")
        
        if msg_type == "heartbeat":
            return
            
        elif msg_type == "text_input":
            await self._handle_text_input(websocket, data, user_id, user_memory)
            
        elif msg_type == "audio_input":
            await self._handle_audio_input(websocket, data, user_id)
            
        elif msg_type == "system_status":
            await self._send_system_status(websocket)

    async def _handle_text_input(self, websocket, data, user_id, user_memory):
        prompt = data.get("text", "").strip()
        if not prompt:
            return

        logger.info(f"💬 [Input] {user_id}: {prompt}")
        
        await websocket.send(json.dumps({
            "type": "system", "content": "Thinking...", "action": "thinking"
        }))
        
        response_text = ""
        
        if self.chat_agent:
            # Ensure ChatAgent is initialized
            await self.chat_agent.initialize()
            
            # Use ChatAgent for Aveline logic (Streaming)
            detected_emotion = None
            async for chunk in self.chat_agent.stream_chat(prompt, user_id=user_id):
                if chunk["type"] == "token":
                    response_text += chunk["data"]
                    # Optional: Send stream token if client supports it
                    # await websocket.send(json.dumps({"type": "stream_token", "content": chunk["data"]}))
                elif chunk["type"] in ["sensory_trigger", "behavior_chain", "ui_interaction"]:
                    # Capture emotion data if available
                    if chunk["type"] == "sensory_trigger":
                        if "visual_emotion_weights" in chunk.get("data", {}):
                             detected_emotion = chunk["data"]["visual_emotion_weights"]
                    
                    # Forward Aveline events
                    await websocket.send(json.dumps(chunk))
                    
            # Update local memory for fallback consistency (ChatAgent handles its own memory)
            user_memory.add_message("user", prompt)
            user_memory.add_message("ai", response_text)
            
        else:
            # Fallback to TRMAdapter (Legacy)
            user_memory.add_message("user", prompt)
            response_text = await self._query_llm(user_id, prompt, user_memory.get_history())
            user_memory.add_message("ai", response_text)
            detected_emotion = None
        
        self.system_status["total_queries"] += 1
        
        await websocket.send(json.dumps({
            "type": "message", "content": response_text, "timestamp": time.time()
        }))
        
        # TTS Task
        asyncio.create_task(self._synthesize_tts(user_id, response_text, emotion=detected_emotion))
        
        # Auto-save memory
        if hasattr(user_memory, 'should_auto_save') and user_memory.should_auto_save():
            asyncio.create_task(asyncio.to_thread(user_memory.save_memory))

    async def _handle_audio_input(self, websocket, data, user_id):
        audio_data = data.get("audio_data")
        if not audio_data:
            return
            
        transcription = await self._transcribe_audio(user_id, audio_data)
        await websocket.send(json.dumps({
            "type": "transcription", "content": transcription
        }))

    async def _send_system_status(self, websocket):
        await websocket.send(json.dumps({
            "type": "system_status",
            "data": {
                "active_users": self.connection_manager.get_active_count(),
                "total_queries": self.system_status["total_queries"]
            }
        }))

    async def _query_llm(self, user_id, prompt, history):
        try:
            if "mock 5s" in prompt.lower():
                await asyncio.sleep(5)
                return "Mock 5s delay completed."
            return await self.trm_adapter.query_llm_async(user_id, prompt, history)
        except Exception as e:
            logger.error(f"LLM Error: {e}")
            return f"System Error: {e}"

    async def _transcribe_audio(self, user_id, audio_data):
        try:
            return await self.trm_adapter.transcribe_audio_async(audio_data)
        except Exception as e:
            logger.error(f"STT Error: {e}")
            return f"STT Error: {e}"

    async def _synthesize_tts(self, user_id, text, emotion=None):
        try:
            # Extract emotion if passed as dictionary or complex object
            emotion_val = None
            if isinstance(emotion, dict):
                # Find dominant emotion
                if emotion:
                    emotion_val = max(emotion, key=emotion.get)
            elif isinstance(emotion, str):
                emotion_val = emotion
                
            await asyncio.to_thread(self.tts_manager.synthesize_and_play, text, speed=1.0, emotion=emotion_val)
        except Exception as e:
            logger.error(f"TTS Error: {e}")
