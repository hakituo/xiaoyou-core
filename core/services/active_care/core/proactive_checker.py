"""
主动关怀检查器（核心协调器 / 门面）
负责协调各个子模块完成主动关怀的检查和执行

拆分自本类的子模块：
- checker_init_state.py: 初始化与状态恢复
- checker_client_gate.py: 客户端门控（活跃检测、私密模式）
- checker_throttle.py: 检查节流与时间调度（抖动、退避）
- sleep_session_manager.py: 睡眠会话状态机
- checker_state_detector.py: 状态检测（决策流程准备、上下文构建）
- checker_event_handler.py: 事件检测（到期提醒处理）
- checker_action_flow.py: 动作流程（优先级构建、发送/跳过）
- checker_time_gate.py: 时间检测（沉默覆盖）
- sleep_session_compat.py: 睡眠会话兼容 mixin（向后兼容垫片）

本文件保留核心协调逻辑（perform_check / _run_decision_core），
其余方法以委托方式转发到对应子模块。
"""
# ruff: noqa: E401,E702,F401
import time
import asyncio
from typing import Any, Dict

from core.utils.logger import get_module_logger
from config.debug_config import is_debug_enabled
from core.utils.config_accessor import get_user_display_name, get_active_care_config
from core.utils.timestamp_utils import safe_timestamp
from config.integrated_config import get_settings
from core.services.active_care.state import ModeStateManager
from core.services.active_care.state.sleep_state import SleepStateManager
from core.services.active_care.shared.constants import SkipReasons
from core.services.active_care.decision.priority_analyzer import PriorityAnalyzer
from core.services.active_care.detection.intent_detector import IntentDetector
from core.services.active_care.core.sleep_policy import SleepPolicy
from core.services.active_care.decision.decision_executor import DecisionExecutor
from core.services.active_care.decision.decision_context import DecisionFlowContext
from core.services.active_care.core.sleep_session_manager import SleepSessionManager
from core.services.active_care.checker.checker_init_state import CheckerInitState
from core.services.active_care.checker.checker_client_gate import CheckerClientGate
from core.services.active_care.checker.checker_throttle import CheckerThrottle
from core.services.active_care.checker.checker_state_detector import CheckerStateDetector
from core.services.active_care.checker.checker_event_handler import CheckerEventHandler
from core.services.active_care.checker.checker_action_flow import CheckerActionFlow
from core.services.active_care.checker.checker_time_gate import CheckerTimeGate
from core.services.active_care.checker.sleep_session_compat import SleepSessionCompatMixin

logger = get_module_logger("ACTIVE_CARE_CHECKER", "active_care_schedule.log")


