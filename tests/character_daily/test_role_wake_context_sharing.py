"""验证：同 role 跨人设共享唤醒上下文。

验证目标（对应 2026-08-07 的优化）：
1. role_wake_context 的 per-scope DND 计数：同 role 不同人设会话共享，不同 role 隔离。
2. _evaluate_dnd 用 max(cid 累积, scope 累积) 算唤醒概率——切人设后不从 0 攒。
3. is_role_recently_woken 读取 per-scope 的 last_wake_ts。
4. evaluate_reply_state 在 DND 且同 role 最近被唤醒过时，宽限放行（should_reply=True）。
"""

from __future__ import annotations

import asyncio
import types
from typing import Any, Dict

import pytest

from core.services.character_daily import reply_policy
from core.services.character_daily import reply_policy_support
from core.services.character_daily.activity_model import ActivityType
from core.services.character_daily.config import ReplyPolicyConfig
from core.services.character_daily.role_wake_context import (
    bump_role_dnd_count,
    clear_role_dnd_count,
    get_role_dnd_count,
    reset_role_dnd_count,
)


@pytest.fixture(autouse=True)
def _clean_counts():
    """每个用例前后清空 scope 计数，避免互相污染。"""
    for s in ("ling", "aveline", "rushuang", "mianmian"):
        clear_role_dnd_count(s)
    yield
    for s in ("ling", "aveline", "rushuang", "mianmian"):
        clear_role_dnd_count(s)


# ---------- 1. role_wake_context：同 role 共享、不同 role 隔离 ----------

def test_scope_count_shared_across_personas_same_role():
    """人设A（cid_A）静默累积 3 条，人设B（cid_B）读到 scope 计数也是 3。"""
    for _ in range(3):
        bump_role_dnd_count("ling")
    # 人设B 新会话，自己 cid 级累积是 0，但 scope 级能读到 3
    assert get_role_dnd_count("ling") == 3


def test_scope_count_isolated_between_roles():
    """ling 的累积不影响 aveline。"""
    for _ in range(5):
        bump_role_dnd_count("ling")
    assert get_role_dnd_count("ling") == 5
    assert get_role_dnd_count("aveline") == 0


def test_reset_on_force_wake():
    """成功唤醒后 scope 计数清零。"""
    for _ in range(4):
        bump_role_dnd_count("ling")
    assert get_role_dnd_count("ling") == 4
    reset_role_dnd_count("ling")
    assert get_role_dnd_count("ling") == 0


# ---------- 2. _evaluate_dnd：用 max(cid, scope) 算唤醒概率 ----------

def test_evaluate_dnd_inherits_scope_count(monkeypatch):
    """人设B（cid 级 count=0）但 scope 级已累积 6 条（达到阈值），应直接强制唤醒。

    force_wake_probability 在 count>=threshold 时概率为 1.0，random<1.0 必然唤醒。
    """
    # 人设A 已经攒到阈值
    for _ in range(6):
        bump_role_dnd_count("ling")

    config = ReplyPolicyConfig()
    # 固定 random 让概率判定确定（threshold=6 → count>=6 时 prob=1.0）
    monkeypatch.setattr(reply_policy.random, "random", lambda: 0.0)

    decision = reply_policy._evaluate_dnd(
        role_id="ling",
        activity=ActivityType.SLEEPING,
        ac_sleeping=True,
        config=config,
        consecutive_dnd_count=0,  # 人设B 自己 cid 级是 0
        accumulated_messages=[],
    )
    assert decision.should_reply is True
    # 唤醒后 scope 计数应被重置
    assert get_role_dnd_count("ling") == 0
    assert "scope_count=6" in decision.reason


def test_evaluate_dnd_silent_bumps_scope_count(monkeypatch):
    """未唤醒的静默累积会同步递增 scope 计数。"""
    config = ReplyPolicyConfig()
    monkeypatch.setattr(reply_policy.random, "random", lambda: 0.99)  # 概率不中

    reply_policy._evaluate_dnd(
        role_id="ling",
        activity=ActivityType.SLEEPING,
        ac_sleeping=False,
        config=config,
        consecutive_dnd_count=0,
        accumulated_messages=[],
    )
    assert get_role_dnd_count("ling") == 1


# ---------- 3. is_role_recently_woken ----------

