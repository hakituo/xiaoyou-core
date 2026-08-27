#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
错误日志记录模块
专门记录系统错误，不经过 BERT 分析，不落盘到用户可见的历史记录
存储在 logs/YYYY/M/D/error.log，与 server.log 和 xiaoyou_main.log 并列
"""

from core.utils.logger import get_logger
import json
import threading
import uuid

from pathlib import Path
from typing import Any, Dict, Optional

from core.utils.time_utils import get_current_time

logger = get_logger("ErrorLogStore")

_LOCK = threading.Lock()
_INSTANCE = None


def get_error_log_store() -> "ErrorLogStore":
    """获取错误日志单例"""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ErrorLogStore()
    return _INSTANCE


class ErrorLogStore:
    """错误日志存储器，存储在 logs/YYYY/M/D/error.log"""

    def _get_base_dir(self) -> Path:
        """获取错误日志目录（logs/YYYY/M/D）"""
        from core.utils.time_utils import get_current_time
        now = get_current_time()
        project_root = Path(__file__).parent.parent.parent
        base_dir = project_root / "logs" / str(now.year) / str(now.month) / str(now.day)
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir

    def append_error(
        self,
        *,
        conversation_id: str,
        user_message: str,
        error_message: str,
        error_code: str = "UNKNOWN_ERROR",
        error_details: Optional[Dict[str, Any]] = None,
        model_hint: Optional[str] = None,
        message_id: Optional[str] = None,
        stack_trace: Optional[str] = None,
        source: str = "stream_orchestrator",
    ) -> Dict[str, Any]:
        """
        记录错误到 error.log

        Args:
            conversation_id: 会话ID
            user_message: 用户发送的原始消息
            error_message: 错误信息
            error_code: 错误码
            error_details: 额外错误详情
            model_hint: 模型提示
            message_id: 消息ID
            stack_trace: 堆栈跟踪
            source: 错误来源

        Returns:
            Dict containing error_id 和路径信息
        """
        now = get_current_time()
        error_id = uuid.uuid4().hex
        msg_id = str(message_id or uuid.uuid4())

        base_dir = self._get_base_dir()
        file_path = base_dir / "error.log"

        payload = {
            "error_id": error_id,
            "message_id": msg_id,
            "conversation_id": str(conversation_id or "default"),
            "user_message": str(user_message or ""),
            "error_message": str(error_message or ""),
            "error_code": str(error_code or "UNKNOWN_ERROR"),
            "error_details": error_details if isinstance(error_details, dict) else {},
            "model_hint": str(model_hint or ""),
            "stack_trace": str(stack_trace or "")[:2000] if stack_trace else "",
            "source": str(source or "unknown"),
            "timestamp": now.timestamp(),
            "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        }

        line = json.dumps(payload, ensure_ascii=False)
        with _LOCK:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

        return {
            "error_id": error_id,
            "file": str(file_path.relative_to(base_dir.parent.parent.parent)),
            "timestamp": payload["timestamp"],
            "conversation_id": payload["conversation_id"],
        }

    def list_errors(
        self,
        *,
        conversation_id: Optional[str] = None,
        limit: int = 100,
        before: Optional[float] = None,
        error_code: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        """
        查询错误日志

        Args:
            conversation_id: 按会话ID过滤
            limit: 返回数量限制
            before: 只返回此时间戳之前的错误
            error_code: 按错误码过滤

        Returns:
            错误列表
        """
        items: list[Dict[str, Any]] = []
        project_root = Path(__file__).parent.parent.parent
        logs_dir = project_root / "logs"

        if not logs_dir.exists():
            return items

        for file_path in sorted(logs_dir.rglob("error.log"), reverse=True):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        raw = line.strip()
                        if not raw:
                            continue
                        try:
                            payload = json.loads(raw)
                        except Exception:
                            continue

                        if conversation_id and payload.get("conversation_id") != conversation_id:
                            continue
                        if error_code and payload.get("error_code") != error_code:
                            continue
                        timestamp = float(payload.get("timestamp") or 0.0)
                        if before is not None and timestamp >= float(before):
                            continue

                        items.append(payload)
            except Exception:
                continue

        items.sort(key=lambda x: float(x.get("timestamp") or 0.0), reverse=True)
        return items[:limit] if limit > 0 else items

    def get_error_stats(self) -> Dict[str, Any]:
        """获取错误统计信息"""
        stats = {
            "total_errors": 0,
            "errors_by_code": {},
            "recent_errors": [],
        }

        recent = self.list_errors(limit=100)
        for err in recent:
            stats["total_errors"] += 1
            code = err.get("error_code", "UNKNOWN")
            stats["errors_by_code"][code] = stats["errors_by_code"].get(code, 0) + 1

        stats["recent_errors"] = recent[:10]
        return stats
