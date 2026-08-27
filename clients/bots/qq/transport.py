"""
QQ适配器 - 传输层
管理 NapCat WebSocket 连接、消息发送、RPC 调用
"""

import asyncio
import json
import logging
import random
import time
from typing import Optional

from clients.bots.qq.utils import strip_all_reaction_delay_tags
from clients.bots.qq.utils import (
    _append_query_param,
    _contains_raw_base64,
    _is_base64_cq_code,
    _split_plain_text,
    _strip_base64_from_text,
    _ws_connect,
    _strip_markdown_for_qq,
    _strip_think_for_qq,
    _strip_trailing_periods_for_qq,
    strip_ai_timestamp,
)
from core.utils.async_locks import LazyAsyncLock

logger = logging.getLogger(__name__)


class NapcatTransport:
    """NapCat WebSocket 传输层"""

    def __init__(self, config):
        self.cfg = config
        self.napcat_ws = None
        self.running = True

        self._napcat_send_lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._napcat_call_lock = LazyAsyncLock()
        self._napcat_echo_seq = 0
        self._napcat_pending_calls: dict[str, asyncio.Future] = {}
        self._napcat_connecting_logged = False
        self._napcat_error_logged = False

    async def connect(self, message_handler):
        """连接到 NapCat WebSocket

        Args:
            message_handler: 消息处理回调，接收 (message: str)
        """
        while self.running:
            try:
                napcat_url = _append_query_param(
                    self.cfg.napcat_ws_url,
                    "access_token",
                    self.cfg.napcat_access_token,
                )
                headers = None
                if self.cfg.napcat_access_token:
                    headers = {"Authorization": f"Bearer {self.cfg.napcat_access_token}"}
                if not self._napcat_connecting_logged:
                    logger.info(f"Connecting to NapCatQQ at {napcat_url}...")
                    self._napcat_connecting_logged = True
                async with (await _ws_connect(napcat_url, headers=headers)) as ws:
                    self.napcat_ws = ws
                    self._napcat_connecting_logged = False
                    self._napcat_error_logged = False
                    logger.info("Connected to NapCatQQ.")

                    async for message in ws:
                        await message_handler(message)
            except Exception as e:
                if not self._napcat_error_logged:
                    logger.error(f"NapCatQQ connection error: {e}")
                    self._napcat_error_logged = True
                for fut in list(self._napcat_pending_calls.values()):
                    if fut and not fut.done():
                        fut.set_exception(ConnectionError("NapCat disconnected"))
                self._napcat_pending_calls.clear()
                self.napcat_ws = None
                await asyncio.sleep(5)

    async def handle_message(self, message: str) -> Optional[dict]:
        """处理接收到的消息，返回需要处理的 post 消息或 None"""
        try:
            data = json.loads(message)
            echo = data.get("echo")
            if echo and echo in self._napcat_pending_calls:
                fut = self._napcat_pending_calls.get(echo)
                if fut and not fut.done():
                    fut.set_result(data)
                return None
            post_type = data.get("post_type")
            if post_type == "message":
                return data
            return None
        except Exception as e:
            logger.error(f"NapCat msg error: {e}")
            return None

    async def send_message(
        self,
        session_id: str,
        content: str,
        *,
        master_qq_id: str = "",
        peer_qq_id: str = "",
        strip_markdown: bool = True,
        face_processor=None,
        wait_for_result: bool = False,
    ) -> bool:
        """发送消息到 NapCat

        Args:
            session_id: 会话ID
            content: 消息内容
            master_qq_id: 主人QQ号
            peer_qq_id: 对方QQ号
            strip_markdown: 是否去除Markdown
            face_processor: 表情处理器，接收 (content) 返回处理后的content
            wait_for_result: 是否等待 NapCat 返回实际发送结果。语音等需要保证
                后续消息顺序的媒体消息应启用此项。
        """
        if not self.napcat_ws:
            return False

        # 不再需要过滤剧本标记前缀（已改用元数据标识）

        content = _strip_think_for_qq(content)
        content = strip_ai_timestamp(content)
        content = strip_all_reaction_delay_tags(content)
        content = content.strip()

        if _is_base64_cq_code(content):
            logger.info(f"[{session_id}] 允许合法 base64 CQ 码发送: {content[:60]}...")
        elif _contains_raw_base64(content):
            logger.warning(f"[{session_id}] 拦截含裸 base64 的消息，尝试剥离: {content[:80]}...")
            content = _strip_base64_from_text(content)
            if not content or _contains_raw_base64(content):
                logger.error(f"[{session_id}] base64 剥离后消息为空或仍含 base64，丢弃该消息")
                return False
            logger.info(f"[{session_id}] base64 剥离后消息: {content[:80]}...")

        has_cq = "[CQ:" in content
        if strip_markdown and not has_cq:
            content = _strip_markdown_for_qq(content)
        if not has_cq:
            content = _strip_trailing_periods_for_qq(content)

        if not content:
            return False

        if face_processor:
            content = face_processor(content)

        target_type = "private"

        if session_id == "default_user":
            target_type = "private"
            if not master_qq_id:
                logger.error("Cannot send to default_user: master_qq_id is not set")
                return False
            payload = {
                "action": "send_private_msg",
                "params": {"user_id": int(master_qq_id), "message": content}
            }
        else:
            parts = session_id.split("_")
            if parts[0] == "group":
                target_type = "group"
                payload = {
                    "action": "send_group_msg",
                    "params": {"group_id": int(parts[1]), "message": content}
                }
            elif parts[0] in ("private", "peer"):
                target_type = "private"
                payload = {
                    "action": "send_private_msg",
                    "params": {"user_id": int(parts[1]), "message": content}
                }
            else:
                return False

        chunks = _split_plain_text(content, max_len=1200)
        if not chunks:
            return False

        if wait_for_result:
            for ch in chunks:
                params = dict(payload["params"])
                params["message"] = ch
                logger.info(f"Sending to NapCat ({target_type}, wait_result): {ch[:50]}...")
                retcode, result = await self.call_action(
                    payload["action"], params, timeout_seconds=30.0
                )
                result_status = (
                    str(result.get("status") or "").lower()
                    if isinstance(result, dict)
                    else ""
                )
                if (
                    retcode != 0
                    or not isinstance(result, dict)
                    or result.get("error")
                    or result_status not in ("", "ok")
                ):
                    logger.error(
                        f"[{session_id}] NapCat 消息发送未确认: "
                        f"retcode={retcode}, result={result}"
                    )
                    return False
            return True

        async with self._napcat_send_lock:
            for idx, ch in enumerate(chunks):
                payload2 = payload
                if idx > 0:
                    payload2 = json.loads(json.dumps(payload))
                payload2["params"]["message"] = ch
                logger.info(f"Sending to NapCat ({target_type}): {ch[:50]}...")
                await self.napcat_ws.send(json.dumps(payload2))
                if idx < len(chunks) - 1:
                    await asyncio.sleep(0.35)
        return True

    async def call_action(self, action: str, params: dict | None = None, timeout_seconds: float = 8.0):
        """调用 NapCat API action

        Returns:
            (retcode, data) 元组
        """
        if not self.napcat_ws:
            return 0, {"error": "napcat_disconnected"}
        if not action:
            return 0, {"error": "empty_action"}

        async with self._napcat_call_lock:
            self._napcat_echo_seq += 1
            echo = f"xy_{int(time.time() * 1000)}_{self._napcat_echo_seq}"
            fut = asyncio.get_running_loop().create_future()
            self._napcat_pending_calls[echo] = fut

            payload = {
                "action": str(action),
                "params": params or {},
                "echo": echo,
            }
            try:
                async with self._napcat_send_lock:
                    await self.napcat_ws.send(json.dumps(payload, ensure_ascii=False))
                data = await asyncio.wait_for(fut, timeout=max(0.5, float(timeout_seconds)))
                if not isinstance(data, dict):
                    return 0, {"error": "invalid_response", "raw": data}
                retcode = data.get("retcode")
                try:
                    code = int(retcode)
                except Exception:
                    code = 0 if str(data.get("status", "")).lower() == "ok" else -1
                return code, data
            except asyncio.TimeoutError:
                return 0, {"error": "timeout", "action": action}
            except Exception as e:
                return 0, {"error": str(e) or type(e).__name__, "action": action}
            finally:
                self._napcat_pending_calls.pop(echo, None)

    async def send_friendly_error(self, session_id: str, context_msg: str, error_detail=None) -> None:
        """发送友好的错误消息"""
        suffixes = ["", " 请稍后重试。", " 我马上再试一次。", " 正在恢复连接中。"]

        friendly_msgs = [
            f"哎呀，{context_msg}好像出了点小问题...",
            f"呜呜，{context_msg}失败了，要不等会儿再试试？",
            f"脑袋有点晕，{context_msg}没成功...",
            f"抱歉哦，{context_msg}遇到点麻烦。",
            f"指挥官，{context_msg}遭遇了未知阻碍...",
        ]

        msg = f"{random.choice(friendly_msgs)}{random.choice(suffixes)}"
        err_str = str(error_detail or "").lower()
        if "timeout" in err_str:
            msg += " (连接超时啦)"
        elif "connect" in err_str and "refused" in err_str:
            msg += " (连不上大脑了)"
        elif error_detail:
            s_err = str(error_detail)
            if len(s_err) < 40 and "{" not in s_err:
                msg += f" ({s_err})"

        await self.send_message(session_id, msg)

    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self.napcat_ws is not None
