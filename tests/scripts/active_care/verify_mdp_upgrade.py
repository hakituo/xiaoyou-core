"""
题材感知 MDP 升级验证脚本

验证内容：
1. slot_tod 时段判断（day/night/late_night 边界）
2. classify_topic 题材分类（intent 主类 + detect_topic_category 子类型）
3. derive_mdp_state_from_proactive_state 状态派生（last_reply 时间戳判断）
4. MDP Q 表读写 + 增量更新（学习率衰减、do_nothing 跳过）
5. self_activity 守卫（自发做事消息不进学习闭环）
6. 端到端闭环模拟（发消息 → 用户回复 +1 / 忽略 -1）

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\active_care\\verify_mdp_upgrade.py
"""
import asyncio
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ==================== 测试工具 ====================

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def ok(self, name: str):
        self.passed += 1
        print(f"  [PASS] {name}")

    def fail(self, name: str, reason: str = ""):
        self.failed += 1
        msg = f"  [FAIL] {name}" + (f": {reason}" if reason else "")
        self.errors.append(msg)
        print(msg)

    def summary(self) -> bool:
        total = self.passed + self.failed
        print("\n========== 验证结果 ==========")
        print(f"通过: {self.passed}/{total}")
        print(f"失败: {self.failed}/{total}")
        if self.failed == 0:
            print("全部通过！")
        else:
            print("有失败项，请检查")
        return self.failed == 0


result = TestResult()


# ==================== 1. 时段判断 ====================

def test_slot_tod():
    """测试 slot_tod 时段判断"""
    print("\n--- 测试1: 时段判断 ---")
    from core.services.active_care.decision.mdp import slot_tod

    cases = [
        (datetime(2026, 1, 1, 0, 30), "late_night"),   # 凌晨
        (datetime(2026, 1, 1, 5, 59), "late_night"),
        (datetime(2026, 1, 1, 6, 0), "day"),            # 白天起点
        (datetime(2026, 1, 1, 17, 59), "day"),
        (datetime(2026, 1, 1, 18, 0), "night"),         # 晚上起点
        (datetime(2026, 1, 1, 22, 59), "night"),
        (datetime(2026, 1, 1, 23, 0), "late_night"),   # 深夜起点
    ]
    for dt, expected in cases:
        got = slot_tod(dt)
        if got == expected:
            result.ok(f"slot_tod({dt.hour:02d}:{dt.minute:02d}) -> {expected}")
        else:
            result.fail(f"slot_tod({dt.hour:02d}:{dt.minute:02d}) -> {expected}", f"got {got}")

    if slot_tod(None) == "day":
        result.ok("slot_tod(None) -> day (兜底)")
    else:
        result.fail("slot_tod(None) 应返回 day")


# ==================== 2. 题材分类 ====================

def test_classify_topic():
    """测试 classify_topic 题材分类"""
    print("\n--- 测试2: 题材分类 ---")
    from core.services.active_care.decision.topic_classifier import (
        classify_topic,
        topic_to_state_slot,
    )

    # intent 主类 + planned_topic 子类型
    cases = [
        # (intent, planned_topic, expected_prefix)
        ("share_thought", "今天吃了火锅", "share_thought:food"),
        ("curious_question", "你在学习高数吗", "curious_question:study"),
        ("bio_complaint", "", "bio_complaint:health"),   # 无子类型走 intent 默认
        ("emotional_support", "有点想你", "emotional_support:care"),
        ("share_peer_chat", "", "share_peer_chat:peer"),
        ("share_thought", "", "share_thought:general"),  # 空 topic 走 general
        ("do_nothing", "", "do_nothing:none"),
    ]
    for intent, planned, expected in cases:
        got = classify_topic(intent, planned_topic=planned)
        if got == expected:
            result.ok(f"classify_topic({intent}, {planned!r}) -> {expected}")
        else:
            result.fail(f"classify_topic({intent}, {planned!r}) -> {expected}", f"got {got}")

    # 空 intent 兜底
    got_empty = classify_topic("", "")
    if got_empty == "share_thought:general":
        result.ok("空 intent 兜底为 share_thought:general")
    else:
        result.fail("空 intent 兜底", got_empty)

    # 实际发送内容兜底（planned_topic 为空时）
    got_content = classify_topic("share_thought", planned_topic="", sent_content="晚上一起开车出去吧")
    if got_content == "share_thought:vehicle":
        result.ok("sent_content 兜底抽取 vehicle")
    else:
        result.fail("sent_content 兜底抽取 vehicle", got_content)

    # 题材槽位提取
    if topic_to_state_slot("share_thought:food") == "food":
        result.ok("topic_to_state_slot -> food")
    else:
        result.fail("topic_to_state_slot -> food", topic_to_state_slot("share_thought:food"))
    if topic_to_state_slot("general") == "general":
        result.ok("topic_to_state_slot(无冒号) -> general")
    else:
        result.fail("topic_to_state_slot(无冒号)", topic_to_state_slot("general"))


