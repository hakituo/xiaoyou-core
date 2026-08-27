# -*- coding: utf-8 -*-
"""专注会话服务：后端权威会话的核心实现。

职责：
- 创建 / 开始 / 暂停 / 恢复 / 结束会话（真实计时在后端，前端只上报观察）。
- observation 幂等：sequence 去重、可接受乱序、重复直接忽略。
- 掉线过期：超过 heartbeat_timeout 无观察则标记；超过 offline_grace 自动暂停。
- 结束生成自然语言总结，并把有效专注分钟同步到 DailyTracker。
- 落盘复用 core/utils/atomic_io 的原子 JSON 写入 + 文件锁（filelock）。
- 同一用户只允许一个活动会话。

隐私约束：observation 只允许 presence/activity/confidence/signals/page_visible，
绝不接收 base64 图片 / 音频 / 视频片段。
"""
from __future__ import annotations

import os
import time
import uuid
from typing import List, Optional

from filelock import FileLock, Timeout

from config.focus_monitor_config import get_focus_monitor_config
from core.services.study.focus_session_models import (
    ACTIVITY_WHITELIST,
    PRESENCE_WHITELIST,
    ActivityState,
    FocusSession,
    NudgeEvent,
    Observation,
    PresenceState,
)
from core.services.study.focus_monitor_policy import FocusMonitorPolicy
from core.utils.atomic_io import safe_json_dump, safe_json_load
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

logger = get_logger("FOCUS_SERVICE")


class FocusSessionError(Exception):
    pass


