# -*- coding: utf-8 -*-
"""用户活跃追踪测试（user_activity.py）。

覆盖 core/services/active_care/peer_chat/user_activity.py 的：
- resolve_role_scope 的归一化与兜底
- UserActivityTracker 的写入 / 节流持久化 / 恢复 / 五类判定
- build_default_tracker 的配置读取与兜底

为什么这个模块值得单独测：``is_active_for_scope`` 是按角色隔离的判定，
历史上缺了它导致「A 角色活跃被 B 角色误判成用户正在聊天」，进而 B 角色发出
告别/晚安消息（用户视角：我根本没找他，他自己跑来报备去干什么）。
所以这里的核心断言是「按角色过滤」与「解析不出归属就不计入任何角色」。

设计要点：
- 时间相关断言全部通过注入固定时间戳（写入过去/未来）来构造，不 sleep、不依赖真实流逝；
  唯一的例外是「刚写入」的窗口内断言，窗口给足余量（如 60s 窗口断言刚写入为 True）。
- storage 用替身，不读写真实 proactive_state.json。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict

import pytest

from core.services.active_care.peer_chat.user_activity import (
    DEFAULT_ACTIVITY_GRACE_SECONDS,
    DEFAULT_IDLE_WINDOW_SECONDS,
    USER_ACTIVITY_PERSIST_MIN_GAP,
    USER_ACTIVITY_STATE_KEY,
    UserActivityTracker,
    build_default_tracker,
    resolve_role_scope,
)


class _StubStorage:
    """替身存储：内存态 proactive_state，记录 save 调用。"""

    def __init__(self, state: Dict[str, Any] | None = None, fail: bool = False):
        self._state = dict(state or {})
        self._fail = fail
        self.saved: list = []

    async def get_proactive_state(self) -> Dict[str, Any]:
        if self._fail:
            raise RuntimeError("存储不可用")
        return dict(self._state)

    async def save_proactive_state(self, data, immediate: bool = True) -> None:
        if self._fail:
            raise RuntimeError("存储不可用")
        self.saved.append(dict(data))
        self._state.update(data)


# ============================================================
# resolve_role_scope
# ============================================================

class TestResolveRoleScope:
    """role_id / conversation_id → 角色 scope 归一化。"""

    def test_empty_returns_empty(self):
        """空输入返回空串（调用方据此判定"无归属"）。"""
        assert resolve_role_scope("") == ""
        assert resolve_role_scope(None) == ""

    def test_plain_role_id_passthrough(self):
        """裸 role_id 归一后仍是自身。"""
        assert resolve_role_scope("ling") == "ling"
        assert resolve_role_scope("aveline") == "aveline"

    def test_case_and_whitespace_normalized(self):
        """大小写与首尾空白被归一。"""
        assert resolve_role_scope("  LING  ") == "ling"
        assert resolve_role_scope("Aveline") == "aveline"

    def test_unknown_value_falls_back_to_lowercased_raw(self):
        """解析不出归属时退回小写原值，而不是空串。

        调用方（告别/晚安判定）宁可沿用原值再交给 matched_persona_scope 逐会话比对，
        也不该因为注册表未就绪就整条判定失效。
        """
        assert resolve_role_scope("SOME_UNKNOWN_CID") == "some_unknown_cid"


# ============================================================
# 写入与节流持久化
# ============================================================

class TestMarkAndPersist:
    """mark 的写入与节流持久化行为。"""

    def test_mark_records_timestamp(self):
        """mark 后该会话立即可判定为活跃。"""
        tracker = UserActivityTracker(_StubStorage(), grace_seconds=60.0)
        tracker.mark("private_10001")

        assert tracker.is_active("private_10001") is True

    def test_mark_empty_cid_uses_default(self):
        """空会话 id 落到 "default"，避免写入空键。"""
        tracker = UserActivityTracker(_StubStorage(), grace_seconds=60.0)
        tracker.mark("")

        assert tracker.is_active("default") is True
        assert "default" in tracker.snapshot()

    def test_mark_overwrites_previous_timestamp(self):
        """同一会话重复 mark 会刷新时间戳。"""
        tracker = UserActivityTracker(_StubStorage(), grace_seconds=60.0)
        tracker.mark("cid")
        first = tracker.snapshot()["cid"]
        tracker.mark("cid")
        second = tracker.snapshot()["cid"]

        assert second >= first

    async def test_first_mark_triggers_persist(self):
        """首次 mark 会异步持久化（last_persist_ts 初始为 0）。"""
        storage = _StubStorage()
        tracker = UserActivityTracker(storage, grace_seconds=60.0)
        tracker.mark("cid")
        await tracker._persist()

        assert storage.saved
        assert "cid" in storage.saved[-1][USER_ACTIVITY_STATE_KEY]

    async def test_persist_throttled_within_min_gap(self):
        """节流窗口内第二次 mark 不再派发持久化任务。

        直接把 _last_persist_ts 设为"刚刚"，等效于"距上次持久化不足节流间隔"，
        无需 sleep 等待。
        """
        tracker = UserActivityTracker(_StubStorage(), grace_seconds=60.0)
        tracker._last_persist_ts = time.time()

        tracker.mark("cid")

        # 节流命中：不应创建新任务
        assert tracker._pending_tasks == set()
        # 但内存态仍已更新（写入不因节流失效）
        assert "cid" in tracker.snapshot()

    async def test_persist_failure_is_swallowed(self):
        """持久化异常被吞掉，不影响内存态（调用方不能因写盘失败而崩）。"""
        tracker = UserActivityTracker(_StubStorage(fail=True), grace_seconds=60.0)
        tracker.mark("cid")
        await tracker._persist()  # 不应抛异常

        assert "cid" in tracker.snapshot()


# ============================================================
# 恢复
# ============================================================

class TestLoad:
    """启动时从 proactive_state 恢复。"""

    async def test_load_restores_timestamps(self):
        """恢复后旧的活跃时间戳可参与判定。"""
        ts = time.time() - 10.0
        storage = _StubStorage({USER_ACTIVITY_STATE_KEY: {"cid": ts}})
        tracker = UserActivityTracker(storage, grace_seconds=60.0)

        await tracker.load()

        assert tracker.snapshot()["cid"] == pytest.approx(ts)
        assert tracker.is_active("cid") is True

    async def test_load_is_idempotent(self):
        """重复 load 只执行一次（_restored 守卫）。"""
        storage = _StubStorage({USER_ACTIVITY_STATE_KEY: {"cid": 1.0}})
        tracker = UserActivityTracker(storage)

        await tracker.load()
        first = tracker.snapshot()
        await tracker.load()

        assert tracker.snapshot() == first
        assert tracker._restored is True

    async def test_load_skips_invalid_entries(self):
        """非法时间戳条目被跳过，其余照常恢复。"""
        storage = _StubStorage(
            {USER_ACTIVITY_STATE_KEY: {"good": 100.0, "bad": "not-a-number"}}
        )
        tracker = UserActivityTracker(storage)

        await tracker.load()

        assert "good" in tracker.snapshot()
        assert "bad" not in tracker.snapshot()

    async def test_load_handles_non_dict_state(self):
        """状态里存的不是 dict 时安全跳过。"""
        storage = _StubStorage({USER_ACTIVITY_STATE_KEY: ["not", "a", "dict"]})
        tracker = UserActivityTracker(storage)

        await tracker.load()

        assert tracker.snapshot() == {}

    async def test_load_swallows_storage_exception(self):
        """存储异常时安全返回，不阻塞启动。"""
        tracker = UserActivityTracker(_StubStorage(fail=True))

        await tracker.load()  # 不应抛异常

        assert tracker.snapshot() == {}


# ============================================================
# 判定
# ============================================================

class TestIsActive:
    """is_active：具体会话的活跃窗口判定。"""

    def test_recent_activity_is_active(self):
        """窗口内的活跃返回 True。"""
        tracker = UserActivityTracker(_StubStorage(), grace_seconds=60.0)
        tracker.mark("cid")

        assert tracker.is_active("cid") is True

    def test_stale_activity_is_inactive(self):
        """窗口外的活跃返回 False（用过去时间戳构造，不 sleep）。"""
        tracker = UserActivityTracker(_StubStorage(), grace_seconds=60.0)
        tracker._activity_ts["cid"] = time.time() - 3600.0

        assert tracker.is_active("cid") is False

    def test_unknown_cid_is_inactive(self):
        """从未活跃过的会话返回 False。"""
        tracker = UserActivityTracker(_StubStorage(), grace_seconds=60.0)

        assert tracker.is_active("never_seen") is False

    def test_empty_cid_falls_back_to_default(self):
        """空会话 id 与 mark 的兜底键一致。"""
        tracker = UserActivityTracker(_StubStorage(), grace_seconds=60.0)
        tracker.mark("")

        assert tracker.is_active("") is True


class TestIsWithinIdleWindow:
    """is_within_idle_window：空闲窗口判定。"""

    def test_never_active_is_within_window(self):
        """用户从未活跃过时允许互聊（返回 True）。"""
        tracker = UserActivityTracker(_StubStorage(), idle_window_seconds=900.0)

        assert tracker.is_within_idle_window("cid") is True

    def test_recent_activity_is_within_window(self):
        """窗口内有活跃 → True。"""
        tracker = UserActivityTracker(_StubStorage(), idle_window_seconds=900.0)
        tracker.mark("cid")

        assert tracker.is_within_idle_window("cid") is True

    def test_long_ago_activity_is_outside_window(self):
        """超出空闲窗口 → False（用过去时间戳构造）。"""
        tracker = UserActivityTracker(_StubStorage(), idle_window_seconds=900.0)
        tracker._activity_ts["cid"] = time.time() - 7200.0

        assert tracker.is_within_idle_window("cid") is False


class TestIsActiveForScope:
    """is_active_for_scope：按角色隔离的活跃判定（本模块的核心价值）。

    真实归属规则（scope_registry.matched_persona_scope）：
    ``web_role_ling`` / ``core_ling`` / ``shared__persona__core_ling`` → ``ling``；
    而 ``private_<主人QQ>``、``group_chat_*`` 这类**解析不出角色**的会话返回空串，
    不计入任何角色。
    """

    def test_matching_scope_is_active(self):
        """用户在该角色自己的会话里活跃 → True。"""
        tracker = UserActivityTracker(_StubStorage())
        tracker._activity_ts["web_role_ling"] = time.time()

        assert tracker.is_active_for_scope("ling", 300.0) is True

    def test_other_role_conversation_does_not_count(self):
        """别的角色的会话活跃，不能算成该角色的活跃（防串味）。"""
        tracker = UserActivityTracker(_StubStorage())
        tracker._activity_ts["web_role_aveline"] = time.time()

        assert tracker.is_active_for_scope("ling", 300.0) is False
        assert tracker.is_active_for_scope("aveline", 300.0) is True

    def test_master_private_conversation_counts_for_nobody(self):
        """与主人的私聊会话（private_*）解析不出角色，不计入任何角色。"""
        tracker = UserActivityTracker(_StubStorage())
        tracker._activity_ts["private_10001"] = time.time()

        assert tracker.is_active_for_scope("ling", 300.0) is False
        assert tracker.is_active_for_scope("aveline", 300.0) is False
        # 但它确实是一次真实活跃 —— 全局判定应当能看到
        assert tracker.is_active_anywhere(300.0) is True

    def test_empty_scope_returns_false(self):
        """scope 为空时返回 False，不做全局兜底。"""
        tracker = UserActivityTracker(_StubStorage())
        tracker._activity_ts["web_role_ling"] = time.time()

        assert tracker.is_active_for_scope("", 300.0) is False

    def test_no_activity_returns_false(self):
        """无任何活跃记录时返回 False。"""
        tracker = UserActivityTracker(_StubStorage())

        assert tracker.is_active_for_scope("ling", 300.0) is False

    def test_stale_activity_outside_window(self):
        """窗口外的活跃不计入。"""
        tracker = UserActivityTracker(_StubStorage())
        tracker._activity_ts["web_role_ling"] = time.time() - 3600.0

        assert tracker.is_active_for_scope("ling", 300.0) is False

    def test_invalid_window_returns_false(self):
        """窗口参数非法时返回 False 而不是崩。"""
        tracker = UserActivityTracker(_StubStorage())
        tracker._activity_ts["web_role_ling"] = time.time()

        assert tracker.is_active_for_scope("ling", "not-a-number") is False

    def test_invalid_timestamp_entry_skipped(self):
        """非法时间戳条目被跳过，合法条目仍生效。"""
        tracker = UserActivityTracker(_StubStorage())
        tracker._activity_ts["web_role_ling"] = "not-a-number"
        tracker._activity_ts["core_ling"] = time.time()

        assert tracker.is_active_for_scope("ling", 300.0) is True

    def test_unresolvable_cid_counts_for_nobody(self, monkeypatch):
        """解析不出角色归属的会话不计入任何角色（防串味）。

        这是本模块存在的根本原因：群聊 / 隔离会话的活跃不能被算成
        "某个角色正在和用户聊天"，否则会误触发该角色的主动消息。
        """
        import core.utils.data.scope_registry as scope_registry

        monkeypatch.setattr(
            scope_registry, "matched_persona_scope", lambda cid: ""
        )
        tracker = UserActivityTracker(_StubStorage())
        tracker._activity_ts["group_chat_999"] = time.time()

        assert tracker.is_active_for_scope("ling", 300.0) is False
        assert tracker.is_active_for_scope("aveline", 300.0) is False


class TestIsActiveAnywhere:
    """is_active_anywhere：全局活跃判定。"""

    def test_any_recent_activity_is_true(self):
        """任意会话近期活跃即 True。"""
        tracker = UserActivityTracker(_StubStorage())
        tracker._activity_ts["some_cid"] = time.time()

        assert tracker.is_active_anywhere(300.0) is True

    def test_no_activity_is_false(self):
        """无记录返回 False。"""
        tracker = UserActivityTracker(_StubStorage())

        assert tracker.is_active_anywhere(300.0) is False

    def test_all_stale_is_false(self):
        """全部超出窗口返回 False。"""
        tracker = UserActivityTracker(_StubStorage())
        tracker._activity_ts["a"] = time.time() - 3600.0
        tracker._activity_ts["b"] = time.time() - 7200.0

        assert tracker.is_active_anywhere(300.0) is False

    def test_invalid_window_returns_false(self):
        """窗口参数非法时返回 False。"""
        tracker = UserActivityTracker(_StubStorage())
        tracker._activity_ts["a"] = time.time()

        assert tracker.is_active_anywhere("bad") is False

    def test_invalid_entries_skipped(self):
        """非法时间戳条目被跳过，合法条目仍生效。"""
        tracker = UserActivityTracker(_StubStorage())
        tracker._activity_ts["bad"] = "not-a-number"
        tracker._activity_ts["good"] = time.time()

        assert tracker.is_active_anywhere(300.0) is True


class TestLatestTsAndSnapshot:
    """latest_ts 与 snapshot。"""

    def test_latest_ts_returns_max(self):
        """返回最大的时间戳。"""
        tracker = UserActivityTracker(_StubStorage())
        tracker._activity_ts["a"] = 100.0
        tracker._activity_ts["b"] = 300.0

        assert tracker.latest_ts() == 300.0

    def test_latest_ts_empty_returns_zero(self):
        """无数据返回 0.0（供健康快照使用）。"""
        tracker = UserActivityTracker(_StubStorage())

        assert tracker.latest_ts() == 0.0

    def test_latest_ts_invalid_returns_zero(self):
        """全部非法时返回 0.0 而不是抛异常。"""
        tracker = UserActivityTracker(_StubStorage())
        tracker._activity_ts["bad"] = "not-a-number"

        assert tracker.latest_ts() == 0.0

    def test_snapshot_is_a_copy(self):
        """snapshot 返回浅拷贝，外部改动不影响内部状态。"""
        tracker = UserActivityTracker(_StubStorage())
        tracker.mark("cid")
        snap = tracker.snapshot()
        snap["injected"] = 1.0

        assert "injected" not in tracker.snapshot()


# ============================================================
# build_default_tracker
# ============================================================

class TestBuildDefaultTracker:
    """按配置构造 tracker。"""

    def test_returns_tracker_with_config_values(self, monkeypatch):
        """能从 DualRoleSettings 读到窗口配置。"""

        class _DualRole:
            peer_chat_user_activity_grace_seconds = 12.0
            peer_chat_user_idle_window_seconds = 34.0

        class _Settings:
            dual_role = _DualRole()

        import config.integrated_config as integrated

        monkeypatch.setattr(integrated, "get_settings", lambda: _Settings())
        tracker = build_default_tracker(_StubStorage())

        assert isinstance(tracker, UserActivityTracker)
        assert tracker._grace_seconds == 12.0
        assert tracker._idle_window_seconds == 34.0

    def test_falls_back_when_config_unavailable(self, monkeypatch):
        """配置不可用时用内置兜底值（保证可运行）。"""
        import config.integrated_config as integrated

        def _boom():
            raise RuntimeError("配置系统未初始化")

        monkeypatch.setattr(integrated, "get_settings", _boom)
        tracker = build_default_tracker(_StubStorage())

        assert tracker._grace_seconds == DEFAULT_ACTIVITY_GRACE_SECONDS
        assert tracker._idle_window_seconds == DEFAULT_IDLE_WINDOW_SECONDS

    def test_constants_have_expected_values(self):
        """关键常量值锁定（下游按这些数值设计节流与窗口）。"""
        assert USER_ACTIVITY_STATE_KEY == "last_user_activity_map"
        assert USER_ACTIVITY_PERSIST_MIN_GAP == 30.0
        assert DEFAULT_ACTIVITY_GRACE_SECONDS == 45.0
        assert DEFAULT_IDLE_WINDOW_SECONDS == 900.0


# ============================================================
# 调试日志与防御分支
# ============================================================


def _capture_logger(monkeypatch, module):
    """替换模块 logger，返回收集到的 (level, text) 列表。"""
    records = []

    class _Logger:
        def __getattr__(self, name):
            def _record(*args, **kwargs):
                records.append((name, " ".join(str(a) for a in args)))

            return _record

    monkeypatch.setattr(module, "logger", _Logger())
    return records


class TestObservabilityAndDefensiveBranches:
    """开关打开时要落日志；依赖不可用时降级返回，不把异常抛给调用方。"""

    def test_resolve_role_scope_returns_raw_when_registry_raises(self, monkeypatch):
        """注册表查询抛异常时退回小写原值，不让整条判定失效。"""
        import core.utils.data.scope_registry as scope_registry

        def _boom(raw):
            raise RuntimeError("注册表未就绪")

        monkeypatch.setattr(scope_registry, "matched_persona_scope", _boom)
        assert resolve_role_scope("  LING  ") == "ling"

    def test_mark_logs_when_debug_enabled(self, monkeypatch):
        """debug.peer_chat 打开时，标记用户活跃要落日志。"""
        import core.services.active_care.peer_chat.user_activity as ua

        tracker = UserActivityTracker(_StubStorage(), grace_seconds=60.0)
        monkeypatch.setattr(ua, "is_debug_enabled", lambda key: True)
        records = _capture_logger(monkeypatch, ua)

        tracker.mark("cid")
        assert any("用户活跃标记" in text for _, text in records)

    async def test_persist_failure_logs_when_debug_enabled(self, monkeypatch):
        """debug.peer_chat 打开时，持久化失败要落日志。"""
        import core.services.active_care.peer_chat.user_activity as ua

        tracker = UserActivityTracker(_StubStorage(fail=True), grace_seconds=60.0)
        monkeypatch.setattr(ua, "is_debug_enabled", lambda key: True)
        records = _capture_logger(monkeypatch, ua)

        await tracker._persist()
        assert any("持久化用户活跃时间戳失败" in text for _, text in records)

    async def test_load_failure_logs_when_debug_enabled(self, monkeypatch):
        """debug.peer_chat 打开时，加载用户活跃时间戳失败要落日志。"""
        import core.services.active_care.peer_chat.user_activity as ua

        tracker = UserActivityTracker(_StubStorage(fail=True), grace_seconds=60.0)
        monkeypatch.setattr(ua, "is_debug_enabled", lambda key: True)
        records = _capture_logger(monkeypatch, ua)

        await tracker.load()
        assert any("加载用户活跃时间戳失败" in text for _, text in records)

    async def test_cancelled_persist_task_is_silent(self, monkeypatch):
        """持久化任务被取消时 done 回调直接返回，不误报成异常。

        取消类断言不能用 `await task`（会把 CancelledError 抛进测试自己的协程），
        统一用 asyncio.wait 观察收尾。
        """
        import core.services.active_care.peer_chat.user_activity as ua

        records = _capture_logger(monkeypatch, ua)

        tracker = UserActivityTracker(_StubStorage(), grace_seconds=60.0)
        tracker.mark("cid")
        tasks = list(tracker._pending_tasks)
        assert len(tasks) == 1

        tasks[0].cancel()
        await asyncio.wait(tasks)
        for _ in range(5):
            await asyncio.sleep(0)

        assert tasks[0].cancelled() is True
        # 取消不是异常：不应出现 error 级日志
        assert [text for level, text in records if level == "error"] == []
        assert tracker._pending_tasks == set()

    async def test_persist_task_exception_is_logged_by_done_callback(self, monkeypatch):
        """持久化任务自身抛异常时，done 回调要落 error 日志而不是静默吞掉。

        ``_persist`` 内部已经 catch 掉所有异常，正常路径下这条回调分支走不到；
        这里把 ``_persist`` 换成会抛异常的协程，专门验证兜底回调存在且有效。
        断言用 ``asyncio.wait`` 观察收尾（异常不回灌到测试自己的协程）。
        """
        import core.services.active_care.peer_chat.user_activity as ua

        tracker = UserActivityTracker(_StubStorage(), grace_seconds=60.0)
        records = _capture_logger(monkeypatch, ua)

        async def _boom() -> None:
            raise RuntimeError("持久化任务炸了")

        monkeypatch.setattr(tracker, "_persist", _boom)

        tracker.mark("cid")
        tasks = list(tracker._pending_tasks)
        assert len(tasks) == 1

        await asyncio.wait(tasks)
        for _ in range(5):
            await asyncio.sleep(0)

        errors = [text for level, text in records if level == "error"]
        assert any("用户活跃持久化任务异常" in text for text in errors)
        assert tracker._pending_tasks == set()

    def test_is_active_for_scope_returns_false_when_registry_unimportable(
        self, monkeypatch
    ):
        """scope 注册表不可导入时降级为 False，不抛异常。"""
        import core.utils.data.scope_registry as scope_registry

        tracker = UserActivityTracker(_StubStorage(), grace_seconds=60.0)
        tracker.mark("private_10001")
        # 删掉属性后 `from ... import matched_persona_scope` 会抛 ImportError
        monkeypatch.delattr(scope_registry, "matched_persona_scope")

        assert tracker.is_active_for_scope("aveline", 300.0) is False