class _FakeSleepManager:
    def __init__(self, last_wake_ts: float):
        self._summary = {"last_wake_ts": last_wake_ts}

    def get_summary(self, scope: str) -> Dict[str, Any]:
        return dict(self._summary)


def test_is_role_recently_woken_within_grace(monkeypatch):
    import time as _time

    now = _time.time()
    fake = _FakeSleepManager(last_wake_ts=now - 60)  # 1 分钟前唤醒
    monkeypatch.setattr(
        reply_policy_support, "get_sleep_manager", lambda: fake, raising=False
    )
    # is_role_recently_woken 内部 from import get_sleep_manager，需 patch 源模块
    import core.services.life_simulation as life_sim_mod

    monkeypatch.setattr(life_sim_mod, "get_sleep_manager", lambda: fake, raising=False)
    assert reply_policy_support.is_role_recently_woken("ling", 1200.0) is True


def test_is_role_recently_woken_outside_grace(monkeypatch):
    import time as _time

    now = _time.time()
    fake = _FakeSleepManager(last_wake_ts=now - 3600)  # 1 小时前唤醒
    import core.services.life_simulation as life_sim_mod

    monkeypatch.setattr(life_sim_mod, "get_sleep_manager", lambda: fake, raising=False)
    assert reply_policy_support.is_role_recently_woken("ling", 1200.0) is False


def test_is_role_recently_woken_never_woken(monkeypatch):
    fake = _FakeSleepManager(last_wake_ts=0.0)
    import core.services.life_simulation as life_sim_mod

    monkeypatch.setattr(life_sim_mod, "get_sleep_manager", lambda: fake, raising=False)
    assert reply_policy_support.is_role_recently_woken("ling", 1200.0) is False


# ---------- 4. evaluate_reply_state：宽限放行 ----------

def test_evaluate_reply_state_grace_passthrough(monkeypatch):
    """DND + 同 role 最近被唤醒过 → 直接放行 should_reply=True。"""

    # 强制 is_role_recently_woken 返回 True（模拟人设A刚唤醒过 ling）
    monkeypatch.setattr(
        reply_policy, "is_role_recently_woken", lambda scope, grace: True
    )

    # 构造一个 is_dnd=True 的环境：activity=SLEEPING，ac_sleeping=False
    fake_engine = types.SimpleNamespace(
        get_current_activity=lambda scope: ActivityType.SLEEPING,
        refresh_current_activity=lambda scope: ActivityType.SLEEPING,
        state=types.SimpleNamespace(get_plan=lambda scope: None),
        get_reply_policy_config=lambda: ReplyPolicyConfig(),
    )
    monkeypatch.setattr(
        reply_policy, "get_character_daily_engine", lambda: fake_engine, raising=False
    )
    import core.services.character_daily.engine as cd_engine_mod

    monkeypatch.setattr(
        cd_engine_mod, "get_character_daily_engine", lambda: fake_engine
    )

    # 让 resolve_reply_scope 把 ling 人设解析到 "ling"
    monkeypatch.setattr(
        reply_policy,
        "resolve_reply_scope",
        lambda role_id, persona_filename="": "ling",
    )
    # ac 睡眠会话不活跃
    async def _ac_sleeping(scope):
        return False
    monkeypatch.setattr(reply_policy, "is_active_care_sleeping", _ac_sleeping)
    # 主动回接窗口不命中
    async def _proactive_elapsed(scope):
        return -1.0
    monkeypatch.setattr(
        reply_policy, "get_recent_proactive_sent_elapsed", _proactive_elapsed
    )
    # 手动中断窗口不命中
    monkeypatch.setattr(
        reply_policy, "get_manual_interrupt_window_state", lambda *a, **k: None
    )
    # 计划提示为空
    monkeypatch.setattr(
        reply_policy, "build_plan_transition_persona_hint", lambda *a, **k: ""
    )
    monkeypatch.setattr(
        reply_policy, "build_activity_return_reply_hint", lambda *a, **k: ""
    )

    decision = asyncio.run(
        reply_policy.evaluate_reply_state(
            role_id="aveline",
            persona_filename="qq/Ling_QQ_Master.json",
            conversation_id="user1__persona__ling_qq_master",
        )
    )
    assert decision.should_reply is True
    assert "role_recently_woken" in (decision.reason or "")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
