"""角色从临时聊天回归原活动的统一消息管理。

使用场景：
1. /打断 后的聊天窗口即将结束，角色要回去做原来的任务。
2. 半夜被叫醒后聊了一会儿，角色决定睡回去。

子模块：
- instruction: 构建回归消息的文案与决策提示
- state: 维护 pending_return 内存状态
- scheduler: 异步调度回归消息发送
- core: 对外核心接口（发送消息、处理用户回复）
"""

from __future__ import annotations

from core.services.character_daily.activity_return.core import (
    handle_user_reply_during_return,
    send_activity_return_message,
)
from core.services.character_daily.activity_return.instruction import (
    build_activity_start_farewell_instruction,
    build_return_decision_hint,
    build_return_instruction,
    build_sleep_during_chat_farewell_instruction,
)
from core.services.character_daily.activity_return.scheduler import (
    cancel_scheduled_return,
    schedule_activity_return,
)
from core.services.character_daily.activity_return.state import (
    PendingReturn,
    clear_pending_return,
    get_pending_return,
    reset_all_pending_returns,
    resolve_pending_return,
)

__all__ = [
    "PendingReturn",
    "build_return_instruction",
    "build_return_decision_hint",
    "build_activity_start_farewell_instruction",
    "build_sleep_during_chat_farewell_instruction",
    "send_activity_return_message",
    "get_pending_return",
    "resolve_pending_return",
    "clear_pending_return",
    "handle_user_reply_during_return",
    "schedule_activity_return",
    "cancel_scheduled_return",
    "reset_all_pending_returns",
]
