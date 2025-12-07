from fastapi import WebSocket, WebSocketDisconnect
from domain.services.chat_service import ChatService
import logging

logger = logging.getLogger("WebSocketHandler")

class WebSocketHandler:
    def __init__(self, chat_service: ChatService):
        self.chat_service = chat_service

    async def handle_connection(self, websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                data = await websocket.receive_json()
                user_input = data.get("text")
                
                if not user_input:
                    continue
                
                async for chunk in self.chat_service.process_message(user_input):
                    await websocket.send_json(chunk)
                    
        except WebSocketDisconnect:
            logger.info("Client disconnected")
        except Exception as e:
            logger.error(f"Error in websocket loop: {e}")
            await websocket.close()
