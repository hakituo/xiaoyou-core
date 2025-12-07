import logging
import sys
from .trace_context import TraceContext

import os

class TraceFormatter(logging.Formatter):
    """
    支持 Trace ID 的日志格式化器
    """
    def format(self, record):
        # 尝试从 record 中获取 trace_id (如果是显式传递的)
        # 否则从 ContextVar 中获取
        if not hasattr(record, 'trace_id'):
            record.trace_id = TraceContext.get_trace_id()
        return super().format(record)

def setup_logger(name: str = "mvp_core", level: int = logging.INFO, log_file: str = None) -> logging.Logger:
    """
    配置并获取 Logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 如果已经有 handler，就不再添加，避免重复日志
    if logger.handlers:
        return logger
        
    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    # 定义日志格式：时间 | 级别 | TraceID | 模块 | 消息
    fmt_str = '[%(asctime)s] [%(levelname)s] [TraceID:%(trace_id)s] [%(name)s] %(message)s'
    formatter = TraceFormatter(fmt_str, datefmt='%Y-%m-%d %H:%M:%S')
    
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File Handler (Optional)
    if log_file:
        try:
            # Ensure directory exists
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir)
                
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            print(f"Failed to setup file logging to {log_file}: {e}")
    
    return logger

# 预定义的全局 logger
logger = setup_logger()
