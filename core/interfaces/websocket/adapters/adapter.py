#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI WebSocket 适配器 - 主类
重构后的精简版适配器
"""

from core.utils.logger import get_logger
import asyncio

import os
import time
import hmac
from typing import Optional, Dict, Any
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from .handlers.main_handlers import MessageHandlers
from .streaming import StreamingHandler
from core.utils.async_locks import LazyAsyncLock

logger = get_logger(__name__)

# 全局实例
_instance = None
_instance_lock = asyncio.Lock()


class FastAPIWebSocketAdapter:
    """
    FastAPI WebSocket 适配器
    将 FastAPI 的 WebSocket 接口转换为与现有 WebSocketManager 兼容的格式
    """

    def __init__(self):
        # 延迟导入以避免循环依赖
        self.websocket_manager = None
        self._initialized = False
        self._chat_tasks: Dict[int, Dict[str, asyncio.Task]] = {}
        self._chat_tasks_lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._image_generation_tasks: Dict[str, asyncio.Task] = {}
        self._last_broadcast_hash: Optional[int] = None  # 用于检测数据变更
        self._last_broadcast_time: float = 0  # 上次广播时间
        self._min_broadcast_interval: float = 3.0  # 最小广播间隔（秒）
        self._last_logged_connection_count: int = -1  # 上次记录日志的连接数
        self._last_logged_models_state: Optional[Dict] = None  # 上次记录日志的模型状态

        # 初始化处理器
        self.handlers = MessageHandlers(self)
        self.streaming = StreamingHandler(self)
        self.demo = None  # 延迟初始化

    def _get_ws_key(self, websocket) -> int:
        """获取 WebSocket 的唯一键"""
        return id(websocket)

    async def _register_chat_task(self, websocket, message_id: str, task: asyncio.Task):
        """注册聊天任务"""
        ws_key = self._get_ws_key(websocket)
        async with self._chat_tasks_lock:
            bucket = self._chat_tasks.get(ws_key)
            if bucket is None:
                bucket = {}
                self._chat_tasks[ws_key] = bucket
            bucket[str(message_id)] = task

    async def _unregister_chat_task(self, websocket, message_id: str):
        """注销聊天任务"""
        ws_key = self._get_ws_key(websocket)
        async with self._chat_tasks_lock:
            bucket = self._chat_tasks.get(ws_key)
            if not bucket:
                return
            bucket.pop(str(message_id), None)
            if not bucket:
                self._chat_tasks.pop(ws_key, None)

    async def _cancel_chat_tasks(self, websocket):
        """取消所有聊天任务"""
        ws_key = self._get_ws_key(websocket)
        async with self._chat_tasks_lock:
            bucket = self._chat_tasks.pop(ws_key, {})

        tasks = [
            t for t in bucket.values() if isinstance(t, asyncio.Task) and not t.done()
        ]
        if tasks:
            for task in tasks:
                task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), timeout=3.0
                )
            except Exception:
                logger.debug("取消聊天任务时部分任务超时", exc_info=True)

        # 请求停止当前推理
        await self._request_stop_current_inference()

    async def _request_stop_current_inference(self):
        """请求停止当前推理"""
        try:
            from core.services.scheduler.cpp_scheduler_engine import (
                get_scheduler_engine,
            )

            engine = get_scheduler_engine()
            if engine:
                await engine.request_stop_current_inference()
        except Exception:
            logger.debug("请求停止当前推理失败", exc_info=True)

        try:
            from core.resource_manager import (
                get_global_resource_manager,
                is_system_under_memory_pressure,
            )

            if await is_system_under_memory_pressure():
                rm = await get_global_resource_manager()
                from core.utils.async_tasks import spawn_bg_task
                spawn_bg_task(rm.optimize_resources(), name="resource_optimize")
        except Exception:
            logger.debug("内存压力检测或资源优化失败", exc_info=True)

    async def initialize(self):
        """初始化适配器"""
        if self._initialized:
            return

        try:
            from core.interfaces.websocket.websocket_manager import (
                get_websocket_manager,
            )

            self.websocket_manager = get_websocket_manager()
            # 启动 WebSocket 管理器（心跳检查器、僵尸连接清理）
            await self.websocket_manager.initialize()

            # 订阅资源更新事件并广播
            from core.core_engine.event_bus import get_event_bus

            await get_event_bus().subscribe(
                "resource.metrics_updated", self._handle_resource_update
            )

            # 初始化演示处理器
            from .demo import DemoHandler

            self.demo = DemoHandler(self)

            self._initialized = True
            logger.info("FastAPIWebSocketAdapter initialized successfully")
            try:
                from core.utils.ws_handshake_debug import log as ws_log
                ws_log("adapter_initialized_ok")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Failed to initialize FastAPIWebSocketAdapter: {e}")
            try:
                from core.utils.ws_handshake_debug import log_exception as ws_log_exc
                ws_log_exc("adapter_initialize_failed", exc=e)
            except Exception:
                pass
            raise

    async def shutdown(self):
        """关闭适配器"""
        logger.info("Shutting down FastAPIWebSocketAdapter...")

        # 停止 WebSocket 管理器（心跳检查器等）
        if self.websocket_manager:
            try:
                await self.websocket_manager.stop()
            except Exception as e:
                logger.debug(f"停止 WebSocketManager 时出错: {e}")

        # 取消所有任务
        async with self._chat_tasks_lock:
            all_tasks = []
            for bucket in self._chat_tasks.values():
                all_tasks.extend(
                    [
                        t
                        for t in bucket.values()
                        if isinstance(t, asyncio.Task) and not t.done()
                    ]
                )
            self._chat_tasks.clear()

        if all_tasks:
            for task in all_tasks:
                task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(*all_tasks, return_exceptions=True), timeout=5.0
                )
            except Exception:
                logger.debug("关闭适配器时部分任务取消超时", exc_info=True)

        self._initialized = False
        logger.info("FastAPIWebSocketAdapter shutdown complete")

    async def handle_connection(self, websocket: WebSocket):
        """
        处理 WebSocket 连接

        Args:
            websocket: FastAPI WebSocket 对象
        """
        try:
            if not self._initialized:
                await self.initialize()
        except Exception as e:
            # 初始化失败（依赖未就绪/资源不可用）时，主动以 1013 关闭握手，
            # 而不是让异常冒泡到全局异常处理器被包装成 500，
            # 否则客户端会报 "Expected HTTP 101 response but was '500 Internal Server Error'"。
            logger.error(
                f"WebSocket 适配器初始化失败，拒绝握手: {e}", exc_info=True
            )
            try:
                await websocket.close(code=1013, reason="服务暂不可用，请稍后重试")
            except Exception:
                pass
            return

        # 判断是否为内部适配器（本地连接），内部适配器不需要 web_access_token
        client_host = ""
        if hasattr(websocket, "client") and websocket.client:
            client_host = str(getattr(websocket.client, "host", ""))
        is_local = client_host in ("127.0.0.1", "::1", "localhost")

        required_token = ""
        try:
            from config.integrated_config import get_settings

            required_token = str(get_settings().security.web_access_token or "").strip()
        except Exception:
            required_token = ""

        if is_local:
            # 内部适配器（如 QQ adapter）从本地连接，跳过 web_access_token 校验
            pass
        elif not required_token:
            await websocket.close(
                code=1008,
                reason="服务未配置访问令牌，请设置 XIAOYOU_SECURITY_WEB_ACCESS_TOKEN",
            )
            return

        query_params = getattr(websocket, "query_params", None)
        ws_token = (
            str(query_params.get("token")).strip()
            if query_params and query_params.get("token") is not None
            else ""
        )
        if not ws_token:
            authorization = str(websocket.headers.get("authorization", "")).strip()
            if authorization.lower().startswith("bearer "):
                ws_token = authorization[7:].strip()
        if not ws_token:
            ws_token = str(websocket.headers.get("x-internal-token", "")).strip()

        # 非本地连接需要校验 token
        if not is_local:
            token_ok = bool(ws_token) and hmac.compare_digest(ws_token, required_token)
            try:
                from core.utils.ws_handshake_debug import log as ws_log
                ws_log(
                    "token_check",
                    client_host=client_host,
                    is_local=is_local,
                    ws_token_present=bool(ws_token),
                    required_token_present=bool(required_token),
                    token_ok=token_ok,
                    user_id=(
                        str(query_params.get("user_id"))
                        if query_params and query_params.get("user_id") is not None
                        else None
                    ),
                )
            except Exception:
                pass
            if not token_ok:
                await websocket.close(code=1008, reason="未授权的 WebSocket 访问")
                return

        # 显式接受连接
        await websocket.accept()

        user_id = (
            str(query_params.get("user_id")).strip()
            if query_params and query_params.get("user_id") is not None
            else str(getattr(websocket, "user_id", "unknown")).strip()
        ) or "unknown"
        platform = (
            str(query_params.get("platform")).strip().lower()
            if query_params and query_params.get("platform") is not None
            else str(getattr(websocket, "platform", "unknown")).strip().lower()
        ) or "unknown"
        client_id = (
            str(query_params.get("client_id")).strip()
            if query_params and query_params.get("client_id") is not None
            else str(getattr(websocket, "client_id", "")).strip()
        )

        setattr(websocket, "user_id", user_id)
        setattr(websocket, "platform", platform)
        if client_id:
            setattr(websocket, "client_id", client_id)

        logger.info(
            f"New WebSocket connection from user: {user_id}, platform: {platform}, client_id: {client_id or 'n/a'}"
        )

        # 注册到管理器
        if self.websocket_manager:
            await self.websocket_manager.add_connection(
                websocket, user_id=user_id, platform=platform
            )

        try:
            while True:
                try:
                    message = await websocket.receive_json()
                except WebSocketDisconnect as disconnect_error:
                    if disconnect_error.code in (1000, 1001):
                        logger.info(
                            f"WebSocket connection closed for user {user_id}: ({disconnect_error.code}, '{disconnect_error.reason or ''}')"
                        )
                    else:
                        logger.warning(
                            f"WebSocket disconnected for user {user_id}: ({disconnect_error.code}, '{disconnect_error.reason or ''}')"
                        )
                    break
                except RuntimeError as runtime_error:
                    # 处理 WebSocket is not connected 错误
                    err_msg = str(runtime_error)
                    if "not connected" in err_msg or "accept" in err_msg:
                        logger.info(
                            f"WebSocket connection lost before receive for user {user_id}: {err_msg}"
                        )
                        break
                    logger.error(
                        f"Runtime error receiving message for user {user_id}: {runtime_error}",
                        exc_info=True,
                    )
                    raise
                except Exception as recv_error:
                    logger.error(
                        f"Error receiving message: {recv_error}", exc_info=True
                    )
                    raise

                # 处理消息
                # P1 修复：把消息处理丢到事件循环后台执行，而不是在这里 await。
                # 原因：Starlette 的 WebSocket 通过单一 receive() 循环处理数据帧与协议层
                # 控制帧（ping/pong）。原实现 `await self._process_message(...)` 会让接收循环
                # 被一次耗时的消息处理（聊天生成、工具调用、图片生成等）长时间阻塞，
                # 期间无法回到 receive() 接收并自动回应 OkHttp 协议层 ping，
                # 导致客户端侧 "sent ping but didn't receive pong within 15000ms" 超时断连。
                # 改为 fire-and-forget 后，receive_json() 立即回到循环，协议层 ping 始终能被
                # 及时回应；消息处理在后台协程中并发进行。
                # 注意：create_task 的异常需自行兜底，否则会触发 Task 未处理异常告警。
                asyncio.create_task(self._safe_process_message(websocket, message))

        except Exception as e:
            # 忽略正常的断开连接错误
            if "disconnect" not in str(e).lower() and "closed" not in str(e).lower():
                logger.error(
                    f"WebSocket connection error for user {user_id}: {e}", exc_info=True
                )
            else:
                logger.info(f"WebSocket connection closed for user {user_id}: {e}")
        finally:
            # 清理
            await self.handlers.cleanup_websocket(websocket)
            await self._cancel_chat_tasks(websocket)
            if self.websocket_manager:
                await self.websocket_manager.remove_connection(websocket)
            logger.info(f"WebSocket connection cleaned up for user: {user_id}")

    async def _safe_process_message(self, websocket: WebSocket, message: dict):
        """后台执行消息处理，兜底未处理异常，避免 asyncio.Task 告警。

        由接收循环以 fire-and-forget 方式调用，确保阻塞式 receive_json() 循环
        不被耗时消息处理占用（从而能持续接收并自动回应协议层 ping/pong）。
        """
        try:
            await self._process_message(websocket, message)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if "disconnect" in str(e).lower() or "closed" in str(e).lower():
                logger.debug(
                    f"后台消息处理时连接已关闭 (user: {getattr(websocket, 'user_id', '?')}): {e}"
                )
            else:
                logger.error(
                    f"后台消息处理异常 (user: {getattr(websocket, 'user_id', '?')}): {e}",
                    exc_info=True,
                )

    async def _process_message(self, websocket: WebSocket, message: dict):
        """
        处理 WebSocket 消息

        Args:
            websocket: WebSocket 连接
            message: 消息字典
        """
        try:
            if not isinstance(message, dict):
                logger.warning(f"接收到非字典消息：{message}")
                return

            msg_type = message.get("type")
            logger.debug(f"收到消息类型：{msg_type}")

            # 收到任何客户端消息都视为连接活跃的证据，刷新心跳计时器。
            # 弱网环境下 ping/pong 可能丢失，但用户消息本身证明连接是通的，
            # 不应因为 60s 内没收到 ping/pong 就误判超时关连接（会误杀延迟回复任务）。
            if self.websocket_manager is not None:
                try:
                    async with self.websocket_manager.connections_lock:
                        conn = self.websocket_manager.connections.get(websocket)
                        if conn is not None:
                            now = time.time()
                            conn.last_activity = now
                            # 用户主动发消息也更新 last_heartbeat，避免 ReplyPolicy 延迟期间被心跳检查器误杀
                            if conn.last_heartbeat < now:
                                conn.last_heartbeat = now
                except Exception:
                    logger.debug("更新连接心跳计时器失败", exc_info=True)

            # 路由到对应的处理器
            if msg_type == "ping":
                await self.handlers.handle_ping(websocket, message)

            elif msg_type == "pong":
                await self.handlers.handle_pong(websocket, message)

            elif msg_type == "greeting":
                # 处理问候消息 - 使用流式输出
                await self.handlers.handle_greeting_message(
                    websocket, message, self.streaming
                )

            elif msg_type == "update_settings":
                await self.handlers.handle_update_settings(websocket, message)

            elif msg_type == "update_user_physiology":
                await self.handlers.handle_update_physiology(websocket, message)

            elif msg_type == "mobile_switch_model":
                await self.handlers.handle_mobile_switch_model(websocket, message)

            elif msg_type == "reconnect":
                await self.handlers.handle_reconnect(websocket, message)

            elif msg_type in ("text", "text_input"):
                # 标准化文本消息
                normalized = await self.handlers.handle_text_message(websocket, message)
                if normalized:
                    await self.handlers.handle_chat_message(
                        websocket, normalized, self.streaming
                    )

            elif msg_type in ("message", "chat"):
                await self.handlers.handle_chat_message(
                    websocket, message, self.streaming
                )

            elif msg_type in (
                "demo_voice_input",
                "demo_generate_image",
                "generate_image",
            ):
                await self._handle_demo_message(websocket, message)

            elif msg_type == "device_command_result":
                # 手机端回传设备指令执行结果, 交给 DeviceCommandBridge resolve 对应 future
                await self._handle_device_command_result(message)

            else:
                # 转发给 WebSocketManager 处理其他类型
                if self.websocket_manager:
                    await self.websocket_manager.handle_message(websocket, message)

        except Exception as e:
            # 连接已进入关闭流程（已发送 close 帧）时，对端消息触发的 send
            # 会抛出 "Cannot call send once a close message has been sent"，
            # 这属于正常的关闭竞态，降级为 debug 而非 error 噪声。
            err_text = str(e)
            if "close message has been sent" in err_text or "not connected" in err_text.lower():
                logger.debug(f"连接关闭竞态导致消息处理跳过：{err_text}")
            else:
                logger.error(f"处理消息时出错：{e}")
                import traceback

                logger.error(traceback.format_exc())

    async def _handle_device_command_result(self, message: dict):
        """处理手机端回传的设备指令执行结果

        消息格式: {"type":"device_command_result", "request_id":"...", "status":"success|error", "result":{...}, "error":"..."}
        交给 DeviceCommandBridge.resolve_result 按 request_id resolve 对应 future
        """
        try:
            from core.services.device_command import get_device_command_bridge

            bridge = get_device_command_bridge()
            await bridge.resolve_result(message)
        except Exception as e:
            logger.error(f"处理设备指令结果失败: {e}", exc_info=True)

    async def _handle_demo_message(self, websocket: WebSocket, message: dict):
        """处理演示消息（图片生成、语音输入等）"""
        msg_type = message.get("type")
        msg_id = message.get("message_id") or str(int(time.time() * 1000))
        conversation_id = (
            message.get("conversation_id")
            or getattr(websocket, "user_id", None)
            or "demo"
        )
        request_id = message.get("request_id") or msg_id
        text = str(message.get("content") or message.get("text") or "").strip()
        num_images = message.get("num_images")

        try:
            from core.services.life_simulation.service import (
                get_life_simulation_service,
            )

            get_life_simulation_service().update_interaction(xp_gain=0)
        except Exception:
            logger.debug("更新生活模拟交互状态失败", exc_info=True)

        if num_images is None:
            num_images = message.get("numImages")
        if num_images is None:
            num_images = message.get("num")

        try:
            num_images = int(num_images) if num_images is not None else 1
        except Exception:
            logger.debug("解析num_images参数失败，使用默认值1", exc_info=True)
            num_images = 1

        # 如果是语音输入，先发送一个 STT 开始事件
        if msg_type == "demo_voice_input":
            await self.demo.send_demo_event(
                websocket,
                "stt_started",
                {"status": "listening"},
                msg_id,
                conversation_id,
                request_id,
            )
            # 模拟 STT 转录时间
            await asyncio.sleep(0.5)

        await websocket.send_json(
            {
                "type": "demo_event",
                "event": "ack",
                "data": {"accepted": True, "mode": "image"},
                "timestamp": time.time(),
                "message_id": msg_id,
                "conversation_id": conversation_id,
                "request_id": request_id,
            }
        )

        if not text:
            await self.demo.send_demo_event(
                websocket,
                "pipeline_error",
                {"message": "请输入有效的生图意图"},
                msg_id,
                conversation_id,
                request_id,
            )
            return

        existing_task = self._image_generation_tasks.get(msg_id)
        if existing_task and not existing_task.done():
            await self.demo.send_demo_event(
                websocket,
                "pipeline_error",
                {"message": "当前生图任务仍在进行中"},
                msg_id,
                conversation_id,
                request_id,
            )
            return

        task = asyncio.create_task(
            self.demo.generate_image_pipeline(
                websocket=websocket,
                user_text=text,
                message_id=msg_id,
                conversation_id=conversation_id,
                request_id=request_id,
                num_images=num_images,
            )
        )
        self._image_generation_tasks[msg_id] = task

    async def _generate_image_and_send(
        self,
        websocket: WebSocket,
        raw_prompt: str,
        message_id: str,
        conversation_id: str,
    ):
        """生成图片并发送"""
        try:
            prompt = str(raw_prompt or "")
        except Exception:
            logger.debug("解析图片生成prompt失败", exc_info=True)
            return

        if "|" in prompt:
            prompt = prompt.split("|", 1)[0].strip()
        prompt = prompt.strip()

        if not prompt:
            return

        try:
            from core.utils.resource_lock import get_resource_lock

            gate_status = get_resource_lock().get_status()
            position = 1
            if bool(gate_status.get("enabled")):
                position = (
                    int(gate_status.get("active") or 0)
                    + int(gate_status.get("waiting") or 0)
                    + 1
                )

            if position > 1:
                try:
                    await websocket.send_json(
                        {
                            "type": "image_status",
                            "data": {
                                "status": "queued",
                                "prompt": prompt,
                                "position": position,
                            },
                            "timestamp": time.time(),
                            "message_id": message_id,
                            "conversation_id": conversation_id,
                        }
                    )
                except Exception:
                    logger.debug("发送图片排队状态失败", exc_info=True)

            try:
                await websocket.send_json(
                    {
                        "type": "image_status",
                        "data": {"status": "started", "prompt": prompt},
                        "timestamp": time.time(),
                        "message_id": message_id,
                        "conversation_id": conversation_id,
                    }
                )
            except Exception:
                logger.debug("发送图片开始状态失败", exc_info=True)

            from config.integrated_config import get_settings
            from core.image.image_manager import (
                get_image_manager,
                ImageGenerationConfig,
            )

            settings = get_settings()
            manager = await get_image_manager()

            config = ImageGenerationConfig(
                width=settings.model.image_gen_width,
                height=settings.model.image_gen_height,
                num_inference_steps=settings.model.image_gen_steps,
            )

            from core.utils.resource_lock import get_resource_lock

            async with get_resource_lock().acquire("IMG", reject_if_full=True):
                result = await manager.generate_image(
                    prompt=prompt,
                    model_id=settings.model.default_image_model,
                    config=config,
                    save_to_file=True,
                )

            if not result.get("prompt"):
                result["prompt"] = prompt
            payload = await self._prepare_image_payload(result)

            await websocket.send_json(
                {
                    "type": "image_result",
                    "data": payload,
                    "timestamp": time.time(),
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                }
            )

        except Exception as e:
            try:
                err_text = str(e)
                lowered = err_text.lower()
                if (
                    "out of memory" in lowered
                    or "cuda" in lowered
                    or "显存" in err_text
                ):
                    try:
                        from core.resource_manager import get_global_resource_manager

                        rm = await get_global_resource_manager()
                        from core.utils.async_tasks import spawn_bg_task
                        spawn_bg_task(rm.optimize_resources(), name="cuda_oom_optimize")
                    except Exception:
                        logger.debug("CUDA OOM后资源优化失败", exc_info=True)

                from core.api.error_response import map_exception_to_error_code

                err_code = map_exception_to_error_code(e)
                await websocket.send_json(
                    {
                        "type": "image_result",
                        "data": {
                            "success": False,
                            "prompt": prompt,
                            "error_code": err_code.value,
                            "message": "图像生成失败",
                            "error": "图像生成失败",
                            "details": {"error_type": type(e).__name__},
                        },
                        "timestamp": time.time(),
                        "message_id": message_id,
                        "conversation_id": conversation_id,
                    }
                )
            except Exception:
                logger.debug("发送图像生成错误响应失败", exc_info=True)

        finally:
            try:
                current = asyncio.current_task()
                existing_task = self._image_generation_tasks.get(message_id)
                if existing_task is current:
                    self._image_generation_tasks.pop(message_id, None)
            except Exception:
                logger.debug("清理图像生成任务失败", exc_info=True)

    async def _prepare_image_payload(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """准备图像发送的 payload，包括 URL 转换和 base64 预览"""
        from core.image.image_utils import get_image_url
        import base64
        from PIL import Image
        import io

        payload = {
            "success": bool(result.get("success")),
            "prompt": result.get("prompt"),
        }

        image_path = result.get("image_path")
        if image_path:
            payload["image_path"] = image_path
            payload["image_url"] = get_image_url(image_path)

            # 生成小的 base64 预览图 (thumbnail)
            try:

                def _gen_thumbnail():
                    if not os.path.exists(image_path):
                        return None
                    with Image.open(image_path) as img:
                        img.thumbnail((128, 128))
                        if img.mode in ("RGBA", "P"):
                            img = img.convert("RGB")
                        buffered = io.BytesIO()
                        img.save(buffered, format="JPEG", quality=60)
                        return base64.b64encode(buffered.getvalue()).decode("utf-8")

                thumb_b64 = await asyncio.to_thread(_gen_thumbnail)
                if thumb_b64:
                    payload["thumbnail_base64"] = f"data:image/jpeg;base64,{thumb_b64}"
            except Exception as e:
                logger.warning(f"Failed to generate thumbnail: {e}")

        # 如果有多个图片
        images = result.get("images")
        if isinstance(images, list):
            out_images = []
            for it in images:
                if not isinstance(it, dict):
                    continue
                p = it.get("image_path")
                if p:
                    out_images.append({"image_path": p, "url": get_image_url(p)})
            if out_images:
                payload["images"] = out_images
                if "image_url" not in payload and out_images[0].get("url"):
                    payload["image_url"] = out_images[0]["url"]

        return payload

    async def _handle_resource_update(self, **kwargs):
        """处理资源更新事件并推送到前端（仅在数据变更时广播）"""
        try:
            # 1. 检查是否有活跃连接，没有连接则不广播
            if not self.websocket_manager:
                return

            # 快速检查：如果没有活跃连接，直接返回（避免无效日志）
            stats = self.websocket_manager.get_stats()
            if stats.get("active_connections", 0) == 0:
                return

            from core.resource_manager import get_resource_manager

            rm = get_resource_manager()

            # 2. 构造模型状态字典
            models_data = {}
            for mid, model in rm.models.items():
                models_data[mid] = {
                    "device": getattr(model, "device", "GPU"),
                    "priority": model.priority.name,
                    "is_loaded": model.is_loaded,
                    "memory_usage": getattr(model, "vram_usage_mb", 0),
                }

            # Inject current LLM settings into models_data for client visibility
            try:
                from config.integrated_config import get_settings

                settings = get_settings()
                if settings and settings.model and settings.model.llm:
                    models_data["llm"] = {
                        "provider": settings.model.llm.provider,
                        "model": settings.model.llm.model,
                        "text_path": settings.model.text_path,
                    }
            except Exception:
                logger.debug("注入LLM设置到模型数据失败", exc_info=True)

            # 3. 构造系统整体状态字典
            gpu_info = rm.monitor.get_gpu_memory_usage()
            gpu_gate_status = None
            scheduler_status = None
            try:
                from core.utils.resource_lock import get_resource_lock

                gpu_gate_status = get_resource_lock().get_status()
            except Exception:
                logger.debug("获取GPU gate状态失败", exc_info=True)

            try:
                from core.services.scheduler.cpp_scheduler_engine import (
                    get_scheduler_engine,
                )

                scheduler_engine = get_scheduler_engine()
                if scheduler_engine:
                    scheduler_status = scheduler_engine.get_status()
            except Exception as e:
                logger.debug(f"获取调度器状态失败：{e}")

            # 对数值进行舍入，避免微小变化触发广播
            current_time = time.time()

            # 5. 时间间隔检查：限制广播频率
            if current_time - self._last_broadcast_time < self._min_broadcast_interval:
                return

            system_data = {
                "cpu_percent": round(rm.monitor.get_cpu_usage(), 1),  # 保留 1 位小数
                "cpu_model": rm.monitor.get_cpu_model(),
                "memory_percent": round(
                    rm.monitor.get_memory_usage(), 1
                ),  # 保留 1 位小数
                "gpu_memory_used": gpu_info[0] if gpu_info else 0,
                "gpu_memory_total": gpu_info[1] if gpu_info else 8192,
                "gpu_model": rm.monitor.get_gpu_model(),
                "gpu_gate": gpu_gate_status,
                "scheduler": scheduler_status,
            }

            status_msg = {
                "type": "system_status",
                "timestamp": current_time,
                "models": models_data,
                "system": system_data,
                "stats": kwargs,  # 保留原始统计信息供调试
            }

            # 6. 数据变更检测：计算哈希值，只有数据变化时才广播
            import hashlib
            import json

            # 排除 timestamp 字段，因为它每次都在变化
            hash_data = {
                "models": models_data,
                "system": system_data,
            }
            current_hash = hashlib.md5(
                json.dumps(hash_data, sort_keys=True, ensure_ascii=False).encode(
                    "utf-8"
                )
            ).hexdigest()

            # 如果数据没有变化，跳过广播（避免刷屏）
            if self._last_broadcast_hash == current_hash:
                return

            # 7. 状态变化检测：只在状态真正变化时才输出日志
            current_connection_count = stats.get("active_connections", 0)

            # 检查连接数是否变化
            if current_connection_count != self._last_logged_connection_count:
                logger.info(f"[WebSocket] 当前连接数：{current_connection_count}")
                self._last_logged_connection_count = current_connection_count

            # 检查模型状态是否变化（简化检测：只检测加载的模型数量）
            current_loaded_count = sum(
                1 for m in models_data.values() if m.get("is_loaded")
            )
            if self._last_logged_models_state != current_loaded_count:
                logger.info(f"[资源状态] 已加载模型数：{current_loaded_count}")
                self._last_logged_models_state = current_loaded_count

            self._last_broadcast_hash = current_hash
            self._last_broadcast_time = current_time

            await self.broadcast_message(status_msg)
        except Exception as e:
            logger.error(f"处理资源更新广播失败：{e}")

    async def broadcast_message(self, data: Dict[str, Any]):
        """广播消息给所有连接"""
        if not self._initialized:
            await self.initialize()
        if not self.websocket_manager:
            return
        try:
            await self.websocket_manager.broadcast(data)
        except Exception as e:
            logger.error(f"广播消息失败：{str(e)}", exc_info=True)


async def get_fastapi_websocket_adapter() -> Optional[FastAPIWebSocketAdapter]:
    """获取 FastAPI WebSocket 适配器实例（单例）"""
    global _instance

    if _instance is None:
        async with _instance_lock:
            if _instance is None:
                _instance = FastAPIWebSocketAdapter()
                await _instance.initialize()

    return _instance


async def initialize_websocket_adapter() -> Optional[FastAPIWebSocketAdapter]:
    adapter = await get_fastapi_websocket_adapter()
    return adapter


async def shutdown_websocket_adapter() -> None:
    global _instance
    if _instance is None:
        return
    try:
        await _instance.shutdown()
    finally:
        _instance = None
