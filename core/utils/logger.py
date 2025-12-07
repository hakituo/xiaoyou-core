import logging
import colorama
from datetime import datetime, timezone
import os
import json
import traceback
from typing import Dict, Any, Optional, Union
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
import threading
import asyncio

# 导入日志脱敏模块
try:
    from core.utils.log_sanitizer import sanitize_log, initialize_sanitizer
    _has_sanitizer = True
except ImportError:
    _has_sanitizer = False
    def sanitize_log(message, logger_name=""):
        return message
    async def initialize_sanitizer():
        pass
# 初始化colorama
colorama.init(autoreset=True)
# 定义颜色映射
COLORS = {
    "DEBUG": colorama.Fore.BLUE,
    "INFO": colorama.Fore.GREEN,
    "WARNING": colorama.Fore.YELLOW,
    "ERROR": colorama.Fore.RED,
    "CRITICAL": colorama.Fore.RED + colorama.Style.BRIGHT,
}
# 从配置加载器导入配置
from config.integrated_config import get_settings
config = get_settings()
# 获取日志配置
def get_log_config() -> Dict[str, Any]:
    """从配置加载器获取日志配置"""
    try:
        log_settings = config.log
        return {
            'log_dir': log_settings.log_dir,
            'log_level': log_settings.level,
            'use_json': log_settings.use_json_format,
            'rotation_type': log_settings.rotation_type,
            'max_bytes': log_settings.max_bytes,
            'backup_count': log_settings.backup_count,
            'rotation_when': log_settings.rotation_when,
            'rotation_interval': log_settings.rotation_interval
        }
    except Exception:
        # 如果属性访问失败，使用默认值
        return {
            'log_dir': './logs/',
            'log_level': 'INFO',
            'use_json': False,
            'rotation_type': 'size',
            'max_bytes': 10485760,  # 10MB
            'backup_count': 5,
            'rotation_when': 'midnight',
            'rotation_interval': 1
        }
# 确保日志目录存在
log_config = get_log_config()
log_dir = log_config['log_dir']
os.makedirs(log_dir, exist_ok=True)
# 请求上下文存储，用于跟踪request_id
_request_context_local = threading.local()
# 格式化递归保护
_formatting_local = threading.local()

# 临时禁用自定义Formatter以修复RecursionError
class SanitizingFormatter(logging.Formatter):
    def format(self, record):
        return super().format(record)

class ColoredFormatter(logging.Formatter):
    def format(self, record):
        return super().format(record)

class JSONFormatter(SanitizingFormatter):
    """JSON格式的日志格式化器"""
    def format(self, record):
        # 构建JSON日志记录
        log_record = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'name': record.name,
            'message': record.getMessage(),
            'request_id': get_request_id() or 'N/A',
            'error_id': getattr(record, 'error_id', None)
        }
        # 添加异常信息
        if record.exc_info:
            log_record['exception'] = traceback.format_exception(*record.exc_info)
        # 添加进程和线程信息
        log_record['process_id'] = record.process
        log_record['thread_id'] = record.thread
        return json.dumps(log_record)
