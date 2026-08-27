# -*- coding: utf-8 -*-
"""健康数据同步服务域。

负责 Samsung Health / Health Connect 上报数据的落盘、事件流生成与查询。
"""

from .store import (
    HealthSyncResult,
    append_body_history,
    append_manual_event,
    ingest_snapshot,
    read_body_history,
    read_events,
    read_latest,
)

__all__ = [
    "HealthSyncResult",
    "append_body_history",
    "append_manual_event",
    "ingest_snapshot",
    "read_body_history",
    "read_events",
    "read_latest",
]
