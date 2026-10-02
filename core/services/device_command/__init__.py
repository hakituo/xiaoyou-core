"""设备指令桥

为后端工具提供"下发指令到手机前端 → 等待结果回传"的 RPC 能力。
后端 LLM 工具调用 DeviceCommandBridge.execute() 后,
通过 WebSocket 下发 device_command 消息到该 user_id 的手机端连接,
手机端执行完后回传 device_command_result,bridge 按 request_id resolve Future。
"""

from .bridge import DeviceCommandBridge, get_device_command_bridge

__all__ = ["DeviceCommandBridge", "get_device_command_bridge"]
