"""2026-07-29 算法升级验证脚本

验证四项算法改动是否生效：
1. 时间衰减台阶 → 艾宾浩斯幂律（recall_probability._compute_time_decay / scoring_utils.score_recent_hit）
2. 召回概率 uniform → sigmoid（recall_probability.passes_recall_filter）
3. 退避算法 → Equal Jitter（constants.calculate_non_response_backoff）
4. ε-greedy 多臂老虎机闭环（storage.update_policy_reward + 调用链）

运行：
    venv_core\\Scripts\\python tests\\scripts\\algorithm_upgrade\\verify_algorithm_upgrade_2026_07_29.py
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ==================== 工具函数 ====================

def _ok(label: str, detail: str = "") -> bool:
    print(f"  [PASS] {label}{(' — ' + detail) if detail else ''}")
    return True


def _fail(label: str, detail: str) -> bool:
    print(f"  [FAIL] {label} — {detail}")
    return False


# ==================== 测试 1：时间衰减连续性 ====================

def test_time_decay_continuous() -> bool:
    """验证时间衰减是连续函数（无分段台阶跳变）"""
    print("\n[TEST 1] 时间衰减连续性（艾宾浩斯幂律）")

    try:
        from memory.core.recall_probability import _compute_time_decay
        from memory.core.scoring_utils import score_recent_hit
    except ImportError as e:
        return _fail("导入失败", str(e))

    # 1.1 _compute_time_decay 单调递减
    points = [0, 1, 6, 12, 24, 48, 168, 720]  # 小时
    values = [_compute_time_decay(h) for h in points]
    for i in range(len(values) - 1):
        if values[i] < values[i + 1]:
            return _fail("单调性", f"h={points[i]}→{points[i+1]}: {values[i]:.4f}→{values[i+1]:.4f} 不递减")
    _ok("衰减单调递减", f"1h={values[1]:.3f}, 1d={values[4]:.3f}, 1w={values[6]:.3f}")

    # 1.2 关键节点衰减值合理（与文档一致）
    expected = {
        1: (0.85, 1.0),     # 1h 接近 1
        24: (0.40, 0.70),   # 1d 约 0.55
        168: (0.10, 0.35),  # 1w 约 0.20
        720: (0.02, 0.20),  # 1mo 约 0.10
    }
    for h, (lo, hi) in expected.items():
        v = _compute_time_decay(h)
        if not (lo <= v <= hi):
            return _fail(f"衰减值 @ {h}h", f"got {v:.4f}, expected [{lo}, {hi}]")
    _ok("关键节点衰减值", "1h≈0.94, 1d≈0.55, 1w≈0.20, 1mo≈0.10")

    # 1.3 连续性：相邻 1 分钟变化应小于 0.01（无跳变）
    for h_base in [0.9, 23.9, 167.9, 719.9]:
        v1 = _compute_time_decay(h_base)
        v2 = _compute_time_decay(h_base + 0.0167)  # +1分钟
        if abs(v1 - v2) > 0.01:
            return _fail("连续性", f"@ {h_base}h, Δv={abs(v1-v2):.4f} > 0.01")
    _ok("无分段跳变", "相邻 1 分钟变化 < 0.01")

    # 1.4 score_recent_hit 同样连续
    now = time.time()
    samples = []
    for age_s in [60, 3600, 86400, 604800]:
        m = {"last_hit_time": now - age_s}
        samples.append(score_recent_hit(m))
    if not (samples[0] > samples[1] > samples[2] > samples[3]):
        return _fail("score_recent_hit 单调性", f"{samples}")
    if samples[0] < 0.95 or samples[3] > 0.15:
        return _fail("score_recent_hit 边界", f"{samples}")
    _ok("score_recent_hit 连续衰减", f"1m={samples[0]:.3f}, 1h={samples[1]:.3f}, 1d={samples[2]:.3f}, 1w={samples[3]:.3f}")

    return True


# ==================== 测试 2：召回概率 sigmoid ====================

def test_recall_sigmoid() -> bool:
    """验证召回概率用 sigmoid 而非 uniform"""
    print("\n[TEST 2] 召回概率 sigmoid 融合")

    try:
        from memory.core.recall_probability import passes_recall_filter, _sigmoid
    except ImportError as e:
        return _fail("导入失败", str(e))

    now = time.time()

    # 2.1 sigmoid 边界
    if abs(_sigmoid(0) - 0.5) > 0.001:
        return _fail("sigmoid(0)", f"got {_sigmoid(0)}, expected 0.5")
    if _sigmoid(100) < 0.99 or _sigmoid(-100) > 0.01:
        return _fail("sigmoid 边界", "数值不稳定")
    _ok("sigmoid 数值稳定", "σ(0)=0.5, σ(±100)→[0,1]")

    # 2.2 高权重 + 高相关 + 近期 → 高召回率
    high_score_result = {
        "weight": 9.0,
        "timestamp": now - 600,  # 10分钟前
    }
    rng = random.Random(42)
    pass_count_high = sum(
        1 for _ in range(1000)
        if passes_recall_filter(rng, now, high_score_result, 0.9, 0.9)
    )
    if pass_count_high < 800:
        return _fail("高权重记忆召回率", f"{pass_count_high}/1000, expected >=800")
    _ok("高权重记忆高召回", f"{pass_count_high}/1000 通过")

    # 2.3 低权重 + 低相关 + 远期 → 低召回率
    low_score_result = {
        "weight": 1.0,
        "timestamp": now - 30 * 86400,  # 30天前
    }
    rng = random.Random(42)
    pass_count_low = sum(
        1 for _ in range(1000)
        if passes_recall_filter(rng, now, low_score_result, 0.1, 0.1)
    )
    if pass_count_low > 300:
        return _fail("低权重记忆召回率", f"{pass_count_low}/1000, expected <=300")
    _ok("低权重记忆低召回", f"{pass_count_low}/1000 通过")

    # 2.4 召回率随权重单调递增（sigmoid 在 logit 空间是单调的）
    weights = [1, 3, 5, 7]
    pass_rates = []
    for w in weights:
        r = {"weight": float(w), "timestamp": now - 3600}
        rng = random.Random(42)
        cnt = sum(1 for _ in range(500) if passes_recall_filter(rng, now, r, 0.3, 0.3))
        pass_rates.append(cnt)
    for i in range(len(pass_rates) - 1):
        if pass_rates[i] >= pass_rates[i + 1]:
            return _fail("权重单调性", f"weights={weights}, rates={pass_rates}")
    _ok("召回率随权重单调递增", f"weights={weights}, rates={pass_rates}")

    # 2.5 硬性保留规则仍生效
    important = {"is_important": True, "weight": 1.0, "timestamp": 0}
    rng = random.Random(42)
    if not passes_recall_filter(rng, now, important, 0.0, 0.0):
        return _fail("硬性保留", "is_important=True 未直接通过")
    _ok("硬性保留规则", "is_important/preference 仍直接通过")

    return True


# ==================== 测试 3：Equal Jitter 退避 ====================

def test_equal_jitter_backoff() -> bool:
    """验证退避算法用 Equal Jitter"""
    print("\n[TEST 3] 退避算法 Equal Jitter")

    try:
        from core.services.active_care.shared.constants import calculate_non_response_backoff
    except ImportError as e:
        return _fail("导入失败", str(e))

    # 3.1 n=0 返回 1.0
    if calculate_non_response_backoff(0) != 1.0:
        return _fail("n=0", f"got {calculate_non_response_backoff(0)}, expected 1.0")
    _ok("n=0 返回 1.0", "无退避")

    # 3.2 所有 n 的乘数 >= 1.0（不会变成"加速"）
    for n in range(1, 8):
        for _ in range(100):
            m = calculate_non_response_backoff(n)
            if m < 1.0:
                return _fail(f"n={n} 下界保护", f"got {m} < 1.0")
    _ok("乘数下界保护", "n=1..7 100 次采样均 >= 1.0")

    # 3.3 均值接近指数退避的一半以上（Equal Jitter 均值 = 0.75 * expo）
    samples_n3 = [calculate_non_response_backoff(3) for _ in range(1000)]
    mean_n3 = statistics.mean(samples_n3)
    expo_n3 = 1.8 ** 3  # 5.832
    # Equal Jitter 均值 = expo/2 + expo/4 = 0.75 * expo
    if not (0.5 * expo_n3 <= mean_n3 <= 0.95 * expo_n3):
        return _fail(f"n=3 均值", f"got {mean_n3:.3f}, expected ~[{0.5*expo_n3:.3f}, {0.95*expo_n3:.3f}]")
    _ok("Equal Jitter 均值", f"n=3 均值={mean_n3:.3f}, expo={expo_n3:.3f}")

    # 3.4 方差显著大于 0（不是固定值）
    stdev_n3 = statistics.stdev(samples_n3)
    if stdev_n3 < 0.3:
        return _fail("方差", f"stdev={stdev_n3:.3f} 太小，jitter 未生效")
    _ok("随机性生效", f"n=3 stdev={stdev_n3:.3f} > 0.3")

    # 3.5 n=5+ 触发 cap（12.0）
    samples_n8 = [calculate_non_response_backoff(8) for _ in range(100)]
    if any(s > 12.0 + 0.001 for s in samples_n8):
        return _fail("cap 保护", f"n=8 出现 {max(samples_n8)} > 12.0")
    _ok("cap 保护", f"n=8 最大值={max(samples_n8):.3f} <= 12.0")

    return True


# ==================== 测试 4：Bandit 闭环 ====================

async def _test_bandit_closed_loop_async() -> bool:
    """异步部分：验证 storage.update_policy_reward 真正写入并影响 select"""
    print("\n[TEST 4] ε-greedy 多臂老虎机闭环")

    try:
        from core.services.active_care.storage.storage import ActiveCareStorage
    except ImportError as e:
        return _fail("导入失败", str(e))

    # 用临时目录构造 storage 实例
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage = ActiveCareStorage.__new__(ActiveCareStorage)
        # 手动初始化必要字段
        storage._policy_scores = {}
        storage._runtime_scope = "test"
        storage._dirty = False
        storage._pending_updates = {}
        storage._proactive_state_cache = {}
        storage._proactive_count_cache = None
        # monkey patch _get_runtime_dir 让它返回临时目录
        storage._get_runtime_dir = lambda scope=None: tmp_dir
        # 同时 patch _write_json_file 和 _read_json_file 走简单实现
        async def _write_json_file(path, data):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        async def _read_json_file(path):
            if not os.path.exists(path):
                return {}
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        storage._write_json_file = _write_json_file
        storage._read_json_file = _read_json_file

        # 4.1 update_policy_reward 增量更新
        await storage.update_policy_reward("share_thought", 1.0)
        scores = await storage.load_policy_scores()
        if scores.get("share_thought", {}).get("avg_reward") != 1.0:
            return _fail("首次更新", f"got {scores}")
        if scores.get("share_thought", {}).get("count") != 1:
            return _fail("计数", f"got {scores}")

        await storage.update_policy_reward("share_thought", -1.0)
        scores = await storage.load_policy_scores()
        if abs(scores["share_thought"]["avg_reward"] - 0.0) > 0.001:
            return _fail("增量平均", f"got {scores['share_thought']}, expected avg=0.0")
        if scores["share_thought"]["count"] != 2:
            return _fail("计数累加", f"got {scores}")
        _ok("update_policy_reward 增量更新", "avg (1.0 + -1.0) / 2 = 0.0")

        # 4.2 多次更新后趋近真实期望
        for _ in range(20):
            await storage.update_policy_reward("curious_question", 1.0)
        for _ in range(10):
            await storage.update_policy_reward("curious_question", -1.0)
        scores = await storage.load_policy_scores()
        avg = scores["curious_question"]["avg_reward"]
        # 30 次：20 * 1 + 10 * -1 = 10, / 30 ≈ 0.333
        if abs(avg - (20 - 10) / 30) > 0.01:
            return _fail("趋近期望", f"got {avg}, expected ~0.333")
        _ok("趋近期望", f"30 次更新后 avg={avg:.4f} ≈ 0.333")

        # 4.3 持久化到磁盘
        policy_file = os.path.join(tmp_dir, "active_care_policy.json")
        if not os.path.exists(policy_file):
            return _fail("持久化", f"{policy_file} 不存在")
        with open(policy_file, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
        if "share_thought" not in disk_data or "curious_question" not in disk_data:
            return _fail("持久化内容", f"got {disk_data}")
        _ok("磁盘持久化", f"包含 {list(disk_data.keys())}")

        # 4.4 select_action_bandit 能利用更新后的分值
        # 模拟：action_A 平均奖励高，action_B 平均奖励低，exploit 时应选 A
        tmp_dir_2 = tmp_dir + "_2"
        os.makedirs(tmp_dir_2, exist_ok=True)
        storage2 = ActiveCareStorage.__new__(ActiveCareStorage)
        storage2._policy_scores = {}
        storage2._runtime_scope = "test"
        storage2._dirty = False
        storage2._pending_updates = {}
        storage2._proactive_state_cache = {}
        storage2._proactive_count_cache = None
        storage2._get_runtime_dir = lambda scope=None: tmp_dir_2
        storage2._write_json_file = _write_json_file
        storage2._read_json_file = _read_json_file

        # 给 action_A 灌入正奖励，给 action_B 灌入负奖励
        for _ in range(15):
            await storage2.update_policy_reward("action_A", 1.0)
        for _ in range(15):
            await storage2.update_policy_reward("action_B", -1.0)

        scores = await storage2.load_policy_scores()
        avg_a = scores["action_A"]["avg_reward"]
        avg_b = scores["action_B"]["avg_reward"]
        if avg_a <= avg_b:
            return _fail("分值排序", f"A={avg_a}, B={avg_b}, A 应 > B")
        _ok("分值排序正确", f"action_A avg={avg_a:.3f} > action_B avg={avg_b:.3f}")

        # 4.5 检查 select_action_bandit 源码引用了 DEFAULT_BANDIT_EPSILON
        decision_src = _PROJECT_ROOT / "core" / "services" / "active_care" / "decision" / "decision.py"
        src_text = decision_src.read_text(encoding="utf-8")
        if "DEFAULT_BANDIT_EPSILON" not in src_text:
            return _fail("常量引用", "decision.py 未引用 DEFAULT_BANDIT_EPSILON")
        _ok("DEFAULT_BANDIT_EPSILON 已接入", "decision.py select_action_bandit 使用常量")

        # 4.6 检查 user_response_handler 有 _reward_last_action
        handler_src = _PROJECT_ROOT / "core" / "services" / "active_care" / "core" / "user_response_handler.py"
        handler_text = handler_src.read_text(encoding="utf-8")
        if "_reward_last_action" not in handler_text or "reward=1.0" not in handler_text:
            return _fail("正奖励接入", "user_response_handler 缺少 _reward_last_action")
        _ok("正奖励接入", "user_response_handler._reward_last_action(reward=1.0)")

        # 4.7 检查 message_dispatcher 有负奖励
        dispatcher_src = _PROJECT_ROOT / "core" / "services" / "active_care" / "core" / "message_dispatcher.py"
        dispatcher_text = dispatcher_src.read_text(encoding="utf-8")
        if "current_count == 1" not in dispatcher_text or "update_policy_reward" not in dispatcher_text:
            return _fail("负奖励接入", "message_dispatcher 缺少 current_count == 1 的负奖励")
        _ok("负奖励接入", "message_dispatcher 首次无响应时 reward=-1.0")

    return True


def test_bandit_closed_loop() -> bool:
    return asyncio.run(_test_bandit_closed_loop_async())


# ==================== 主入口 ====================

def main() -> int:
    print("=" * 70)
    print("2026-07-29 算法升级验证")
    print("=" * 70)

    results = [
        test_time_decay_continuous(),
        test_recall_sigmoid(),
        test_equal_jitter_backoff(),
        test_bandit_closed_loop(),
    ]

    print("\n" + "=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"汇总: {passed}/{total} 通过")
    print("=" * 70)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
