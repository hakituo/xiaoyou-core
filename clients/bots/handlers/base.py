class BaseHandler:
    def __init__(self, adapter):
        self.adapter = adapter
        self.logger = adapter.logger if hasattr(adapter, "logger") else None

    async def api_request(self, method, path, json_body=None, params=None):
        """Delegate to adapter's API request method"""
        return await self.adapter._api_request(method, path, json_body, params)

    async def send_text(self, session_id, content):
        """Delegate to adapter's send method"""
        await self.adapter.send_to_napcat(session_id, content)

    async def send_friendly_error(self, session_id, context, error):
        """Delegate to adapter's friendly error method"""
        if hasattr(self.adapter, "_send_friendly_error"):
            await self.adapter._send_friendly_error(session_id, context, error)
        else:
            await self.send_text(session_id, f"{context}失败: {error}")
