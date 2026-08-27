"""日志系统统一入口（编排层）。

本模块只负责「创建 logger 实例 + 对外公开 API」，所有实现已拆分到
``core.utils.logging`` 子包：

- ``logging.handlers``    : 安全/跨天文件 Handler 实现
- ``logging.formatters``  : 日志格式化器
- ``logging.config``      : 配置加载与按日目录解析
- ``logging.context``     : request_id 上下文
- ``logging.registry``    : Handler 注册中心 + QueueListener 运行时管理（状态中枢）

为保持向后兼容，所有外部 ``from core.utils.logger import get_logger`` 等
导入均在此 re-export，无需改动调用方。
"""
import logging
import threading
from typing import Dict, Any, Optional

import colorama

# 初始化 colorama（Windows 下把 ANSI 转义翻译成 Win32 调用，autoreset 自动复位颜色）
colorama.init(autoreset=True)

from core.utils.logging.config import (
    get_log_config,
    _resolve_daily_log_dir,
    ensure_log_dir,
    _get_settings,
)
from core.utils.logging.context import (
    get_request_id,
    set_request_id,
    _request_context_local,
)
from core.utils.logging.formatters import (
    SanitizingFormatter,
    ColoredFormatter,
    JSONFormatter,
)
from core.utils.logging.handlers import (
    _SafeRotatingFileHandler,
    _SafeTimedRotatingFileHandler,
    _CrossDayFileHandlerMixin,
    _CrossDayRotatingFileHandler,
    _CrossDayTimedRotatingFileHandler,
    _report_rotation_failure,
)
from core.utils.logging.registry import (
    _log_queue,
    _file_handlers,
    _module_file_handlers,
    _console_handler,
    _heartbeat_handler,
    _auto_heal_handler,
    _is_queue_listener_alive,
    _restart_queue_listener,
    _stop_queue_listener,
    _setup_handlers,
    _get_queue_listener,
    _start_listener_monitor,
    _stop_listener_monitor,
    _monitor_queue_listener,
    SafeQueueHandler,
    HeartbeatHandler,
    AutoHealErrorHandler,
    register_module_file_handler,
)


# 抑制 PyTorch Triton 警告 (Windows 下不适用且影响观感)
logging.getLogger("torch.utils.flop_counter").setLevel(logging.ERROR)

# 格式化递归保护
_formatting_local = threading.local()

# logger 实例缓存
_loggers: Dict[str, logging.Logger] = {}
# 用 RLock：初始化期（模块级 get_logger -> config -> core.utils.common ->
# 递归 get_logger）同一线程会重入，普通 Lock 会死锁
_loggers_lock = threading.RLock()


# ===================== 脱敏包装 =====================
try:
    from core.utils.errors.log_sanitizer import sanitize_log, initialize_sanitizer

    _has_sanitizer = True
except ImportError:
    _has_sanitizer = False

    def sanitize_log(message, logger_name=""):
        return message

    async def initialize_sanitizer():
        pass


# ===================== logger 实例创建 =====================
def get_logger(name: str) -> logging.Logger:
    """获取或创建一个命名的日志记录器 (异步)"""
    with _loggers_lock:
        if name in _loggers:
            return _loggers[name]
        logger = logging.getLogger(name)
        # 从配置获取日志级别
        log_config = get_log_config()
        log_level = getattr(logging, log_config["log_level"], logging.INFO)
        logger.setLevel(log_level)
        logger.propagate = False  # 防止重复记录

        # 增强的异常日志记录
        def enhanced_error(msg, *args, **kwargs):
            exc_info = kwargs.get("exc_info", False)
            error_id = kwargs.pop("error_id", None)

            # 创建一个记录对象
            record = logger.makeRecord(
                logger.name,
                logging.ERROR,
                "",  # pathname
                0,  # lineno
                msg,
                args,
                exc_info if exc_info else None,
                func=None,
                sinfo=None,
                **kwargs,
            )

            # 添加错误ID
            if error_id:
                record.error_id = error_id

            logger.handle(record)

        # 增强的警告日志记录
        def enhanced_warning(msg, *args, **kwargs):
            record = logger.makeRecord(
                logger.name,
                logging.WARNING,
                "",  # pathname
                0,  # lineno
                msg,
                args,
                None,  # exc_info
                func=None,
                sinfo=None,
                **kwargs,
            )
            logger.handle(record)

        # 添加增强方法
        logger.enhanced_error = enhanced_error
        logger.enhanced_warning = enhanced_warning

        # 移除已存在的处理器
        if logger.handlers:
            logger.handlers.clear()

        # 使用 QueueHandler 实现异步
        queue_handler = SafeQueueHandler(_log_queue)
        logger.addHandler(queue_handler)

        # 添加 AutoHeal 错误捕获 handler
        if _auto_heal_handler is not None:
            logger.addHandler(_auto_heal_handler)

        if not _is_queue_listener_alive():
            _restart_queue_listener()

        _loggers[name] = logger
        return logger


