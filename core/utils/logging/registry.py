"""日志 Handler 注册中心 + QueueListener 运行时管理。

集中持有所有运行时可变状态（文件 handler 缓存、QueueListener 实例、监听器
监控线程等），并负责：
- ``_setup_handlers``：创建 console / main file / 特殊 handler 并组装 QueueListener
- QueueListener 的存活监控、重启、停止
- HeartbeatHandler / AutoHealErrorHandler / SafeQueueHandler 等特殊 handler

与纯逻辑模块（handlers / formatters / config）解耦，是 logger 子包的状态中枢。
"""
import atexit
import logging
import os
import re
import threading
import time
import traceback
from logging.handlers import QueueListener, QueueHandler

import colorama

from core.utils.logging.config import get_log_config
from core.utils.logging.formatters import (
    ColoredFormatter,
    JSONFormatter,
    SanitizingFormatter,
)
from core.utils.logging.handlers import (
    _CrossDayRotatingFileHandler,
    _CrossDayTimedRotatingFileHandler,
)


# ===================== 运行时可变状态 =====================
# 全局日志队列和监听器
_log_queue = __import__("queue").Queue(-1)  # 无界队列
_queue_listener = None
_listener_monitor_stop = threading.Event()
_listener_monitor_thread = None
_listener_monitor_lock = threading.RLock()
_listener_restart_lock = threading.RLock()
_listener_last_emit = 0.0
_listener_last_restart = 0.0
_listener_last_qsize = 0
_atexit_registered = False

# 全局文件 Handler 缓存 (避免重复创建)
_file_handlers = {}
_module_file_handlers = {}
_module_file_filters = {}
_module_file_handlers_lock = threading.Lock()
_section_file_handlers = {}
_console_handler = None
_heartbeat_handler = None
_auto_heal_handler = None


class ModuleLoggerNameFilter(logging.Filter):
    """仅允许登记过的 logger 写入指定模块日志文件。"""

    def __init__(self, logger_names=None):
        super().__init__()
        self._logger_names = set(logger_names or [])
        self._lock = threading.RLock()

    def add_logger_name(self, logger_name: str) -> None:
        """为共享同一文件的模块补充 logger 名称。"""
        name = str(logger_name or "").strip()
        if not name:
            return
        with self._lock:
            self._logger_names.add(name)

    def filter(self, record: logging.LogRecord) -> bool:
        with self._lock:
            return record.name in self._logger_names


_LOG_SECTIONS = (
    ("active_care", "01_active_care.log", "主动关怀、互聊、提醒与状态机"),
    ("conversation", "02_conversation.log", "用户消息、回复生成与会话分发"),
    ("health_daily", "03_health_daily.log", "健康同步、作息、日记、学习与生活数据"),
    ("llm_media", "04_llm_media.log", "LLM、工具、记忆、图像与语音"),
    ("scheduler_runtime", "05_scheduler_runtime.log", "调度、心跳、资源、启停与运行时"),
    ("integrations", "06_integrations.log", "QQ、Telegram、WebSocket、设备与外部连接"),
    ("other", "07_other.log", "未归类的其他模块"),
)

_IMPORTANT_INFO_PATTERN = re.compile(
    r"(?:接收\s*<-|发送\s*->|消息分发完成|主动消息已实时送达|"
    r"已发送.*消息|手表检测到起床|同步健康起床时间|"
    r"启动完成|已启动|已停止|关闭完成)"
)


