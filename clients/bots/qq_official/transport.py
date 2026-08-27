"""
QQ官方机器人传输层
基于QQ开放平台API v2
使用botpy库连接WebSocket，通过OpenAPI发送消息
"""

import logging
import os
import time
from logging.handlers import TimedRotatingFileHandler
from typing import Optional, Callable

import botpy
import botpy.logging as botpy_logging
from botpy import BotAPI
from botpy.message import Message, GroupMessage, C2CMessage

logger = logging.getLogger("QQOfficial")


class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """Windows 安全的 TimedRotatingFileHandler，轮转失败时不会崩溃

    Windows 下当日志文件被其他进程/句柄占用时，os.rename 会抛 PermissionError，
    导致心跳线程内的日志输出连锁失败。这里在轮转失败时回退为重新打开当前文件继续写入，
    放弃本次按天轮转，下次到点再尝试。
    """

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            try:
                if self.stream:
                    try:
                        self.stream.close()
                    except Exception:
                        pass
                    self.stream = None
                # 轮转失败时直接重新打开当前文件继续追加写入
                self.stream = self._open()
            except Exception:
                pass


# 项目根目录（clients/bots/qq_official/transport.py 向上 4 层）
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
_LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

# botpy 默认会把日志写到 cwd/botpy.log，污染项目根目录；
# 这里改成写到 logs/botpy.log，按天滚动、保留 7 天
# 使用 SafeTimedRotatingFileHandler 避免 Windows 下文件占用导致轮转失败
_BOTPY_LOG_HANDLER = {
    "handler": SafeTimedRotatingFileHandler,
    "format": "%(asctime)s\t[%(levelname)s]\t(%(filename)s:%(lineno)s)%(funcName)s\t%(message)s",
    "level": logging.DEBUG,
    "when": "D",
    "backupCount": 7,
    "encoding": "utf-8",
    "filename": os.path.join(_LOG_DIR, "botpy.log"),
}

# 在 import botpy 时 botpy 已创建 "botpy" logger，这里直接给它挂上自定义 handler
# force=True 确保即使重复 import 也只保留我们的配置
botpy_logging.configure_logging(ext_handlers=_BOTPY_LOG_HANDLER, force=True)


class QQOfficialClient(botpy.Client):
    """QQ官方机器人客户端"""
    
    def __init__(self, config, message_callback: Callable, **kwargs):
        intents = botpy.Intents(
            public_guild_messages=True,
            public_messages=True,
            guild_messages=True,
            direct_message=True,
        )
        # ext_handlers=False：日志 handler 已在模块加载时通过
        # botpy_logging.configure_logging 配置到 logs/botpy.log，
        # 这里关闭 botpy.Client 默认的 cwd/botpy.log 文件 handler
        kwargs.setdefault("ext_handlers", False)
        super().__init__(intents=intents, **kwargs)
        self.config = config
        self.message_callback = message_callback
        self._api: Optional[BotAPI] = None
        
    async def on_ready(self):
        """机器人就绪事件"""
        logger.info(f"QQ官方机器人已连接: {self.robot.name}")
        self._api = self.api
        
    async def on_at_message_create(self, message: Message):
        """收到@消息（频道/群）"""
        logger.info(f"[频道/群消息] {message.author.username}: {message.content}")
        await self.message_callback({
            "type": "at_message",
            "channel_id": message.channel_id,
            "guild_id": getattr(message, "guild_id", ""),
            "author_id": message.author.id,
            "author_name": message.author.username,
            "content": message.content.strip(),
            "message_id": message.id,
            "timestamp": int(time.time() * 1000),
        })
        
    async def on_message_create(self, message: Message):
        """收到普通消息（频道）"""
        logger.info(f"[频道消息] {message.author.username}: {message.content}")
        await self.message_callback({
            "type": "message",
            "channel_id": message.channel_id,
            "guild_id": getattr(message, "guild_id", ""),
            "author_id": message.author.id,
            "author_name": message.author.username,
            "content": message.content.strip(),
            "message_id": message.id,
            "timestamp": int(time.time() * 1000),
        })
        
    async def on_group_at_message_create(self, message: GroupMessage):
        """收到群@消息"""
        logger.info(f"[群@消息] {message.author.member_openid}: {message.content}")
        await self.message_callback({
            "type": "group_at_message",
            "group_id": message.group_id,
            "author_id": message.author.member_openid,
            "author_name": "",
            "content": message.content.strip(),
            "message_id": message.id,
            "timestamp": int(time.time() * 1000),
        })
        
    async def on_c2c_message_create(self, message: C2CMessage):
        """收到私聊消息"""
        logger.info(f"[私聊消息] {message.author.user_openid}: {message.content}")
        await self.message_callback({
            "type": "c2c_message",
            "author_id": message.author.user_openid,
            "author_name": "",
            "content": message.content.strip(),
            "message_id": message.id,
            "timestamp": int(time.time() * 1000),
        })


