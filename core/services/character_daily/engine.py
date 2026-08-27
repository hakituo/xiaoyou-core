"""
角色日常引擎（CharacterDailyEngine）

独立 async 主循环，管理所有已配置角色的日常生活：
- 每天生成活动计划
- 按计划推进角色当前活动
- 在活动间隙自然触发 peer chat
"""

from core.utils.logger import get_logger
import asyncio

import random
from datetime import datetime
from typing import Optional

from core.utils.time_utils import get_current_time

from core.services.character_daily.activity_model import (
    ActivityType,
    DailyPlan,
    DailyState,
    DO_NOT_DISTURB_ACTIVITIES,
)
from core.services.character_daily.activity_resolution import resolve_planned_activity
from core.services.character_daily.activity_state_sync import sync_current_activities
from core.services.character_daily.config import (
    CharacterDailyConfig,
    load_character_daily_config,
    load_schedule_templates,
)
from core.services.character_daily.daily_plan import DailyPlanGenerator
from core.services.character_daily.night_patch import build_night_patch_decision
from core.services.character_daily.plan_execution import sync_plan_execution
from core.services.character_daily.reply_policy import ReplyPolicyConfig
from core.services.character_daily.wakeup_recovery import build_wakeup_recovery_summary
from core.services.life_simulation import get_sleep_manager
from core.services.character_daily.engine_peer_chat_support import (
    execute_peer_chat,
    is_user_recently_active,
)
from core.services.character_daily.peer_chat_gate import should_trigger_peer_chat
from core.services.character_daily.state import DailyStateStore
from core.utils.logger import get_module_logger

logger = get_logger(__name__)

# 诊断专用 logger，写入 active_care_schedule.log（确保 peer chat 调度链路可观测）
_diag_logger = get_module_logger("ACTIVE_CARE", "active_care_schedule.log")

# 旧验证脚本和外部导入的兼容常量。
# 运行时计划生成与活动推进不再依赖此列表，而是以已加载模板键为真源。
# Peer Chat、Active Care 是否接入仍由各自的角色映射/白名单控制。
# 已知角色列表
# aveline/ling/yeye/rushuang：完整接入（character_daily + active_care + sleep_manager）
#               （yeye/rushuang 已接入独立 QQ 账号，可主动关怀/peer chat）
# xiaolu：仅 character_daily + sleep_manager 推进作息，不接 active_care
# mianmian：sensitive/ 下的私密人设，轻接入模式（仅作息推进）；
#               模板放在 character_daily_sensitive.yaml（已 gitignore）
KNOWN_ROLES = ("aveline", "ling", "yeye", "xiaolu", "rushuang", "mianmian", "chiba")
ROLE_NAMES = {
    "aveline": "七濑澪",
    "ling": "Ling",
    "yeye": "Coco",
    "xiaolu": "小鹿",
    "rushuang": "Frost",
    "mianmian": "Mian",
    "chiba": "Chiba",
}

# 全局单例
_character_daily_engine: Optional["CharacterDailyEngine"] = None


def get_character_daily_engine() -> Optional["CharacterDailyEngine"]:
    """获取 CharacterDailyEngine 全局单例"""
    return _character_daily_engine


def init_character_daily_engine() -> "CharacterDailyEngine":
    """初始化 CharacterDailyEngine 全局单例"""
    global _character_daily_engine
    if _character_daily_engine is None:
        _character_daily_engine = CharacterDailyEngine()
        logger.info("CharacterDailyEngine: 全局单例已初始化")
    return _character_daily_engine