# 全局日志记录器缓存
_loggers = {}
_loggers_lock = threading.RLock()
def get_logger(name: str) -> logging.Logger:
    """获取或创建一个命名的日志记录器"""
    with _loggers_lock:
        if name in _loggers:
            return _loggers[name]
        logger = logging.getLogger(name)
        # 从配置获取日志级别
        log_config = get_log_config()
        log_level = getattr(logging, log_config['log_level'], logging.INFO)
        logger.setLevel(log_level)
        logger.propagate = False  # 防止重复记录
        
        # 增强的异常日志记录
        def enhanced_error(msg, *args, **kwargs):
            exc_info = kwargs.get('exc_info', False)
            error_id = kwargs.pop('error_id', None)
            
            # 创建一个记录对象
            record = logger.makeRecord(
                logger.name,
                logging.ERROR,
                "",  # pathname
                0,    # lineno
                msg,
                args,
                exc_info if exc_info else None,
                func=None,
                sinfo=None,
                **kwargs
            )
            
            # 添加错误ID
            if error_id:
                record.error_id = error_id
            
            # 处理记录
            for handler in logger.handlers:
                if handler.level <= logging.ERROR:
                    handler.handle(record)
        
        # 增强的警告日志记录
        def enhanced_warning(msg, *args, **kwargs):
            record = logger.makeRecord(
                logger.name,
                logging.WARNING,
                "",  # pathname
                0,    # lineno
                msg,
                args,
                None, # exc_info
                func=None,
                sinfo=None,
                **kwargs
            )
            
            for handler in logger.handlers:
                if handler.level <= logging.WARNING:
                    handler.handle(record)
        
        # 添加增强方法
        logger.enhanced_error = enhanced_error
        logger.enhanced_warning = enhanced_warning
        
        # 移除已存在的处理器
        if logger.handlers:
            logger.handlers.clear()
        
        # 创建控制台处理器
        console_handler = logging.StreamHandler()
        console_formatter = ColoredFormatter(
            f"[{colorama.Fore.CYAN}%(asctime)s{colorama.Style.RESET_ALL}][%(levelname)s][{colorama.Fore.MAGENTA}{name}{colorama.Style.RESET_ALL}] %(message)s",
            "%H:%M:%S",
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        # 创建文件处理器
        if log_dir:
            log_file = os.path.join(log_dir, f"{name.lower().replace('.', '_')}.log")
            try:
                # 根据配置选择轮转方式
                if log_config.get('rotation_type') == 'time':
                    file_handler = TimedRotatingFileHandler(
                        log_file, 
                        when=log_config['rotation_when'],
                        interval=log_config['rotation_interval'],
                        backupCount=log_config['backup_count'],
                        encoding="utf-8"
                    )
                else:
                    file_handler = RotatingFileHandler(
                        log_file,
                        maxBytes=log_config['max_bytes'],
                        backupCount=log_config['backup_count'],
                        encoding="utf-8"
                    )
                # 根据配置选择日志格式
                if log_config['use_json']:
                    file_formatter = JSONFormatter()
                else:
                    file_formatter = SanitizingFormatter(
                        "[%(asctime)s][%(levelname)s][%(name)s] %(message)s",
                        "%Y-%m-%d %H:%M:%S",
                    )
                file_handler.setFormatter(file_formatter)
                logger.addHandler(file_handler)
            except Exception as e:
                print(f"无法创建日志文件: {e}")
        
        _loggers[name] = logger
        return logger
def get_request_id() -> Optional[str]:
    """获取当前请求的request_id"""
    return getattr(_request_context_local, 'request_id', None)
def format_log_message(message: str, **kwargs) -> str:
    """
    格式化日志消息，添加额外信息
    Args:
        message: 基础消息
        **kwargs: 额外的键值对
    Returns:
        str: 格式化后的消息
    """
    parts = [message]
    # 添加request_id
    request_id = get_request_id()
    if request_id:
        parts.append(f"request_id={request_id}")
    # 添加其他参数
    for key, value in kwargs.items():
        parts.append(f"{key}={value}")
    return " ".join(parts)
# 提供一个默认的根日志记录器
default_logger = get_logger("xiaoyou_core")

# 初始化日志脱敏系统
def init_logging_system():
    """初始化日志系统，包括脱敏功能"""
    try:
        # 尝试获取当前线程的事件循环
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # 如果在运行中的事件循环中，异步初始化
            loop.create_task(initialize_sanitizer())
        else:
            # 如果不在事件循环中，或者没有事件循环，使用 asyncio.run
            asyncio.run(initialize_sanitizer())
            
        default_logger.info("日志脱敏系统初始化完成")
    except Exception as e:
        # 如果是 "Event loop is closed" 错误，尝试创建新循环
        try:
            asyncio.run(initialize_sanitizer())
            default_logger.info("日志脱敏系统初始化完成 (Fallback)")
        except Exception as retry_e:
            print(f"初始化日志脱敏系统失败: {e}")

# 导出标准日志函数
def debug(message: str, **kwargs):
    """调试日志"""
    if _has_sanitizer:
        message = sanitize_log(message, "xiaoyou_core")
    default_logger.debug(format_log_message(message, **kwargs))

def info(message: str, **kwargs):
    """信息日志"""
    if _has_sanitizer:
        message = sanitize_log(message, "xiaoyou_core")
    default_logger.info(format_log_message(message, **kwargs))

def warning(message: str, **kwargs):
    """警告日志"""
    if _has_sanitizer:
        message = sanitize_log(message, "xiaoyou_core")
    default_logger.warning(format_log_message(message, **kwargs))

def error(message: str, **kwargs):
    """错误日志"""
    if _has_sanitizer:
        message = sanitize_log(message, "xiaoyou_core")
    default_logger.error(format_log_message(message, **kwargs))

def critical(message: str, **kwargs):
    """严重错误日志"""
    if _has_sanitizer:
        message = sanitize_log(message, "xiaoyou_core")
    default_logger.critical(format_log_message(message, **kwargs))

# 导出增强的日志函数
def report_error(error: Exception, context: Optional[Dict] = None, **kwargs):
    """
    报告错误并记录日志
    
    Args:
        error: 异常对象
        context: 上下文信息
        **kwargs: 额外参数
        
    Returns:
        str: 错误ID
    """
    if _has_sanitizer:
        try:
            from core.utils.log_sanitizer import ErrorReporter
            
            # 在事件循环中报告
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 返回一个Future
                return loop.create_task(ErrorReporter.report_error(error, context, **kwargs))
            else:
                # 同步执行
                return loop.run_until_complete(ErrorReporter.report_error(error, context, **kwargs))
        except Exception as e:
            # 如果报告失败，至少记录错误
            default_logger.error(f"报告错误失败: {e}", exc_info=True)
            return ""
    else:
        import uuid as _uuid
        error_id = str(_uuid.uuid4())
        default_logger.error(f"错误: {str(error)}", exc_info=True, extra={'error_id': error_id}, **kwargs)
        return error_id

# 自动初始化
if _has_sanitizer:
    try:
        # 延迟初始化，避免导入循环
        import threading
        import time
        
        def delayed_init():
            time.sleep(0.1)  # 短暂延迟
            init_logging_system()
        
        # 启动后台线程进行初始化
        threading.Thread(target=delayed_init, daemon=True).start()
    except Exception:
        pass
