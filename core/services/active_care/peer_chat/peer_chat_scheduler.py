"""
双角色互聊独立调度器 (PeerChatScheduler)

将 peer chat 的调度从 ProactiveChecker 主循环中解耦，
作为独立 asyncio.Task 运行，不受 perform_check 超时限制。

特性：
- 独立调度循环，30分钟检查一次
- 指数退避恢复：连续失败 3 次后退避（30min → 1h → 2h → 最大4h）
- 健康状态持久化到 state.json
- 可观测：get_health_status() 返回完整运行状态

【模块结构】本类只保留「编排 + 状态装配」，具体职责已拆到同目录的 mixin：
- ``scheduler_lifecycle.py``  启动 / 停止 / 幂等保活
- ``scheduler_negotiation.py`` 分工协商（提醒 / 主动关怀时段）
- ``scheduler_role_cycle.py``  单角色互聊决策、连接解析
- ``scheduler_sleep_gate.py``  角色与用户睡眠门禁
- ``scheduler_health.py``      健康追踪、退避、手动触发
- ``user_activity.py``         用户活跃追踪（按角色隔离判定）
"""
import asyncio
import time
from typing import Dict, List, Optional

from core.utils.logger import get_module_logger
from config.debug_config import is_debug_enabled

from .scheduler_health import PeerChatHealthMixin
from .scheduler_lifecycle import PeerChatLifecycleMixin
from .scheduler_negotiation import PeerChatNegotiationMixin
from .scheduler_role_cycle import PeerChatRoleCycleMixin
from .scheduler_sleep_gate import PeerChatSleepGateMixin
from .user_activity import UserActivityTracker, build_default_tracker

logger = get_module_logger("PEER_CHAT_SCHEDULER", "peer_chat.log")

# 调度参数从 config/settings_life.py 的 DualRoleSettings 读取（PeerChatScheduler.__init__）
# 可通过环境变量 XIAOYOU_DUAL_ROLE_PEER_CHAT_* 覆盖