class CharacterDailyEngine:
    """角色日常引擎

    独立的 async 主循环，每 2 分钟检查一次：
    1. 是否需要生成今天的计划（新一天开始时）
    2. 更新每个角色的当前活动
    3. 判定是否触发 peer chat
    """

    def __init__(self, config: CharacterDailyConfig = None):
        self._config = config or load_character_daily_config()
        self._templates = load_schedule_templates()
        # 角色日程固定走共享确定性算法。即使旧 app.yaml 误开 llm_plan，
        # 这里也不会导入或实例化 LLMPlanGenerator。
        self._generator = DailyPlanGenerator(self._templates)
        if self._config.llm_plan.enabled:
            logger.warning(
                "CharacterDailyEngine: 忽略已废弃的 llm_plan.enabled=true，"
                "角色计划固定使用确定性算法"
            )
        logger.info("CharacterDailyEngine: 使用共享确定性计划生成器")
        self._store = DailyStateStore()
        self._state = DailyState()
        self._sleep_manager = get_sleep_manager()

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._peer_chat_scheduler = None  # 延迟注入

    @property
    def config(self) -> CharacterDailyConfig:
        return self._config

    @property
    def state(self) -> DailyState:
        return self._state

    @property
    def managed_role_ids(self) -> tuple[str, ...]:
        """返回当前模板中全部角色；新增角色只需增加 YAML 模板。"""
        return self._generator.role_ids

    # ==================== 生命周期 ====================

    def start(self) -> bool:
        """启动引擎（幂等）"""
        if self._running and self._task and not self._task.done():
            return True
        if not self._config.enabled:
            logger.info("CharacterDailyEngine: 已禁用，不启动")
            return False

        self._running = True
        self._task = asyncio.create_task(self._run_loop())

        def _on_done(t: asyncio.Task):
            try:
                t.result()
            except asyncio.CancelledError:
                logger.info("CharacterDailyEngine: 主循环已取消")
            except Exception as e:
                logger.error("CharacterDailyEngine: 主循环异常退出: %s", e, exc_info=True)
                # 自动重启
                if self._running:
                    logger.warning("CharacterDailyEngine: 30s 后自动重启")
                    # P1-1: 使用 asyncio.get_event_loop_policy().get_event_loop()
                    # 在 done_callback 中可能不在协程上下文，需用 policy 获取 loop
                    asyncio.get_event_loop_policy().get_event_loop().call_later(
                        30, self.start
                    )

        self._task.add_done_callback(_on_done)
        logger.info("CharacterDailyEngine: 主循环已启动")
        return True

    async def stop(self):
        """停止引擎"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # 保存最终状态
        self._store.save(self._state, immediate=True)
        logger.info("CharacterDailyEngine: 已停止")

    def set_peer_chat_scheduler(self, scheduler):
        """注入 PeerChatScheduler 实例（用于执行 peer chat 脚本）"""
        self._peer_chat_scheduler = scheduler

    # ==================== 主循环 ====================

    async def _run_loop(self):
        """独立调度主循环"""
        logger.info("CharacterDailyEngine: 主循环开始")
        _diag_logger.info("CharacterDailyEngine: 主循环开始 (diag)")

        # 恢复上次的状态
        self._state = self._store.load()
        _diag_logger.info(
            "CharacterDailyEngine: 状态已加载 date=%s plans=%s",
            self._state.date,
            sorted(self._state.plans),
        )

        # 启动延迟
        _diag_logger.info("CharacterDailyEngine: 启动延迟 30s")
        await asyncio.sleep(30)

        tick_count = 0
        while self._running:
            try:
                tick_count += 1
                await self._tick()
            except asyncio.CancelledError:
                logger.info("CharacterDailyEngine: 主循环被取消")
                _diag_logger.info("CharacterDailyEngine: 主循环被取消 (diag)")
                break
            except Exception as e:
                logger.error("CharacterDailyEngine: 主循环异常: %s", e, exc_info=True)
                _diag_logger.error(
                    "CharacterDailyEngine: 主循环异常 (diag): %s", e, exc_info=True
                )

            # 计算下次检查间隔
            jitter = random.uniform(
                1.0 - self._config.check_interval_jitter,
                1.0 + self._config.check_interval_jitter,
            )
            sleep_seconds = self._config.check_interval_seconds * jitter
            try:
                await asyncio.sleep(sleep_seconds)
            except asyncio.CancelledError:
                break

        _diag_logger.info("CharacterDailyEngine: 主循环退出 (diag), 共执行 %d 次 tick", tick_count)
        logger.info("CharacterDailyEngine: 主循环退出")

    async def _tick(self):
        """单次检查周期"""
        now = get_current_time()
        today_str = now.strftime("%Y-%m-%d")
        _diag_logger.info(
            "CharacterDailyEngine: _tick hour=%d state_date=%s",
            now.hour, self._state.date,
        )

        # 1. 以模板键为真源补齐当天全部角色计划。即使当天新增模板并重启，
        # 也会只补缺失角色，不要求等到第二天。
        await self._ensure_daily_plans(today_str)
        role_ids = self.managed_role_ids

        # 2. 更新每个角色的当前活动（包裹 try/except 防止异常中断 _tick）
        # 记录切换前的活动，用于活动切换告别消息检测
        prev_activities: dict[str, ActivityType] = {}
        for role_id in role_ids:
            plan = self._state.get_plan(role_id)
            if plan:
                prev_activities[role_id] = plan.current_activity

        try:
            sync_current_activities(
                state=self._state,
                role_ids=role_ids,
                updater=self._update_current_activity,
                execution_updater=sync_plan_execution,
                store=self._store,
                now=now,
            )
        except Exception as e:
            _diag_logger.error(
                "CharacterDailyEngine: sync_current_activities 异常: %s", e, exc_info=True
            )
            logger.error("CharacterDailyEngine: sync_current_activities 异常: %s", e, exc_info=True)

        # 2.1 检测活动切换：从"可聊天"切到"忙碌/睡觉"时，若用户正在聊天，主动发告别消息
        try:
            from core.services.character_daily.activity_transition import (
                check_and_process_pending_on_activity_done,
                check_and_send_farewell_on_transition,
            )
            rp_config = getattr(self._config, "reply_policy", None) or ReplyPolicyConfig()
            for role_id in role_ids:
                prev_activity = prev_activities.get(role_id)
                plan = self._state.get_plan(role_id)
                if not plan or prev_activity is None:
                    continue
                new_activity = plan.current_activity
                if new_activity == prev_activity:
                    continue
                # 活动发生切换，检查是否需要发告别消息
                await check_and_send_farewell_on_transition(
                    engine=self,
                    role_id=role_id,
                    prev_activity=prev_activity,
                    new_activity=new_activity,
                    config=rp_config,
                )
                # 做事结束切换：主动处理做事期间累积的用户消息
                # （旧逻辑下累积消息只在用户再发新消息时才会被注入处理）
                try:
                    await check_and_process_pending_on_activity_done(
                        engine=self,
                        role_id=role_id,
                        prev_activity=prev_activity,
                        new_activity=new_activity,
                        config=rp_config,
                    )
                except Exception as done_e:
                    _diag_logger.error(
                        "CharacterDailyEngine: 做事结束累积消息处理异常 (role=%s): %s",
                        role_id, done_e, exc_info=True,
                    )
                    logger.error(
                        "CharacterDailyEngine: 做事结束累积消息处理异常 (role=%s): %s",
                        role_id, done_e, exc_info=True,
                    )
        except Exception as e:
            _diag_logger.error(
                "CharacterDailyEngine: 活动切换告别检测异常: %s", e, exc_info=True
            )
            logger.error("CharacterDailyEngine: 活动切换告别检测异常: %s", e, exc_info=True)

        # 3. 检查提醒分工协商（每日 1 次，不占 daily_limit）
        # PeerChatScheduler 主循环退出后，协商检查不再被调用，这里接管
        if self._peer_chat_scheduler:
            try:
                connections = await self._peer_chat_scheduler._get_multi_qq_connections()
                if len(connections) >= 2:
                    negotiation_triggered = await self._peer_chat_scheduler._try_negotiation_peer_chat(connections)
                    if negotiation_triggered:
                        _diag_logger.info("CharacterDailyEngine: 提醒分工协商已触发，跳过本轮普通 peer chat")
                        return
                    proactive_triggered = (
                        await self._peer_chat_scheduler._try_proactive_assignment_negotiation(
                            connections
                        )
                    )
                    if proactive_triggered:
                        _diag_logger.info(
                            "CharacterDailyEngine: 主动关怀时段分工协商已触发，"
                            "跳过本轮普通 peer chat"
                        )
                        return
            except Exception as e:
                _diag_logger.error("CharacterDailyEngine: 协商检查异常: %s", e, exc_info=True)

        # 5. 检查是否可以触发普通 peer chat
        _diag_logger.info(
            "CharacterDailyEngine: _tick 即将检查 peer chat, aveline=%s ling=%s",
            self._state.get_plan("aveline").current_activity.value if self._state.get_plan("aveline") else None,
            self._state.get_plan("ling").current_activity.value if self._state.get_plan("ling") else None,
        )
        await self._maybe_trigger_peer_chat(now)

    async def _ensure_daily_plans(self, today_str: str) -> tuple[str, ...]:
        """按模板动态补齐当日计划，并返回本轮新生成的角色 ID。"""
        is_new_day = self._state.date != today_str
        previous_state = self._state if is_new_day else None
        if is_new_day:
            logger.info("CharacterDailyEngine: 新的一天 %s，生成今日计划", today_str)
            _diag_logger.info("CharacterDailyEngine: 新的一天 %s，生成计划", today_str)
            self._state = DailyState(date=today_str)

        generated_roles: list[str] = []
        for role_id in self.managed_role_ids:
            if self._state.get_plan(role_id) is not None:
                continue
            plan = await self._generate_plan(role_id, today_str, previous_state)
            if plan is None:
                continue
            self._state.set_plan(plan)
            generated_roles.append(role_id)

        if is_new_day or generated_roles:
            self._store.save(self._state, immediate=True)
        if generated_roles:
            logger.info(
                "CharacterDailyEngine: 已生成角色计划 roles=%s",
                generated_roles,
            )
        return tuple(generated_roles)

    def _update_current_activity(self, plan: DailyPlan, now: datetime):
        """根据每日计划确定角色当前在做什么"""
        sleep_override = self._sleep_manager.get_activity_override(plan.role_id, now=now)
        sleep_summary = self._sleep_manager.get_summary(plan.role_id, now=now)
        planned_activity = resolve_planned_activity(plan, now)
        if sleep_override:
            plan.current_activity = ActivityType.from_str(sleep_override)
            return
        # 角色已清醒（FULLY_AWAKE/NIGHT_AWAKE/WAKING_UP）时，不再进入 DND 类活动。
        # overslept 标记一旦设置就只在跨天时清除，但 /wake 后 phase 已经是
        # fully_awake，此时若继续按 overslept_recovery 处理，reply_policy 会
        # 走 DND 分支静默累积消息，导致角色被唤醒后仍不回复用户。
        # WAKING_UP 也纳入：good_morning_proactive 在 waking_up 阶段触发了早安消息，
        # 说明角色已经醒了能聊天；waking_up 持续 1 小时，若这期间 DND 静默，
        # 会导致用户回复早安后被静默累积 1 小时（与主动发消息的行为矛盾）。
        phase = str(sleep_summary.get("phase") or "").strip().lower()
        is_conscious = phase in {"fully_awake", "night_awake", "waking_up"}
        if (
            sleep_summary.get("overslept")
            and not is_conscious
        ):
            plan.current_activity = ActivityType.OVERSLEPT_RECOVERY
            return
        if (
            sleep_summary.get("impact_level") in {"mild", "medium", "severe"}
            and planned_activity == ActivityType.IDLE
        ):
            plan.current_activity = ActivityType.SLEEP_RECOVERY
            return
        # 角色已清醒但计划槽位是 DND 活动（如 napping 午睡）时，
        # 不应继续按 DND 处理，否则 reply_policy 会静默累积消息导致角色被
        # 唤醒后仍不回复。改为 idle 让角色能正常回消息。
        if (
            planned_activity in DO_NOT_DISTURB_ACTIVITIES
            and is_conscious
        ):
            plan.current_activity = ActivityType.IDLE
            return
        plan.current_activity = planned_activity

    # ==================== Peer Chat 触发 ====================

    async def _maybe_trigger_peer_chat(self, now: datetime):
        """检查并触发 peer chat"""
        plan_a = self._state.get_plan("aveline")
        plan_l = self._state.get_plan("ling")
        if not plan_a or not plan_l:
            _diag_logger.warning(
                "PeerChat 诊断: plan 缺失 plan_a=%s plan_l=%s，跳过",
                bool(plan_a), bool(plan_l),
            )
            return

        user_active = is_user_recently_active(self)

        # 角色睡眠门禁：peer_chat 需要双方都参与，任一角色在睡觉就不触发
        # （peer_chat 是角色间互聊、不发消息给用户，用户睡觉不影响触发）
        character_sleeping = (
            plan_a.current_activity == ActivityType.SLEEPING
            or plan_l.current_activity == ActivityType.SLEEPING
        )

        should, initiator = should_trigger_peer_chat(now, plan_a, plan_l, self._config)

        # 诊断日志：每次都输出，用 ACTIVE_CARE logger 确保落盘
        _diag_logger.info(
            "PeerChat 诊断: hour=%d aveline=%s ling=%s user_active=%s char_sleeping=%s should=%s initiator=%s "
            "a_last=%d l_last=%d a_cnt=%d l_cnt=%d",
            now.hour,
            plan_a.current_activity.value if plan_a.current_activity else None,
            plan_l.current_activity.value if plan_l.current_activity else None,
            user_active,
            character_sleeping,
            should,
            initiator,
            int(plan_a.last_peer_chat_ts or 0),
            int(plan_l.last_peer_chat_ts or 0),
            plan_a.today_peer_chat_count,
            plan_l.today_peer_chat_count,
        )

        if user_active:
            return

        # 角色睡觉时不触发 peer_chat（peer_chat 需要双方都参与）
        if character_sleeping:
            return

        if not should or not initiator:
            return

        await self._execute_peer_chat(initiator, now)

    async def _execute_peer_chat(self, initiator: str, now: datetime):
        """执行一次 peer chat"""
        await execute_peer_chat(self, initiator, now)

    # ==================== 对外接口 ====================

    async def _generate_plan(self, role_id: str, date_str: str, yesterday_state):
        """用同角色昨日计划作为重复惩罚输入，确定性生成当日日程。"""
        try:
            previous_plan = (
                yesterday_state.get_plan(role_id)
                if yesterday_state is not None
                else None
            )
            return self._generator.generate(
                role_id,
                date_str,
                previous_plan=previous_plan,
            )
        except Exception as e:
            logger.error("CharacterDailyEngine: 生成 %s 计划失败: %s", role_id, e)
            return None

    def get_reply_policy_config(self) -> ReplyPolicyConfig:
        """获取被动回复策略配置（供 reply_policy 模块查询）"""
        return self._config.reply_policy

    def get_current_activity(self, role_id: str) -> ActivityType:
        """获取角色当前活动（供外部查询）"""
        plan = self._state.get_plan(role_id)
        if plan:
            return plan.current_activity
        return ActivityType.IDLE

    def refresh_current_activity(self, role_id: str) -> ActivityType:
        """强制重新计算指定角色当前活动，并返回最新值。

        场景：sleep_manager 状态被外部接口（如 /api/v1/life/sleep/wake）
        立即修改后，需要同步刷新 character_daily 的 plan.current_activity，
        避免下一次 tick（间隔可达 2 分钟）之前返回过时的活动状态。

        Args:
            role_id: 角色 ID（如 aveline/ling）

        Returns:
            刷新后的当前活动；若无 plan 则返回 IDLE。
        """
        plan = self._state.get_plan(role_id)
        if not plan:
            return ActivityType.IDLE
        self._update_current_activity(plan, get_current_time())
        if self._store is not None:
            try:
                self._store.save(self._state, immediate=True)
            except Exception as exc:
                logger.warning(
                    "CharacterDailyEngine: refresh_current_activity 持久化失败: %s",
                    exc,
                )
        return plan.current_activity

    def get_current_slot_remaining_seconds(self, role_id: str) -> float:
        """获取当前活动槽位的剩余秒数。

        用于 /跳过 命令计算窗口时长：跳过整个活动的剩余时间，
        而不是用固定的 300 秒窗口。

        Returns:
            剩余秒数；若无 plan 或无当前槽位，返回 -1.0 表示未知。
        """
        plan = self._state.get_plan(role_id)
        if not plan:
            return -1.0
        now = get_current_time()
        slot = plan.find_current_slot(now)
        if not slot:
            return -1.0
        remaining = (slot.planned_end - now).total_seconds()
        return max(0.0, remaining)

    def get_sleep_prompt_summary(self, role_id: str) -> str:
        """获取角色睡眠摘要文本。"""
        return self._sleep_manager.get_prompt_summary(role_id)

    def consume_sleep_patch_pending(self, role_id: str) -> bool:
        """消费角色熬夜后的补丁待处理标记。"""
        return self._sleep_manager.consume_patch_pending(role_id)

    def build_wakeup_recovery_context(self, role_id: str) -> str:
        """构建角色起床恢复文本。"""
        template = self._templates.get(role_id)
        if not template or not template.sleep_profile:
            return ""
        sleep_summary = self._sleep_manager.get_summary(role_id)
        patch = build_night_patch_decision(
            schedule_adjust_tendency=template.sleep_profile.schedule_adjust_tendency,
            diary_backfill_tendency=template.sleep_profile.diary_backfill_tendency,
            patch_pending=bool(sleep_summary.get("patch_pending")),
        )
        if patch.should_ignore and not sleep_summary.get("overslept"):
            return ""
        return build_wakeup_recovery_summary(
            role_name=ROLE_NAMES.get(role_id, role_id),
            sleep_summary=sleep_summary,
            schedule_adjust_tendency=template.sleep_profile.schedule_adjust_tendency,
            diary_backfill_tendency=template.sleep_profile.diary_backfill_tendency,
        )

    def get_activity_context_text(self, role_id: str) -> str:
        """获取角色当前活动的自然语言描述（供 Active Care prompt 注入）"""
        plan = self._state.get_plan(role_id)
        if not plan:
            return ""

        name = ROLE_NAMES.get(role_id, role_id)
        activity = plan.current_activity

        from core.services.character_daily.activity_model import ACTIVITY_VERBS_ONGOING
        verb = ACTIVITY_VERBS_ONGOING.get(activity, "休息")
        sleep_line = self.build_wakeup_recovery_context(role_id)
        if sleep_line:
            return f"{name}现在在{verb}\n{sleep_line}"
        return f"{name}现在在{verb}"

    def get_peer_chat_summary(self) -> str:
        """获取今日 peer chat 摘要（供 prompt 注入）"""
        plan_a = self._state.get_plan("aveline")
        plan_l = self._state.get_plan("ling")
        if not plan_a or not plan_l:
            return ""

        total = plan_a.today_peer_chat_count + plan_l.today_peer_chat_count
        if total == 0:
            return "今天还没聊过。"
        return f"今天已经聊过{total}次了。"
