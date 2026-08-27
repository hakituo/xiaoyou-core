#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
客户端工具函数
统一处理客户端类型探测、连接状态检查等
"""

from core.utils.logger import get_module_logger
from core.utils.config_accessor import get_config

logger = get_module_logger("CLIENT_UTILS", "client_utils.log")


def probe_client_type() -> str:
    """
    探测当前活跃的客户端类型
    
    Returns:
        str: 客户端类型
            - "qq": QQ 客户端
            - "websocket": WebSocket 客户端（非QQ）
            - "web": Web 客户端或无连接
    """
    try:
        from core.interfaces.websocket.websocket_manager import get_websocket_manager
        
        ws_manager = get_websocket_manager()
        if not ws_manager or not hasattr(ws_manager, "connections"):
            return "web"
        
        if not ws_manager.connections:
            return "web"
        
        has_qq = False
        has_non_qq = False
        
        for conn in list(ws_manager.connections.values()):
            platform = str(getattr(conn, "platform", "") or "").lower().strip()
            ws_client_id = str(
                get_config("websocket.client_id", default="", settings=conn)
            ).lower().strip()
            
            is_qq = (
                platform == "qq"
                or "qq" in platform
                or ws_client_id.startswith("qq_")
            )
            
            if is_qq:
                has_qq = True
            else:
                has_non_qq = True
        
        # 优先返回 QQ：主动关怀是主动推送，QQ 是推送主渠道（手机通知），
        # websocket 客户端在前端可直接看到消息；QQ 优先确保推送到位
        if has_qq:
            return "qq"
        if has_non_qq:
            return "websocket"
        
        return "web"
        
    except Exception as e:
        logger.debug(f"探测客户端类型失败: {e}")
        return "web"


def has_active_client() -> bool:
    """
    检查是否有活跃的客户端连接
    
    Returns:
        bool: 是否有活跃连接
    """
    try:
        from core.interfaces.websocket.websocket_manager import get_websocket_manager
        
        ws_manager = get_websocket_manager()
        if ws_manager and hasattr(ws_manager, "connections"):
            if len(ws_manager.connections) > 0:
                return True
    except Exception:
        pass
    
    # 检查通知管理器
    try:
        from core.managers.notification_manager import get_notification_manager
        
        nm = get_notification_manager()
        if nm and nm.has_active_connections():
            return True
    except Exception:
        pass
    
    return False