class ProactiveChecker(SleepSessionCompatMixin):
    """
    主动关怀检查器（门面 + 核心协调器）

    职责：协调各个子模块，执行主动关怀检查流程
    - 客户端检测（委托 CheckerClientGate）
    - 私密模式检测（委托 CheckerClientGate）
    - 初始化/状态恢复（委托 CheckerInitState）
    - 节流/退避计算（委托 CheckerThrottle）
    - 睡眠会话管理（委托 SleepSessionManager + SleepSessionCompatMixin）
    - 状态检测（委托 CheckerStateDetector）
    - 事件检测（委托 CheckerEventHandler）
    - 动作流程（委托 CheckerActionFlow）
    - 时间检测（委托 CheckerTimeGate）
    - 优先级分析 / 决策执行（保留核心协调逻辑 perform_check / _run_decision_core）
    """

    def __init__(self, storage, context, scheduler_logic, decision, executor, user_profile_service=None):
        self.storage = storage
        self.context = context
        self.scheduler_logic = scheduler_logic
        self.decision = decision
        self.executor = executor
        self.settings = get_settings()
        self._bert_analyzer = None

        # 用户画像服务（独立于状态追踪）
        from core.services.active_care.storage.user_profile_service import UserProfileService
        self.user_profile_service = user_profile_service or UserProfileService(storage)

        self.last_intent = "none"
        self.last_client_probe = "none"
        self.last_check_started_ts = 0.0
        self.last_check_finished_ts = 0.0
        self.last_decision_eval_ts = 0.0
        self._last_decision_ts = 0.0
        self.last_skip_reason = "none"
        self.last_check_phase = "init"
        # 提醒重试计数器（由 CheckerEventHandler 读写）
        self._consecutive_reminder_retries = 0

        # 子模块：初始化/状态恢复
        self._init_state = CheckerInitState(
            storage=storage,
            get_config_value=self._get_config_value,
        )

        # 子模块：客户端门控
        self._client_gate = CheckerClientGate(
            context=context,
            storage=storage,
            get_config_value=self._get_config_value,
        )

        # 子模块：节流/退避
        self._throttle = CheckerThrottle()

        self._mode_state_resolver = ModeStateManager()
        self._intent_detector = IntentDetector(self._mode_state_resolver)
        self._sleep_policy = SleepPolicy()
        self._priority_analyzer = PriorityAnalyzer(None)
        self._decision_executor = DecisionExecutor(
            storage, context, decision, executor,
            self._priority_analyzer, self._intent_detector, self._sleep_policy
        )
        # 睡眠会话状态机委托给 SleepSessionManager（拆分自本类，保持向后兼容）
        # 传入 checker=self 以支持测试时对 self._get_config_value 的 mock 替换
        self._sleep_session_manager = SleepSessionManager(
            intent_detector=self._intent_detector,
            sleep_policy=self._sleep_policy,
            storage=storage,
            get_config_value=self._get_config_value,
            checker=self,
        )

        # 子模块：状态检测（决策流程准备、上下文构建）
        self._state_detector = CheckerStateDetector(checker=self)
        # 子模块：事件检测（到期提醒处理）
        self._event_handler = CheckerEventHandler(checker=self)
        # 子模块：动作流程（优先级构建、发送/跳过）
        self._action_flow = CheckerActionFlow(checker=self)
        # 子模块：时间检测（沉默覆盖）
        self._time_gate = CheckerTimeGate(checker=self)

    # ==================== 属性委托（保持外部兼容） ====================

    @property
    def next_decision_ts(self) -> float:
        return self._init_state.next_decision_ts

    @next_decision_ts.setter
    def next_decision_ts(self, value: float):
        self._init_state.next_decision_ts = value

    @property
    def _next_llm_decision_ts(self) -> float:
        return self._init_state._next_llm_decision_ts

    @_next_llm_decision_ts.setter
    def _next_llm_decision_ts(self, value: float):
        self._init_state._next_llm_decision_ts = value

    @property
    def _next_decision_ts_by_persona(self) -> Dict[str, float]:
        return self._init_state._next_decision_ts_by_persona

    @_next_decision_ts_by_persona.setter
    def _next_decision_ts_by_persona(self, value: Dict[str, float]):
        self._init_state._next_decision_ts_by_persona = value

    @property
    def _next_llm_decision_ts_by_persona(self) -> Dict[str, float]:
        return self._init_state._next_llm_decision_ts_by_persona

    @_next_llm_decision_ts_by_persona.setter
    def _next_llm_decision_ts_by_persona(self, value: Dict[str, float]):
        self._init_state._next_llm_decision_ts_by_persona = value

    @property
    def bert_analyzer(self):
        if self._bert_analyzer is None:
            from core.services.data_ops.bert_analyzer import get_bert_analyzer
            self._bert_analyzer = get_bert_analyzer()
            self._priority_analyzer.bert_analyzer = self._bert_analyzer
        return self._bert_analyzer

    # ==================== 工具方法（委托 CheckerThrottle） ====================

    def _apply_interval_jitter(
        self,
        base_seconds: float,
        *,
        min_seconds: int = 30,
        jitter_ratio: float = 0.20,
    ) -> int:
        return self._throttle.apply_interval_jitter(
            base_seconds, min_seconds=min_seconds, jitter_ratio=jitter_ratio,
        )

    def _non_response_backoff_multiplier(self, non_response_count: int) -> float:
        return self._throttle.non_response_backoff_multiplier(non_response_count)

    # ==================== 客户端检测（委托 CheckerClientGate） ====================

    def _has_active_client(self) -> bool:
        return self._client_gate.has_active_client()

    async def _detect_user_activity(self, now: float) -> Dict[str, Any]:
        return await self._client_gate.detect_user_activity(now)

    async def _check_private_mode(self) -> bool:
        return await self._client_gate.check_private_mode()

    def _probe_client_type(self) -> str:
        result = self._client_gate.probe_client_type()
        self.last_client_probe = f"probe:{result}"
        return result

    # ==================== 初始化和状态管理（委托 CheckerInitState） ====================

    async def initialize(self):
        await self._init_state.initialize()

    async def set_next_decision_ts(self, ts: float, source: str = "system", persona_filename: str = ""):
        await self._init_state.set_next_decision_ts(ts, source=source, persona_filename=persona_filename)

    def _get_earliest_next_decision_ts(self) -> float:
        return self._init_state._get_earliest_next_decision_ts()

    def get_next_decision_ts_for_persona(self, persona_filename: str) -> float:
        return self._init_state.get_next_decision_ts_for_persona(persona_filename)

    def get_all_persona_keys(self) -> list:
        """获取所有已注册的persona key列表，用于跨persona协调"""
        return self._init_state.get_all_persona_keys()

    # ==================== 配置获取 ====================

    def _get_config_value(self, attr: str, default: Any) -> Any:
        return get_active_care_config(attr, default=default, settings=self.settings)

    # ==================== 主检查流程（核心协调逻辑，保留完整） ====================

    async def perform_check(self, is_startup: bool = False):
        self.last_check_started_ts = time.time()
        self.last_skip_reason = ""
        self.last_check_phase = "start"

        try:
            now = time.time()

            require_active_client = bool(
                self._get_config_value("active_care_require_active_client", True)
            )
            if require_active_client and not self._has_active_client():
                self.last_skip_reason = "no_active_client"
                self.last_check_phase = "client_gate"
                default_next_check = self._get_config_value("active_care_default_next_check_seconds", 300)
                await self.set_next_decision_ts(
                    now + float(max(60, default_next_check)),
                    source="no_active_client",
                )
                logger.info(
                    "Active Care: 跳过 - 无活跃客户端 (require_active_client=%s)",
                    require_active_client,
                )
                return

            is_private_mode = await self._check_private_mode()
            if is_private_mode:
                self.last_skip_reason = SkipReasons.PRIVATE_MODE
                self.last_check_phase = "private_mode_gate"
                default_next_check = self._get_config_value("active_care_default_next_check_seconds", 300)
                await self.set_next_decision_ts(
                    now + float(default_next_check),
                    source=SkipReasons.PRIVATE_MODE,
                )
                logger.info(
                    "Active Care: 跳过 - 私密模式已激活 (sensitive人设)"
                )
                return

            if now < self._next_llm_decision_ts:
                # 双QQ模式下，检查是否有 persona 已到决策时间
                qq_connections = self.executor._get_qq_connections(emit_logs=False)
                multi_persona_connections = [
                    conn for conn in qq_connections
                    if conn.get("persona_filename", "").strip()
                ]
                if len(multi_persona_connections) >= 2:
                    has_due_persona = False
                    for conn in multi_persona_connections:
                        persona_fn = conn.get("persona_filename", "").strip()
                        persona_next_ts = self.get_next_decision_ts_for_persona(persona_fn)
                        if persona_next_ts <= now:
                            has_due_persona = True
                            break
                    if not has_due_persona:
                        self.last_skip_reason = "manual_delay"
                        self.next_decision_ts = self._next_llm_decision_ts
                        logger.info(
                            "Active Care: 跳过 - 手动延迟 (还需等待%ds)",
                            int(self._next_llm_decision_ts - now),
                        )
                        return
                    else:
                        logger.info(
                            "Active Care: 全局延迟中但有 persona 已到决策时间，继续执行"
                        )
                else:
                    self.last_skip_reason = "manual_delay"
                    self.next_decision_ts = self._next_llm_decision_ts
                    logger.info(
                        "Active Care: 跳过 - 手动延迟 (还需等待%ds)",
                        int(self._next_llm_decision_ts - now),
                    )
                    return

            logger.info("Active Care: 开始执行决策流程 (is_startup=%s)", is_startup)

            qq_connections = self.executor._get_qq_connections()
            multi_persona_connections = [
                conn for conn in qq_connections
                if conn.get("persona_filename", "").strip()
            ]

            logger.info(
                "Active Care: QQ连接数=%d, 有persona的连接数=%d, 连接详情=%s",
                len(qq_connections),
                len(multi_persona_connections),
                [(c.get("role_id"), c.get("persona_filename")[:30] if c.get("persona_filename") else "") for c in qq_connections],
            )

            if len(multi_persona_connections) >= 2:
                logger.info(
                    "Active Care: 检测到双QQ模式 (%d 个 persona)，按 persona 独立触发",
                    len(multi_persona_connections),
                )
                # 每个 persona 独立超时，避免 aveline 处理慢耗尽预算导致 ling 饥饿
                # 单 persona 上限 60s，双 persona 总共最多 120s，留 30s 缓冲给主循环 150s 超时
                _PER_PERSONA_TIMEOUT = 60
                for conn in multi_persona_connections:
                    persona_fn = conn.get("persona_filename", "").strip()
                    role_id = conn.get("role_id", "").strip()
                    persona_next_ts = self.get_next_decision_ts_for_persona(persona_fn)
                    if persona_next_ts > now:
                        logger.info(
                            "Active Care: 双QQ模式 - persona=%s (role=%s) 尚未到决策时间 (还需等待%ds)，跳过",
                            persona_fn, role_id, int(persona_next_ts - now),
                        )
                        continue
                    logger.info(
                        "Active Care: 双QQ模式 - 为 persona=%s (role=%s) 执行决策流程 (独立超时=%ds)",
                        persona_fn, role_id, _PER_PERSONA_TIMEOUT,
                    )
                    _persona_start = time.monotonic()
                    try:
                        await asyncio.wait_for(
                            self._execute_decision_flow(now, persona_filename=persona_fn),
                            timeout=_PER_PERSONA_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        _elapsed = time.monotonic() - _persona_start
                        logger.error(
                            "Active Care: 双QQ模式 persona=%s (role=%s) 决策流程超时(%.1fs)，"
                            "跳过该 persona 继续下一个，避免 ling 饥饿",
                            persona_fn, role_id, _elapsed,
                        )
                        # 标记该 persona 的下次决策时间，避免立即重试再次超时
                        try:
                            await self.set_next_decision_ts(
                                now + 300,  # 5 分钟后重试
                                source="persona_decision_timeout",
                                persona_filename=persona_fn,
                            )
                        except Exception:
                            pass
                    except Exception as e:
                        logger.error(
                            "Active Care: 双QQ模式 persona=%s 决策流程异常: %s",
                            persona_fn, e, exc_info=True,
                        )

                # peer chat 已由独立的 PeerChatScheduler 调度，此处仅确认其存活
                try:
                    from core.services.active_care.peer_chat.peer_chat_scheduler import get_peer_chat_scheduler
                    _pcs = get_peer_chat_scheduler()
                    if _pcs:
                        _pcs.ensure_running()
                    else:
                        if is_debug_enabled("active_care"):
                            logger.info("Active Care: PeerChatScheduler 未初始化，跳过 peer chat 心跳")
                except Exception as e:
                    logger.warning("Active Care: PeerChatScheduler 心跳检查异常: %s", e)
            else:
                await self._execute_decision_flow(now)

            if not self.last_skip_reason:
                self.last_skip_reason = "decision_executed"

            logger.info(
                "Active Care: 决策流程完成 skip_reason=%s phase=%s",
                self.last_skip_reason, self.last_check_phase,
            )

        except asyncio.CancelledError:
            self.last_skip_reason = "cancelled"
            logger.info("Active Care: perform_check 被 CancelledError 中断")
            raise
        except Exception as e:
            self.last_skip_reason = f"error: {e}"
            logger.error(f"Active Care execution error: {e}", exc_info=True)
        finally:
            now_ts = time.time()
            self.last_check_finished_ts = now_ts
            self._repair_stale_next_decision_ts(now_ts)

    def _repair_stale_next_decision_ts(self, now_ts: float) -> None:
        """修复已经过期的下次检查时间，避免双 QQ 模式被过期 persona 卡成固定短轮询。"""
        if self.next_decision_ts >= now_ts:
            return
        fallback_wait = float(max(
            300,
            self._get_config_value("active_care_default_next_check_seconds", 300),
        ))
        fallback_ts = now_ts + fallback_wait
        self.next_decision_ts = fallback_ts
        self._next_llm_decision_ts = fallback_ts
        repaired_personas = []
        for key, ts in list(self._next_decision_ts_by_persona.items()):
            if float(ts or 0.0) < now_ts:
                self._next_decision_ts_by_persona[key] = fallback_ts
                self._next_llm_decision_ts_by_persona[key] = fallback_ts
                repaired_personas.append(key)
        logger.warning(
            "Active Care: 检测到过期 next_decision_ts，应用保底回退 %.0fs"
            " (global + overdue_personas=%s)",
            fallback_wait,
            repaired_personas or [],
        )

    # ==================== 决策核心（保留完整，内部调用委托新模块） ====================

    async def _run_decision_core(self, ctx: DecisionFlowContext):
        """决策核心逻辑"""
        now = ctx.now
        now_dt = ctx.now_dt
        phase_start = time.monotonic()

        ctx.client_type = self._probe_client_type()
        ctx.workspace_snapshot = await self._decision_executor.get_workspace_snapshot(now_dt)
        logger.info("Active Care 计时: get_workspace_snapshot=%.1fs", time.monotonic() - phase_start)

        # 用户进程活动检测
        t0 = time.monotonic()
        ctx.activity_result = await self._detect_user_activity(now)
        logger.info("Active Care 计时: _detect_user_activity=%.1fs", time.monotonic() - t0)

        ctx.history_msgs = ctx.full_history[:8]

        t0 = time.monotonic()
        ctx.recent_history = await self._decision_executor.get_recent_history(
            ctx.workspace_snapshot, cached_history=ctx.full_history[:8]
        )
        logger.info("Active Care 计时: get_recent_history=%.1fs", time.monotonic() - t0)

        t0 = time.monotonic()
        inferred_text, inferred_ts, inferred_goodnight, inferred_goodmorning, inferred_sleep_hint, primary_cid = \
            await self._decision_executor.get_user_signal_and_intent(
                cached_history=ctx.full_history[:20], primary_cid=ctx.primary_cid, persona_filename=ctx.persona_filename
            )
        logger.info("Active Care 计时: get_user_signal_and_intent=%.1fs", time.monotonic() - t0)
        ctx.primary_cid = primary_cid

        # 注意：不再将"助手说晚安"视为用户入睡信号。
        # 角色（Aveline/Ling）按自身作息进入 SLEEPING 并发送晚安，只代表角色睡了，
        # 与用户是否入睡无关。若把助手晚安强制注入睡眠会话，会导致：
        # - nightly_processor.check_user_sleeping() 误判用户入睡 → 提前生成日记
        # - peer_chat 的 is_user_sleeping() 误判 → 错误门禁
        # 用户是否入睡只依据用户真实行为（用户说晚安 / sleep_hint + 沉默）。
        # 角色睡眠时的降频由 checker_event_handler.role_sleeping / decision.py 兜底。

        try:
            from core.services.active_care.core.persona_resolver import PersonaResolver
            ctx.decision_persona_prompt = PersonaResolver(self.storage).load_persona_prompt(primary_cid)
        except Exception:
            pass

        ctx.decision_user_display_name = get_user_display_name(self.settings)

        ctx.life_stats, ctx.immune_stats, ctx.user_bio_state, ctx.emo_payload = \
            self._decision_executor.get_life_and_emotion_state()

        # 提前构建紧急需求（软门控评分需要）
        device_context = {}
        ctx.urgent_needs = self._decision_executor.build_urgent_needs(
            ctx.life_stats, ctx.immune_stats, device_context, now
        )

        t0 = time.monotonic()
        ctx.state_data = await self._process_sleep_session_state(
            now, ctx.state_data, inferred_goodnight, inferred_goodmorning, inferred_ts,
            inferred_text, ctx.workspace_snapshot,
            inferred_sleep_hint=inferred_sleep_hint,
        )
        logger.info("Active Care 计时: _process_sleep_session_state=%.1fs", time.monotonic() - t0)

        preference_mode = "normal"
        try:
            from core.managers.preference_manager import get_preference_manager
            preference_mode = str(get_preference_manager().get_mode() or "normal")
        except Exception:
            pass

        ctx.active_care_mode_info = self._mode_state_resolver.resolve_active_care_mode(
            preference_mode=preference_mode,
            proactive_state=ctx.state_data,
        )

        ctx.reduced_mode_active = bool(ctx.state_data.get("reduced_mode_active"))
        ctx.reduced_mode_reason = str(ctx.state_data.get("reduced_mode_reason") or "none")
        ctx.latest_user_signal_ts = max(inferred_ts, ctx.last_interaction)

        focus_policy = self._sleep_policy.resolve_focus_reduced_policy(
            now=now,
            reduced_mode_active=ctx.reduced_mode_active,
            reduced_mode_reason=ctx.reduced_mode_reason,
            latest_user_signal_ts=ctx.latest_user_signal_ts,
            last_sent_ts=float(ctx.last_sent_ts or 0.0),
            default_next_check=ctx.default_next_check,
            focus_user_quiet_seconds=self._get_config_value("active_care_focus_user_quiet_seconds", 1800),
            focus_low_disturb_gap_seconds=self._get_config_value("active_care_focus_low_disturb_gap_seconds", 7200),
        )

        ctx.last_goodnight_ts = safe_timestamp(ctx.state_data.get("last_goodnight_ts"))
        ctx.last_goodmorning_ts = safe_timestamp(ctx.state_data.get("last_goodmorning_ts"))
        ctx.sleep_session_active = SleepStateManager.is_sleep_session_active_from_state(
            ctx.last_goodnight_ts, ctx.last_goodmorning_ts
        )

        quiet_cfg = ctx.quiet_hours if isinstance(ctx.quiet_hours, dict) else {}
        allow_goodnight_probe = bool(quiet_cfg.get("allow_goodnight_probe", False))
        last_goodnight_probe_ts = safe_timestamp(ctx.state_data.get("last_goodnight_probe_ts"))

        ctx.probe_policy = self._sleep_policy.resolve_sleep_probe_policy(
            now=now,
            sleep_session_active=ctx.sleep_session_active,
            allow_goodnight_probe=allow_goodnight_probe,
            reduced_mode_active=ctx.reduced_mode_active,
            reduced_mode_reason=ctx.reduced_mode_reason,
            last_goodnight_ts=ctx.last_goodnight_ts,
            last_goodnight_probe_ts=last_goodnight_probe_ts,
            default_next_check=ctx.default_next_check,
            min_gap_seconds=ctx.min_gap_seconds,
            goodnight_probe_gap_seconds=int(quiet_cfg.get("goodnight_probe_gap_seconds", 2 * 3600) or (2 * 3600)),
            goodnight_low_disturb_gap_seconds=int(quiet_cfg.get("goodnight_low_disturb_gap_seconds", 3 * 3600) or (3 * 3600)),
        )

        # ==================== 软评分门控 ====================
        # 使用 GateScorer 综合评估活动/专注/睡眠/交互门控，替代原来的硬拦截
        from core.services.active_care.detection.gate_scorer import GateScorer
        gate_scorer = GateScorer()

        # 计算专注模式安静时长
        focus_quiet_seconds = 0.0
        if ctx.reduced_mode_active and ctx.reduced_mode_reason == "focus":
            focus_started_ts = safe_timestamp(ctx.state_data.get("reduced_mode_started_ts"))
            if focus_started_ts > 0:
                focus_quiet_seconds = now - focus_started_ts

        # 计算交互保护参数
        last_interaction_ts = ctx.last_interaction
        user_quiet_seconds = self._get_config_value("active_care_user_quiet_seconds", 300)

        # 获取对话完整性
        conversation_incomplete = getattr(ctx, "conversation_incomplete", False)
        _persona_key = self.executor._resolve_persona_key_from_filename(getattr(ctx, 'persona_filename', ''))
        non_response_count = self.executor.get_non_response_count(_persona_key)

        gate_result = gate_scorer.evaluate_gates(
            has_active_client=True,  # 客户端已在 perform_check 中检查
            is_private_mode=False,   # 私密模式已在 perform_check 中检查
            manual_delay_remaining=0.0,  # 延迟已在 perform_check 中检查
            is_user_busy=bool(ctx.activity_result.get("is_busy")),
            busy_level=float(ctx.activity_result.get("busy_level", 0.0)),
            busy_category=str(ctx.activity_result.get("category", "")),
            is_focus_mode=ctx.reduced_mode_active and ctx.reduced_mode_reason == "focus",
            focus_quiet_seconds=focus_quiet_seconds,
            focus_low_disturb_gap=float(self._get_config_value("active_care_focus_low_disturb_gap_seconds", 7200)),
            is_sleep_session=ctx.sleep_session_active,
            is_reduced_mode=ctx.reduced_mode_active,
            reduced_mode_reason=ctx.reduced_mode_reason,
            probe_policy=ctx.probe_policy,
            last_interaction_ts=last_interaction_ts,
            user_quiet_seconds=user_quiet_seconds,
            conversation_incomplete=conversation_incomplete,
            non_response_count=non_response_count,
            has_urgent_needs=bool(ctx.urgent_needs),
            now=now,
        )

        logger.info(
            "Active Care: 软评分门控结果 passed=%s score=%.2f adaptive=%s reason=%s scores=[%s]",
            gate_result.passed, gate_result.final_score, gate_result.is_adaptive,
            gate_result.block_reason,
            ", ".join(f"{s.gate_name}={s.score:.2f}" for s in gate_result.scores),
        )

        if not gate_result.passed:
            self.last_skip_reason = gate_result.block_reason
            self.last_check_phase = "soft_gate"
            _pf = getattr(ctx, 'persona_filename', '')
            if "activity" in gate_result.block_reason:
                busy_wait = self._get_config_value("active_care_busy_user_next_check_seconds", 600)
                await self.set_next_decision_ts(now + float(busy_wait), source=gate_result.block_reason, persona_filename=_pf)
            elif "focus" in gate_result.block_reason:
                wait_seconds = int(focus_policy.get("wait_seconds") or ctx.default_next_check)
                await self.set_next_decision_ts(now + float(wait_seconds), source=gate_result.block_reason, persona_filename=_pf)
            elif "sleep" in gate_result.block_reason:
                wait_seconds = int(ctx.probe_policy.get("wait_seconds") or ctx.default_next_check)
                await self.set_next_decision_ts(now + float(wait_seconds), source=gate_result.block_reason, persona_filename=_pf)
            elif "interaction" in gate_result.block_reason:
                remaining = max(int(user_quiet_seconds - max(0.0, now - last_interaction_ts)), ctx.default_next_check)
                await self.set_next_decision_ts(now + float(remaining), source=gate_result.block_reason, persona_filename=_pf)
            else:
                await self.set_next_decision_ts(now + float(ctx.default_next_check), source=gate_result.block_reason, persona_filename=_pf)
            return

        # 软门控通过，继续后续流程

        t0 = time.monotonic()
        await self._check_daily_record_auto_wakeup(ctx)
        logger.info("Active Care 计时: _check_daily_record_auto_wakeup=%.1fs", time.monotonic() - t0)

        if ctx.sleep_session_active or (
            ctx.reduced_mode_active and ctx.reduced_mode_reason == "sleep_hint"
        ):
            await self.storage.save_user_sleep_state(
                {"last_goodnight_probe_ts": now}, immediate=True
            )

        t0 = time.monotonic()
        if await self._handle_due_reminder(ctx):
            logger.info("Active Care 计时: _handle_due_reminder=%.1fs (已处理，终止决策)", time.monotonic() - t0)
            return
        logger.info("Active Care 计时: _handle_due_reminder=%.1fs (无到期提醒)", time.monotonic() - t0)

        t0 = time.monotonic()
        if await self._event_handler.guard_general_proactive_during_sleep_recovery(ctx):
            logger.info(
                "Active Care 计时: guard_general_proactive_during_sleep_recovery=%.1fs (已拦截，终止决策)",
                time.monotonic() - t0,
            )
            return
        logger.info(
            "Active Care 计时: guard_general_proactive_during_sleep_recovery=%.1fs (未拦截)",
            time.monotonic() - t0,
        )

        await self._build_priority_and_select_action(ctx, persona_filename=getattr(ctx, 'persona_filename', ''))

    # ==================== 委托方法（→ 5 个新子模块，保持向后兼容） ====================

    async def _execute_decision_flow(self, now: float, persona_filename: str = ""):
        """执行决策流程（委托 CheckerStateDetector）"""
        return await self._state_detector.execute_decision_flow(now, persona_filename=persona_filename)

    def _build_unified_decision_ctx(self, ctx: DecisionFlowContext) -> Dict[str, Any]:
        """构建统一决策上下文（委托 CheckerStateDetector）"""
        return self._state_detector.build_unified_decision_ctx(ctx)

    def _inject_peer_chat_info(
        self, priority_focus: Dict[str, Any], state_data: Dict[str, Any], now: float
    ):
        """注入双角色互聊信息（委托 CheckerStateDetector）"""
        return self._state_detector.inject_peer_chat_info(priority_focus, state_data, now)

    async def _execute_peer_chat_check(
        self, now: float, connections
    ):
        """已废弃兼容方法（委托 CheckerStateDetector）"""
        return await self._state_detector.execute_peer_chat_check(now, connections)

    async def _check_daily_record_auto_wakeup(self, ctx: DecisionFlowContext):
        """检查日程记录起床时间，自动退出睡眠会话（委托 CheckerStateDetector）"""
        return await self._state_detector.check_daily_record_auto_wakeup(ctx)

    async def _handle_due_reminder(self, ctx: DecisionFlowContext) -> bool:
        """处理到期提醒（委托 CheckerEventHandler）"""
        return await self._event_handler.handle_due_reminder(ctx)

    async def _build_priority_and_select_action(self, ctx: DecisionFlowContext, persona_filename: str = ""):
        """构建优先级并选择动作（委托 CheckerActionFlow）"""
        return await self._action_flow.build_priority_and_select_action(ctx, persona_filename=persona_filename)

    async def _execute_send_or_skip(self, ctx: DecisionFlowContext, decision: Dict, chosen_action: str, persona_filename: str = ""):
        """执行发送或跳过（委托 CheckerActionFlow）"""
        return await self._action_flow.execute_send_or_skip(ctx, decision, chosen_action, persona_filename=persona_filename)

    def _apply_silence_overrides(
        self,
        ctx: DecisionFlowContext,
        should_send: bool,
        thought: str,
        non_response_count: int,
    ) -> tuple:
        """应用沉默覆盖逻辑（委托 CheckerTimeGate）"""
        return self._time_gate.apply_silence_overrides(ctx, should_send, thought, non_response_count)
