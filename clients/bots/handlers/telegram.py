from clients.bots.handlers.base import BaseHandler


class TelegramHandler(BaseHandler):
    """Telegram 平台专用处理器"""

    def __init__(self, adapter):
        super().__init__(adapter)
        self.adapter = adapter

    async def send_text(self, chat_id, content):
        """发送文本消息到 Telegram"""
        await self.adapter.send_text(chat_id, content)

    async def send_photo(self, chat_id, photo_url, caption=None):
        """发送图片到 Telegram"""
        await self.adapter.send_photo(chat_id, photo_url, caption)

    async def send_voice(self, chat_id, voice_file_path):
        """发送语音消息到 Telegram"""
        await self.adapter.send_voice(chat_id, voice_file_path)

    async def send_error(self, chat_id, context, error):
        """发送错误消息"""
        error_msg = f"❌ {context}失败：{str(error)}"
        await self.send_text(chat_id, error_msg)

    def parse_message(self, message_data):
        """解析 Telegram 消息数据"""
        # Telegram 消息解析逻辑
        return {
            "chat_id": message_data.get("chat_id"),
            "message_id": message_data.get("message_id"),
            "from_user": message_data.get("from"),
            "text": message_data.get("text"),
        }
