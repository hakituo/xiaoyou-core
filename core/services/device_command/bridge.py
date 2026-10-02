"""设备指令桥

为后端工具提供"下发指令到手机前端 → 等待结果回传"的 RPC 能力。

链路:
1. 后端工具 _run() 调用 bridge.execute(command, args, user_id, timeout)
2. bridge 生成 request_id, 存入 pending_requests[request_id] = Future
3. bridge 通过 WebSocket 下发 device_command 到 user_id 的手机端连接
4. 手机端执行完后回传 device_command_result
5. adapter 收到后调 bridge.resolve_result(message), 按 request_id resolve Future
6. 工具 _run() 拿到结果返回字符串给 LLM

设计要点:
- 按 platform 过滤: 只发给 is_mobile 的连接 (android/ios)
- 前端不在线快速失败: 不走离线队列 (工具调用不能延迟到重连后)
- 超时兜底: 默认 30s, 蓝牙扫描等长操作可传 60s
- request_id → Future 配对, asyncio.Lock 防并发竞态
"""

import asyncio
import uuid
from typing import Any, Dict, Optional

from core.contracts import ConnectionState
from core.utils.logger import get_logger

logger = get_logger("device_command_bridge")


class DeviceCommandBridge:
    """设备指令桥: 后端工具 → WebSocket 下发 → 手机端执行 → 结果回传"""

    def __init__(self) -> None:
        # request_id → Future, 跟踪等待中的指令
        self._pending: Dict[str, asyncio.Future] = {}
        # 保护 _pending 的并发访问
        self._lock = asyncio.Lock()

    async def execute(
        self,
        command: str,
        args: Dict[str, Any],
        user_id: str,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """下发指令到 user_id 的手机端连接, 等待结果回传

        Args:
            command: 指令名 (如 "force_stop_app")
            args: 指令参数 (如 {"package_name": "com.xxx"})
            user_id: 目标用户 ID
            timeout: 超时秒数, 默认 30s

        Returns:
            {"status": "success", "result": {...}} 或
            {"status": "error", "error": "..."}
        """
        if not user_id:
            return {"status": "error", "error": "缺少 user_id"}

        request_id = str(uuid.uuid4())
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()

        async with self._lock:
            self._pending[request_id] = future

        # 查找该 user_id 的手机端连接
        target_ws = self._find_mobile_websocket(user_id)
        if target_ws is None:
            async with self._lock:
                self._pending.pop(request_id, None)
            logger.info(
                "设备指令 %s 下发失败: 用户 %s 无在线手机端连接",
                command,
                user_id,
            )
            return {
                "status": "error",
                "error": "手机端未连接, 请确保 App 在线并已连接后端",
            }

        # 下发指令
        payload = {
            "type": "device_command",
            "command": command,
            "args": args,
            "request_id": request_id,
            "timeout": int(timeout),
        }

        from core.interfaces.websocket.websocket_manager import get_websocket_manager

        ws_manager = get_websocket_manager()
        sent = await ws_manager.send_to_client(target_ws, payload)
        if not sent:
            async with self._lock:
                self._pending.pop(request_id, None)
            logger.warning(
                "设备指令 %s 下发失败: WebSocket 发送失败, user_id=%s",
                command,
                user_id,
            )
            return {"status": "error", "error": "指令下发失败, 连接异常"}

        logger.info(
            "设备指令已下发: command=%s, request_id=%s, user_id=%s, timeout=%ss",
            command,
            request_id,
            user_id,
            timeout,
        )

        # 等待结果
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            logger.info(
                "设备指令完成: command=%s, request_id=%s, status=%s",
                command,
                request_id,
                result.get("status"),
            )
            return result
        except asyncio.TimeoutError:
            async with self._lock:
                self._pending.pop(request_id, None)
            logger.warning(
                "设备指令超时: command=%s, request_id=%s, timeout=%ss",
                command,
                request_id,
                timeout,
            )
            return {
                "status": "error",
                "error": f"手机端 {timeout:.0f}s 内未响应, 可能 App 在后台或网络异常",
            }

    async def resolve_result(self, message: Dict[str, Any]) -> None:
        """前端回传 device_command_result 时调用, resolve 对应 future

        Args:
            message: {"request_id": "...", "status": "success|error", "result": {...}, "error": "..."}
        """
        request_id = message.get("request_id")
        if not request_id:
            logger.warning("收到无 request_id 的 device_command_result: %s", message)
            return

        async with self._lock:
            future = self._pending.pop(request_id, None)

        if future is None:
            logger.warning(
                "收到未知的 device_command_result (已超时或不存在): request_id=%s",
                request_id,
            )
            return

        if future.done():
            logger.warning(
                "device_command_result 对应的 future 已完成: request_id=%s",
                request_id,
            )
            return

        status = str(message.get("status", "success")).strip().lower()
        error = message.get("error")
        result = message.get("result", {})

        if status == "error" or error:
            future.set_result(
                {"status": "error", "error": error or "手机端执行失败, 未返回具体错误"}
            )
        else:
            future.set_result({"status": "success", "result": result})

    def _find_mobile_websocket(self, user_id: str):
        """在 user_connections 里找 is_mobile 且已连接的 websocket

        优先返回最近活跃的连接 (多个手机端在线时取 message_count 最多的)
        """
        try:
            from core.interfaces.websocket.websocket_manager import get_websocket_manager

            ws_manager = get_websocket_manager()
        except Exception as e:
            logger.error("获取 WebSocketManager 失败: %s", e)
            return None

        try:
            # 直接读 user_connections, 不加锁 (读快照, 偶发不一致可接受)
            conns = ws_manager.user_connections.get(user_id, [])
            mobile_conns = [
                conn
                for conn in conns
                if conn.is_mobile and conn.state == ConnectionState.CONNECTED
            ]
            if not mobile_conns:
                return None
            # 取最近活跃的 (last_activity 最大)
            mobile_conns.sort(key=lambda c: c.last_activity, reverse=True)
            return mobile_conns[0].websocket
        except Exception as e:
            logger.error("查找手机端连接失败: %s", e, exc_info=True)
            return None

    async def cleanup(self) -> None:
        """清理所有 pending (用于关闭时)"""
        async with self._lock:
            for request_id, future in self._pending.items():
                if not future.done():
                    future.set_result(
                        {"status": "error", "error": "服务关闭, 指令已取消"}
                    )
            self._pending.clear()


_bridge: Optional[DeviceCommandBridge] = None


def get_device_command_bridge() -> DeviceCommandBridge:
    """获取 DeviceCommandBridge 单例"""
    global _bridge
    if _bridge is None:
        _bridge = DeviceCommandBridge()
    return _bridge