# ==================== 3. MDP 状态派生 ====================

def test_derive_state():
    """测试 derive_mdp_state_from_proactive_state"""
    print("\n--- 测试3: 状态派生 ---")
    from core.services.active_care.decision.mdp import (
        derive_mdp_state_from_proactive_state,
    )

    now_dt = datetime(2026, 1, 1, 10, 0)  # day 时段

    # 用户回复了上一条主动消息（last_user_interaction_ts >= last_sent_ts）
    state_replied = {
        "last_sent_topic": "share_thought:food",
        "last_sent_ts": 100.0,
        "last_user_interaction_ts": 200.0,
    }
    key = derive_mdp_state_from_proactive_state(state_replied, now_dt)
    if key == "day|food|replied":
        result.ok("回复后状态: day|food|replied")
    else:
        result.fail("回复后状态", key)

    # 用户未回复（无新交互）
    state_ignored = {
        "last_sent_topic": "curious_question:study",
        "last_sent_ts": 200.0,
        "last_user_interaction_ts": 100.0,
    }
    key2 = derive_mdp_state_from_proactive_state(state_ignored, now_dt)
    if key2 == "day|study|ignored":
        result.ok("忽略后状态: day|study|ignored")
    else:
        result.fail("忽略后状态", key2)

    # 从未发过主动消息
    state_empty = {}
    key3 = derive_mdp_state_from_proactive_state(state_empty, now_dt)
    if key3 == "day|general|none":
        result.ok("冷启动状态: day|general|none")
    else:
        result.fail("冷启动状态", key3)

    # 老数据无 last_sent_topic
    state_old = {"last_sent_ts": 100.0, "last_user_interaction_ts": 50.0}
    key4 = derive_mdp_state_from_proactive_state(state_old, now_dt)
    if key4 == "day|general|ignored":
        result.ok("老数据降级: day|general|ignored")
    else:
        result.fail("老数据降级", key4)


# ==================== 4. MDP Q 表读写与更新 ====================

async def test_mdp_q():
    """测试 MDP Q 表读写与增量更新"""
    print("\n--- 测试4: MDP Q 表 ---")
    from core.services.active_care.decision.mdp import ActiveCareMDP

    class FakeStorage:
        """内存版 storage，模拟 load_mdp_q/save_mdp_q"""

        def __init__(self):
            self._q = {}

        async def load_mdp_q(self):
            return dict(self._q)

        async def save_mdp_q(self, q):
            self._q = dict(q)

    fake = FakeStorage()
    mdp = ActiveCareMDP(fake)

    # 空表 select：由于 Q 空，会退化——直接测 update
    await mdp.update("day|food|replied", "share_thought", +1.0)
    q = await fake.load_mdp_q()
    entry = q.get("day|food|replied::share_thought")
    if entry and entry["count"] == 1 and 0.0 < entry["q"] <= 0.15:
        result.ok(f"首次更新 q={entry['q']} count=1")
    else:
        result.fail("首次更新", str(entry))

    # 再次同状态更新：q 应继续朝 +1 靠拢，count=2
    await mdp.update("day|food|replied", "share_thought", +1.0)
    q2 = await fake.load_mdp_q()
    entry2 = q2.get("day|food|replied::share_thought")
    if entry2 and entry2["count"] == 2 and entry2["q"] > entry["q"]:
        result.ok(f"二次更新 q 上升: {entry['q']} -> {entry2['q']}")
    else:
        result.fail("二次更新", str(entry2))

    # 负奖励
    await mdp.update("day|study|ignored", "curious_question", -1.0)
    q3 = await fake.load_mdp_q()
    entry3 = q3.get("day|study|ignored::curious_question")
    if entry3 and entry3["q"] < 0:
        result.ok(f"负奖励 q 为负: {entry3['q']}")
    else:
        result.fail("负奖励", str(entry3))

    # do_nothing 跳过
    await mdp.update("day|general|none", "do_nothing", +1.0)
    q4 = await fake.load_mdp_q()
    if "day|general|none::do_nothing" not in q4:
        result.ok("do_nothing 不进入学习闭环")
    else:
        result.fail("do_nothing 不应写入 Q 表")

    # select_action：有数据后应选择 Q 最高的动作
    q_src = {
        "day|food|replied::share_thought": {"q": 0.9, "count": 5},
        "day|food|replied::curious_question": {"q": 0.1, "count": 5},
    }

    async def _fake_load_q():
        return dict(q_src)

    with patch.object(fake, "load_mdp_q", new=_fake_load_q), patch(
        "core.services.active_care.decision.mdp.random.random", return_value=0.99  # 不探索
    ):
        chosen = await mdp.select_action("day|food|replied", ["share_thought", "curious_question"])
        if chosen == "share_thought":
            result.ok("利用: 选择 Q 最高动作 share_thought")
        else:
            result.fail("利用选择", chosen)

    # 探索路径
    with patch.object(fake, "load_mdp_q", new=_fake_load_q), patch(
        "core.services.active_care.decision.mdp.random.random", return_value=0.01  # 探索
    ), patch(
        "core.services.active_care.decision.mdp.random.choice",
        return_value="curious_question",
    ):
        chosen2 = await mdp.select_action("day|food|replied", ["share_thought", "curious_question"])
        if chosen2 == "curious_question":
            result.ok("探索: 随机选择")
        else:
            result.fail("探索选择", chosen2)


