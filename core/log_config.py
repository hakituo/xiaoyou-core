import logging
import os
import sys
from datetime import datetime
import json
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from typing import Dict, Any, Optional
import threading
import traceback

# 确保日志目录存在
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# 日志级别映射
LOG_LEVEL_MAP = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'WARN': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}


class JsonFormatter(logging.Formatter):
    """
    JSON格式的日志格式化器
    """
    
    def __init__(self, include_stack_info: bool = True, **kwargs):
        super().__init__(**kwargs)
        self.include_stack_info = include_stack_info
    
    def format(self, record: logging.LogRecord) -> str:
        """
        将日志记录格式化为JSON字符串
        """
        # 基础日志数据
        log_data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'line': record.lineno,
            'function': record.funcName,
            'thread_id': record.thread,
            'thread_name': record.threadName
        }
        
        # 添加异常信息
        if record.exc_info:
            log_data['exception'] = {
                'type': record.exc_info[0].__name__ if record.exc_info[0] else 'Unknown',
                'message': str(record.exc_info[1]) if record.exc_info[1] else 'Unknown',
                'traceback': ''.join(traceback.format_exception(*record.exc_info)) if self.include_stack_info else None
            }
        
        # 添加额外的上下文信息
        if hasattr(record, 'context'):
            log_data['context'] = record.context
        
        # 添加请求相关信息（如果有）
        if hasattr(record, 'request_id'):
            log_data['request_id'] = record.request_id
        
        if hasattr(record, 'client_ip'):
            log_data['client_ip'] = record.client_ip
        
        if hasattr(record, 'user_id'):
            log_data['user_id'] = record.user_id
        
        return json.dumps(log_data, ensure_ascii=False)


