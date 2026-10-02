# -*- coding: utf-8 -*-
"""互聊调度器健康追踪（从 PeerChatScheduler 拆出）。"""

from __future__ import annotations

import time
from typing import Any, Dict

from core.utils.logger import get_module_logger

logger = get_module_logger("PEER_CHAT_SCHEDULER", "peer_chat.log")


class PeerChatHealthMixin:
    """成功/失败计数、退避间隔、健康快照、手动触发检查。"""

    def _record_success(self):
        self._last_success_ts = time.time()
        self._consecutive_failures = 0
        self._total_successes += 1

    def _record_failure(self, error_msg: str):
        self._consecutive_failures += 1
        self._last_error = error_msg[:500]
        logger.warning(
            "PeerChatScheduler: 记录失败 #%d: %s",
            self._consecutive_failures, error_msg[:100]
        )

    def _compute_next_interval(self) -> float:
        """计算下次检查间隔，支持指数退避（参数从 config 读取）"""
        if self._consecutive_failures < self._backoff_threshold:
            return float(self._check_interval)
        # 指数退避：base * 2^(failures - threshold)
        exponent = min(self._consecutive_failures - self._backoff_threshold, 4)
        backoff = self._backoff_base_seconds * (2 ** exponent)
        return min(float(backoff), float(self._backoff_max_seconds))

    def get_health_status(self) -> Dict[str, Any]:
        """返回调度器完整健康状态"""
        now = time.time()
        return {
            "running": self._running,
            "task_alive": bool(self._task and not self._task.done()),
            "last_run_ts": self._last_run_ts,
            "last_run_ago_seconds": int(now - self._last_run_ts) if self._last_run_ts > 0 else -1,
            "last_success_ts": self._last_success_ts,
            "last_success_ago_seconds": int(now - self._last_success_ts) if self._last_success_ts > 0 else -1,
            "consecutive_failures": self._consecutive_failures,
            "last_error": self._last_error,
            "today_count": self._today_count,
            "total_runs": self._total_runs,
            "total_successes": self._total_successes,
            "next_check_ts": self._next_check_ts,
            "next_check_in_seconds": max(0, int(self._next_check_ts - now)) if self._next_check_ts > 0 else -1,
            "check_interval": self._check_interval,
            "user_last_activity_ts": self._user_activity.latest_ts(),
            # P3#12: 互聊效果评估指标（来自 PeerChatMetrics 单例）
            "peer_chat_metrics": self._get_peer_chat_metrics_snapshot(),
        }

    def _get_peer_chat_metrics_snapshot(self) -> Dict[str, Any]:
        """获取互聊效果评估指标快照"""
        try:
            from core.services.active_care.peer_chat.peer_chat_metrics import get_peer_chat_metrics
            return get_peer_chat_metrics().get_snapshot()
        except Exception:
            return {}

    async def run_single_check(self) -> Dict[str, Any]:
        """手动触发一次检查（供 API 端点调用）

        Returns:
            包含 success, sent, error 的结果字典
        """
        logger.info("PeerChatScheduler: 手动触发单次检查")
        try:
            await self._run_single_cycle()
            return {
                "success": True,
                "sent": True,
                "message": "单次检查完成",
                "health": self.get_health_status(),
            }
        except Exception as e:
            logger.error("PeerChatScheduler: 手动检查失败: %s", e, exc_info=True)
            return {
                "success": False,
                "sent": False,
                "error": str(e),
                "health": self.get_health_status(),
            }
