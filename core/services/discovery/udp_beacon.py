#!/usr/bin/env python3
"""
UDP 服务发现信标

向后端局域网广播服务器地址，供安卓客户端零配置发现。
广播格式: AVELINE_SERVER|http://<ip>:<port>
"""

from core.utils.logger import get_logger
import asyncio

import socket
from typing import Optional

logger = get_logger(__name__)

# 配置
DISCOVERY_PORT = 28899
BROADCAST_MAGIC = "AVELINE_SERVER"
BROADCAST_INTERVAL = 5  # 秒


class UDPBeaconService:
    """UDP 服务发现信标"""
    
    def __init__(self, http_port: int = 8000):
        self.http_port = http_port
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cached_ip: Optional[str] = None
        
    async def start(self):
        """启动 UDP 广播服务"""
        if self._running:
            return
            
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.setblocking(False)
            
            self._running = True
            self._task = asyncio.create_task(self._broadcast_loop())
            logger.info(f"UDP 信标服务已启动，端口 {DISCOVERY_PORT}，HTTP 端口 {self.http_port}")
        except Exception as e:
            logger.error(f"启动 UDP 信标失败: {e}")
            
    async def stop(self):
        """停止 UDP 广播服务"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._socket:
            self._socket.close()
            self._socket = None
        logger.info("UDP 信标服务已停止")
        
    async def _broadcast_loop(self):
        """广播循环"""
        while self._running:
            try:
                # 获取本机 IP（缓存避免频繁计算）
                if not self._cached_ip:
                    self._cached_ip = self._get_local_ip()
                    
                if self._cached_ip:
                    message = f"{BROADCAST_MAGIC}|http://{self._cached_ip}:{self.http_port}"
                    data = message.encode('utf-8')
                    
                    # 向局域网广播
                    self._socket.sendto(data, ('<broadcast>', DISCOVERY_PORT))
                    logger.debug(f"广播: {message}")
                    
                await asyncio.sleep(BROADCAST_INTERVAL)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"UDP 广播错误: {e}")
                await asyncio.sleep(BROADCAST_INTERVAL)
                
    def _get_local_ip(self) -> Optional[str]:
        """获取本机局域网 IP"""
        try:
            # 方法1：通过 UDP 连接外部地址来推断本地 IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(('8.8.8.8', 80))
                ip = s.getsockname()[0]
                return ip
            finally:
                s.close()
        except Exception:
            pass
            
        try:
            # 方法2：获取主机名对应的 IP
            hostname = socket.gethostname()
            ip = socket.getaddrinfo(hostname, None, socket.AF_INET)[0][4][0]
            return ip
        except Exception:
            pass
            
        return None


# 全局实例
_beacon_service: Optional[UDPBeaconService] = None


async def start_discovery_beacon(http_port: int = 8000) -> UDPBeaconService:
    """启动服务发现信标（全局单例）"""
    global _beacon_service
    if _beacon_service is None:
        _beacon_service = UDPBeaconService(http_port)
        await _beacon_service.start()
    return _beacon_service


async def stop_discovery_beacon():
    """停止服务发现信标"""
    global _beacon_service
    if _beacon_service:
        await _beacon_service.stop()
        _beacon_service = None
