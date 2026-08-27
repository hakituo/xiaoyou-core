"""
睡眠策略模块
负责管理睡眠会话、晚安探针策略、专注模式策略
"""
from typing import Any, Dict

from core.utils.logger import get_module_logger

logger = get_module_logger("ACTIVE_CARE_SLEEP", "active_care_schedule.log")


class SleepPolicy:
    """睡眠策略管理器，负责处理睡眠相关的策略决策"""
    
    def build_sleep_session_archive_updates(
        self,
        state_data: Dict[str, Any],
        now_ts: float,
        safe_ts_func=None
    ) -> Dict[str, Any]:
        """
        构建睡眠会话归档更新数据
        
        Args:
            state_data: 当前状态数据
            now_ts: 当前时间戳
            safe_ts_func: 安全时间戳转换函数
            
        Returns:
            睡眠会话归档数据
        """
        state = state_data if isinstance(state_data, dict) else {}
        
        # 使用传入的 safe_ts 函数或默认实现
        if safe_ts_func:
            start_ts = safe_ts_func(state.get("last_goodnight_ts"))
            end_ts = safe_ts_func(now_ts)
        else:
            try:
                start_ts = float(state.get("last_goodnight_ts") or 0.0)
                end_ts = float(now_ts)
            except (TypeError, ValueError):
                start_ts = 0.0
                end_ts = 0.0
        
        duration_seconds = 0
        if start_ts > 0 and end_ts > start_ts:
            duration_seconds = int(end_ts - start_ts)
        
        return {
            "last_sleep_session_start_ts": start_ts,
            "last_sleep_session_end_ts": end_ts,
            "last_sleep_session_duration_seconds": duration_seconds,
        }

    def resolve_sleep_probe_policy(
        self,
        *,
        now: float,
        sleep_session_active: bool,
        allow_goodnight_probe: bool,
        reduced_mode_active: bool,
        reduced_mode_reason: str,
        last_goodnight_ts: float,
        last_goodnight_probe_ts: float,
        default_next_check: int,
        min_gap_seconds: int,
        goodnight_probe_gap_seconds: int,
        goodnight_low_disturb_gap_seconds: int,
    ) -> Dict[str, Any]:
        """
        解析睡眠探针策略
        
        决定是否允许在睡眠会话期间发送探针消息
        
        Args:
            now: 当前时间戳
            sleep_session_active: 睡眠会话是否活跃
            allow_goodnight_probe: 是否允许晚安探针
            reduced_mode_active: 减少模式是否活跃
            reduced_mode_reason: 减少模式原因
            last_goodnight_ts: 最后一次晚安时间戳
            last_goodnight_probe_ts: 最后一次晚安探针时间戳
            default_next_check: 默认下次检查间隔（秒）
            min_gap_seconds: 最小间隔（秒）
            goodnight_probe_gap_seconds: 晚安探针间隔（秒）
            goodnight_low_disturb_gap_seconds: 晚安低打扰间隔（秒）
            
        Returns:
            {
                "allow_send": bool,
                "skip_reason": str,
                "wait_seconds": int,
                "is_probe": bool,
                "is_first_probe": bool,
            }
        """
        if not sleep_session_active:
            if reduced_mode_active and reduced_mode_reason == "sleep_hint":
                return self._resolve_probable_sleep_probe_policy(
                    now=now,
                    last_goodnight_probe_ts=last_goodnight_probe_ts,
                    default_next_check=default_next_check,
                    goodnight_low_disturb_gap_seconds=goodnight_low_disturb_gap_seconds,
                )
            return {"allow_send": True, "skip_reason": "", "wait_seconds": 0}

        if not allow_goodnight_probe:
            return {
                "allow_send": False,
                "skip_reason": "goodnight_quiet_block",
                "wait_seconds": max(default_next_check, 3600),
            }

        elapsed_since_goodnight = max(0.0, now - last_goodnight_ts) if last_goodnight_ts > 0 else 0.0

        # 探针窗口：10-30分钟（用户说晚安后，等10分钟再确认是否真的睡了）
        probe_window_min = 600
        probe_window_max = 1800
        
        if elapsed_since_goodnight < probe_window_min:
            wait_seconds = max(default_next_check, int(probe_window_min - elapsed_since_goodnight))
            return {
                "allow_send": False,
                "skip_reason": "goodnight_probe_window_wait",
                "wait_seconds": wait_seconds,
            }

        # 首次探针
        if last_goodnight_probe_ts <= 0 and elapsed_since_goodnight < probe_window_max:
            return {
                "allow_send": True,
                "skip_reason": "",
                "wait_seconds": 0,
                "is_probe": True,
                "is_first_probe": True,
            }

        if last_goodnight_probe_ts <= 0 and elapsed_since_goodnight >= probe_window_max:
            return {
                "allow_send": True,
                "skip_reason": "",
                "wait_seconds": 0,
                "is_probe": True,
                "is_first_probe": True,
            }

        probe_gap = max(goodnight_probe_gap_seconds, 3600)

        if last_goodnight_probe_ts > 0:
            elapsed_since_probe = now - last_goodnight_probe_ts
            elapsed_since_goodnight_total = now - last_goodnight_ts if last_goodnight_ts > 0 else 0

            if elapsed_since_goodnight_total < 3600:
                probe_gap = max(1800, goodnight_probe_gap_seconds)
            elif elapsed_since_goodnight_total < 2 * 3600:
                probe_gap = max(3600, goodnight_probe_gap_seconds)
            else:
                probe_gap = max(goodnight_low_disturb_gap_seconds, 2 * 3600)

            if elapsed_since_probe < probe_gap:
                wait_seconds = max(default_next_check, int(probe_gap - elapsed_since_probe))
                return {
                    "allow_send": False,
                    "skip_reason": "goodnight_probe_gap",
                    "wait_seconds": wait_seconds,
                }

        return {
            "allow_send": True,
            "skip_reason": "",
            "wait_seconds": 0,
            "is_probe": True,
        }

    def _resolve_probable_sleep_probe_policy(
        self,
        *,
        now: float,
        last_goodnight_probe_ts: float,
        default_next_check: int,
        goodnight_low_disturb_gap_seconds: int,
    ) -> Dict[str, Any]:
        """sleep_hint 模式的探针策略

        probable_sleep 已于 2026-07-30 移除，此方法现在只处理 sleep_hint。
        与 goodnight 模式类似但间隔更长：
        - 首次探针：允许发送
        - 后续探针：至少间隔 PROBABLE_SLEEP_PROBE_GAP_SECONDS（默认1小时）
        - wait_seconds 上限 3600s（1小时），避免过长时间阻塞
        """
        from core.services.active_care.shared.constants import PROBABLE_SLEEP_PROBE_GAP_SECONDS

        probe_gap = min(goodnight_low_disturb_gap_seconds, PROBABLE_SLEEP_PROBE_GAP_SECONDS)
        max_wait_seconds = 3600

        if last_goodnight_probe_ts <= 0:
            return {
                "allow_send": True,
                "skip_reason": "",
                "wait_seconds": 0,
                "is_probe": True,
                "is_first_probe": True,
            }

        elapsed_since_probe = now - last_goodnight_probe_ts
        if elapsed_since_probe < probe_gap:
            wait_seconds = max(default_next_check, int(probe_gap - elapsed_since_probe))
            wait_seconds = min(wait_seconds, max_wait_seconds)
            return {
                "allow_send": False,
                "skip_reason": "sleep_hint_probe_gap",
                "wait_seconds": wait_seconds,
            }

        return {
            "allow_send": True,
            "skip_reason": "",
            "wait_seconds": 0,
            "is_probe": True,
        }

    def resolve_focus_reduced_policy(
        self,
        *,
        now: float,
        reduced_mode_active: bool,
        reduced_mode_reason: str,
        latest_user_signal_ts: float,
        last_sent_ts: float,
        default_next_check: int,
        focus_user_quiet_seconds: int,
        focus_low_disturb_gap_seconds: int,
    ) -> Dict[str, Any]:
        """
        解析专注模式减少策略
        
        决定是否在专注模式期间允许发送消息
        
        Args:
            now: 当前时间戳
            reduced_mode_active: 减少模式是否活跃
            reduced_mode_reason: 减少模式原因
            latest_user_signal_ts: 最新用户信号时间戳
            last_sent_ts: 最后发送时间戳
            default_next_check: 默认下次检查间隔（秒）
            focus_user_quiet_seconds: 专注模式用户安静期（秒）
            focus_low_disturb_gap_seconds: 专注模式低打扰间隔（秒）
            
        Returns:
            {
                "allow_send": bool,
                "skip_reason": str,
                "wait_seconds": int,
            }
        """
        if not (reduced_mode_active and str(reduced_mode_reason or "") == "focus"):
            return {"allow_send": True, "skip_reason": "", "wait_seconds": 0}
        
        # 用户最近有交互，等待安静期结束
        if latest_user_signal_ts > 0:
            elapsed_user = max(0.0, now - latest_user_signal_ts)
            if elapsed_user < focus_user_quiet_seconds:
                wait_seconds = max(
                    default_next_check,
                    int(focus_user_quiet_seconds - elapsed_user),
                )
                return {
                    "allow_send": False,
                    "skip_reason": "focus_recent_user_interaction_guard",
                    "wait_seconds": wait_seconds,
                }
        
        # 低打扰退避
        if last_sent_ts > 0:
            elapsed_sent = max(0.0, now - last_sent_ts)
            if elapsed_sent < focus_low_disturb_gap_seconds:
                wait_seconds = max(
                    default_next_check,
                    int(focus_low_disturb_gap_seconds - elapsed_sent),
                )
                return {
                    "allow_send": False,
                    "skip_reason": "focus_low_disturb_backoff",
                    "wait_seconds": wait_seconds,
                }
        
        return {"allow_send": True, "skip_reason": "", "wait_seconds": 0}
