"""
双角色互聊独立调度器 (PeerChatScheduler)

将 peer chat 的调度从 ProactiveChecker 主循环中解耦，
作为独立 asyncio.Task 运行，不受 perform_check 超时限制。

特性：
- 独立调度循环，30分钟检查一次
- 指数退避恢复：连续失败 3 次后退避（30min → 1h → 2h → 最大4h）
- 健康状态持久化到 state.json
- 可观测：get_health_status() 返回完整运行状态
"""
import asyncio
import os
import time
from typing import Any, Dict, List, Optional

from core.utils.logger import get_module_logger
from config.debug_config import is_debug_enabled
from core.utils.config_accessor import get_active_care_config
from core.utils.time_utils import get_current_time

logger = get_module_logger("PEER_CHAT_SCHEDULER", "peer_chat.log")

# 调度参数从 config/settings_life.py 的 DualRoleSettings 读取（PeerChatScheduler.__init__）
# 可通过环境变量 XIAOYOU_DUAL_ROLE_PEER_CHAT_* 覆盖


class PeerChatScheduler:
    """双角色互聊独立调度器"""

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

        # 用户活跃追踪（参数从 DualRoleSettings 读取）
        self._last_user_activity_ts: Dict[str, float] = {}
        try:
            from config.integrated_config import get_settings
            _dr = get_settings().dual_role
            self._user_activity_grace_seconds = float(_dr.peer_chat_user_activity_grace_seconds)
            self._user_idle_window_seconds = float(_dr.peer_chat_user_idle_window_seconds)
        except Exception:
            self._user_activity_grace_seconds = 45.0
            self._user_idle_window_seconds = 900.0
        # 持久化节流：记录上次写盘时间，避免每条用户消息都触发磁盘IO
        self._last_user_activity_persist_ts: float = 0.0
        self._user_activity_restored: bool = False
        # P1-2: 跟踪用户活跃持久化任务，防止被 GC 后丢失活跃时间戳
        self._pending_persist_tasks: set = set()

    # ==================== 生命周期 ====================

    @staticmethod
    def _is_character_daily_active() -> bool:
        """检查 CharacterDailyEngine 是否正在运行"""
        try:
            from core.services.character_daily.engine import get_character_daily_engine
            engine = get_character_daily_engine()
            return engine is not None and engine._running
        except Exception:
            return False

    def start(self) -> bool:
        """启动调度循环（幂等）

        如果 CharacterDailyEngine 正在运行，则不启动独立循环
        （peer chat 触发由 CharacterDailyEngine 管理）。
        """
        if self._is_character_daily_active():
            logger.info(
                "PeerChatScheduler: CharacterDailyEngine 已接管 peer chat 调度，"
                "跳过独立循环启动"
            )
            self._running = True  # 标记为 running，保证 ensure_running 不反复尝试
            return True

        if self._running and self._task and not self._task.done():
            return True
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

        def _on_done(t: asyncio.Task):
            try:
                t.result()
            except asyncio.CancelledError:
                logger.info("PeerChatScheduler: 调度循环已取消")
            except Exception as e:
                logger.error("PeerChatScheduler: 调度循环异常退出: %s", e, exc_info=True)
                # 自动重启（最多延迟 60s）
                if self._running and not self._is_character_daily_active():
                    logger.warning("PeerChatScheduler: 60s 后自动重启调度循环")
                    # P1-1: 使用 asyncio.get_event_loop_policy().get_event_loop()
                    # 在 done_callback 中可能不在协程上下文，需用 policy 获取 loop
                    asyncio.get_event_loop_policy().get_event_loop().call_later(
                        60, self.start
                    )

        self._task.add_done_callback(_on_done)
        logger.info("PeerChatScheduler: 调度循环已启动 (interval=%ds)", self._check_interval)
        return True

    async def stop(self):
        """停止调度循环"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PeerChatScheduler: 调度循环已停止")

    def ensure_running(self) -> bool:
        """确保调度器正在运行（供 ProactiveChecker 心跳调用）

        如果 CharacterDailyEngine 已接管，则直接返回 True。
        """
        if self._is_character_daily_active():
            return True
        if not self._running:
            return self.start()
        if self._task and self._task.done():
            logger.warning("PeerChatScheduler: 调度器已停止，重启中")
            return self.start()
        return True

    # ==================== 主循环 ====================

    async def _run_loop(self):
        """独立调度主循环

        当 CharacterDailyEngine 启动后，本循环自动退出，
        将 peer chat 调度权移交给 CharacterDailyEngine。
        """
        logger.info("PeerChatScheduler: 主循环开始")
        # 启动时恢复用户活跃时间戳，避免重启后立刻误触发互聊
        await self._load_user_activity()
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
        self._last_run_ts = time.time()
        self._total_runs += 1
        logger.info("PeerChatScheduler: 开始第 %d 次检查", self._total_runs)

        # 1. 检查开关
        peer_chat_enabled = bool(get_active_care_config(
            "peer_chat_enabled", default=True, settings=self._settings
        ))
        if not peer_chat_enabled:
            logger.info("PeerChatScheduler: peer_chat 已禁用，跳过")
            return

        peer_private_enabled = bool(get_active_care_config(
            "peer_private_chat_enabled", default=True, settings=self._settings
        ))
        if not peer_private_enabled:
            logger.info("PeerChatScheduler: peer_private_chat 已禁用，跳过")
            return

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
        valid_role_ids = {
            str(c.get("role_id", "")).strip().lower() for c in connections
        }

        success_any = False
        for conn in connections:
            role_id = str(conn.get("role_id", "")).strip().lower()
            if role_id not in valid_role_ids:
                continue
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

    async def _try_negotiation_peer_chat(self, connections: List[Dict[str, str]]) -> bool:
        """提醒分工协商检查（每日 1 次）

        条件：
        - ReminderAssignmentRegistry.needs_negotiation() == True（pending 状态）
        - 有待发提醒候选（planned_topic / user_health_reminder 类）
        - 双 QQ 模式
        - 任一角色不在 SLEEPING 状态（修复 QR-20260718-PEER-CHAT-SLEEP-GUARD）

        触发后：
        - 调用 generate_peer_script(negotiation_reminders=...)
        - 剧本分发成功后，由 PeerScriptGenerator 自动解析分工并写入 registry
        - 不占 daily_limit（系统调度需求）

        Returns:
            True 表示触发了协商 peer chat
        """
        try:
            from core.services.active_care.storage.reminder_assignment_registry import (
                get_reminder_assignment_registry,
            )
            registry = get_reminder_assignment_registry()

            # 1. 检查是否需要协商
            if not await registry.needs_negotiation():
                return False

            # 1.5 睡眠门禁：任一角色在 SLEEPING 时跳过协商，保持 pending 等起床后重试
            # （修复 QR-20260718-PEER-CHAT-SLEEP-GUARD：角色声明睡了不应被拉去商量提醒分工）
            # 说明：只拦 SLEEPING，不拦 NIGHT_AWAKE（被叫醒后的清醒状态，可参与协商）
            # 仅检查实际参与互聊的连接角色（aveline/ling），非常驻角色（Frost/Coco）
            # 无真实客户端连接，不应被纳入 peer chat 的睡眠门禁与协商范围。
            all_role_ids = [
                str(c.get("role_id", "")).strip().lower() for c in connections
            ]
            if await self._is_any_character_sleeping(all_role_ids):
                logger.info(
                    "PeerChatScheduler: 协商跳过，角色在睡眠中，保持 pending 等起床后重试"
                )
                return False

            # 注：peer_chat 是角色间互聊，不发消息给用户，不会吵醒用户，
            # 故不再设用户睡眠门禁；上方角色睡眠门禁已保证角色睡觉时不触发。
            # 2. 收集今日待发提醒
            reminders = await self._collect_today_reminders()
            if not reminders:
                logger.info("PeerChatScheduler: 无待发提醒，跳过协商")
                # 标记为 completed（无提醒可协商），避免后续重复检查
                await registry.mark_negotiation_status("completed", reason="无待发提醒")
                return False

            # 3. 写入 pending 列表到 registry（供 prompt 注入和调试）
            await registry.set_pending_reminders(reminders)

            # 4. 选第一个角色作为发起者（协商 peer chat 是角色互聊，由谁发起都行）
            # N 角色系统:取第一个有效角色,peer 取其第一个 peer
            init_conn = connections[0]
            role_id = str(init_conn.get("role_id", "")).strip().lower()
            if role_id not in all_role_ids:
                role_id = all_role_ids[0] if all_role_ids else "aveline"
            from core.services.dual_role.personas import get_peer_role_ids
            peer_ids = get_peer_role_ids(role_id)
            peer_role_id = peer_ids[0] if peer_ids else ""
            if not peer_role_id:
                logger.warning("PeerChatScheduler: 协商跳过，无 peer 角色")
                return False
            peer_qq_id = self._resolve_peer_qq_id(peer_role_id)
            if not peer_qq_id:
                logger.warning("PeerChatScheduler: 协商跳过，peer_qq_id 为空")
                return False

            # 5. 用户活跃检查（协商 peer chat 也遵守用户活跃规则）
            base_cid = f"private_{master_qq_id}" if (master_qq_id := self._resolve_master_qq_id()) else "default"
            if self.is_user_recently_active(base_cid):
                logger.info("PeerChatScheduler: 协商跳过，用户最近活跃")
                return False

            logger.info(
                "PeerChatScheduler: 触发提醒分工协商 (role=%s, reminders=%d)",
                role_id, len(reminders),
            )

            # 6. 调用 generate_peer_script 进入协商模式
            sent = await self._executor.generate_peer_script(
                role_id=role_id,
                peer_qq_id=peer_qq_id,
                topic="提醒分工",
                situation="今天有几条提醒要发给主人，我们商量下谁发哪条",
                opening_idea="",
                persona_filename=init_conn.get("persona_filename", ""),
                negotiation_reminders=reminders,
            )

            if sent:
                logger.info("PeerChatScheduler: 提醒分工协商 peer chat 发送成功")
                # 协商 peer chat 也更新 last_peer_chat_ts，避免普通 peer chat 紧接着触发
                scope = role_id if role_id in all_role_ids else "aveline"
                self._storage.set_runtime_scope(scope)
                state_data = await self._storage.get_proactive_state()
                state_data["last_peer_chat_ts"] = time.time()
                date_key = get_current_time().strftime("%Y-%m-%d")
                global_count = int(state_data.get(f"peer_chat_global_count_{date_key}", 0))
                state_data[f"peer_chat_global_count_{date_key}"] = global_count + 1
                await self._storage.save_proactive_state(state_data)
                return True
            else:
                logger.warning("PeerChatScheduler: 提醒分工协商 peer chat 发送失败")
                # 标记为 failed 避免重复触发
                try:
                    await registry.mark_negotiation_status("failed", reason="剧本发送失败")
                except Exception:
                    pass
                return False

        except Exception as e:
            logger.error(
                "PeerChatScheduler: 提醒分工协商异常: %s", e, exc_info=True
            )
            # 标记为 failed 避免每 2 分钟重复触发（needs_negotiation 只在 pending 时返回 True）
            try:
                from core.services.active_care.storage.reminder_assignment_registry import (
                    get_reminder_assignment_registry,
                )
                registry = get_reminder_assignment_registry()
                await registry.mark_negotiation_status(
                    "failed", reason=f"协商异常: {e}"
                )
                logger.info("PeerChatScheduler: 协商状态已标记为 failed，今日不再重试")
            except Exception:
                pass
            return False

    async def _collect_today_reminders(self) -> List[Dict[str, Any]]:
        """收集今日待发提醒候选列表

        从 daily_push_priority 候选中过滤出"提醒类"（planned_topic / user_health_reminder），
        返回简化的 [{reminder_id, title}, ...] 列表供协商 prompt 使用。
        """
        try:
            from core.services.active_care.decision.daily_push_priority import (
                build_daily_push_priority_candidates,
            )
            candidates = build_daily_push_priority_candidates(
                workspace_snapshot={},
                priority_focus={},
                urgent_needs=[],
            )
            # 过滤提醒类
            reminder_intents = {"planned_topic", "user_health_reminder"}
            reminders = []
            for c in candidates:
                if str(c.get("suggested_intent") or "") in reminder_intents:
                    reminders.append({
                        "reminder_id": str(c.get("id") or ""),
                        "title": str(c.get("title") or ""),
                    })
            return reminders
        except Exception as e:
            logger.warning("PeerChatScheduler: 收集待发提醒失败: %s", e)
            return []

    async def _try_proactive_assignment_negotiation(
        self, connections: List[Dict[str, str]]
    ) -> bool:
        """主动关怀时段分工协商检查（每日 1 次）

        条件：
        - ProactiveAssignmentRegistry.needs_negotiation() == True（pending 状态）
        - 双 QQ 模式
        - 用户不在活跃窗口内

        触发后：
        - 调用 generate_peer_script(proactive_assignment_mode=True)
        - 剧本分发成功后，由 PeerScriptGenerator 自动解析分工并写入 registry
        - 不占 daily_limit（系统调度需求）

        Returns:
            True 表示触发了协商 peer chat
        """
        try:
            from core.services.active_care.storage.proactive_assignment_registry import (
                get_proactive_assignment_registry,
            )
            registry = get_proactive_assignment_registry()

            # 1. 检查是否需要协商
            if not await registry.needs_negotiation():
                return False

            # 1.5 角色睡眠门禁：任一角色在 SLEEPING 时跳过，保持 pending 等起床后重试
            # （与提醒分工协商一致：角色睡觉时不应被拉去商量主动关怀分工）
            # 仅检查实际参与互聊的连接角色（aveline/ling），非常驻角色（Frost/Coco）
            # 无真实客户端连接，不应被纳入 peer chat 的睡眠门禁与协商范围。
            all_role_ids = [
                str(c.get("role_id", "")).strip().lower() for c in connections
            ]
            if await self._is_any_character_sleeping(all_role_ids):
                logger.info(
                    "PeerChatScheduler: 主动关怀分工协商跳过，角色在睡眠中，保持 pending 等起床后重试"
                )
                return False

            # 2. 用户活跃检查（协商 peer chat 也遵守用户活跃规则）
            base_cid = f"private_{master_qq_id}" if (master_qq_id := self._resolve_master_qq_id()) else "default"
            if self.is_user_recently_active(base_cid):
                logger.info("PeerChatScheduler: 主动关怀分工协商跳过，用户最近活跃")
                return False

            # 3. 收集所有角色的今日状态简述（供 prompt 注入,N 角色动态）
            role_states = {
                rid: self._get_persona_state_brief(rid)
                for rid in all_role_ids
            }
            # 向后兼容:aveline_state/ling_state 取前两个角色
            aveline_state = role_states.get("aveline", "")
            ling_state = role_states.get("ling", "")

            # 4. 选第一个角色作为发起者
            init_conn = connections[0]
            role_id = str(init_conn.get("role_id", "")).strip().lower()
            if role_id not in all_role_ids:
                role_id = all_role_ids[0] if all_role_ids else "aveline"
            from core.services.dual_role.personas import get_peer_role_ids
            peer_ids = get_peer_role_ids(role_id)
            peer_role_id = peer_ids[0] if peer_ids else ""
            if not peer_role_id:
                logger.warning("PeerChatScheduler: 主动关怀分工协商跳过，无 peer 角色")
                return False
            peer_qq_id = self._resolve_peer_qq_id(peer_role_id)
            if not peer_qq_id:
                logger.warning("PeerChatScheduler: 主动关怀分工协商跳过，peer_qq_id 为空")
                return False

            logger.info(
                "PeerChatScheduler: 触发主动关怀时段分工协商 (role=%s)",
                role_id,
            )

            # 5. 调用 generate_peer_script 进入主动关怀分工协商模式
            sent = await self._executor.generate_peer_script(
                role_id=role_id,
                peer_qq_id=peer_qq_id,
                topic="主动关怀分工",
                situation="今天我们商量下谁在上午、下午、晚上去给主人发主动消息",
                opening_idea="",
                persona_filename=init_conn.get("persona_filename", ""),
                proactive_assignment_mode=True,
                aveline_state=aveline_state,
                ling_state=ling_state,
                role_states=role_states,
            )

            if sent:
                logger.info("PeerChatScheduler: 主动关怀时段分工协商 peer chat 发送成功")
                # 协商 peer chat 也更新 last_peer_chat_ts，避免普通 peer chat 紧接着触发
                scope = role_id if role_id in all_role_ids else "aveline"
                self._storage.set_runtime_scope(scope)
                state_data = await self._storage.get_proactive_state()
                state_data["last_peer_chat_ts"] = time.time()
                date_key = get_current_time().strftime("%Y-%m-%d")
                global_count = int(state_data.get(f"peer_chat_global_count_{date_key}", 0))
                state_data[f"peer_chat_global_count_{date_key}"] = global_count + 1
                await self._storage.save_proactive_state(state_data)
                return True
            else:
                logger.warning("PeerChatScheduler: 主动关怀时段分工协商 peer chat 发送失败")
                # 标记为 failed 避免重复触发
                try:
                    await registry.mark_negotiation_status("failed", reason="剧本发送失败")
                except Exception:
                    pass
                return False

        except Exception as e:
            logger.error(
                "PeerChatScheduler: 主动关怀时段分工协商异常: %s", e, exc_info=True
            )
            # 标记为 failed 避免每 2 分钟重复触发
            try:
                from core.services.active_care.storage.proactive_assignment_registry import (
                    get_proactive_assignment_registry,
                )
                registry = get_proactive_assignment_registry()
                await registry.mark_negotiation_status(
                    "failed", reason=f"协商异常: {e}"
                )
                logger.info("PeerChatScheduler: 主动关怀分工协商状态已标记为 failed，今日不再重试")
            except Exception:
                pass
            return False

    def _get_persona_state_brief(self, role_id: str) -> str:
        """获取角色今日状态简述（供协商 prompt 注入）

        从生命模拟系统读取生理状态，生成简短描述。
        """
        try:
            from core.services.life_simulation import get_life_simulation_service
            life_sim = get_life_simulation_service()
            if not life_sim:
                return ""
            bio_state = life_sim.get_bio_state(role_id)
            if not isinstance(bio_state, dict):
                return ""
            parts = []
            energy = float(bio_state.get("energy", 0))
            if energy > 0:
                if energy > 70:
                    parts.append("精力充沛")
                elif energy > 40:
                    parts.append("精力尚可")
                else:
                    parts.append("有点累")
            mood = str(bio_state.get("mood") or "").strip()
            if mood:
                parts.append(f"心情{mood}")
            is_sick = bool(bio_state.get("is_sick", False))
            if is_sick:
                parts.append("身体不适")
            return "，".join(parts) if parts else ""
        except Exception:
            return ""

    # ==================== 核心逻辑 ====================

    async def _check_and_trigger_for_role(
        self,
        role_id: str,
        conn: Dict[str, str],
        all_connections: List[Dict[str, str]],
    ) -> bool:
        """为指定角色检查并触发互聊(N 角色系统:遍历所有 peer 选第一个可用的)"""
        now = time.time()
        from core.services.dual_role.personas import get_peer_role_ids, get_persona

        # N 角色系统:获取所有 peer,选第一个可用的(非睡眠、有 qq_id)
        peer_role_ids = get_peer_role_ids(role_id)
        if not peer_role_ids:
            logger.info("PeerChatScheduler: %s 跳过，无 peer 角色", role_id)
            return False

        # 频率限制（全局）- 提前检查避免不必要的睡眠/peer 查询
        daily_limit = int(get_active_care_config(
            "peer_chat_daily_limit", default=6, settings=self._settings
        ))
        min_gap = float(get_active_care_config(
            "peer_chat_min_gap_seconds", default=5400.0, settings=self._settings
        ))

        # 使用 role_id 来设置 scope(N 角色系统:所有角色用自己的 scope)
        self._storage.set_runtime_scope(role_id)
        state_data = await self._storage.get_proactive_state()

        date_key = get_current_time().strftime("%Y-%m-%d")

        # 全局计数检查：所有角色合计不超过 daily_limit
        global_count = int(state_data.get(f"peer_chat_global_count_{date_key}", 0))
        if global_count >= daily_limit:
            if is_debug_enabled("peer_chat"):
                logger.info(
                    "PeerChatScheduler: 全局已达上限 (%d/%d)",
                    global_count, daily_limit
                )
            return False

        # per-role 计数仍保留，用于日志参考
        today_count = int(state_data.get(f"peer_chat_count_{date_key}", 0))

        last_peer_chat_ts = float(state_data.get("last_peer_chat_ts", 0.0))
        if last_peer_chat_ts > 0 and (now - last_peer_chat_ts) < min_gap:
            if is_debug_enabled("peer_chat"):
                logger.info(
                    "PeerChatScheduler: %s 间隔不足 (%.0fs < %.0fs)",
                    role_id, now - last_peer_chat_ts, min_gap
                )
            return False

        # 用户活跃检查（从 DualRoleCoordinator 合并）
        base_cid = f"private_{master_qq_id}" if (master_qq_id := self._resolve_master_qq_id()) else "default"
        if self.is_user_recently_active(base_cid):
            if is_debug_enabled("peer_chat"):
                logger.info("PeerChatScheduler: %s 跳过，用户最近活跃", role_id)
            return False
        if not self.is_within_idle_window(base_cid):
            if is_debug_enabled("peer_chat"):
                logger.info("PeerChatScheduler: %s 跳过，不在用户空闲窗口内", role_id)
            return False

        # N 角色系统:遍历所有 peer,选第一个可用的(非睡眠、有 qq_id)
        peer_role_id = ""
        peer_qq_id = ""
        peer_name = ""
        from core.services.active_care.core.qq_connection_resolver import (
            can_send_proactive_message,
        )

        for candidate_peer_id in peer_role_ids:
            # 连接门禁：peer 侧角色来自全量注册表，未接入客户端的角色
            # （如未开前端的Frost/Coco）不应被拉进互聊并对外发消息
            if not can_send_proactive_message(candidate_peer_id):
                logger.info(
                    "PeerChatScheduler: %s->%s 跳过，peer 无客户端接入",
                    role_id, candidate_peer_id,
                )
                continue
            # 角色睡眠门禁：peer_chat 需要双方都参与，任一角色在 SLEEPING 就跳过
            if await self._is_either_character_sleeping(role_id, candidate_peer_id):
                if is_debug_enabled("peer_chat"):
                    logger.info(
                        "PeerChatScheduler: %s->%s 跳过，角色在睡眠中",
                        role_id, candidate_peer_id,
                    )
                continue
            # 解析 peer_qq_id
            candidate_qq_id = self._resolve_peer_qq_id(candidate_peer_id)
            if not candidate_qq_id:
                logger.info(
                    "PeerChatScheduler: %s->%s 跳过，peer_qq_id 为空",
                    role_id, candidate_peer_id,
                )
                continue
            # 获取 peer 中文名(从 personas 查)
            peer_persona = get_persona(candidate_peer_id)
            if peer_persona:
                peer_name = peer_persona.cn_name
            else:
                peer_name = candidate_peer_id
            peer_role_id = candidate_peer_id
            peer_qq_id = candidate_qq_id
            break

        if not peer_role_id:
            logger.info("PeerChatScheduler: %s 跳过，无可用 peer", role_id)
            return False

        # 获取生理状态
        bio_state = {}
        try:
            from core.services.life_simulation import get_life_simulation_service
            life_sim = get_life_simulation_service()
            if life_sim:
                bio_state = life_sim.get_bio_state(role_id)
        except Exception:
            pass

        # LLM 决策
        decision_context = {
            "now": get_current_time().strftime("%Y-%m-%d %H:%M:%S"),
            "now_ts": now,
            "bio_state": bio_state,
            "elapsed_seconds": int(now - last_peer_chat_ts) if last_peer_chat_ts > 0 else 9999,
            "recent_peer_chat_topics": list(state_data.get("recent_peer_chat_topics") or []),
        }

        decision_result = await self._decision.decide_peer_chat(
            decision_context, role_id, peer_name,
        )

        logger.info(
            "PeerChatScheduler: %s LLM决策 should_send=%s topic=%s",
            role_id,
            decision_result.get("should_send"),
            str(decision_result.get("topic", ""))[:30],
        )

        if not decision_result.get("should_send", False):
            logger.info(
                "PeerChatScheduler: %s 决策不发送: %s",
                role_id, str(decision_result.get("thought", ""))[:80]
            )
            return False

        topic = str(
            decision_result.get("topic", "")
            or decision_result.get("planned_topic", "")
        ).strip()
        situation = str(decision_result.get("situation", "")).strip()
        opening_idea = str(decision_result.get("opening_idea", "")).strip()

        # 生成剧本并发送
        sent = await self._executor.generate_peer_script(
            role_id=role_id,
            peer_qq_id=peer_qq_id,
            topic=topic,
            situation=situation,
            opening_idea=opening_idea,
            persona_filename=conn.get("persona_filename", ""),
        )

        if sent:
            # 更新状态（全局计数 + per-role 计数）
            state_data[f"peer_chat_count_{date_key}"] = today_count + 1
            state_data[f"peer_chat_global_count_{date_key}"] = global_count + 1
            state_data["last_peer_chat_ts"] = now
            if topic:
                recent_topics = list(state_data.get("recent_peer_chat_topics") or [])
                recent_topics.append(topic)
                state_data["recent_peer_chat_topics"] = recent_topics[-5:]
                logger.info(f"PeerChatScheduler: 保存 recent_peer_chat_topics={recent_topics[-5:]}")
            await self._storage.save_proactive_state(state_data)
            self._today_count = today_count + 1
            logger.info(
                "PeerChatScheduler: %s->%s 发送成功 (今日第%d次, topic=%s)",
                role_id, peer_name, today_count + 1, topic[:30],
            )
            return True

        return False

    # ==================== 辅助方法 ====================

    async def _get_multi_qq_connections(self) -> List[Dict[str, str]]:
        """获取多QQ模式下的连接列表（带缓存）"""
        now = time.time()
        if (
            self._cached_connections
            and (now - self._connections_cache_ts) < self._connections_cache_ttl
        ):
            return self._cached_connections

        connections = self._executor._get_qq_connections()
        multi = [
            c for c in connections
            if c.get("persona_filename", "").strip()
        ]
        self._cached_connections = multi
        self._connections_cache_ts = now
        return multi

    def _resolve_peer_qq_id(self, peer_role_id: str) -> str:
        """从 multi_qq_config 或环境变量获取对方 QQ 号(N 角色通用)"""
        # 局部导入：避免 config 包循环导入
        # 通过统一入口 get_multi_qq_role_config() 读强类型配置,
        # settings_adapters 内部已应用 env var override
        from config.settings_adapters import get_multi_qq_role_config

        role_cfg = get_multi_qq_role_config(peer_role_id)
        if role_cfg is not None:
            peer_qq_id = str(getattr(role_cfg, "peer_qq_id", "") or "").strip()
            if peer_qq_id:
                return peer_qq_id

        # 兜底：读角色专属环境变量 XIAOYOU_QQ_BOT_NUMBER_{ROLE_ID_UPPER}
        # 向后兼容:aveline/ling 用旧 env var 名
        env_key_legacy = None
        if peer_role_id == "aveline":
            env_key_legacy = "XIAOYOU_QQ_BOT_NUMBER"
        elif peer_role_id == "ling":
            env_key_legacy = "XIAOYOU_QQ_BOT_NUMBER_LING"
        if env_key_legacy:
            val = os.getenv(env_key_legacy, "").strip()
            if val:
                return val
        # N 角色通用:XIAOYOU_QQ_BOT_NUMBER_{ROLE_ID_UPPER}
        env_key_generic = f"XIAOYOU_QQ_BOT_NUMBER_{peer_role_id.upper()}"
        return os.getenv(env_key_generic, "").strip()

    # ==================== 用户活跃感知（从 DualRoleCoordinator 合并）====================

    # 用户活跃时间戳持久化 key（写入 proactive_state.json，重启后可恢复）
    _USER_ACTIVITY_STATE_KEY = "last_user_activity_map"
    # 节流：两次持久化之间的最小间隔，避免每条用户消息都写盘
    _USER_ACTIVITY_PERSIST_MIN_GAP = 30.0

    def mark_user_activity(self, conversation_id: str) -> None:
        """标记用户活跃时间戳，供外部聊天流程调用

        同步更新内存字典，并节流地异步持久化到 proactive_state.json，
        使进程重启后 is_within_idle_window 仍能正确判断。
        """
        cid = str(conversation_id or "").strip() or "default"
        now = time.time()
        self._last_user_activity_ts[cid] = now
        if is_debug_enabled("peer_chat"):
            logger.info("PeerChatScheduler: 用户活跃标记 cid=%s", cid)
        # 节流持久化：距离上次写盘超过阈值才触发
        if (now - self._last_user_activity_persist_ts) >= self._USER_ACTIVITY_PERSIST_MIN_GAP:
            self._last_user_activity_persist_ts = now
            # P1-2: 保存任务引用，避免被 GC 后用户活跃时间戳丢失
            task = asyncio.ensure_future(self._persist_user_activity())
            self._pending_persist_tasks.add(task)

            def _on_done(t: asyncio.Task) -> None:
                self._pending_persist_tasks.discard(t)
                if t.cancelled():
                    return
                exc = t.exception()
                if exc is not None:
                    logger.error(
                        "PeerChatScheduler: 用户活跃持久化任务异常: %r",
                        exc, exc_info=exc,
                    )

            task.add_done_callback(_on_done)

    async def _persist_user_activity(self) -> None:
        """把内存里的用户活跃时间戳写到 proactive_state.json"""
        try:
            snapshot = dict(self._last_user_activity_ts)
            await self._storage.save_proactive_state(
                {self._USER_ACTIVITY_STATE_KEY: snapshot},
                immediate=False,
            )
        except Exception as e:
            if is_debug_enabled("peer_chat"):
                logger.info("PeerChatScheduler: 持久化用户活跃时间戳失败: %s", e)

    async def _load_user_activity(self) -> None:
        """从 proactive_state.json 恢复用户活跃时间戳（启动时调用一次）"""
        if self._user_activity_restored:
            return
        self._user_activity_restored = True
        try:
            state_data = await self._storage.get_proactive_state()
            saved = state_data.get(self._USER_ACTIVITY_STATE_KEY)
            if isinstance(saved, dict) and saved:
                for cid, ts in saved.items():
                    try:
                        self._last_user_activity_ts[str(cid)] = float(ts)
                    except (TypeError, ValueError):
                        continue
                logger.info(
                    "PeerChatScheduler: 恢复 %d 条用户活跃时间戳",
                    len(self._last_user_activity_ts),
                )
        except Exception as e:
            if is_debug_enabled("peer_chat"):
                logger.info("PeerChatScheduler: 加载用户活跃时间戳失败: %s", e)

    def is_user_recently_active(self, conversation_id: str) -> bool:
        """判断用户是否最近活跃（在grace期内）"""
        cid = str(conversation_id or "").strip() or "default"
        last = float(self._last_user_activity_ts.get(cid, 0.0))
        return (time.time() - last) < self._user_activity_grace_seconds

    def is_within_idle_window(self, conversation_id: str) -> bool:
        """判断是否在用户空闲窗口内（用户最后消息后idle_window秒内才允许互聊）"""
        cid = str(conversation_id or "").strip() or "default"
        last = float(self._last_user_activity_ts.get(cid, 0.0))
        if last <= 0:
            # 用户从未活跃过，允许互聊
            return True
        return (time.time() - last) <= self._user_idle_window_seconds

    async def _is_either_character_sleeping(
        self, role_a: str = "aveline", role_b: str = "ling"
    ) -> bool:
        """判断任一角色是否在睡眠中(peer_chat 角色睡眠门禁,双角色版本)

        只拦 SleepPhase.SLEEPING（夜间睡眠），不拦 NIGHT_AWAKE
        （被叫醒后的清醒状态，可参与互聊）。

        Returns:
            True 表示任一角色在睡眠中，应跳过 peer_chat
        """
        try:
            from core.services.life_simulation import get_sleep_manager
            from core.services.life_simulation.sleep_models import SleepPhase

            sleep_manager = get_sleep_manager()
            a_phase = sleep_manager.get_state(role_a).phase
            b_phase = sleep_manager.get_state(role_b).phase
            if a_phase == SleepPhase.SLEEPING or b_phase == SleepPhase.SLEEPING:
                logger.info(
                    "PeerChatScheduler: 角色睡眠门禁命中 (%s=%s, %s=%s)",
                    role_a, a_phase.value, role_b, b_phase.value,
                )
                return True
        except Exception as e:
            logger.warning("PeerChatScheduler: 角色睡眠门禁检查异常: %s", e)
        return False

    async def _is_any_character_sleeping(self, role_ids: List[str]) -> bool:
        """判断任一角色是否在睡眠中(N 角色通用版本)

        遍历所有角色,任一在 SLEEPING 即返回 True。
        用于协商类 peer chat(需要所有角色参与)。
        """
        try:
            from core.services.life_simulation import get_sleep_manager
            from core.services.life_simulation.sleep_models import SleepPhase

            sleep_manager = get_sleep_manager()
            for rid in role_ids:
                phase = sleep_manager.get_state(rid).phase
                if phase == SleepPhase.SLEEPING:
                    logger.info(
                        "PeerChatScheduler: 角色睡眠门禁命中 (%s=%s)",
                        rid, phase.value,
                    )
                    return True
        except Exception as e:
            logger.warning("PeerChatScheduler: 角色睡眠门禁检查异常: %s", e)
        return False

    async def is_user_sleeping(self) -> bool:
        """判断用户是否在睡觉（用于 peer_chat 等场景的睡眠门禁）

        判定标准（任一满足即视为睡觉）：
        1. reduced_mode_active=true 且 reason 属于睡眠相关（goodnight/sleep_hint）
        2. sleep_session_active=true（last_goodnight_ts > last_goodmorning_ts）

        注：probable_sleep 已于 2026-07-30 移除，不再基于长时间无响应推断入睡。

        Returns:
            True 表示用户在睡觉，应跳过 peer_chat
        """
        try:
            # 仅遍历可参与互聊的角色（aveline/ling），非常驻角色
            # （Frost/Coco）无真实客户端连接，不应被纳入睡眠门禁判定。
            connections = await self._get_multi_qq_connections()
            role_ids = [
                str(c.get("role_id", "")).strip().lower()
                for c in connections
                if str(c.get("role_id", "")).strip()
            ]
            for scope in role_ids:
                try:
                    self._storage.set_runtime_scope(scope)
                    state_data = await self._storage.get_proactive_state()
                except Exception:
                    continue

                # 条件1：reduced_mode_active + 睡眠相关 reason
                reduced_active = bool(state_data.get("reduced_mode_active", False))
                reduced_reason = str(state_data.get("reduced_mode_reason", "none") or "none")
                if reduced_active and reduced_reason in ("goodnight", "sleep_hint"):
                    return True

                # 条件2：sleep_session_active（基于 goodnight/goodmorning 时间戳）
                last_goodnight_ts = float(state_data.get("last_goodnight_ts", 0.0) or 0.0)
                last_goodmorning_ts = float(state_data.get("last_goodmorning_ts", 0.0) or 0.0)
                if last_goodnight_ts > 0 and last_goodmorning_ts < last_goodnight_ts:
                    return True
        except Exception as e:
            logger.warning("PeerChatScheduler: is_user_sleeping 检查异常: %s", e)
        return False

    def _resolve_master_qq_id(self) -> str:
        """获取主人QQ号"""
        try:
            from clients.bots.qq.main import QQAdapter
            for inst in QQAdapter.get_active_instances():
                qq_id = str(inst.get("adapter").cfg.qq_id if hasattr(inst.get("adapter"), "cfg") else "").strip()
                if qq_id:
                    return qq_id
        except Exception:
            pass
        return ""

    # ==================== 健康追踪 ====================

    def _record_success(self):
        self._last_success_ts = time.time()
        self._consecutive_failures = 0
        self._total_successes += 1

    def _record_failure(self, error_msg: str):
        self._consecutive_failures += 1
        self._last_error = error_msg[:500]
        logger.warning(
            "PeerChatScheduler: 记录失败 #%d: %s",
            self._consecutive_failures, error_msg[:100]
        )

    def _compute_next_interval(self) -> float:
        """计算下次检查间隔，支持指数退避（参数从 config 读取）"""
        if self._consecutive_failures < self._backoff_threshold:
            return float(self._check_interval)
        # 指数退避：base * 2^(failures - threshold)
        exponent = min(self._consecutive_failures - self._backoff_threshold, 4)
        backoff = self._backoff_base_seconds * (2 ** exponent)
        return min(float(backoff), float(self._backoff_max_seconds))

    def get_health_status(self) -> Dict[str, Any]:
        """返回调度器完整健康状态"""
        now = time.time()
        return {
            "running": self._running,
            "task_alive": bool(self._task and not self._task.done()),
            "last_run_ts": self._last_run_ts,
            "last_run_ago_seconds": int(now - self._last_run_ts) if self._last_run_ts > 0 else -1,
            "last_success_ts": self._last_success_ts,
            "last_success_ago_seconds": int(now - self._last_success_ts) if self._last_success_ts > 0 else -1,
            "consecutive_failures": self._consecutive_failures,
            "last_error": self._last_error,
            "today_count": self._today_count,
            "total_runs": self._total_runs,
            "total_successes": self._total_successes,
            "next_check_ts": self._next_check_ts,
            "next_check_in_seconds": max(0, int(self._next_check_ts - now)) if self._next_check_ts > 0 else -1,
            "check_interval": self._check_interval,
            "user_last_activity_ts": max(self._last_user_activity_ts.values()) if self._last_user_activity_ts else 0,
            # P3#12: 互聊效果评估指标（来自 PeerChatMetrics 单例）
            "peer_chat_metrics": self._get_peer_chat_metrics_snapshot(),
        }

    def _get_peer_chat_metrics_snapshot(self) -> Dict[str, Any]:
        """获取互聊效果评估指标快照"""
        try:
            from core.services.active_care.peer_chat.peer_chat_metrics import get_peer_chat_metrics
            return get_peer_chat_metrics().get_snapshot()
        except Exception:
            return {}

    async def run_single_check(self) -> Dict[str, Any]:
        """手动触发一次检查（供 API 端点调用）

        Returns:
            包含 success, sent, error 的结果字典
        """
        logger.info("PeerChatScheduler: 手动触发单次检查")
        try:
            await self._run_single_cycle()
            return {
                "success": True,
                "sent": True,
                "message": "单次检查完成",
                "health": self.get_health_status(),
            }
        except Exception as e:
            logger.error("PeerChatScheduler: 手动检查失败: %s", e, exc_info=True)
            return {
                "success": False,
                "sent": False,
                "error": str(e),
                "health": self.get_health_status(),
            }


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