def classify_log_section(logger_name: str) -> str:
    """根据 logger 名称将记录归入唯一板块。"""
    name = str(logger_name or "").lower()
    if any(
        token in name
        for token in (
            "active_care",
            "peer_chat",
            "state_manager",
            "mode_state",
            "focus_state",
            "sleep_state",
            "schedule_adapter",
            "reminder_injection",
            "gate_scorer",
        )
    ):
        return "active_care"
    if any(
        token in name
        for token in (
            "aveline_service",
            "chat_history",
            "conversation",
            "response_generator",
            "stream_orchestrator",
            "chat_reply",
        )
    ):
        return "conversation"
    if any(
        token in name
        for token in (
            "health",
            "daily_manager",
            "daily_tool",
            "activity_extractor",
            "journal",
            "study",
            "life_simulation",
            "nutrition",
            "workspace",
        )
    ):
        return "health_daily"
    if any(
        token in name
        for token in (
            "llm",
            "openai",
            "model_loader",
            "memory",
            "image",
            "vision",
            "tts",
            "stt",
            "voice",
            "tool_",
        )
    ):
        return "llm_media"
    if any(
        token in name
        for token in (
            "scheduler",
            "heartbeat",
            "lifecycle",
            "resource",
            "async_",
            "config",
            "server",
            "monitor",
        )
    ):
        return "scheduler_runtime"
    if any(
        token in name
        for token in (
            "qq",
            "telegram",
            "websocket",
            "device",
            "discovery",
            "client",
        )
    ):
        return "integrations"
    return "other"


class LogSectionFilter(logging.Filter):
    """仅保留属于指定板块的记录。"""

    def __init__(self, section: str):
        super().__init__()
        self.section = section

    def filter(self, record: logging.LogRecord) -> bool:
        return classify_log_section(record.name) == self.section


