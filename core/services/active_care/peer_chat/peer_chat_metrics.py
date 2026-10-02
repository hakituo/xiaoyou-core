"""双角色互聊效果评估指标收集器（轻量内存计数器）

设计：
- 进程级单例，executor/scheduler 都往里写，health_status/api 从里读
- 只累积计数，不存储明细（避免内存增长），重启清零
- 指标用途：衡量互聊质量、调参依据（过滤率高说明 prompt/temperature 需调）

指标含义：
- scripts_generated:    成功生成并分发的剧本数
- parse_retries:        剧本 JSON 解析失败触发重试的次数
- mention_triggered:    末句 mention_user 触发主人通知的次数
- decision_no_send:     LLM 决策不发送的次数
- decision_timeout:     决策 LLM 超时的次数
- script_llm_timeout:   剧本 LLM 超时的次数
"""
from __future__ import annotations

import threading
from typing import Dict


class PeerChatMetrics:
    """双角色互聊指标收集器（线程安全，进程级单例）"""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {
            "scripts_generated": 0,
            "parse_retries": 0,
            "mention_triggered": 0,
            "decision_no_send": 0,
            "decision_timeout": 0,
            "script_llm_timeout": 0,
        }

    def incr(self, key: str, amount: int = 1) -> None:
        """递增某个指标"""
        with self._lock:
            if key in self._counters:
                self._counters[key] += amount
            else:
                self._counters[key] = amount

    def get_snapshot(self) -> Dict[str, int]:
        """获取当前指标快照（副本）"""
        with self._lock:
            return dict(self._counters)

    def reset(self) -> None:
        """清零（主要用于测试）"""
        with self._lock:
            for k in self._counters:
                self._counters[k] = 0


# 进程级单例
_instance: PeerChatMetrics | None = None
_instance_lock = threading.Lock()


def get_peer_chat_metrics() -> PeerChatMetrics:
    """获取 PeerChatMetrics 全局单例"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = PeerChatMetrics()
    return _instance
