"""题材感知的马尔可夫决策过程（MDP）层。

取代/增强原有的"只看时间"的 Contextual Bandit，把"题材"纳入决策与学习闭环。

状态 S（按用户确认，不含情绪）：
    S = (tod_slot, last_topic_sub, last_reply)
    - tod_slot:   时间段槽位（"day" / "night" / "late_night"），保留原按时间分流
    - last_topic_sub: 上一条主动关怀消息的"题材"子类型（sleep/food/study/care/...）
    - last_reply:    上一轮用户是否回复（"replied" / "ignored" / "none"）

动作 A：即主动关怀 intent（share_thought / curious_question / bio_complaint / ...）。

状态转移：S_t -> 执行动作 a -> 环境反馈 reward -> S_{t+1}。
这里 S 的主要来源是"上一条发的题材 + 用户回没回"，这正是用户要的
"她发我的类型 → 我回不回"的马尔可夫链。

奖励 R：
    +1.0  用户回复（视为该题材+动作组合受欢迎）
    -1.0  用户忽略（首次）后不再惩罚
    0.0   占位/未决

Q 表存储：active_care_mdp.json
    { "<state_key>::<action>": {"q": float, "count": int}, ... }

学习：增量 Q-learning 更新（带衰减的学习率，约等于 EMA，但与 bandit 解耦）。
"""
import random
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger
from core.services.active_care.decision.topic_classifier import topic_to_state_slot
from core.services.active_care.shared.constants import DEFAULT_BANDIT_EPSILON

logger = get_logger("ACTIVE_CARE_MDP")


# MDP 配置（从 active_care config 读取，失败用默认值）
MDP_EPSILON = 0.2            # 探索概率
MDP_LEARNING_RATE = 0.15     # Q-learning 学习率（保守，避免单次反馈剧烈震荡）
MDP_DISCOUNT = 0.9           # 折扣因子（转移价值，当前较弱依赖）
MDP_DEFAULT_Q = 0.0          # 未见过状态-动作对的初始 Q


def slot_tod(now_dt: Optional[datetime]) -> str:
    """把当前时间映射为时段槽位。"""
    if now_dt is None:
        return "day"
    try:
        h = now_dt.hour
    except (AttributeError, TypeError):
        return "day"
    if 6 <= h < 18:
        return "day"
    if 18 <= h < 23:
        return "night"
    return "late_night"  # 23..5


def build_state_key(
    tod_slot: str,
    last_topic_sub: str,
    last_reply: str,
) -> str:
    """构造 MDP 状态键。"""
    return f"{tod_slot}|{last_topic_sub}|{last_reply}"


def _normalize_state_components(
    tod_slot: str,
    last_topic: str,
    last_reply: str,
) -> tuple:
    tod = str(tod_slot or "day").strip() or "day"
    sub = topic_to_state_slot(str(last_topic or "")) or "general"
    reply = str(last_reply or "none").strip().lower()
    if reply not in ("replied", "ignored"):
        reply = "none"
    return tod, sub, reply


