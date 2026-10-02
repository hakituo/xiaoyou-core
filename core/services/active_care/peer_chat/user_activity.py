# -*- coding: utf-8 -*-
"""用户活跃追踪（从 PeerChatScheduler 拆出）。

职责单一：记录「用户在哪个会话、什么时候发过消息」，并据此回答三类问题：

1. **某个具体会话**最近是否有用户消息 —— :meth:`UserActivityTracker.is_active`
   / :meth:`UserActivityTracker.is_within_idle_window`；
2. **某个角色自己的会话**最近是否有用户消息 ——
   :meth:`UserActivityTracker.is_active_for_scope`（告别 / 晚安等「发给用户」的场景必须用这个）；
3. 用户在**任意会话**是否活跃 —— :meth:`UserActivityTracker.is_active_anywhere`
   （AI 间互聊这类确实需要全局判定的场景才用）。

为什么单独拆出来：这些状态原本挂在 1200+ 行的 ``PeerChatScheduler`` 上，而第 2 类
判定长期缺失，导致 A 角色的活跃被 B 角色误判成「用户正在聊天」，进而触发 B 角色
发出告别消息（用户视角：「我根本没找他，他自己跑来报备去干什么」）。
详见 ``docs/important/ACTIVE_CARE_REPLY_CONTINUITY_PLAN.md`` R6。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict

from config.debug_config import is_debug_enabled
from core.utils.logger import get_module_logger

# 与 PeerChatScheduler 同源 logger：用户活跃追踪属于 peer chat 链路，
# 日志统一落 peer_chat.log（见 tests/scripts/active_care/verify_peer_chat_log_separation.py）
logger = get_module_logger("PEER_CHAT_SCHEDULER", "peer_chat.log")

# 用户活跃时间戳持久化 key（写入 proactive_state.json，重启后可恢复）
USER_ACTIVITY_STATE_KEY = "last_user_activity_map"

# 节流：两次持久化之间的最小间隔，避免每条用户消息都写盘
USER_ACTIVITY_PERSIST_MIN_GAP = 30.0

# 配置不可用时的兜底窗口
DEFAULT_ACTIVITY_GRACE_SECONDS = 45.0
DEFAULT_IDLE_WINDOW_SECONDS = 900.0


def resolve_role_scope(role_id: str) -> str:
    """把 role_id / conversation_id 归一化成角色 scope。

    例：``ling`` / ``core_ling`` / ``web_role_ling`` / ``shared__persona__core_ling``
    都归到 ``ling``。

    解析不出归属时退回小写原值：调用方（告别 / 晚安判定）宁可沿用原值再交给
    ``matched_persona_scope`` 逐会话比对，也不该因为注册表未就绪就整条判定失效。
    """
    raw = str(role_id or "").strip().lower()
    if not raw:
        return ""
    try:
        from core.utils.data.scope_registry import matched_persona_scope

        return matched_persona_scope(raw) or raw
    except Exception:
        return raw


class UserActivityTracker:
    """用户活跃时间戳的内存表 + 节流持久化 + 三类判定。

    线程/协程安全说明：``mark`` 与各判定都只读写进程内 dict，CPython 下 dict
    的单项读写是原子的；持久化走节流异步任务，不阻塞调用方。
    """

    def __init__(
        self,
        storage: Any,
        grace_seconds: float = DEFAULT_ACTIVITY_GRACE_SECONDS,
        idle_window_seconds: float = DEFAULT_IDLE_WINDOW_SECONDS,
    ) -> None:
        """
        Args:
            storage: ActiveCareStorage 实例（用于读写 proactive_state.json）
            grace_seconds: 「最近活跃」窗口，供 ``is_active`` 使用
            idle_window_seconds: 空闲窗口，供 ``is_within_idle_window`` 使用
        """
        self._storage = storage
        self._grace_seconds = float(grace_seconds)
        self._idle_window_seconds = float(idle_window_seconds)
        self._activity_ts: Dict[str, float] = {}
        self._last_persist_ts: float = 0.0
        self._restored: bool = False
        # P1-2: 跟踪持久化任务，防止被 GC 后丢失活跃时间戳
        self._pending_tasks: set = set()

    # ==================== 写入 ====================

    def mark(self, conversation_id: str) -> None:
        """标记用户在某个会话活跃，并节流地异步持久化。

        供外部聊天流程（stream_orchestrator 等）在收到用户消息时调用。
        节流持久化使进程重启后 ``is_within_idle_window`` 仍能正确判断。
        """
        cid = str(conversation_id or "").strip() or "default"
        now = time.time()
        self._activity_ts[cid] = now
        if is_debug_enabled("peer_chat"):
            logger.info("UserActivityTracker: 用户活跃标记 cid=%s", cid)

        if (now - self._last_persist_ts) < USER_ACTIVITY_PERSIST_MIN_GAP:
            return
        self._last_persist_ts = now
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 无事件循环（同步调用场景）时跳过持久化，内存态仍已更新
            return
        task = loop.create_task(self._persist())
        self._pending_tasks.add(task)

        def _on_done(t: asyncio.Task) -> None:
            self._pending_tasks.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.error(
                    "UserActivityTracker: 用户活跃持久化任务异常: %r",
                    exc,
                    exc_info=exc,
                )

        task.add_done_callback(_on_done)

    async def _persist(self) -> None:
        """把内存里的用户活跃时间戳写到 proactive_state.json"""
        try:
            snapshot = dict(self._activity_ts)
            await self._storage.save_proactive_state(
                {USER_ACTIVITY_STATE_KEY: snapshot},
                immediate=False,
            )
        except Exception as e:
            if is_debug_enabled("peer_chat"):
                logger.info("UserActivityTracker: 持久化用户活跃时间戳失败: %s", e)

    async def load(self) -> None:
        """从 proactive_state.json 恢复用户活跃时间戳（启动时调用一次）。"""
        if self._restored:
            return
        self._restored = True
        try:
            state_data = await self._storage.get_proactive_state()
            saved = state_data.get(USER_ACTIVITY_STATE_KEY)
            if isinstance(saved, dict) and saved:
                for cid, ts in saved.items():
                    try:
                        self._activity_ts[str(cid)] = float(ts)
                    except (TypeError, ValueError):
                        continue
                logger.info(
                    "UserActivityTracker: 恢复 %d 条用户活跃时间戳",
                    len(self._activity_ts),
                )
        except Exception as e:
            if is_debug_enabled("peer_chat"):
                logger.info("UserActivityTracker: 加载用户活跃时间戳失败: %s", e)

    # ==================== 判定 ====================

    def is_active(self, conversation_id: str) -> bool:
        """判断用户在该**具体会话**最近是否活跃（在 grace 窗口内）。"""
        cid = str(conversation_id or "").strip() or "default"
        last = float(self._activity_ts.get(cid, 0.0))
        return (time.time() - last) < self._grace_seconds

    def is_within_idle_window(self, conversation_id: str) -> bool:
        """判断是否在用户空闲窗口内（用户最后消息后 idle_window 秒内才允许互聊）。"""
        cid = str(conversation_id or "").strip() or "default"
        last = float(self._activity_ts.get(cid, 0.0))
        if last <= 0:
            # 用户从未活跃过，允许互聊
            return True
        return (time.time() - last) <= self._idle_window_seconds

    def is_active_for_scope(self, scope: str, window_seconds: float) -> bool:
        """判断用户最近是否在**指定角色自己的会话**里活跃。

        【为什么必须按角色过滤】``_activity_ts`` 是全局表，键为 conversation_id，
        同时混着 ``web_role_aveline`` / ``web_role_ling`` / ``shared__persona__core_ling``
        等所有角色的会话。直接遍历它的全部取值，会让 A 角色的活跃被 B 角色判成
        「用户正在聊天」，进而触发 B 角色的告别 / 晚安消息 —— 用户视角就是
        「我根本没找他，他自己跑来报备去干什么」。

        因此这里按 conversation_id 的角色归属过滤；解析不出归属的会话
        （群聊、隔离会话等）一律不计入任何角色。

        Args:
            scope: 角色 scope（如 ``ling``）。为空时返回 False，不做全局兜底。
            window_seconds: 活跃窗口（秒）。

        Returns:
            True 表示该角色自己的会话在窗口内有用户消息。
        """
        target = str(scope or "").strip().lower()
        if not target or not self._activity_ts:
            return False

        try:
            from core.utils.data.scope_registry import matched_persona_scope
        except Exception:
            return False

        try:
            window = float(window_seconds)
        except (TypeError, ValueError):
            return False

        now = time.time()
        for cid, ts in self._activity_ts.items():
            try:
                ts_value = float(ts)
            except (TypeError, ValueError):
                continue
            if ts_value <= 0 or (now - ts_value) >= window:
                continue
            # 严格解析：匹配不到角色的会话不归任何角色，避免误算
            if matched_persona_scope(cid) == target:
                return True
        return False

    def is_active_anywhere(self, window_seconds: float) -> bool:
        """判断用户在**任意会话**是否最近活跃。

        仅用于「用户是否正在使用本系统」这类全局语义（如 AI 间互聊的门禁：
        用户正跟某个角色聊着，就不该再让角色之间开一场私聊）。需要判断
        「用户是不是在跟这个角色说话」时必须改用 :meth:`is_active_for_scope`。
        """
        if not self._activity_ts:
            return False
        try:
            window = float(window_seconds)
        except (TypeError, ValueError):
            return False
        now = time.time()
        for ts in self._activity_ts.values():
            try:
                ts_value = float(ts)
            except (TypeError, ValueError):
                continue
            if ts_value > 0 and (now - ts_value) < window:
                return True
        return False

    def latest_ts(self) -> float:
        """最近一次用户活跃时间戳（无数据返回 0.0），供健康快照使用。"""
        if not self._activity_ts:
            return 0.0
        try:
            return float(max(self._activity_ts.values()))
        except (TypeError, ValueError):
            return 0.0

    def snapshot(self) -> Dict[str, float]:
        """返回活跃表的浅拷贝（调试 / 诊断用）。"""
        return dict(self._activity_ts)


def build_default_tracker(storage: Any) -> UserActivityTracker:
    """按配置构造 tracker（参数从 DualRoleSettings 读取，读不到则用兜底值）。"""
    grace = DEFAULT_ACTIVITY_GRACE_SECONDS
    idle = DEFAULT_IDLE_WINDOW_SECONDS
    try:
        from config.integrated_config import get_settings

        dr = get_settings().dual_role
        grace = float(dr.peer_chat_user_activity_grace_seconds)
        idle = float(dr.peer_chat_user_idle_window_seconds)
    except Exception:
        pass
    return UserActivityTracker(storage, grace_seconds=grace, idle_window_seconds=idle)


__all__ = [
    "UserActivityTracker",
    "build_default_tracker",
    "resolve_role_scope",
    "USER_ACTIVITY_STATE_KEY",
    "USER_ACTIVITY_PERSIST_MIN_GAP",
]