class PeerChatScheduler(
    PeerChatLifecycleMixin,
    PeerChatNegotiationMixin,
    PeerChatRoleCycleMixin,
    PeerChatSleepGateMixin,
    PeerChatHealthMixin,
):
    """双角色互聊独立调度器

    职责拆分见模块 docstring；本类只保留 __init__、主循环编排、
    用户活跃判定的对外委托，以及全局单例入口。
    """

    def __init__(self, storage, context, decision, executor, settings):
        self._storage = storage
        self._context = context
        self._decision = decision
        self._executor = executor
        self._settings = settings

        # 从 DualRoleSettings 读取调度参数（原硬编码值已收敛到 config）
        try:
            from config.integrated_config import get_settings
            _dr = get_settings().dual_role
            self._check_interval = float(_dr.peer_chat_check_interval_seconds)
            self._backoff_base_seconds = float(_dr.peer_chat_backoff_base_seconds)
            self._backoff_max_seconds = float(_dr.peer_chat_backoff_max_seconds)
            self._backoff_threshold = int(_dr.peer_chat_backoff_threshold)
        except Exception:
            # 配置不可用时回退到内置默认值（保证可运行）
            self._check_interval = 1800.0
            self._backoff_base_seconds = 1800.0
            self._backoff_max_seconds = 14400.0
            self._backoff_threshold = 3

        # 调度状态
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # 健康追踪
        self._last_run_ts: float = 0.0
        self._last_success_ts: float = 0.0
        self._consecutive_failures: int = 0
        self._last_error: str = ""
        self._today_count: int = 0
        self._next_check_ts: float = 0.0
        self._total_runs: int = 0
        self._total_successes: int = 0

        # 缓存的 QQ 连接（避免频繁扫描）
        self._cached_connections: List[Dict[str, str]] = []
        self._connections_cache_ts: float = 0.0
        self._connections_cache_ttl: float = 120.0  # 2分钟刷新

        # 用户活跃追踪：状态与判定已拆到 user_activity.UserActivityTracker
        # （原本散在本类里的 240 行状态 + 判定，见该模块 docstring）
        self._user_activity = build_default_tracker(storage)

        # 互聊开关关闭时，提示日志只打一次（避免每 30 分钟重复一条）
        self._disabled_flag_logged: str = ""

    def _dual_role_flag(self, key: str, default: bool = True) -> bool:
        """读取 dual_role 段的布尔开关。

        必须直读 DualRoleSettings（config/yaml/app.yaml -> dual_role.*），
        不能用 get_active_care_config：后者内部会强制拼 `life_simulation.` 前缀，
        而 peer_chat_enabled / peer_private_chat_enabled 并不在
        LifeSimulationSettings 下，读不到时永远回落到 default=True，
        表现为"明明关了开关，互聊照常调度、日志照常刷"。
        """
        try:
            from config.integrated_config import get_settings

            return bool(getattr(get_settings().dual_role, key, default))
        except Exception:
            return default

    def _log_disabled_once(self, flag_name: str) -> None:
        """互聊开关关闭的提示只输出一次。"""
        if self._disabled_flag_logged == flag_name:
            return
        self._disabled_flag_logged = flag_name
        logger.info(
            "PeerChatScheduler: %s 已禁用，跳过互聊调度（需排查互聊时再打开该开关）",
            flag_name,
        )


    # ==================== 主循环 ====================

    async def _run_loop(self):
        """独立调度主循环

        当 CharacterDailyEngine 启动后，本循环自动退出，
        将 peer chat 调度权移交给 CharacterDailyEngine。
        """
        logger.info("PeerChatScheduler: 主循环开始")
        # 启动时恢复用户活跃时间戳，避免重启后立刻误触发互聊
        await self._user_activity.load()
        # 启动延迟：等待 60s 让系统稳定
        await asyncio.sleep(60)

        while self._running:
            # 每次迭代都检查 CharacterDailyEngine 是否已接管
            if self._is_character_daily_active():
                logger.info(
                    "PeerChatScheduler: CharacterDailyEngine 已激活，"
                    "退出独立循环，移交 peer chat 调度权"
                )
                self._running = False
                break

            try:
                await self._run_single_cycle()
            except asyncio.CancelledError:
                logger.info("PeerChatScheduler: 主循环被取消")
                break
            except Exception as e:
                logger.error("PeerChatScheduler: 主循环异常: %s", e, exc_info=True)
                self._record_failure(str(e))

            # 计算下次检查间隔
            sleep_seconds = self._compute_next_interval()
            self._next_check_ts = time.time() + sleep_seconds
            if is_debug_enabled("peer_chat"):
                logger.info(
                    "PeerChatScheduler: 下次检查在 %ds 后 (failures=%d)",
                    int(sleep_seconds), self._consecutive_failures
                )
            try:
                await asyncio.sleep(sleep_seconds)
            except asyncio.CancelledError:
                break

        logger.info("PeerChatScheduler: 主循环退出")

    async def _run_single_cycle(self):
        """单次检查周期"""
        # 1. 检查开关（必须放在任何周期日志之前：关闭时直接静默返回）
        if not self._dual_role_flag("peer_chat_enabled"):
            self._log_disabled_once("peer_chat_enabled")
            return
        if not self._dual_role_flag("peer_private_chat_enabled"):
            self._log_disabled_once("peer_private_chat_enabled")
            return

        self._last_run_ts = time.time()
        self._total_runs += 1
        if is_debug_enabled("peer_chat"):
            logger.info("PeerChatScheduler: 开始第 %d 次检查", self._total_runs)

        # 2. 获取 QQ 连接
        connections = await self._get_multi_qq_connections()
        if len(connections) < 2:
            logger.info(
                "PeerChatScheduler: 非多QQ模式 (connections=%d)，跳过",
                len(connections)
            )
            return

        # 2.5 提醒分工协商检查（每日 1 次，不占 daily_limit）
        negotiation_triggered = await self._try_negotiation_peer_chat(connections)
        if negotiation_triggered:
            # 协商 peer chat 刚发过，本轮跳过普通 peer chat，避免一天内互聊过多
            logger.info("PeerChatScheduler: 提醒分工协商已触发，跳过本轮普通 peer chat")
            self._record_success()
            return

        # 2.6 主动关怀时段分工协商检查（每日 1 次，不占 daily_limit）
        proactive_negotiation_triggered = await self._try_proactive_assignment_negotiation(connections)
        if proactive_negotiation_triggered:
            logger.info("PeerChatScheduler: 主动关怀时段分工协商已触发，跳过本轮普通 peer chat")
            self._record_success()
            return

        # 3. 对每个角色执行检查（只遍历实际参与互聊的连接角色，即 aveline/ling）
        # 注：这里不再按 role_id 过滤。connections 本身已是「实际参与互聊的连接」，
        # 且 _check_and_trigger_for_role 开头会用 get_peer_role_ids(role_id) 做同样的
        # 有效性判断（无效则 return False 并打 INFO 日志），过滤职责在那一层。
        # 原先那层 `if role_id not in valid_role_ids: continue` 里的 valid_role_ids
        # 由同一个 connections 现场推导，条件恒为真、continue 永不执行，属误导性
        # 死代码（2026-09-23 删除，可观察行为零变化）。
        success_any = False
        for conn in connections:
            role_id = str(conn.get("role_id", "")).strip().lower()
            try:
                sent = await self._check_and_trigger_for_role(role_id, conn, connections)
                if sent:
                    success_any = True
            except Exception as e:
                logger.error(
                    "PeerChatScheduler: role=%s 检查异常: %s",
                    role_id, e, exc_info=True
                )

        if success_any:
            self._record_success()
            # 注：逐句社交事件注册已由 executor._run_peer_post_hooks 完成
            # （含真实台词内容，信息量远大于"互聊完成"总结），此处不再重复注册
        else:
            # 没有成功发送但不算异常，不增加失败计数
            logger.info("PeerChatScheduler: 本轮未发送（可能受频率限制或LLM决策不发）")




    # ==================== 用户活跃感知（委托 UserActivityTracker）====================
    # 状态与判定逻辑已拆到 core/services/active_care/peer_chat/user_activity.py。
    # 这里只保留薄委托，供外部（engine / goodnight_proactive / stream_orchestrator）
    # 沿用原有调用方式，避免破坏既有调用点。

    @property
    def _user_activity_tracker(self) -> UserActivityTracker:
        """用户活跃追踪器（内部/诊断访问用）。"""
        return self._user_activity

    def mark_user_activity(self, conversation_id: str) -> None:
        """标记用户在某个会话活跃（供外部聊天流程调用）。"""
        self._user_activity.mark(conversation_id)

    def is_user_recently_active(self, conversation_id: str) -> bool:
        """判断用户在该**具体会话**最近是否活跃（在 grace 期内）。"""
        return self._user_activity.is_active(conversation_id)

    def is_user_recently_active_for_scope(
        self,
        scope: str,
        window_seconds: float,
    ) -> bool:
        """判断用户最近是否在**指定角色自己的会话**里活跃。

        告别 / 晚安等「主动发消息给用户」的场景必须用这个，不能用全局判定 ——
        否则用户在跟 A 角色聊天时，B 角色会被误判成「用户正在聊天」并发出消息。
        """
        return self._user_activity.is_active_for_scope(scope, window_seconds)

    def is_within_idle_window(self, conversation_id: str) -> bool:
        """判断是否在用户空闲窗口内（用户最后消息后 idle_window 秒内才允许互聊）。"""
        return self._user_activity.is_within_idle_window(conversation_id)




# ==================== 全局单例 ====================

_peer_chat_scheduler: Optional[PeerChatScheduler] = None


def get_peer_chat_scheduler() -> Optional[PeerChatScheduler]:
    """获取 PeerChatScheduler 全局单例（可能为 None，未初始化时）"""
    return _peer_chat_scheduler


def init_peer_chat_scheduler(storage, context, decision, executor, settings) -> PeerChatScheduler:
    """初始化并返回 PeerChatScheduler 单例"""
    global _peer_chat_scheduler
    if _peer_chat_scheduler is None:
        _peer_chat_scheduler = PeerChatScheduler(
            storage=storage,
            context=context,
            decision=decision,
            executor=executor,
            settings=settings,
        )
        logger.info("PeerChatScheduler: 全局单例已初始化")
    return _peer_chat_scheduler