class ColorConsoleFormatter(logging.Formatter):
    """
    带颜色的控制台日志格式化器
    """
    
    # ANSI颜色代码
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[35m',   # 紫色
        'RESET': '\033[0m'        # 重置
    }
    
    def __init__(self, include_thread_info: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.include_thread_info = include_thread_info
    
    def format(self, record: logging.LogRecord) -> str:
        """
        格式化日志记录，添加颜色
        """
        color = self.COLORS.get(record.levelname, '')
        reset = self.COLORS['RESET']
        
        # 基础格式
        if self.include_thread_info:
            base_format = f'{color}[%(asctime)s] [%(levelname)-8s] [%(name)s:%(lineno)d] [%(threadName)s] %(message)s{reset}'
        else:
            base_format = f'{color}[%(asctime)s] [%(levelname)-8s] [%(name)s:%(lineno)d] %(message)s{reset}'
        
        formatter = logging.Formatter(base_format, datefmt='%Y-%m-%d %H:%M:%S')
        result = formatter.format(record)
        
        # 添加异常信息
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            if record.exc_text:
                result = f'{result}\n{record.exc_text}'
        
        # 添加额外上下文
        if hasattr(record, 'context'):
            result = f'{result} | Context: {record.context}'
        
        return result


class LogManager:
    """
    日志管理器，负责配置和管理应用日志
    """
    
    _instance = None
    _lock = threading.RLock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """
        初始化日志管理器
        """
        if not hasattr(self, '_initialized'):
            with self._lock:
                if not hasattr(self, '_initialized'):
                    self.config = {}
                    self._initialized = True
    
    def configure(self, config: Dict[str, Any] = None):
        """
        配置日志系统
        """
        self.config = config or {}
        
        # 获取根日志级别
        root_level = LOG_LEVEL_MAP.get(
            self.config.get('level', 'INFO').upper(),
            logging.INFO
        )
        
        # 配置根日志记录器
        root_logger = logging.getLogger()
        root_logger.setLevel(root_level)
        
        # 清除现有处理器
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # 配置控制台日志
        if self.config.get('console', True):
            console_handler = self._create_console_handler()
            root_logger.addHandler(console_handler)
        
        # 配置文件日志
        if self.config.get('file', True):
            file_handlers = self._create_file_handlers()
            for handler in file_handlers:
                root_logger.addHandler(handler)
        
        # 配置其他特性
        self._configure_additional_features()
        
        logging.info("日志系统配置完成")
    
    def _create_console_handler(self) -> logging.Handler:
        """
        创建控制台日志处理器
        """
        handler = logging.StreamHandler(sys.stdout)
        
        # 设置日志级别
        console_level = LOG_LEVEL_MAP.get(
            self.config.get('console_level', 'INFO').upper(),
            logging.INFO
        )
        handler.setLevel(console_level)
        
        # 设置格式化器
        if self.config.get('console_json', False):
            formatter = JsonFormatter()
        else:
            formatter = ColorConsoleFormatter(
                include_thread_info=self.config.get('console_thread_info', False)
            )
        
        handler.setFormatter(formatter)
        return handler
    
    def _create_file_handlers(self) -> list[logging.Handler]:
        """
        创建文件日志处理器
        """
        handlers = []
        
        # 获取文件日志配置
        file_config = self.config.get('file_config', {})
        
        # 1. 主日志文件
        main_log_file = os.path.join(LOG_DIR, file_config.get('filename', 'app.log'))
        
        # 确定轮换策略
        rotation_type = file_config.get('rotation', 'size')  # size 或 time
        
        if rotation_type == 'size':
            # 基于大小的日志轮转
            max_bytes = file_config.get('max_bytes', 10 * 1024 * 1024)  # 默认10MB
            backup_count = file_config.get('backup_count', 5)
            
            handler = RotatingFileHandler(
                main_log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
        else:
            # 基于时间的日志轮转
            when = file_config.get('when', 'midnight')  # S, M, H, D, W0-W6, midnight
            interval = file_config.get('interval', 1)
            backup_count = file_config.get('backup_count', 7)
            
            handler = TimedRotatingFileHandler(
                main_log_file,
                when=when,
                interval=interval,
                backupCount=backup_count,
                encoding='utf-8'
            )
        
        # 设置日志级别
        file_level = LOG_LEVEL_MAP.get(
            file_config.get('level', 'INFO').upper(),
            logging.INFO
        )
        handler.setLevel(file_level)
        
        # 设置格式化器
        if self.config.get('file_json', True):
            formatter = JsonFormatter()
        else:
            formatter = logging.Formatter(
                '[%(asctime)s] [%(levelname)-8s] [%(name)s:%(lineno)d] [%(threadName)s] %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        
        handler.setFormatter(formatter)
        handlers.append(handler)
        
        # 2. 错误日志文件（可选）
        if file_config.get('separate_error_log', True):
            error_log_file = os.path.join(LOG_DIR, file_config.get('error_filename', 'error.log'))
            
            if rotation_type == 'size':
                error_handler = RotatingFileHandler(
                    error_log_file,
                    maxBytes=file_config.get('error_max_bytes', 5 * 1024 * 1024),  # 默认5MB
                    backupCount=file_config.get('error_backup_count', 5),
                    encoding='utf-8'
                )
            else:
                error_handler = TimedRotatingFileHandler(
                    error_log_file,
                    when=when,
                    interval=interval,
                    backupCount=backup_count,
                    encoding='utf-8'
                )
            
            # 只记录错误及以上级别的日志
            error_handler.setLevel(logging.ERROR)
            error_handler.setFormatter(JsonFormatter() if self.config.get('file_json', True) else formatter)
            handlers.append(error_handler)
        
        return handlers
    
    def _configure_additional_features(self):
        """
        配置其他日志特性
        """
        # 配置特定模块的日志级别
        module_levels = self.config.get('module_levels', {})
        for module_name, level in module_levels.items():
            module_logger = logging.getLogger(module_name)
            module_logger.setLevel(LOG_LEVEL_MAP.get(level.upper(), logging.INFO))
        
        # 配置禁用的日志器
        disabled_loggers = self.config.get('disabled_loggers', [])
        for logger_name in disabled_loggers:
            logger = logging.getLogger(logger_name)
            logger.disabled = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    获取日志记录器实例
    """
    return logging.getLogger(name)


def initialize_logging(config: Dict[str, Any] = None):
    """
    初始化日志系统
    """
    manager = LogManager()
    manager.configure(config)
    
    # 返回根日志记录器，方便立即使用
    return get_logger()


def log_with_context(logger: logging.Logger, level: int, message: str, **context):
    """
    记录带上下文信息的日志
    """
    extra = {'context': context}
    logger.log(level, message, extra=extra)


def log_request(logger: logging.Logger, request, response = None, error = None):
    """
    记录HTTP请求日志
    """
    context = {
        'method': request.method,
        'url': str(request.url),
        'client_ip': request.client.host if request.client else 'unknown',
    }
    
    if hasattr(request, 'headers'):
        # 记录关键头部，但不记录敏感信息
        safe_headers = {}
        for key, value in request.headers.items():
            if key.lower() not in ['authorization', 'cookie']:
                safe_headers[key] = value
        context['headers'] = safe_headers
    
    if response:
        context['status_code'] = response.status_code
        context['response_size'] = len(response.body) if hasattr(response, 'body') else 0
    
    if error:
        context['error'] = str(error)
        logger.error(f"请求处理失败: {request.method} {request.url.path}", extra={'context': context})
    else:
        logger.info(f"请求处理: {request.method} {request.url.path} {response.status_code if response else 'N/A'}", 
                   extra={'context': context})


# 创建默认的日志管理器实例
log_manager = LogManager()