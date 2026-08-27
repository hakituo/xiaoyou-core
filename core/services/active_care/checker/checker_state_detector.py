"""
主动关怀检查器 - 状态检测

负责决策流程的准备阶段和上下文构建，包括：
- 执行决策流程（准备阶段 + 调用核心决策）
- 构建统一决策上下文
- 注入双角色互聊信息
- 检查日程记录中的起床时间，自动退出睡眠会话
- peer chat 兼容垫片（已废弃但保留签名）

依赖通过构造函数注入 checker 实例，方法内通过 checker.xxx 访问原 self 属性，
参考 SleepSessionManager 的依赖注入模式。
"""
import time
from datetime import datetime
from typing import Any, Dict, List

from core.utils.logger import get_module_logger
from config.debug_config import is_debug_enabled
from core.utils.timestamp_utils import safe_timestamp, is_plausible_timestamp
from core.services.active_care.decision.decision_context import DecisionFlowContext

logger = get_module_logger("ACTIVE_CARE_CHECKER", "active_care_schedule.log")


class CheckerStateDetector:
    """主动关怀检查器 - 状态检测

    封装决策流程的准备阶段和上下文构建逻辑，
    由 ProactiveChecker 委托调用。方法签名与原 ProactiveChecker 中
    对应方法保持一致（去掉 _ 前缀变公开方法）。
    """

    def __init__(self, checker):
        """
        Args:
            checker: ProactiveChecker 实例，用于访问 storage/context/executor 等依赖
        """
        self._checker = checker

    # ==================== 决策流程 ====================

    async def execute_decision_flow(self, now: float, persona_filename: str = ""):
        """执行决策流程（准备阶段 + 核心决策阶段）

        Args:
            persona_filename: 人设文件名，双QQ模式下按 persona 独立触发
        """
        checker = self._checker
        flow_start = time.monotonic()
        now_dt = datetime.fromtimestamp(now)
        ctx = DecisionFlowContext(now=now, now_dt=now_dt)
        ctx.persona_filename = persona_filename

        # 双QQ模式：在读取 state 之前，先根据 persona_filename 设置正确的 scope
        # 否则所有 persona 共享同一个 proactive_state.json
        if persona_filename:
            scope = checker.storage.resolve_scope_from_persona_filename(persona_filename)
            checker.storage.set_runtime_scope(scope)
            logger.info(
                "Active Care: 双QQ模式 - 设置 scope=%s (persona=%s)",
                scope, persona_filename,
            )

        ctx.default_next_check = checker._get_config_value("active_care_default_next_check_seconds", 300)
        # P1-4: 默认值与 settings_life.py 的 pydantic Field 对齐（min_gap=900, daily_limit=20）
        ctx.min_gap_seconds = checker._get_config_value("active_care_min_gap_seconds", 900)
        ctx.daily_limit = checker._get_config_value("active_care_daily_limit", 20)
        ctx.state_data = await checker.storage.get_proactive_state()

        try:
            ctx.full_history = await checker.context.get_latest_history(limit=20, persona_filename=persona_filename)
        except Exception:
            ctx.full_history = []

        try:
            # 双QQ模式下，用 persona_filename 构建正确的 primary_cid
            if persona_filename:
                from clients.bots.qq.utils import build_persona_conversation_id
                qq_connections = checker.executor._get_qq_connections(emit_logs=False)
                matching_conn = None
                for conn in qq_connections:
                    if conn.get("persona_filename", "").strip() == persona_filename:
                        matching_conn = conn
                        break
                if matching_conn:
                    ctx.primary_cid = build_persona_conversation_id(
                        matching_conn.get("user_id", ""), persona_filename
                    )
                    logger.info(
                        "Active Care: 双QQ模式 - primary_cid=%s (persona=%s)",
                        ctx.primary_cid, persona_filename,
                    )
                else:
                    ctx.primary_cid = await checker.context.resolve_primary_conversation_id()
            else:
                ctx.primary_cid = await checker.context.resolve_primary_conversation_id()

            scope = checker.storage.resolve_scope_from_conversation_id(ctx.primary_cid)
            checker.storage.set_runtime_scope(scope)
        except Exception:
            ctx.primary_cid = "default"

        # 用 _recent_user_message_cache 补全尚未落盘的最新用户消息
        try:
            if ctx.full_history is not None and ctx.primary_cid:
                cached = checker.context.get_recent_user_message(ctx.primary_cid)
                cached_content = str(cached.get("content") or "").strip()
                cached_ts = safe_timestamp(cached.get("timestamp"))
                if cached_content and cached_ts > 0:
                    from core.services.active_care.shared.constants import normalize_content
                    normalized_cached = normalize_content(cached_content)
                    already_exists = False
                    for msg in ctx.full_history:
                        if str(msg.get("role") or "").lower() != "user":
                            continue
                        if normalize_content(str(msg.get("content", ""))) == normalized_cached:
                            already_exists = True
                            break
                    if not already_exists:
                        ctx.full_history.append({
                            "role": "user",
                            "content": cached_content,
                            "timestamp": cached_ts,
                        })
        except Exception as cache_e:
            if is_debug_enabled("active_care"):
                logger.info(f"Active Care: full_history 缓存补全失败: {cache_e}")

        ctx.last_interaction = safe_timestamp(ctx.state_data.get("last_user_interaction_ts"))

        # 双QQ模式下，取全局和 per-persona 时间戳中的最大值
        # 修复：之前无条件用 per-persona 覆盖全局，当 per-persona 过期时
        # 会导致 elapsed 被错误计算为十几小时
        if persona_filename:
            per_persona_ts = ctx.state_data.get("last_user_interaction_ts_by_persona") or {}
            scope = checker.storage.resolve_scope_from_persona_filename(persona_filename)
            persona_key = scope if scope else "default"
            persona_ts = safe_timestamp(per_persona_ts.get(persona_key))
            if persona_ts > 0 and persona_ts > ctx.last_interaction:
                ctx.last_interaction = persona_ts

        if not is_plausible_timestamp(ctx.last_interaction, now):
            for item in reversed(ctx.full_history[:6]):
                if str(item.get("role") or "").strip().lower() != "user":
                    continue
                ts = safe_timestamp(item.get("timestamp"))
                if is_plausible_timestamp(ts, now):
                    ctx.last_interaction = ts
                    break

        reduced_mode_active_now = bool(ctx.state_data.get("reduced_mode_active"))
        expected_end_ts = float(ctx.state_data.get("reduced_mode_expected_end_ts") or 0.0)
        if reduced_mode_active_now and expected_end_ts > 0 and now >= expected_end_ts:
            from core.services.active_care.shared.constants import build_reduced_mode_clear_updates
            ctx.state_data = await checker.storage.save_proactive_state(
                    build_reduced_mode_clear_updates(), immediate=True
                )

        if not is_plausible_timestamp(ctx.last_interaction, now):
            persisted_last_user_ts = safe_timestamp(ctx.state_data.get("last_user_interaction_ts"))
            if is_plausible_timestamp(persisted_last_user_ts, now):
                ctx.last_interaction = persisted_last_user_ts

        if not is_plausible_timestamp(ctx.last_interaction, now):
            ctx.last_interaction = now - 300
            logger.warning(
                "Active Care: last_interaction timestamp invalid, fallback to 5min ago."
            )

        ctx.elapsed = max(0.0, now - ctx.last_interaction)

        try:
            recent_history_raw = ctx.full_history[:10]
            if recent_history_raw and ctx.elapsed >= 300:
                conv_result = checker.bert_analyzer.analyze_conversation_context(
                    recent_messages=recent_history_raw,
                    silence_seconds=ctx.elapsed,
                )
                ctx.conversation_incomplete = conv_result.get("is_conversation_incomplete", False)
                ctx.incomplete_type = conv_result.get("incomplete_type", "")
                ctx.incomplete_hint = conv_result.get("context_hint", "")

                if ctx.conversation_incomplete:
                    logger.info(
                        f"Active Care: 检测到对话未完成 ({ctx.incomplete_type}): {ctx.incomplete_hint}, "
                        f"沉默时长={int(ctx.elapsed)}秒"
                    )
        except Exception as e:
            if is_debug_enabled("active_care"):
                logger.info(f"Active Care: 对话上下文分析失败: {e}")

        ctx.count = await checker.storage.get_proactive_count(now_dt.strftime("%Y-%m-%d"))
        ctx.last_sent_ts = float(ctx.state_data.get("last_sent_ts", 0.0))
        ctx.last_attempt_ts = float(ctx.state_data.get("last_attempt_ts", 0.0))
        ctx.push_schedule = checker._get_config_value("active_care_schedule", {})
        ctx.quiet_hours = checker._get_config_value("active_care_quiet_hours", {})

        logger.info("Active Care 计时: 准备阶段=%.1fs", time.monotonic() - flow_start)
        await checker._run_decision_core(ctx)

    def build_unified_decision_ctx(self, ctx: DecisionFlowContext) -> Dict[str, Any]:
        """构建统一的决策上下文，消除 decision_ctx 和 content_decision_ctx 的重复构建"""
        checker = self._checker
        late_night_info = {}
        if checker._intent_detector:
            try:
                late_night_info = checker._intent_detector.infer_late_night_activity(ctx.history_msgs, ctx.now)
            except Exception:
                late_night_info = {}

        # 从用户画像服务获取 daily_push_priority
        daily_push_priority_data = {}
        try:
            # 从 UserProfileService 获取已缓存的 daily_push_priority
            cached_priority = checker.user_profile_service._cache.get("daily_push_priority") or {}
            if cached_priority.get("date") == ctx.now_dt.strftime("%Y-%m-%d"):
                daily_push_priority_data = cached_priority
        except Exception:
            pass

        # 获取角色日常活动状态
        character_daily = self._get_character_daily_context()

        return {
            "elapsed_seconds": int(ctx.elapsed),
            "now_ts": ctx.now,
            "now": ctx.now_dt.strftime("%Y-%m-%d %H:%M:%S") if ctx.now_dt else "",
            "tod": ctx.now_dt.strftime("%H:%M") if ctx.now_dt else "",
            "bio_state": ctx.life_stats,
            "urgent_needs": ctx.urgent_needs,
            "user_bio_state": ctx.user_bio_state,
            "quiet_mode_active": ctx.quiet_mode_active,
            "reduced_mode_active": ctx.reduced_mode_active,
            "reduced_mode_reason": ctx.reduced_mode_reason,
            "active_care_mode": ctx.active_care_mode_info.get("mode", "daily") if ctx.active_care_mode_info else "daily",
            "sleep_session": {
                "active": ctx.sleep_session_active,
                "last_sleep_session_duration_seconds": int(ctx.state_data.get("last_sleep_session_duration_seconds") or 0),
                "current_sleep_session_elapsed_seconds": int(
                    max(0.0, ctx.now - ctx.last_goodnight_ts) if ctx.sleep_session_active and ctx.last_goodnight_ts > 0 else 0
                ),
                "last_goodnight_ts": ctx.last_goodnight_ts,
                "last_goodmorning_ts": ctx.last_goodmorning_ts,
                "inferred_late_night_activity": late_night_info,
            },
            "priority_focus": ctx.priority_focus,
            "daily_push_priority": daily_push_priority_data or (
                {
                    "summary": str(ctx.priority_analysis.get("summary") or ""),
                    "ranked": ctx.priority_analysis.get("ranked") or [],
                }
                if isinstance(ctx.priority_analysis, dict) and ctx.priority_analysis.get("ranked")
                else ctx.priority_analysis
            ),
            "recent_history": ctx.recent_history,
            "persona_prompt": ctx.decision_persona_prompt,
            "user_display_name": ctx.decision_user_display_name,
            "last_proactive_sent_ts": ctx.last_sent_ts,
            "daily_record_quality": (ctx.workspace_snapshot.get("daily_record") or {}).get("quality") if ctx.workspace_snapshot else None,
            "is_early_morning": ctx.is_early_morning,
            "user_activity": ctx.activity_result,
            "primary_cid": getattr(ctx, "primary_cid", ""),  # 供决策模型工具调用使用
            "character_daily": character_daily,  # 角色日常活动状态
        }

    def inject_peer_chat_info(
        self, priority_focus: Dict[str, Any], state_data: Dict[str, Any], now: float
    ):
        """将双角色互聊信息注入 priority_focus，供 action 选择和内容生成使用"""
        last_peer_chat_ts = float(state_data.get("last_peer_chat_ts", 0.0))
        has_recent = (now - last_peer_chat_ts) < 7200 if last_peer_chat_ts > 0 else False
        priority_focus["has_recent_peer_chat"] = has_recent

        peer_chat_topics = []
        if has_recent:
            raw_topics = state_data.get("recent_peer_chat_topics") or []
            if isinstance(raw_topics, list):
                peer_chat_topics = [str(t).strip() for t in raw_topics if str(t).strip()]
        priority_focus["recent_peer_chat_topics"] = peer_chat_topics

    def _get_character_daily_context(self) -> Dict[str, Any]:
        """获取角色日常活动状态，注入到决策上下文中

        Returns:
            包含角色当前活动、是否空闲等信息的字典
        """
        try:
            from core.services.character_daily.engine import get_character_daily_engine
            engine = get_character_daily_engine()
            if not engine or not engine._running:
                return {}

            from core.services.character_daily.activity_model import (
                CHAT_ELIGIBLE_ACTIVITIES,
            )

            result = {}
            for role_id in ("aveline", "ling"):
                activity = engine.get_current_activity(role_id)
                activity_text = engine.get_activity_context_text(role_id)
                is_idle = activity in CHAT_ELIGIBLE_ACTIVITIES
                result[role_id] = {
                    "activity": activity.value,
                    "activity_text": activity_text,
                    "is_idle": is_idle,
                }

            # peer chat 摘要
            result["peer_chat_summary"] = engine.get_peer_chat_summary()

            logger.info(
                "CharacterDaily: 活动状态注入 Active Care - aveline=%s(idle=%s), ling=%s(idle=%s)",
                result.get("aveline", {}).get("activity", "?") ,
                result.get("aveline", {}).get("is_idle", False),
                result.get("ling", {}).get("activity", "?") ,
                result.get("ling", {}).get("is_idle", False),
            )
            return result
        except Exception as e:
            if is_debug_enabled("active_care"):
                logger.debug("CharacterDaily: 获取活动状态失败: %s", e)
            return {}

    async def execute_peer_chat_check(
        self, now: float, connections: List[Dict[str, str]]
    ):
        """已废弃：peer chat 已迁移到独立的 PeerChatScheduler。
        保留方法签名以防外部调用，实际逻辑已移除。"""
        try:
            from core.services.active_care.peer_chat.peer_chat_scheduler import get_peer_chat_scheduler
            scheduler = get_peer_chat_scheduler()
            if scheduler:
                scheduler.ensure_running()
        except Exception as e:
            if is_debug_enabled("active_care"):
                logger.info("Active Care: _execute_peer_chat_check 兼容调用失败: %s", e)

    async def check_daily_record_auto_wakeup(self, ctx: DecisionFlowContext):
        """检查日程记录中的起床时间，自动退出睡眠会话"""
        checker = self._checker
        if not ctx.sleep_session_active or not isinstance(ctx.workspace_snapshot, dict):
            return
        daily_record = ctx.workspace_snapshot.get("daily_record")
        if not isinstance(daily_record, dict):
            return
        # 兼容新旧格式
        sc = daily_record.get("sleep_cycle") or daily_record.get("schedule") or {}
        wakeup_str = str(
            sc.get("wakeup") or ""
        ).strip()
        if not wakeup_str:
            return
        try:
            wakeup_h, wakeup_m = int(wakeup_str.split(":")[0]), int(wakeup_str.split(":")[1])
            wakeup_dt = ctx.now_dt.replace(
                hour=wakeup_h, minute=wakeup_m, second=0, microsecond=0
            )
            wakeup_ts = wakeup_dt.timestamp()
            if wakeup_ts > ctx.last_goodnight_ts:
                logger.info(
                    "Active Care: daily_record wakeup=%s detected after goodnight, auto-exiting sleep session.",
                    wakeup_str,
                )
                ctx.sleep_session_active = False
                ctx.last_goodmorning_ts = wakeup_ts
                if ctx.reduced_mode_active and ctx.reduced_mode_reason == "goodnight":
                    ctx.reduced_mode_active = False
                    ctx.reduced_mode_reason = "none"
                sleep_archive_updates = checker._sleep_policy.build_sleep_session_archive_updates(
                    ctx.state_data, wakeup_ts, safe_timestamp
                )
                from core.services.active_care.shared.constants import build_goodnight_clear_updates, StateKeys
                goodnight_clear = build_goodnight_clear_updates()
                goodnight_clear[StateKeys.LAST_GOODMORNING_TS] = wakeup_ts
                goodnight_clear.update(sleep_archive_updates)
                ctx.state_data = await checker.storage.save_user_sleep_state(
                    goodnight_clear, immediate=True
                )
        except Exception as e:
            logger.warning(
                "Active Care: failed to parse daily_record wakeup time '%s': %s",
                wakeup_str,
                e,
            )
