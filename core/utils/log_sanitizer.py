#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
日志脱敏与错误上报模块
提供敏感信息保护、错误跟踪和上报功能
"""

import re
import json
import uuid
import asyncio
import traceback
from typing import Dict, Any, Optional, Union, Callable, List
from datetime import datetime, timezone
import threading
from pathlib import Path
import os
import aiofiles
from config.integrated_config import get_settings

import logging

# from core.utils.logger import get_logger
from core.core_engine.event_bus import get_event_bus, EventTypes

# 使用标准logging以避免循环依赖
logger = logging.getLogger("LOG_SANITIZER")

# 敏感信息模式定义
SENSITIVE_PATTERNS = {
    # 手机号
    "phone": re.compile(r'1[3-9]\d{9}'),
    # 邮箱
    "email": re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),
    # 身份证号
    "id_card": re.compile(r'[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]'),
    # 银行卡号
    "bank_card": re.compile(r'\b(?:\d{4}[ -]?){3}\d{4}\b'),
    # API Key/Secret
    "api_key": re.compile(r'(?:api[_-]?key|apikey|secret)[_=:\s]*(?P<key>[a-zA-Z0-9]{20,})'),
    # 密码
    "password": re.compile(r'(?:password|passwd)[_=:\s]*(?P<pass>[^\s,]+)'),
    # URL中的参数
    "url_params": re.compile(r'(?:token|auth|secret|key)=([^&]+)'),
}

# 脱敏替换规则
SANITIZATION_RULES = {
    "phone": lambda x: x[:3] + "****" + x[-4:],
    "email": lambda x: x.split("@")[0][:2] + "****@" + x.split("@")[1],
    "id_card": lambda x: x[:6] + "********" + x[-4:],
    "bank_card": lambda x: x[:4] + "********" + x[-4:],
    "api_key": lambda x: "********",
    "password": lambda x: "********",
    "url_params": lambda x: "********",
}

# 全局配置
_sanitizer_config = {
    "enabled": True,
    "patterns": SENSITIVE_PATTERNS.copy(),
    "rules": SANITIZATION_RULES.copy(),
    "exclude_loggers": [],
    "error_reporting": {
        "enabled": True,
        "max_queue_size": 100,
        "report_interval": 5.0,  # 秒
        "min_level": "ERROR",
    },
}

# 错误报告队列
_error_queue = asyncio.Queue()
# 错误报告处理任务
_report_task = None
# 错误回调函数列表
_error_callbacks: List[Callable] = []
# 锁
_lock = threading.RLock()

class LogSanitizer:
    """日志脱敏器"""
    
    @staticmethod
    def sanitize_message(message: str, extra_patterns: Optional[Dict[str, re.Pattern]] = None,
                        extra_rules: Optional[Dict[str, Callable[[str], str]]] = None) -> str:
        """
        脱敏日志消息
        
        Args:
            message: 原始消息
            extra_patterns: 额外的敏感信息模式
            extra_rules: 额外的脱敏规则
            
        Returns:
            脱敏后的消息
        """
        if not _sanitizer_config["enabled"]:
            return message
        
        result = message
        patterns = _sanitizer_config["patterns"].copy()
        rules = _sanitizer_config["rules"].copy()
        
        # 添加额外模式和规则
        if extra_patterns:
            patterns.update(extra_patterns)
        if extra_rules:
            rules.update(extra_rules)
        
        # 对每种敏感信息进行脱敏
        for pattern_name, pattern in patterns.items():
            # 针对捕获组的特殊处理
            if "(?P<key>" in pattern.pattern or "(?P<pass>" in pattern.pattern:
                def replace_with_capture(match):
                    for group_name, value in match.groupdict().items():
                        if value:
                            rule = rules.get(pattern_name, lambda x: "********")
                            return match.group(0).replace(value, rule(value))
                    return match.group(0)
                result = pattern.sub(replace_with_capture, result)
            else:
                # 普通替换
                rule = rules.get(pattern_name, lambda x: "********")
                result = pattern.sub(lambda m: rule(m.group(0)), result)
        
        return result
    
    @staticmethod
    def sanitize_dict(data: Dict[str, Any], sensitive_keys: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        脱敏字典数据
        
        Args:
            data: 原始字典
            sensitive_keys: 敏感键列表
            
        Returns:
            脱敏后的字典
        """
        if not _sanitizer_config["enabled"]:
            return data
        
        # 默认敏感键
        default_sensitive_keys = [
            "password", "passwd", "token", "auth", "secret", 
            "api_key", "apikey", "key", "credit_card", "cc_number"
        ]
        
        if sensitive_keys:
            default_sensitive_keys.extend(sensitive_keys)
        
        result = {}
        
        for key, value in data.items():
            key_lower = key.lower()
            
            # 检查是否为敏感键
            is_sensitive = any(sensitive in key_lower for sensitive in default_sensitive_keys)
            
            if is_sensitive and isinstance(value, str):
                result[key] = "********"
            elif isinstance(value, dict):
                # 递归处理嵌套字典
                result[key] = LogSanitizer.sanitize_dict(value, sensitive_keys)
            elif isinstance(value, list):
                # 处理列表
                result[key] = [
                    LogSanitizer.sanitize_dict(item, sensitive_keys) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value
        
        return result
    
    @staticmethod
    def should_sanitize_logger(logger_name: str) -> bool:
        """
        检查是否应该对指定的日志记录器进行脱敏
        
        Args:
            logger_name: 日志记录器名称
            
        Returns:
            是否应该脱敏
        """
        exclude_loggers = _sanitizer_config["exclude_loggers"]
        return not any(exclude in logger_name for exclude in exclude_loggers)

class ErrorReporter:
    """错误报告器"""
    
    @staticmethod
    async def report_error(
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        severity: str = "ERROR",
        error_id: Optional[str] = None
    ) -> str:
        """
        报告错误
        
        Args:
            error: 异常对象
            context: 错误上下文
            severity: 严重程度
            error_id: 错误ID（如果为None则自动生成）
            
        Returns:
            错误ID
        """
        if not _sanitizer_config["error_reporting"]["enabled"]:
            return ""
        
        # 确保severity是有效的
        valid_severities = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if severity not in valid_severities:
            severity = "ERROR"
        
        # 检查最小级别
        min_level = _sanitizer_config["error_reporting"]["min_level"]
        if valid_severities.index(severity) < valid_severities.index(min_level):
            return ""
        
        # 生成错误ID
        if not error_id:
            error_id = f"err_{uuid.uuid4().hex[:12]}"
        
        # 构建错误报告
        error_report = {
            "error_id": error_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "severity": severity,
            "error_type": error.__class__.__name__ if error else "UnknownError",
            "error_message": str(error) if error else "Unknown error",
            "traceback": traceback.format_exc() if error else "",
            "context": LogSanitizer.sanitize_dict(context or {})
        }
        
        # 添加到队列
        try:
            await _error_queue.put(error_report)
            # 触发错误事件
            event_bus = get_event_bus()
            await event_bus.publish(EventTypes.ERROR_OCCURRED, error_id=error_id, error=error_report)
            
            # 立即执行回调
            for callback in _error_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(error_id, error_report)
                    else:
                        callback(error_id, error_report)
                except Exception as e:
                    logger.error(f"错误回调执行失败: {e}")
                    
            return error_id
        except asyncio.QueueFull:
            logger.warning("错误队列已满，无法报告错误")
            return ""
    
    @staticmethod
    async def _process_error_queue():
        """处理错误队列"""
        while True:
            try:
                # 批量处理错误
                errors = []
                try:
                    # 尝试获取最多10个错误
                    for _ in range(10):
                        error = await asyncio.wait_for(_error_queue.get(), timeout=0.1)
                        errors.append(error)
                        _error_queue.task_done()
                except asyncio.TimeoutError:
                    # 没有更多错误
                    pass
                
                if errors:
                    # 这里可以实现批量上报逻辑
                    # 例如保存到文件、发送到远程服务器等
                    await ErrorReporter._save_errors_to_file(errors)
                
                # 等待一段时间再处理下一批
                await asyncio.sleep(_sanitizer_config["error_reporting"]["report_interval"])
                
            except Exception as e:
                logger.error(f"错误队列处理失败: {e}")
                await asyncio.sleep(1.0)  # 出错后短暂等待

    @staticmethod
    async def _save_errors_to_file(errors: List[Dict[str, Any]]):
        """
        保存错误到文件
        
        Args:
            errors: 错误列表
        """
        try:
            # 获取日志目录
            settings = get_settings()
            log_dir = Path(settings.log.error_dir)
            # Use absolute path if configured, otherwise relative to cwd
            if not log_dir.is_absolute():
                 log_dir = Path.cwd() / log_dir
            
            log_dir.mkdir(parents=True, exist_ok=True)
            
            # 生成文件名
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = log_dir / f"errors_{timestamp}.json"
            
            # 保存错误信息
            async with aiofiles.open(filename, "w", encoding="utf-8") as f:
                await f.write(json.dumps(errors, ensure_ascii=False, indent=2))
                
            logger.info(f"已保存 {len(errors)} 个错误到 {filename}")
            
        except Exception as e:
            logger.error(f"保存错误到文件失败: {e}")

# 工具函数
def sanitize_log(message: str, logger_name: str = "") -> str:
    """
    便捷的日志脱敏函数
    
    Args:
        message: 原始消息
        logger_name: 日志记录器名称
        
    Returns:
        脱敏后的消息
    """
    if LogSanitizer.should_sanitize_logger(logger_name):
        return LogSanitizer.sanitize_message(message)
    return message

def register_error_callback(callback: Callable[[str, Dict[str, Any]], None]):
    """
    注册错误回调函数
    
    Args:
        callback: 回调函数，接受(error_id, error_report)参数
    """
    with _lock:
        if callback not in _error_callbacks:
            _error_callbacks.append(callback)

def unregister_error_callback(callback: Callable):
    """
    注销错误回调函数
    
    Args:
        callback: 回调函数
    """
    with _lock:
        if callback in _error_callbacks:
            _error_callbacks.remove(callback)

def get_error_count() -> int:
    """
    获取队列中的错误数量
    
    Returns:
        错误数量
    """
    return _error_queue.qsize()

def clear_error_queue():
    """
    清空错误队列
    """
    while not _error_queue.empty():
        try:
            _error_queue.get_nowait()
            _error_queue.task_done()
        except asyncio.QueueEmpty:
            break

def update_config(config: Dict[str, Any]):
    """
    更新配置
    
    Args:
        config: 新的配置字典
    """
    with _lock:
        _sanitizer_config.update(config)
        
        # 特别处理模式和规则
        if "patterns" in config:
            _sanitizer_config["patterns"].update(config["patterns"])
        if "rules" in config:
            _sanitizer_config["rules"].update(config["rules"])

# 初始化和关闭函数
async def initialize_sanitizer():
    """
    初始化日志脱敏和错误上报系统
    """
    global _report_task
    
    if _report_task is None:
        # 设置队列最大大小
        _error_queue._maxsize = _sanitizer_config["error_reporting"]["max_queue_size"]
        
        # 启动错误处理任务
        _report_task = asyncio.create_task(ErrorReporter._process_error_queue())
        logger.info("日志脱敏与错误上报系统已初始化")

async def shutdown_sanitizer():
    """
    关闭日志脱敏和错误上报系统
    """
    global _report_task
    
    if _report_task:
        # 取消任务
        _report_task.cancel()
        try:
            await _report_task
        except asyncio.CancelledError:
            pass
        _report_task = None
    
    # 清空队列
    clear_error_queue()
    
    # 清空回调列表
    with _lock:
        _error_callbacks.clear()
    
    logger.info("日志脱敏与错误上报系统已关闭")

# 装饰器
def with_log_sanitization(func):
    """
    自动脱敏日志的装饰器
    
    Args:
        func: 被装饰的函数
        
    Returns:
        装饰后的函数
    """
    import functools
    
    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            # 报告错误
            context = {
                "function": func.__name__,
                "args": LogSanitizer.sanitize_dict({k: v for k, v in enumerate(args)}),
                "kwargs": LogSanitizer.sanitize_dict(kwargs)
            }
            await ErrorReporter.report_error(e, context=context)
            raise
    
    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # 报告错误（同步方式）
            context = {
                "function": func.__name__,
                "args": LogSanitizer.sanitize_dict({k: v for k, v in enumerate(args)}),
                "kwargs": LogSanitizer.sanitize_dict(kwargs)
            }
            # 使用事件循环报告错误
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 如果事件循环正在运行，使用create_task
                    loop.create_task(ErrorReporter.report_error(e, context=context))
                else:
                    # 如果事件循环未运行，直接运行
                    loop.run_until_complete(ErrorReporter.report_error(e, context=context))
            except Exception:
                # 如果无法获取事件循环，记录但不崩溃
                logger.error(f"无法报告错误: {e}")
            raise
    
    # 根据函数类型返回不同的包装器
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper

# 导出
__all__ = [
    "LogSanitizer",
    "ErrorReporter",
    "sanitize_log",
    "register_error_callback",
    "unregister_error_callback",
    "get_error_count",
    "clear_error_queue",
    "update_config",
    "initialize_sanitizer",
    "shutdown_sanitizer",
    "with_log_sanitization"
]