def get_module_logger(name: str, module_file: str) -> logging.Logger:
    """
    获取或创建一个模块专用日志记录器，同时写入主日志和模块独立日志文件。

    Args:
        name: logger 名称（如 "ACTIVE_CARE_MSG"）
        module_file: 模块独立日志文件名（如 "active_care_messages.log"）

    Returns:
        logging.Logger: 配置好的 logger，日志同时写入主日志和模块独立文件
    """
    logger = get_logger(name)
    registered = register_module_file_handler(module_file, logger_name=name)
    # register_module_file_handler 返回 None 表示已存在或注册失败，无需额外处理
    _ = registered
    return logger


# ===================== 便捷 API =====================
# get_request_id / set_request_id 已在顶部从 context 模块 re-export


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
    """初始化日志系统，包括脱敏功能和根日志记录器配置"""
    try:
        # 配置根日志记录器，确保所有第三方库和未显式获取的 logger 也使用统一格式
        root_logger = logging.getLogger()

        # 清除已有的 basicConfig 处理器，避免格式冲突
        for h in root_logger.handlers[:]:
            root_logger.removeHandler(h)

        if _console_handler:
            root_logger.addHandler(_console_handler)
            root_logger.setLevel(logging.INFO)

        loop = None
        try:
            loop = __import__("asyncio").get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(initialize_sanitizer())
            default_logger.info("日志脱敏系统初始化完成")
            return

        default_logger.info("日志脱敏系统初始化已延迟（等待应用事件循环启动后接管）")
    except Exception as e:
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
            from core.utils.errors.log_sanitizer import ErrorReporter, _spawn_error_report

            # P1-1: 使用 asyncio.get_running_loop() 替代 get_event_loop().is_running()
            # 在事件循环运行时调度报告，否则跳过（避免 Python 3.10+ 弃用警告）
            try:
                __import__("asyncio").get_running_loop()
                # P1-2: 保存任务引用避免被 GC，复用 log_sanitizer 的 tracker
                # 不再返回 task（调用方一般丢弃返回值，依赖 tracker 兜底异常）
                _spawn_error_report(ErrorReporter.report_error(error, context, **kwargs))
                return ""
            except RuntimeError:
                # 无运行的事件循环，直接记录错误，不再 fallback 到 run_until_complete
                default_logger.error(
                    f"无法报告错误（无运行事件循环）: {error}", exc_info=False
                )
                return ""
        except Exception as e:
            # 如果报告失败，至少记录错误
            default_logger.error(f"报告错误失败: {e}", exc_info=True)
            return ""
    else:
        import uuid as _uuid

        error_id = str(_uuid.uuid4())
        default_logger.error(
            f"错误: {str(error)}", exc_info=True, extra={"error_id": error_id}, **kwargs
        )
        return error_id


# ===================== 运行时可变状态代理 =====================
# ``_queue_listener`` 等变量由 registry 在运行时重赋（QueueListener 重启）。
# 若直接 ``from core.utils.logger import _queue_listener``（值拷贝）会在重启后失效。
# 这里把 logger 模块替换为自定义模块类，让 ``_queue_listener`` 作为属性实时转发到
# registry，确保任何访问都拿到最新对象（兼容 error_collector 等既有调用方）。
import sys as _sys

_orig_logger_module = _sys.modules[__name__]


class _LoggerModule(_orig_logger_module.__class__):
    @property
    def _queue_listener(self):
        from core.utils.logging import registry
        return registry._queue_listener


# 替换为代理模块实例时必须保留原模块的全部属性（get_logger 等），
# 否则 ``from core.utils.logger import get_logger`` 会失败。
_logger_module = _LoggerModule(__name__)
_logger_module.__dict__.update(_orig_logger_module.__dict__)
_sys.modules[__name__] = _logger_module