class ActiveCareMDP:
    """题材感知的 MDP 决策与学习器（无状态实例，状态从 storage 读）。"""

    def __init__(self, storage):
        self.storage = storage
        self.settings = None

    async def _load_q(self) -> Dict[str, Any]:
        return await self.storage.load_mdp_q()

    def _get_epsilon(self) -> float:
        try:
            from core.utils.config_accessor import get_active_care_config
            from config.integrated_config import get_settings

            if self.settings is None:
                self.settings = get_settings()
            return float(
                get_active_care_config(
                    "active_care_mdp_epsilon",
                    default=MDP_EPSILON,
                    settings=self.settings,
                )
                or MDP_EPSILON
            )
        except Exception:
            return MDP_EPSILON

    def _get_learning_rate(self) -> float:
        try:
            from core.utils.config_accessor import get_active_care_config
            from config.integrated_config import get_settings

            if self.settings is None:
                self.settings = get_settings()
            return float(
                get_active_care_config(
                    "active_care_mdp_learning_rate",
                    default=MDP_LEARNING_RATE,
                    settings=self.settings,
                )
                or MDP_LEARNING_RATE
            )
        except Exception:
            return MDP_LEARNING_RATE

    # ───────────────────────── 选择动作 ─────────────────────────

    async def select_action(
        self,
        state_key: str,
        actions: List[str],
        decision_ctx: Optional[Dict[str, Any]] = None,
    ) -> str:
        """基于 MDP 状态选择动作（ε-greedy over Q-table）。

        与 bandit 同构：探索随机、利用取该状态下 Q 最高的动作。
        若 state_key 全未见过，则退化为随机（与 bandit 冷启动一致）。
        """
        q = await self._load_q()

        # 探索
        if random.random() < self._get_epsilon():
            chosen = random.choice(actions)
            logger.info("Active Care MDP: 探索(随机) state=%s -> %s", state_key, chosen)
            return chosen

        # 利用：取当前状态下 Q 最高的动作
        def _q_of(a: str) -> float:
            entry = q.get(f"{state_key}::{a}")
            if entry:
                return float(entry.get("q", MDP_DEFAULT_Q))
            return MDP_DEFAULT_Q

        best = max(actions, key=_q_of)
        best_q = _q_of(best)
        logger.info(
            "Active Care MDP: 利用 state=%s -> %s (q=%.3f, 见过=%s)",
            state_key,
            best,
            best_q,
            f"{state_key}::{best}" in q,
        )
        return best

    # ───────────────────────── 更新 Q ─────────────────────────

    async def update(
        self,
        state_key: str,
        action: str,
        reward: float,
    ) -> None:
        """增量 Q-learning 更新单个 (state, action) 对。

        Q(s,a) <- Q(s,a) + alpha * (r - Q(s,a))
        （单步 TD(0)，无显式 next-state 估计——next state 在下次决策时自然读取，
         这里只更新"产生 reward 的那一步"的 Q 值，等价于把奖励归因到
         "上一状态 + 上次动作"组合，即"她发了X类型 + 用了Y动作 → 用户回/不回"。）
        """
        if not action or action == "do_nothing":
            # do_nothing 不进入学习闭环（没有"题材-回复"信号）
            return
        try:
            q = await self._load_q()
            key = f"{state_key}::{action}"
            entry = q.get(key) or {"q": MDP_DEFAULT_Q, "count": 0}
            count = int(entry.get("count", 0)) + 1
            old_q = float(entry.get("q", MDP_DEFAULT_Q))
            alpha = self._get_learning_rate() / max(1.0, count ** 0.5)  # 样本越多越稳
            new_q = old_q + alpha * (float(reward) - old_q)
            q[key] = {"q": round(new_q, 4), "count": count}
            await self.storage.save_mdp_q(q)
            logger.info(
                "Active Care MDP: 更新 state=%s action=%s reward=%.2f q=%.4f count=%d",
                state_key, action, reward, new_q, count,
            )
        except Exception as e:
            logger.debug("Active Care MDP: 更新失败: %s", e)


def derive_mdp_state_from_proactive_state(
    proactive_state: Dict[str, Any],
    now_dt: Optional[datetime],
) -> str:
    """从历史 proactive_state 派生"当前 MDP 状态"。

    这是 S_t，由"上一轮留下的信号"构成：
    - last_sent_topic（上一条题材子类型）
    - 上一轮用户是否回复（last_reply）：
      若用户最后一次互动时间戳 >= 上次主动消息发送时间戳，说明用户回复了
      上一条主动消息 → "replied"；否则视为被忽略/无回复 → "ignored"。
      用时间戳比较比 consecutive_non_responses 更可靠（后者在双QQ/重置
      时序下容易失真）。
    """
    last_topic = str(proactive_state.get("last_sent_topic") or "").strip()
    last_sent_ts = float(proactive_state.get("last_sent_ts") or 0.0)
    last_user_ts = float(proactive_state.get("last_user_interaction_ts") or 0.0)
    if last_sent_ts > 0 and last_user_ts > 0 and last_user_ts >= last_sent_ts:
        last_reply = "replied"
    elif last_sent_ts <= 0:
        # 从未主动发过消息：没有历史状态，标记 none
        last_reply = "none"
    else:
        last_reply = "ignored"

    tod = slot_tod(now_dt)
    _, sub, reply = _normalize_state_components(tod, last_topic, last_reply)
    return build_state_key(tod, sub, reply)


def build_reward_state_key(
    last_topic: str,
    now_dt: Optional[datetime],
    last_reply: str,
) -> str:
    """为 reward 更新构造状态键。

    reward 发生时（用户回复 / 首次忽略），状态由"上一次发送的题材" +
    "这一次的回复结果"构成，与时序独立的 now_dt 无关（tod 用当前时间）。
    """
    tod = slot_tod(now_dt)
    _, sub, reply = _normalize_state_components(tod, last_topic, last_reply)
    return build_state_key(tod, sub, reply)