class FocusSessionService:
    """单例。进程内维护活动会话索引，落盘为最终存储。"""

    def __init__(self):
        self.cfg = get_focus_monitor_config()
        self.policy = FocusMonitorPolicy()
        self._active: dict[str, FocusSession] = {}  # user_id -> session（仅 active/paused）
        self._lock = __import__("threading").Lock()

    # ---------------- 生命周期 ----------------
    def start_session(self, user_id: str, subject: str, planned_minutes: int,
                      mode: str = "gentle", monitoring: bool = True) -> FocusSession:
        with self._lock:
            existing = self._active.get(user_id)
            if existing and existing.status in ("active", "paused"):
                raise FocusSessionError(
                    f"用户 {user_id} 已有活动会话 {existing.session_id}，先结束或恢复它"
                )
            now = get_current_time().timestamp()
            sess = FocusSession(
                session_id=uuid.uuid4().hex[:16],
                user_id=user_id,
                subject=subject or "未命名学习任务",
                planned_minutes=max(1, int(planned_minutes)),
                mode=mode if mode in ("gentle", "strict") else "gentle",
                monitoring=bool(monitoring),
                created_at=now,
                started_at=now,
                last_resume_at=now,
                status="active",
            )
            self._active[user_id] = sess
            self._persist(sess)
            logger.info(f"专注会话开始: {sess.session_id} user={user_id} subject={subject}")
            return sess

    def get_current(self, user_id: str) -> Optional[FocusSession]:
        sess = self._active.get(user_id)
        if sess is None:
            # 尝试从落盘恢复（进程重启后）
            sess = self._load_latest_active(user_id)
            if sess:
                self._active[user_id] = sess
        return sess

    def pause(self, user_id: str, reason: str = "user") -> FocusSession:
        sess = self._require_active(user_id)
        now = get_current_time().timestamp()
        if sess.status != "active":
            raise FocusSessionError("会话不处于 active 状态，无法暂停")
        # 结算已累计 active 秒数
        sess.accumulated_active_seconds += (now - sess.last_resume_at)
        sess.last_resume_at = 0.0
        sess.paused_at = now
        sess.status = "paused"
        sess.interruption_count += 1
        self._persist(sess)
        logger.info(f"会话暂停: {sess.session_id} reason={reason}")
        return sess

    def resume(self, user_id: str) -> FocusSession:
        sess = self._require_active(user_id)
        now = get_current_time().timestamp()
        if sess.status != "paused":
            raise FocusSessionError("会话不处于 paused 状态，无法恢复")
        sess.last_resume_at = now
        sess.status = "active"
        # 重置连续分心起点（恢复后从新观察开始计）
        sess._distraction_since = 0.0
        self._persist(sess)
        logger.info(f"会话恢复: {sess.session_id}")
        return sess

    def finish(self, user_id: str, self_rating: Optional[int] = None,
               note: Optional[str] = None) -> FocusSession:
        sess = self._require_active(user_id)
        now = get_current_time().timestamp()
        if sess.status == "active" and sess.last_resume_at > 0:
            sess.accumulated_active_seconds += (now - sess.last_resume_at)
        sess.accumulated_active_seconds = round(sess.accumulated_active_seconds, 1)
        sess.status = "finished"
        sess.finished_at = now
        sess.self_rating = self_rating
        sess.note = note
        self._finalize_summary(sess)
        self._sync_to_daily(sess)
        self._persist(sess)
        self._active.pop(user_id, None)
        logger.info(f"会话结束: {sess.session_id} effective={sess.accumulated_active_seconds}s")
        return sess

    # ---------------- 观察 / 心跳 ----------------
    def record_observations(self, user_id: str, observations: List[dict]) -> dict:
        """批量上报观察（含心跳）。每个 observation 带 sequence 做幂等。

        返回 {accepted, ignored, dropped} 统计，供前端核对。
        """
        d = self._require_active(user_id)
        accepted, ignored, dropped = 0, 0, 0
        now = get_current_time().timestamp()
        for raw in observations:
            try:
                obs = self._validate_observation(raw, now)
            except FocusSessionError as e:
                dropped += 1
                logger.warning(f"观察被拒: {e}")
                continue
            if obs.sequence in d._seen_sequences:
                ignored += 1
                continue
            d._seen_sequences.add(obs.sequence)
            d.observations.append(obs.to_dict())
            accepted += 1
            self._aggregate(d, obs)
        self._persist(d)
        return {"accepted": accepted, "ignored": ignored, "dropped": dropped,
                "total_observations": len(d.observations)}

    def _validate_observation(self, raw: dict, now: float) -> Observation:
        presence = raw.get("presence")
        activity = raw.get("activity")
        if presence not in PRESENCE_WHITELIST:
            raise FocusSessionError(f"非法 presence: {presence}")
        if activity not in ACTIVITY_WHITELIST:
            raise FocusSessionError(f"非法 activity: {activity}")
        seq = raw.get("sequence")
        if not isinstance(seq, int) or seq < 0:
            raise FocusSessionError(f"非法 sequence: {seq}")
        observed_at = float(raw.get("observed_at", now))
        # 拒绝任何可能包含媒体的字段（隐私护栏）
        for banned in ("image", "base64", "audio", "video", "frame", "data_url", "screenshot"):
            if banned in raw:
                raise FocusSessionError(f"观察包含被禁止字段: {banned}")
        return Observation(
            sequence=seq,
            observed_at=observed_at,
            presence=presence,
            activity=activity,
            confidence=float(raw.get("confidence", 0.0)),
            signals=list(raw.get("signals", []))[:16],
            page_visible=bool(raw.get("page_visible", True)),
            client_ts=float(raw.get("client_ts", observed_at)),
            server_ts=now,
        )

    def _aggregate(self, sess: FocusSession, obs: Observation):
        """把单条观察并入聚合统计，并更新策略运行时态。"""
        # 时长聚合（用 observed_at 与上次观察的差值近似，避免前端计时依赖）
        dt = obs.observed_at - (sess.last_observed_at or obs.observed_at)
        if dt > 0 and dt < 300:  # 单段不超过5分钟，过滤异常
            if obs.presence == PresenceState.AWAY.value:
                sess.sec_away += dt
            elif obs.activity == ActivityState.POSSIBLY_DISTRACTED.value:
                sess.sec_possibly_distracted += dt
            elif obs.activity == ActivityState.FOCUSED.value:
                sess.sec_focused += dt
                # 更新最长连续专注段
                if getattr(sess, "_focus_streak", 0.0) + dt > sess.longest_focus_streak_sec:
                    sess.longest_focus_streak_sec = sess._focus_streak + dt
                sess._focus_streak = getattr(sess, "_focus_streak", 0.0) + dt
            else:
                sess.sec_unknown += dt
                sess._focus_streak = 0.0

        # 连续分心起点（策略用）
        if obs.activity == ActivityState.POSSIBLY_DISTRACTED.value:
            if getattr(sess, "_distraction_since", 0.0) == 0.0:
                sess._distraction_since = obs.observed_at
        else:
            sess._distraction_since = 0.0
            if obs.activity != ActivityState.POSSIBLY_DISTRACTED.value:
                sess._focus_streak = 0.0

        sess.last_presence = obs.presence
        sess.last_activity = obs.activity
        sess.last_confidence = obs.confidence
        sess.last_observed_at = obs.observed_at

    # ---------------- 掉线 / 过期检测 ----------------
    def check_offline_and_pause(self, user_id: str) -> Optional[str]:
        """由后端定时或随请求调用：超过 offline_grace 无观察则自动暂停。"""
        sess = self._active.get(user_id)
        if not sess or sess.status != "active":
            return None
        now = get_current_time().timestamp()
        if now - sess.last_observed_at > self.cfg.offline_grace_sec:
            try:
                self.pause(user_id, reason="auto_offline")
                return "auto_paused_offline"
            except FocusSessionError:
                return None
        return None

    # ---------------- 探班策略触发 ----------------
    def maybe_nudge(self, user_id: str) -> Optional[NudgeEvent]:
        """评估策略，若需探班则返回 NudgeEvent（不在此发消息）。

        同时评估 strict 模式的低频视觉复核：若策略建议视觉复核，
        返回带有 vision_review 标记的 NudgeEvent（调用方据此异步发起复核）。
        """
        sess = self._active.get(user_id)
        if not sess:
            return None
        # 先处理掉线自动暂停
        self.check_offline_and_pause(user_id)
        dec = self.policy.evaluate(sess)
        if not dec.should_nudge:
            # strict 模式下额外评估视觉复核
            vr_dec = self.policy.evaluate_strict_vision_review(sess)
            if vr_dec.should_nudge and vr_dec.vision_review:
                now = get_current_time().timestamp()
                sess.vision_review_last_at = now
                event = NudgeEvent(
                    at=now, reason=vr_dec.reason, mode=sess.mode, message=vr_dec.message
                )
                sess.nudge_events.append(event.to_dict())
                self._persist(sess)
                return event
            return None
        now = get_current_time().timestamp()
        event = NudgeEvent(at=now, reason=dec.reason, mode=sess.mode, message=dec.message)
        sess.nudge_events.append(event.to_dict())
        self._persist(sess)
        return event

    def request_vision_review(self, user_id: str, reviewer: callable) -> Optional[dict]:
        """异步发起低频视觉复核（strict 模式）。

        复查器 `reviewer` 由调用方（router/后台任务）注入，签名为
        `async def reviewer() -> str`（返回对当前帧的自然语言结论）。
        本方法只负责：
        - 调用 reviewer 拿到结论文本；
        - 把结论以结构化信号回灌到会话（不保存任何图像）；
        - 返回 {ok, conclusion, error}。

        reviewer 失败或返回空时不写入任何观察，避免污染统计。
        """
        sess = self._active.get(user_id)
        if not sess or sess.status != "active" or sess.mode != "strict":
            return {"ok": False, "error": "no_active_strict_session"}
        try:
            conclusion = reviewer()
            if not conclusion:
                return {"ok": False, "error": "empty_conclusion"}
            import json
            # 结论文本只作为信号记录，绝不存图像
            signals = ["vision_review"]
            sess.vision_review_events.append({
                "at": get_current_time().timestamp(),
                "conclusion": str(conclusion)[:500],
                "source": "low_freq_vision_review",
            })
            # 把结论摘要作为一次轻量观察信号回流（不计入分心/专注聚合负面）
            sess.last_signals = list(getattr(sess, "last_signals", []))[:0] + signals
            self._persist(sess)
            return {"ok": True, "conclusion": str(conclusion)[:500]}
        except Exception as e:  # pragma: no cover
            logger.warning(f"低频视觉复核失败: {e}")
            return {"ok": False, "error": str(e)}

    # ---------------- 总结 ----------------
    def _finalize_summary(self, sess: FocusSession):
        total_obs = sess.sec_focused + sess.sec_possibly_distracted + sess.sec_away + sess.sec_unknown
        focus_rate = (sess.sec_focused / total_obs * 100) if total_obs > 0 else 0.0
        completeness = (total_obs / max(1, sess.accumulated_active_seconds) * 100) if sess.accumulated_active_seconds > 0 else 0.0
        minutes = int(round(sess.accumulated_active_seconds / 60))
        nudge_count = len(sess.nudge_events)
        recovered = sum(1 for e in sess.nudge_events if e.get("recovered"))
        # 简短自然语言总结（本地模板，不调用 LLM）
        summary = (
            f"本次「{sess.subject}」计划 {sess.planned_minutes} 分钟，实际专注约 {minutes} 分钟。"
            f"专注率约 {focus_rate:.0f}%，其中离开 {int(sess.sec_away//60)} 分钟、疑似分心 {int(sess.sec_possibly_distracted//60)} 分钟。"
            f"被打断 {sess.interruption_count} 次，最长连续专注约 {int(sess.longest_focus_streak_sec//60)} 分钟。"
            f"期间收到陪伴消息 {nudge_count} 次，其中 {recovered} 次在你恢复专注后得到延续。"
        )
        sess.summary_text = summary
        sess._summary_metrics = {  # 仅运行期，落盘时转 dict
            "planned_minutes": sess.planned_minutes,
            "effective_minutes": minutes,
            "focus_rate": round(focus_rate, 1),
            "completeness_rate": round(min(100.0, completeness), 1),
            "sec_focused": sess.sec_focused,
            "sec_possibly_distracted": sess.sec_possibly_distracted,
            "sec_away": sess.sec_away,
            "sec_unknown": sess.sec_unknown,
            "interruption_count": sess.interruption_count,
            "longest_focus_streak_sec": sess.longest_focus_streak_sec,
            "nudge_count": nudge_count,
            "nudge_recovered": recovered,
        }

    # ---------------- 同步到 DailyTracker ----------------
    def _sync_to_daily(self, sess: FocusSession):
        try:
            from core.services.study.daily_tracker import DailyTracker
            tracker = DailyTracker.get_instance()
            tracker.record_session(
                subject=sess.subject,
                topics=[],
                duration_min=int(round(sess.accumulated_active_seconds / 60)),
                notes=f"专注番茄钟（计划{sess.planned_minutes}分钟，专注率"
                      f"{getattr(sess, '_summary_metrics', {}).get('focus_rate', 0.0):.0f}%）",
            )
        except Exception as e:  # pragma: no cover
            logger.warning(f"同步 DailyTracker 失败（不影响会话）: {e}")

    # ---------------- 历史 / 读取 ----------------
    def get_history(self, user_id: str, limit: int = 20) -> List[dict]:
        # 简单实现：扫描落盘目录，按 finished_at 倒序
        from core.services.study.focus_session_models import FocusSession as _FS
        probe = _FS(session_id="probe", user_id=user_id, subject="", planned_minutes=1)
        base = probe.storage_dir()
        import os, glob
        results = []
        if os.path.isdir(base):
            for fp in glob.glob(os.path.join(base, "*.json")):
                try:
                    data = safe_json_load(fp)
                    if data.get("user_id") == user_id and data.get("status") == "finished":
                        results.append(data)
                except Exception:
                    continue
        results.sort(key=lambda x: x.get("finished_at", 0), reverse=True)
        return results[:limit]

    def get_summary(self, user_id: str, session_id: str) -> Optional[dict]:
        sess = self._active.get(user_id)
        if sess and sess.session_id == session_id:
            return sess.to_dict()
        probe = FocusSession(session_id=session_id, user_id=user_id, subject="", planned_minutes=1)
        fp = probe.file_path()
        if os.path.exists(fp):
            return safe_json_load(fp)
        return None

    # ---------------- 持久化 ----------------
    def _persist(self, sess: FocusSession):
        fp = sess.file_path()
        lock = FileLock(sess.lock_path(), timeout=5)
        try:
            with lock:
                safe_json_dump(sess.to_dict(), fp)
        except Timeout:
            logger.warning(f"写入会话锁超时: {fp}")
        except Exception as e:
            logger.error(f"持久化会话失败: {e}")

    def _load_latest_active(self, user_id: str) -> Optional[FocusSession]:
        # 仅恢复 unfinished 的最近一条（进程重启兜底）
        from core.services.study.focus_session_models import FocusSession as _FS
        probe = _FS(session_id="probe", user_id=user_id, subject="", planned_minutes=1)
        base = probe.storage_dir()
        import os, glob
        best = None
        if os.path.isdir(base):
            for fp in glob.glob(os.path.join(base, "*.json")):
                try:
                    data = safe_json_load(fp)
                except Exception:
                    continue
                if data.get("user_id") == user_id and data.get("status") in ("active", "paused"):
                    if best is None or data.get("created_at", 0) > best.created_at:
                        best = self._dict_to_session(data)
        return best

    def _dict_to_session(self, data: dict) -> FocusSession:
        sess = FocusSession(**{k: v for k, v in data.items()
                               if k in FocusSession.__dataclass_fields__})
        sess._seen_sequences = {o.get("sequence") for o in sess.observations if "sequence" in o}
        return sess

    def _require_active(self, user_id: str) -> FocusSession:
        sess = self.get_current(user_id)
        if not sess:
            raise FocusSessionError(f"用户 {user_id} 没有进行中的会话")
        return sess


# 模块级单例
_service: Optional[FocusSessionService] = None


def get_focus_session_service() -> FocusSessionService:
    global _service
    if _service is None:
        _service = FocusSessionService()
    return _service