# ==================== 5. self_activity 守卫 ====================

async def test_self_activity_persist():
    """测试 state_persistence 中 self_activity 标记与题材记录"""
    print("\n--- 测试5: self_activity 守卫 ---")
    from core.services.active_care.storage.state_persistence import StatePersistence

    class FakeStorage2:
        async def save_proactive_state(self, updates, immediate=False, scope=None):
            self.saved = updates
            return updates

    fake = FakeStorage2()
    sp = StatePersistence(fake)

    # 自发做事：不记录题材，标记 self_activity=True
    await sp.persist_proactive_message(
        user_id="u", final_text="我去学习啦", full_raw_text="我去学习啦",
        message_type="text", llm_thought=None,
        sys_prompt_type="activity_return_proactive", now_ts=1.0,
        conversation_id="c", proactive_state={},
        planned_topic="", self_activity=True,
    )
    saved = fake.saved
    if saved.get("last_sent_self_activity") is True:
        result.ok("自发做事标记 self_activity=True")
    else:
        result.fail("自发做事应标记 self_activity", str(saved.get("last_sent_self_activity")))
    if not saved.get("last_sent_topic"):
        result.ok("自发做事不记录题材")
    else:
        result.fail("自发做事不应记录题材", saved.get("last_sent_topic"))

    # 正常主动关怀：记录题材，self_activity=False
    fake2 = FakeStorage2()
    sp2 = StatePersistence(fake2)
    await sp2.persist_proactive_message(
        user_id="u", final_text="吃饭了吗", full_raw_text="吃饭了吗",
        message_type="text", llm_thought=None,
        sys_prompt_type="share_thought", now_ts=2.0,
        conversation_id="c", proactive_state={},
        planned_topic="今天吃的啥", self_activity=False,
    )
    saved2 = fake2.saved
    if saved2.get("last_sent_topic") == "share_thought:food":
        result.ok(f"正常关怀记录题材: {saved2.get('last_sent_topic')}")
    else:
        result.fail("正常关怀应记录题材", saved2.get("last_sent_topic"))
    if saved2.get("last_sent_self_activity") is False:
        result.ok("正常关怀 self_activity=False")
    else:
        result.fail("正常关怀 self_activity 应为 False", saved2.get("last_sent_self_activity"))


# ==================== 6. 端到端闭环 ====================

async def test_reward_loop():
    """测试 reward 闭环（用户回复 +1 / 忽略 -1）与 self_activity 守卫"""
    print("\n--- 测试6: 奖励闭环 ---")
    from core.services.active_care.decision.mdp import (
        ActiveCareMDP,
        build_reward_state_key,
    )
    from core.services.active_care.storage.storage import ActiveCareStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch(
            "core.services.active_care.storage.storage.get_active_care_dir",
            return_value=Path(tmpdir),
        ):
            storage = ActiveCareStorage()
            mdp = ActiveCareMDP(storage)

            # 发消息后保存状态（正常关怀，题材 food）
            state = {
                "last_sent_type": "share_thought",
                "last_sent_topic": "share_thought:food",
                "last_sent_self_activity": False,
            }
            state_key = build_reward_state_key(
                last_topic="share_thought:food",
                now_dt=datetime(2026, 1, 1, 10, 0),
                last_reply="replied",
            )
            if state_key == "day|food|replied":
                result.ok(f"reward 状态键: {state_key}")
            else:
                result.fail("reward 状态键", state_key)

            # 用户回复 → +1
            await mdp.update(state_key, "share_thought", +1.0)
            q = await storage.load_mdp_q()
            if "day|food|replied::share_thought" in q:
                result.ok("正奖励写入 Q 表")
            else:
                result.fail("正奖励未写入 Q 表")

            # 忽略 → -1
            state_key_ig = build_reward_state_key(
                last_topic="share_thought:food",
                now_dt=datetime(2026, 1, 1, 10, 0),
                last_reply="ignored",
            )
            await mdp.update(state_key_ig, "share_thought", -1.0)
            q2 = await storage.load_mdp_q()
            if "day|food|ignored::share_thought" in q2 and q2["day|food|ignored::share_thought"]["q"] < 0:
                result.ok("负奖励写入 Q 表")
            else:
                result.fail("负奖励未写入 Q 表", str(q2.get("day|food|ignored::share_thought")))


# ==================== 主入口 ====================

async def main():
    print("=" * 60)
    print("题材感知 MDP 升级验证")
    print("=" * 60)

    test_slot_tod()
    test_classify_topic()
    test_derive_state()
    await test_mdp_q()
    await test_self_activity_persist()
    await test_reward_loop()

    return result.summary()


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
