# QQ Bot Module (currently not used)
# import asyncio, websockets, json
# from core.llm_connector import query_model
# from memory.memory_manager import MemoryManager
# from core.utils import tts_generate

# memory = MemoryManager()

async def handle_qq_msg(user_id, text):
    """Function to handle QQ messages, currently not used"""
    # response = await query_model(text, memory)
    # tts_path = await tts_generate(response)
    # memory.add_message("user", text)
    # memory.add_message("assistant", response)
    # # Push to WebSocket
    # async with websockets.connect("ws://localhost:6789") as ws:
    #     await ws.send(json.dumps({
    #         "platform": "qq",
    #         "user_id": user_id,
    #         "message": text,
    #         "response": response,
    #         "tts": tts_path
    #     }))
    # return response, tts_path
    return "QQ Bot feature is currently disabled", None