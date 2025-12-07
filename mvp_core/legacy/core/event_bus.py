#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
事件总线模块
用于组件间通信
"""
import logging
from typing import Dict, List, Callable, Any, Set, Awaitable, Optional
import asyncio

logger = logging.getLogger(__name__)

class EventBus:
    """
    事件总线
    支持异步事件发布和订阅
    """
    
    def __init__(self):
        """
        初始化事件总线
        """
        # 事件订阅者字典
        # 格式: {event_name: [subscribers]}
        self._subscribers: Dict[str, List[Callable[[Any], Awaitable[None]]]] = {}
        
        # 事件历史
        self._event_history = []
        self._max_history = 100
        
        logger.info("EventBus initialized")
    
    async def subscribe(self, event_name: str, callback: Callable[[Any], Awaitable[None]]):
        """
        订阅事件
        
        Args:
            event_name: 事件名称
            callback: 回调函数，接收事件数据作为参数
        """
        if event_name not in self._subscribers:
            self._subscribers[event_name] = []
        
        # 检查是否已经订阅
        if callback not in self._subscribers[event_name]:
            self._subscribers[event_name].append(callback)
            logger.info(f"Subscribed to event: {event_name}")
    
    async def unsubscribe(self, event_name: str, callback: Callable[[Any], Awaitable[None]]):
        """
        取消订阅事件
        
        Args:
            event_name: 事件名称
            callback: 回调函数
        """
        if event_name in self._subscribers:
            if callback in self._subscribers[event_name]:
                self._subscribers[event_name].remove(callback)
                logger.info(f"Unsubscribed from event: {event_name}")
            
            # 如果没有订阅者了，移除事件
            if not self._subscribers[event_name]:
                del self._subscribers[event_name]
    
    async def publish(self, event_name: str, data: Any = None):
        """
        发布事件
        
        Args:
            event_name: 事件名称
            data: 事件数据
        """
        # 记录事件历史
        self._event_history.append({
            "event_name": event_name,
            "data": data,
            "timestamp": asyncio.get_event_loop().time()
        })
        
        # 限制历史记录数量
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)
        
        logger.info(f"Publishing event: {event_name}")
        
        # 通知所有订阅者
        if event_name in self._subscribers:
            for callback in self._subscribers[event_name]:
                try:
                    await callback(data)
                except Exception as e:
                    logger.error(f"Error in event handler for {event_name}: {e}")
    
    def get_event_history(self, event_name: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取事件历史
        
        Args:
            event_name: 事件名称，None表示所有事件
            limit: 返回的历史记录数量
            
        Returns:
            事件历史列表
        """
        if event_name:
            history = [event for event in self._event_history if event["event_name"] == event_name]
        else:
            history = self._event_history.copy()
        
        return history[-limit:]
    
    def get_subscribers(self, event_name: Optional[str] = None) -> Dict[str, List[Callable]]:
        """
        获取订阅者列表
        
        Args:
            event_name: 事件名称，None表示所有事件
            
        Returns:
            订阅者字典
        """
        if event_name:
            return {event_name: self._subscribers.get(event_name, [])}
        else:
            return self._subscribers.copy()
    
    def clear_events(self, event_name: Optional[str] = None):
        """
        清除事件历史
        
        Args:
            event_name: 事件名称，None表示所有事件
        """
        if event_name:
            self._event_history = [event for event in self._event_history if event["event_name"] != event_name]
        else:
            self._event_history.clear()
        
        logger.info(f"Cleared event history for {event_name or 'all events'}")
