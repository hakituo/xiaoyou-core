import asyncio, websockets, json
from core.llm_connector import query_model
from memory.memory_manager import MemoryManager
from core.utils import tts_generate

memory = MemoryManager()

async def handle_wx_msg(user_id, text):
    response = await query_model(text, memory)
    tts_path = await tts_generate(response)
    memory.add_message("user", text)
    memory.add_message("assistant", response)
    async with websockets.connect("ws://localhost:6789") as ws:
        await ws.send(json.dumps({
            "platform": "wx",
            "user_id": user_id,
            "message": text,
            "response": response,
            "tts": tts_path
        }))
    return response, tts_path
