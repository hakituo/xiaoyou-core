#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
错误收集器模块

捕获所有 ERROR 及以上级别的日志，按错误性质分流写入不同目录：
1. 上游瞬时错误（503/429/网络抖动等） → logs/upstream_errors/upstream_errors_YYYYMMDD.json
2. 真正的后端代码错误 → 根目录 errors_YYYYMMDD.json（用户关注）
3. 异步转发给 ErrorReporter（写入 logs/errors/ 批次文件，保留原有行为）

设计要点：
- 通过附加到 QueueListener.handlers 实现，无需修改 logger.py
- 排除日志基础设施自身的 logger（LOG_SANITIZER 等）避免递归
- global_exception_handler 通过 extra={"_skip_collector": True} 标记已直接报告的错误
- 上游错误判定基于错误消息关键词 + HTTP 状态码 + traceback 为空组合特征
"""

import asyncio
import json
import logging
import re
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.utils.time.time_utils import now_str

# 排除的 logger 名称（这些 logger 的 ERROR 不收集，避免递归和噪音）
_EXCLUDED_LOGGERS = (
    "LOG_SANITIZER",        # 错误上报系统自身，避免递归
    "_rotation_failure",    # 日志轮转失败记录器
    "uvicorn.error",        # WebSocket 断连等噪音（data transfer failed）
    "uvicorn.access",       # 访问日志
)

# 主事件循环引用（install() 时捕获，供 handler 跨线程调度协程）
_main_event_loop: Optional[asyncio.AbstractEventLoop] = None

# 每日根目录文件写入锁（QueueListener 单线程，但保险起见加锁）
_daily_file_lock = threading.Lock()

# 模块自身日志（不通过 get_logger，避免循环导入）
_logger = logging.getLogger("ERROR_COLLECTOR")


# ============================================================
# 上游瞬时错误判定规则
# ============================================================
# 命中任一条件即归类为"上游瞬时错误"，不写到根目录 errors_*.json
# 判定优先级与说明：
# 1. HTTP 状态码 408/409/425/429/502/503/504 等可重试状态
# 2. 错误消息包含常见上游故障关键词（timeout/too busy/overloaded/rate limit/reset/...）
# 3. 已知供应商专属错误码（SiliconFlow code=50508、DeepSeek 余额/限流、通用 402 余额等）
# 4. traceback 为空（非 Python 异常栈，仅远程 API 返回错误）+ 命中 LLM 客户端 logger 白名单
# ============================================================

# 上游瞬时错误的 HTTP 状态码（按行业惯例可重试的状态）
_UPSTREAM_TRANSIENT_HTTP_CODES = {408, 409, 425, 429, 500, 502, 503, 504, 507, 508, 509, 520, 521, 522, 523, 524, 525, 526, 527, 529, 530, 598, 599}

# 上游瞬时错误消息关键词（子串匹配，忽略大小写）
_UPSTREAM_TRANSIENT_KEYWORDS = (
    # 服务繁忙 / 过载 / 限流
    "too busy",
    "system is too busy",
    "service is too busy",
    "service unavailable",
    "rate limit",
    "ratelimit",
    "rate_limit",
    "too many requests",
    "overloaded",
    "overload",
    "quota exceeded",
    # 超时 / 连接中断
    "read timeout",
    "connection timeout",
    "request timeout",
    "timed out",
    "timeout",
    "connection reset",
    "connection refused",
    "connection aborted",
    "broken pipe",
    "eof occurred",
    "temporary failure in name resolution",
    "network is unreachable",
    "host is unreachable",
    "no route to host",
    # 代理 / 网关层
    "bad gateway",
    "gateway timeout",
    "upstream request timeout",
    "upstream connect error",
    "502 bad gateway",
    "504 gateway timeout",
    # 通用重试建议
    "please try again later",
    "try again later",
    "retry later",
    "internal server error",
    # 空返回（已由上游调用方兜底）
    "stream request failed",
    "request failed",
    # 余额 / 配额（非代码问题，属于运维侧）
    "insufficient balance",
    "balance is not enough",
    "402 payment required",
)

# 上游瞬时错误的供应商专有错误码（按 JSON body 中 code 字段判定）
_UPSTREAM_VENDOR_ERROR_CODES = (
    # SiliconFlow 限流 / 繁忙
    "50508",   # System is too busy now
    "50503",   # Service unavailable
    # 通用余额
    "20014",   # Balance insufficient (部分供应商)
    # 通用限流
    "42900",   # Too many requests (兼容)
)

# 已知属于"纯代理上游调用"的 logger 名称（这些 logger 的空 traceback 错误全部视为上游）
_UPSTREAM_ONLY_LOGGERS = (
    "siliconflow_client",
    "openai_client",
    "deepseek_client",
    "dashscope_client",
    "minimax_client",
    "ark_client",
    "zhipu_client",
    "llm",       # CloudRouterLLM / hybrid_module 包装层
    "LLM",
)

# 正则：从错误消息中提取 HTTP 状态码（兼容 "Stream Error 503" / "API Error (503)" / "HTTP 429" 等多种格式）
_HTTP_CODE_PATTERN = re.compile(r"(?:HTTP|Error|status|code)\s*[(:=\[]?\s*(4\d{2}|5\d{2})", re.IGNORECASE)


def is_upstream_transient_error(error_report: Dict[str, Any]) -> bool:
    """判定一条错误报告是否属于"上游瞬时/运维侧故障"，不写入根目录 errors_*.json。

    判定规则为"或"关系，命中任一条件即返回 True，宁可多归（噪音少）也不漏（污染根目录）。
    """
    error_message = str(error_report.get("error_message", "")).strip()
    traceback_str = str(error_report.get("traceback", "")).strip()
    context = error_report.get("context", {}) or {}
    logger_name = str(context.get("logger_name", "") or "").strip()
    error_lower = error_message.lower()

    # 规则 1：明确命中的可重试 HTTP 状态码
    m = _HTTP_CODE_PATTERN.search(error_message)
    if m:
        try:
            code = int(m.group(1))
            if code in _UPSTREAM_TRANSIENT_HTTP_CODES:
                return True
        except (ValueError, TypeError):
            pass

    # 规则 2：错误消息关键词匹配（忽略大小写子串）
    for kw in _UPSTREAM_TRANSIENT_KEYWORDS:
        if kw in error_lower:
            return True

    # 规则 3：供应商专有错误码（出现在 JSON body 字符串里）
    for code in _UPSTREAM_VENDOR_ERROR_CODES:
        if f'"code":{code}' in error_message or f'"code": {code}' in error_message:
            return True
        # 也兼容 "code":50508 无空格
        if f'"code":{code}' in error_message.replace(" ", ""):
            return True

    # 规则 4：余额不足 / 限流类错误码语义（"Insufficient Balance" / "Payment Required" 已经关键词覆盖，这里兜底 402）
    if '"code":20012' in error_message or '"code": 20012' in error_message:
        # SiliconFlow 20012 = "Model does not exist"，但在 503 过载窗口常被网关误报，
        # 若同时满足 traceback 为空 + 上游 logger 白名单则按上游归（见规则 5），
        # 若为真实配置错误（traceback 非空/非上游 logger）则保留在根目录。
        pass

    # 规则 5：纯上游客户端 logger 且 traceback 为空（没有 Python 异常栈，仅是 API 返回错误文本）
    if not traceback_str:
        for ul in _UPSTREAM_ONLY_LOGGERS:
            if logger_name == ul or logger_name.startswith(ul + "."):
                return True

    return False



def _find_project_root() -> Path:
    """定位项目根目录（包含 main.py 的目录）"""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "main.py").exists():
            return parent
    return current.parent.parent


def _is_excluded(logger_name: str) -> bool:
    """检查 logger 是否在排除列表中"""
    for excluded in _EXCLUDED_LOGGERS:
        if logger_name == excluded or logger_name.startswith(excluded + "."):
            return True
    return False


class ErrorCollectorHandler(logging.Handler):
    """
    错误收集处理器

    附加到 QueueListener，捕获所有 ERROR 及以上级别日志：
    - 写入根目录每日聚合文件 errors_YYYYMMDD.json
    - 异步转发给 ErrorReporter 写入 logs/errors/ 批次文件
    """

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR:
            return
        if _is_excluded(record.name):
            return

        # 构造错误报告
        error_report = self._build_error_report(record)

        # 1. 按错误性质分流写入（所有 ERROR+ 都写，包括 _skip_collector 的）
        #    - 上游瞬时错误 → logs/upstream_errors/upstream_errors_YYYYMMDD.json
        #    - 后端代码错误 → 根目录 errors_YYYYMMDD.json
        self._append_to_daily_file(error_report)

        # 2. 跳过已直接报告的错误（global_exception_handler 已调用 report_error）
        if getattr(record, "_skip_collector", False):
            return

        # 3. 异步转发给 ErrorReporter（写入 logs/errors/ 批次文件）
        self._schedule_report(record, error_report)

    def _build_error_report(self, record: logging.LogRecord) -> Dict[str, Any]:
        """从 LogRecord 构造错误报告字典"""
        exc = record.exc_info[1] if record.exc_info and record.exc_info[1] else None
        traceback_str = ""
        if record.exc_info:
            traceback_str = "".join(traceback.format_exception(*record.exc_info))

        # 提取上下文：优先使用 extra 传入的 error_context，否则用 LogRecord 元信息
        context = getattr(record, "error_context", None)
        if not context:
            context = {
                "logger_name": record.name,
                "source_file": record.pathname,
                "source_line": record.lineno,
                "source_func": record.funcName,
            }

        return {
            "error_id": getattr(record, "error_id", None)
            or f"err_{uuid.uuid4().hex[:12]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": record.levelname,
            "error_type": exc.__class__.__name__ if exc else "LoggedError",
            "error_message": record.getMessage(),
            "traceback": traceback_str,
            "context": context,
        }

    def _append_to_daily_file(self, error_report: Dict[str, Any]) -> None:
        """按错误性质分流写入：
        - 上游瞬时错误 → logs/upstream_errors/upstream_errors_YYYYMMDD.json
        - 后端代码错误 → 根目录 errors_YYYYMMDD.json
        """
        try:
            project_root = _find_project_root()
            today = now_str("%Y%m%d")

            # 判定是否上游瞬时错误
            is_upstream = is_upstream_transient_error(error_report)
            if is_upstream:
                upstream_dir = project_root / "logs" / "upstream_errors"
                upstream_dir.mkdir(parents=True, exist_ok=True)
                target_path = upstream_dir / f"upstream_errors_{today}.json"
            else:
                target_path = project_root / f"errors_{today}.json"

            # 在错误报告里注入分流元信息（方便调试，不影响消费方）
            error_report.setdefault("classification", "upstream" if is_upstream else "backend")

            with _daily_file_lock:
                # 读取现有内容
                existing: List[Dict[str, Any]] = []
                if target_path.exists():
                    try:
                        with open(target_path, "r", encoding="utf-8") as f:
                            content = f.read()
                            if content.strip():
                                existing = json.loads(content)
                    except (json.JSONDecodeError, OSError):
                        # 文件损坏，从头开始
                        existing = []
                # 追加新错误
                existing.append(error_report)
                # 写回文件
                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump(existing, f, ensure_ascii=False, indent=2)
        except Exception:
            # 不能让日志 handler 崩溃，静默失败
            pass

    def _schedule_report(
        self, record: logging.LogRecord, error_report: Dict[str, Any]
    ) -> None:
        """异步转发给 ErrorReporter（写入 logs/errors/ 批次文件）"""
        global _main_event_loop
        loop = _main_event_loop
        if loop is None or not loop.is_running():
            return

        exc = (
            record.exc_info[1]
            if record.exc_info and record.exc_info[1]
            else RuntimeError(record.getMessage())
        )
        context = error_report.get("context", {})
        error_id = error_report.get("error_id")
        severity = record.levelname

        try:
            asyncio.run_coroutine_threadsafe(
                _call_report_error(exc, context, severity, error_id),
                loop,
            )
        except Exception:
            pass


async def _call_report_error(
    exc: Exception,
    context: Dict[str, Any],
    severity: str,
    error_id: Optional[str],
) -> None:
    """调用 ErrorReporter.report_error（延迟导入避免循环）"""
    try:
        from core.utils.errors.log_sanitizer import ErrorReporter

        await ErrorReporter.report_error(
            exc, context=context, severity=severity, error_id=error_id
        )
    except Exception:
        # ErrorReporter 自身失败不应影响主流程
        pass


async def install() -> bool:
    """
    安装错误收集器

    在服务启动时调用（由 service_registry 注册为服务）：
    1. 捕获主事件循环（供 handler 跨线程调度协程）
    2. 将 ErrorCollectorHandler 附加到 QueueListener

    Returns:
        True 表示安装成功，False 表示失败
    """
    global _main_event_loop

    try:
        _main_event_loop = asyncio.get_running_loop()
    except RuntimeError:
        _logger.warning("安装错误收集器失败：没有运行中的事件循环")
        return False

    try:
        from core.utils.logging.registry import _queue_listener

        if _queue_listener is None:
            _logger.warning("安装错误收集器失败：QueueListener 未初始化")
            return False

        # 避免重复附加
        for h in _queue_listener.handlers:
            if isinstance(h, ErrorCollectorHandler):
                _logger.info("错误收集器已安装，跳过")
                return True

        handler = ErrorCollectorHandler()
        handler.setLevel(logging.ERROR)
        _queue_listener.handlers = _queue_listener.handlers + (handler,)
        _logger.info(
            "错误收集器已安装：ERROR+ 日志按性质分流写入 logs/upstream_errors/（上游瞬时）和根目录 errors_YYYYMMDD.json（后端代码错误），同时转 logs/errors/"
        )
        return True
    except Exception as e:
        _logger.error(f"安装错误收集器异常: {e}", exc_info=True)
        return False


async def uninstall() -> None:
    """卸载错误收集器（服务关闭时调用）"""
    try:
        from core.utils.logging.registry import _queue_listener

        if _queue_listener is None:
            return
        new_handlers = tuple(
            h for h in _queue_listener.handlers if not isinstance(h, ErrorCollectorHandler)
        )
        if len(new_handlers) != len(_queue_listener.handlers):
            _queue_listener.handlers = new_handlers
            _logger.info("错误收集器已卸载")
    except Exception as e:
        _logger.warning(f"卸载错误收集器异常: {e}")


__all__ = [
    "ErrorCollectorHandler",
    "install",
    "uninstall",
]
