"""
QQ官方机器人适配器
基于QQ开放平台API v2
通过WebSocket连接后端，复用后端所有逻辑
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiohttp

from clients.bots.qq_official.config import QQOfficialConfig
from clients.bots.qq_official.transport import QQOfficialTransport
from clients.bots.qq.utils import _strip_markdown_for_qq, _ws_connect, build_persona_conversation_id
from core.utils.async_locks import LazyAsyncLock

logger = logging.getLogger("QQOfficial")


class ChatHistoryManager:
    """聊天历史记录管理器"""
    
    def __init__(self, base_dir: str = "data/qq_official_history"):
        self.base_dir = Path(base_dir)
        
    def _get_session_dir(self, session_id: str, create: bool = False) -> Path:
        safe_id = session_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        session_dir = self.base_dir / safe_id
        if create:
            session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir
        
    def save_message(self, session_id: str, role: str, content: str, 
                     metadata: Optional[dict] = None):
        try:
            session_dir = self._get_session_dir(session_id, create=True)
            today = datetime.now().strftime("%Y-%m-%d")
            file_path = session_dir / f"{today}.jsonl"
            
            entry = {
                "timestamp": time.time(),
                "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "role": role,
                "content": content,
                "metadata": metadata or {},
            }
            
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"保存聊天记录失败: {e}")
            
    def get_recent_messages(self, session_id: str, limit: int = 50) -> list[dict]:
        try:
            session_dir = self._get_session_dir(session_id)
            if not session_dir.exists():
                return []
            messages = []
            
            date_files = sorted(session_dir.glob("*.jsonl"), reverse=True)
            for date_file in date_files:
                with open(date_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                messages.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
                if len(messages) >= limit:
                    break
                    
            return messages[-limit:]
        except Exception as e:
            logger.error(f"读取聊天记录失败: {e}")
            return []


class XiaoyouSession:
    """小悠后端WebSocket会话"""
    
    def __init__(self, session_id: str, adapter: "QQOfficialAdapter"):
        self.session_id = session_id
        self.adapter = adapter
        self.ws = None
        self.running = False
        self.queue = asyncio.Queue()
        self.task = None
        self._connection_state = "disconnected"
        self._response_future: Optional[asyncio.Future] = None
        self._stream_buffer = ""
        
    async def start(self):
        self.running = True
        self.task = asyncio.create_task(self._run_loop())
        
    async def stop(self):
        self.running = False
        if self.ws:
            await self.ws.close()
        if self.task:
            self.task.cancel()
            
    async def send_text(self, text: str, persona_filename: str = "") -> str:
        """发送文本并等待回复"""
        if not self.ws or self.ws.closed:
            raise ConnectionError("未连接到后端")
            
        # 构建带persona后缀的conversation_id
        conversation_id = self.session_id
        if persona_filename:
            conversation_id = build_persona_conversation_id(self.session_id, persona_filename)
            
        payload = {
            "type": "text_input",
            "text": text,
            "content": text,
            "client_id": f"qq_official_{self.session_id}",
            "user_id": self.session_id,
            "platform": "qq_official",
            "conversation_id": conversation_id,
            "api_key_env": self.adapter.cfg.deepseek_api_key_env,
            "model": self.adapter.cfg.default_model_name or "",
        }
        
        if persona_filename:
            payload["persona_filename"] = persona_filename
            
        # 创建Future等待回复
        self._response_future = asyncio.get_running_loop().create_future()
        self._stream_buffer = ""
        
        # 发送消息
        await self.ws.send(json.dumps(payload))
        
        # 等待回复（超时60秒）
        try:
            response = await asyncio.wait_for(self._response_future, timeout=60.0)
            return response
        except asyncio.TimeoutError:
            return "抱歉，回复超时了..."
        finally:
            self._response_future = None
            
    async def _run_loop(self):
        retry_count = 0
        while self.running:
            try:
                cfg = self.adapter.cfg
                ws_url = f"{cfg.xiaoyou_ws_url}?client_id=qq_official_{self.session_id}&user_id={self.session_id}&platform=qq_official"
                headers = None
                if cfg.xiaoyou_access_token:
                    headers = {"Authorization": f"Bearer {cfg.xiaoyou_access_token}"}
                    
                async with (await _ws_connect(ws_url, headers=headers)) as ws:
                    self.ws = ws
                    self._connection_state = "connected"
                    logger.info(f"[{self.session_id}] 已连接到小悠后端")
                    retry_count = 0
                    
                    await self._receive_loop(ws)
                    
            except Exception as e:
                self._connection_state = "disconnected"
                retry_count += 1
                logger.error(f"[{self.session_id}] 连接失败: {e}")
                
                if retry_count > 20:
                    logger.warning(f"[{self.session_id}] 重试次数过多，停止会话")
                    self.running = False
                    
            await asyncio.sleep(min(5 * retry_count, 60))
            
    async def _receive_loop(self, ws):
        """接收消息循环"""
        async for message in ws:
            try:
                data = json.loads(message)
                msg_type = data.get("type", "")
                msg_subtype = data.get("subtype", "")
                
                # 处理流式响应块
                if msg_type == "message" and msg_subtype == "response_chunk":
                    chunk = data.get("content", "")
                    if chunk:
                        self._stream_buffer += chunk
                        
                # 处理响应完成
                elif msg_type == "message" and msg_subtype == "response_done":
                    if self._response_future and not self._response_future.done():
                        self._response_future.set_result(self._stream_buffer)
                        self._stream_buffer = ""
                        
                # 兼容旧格式
                elif msg_type == "stream_chunk":
                    chunk = data.get("chunk", "")
                    if chunk:
                        self._stream_buffer += chunk
                        
                elif msg_type == "stream_end":
                    if self._response_future and not self._response_future.done():
                        self._response_future.set_result(self._stream_buffer)
                        self._stream_buffer = ""
                        
                elif msg_type == "text_response":
                    content = data.get("content", "")
                    if self._response_future and not self._response_future.done():
                        self._response_future.set_result(content)
                        
            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error(f"处理消息失败: {e}")


class ProactiveMessenger:
    """主动消息管理器"""
    
    def __init__(self, adapter: "QQOfficialAdapter"):
        self.adapter = adapter
        self._message_queue: asyncio.Queue = asyncio.Queue()
        
    async def start(self):
        asyncio.create_task(self._process_queue())
        
    async def _process_queue(self):
        while True:
            try:
                target_type, target_id, content, delay = await self._message_queue.get()
                if delay > 0:
                    await asyncio.sleep(delay)
                await self.adapter._send_message(target_type, target_id, content)
            except Exception as e:
                logger.error(f"处理主动消息失败: {e}")
            await asyncio.sleep(0.1)
            
    async def send_to_master(self, content: str, delay: float = 0):
        if not self.adapter.cfg.master_qq_id:
            logger.warning("未配置主人QQ号")
            return
        await self._message_queue.put(("c2c", self.adapter.cfg.master_qq_id, content, delay))
        
    async def send_to_user(self, user_id: str, content: str, delay: float = 0):
        await self._message_queue.put(("c2c", user_id, content, delay))


class QQOfficialAdapter:
    """QQ官方机器人适配器"""
    
    _instances: dict[str, "QQOfficialAdapter"] = {}
    
    def __init__(self, config: Optional[QQOfficialConfig] = None, role_id: str = ""):
        self.cfg = config or QQOfficialConfig.from_env(role_id)
        
        instance_key = str(self.cfg.role_id or self.cfg.app_id or id(self)).strip()
        if instance_key:
            QQOfficialAdapter._instances[instance_key] = self
            
        self._log_prefix = ""
        if self.cfg.role_name:
            self._log_prefix = f"[{self.cfg.role_name}] "
        elif self.cfg.role_id:
            self._log_prefix = f"[{self.cfg.role_id}] "
            
        self.sessions: dict[str, XiaoyouSession] = {}
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._http_session_lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        
        self.transport = QQOfficialTransport(self.cfg)
        self.chat_history = ChatHistoryManager(
            base_dir=f"data/qq_official_history/{self.cfg.role_id or 'default'}"
        )
        self.proactive_messenger = ProactiveMessenger(self)
        
    def _log(self, level: str, msg: str):
        log_msg = f"{self._log_prefix}{msg}"
        getattr(logger, level)(log_msg)
        
    def _is_master(self, user_id: str) -> bool:
        return str(user_id) == str(self.cfg.master_qq_id)
        
    async def _get_or_create_session(self, session_id: str) -> XiaoyouSession:
        """获取或创建后端会话"""
        if session_id not in self.sessions:
            session = XiaoyouSession(session_id, self)
            self.sessions[session_id] = session
            await session.start()
            # 等待连接建立
            await asyncio.sleep(1)
        return self.sessions[session_id]
        
    async def _handle_message(self, data: dict):
        """处理接收到的消息"""
        msg_type = data.get("type")
        author_id = str(data.get("author_id", ""))
        content = str(data.get("content", "")).strip()
        msg_id = str(data.get("message_id", ""))
        
        if not content:
            return
            
        if msg_type == "group_at_message":
            group_id = str(data.get("group_id", ""))
            session_id = f"group_{group_id}_{author_id}"
            target_type = "group"
            target_id = group_id
        elif msg_type == "c2c_message":
            session_id = f"private_{author_id}"
            target_type = "c2c"
            target_id = author_id
        elif msg_type in ("at_message", "message"):
            channel_id = str(data.get("channel_id", ""))
            session_id = f"channel_{channel_id}_{author_id}"
            target_type = "channel"
            target_id = channel_id
        else:
            return
            
        self._log("info", f"[{session_id}] 收到消息: {content[:50]}...")
        
        # 保存用户消息
        self.chat_history.save_message(session_id, "user", content, {
            "msg_id": msg_id,
            "msg_type": msg_type,
        })
        
        # 获取AI回复（通过后端）
        try:
            session = await self._get_or_create_session(session_id)
            response = await session.send_text(content, self.cfg.persona_filename)
            
            if response:
                # 保存AI回复
                self.chat_history.save_message(session_id, "assistant", response)
                await self._send_message(target_type, target_id, response, msg_id)
        except Exception as e:
            self._log("error", f"获取AI回复失败: {e}")
            await self._send_message(target_type, target_id, "哎呀，出了点小问题...", msg_id)
            
    async def _send_message(self, target_type: str, target_id: str, content: str, msg_id: str = ""):
        if not content:
            return
            
        if self.cfg.qq_strip_markdown:
            content = _strip_markdown_for_qq(content)
            
        max_len = self.cfg.qq_max_bubble_len
        if len(content) > max_len:
            chunks = self._split_message(content)
        else:
            chunks = [content]
            
        for chunk in chunks:
            if target_type == "channel":
                await self.transport.send_to_channel(target_id, chunk, msg_id)
            elif target_type == "group":
                await self.transport.send_to_group(target_id, chunk, msg_id)
            elif target_type == "c2c":
                await self.transport.send_to_c2c(target_id, chunk, msg_id)
            await asyncio.sleep(0.5)
            
    def _split_message(self, content: str) -> list[str]:
        max_len = self.cfg.qq_max_bubble_len
        min_len = self.cfg.qq_min_split_len
        
        if len(content) <= max_len:
            return [content]
            
        chunks = []
        while content:
            if len(content) <= max_len:
                chunks.append(content)
                break
                
            split_pos = -1
            for sep in ["。", "！", "？", "，", "；", "\n"]:
                pos = content.rfind(sep, min_len, max_len)
                if pos > split_pos:
                    split_pos = pos + 1
                    
            if split_pos < min_len:
                split_pos = max_len
                
            chunks.append(content[:split_pos])
            content = content[split_pos:].lstrip()
            
        return chunks
        
    async def send_proactive_message(self, content: str, target_user_id: str = ""):
        """发送主动消息（供Active Care调用）"""
        target_id = target_user_id or self.cfg.master_qq_id
        if not target_id:
            self._log("warning", "无法发送主动消息：未配置目标用户")
            return False
            
        await self.proactive_messenger.send_to_user(target_id, content)
        self._log("info", f"发送主动消息到 {target_id}: {content[:30]}...")
        return True
        
    async def run(self):
        try:
            self._log("info", "启动QQ官方机器人适配器...")
            self._log("info", f"人设: {self.cfg.persona_filename or '未配置'}")
            self._log("info", f"后端: {self.cfg.xiaoyou_ws_url}")
            await self.proactive_messenger.start()
            await self.transport.connect(self._handle_message)
        finally:
            QQOfficialAdapter._unregister_instance(self)
            for session in self.sessions.values():
                await session.stop()
            if self._http_session and not self._http_session.closed:
                await self._http_session.close()
                
    @classmethod
    def get_active_instances(cls) -> list[dict[str, str]]:
        """获取所有活跃实例"""
        result = []
        for key, adapter in list(cls._instances.items()):
            if not adapter.transport.is_connected():
                continue
            result.append({
                "role_id": str(adapter.cfg.role_id or "").strip(),
                "app_id": str(adapter.cfg.app_id or "").strip(),
                "persona_filename": str(adapter.cfg.persona_filename or "").strip(),
                "master_qq_id": str(adapter.cfg.master_qq_id or "").strip(),
            })
        return result
        
    @classmethod
    def _unregister_instance(cls, adapter):
        keys_to_remove = [k for k, v in cls._instances.items() if v is adapter]
        for k in keys_to_remove:
            cls._instances.pop(k, None)


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    
    role_id = ""
    if len(sys.argv) > 1 and sys.argv[1] == "--role_id" and len(sys.argv) > 2:
        role_id = sys.argv[2]
    
    adapter = QQOfficialAdapter(role_id=role_id)
    try:
        asyncio.run(adapter.run())
    except KeyboardInterrupt:
        logger.info("QQ官方机器人适配器已停止")
    except Exception as e:
        logger.error(f"致命错误: {e}", exc_info=True)
        if os.name == "nt":
            input("按回车键退出...")