class QQOfficialTransport:
    """QQ官方机器人传输层"""
    
    def __init__(self, config):
        self.config = config
        self.client: Optional[QQOfficialClient] = None
        self._api: Optional[BotAPI] = None
        self.running = False
        
    async def connect(self, message_callback: Callable):
        """连接到QQ官方机器人
        
        Args:
            message_callback: 消息回调，接收消息字典
        """
        self.running = True
        
        self.client = QQOfficialClient(
            config=self.config,
            message_callback=message_callback,
            is_sandbox=self.config.sandbox_mode,
        )
        
        logger.info(f"正在连接QQ官方机器人 (AppID: {self.config.app_id})...")
        logger.info(f"沙箱模式: {self.config.sandbox_mode}")
        
        try:
            await self.client.start(self.config.app_id, self.config.app_secret)
        except Exception as e:
            logger.error(f"QQ官方机器人连接失败: {e}")
            raise
            
    async def send_to_channel(self, channel_id: str, content: str, msg_id: str = ""):
        """发送消息到频道
        
        Args:
            channel_id: 频道ID
            content: 消息内容
            msg_id: 原消息ID（用于回复）
        """
        if not self.client or not self.client._api:
            logger.error("未连接到QQ官方机器人")
            return
            
        try:
            payload = {
                "channel_id": channel_id,
                "content": content,
            }
            if msg_id:
                payload["msg_id"] = msg_id
                
            await self.client._api.post_message(**payload)
            logger.info(f"发送到频道 {channel_id}: {content[:50]}...")
        except Exception as e:
            logger.error(f"发送频道消息失败: {e}")
            
    async def send_to_group(self, group_id: str, content: str, msg_id: str = "", msg_type: int = 0):
        """发送消息到群
        
        Args:
            group_id: 群ID
            content: 消息内容
            msg_id: 原消息ID（用于回复）
            msg_type: 消息类型
        """
        if not self.client or not self.client._api:
            logger.error("未连接到QQ官方机器人")
            return
            
        try:
            payload = {
                "group_id": group_id,
                "content": content,
                "msg_type": msg_type,
            }
            if msg_id:
                payload["msg_id"] = msg_id
                
            await self.client._api.post_group_message(**payload)
            logger.info(f"发送到群 {group_id}: {content[:50]}...")
        except Exception as e:
            logger.error(f"发送群消息失败: {e}")
            
    async def send_to_c2c(self, openid: str, content: str, msg_id: str = "", msg_type: int = 0):
        """发送私聊消息
        
        Args:
            openid: 用户openid
            content: 消息内容
            msg_id: 原消息ID（用于回复）
            msg_type: 消息类型
        """
        if not self.client or not self.client._api:
            logger.error("未连接到QQ官方机器人")
            return
            
        try:
            payload = {
                "openid": openid,
                "content": content,
                "msg_type": msg_type,
            }
            if msg_id:
                payload["msg_id"] = msg_id
                
            await self.client._api.post_c2c_message(**payload)
            logger.info(f"发送私聊到 {openid}: {content[:50]}...")
        except Exception as e:
            logger.error(f"发送私聊消息失败: {e}")
            
    async def send_rich_media(self, target_type: str, target_id: str, 
                              file_type: int, url: str, msg_id: str = ""):
        """发送富媒体消息（图片、视频等）
        
        Args:
            target_type: 目标类型 (channel/group/c2c)
            target_id: 目标ID
            file_type: 文件类型 (1:图片, 2:视频, 3:语音)
            url: 文件URL
            msg_id: 原消息ID
        """
        if not self.client or not self.client._api:
            logger.error("未连接到QQ官方机器人")
            return
            
        try:
            # 上传媒体文件
            media = MessageMediaInput(
                file_type=file_type,
                url=url,
            )
            
            if target_type == "channel":
                result = await self.client._api.post_group_file(
                    group_openid=target_id,
                    file_type=file_type,
                    url=url,
                )
            elif target_type == "group":
                result = await self.client._api.post_group_file(
                    group_openid=target_id,
                    file_type=file_type,
                    url=url,
                )
            elif target_type == "c2c":
                result = await self.client._api.post_c2c_file(
                    openid=target_id,
                    file_type=file_type,
                    url=url,
                )
                
            logger.info(f"发送富媒体到 {target_type}/{target_id}: {url[:50]}...")
        except Exception as e:
            logger.error(f"发送富媒体失败: {e}")
            
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self.running and self.client is not None
        
    async def disconnect(self):
        """断开连接"""
        self.running = False
        if self.client:
            await self.client.close()