class ImportantLogFilter(logging.Filter):
    """保留警告/错误和少量用户可感知的关键事件。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        return bool(_IMPORTANT_INFO_PATTERN.search(record.getMessage()))


def _write_daily_log_index(log_dir_path: str) -> None:
    """写入当日日志导航，让排查时先看重要摘要再进板块。"""
    lines = [
        "# 小悠日志导航",
        "",
        "1. `important.log`：警告、错误和用户可感知的关键事件。",
        "2. `sections/`：按功能板块拆分的详细日志。",
        "3. `xiaoyou_main.log`：完整聚合日志，仅在需要跨板块追踪时查看。",
        "",
        "## 板块",
        "",
    ]
    lines.extend(
        f"- `sections/{file_name}`：{description}"
        for _, file_name, description in _LOG_SECTIONS
    )
    content = "\n".join(lines).rstrip() + "\n"
    index_path = os.path.join(log_dir_path, "README.md")
    try:
        current = ""
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as file:
                current = file.read()
        if current != content:
            with open(index_path, "w", encoding="utf-8", newline="\n") as file:
                file.write(content)
    except OSError:
        pass


# ===================== QueueListener 管理 =====================
def _get_listener_thread(listener):
    if listener is None:
        return None
    thread = getattr(listener, "_thread", None)
    if thread is None:
        thread = getattr(listener, "thread", None)
    return thread


def _is_queue_listener_alive() -> bool:
    thread = _get_listener_thread(_queue_listener)
    if thread is None:
        return False
    return thread.is_alive()


def _restart_queue_listener():
    global _queue_listener, _listener_last_restart
    with _listener_restart_lock:
        old_listener = _queue_listener
        if old_listener:
            try:
                old_listener.stop()
            except Exception:
                pass
        kept_records = []
        while True:
            try:
                item = _log_queue.get_nowait()
            except Exception:
                break
            if isinstance(item, logging.LogRecord):
                kept_records.append(item)
        for item in kept_records:
            try:
                _log_queue.put_nowait(item)
            except Exception:
                break
        _queue_listener = None
        _listener_last_restart = time.time()
        _setup_handlers()


def _monitor_queue_listener():
    while not _listener_monitor_stop.is_set():
        try:
            now = time.time()
            if not _is_queue_listener_alive():
                _restart_queue_listener()
            else:
                queue_size = 0
                try:
                    queue_size = _log_queue.qsize()
                except Exception:
                    queue_size = 0
                stall_seconds = 6.0
                if queue_size > 0 and now - _listener_last_restart > 3.0:
                    last_emit = _listener_last_emit
                    if last_emit == 0.0 or now - last_emit > stall_seconds:
                        _restart_queue_listener()
        except Exception:
            pass
        _listener_monitor_stop.wait(3.0)


def _start_listener_monitor():
    global _listener_monitor_thread
    with _listener_monitor_lock:
        if _listener_monitor_thread and _listener_monitor_thread.is_alive():
            return
        _listener_monitor_stop.clear()
        _listener_monitor_thread = threading.Thread(
            target=_monitor_queue_listener,
            name="LogListenerMonitor",
            daemon=True,
        )
        _listener_monitor_thread.start()


def _stop_listener_monitor():
    _listener_monitor_stop.set()
    thread = _listener_monitor_thread
    if thread and thread.is_alive():
        thread.join(timeout=2.0)


def _stop_queue_listener():
    listener = _queue_listener
    if listener:
        try:
            listener.stop()
        except Exception:
            pass


def _get_queue_listener():
    if _queue_listener is None:
        # 此时 handler 还没完全加进去，需要在 get_logger 里动态管理，或者在这里预设一个空的
        # 由于 QueueListener 需要 handlers 列表，我们推迟初始化
        pass
    return _queue_listener


# ===================== 特殊 Handler =====================
class HeartbeatHandler(logging.Handler):
    def emit(self, record):
        global _listener_last_emit, _listener_last_qsize
        _listener_last_emit = time.time()
        try:
            _listener_last_qsize = _log_queue.qsize()
        except Exception:
            pass


class AutoHealErrorHandler(logging.Handler):
    """将 ERROR 及以上级别的日志转发给 auto_heal 的 AnomalyDetector

    P1-3: 不再直接 import core.services.auto_heal.heal_service（utils 反向依赖 services）。
    改为通过 core.utils.log_sanitizer.dispatch_error_to_callbacks 派发，
    由 services 层在初始化时调用 register_error_callback 注册自身回调。
    """

    def emit(self, record):
        if record.levelno < logging.ERROR:
            return
        try:
            from core.utils.errors.log_sanitizer import dispatch_error_to_callbacks
            error_type = getattr(record, "error_type", None) or record.name or "UnknownError"
            error_message = record.getMessage()
            traceback_str = ""
            if record.exc_info and record.exc_info[0] is not None:
                traceback_str = "".join(traceback.format_exception(*record.exc_info))
            context = {}
            if hasattr(record, "error_id"):
                context["error_id"] = record.error_id
            error_report = {
                "error_type": error_type,
                "error_message": error_message[:500],
                "traceback": traceback_str[:3000],
                "context": context,
                "logger_name": record.name,
                "source_file": getattr(record, "pathname", ""),
                "source_line": getattr(record, "lineno", 0),
                "source_func": getattr(record, "funcName", ""),
            }
            error_id = getattr(record, "error_id", None) or f"log_{record.name}_{int(time.time())}"
            dispatch_error_to_callbacks(error_id, error_report)
        except Exception:
            pass


class SafeQueueHandler(QueueHandler):
    def emit(self, record):
        if not _is_queue_listener_alive():
            _restart_queue_listener()
        super().emit(record)


# ===================== Handler 组装 =====================
def _create_routed_file_handler(file_path: str, log_cfg: dict):
    """按统一轮转与格式创建文件 handler。"""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    if log_cfg.get("rotation_type") == "time":
        handler = _CrossDayTimedRotatingFileHandler(
            file_path,
            when=log_cfg["rotation_when"],
            interval=log_cfg["rotation_interval"],
            backupCount=log_cfg["backup_count"],
            encoding="utf-8",
        )
    else:
        handler = _CrossDayRotatingFileHandler(
            file_path,
            maxBytes=log_cfg["max_bytes"],
            backupCount=log_cfg["backup_count"],
            encoding="utf-8",
        )
    if log_cfg["use_json"]:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            SanitizingFormatter(
                "[%(asctime)s][%(levelname)s][%(name)s] %(message)s",
                "%Y-%m-%d %H:%M:%S",
            )
        )
    daily_log_dir = os.path.abspath(log_cfg["log_dir"])
    log_root = daily_log_dir
    for _ in range(3):
        log_root = os.path.dirname(log_root)
    handler._daily_log_root = log_root
    handler._daily_relative_path = os.path.relpath(file_path, daily_log_dir)
    handler._daily_index_writer = _write_daily_log_index
    return handler


def _ensure_section_handlers(log_dir_path: str, log_cfg: dict) -> None:
    """创建重要摘要与功能板块 handlers。"""
    if "important" not in _section_file_handlers:
        important_handler = _create_routed_file_handler(
            os.path.join(log_dir_path, "important.log"), log_cfg
        )
        important_handler.addFilter(ImportantLogFilter())
        _section_file_handlers["important"] = important_handler

    for section, file_name, _ in _LOG_SECTIONS:
        if section in _section_file_handlers:
            continue
        handler = _create_routed_file_handler(
            os.path.join(log_dir_path, "sections", file_name), log_cfg
        )
        handler.addFilter(LogSectionFilter(section))
        _section_file_handlers[section] = handler

    _write_daily_log_index(log_dir_path)


def _setup_handlers():
    """初始化全局 Handlers"""
    global \
        _console_handler, \
        _file_handlers, \
        _queue_listener, \
        _heartbeat_handler, \
        _auto_heal_handler, \
        _atexit_registered

    # 延迟获取日志配置
    log_cfg = get_log_config()
    log_dir_path = log_cfg["log_dir"]
    os.makedirs(log_dir_path, exist_ok=True)

    handlers = []

    # Console Handler
    if _console_handler is None:
        _console_handler = logging.StreamHandler()
        # Console formatter needs color
        # 注意：QueueListener 里的 handler 会收到 LogRecord，需要再次 format
        # 但 StreamHandler 默认会 format。
        # 这里的 trick 是：QueueHandler 只是传递 record。
        # 真正的 formatting 发生在 Listener 调用的 handlers 里。
        console_formatter = ColoredFormatter(
            f"[{colorama.Fore.CYAN}%(asctime)s{colorama.Style.RESET_ALL}] [%(levelname)-5s] [{colorama.Fore.MAGENTA}%(name)s{colorama.Style.RESET_ALL}] %(message)s",
            "%H:%M:%S",
        )
        _console_handler.setFormatter(console_formatter)
        console_level_name = str(log_cfg.get("console_level", "WARNING")).upper()
        _console_handler.setLevel(getattr(logging, console_level_name, logging.WARNING))

    if _heartbeat_handler is None:
        _heartbeat_handler = HeartbeatHandler()
    handlers.append(_heartbeat_handler)
    handlers.append(_console_handler)

    # AutoHeal 错误捕获 handler（不加入 QueueListener，直接独立工作）
    if _auto_heal_handler is None:
        _auto_heal_handler = AutoHealErrorHandler()
        _auto_heal_handler.setLevel(logging.ERROR)

    # 我们为每个 logger name 创建单独的 file handler 是比较昂贵的，且 QueueListener 通常处理一组固定的 handlers。
    # 为了简化异步日志，我们创建一个主日志文件 'xiaoyou_core.log' 包含所有，
    # 或者我们动态维护 Listener。动态维护 Listener 比较复杂。
    # 策略：
    # 1. 所有的 logger 都使用 QueueHandler。
    # 2. QueueListener 后面接一个 ConsoleHandler 和一个 Main FileHandler。
    # 3. 如果需要按模块分文件，可以在 Listener 后接一个 DispatchingHandler (复杂)。
    #
    # 鉴于当前架构是每个 logger 一个文件 (logger.name.log)，这在异步下比较难搞。
    # 妥协方案：只对主 'xiaoyou_core' 和关键 logger 启用异步，或者让所有日志都打到一个主文件 + 控制台。
    #
    # 现在的代码逻辑是 `log_file = os.path.join(log_dir, f"{name.lower().replace('.', '_')}.log")`
    # 这意味着 logger 越多，文件句柄越多。
    #
    # 为了实现 P1 异步日志优化，我将创建一个统一的 FileHandler 处理所有日志，不再分文件。
    # 这样大大减少 IO 和句柄数。

    main_log_file = os.path.join(log_dir_path, "xiaoyou_main.log")
    if "main" not in _file_handlers:
        try:
            if log_cfg.get("rotation_type") == "time":
                fh = _CrossDayTimedRotatingFileHandler(
                    main_log_file,
                    when=log_cfg["rotation_when"],
                    interval=log_cfg["rotation_interval"],
                    backupCount=log_cfg["backup_count"],
                    encoding="utf-8",
                )
            else:
                fh = _CrossDayRotatingFileHandler(
                    main_log_file,
                    maxBytes=log_cfg["max_bytes"],
                    backupCount=log_cfg["backup_count"],
                    encoding="utf-8",
                )

            if log_cfg["use_json"]:
                fh.setFormatter(JSONFormatter())
            else:
                fh.setFormatter(
                    SanitizingFormatter(
                        "[%(asctime)s][%(levelname)s][%(name)s] %(message)s",
                        "%Y-%m-%d %H:%M:%S",
                    )
                )
            _file_handlers["main"] = fh
        except Exception as e:
            print(f"Failed to create main log handler: {e}")

    if "main" in _file_handlers:
        handlers.append(_file_handlers["main"])

    # 保留完整聚合日志作为审计入口，同时生成重要摘要和板块日志。
    try:
        _ensure_section_handlers(log_dir_path, log_cfg)
        handlers.extend(_section_file_handlers.values())
    except Exception as e:
        print(f"Failed to create section log handlers: {e}")

    if _queue_listener is None:
        # 收集 get_module_logger 动态注册的独立模块日志 handler。
        # 注意：_module_file_handlers 定义在本函数之后，首次调用时尚未存在，
        # 因此用 globals().get 保证安全；QueueListener 每次重建（如 _restart_queue_listener）
        # 都必须保留这些 fh，否则模块日志（active_care_*.log 等）会集体停止写入。
        all_handlers = list(handlers)
        all_handlers.extend(globals().get("_module_file_handlers", {}).values())
        _queue_listener = QueueListener(
            _log_queue, *all_handlers, respect_handler_level=True
        )
        _queue_listener.start()

        # 注册 atexit 处理器
        if not _atexit_registered:
            try:
                atexit.register(_stop_queue_listener)
                atexit.register(_stop_listener_monitor)
                _atexit_registered = True
            except Exception:
                pass

    # 启动监听器监控线程
    _start_listener_monitor()


def register_module_file_handler(
    module_file: str,
    logger_name: str = "",
) -> "logging.FileHandler | None":
    """创建（若尚未创建）模块独立日志文件 handler，返回 handler 或 None。

    由 get_module_logger 调用；handler 缓存进 _module_file_handlers，
    并在下一次 _setup_handlers 组装 QueueListener 时并入。
    """
    with _module_file_handlers_lock:
        cache_key = module_file
        if cache_key in _module_file_handlers:
            module_filter = _module_file_filters.get(cache_key)
            if module_filter is not None:
                module_filter.add_logger_name(logger_name)
            return None
        log_config = get_log_config()
        log_dir = log_config.get("log_dir", "logs")
        module_log_path = os.path.join(log_dir, module_file)
        try:
            os.makedirs(os.path.dirname(module_log_path), exist_ok=True)
            if log_config.get("rotation_type") == "time":
                fh = _CrossDayTimedRotatingFileHandler(
                    module_log_path,
                    when=log_config.get("rotation_when", "midnight"),
                    interval=int(log_config.get("rotation_interval", 1)),
                    backupCount=int(log_config.get("backup_count", 5)),
                    encoding="utf-8",
                )
            else:
                fh = _CrossDayRotatingFileHandler(
                    module_log_path,
                    maxBytes=int(log_config.get("max_bytes", 10 * 1024 * 1024)),
                    backupCount=int(log_config.get("backup_count", 5)),
                    encoding="utf-8",
                )
            if log_config.get("use_json"):
                fh.setFormatter(JSONFormatter())
            else:
                fh.setFormatter(
                    SanitizingFormatter(
                        "[%(asctime)s][%(levelname)s][%(name)s] %(message)s",
                        "%Y-%m-%d %H:%M:%S",
                    )
                )
            module_filter = ModuleLoggerNameFilter([logger_name] if logger_name else [])
            fh.addFilter(module_filter)
            _module_file_filters[cache_key] = module_filter
            _module_file_handlers[cache_key] = fh
            if _queue_listener is not None:
                try:
                    _queue_listener.handlers = _queue_listener.handlers + (fh,)
                except Exception:
                    # 极少数运行时不允许替换 listener.handlers，退回根 logger。
                    # handler 自带名称过滤器，不会重新造成模块日志广播。
                    logging.getLogger().addHandler(fh)
            return fh
        except Exception as e:
            print(f"Failed to create module log handler for {module_file}: {e}")
            return None
