"""
作息适配器
从用户的每日记录中学习作息规律，动态调整推断睡眠的时间窗口和沉默阈值。

替代 constants.py 中的硬编码时段：
- PROBABLE_SLEEP_NIGHT_HOUR_START/END (0-6点)
- PROBABLE_SLEEP_MORNING_HOUR_START/END (6-10点)
- PROBABLE_SLEEP_EVENING_HOUR_START/END (18-24点)
- PROBABLE_SLEEP_SILENCE_NIGHT/MORNING/EVENING_SECONDS

学习逻辑：
1. 读取最近 N 天的起床/睡觉记录
2. 计算典型睡觉时间和起床时间
3. 根据典型作息动态调整推断睡眠的时间窗口
4. 夜猫子用户（通常凌晨2点睡）不会被0点就推断睡眠
5. 早起用户（通常6点起）不会被7点还认为在睡
"""
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from core.utils.logger import get_module_logger
from core.services.active_care.shared.constants import (
    PROBABLE_SLEEP_SILENCE_NIGHT_SECONDS,
    PROBABLE_SLEEP_SILENCE_MORNING_SECONDS,
    PROBABLE_SLEEP_SILENCE_EVENING_SECONDS,
    PROBABLE_SLEEP_NIGHT_HOUR_START,
    PROBABLE_SLEEP_NIGHT_HOUR_END,
    PROBABLE_SLEEP_MORNING_HOUR_START,
    PROBABLE_SLEEP_MORNING_HOUR_END,
    PROBABLE_SLEEP_EVENING_HOUR_START,
    PROBABLE_SLEEP_EVENING_HOUR_END,
)

logger = get_module_logger("SCHEDULE_ADAPTER", "active_care_schedule.log")

# 学习参数
_DEFAULT_LEARN_DAYS = 7
_MIN_SAMPLES_FOR_LEARNING = 3  # 至少3天数据才启用自适应
_SLEEP_HOUR_OUTLIER_THRESHOLD = 4.0  # 睡觉时间偏离中位数超过4小时视为异常值


class ScheduleAdapter:
    """作息适配器：从用户历史记录学习作息规律，动态调整推断睡眠参数"""

    def __init__(self):
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_ts: float = 0.0
        self._cache_ttl: float = 1800.0  # 缓存30分钟

    def get_adaptive_params(self, now: Optional[float] = None) -> Dict[str, Any]:
        """获取自适应的推断睡眠参数

        Returns:
            {
                "night_hour_start": int,     # 自适应深夜时段开始
                "night_hour_end": int,       # 自适应深夜时段结束
                "morning_hour_start": int,   # 自适应早上时段开始
                "morning_hour_end": int,     # 自适应早上时段结束
                "evening_hour_start": int,   # 自适应晚间时段开始
                "evening_hour_end": int,     # 自适应晚间时段结束
                "night_silence_seconds": int,   # 自适应深夜沉默阈值
                "morning_silence_seconds": int, # 自适应早上沉默阈值
                "evening_silence_seconds": int, # 自适应晚间沉默阈值
                "is_adaptive": bool,            # 是否启用了自适应（数据不足时为 False）
                "typical_sleep_hour": float,    # 典型睡觉时间（小时）
                "typical_wakeup_hour": float,   # 典型起床时间（小时）
            }
        """
        now = now or time.time()

        # 检查缓存
        if self._cache and (now - self._cache_ts) < self._cache_ttl:
            return self._cache

        # 尝试从历史记录学习
        schedule_data = self._learn_schedule()

        if schedule_data.get("is_adaptive"):
            params = self._compute_adaptive_params(schedule_data)
        else:
            params = self._get_default_params()

        params["is_adaptive"] = schedule_data.get("is_adaptive", False)
        params["typical_sleep_hour"] = schedule_data.get("typical_sleep_hour", -1.0)
        params["typical_wakeup_hour"] = schedule_data.get("typical_wakeup_hour", -1.0)

        self._cache = params
        self._cache_ts = now
        return params

    def _learn_schedule(self, days: int = _DEFAULT_LEARN_DAYS) -> Dict[str, Any]:
        """从最近几天的记录推断作息规律

        Returns:
            {
                "is_adaptive": bool,
                "typical_sleep_hour": float,  # 典型睡觉时间（0-24小时制）
                "typical_wakeup_hour": float, # 典型起床时间（0-24小时制）
                "sleep_samples": int,
                "wakeup_samples": int,
            }
        """
        try:
            from core.services.daily.manager import DailyActivityManager
            mgr = DailyActivityManager()
            today = mgr._normalize_date()
            today_dt = datetime.strptime(today, "%Y-%m-%d")

            sleep_hours: List[float] = []
            wakeup_hours: List[float] = []

            for i in range(1, days + 1):
                past_dt = today_dt - timedelta(days=i)
                past_str = past_dt.strftime("%Y-%m-%d")
                data = mgr._load_record(past_str)
                sch = data.get("schedule", {})

                sleep_str = sch.get("sleep")
                wakeup_str = sch.get("wakeup")

                if sleep_str:
                    hour = self._parse_hour(sleep_str)
                    if hour is not None:
                        # 睡觉时间：22-24点保持原值，0-9点视为凌晨（+24归一化到24-33）
                        if 0 <= hour < 9:
                            sleep_hours.append(hour + 24.0)
                        else:
                            sleep_hours.append(float(hour))

                if wakeup_str:
                    hour = self._parse_hour(wakeup_str)
                    if hour is not None:
                        wakeup_hours.append(float(hour))

            if len(sleep_hours) < _MIN_SAMPLES_FOR_LEARNING and len(wakeup_hours) < _MIN_SAMPLES_FOR_LEARNING:
                return {"is_adaptive": False, "typical_sleep_hour": -1.0, "typical_wakeup_hour": -1.0,
                        "sleep_samples": len(sleep_hours), "wakeup_samples": len(wakeup_hours)}

            # 计算中位数（去除异常值）
            typical_sleep = self._robust_median(sleep_hours) if sleep_hours else -1.0
            typical_wakeup = self._robust_median(wakeup_hours) if wakeup_hours else -1.0

            # 归一化回 0-24 小时制
            if typical_sleep >= 24.0:
                typical_sleep -= 24.0

            is_adaptive = (
                (len(sleep_hours) >= _MIN_SAMPLES_FOR_LEARNING or len(wakeup_hours) >= _MIN_SAMPLES_FOR_LEARNING)
                and typical_sleep >= 0
            )

            logger.info(
                "ScheduleAdapter: 学习到作息规律 - 典型睡觉=%.1f点, 典型起床=%.1f点, "
                "sleep_samples=%d, wakeup_samples=%d, is_adaptive=%s",
                typical_sleep, typical_wakeup,
                len(sleep_hours), len(wakeup_hours), is_adaptive,
            )

            return {
                "is_adaptive": is_adaptive,
                "typical_sleep_hour": typical_sleep,
                "typical_wakeup_hour": typical_wakeup,
                "sleep_samples": len(sleep_hours),
                "wakeup_samples": len(wakeup_hours),
            }

        except Exception as e:
            logger.warning("ScheduleAdapter: 学习作息规律失败: %s", e)
            return {"is_adaptive": False, "typical_sleep_hour": -1.0, "typical_wakeup_hour": -1.0,
                    "sleep_samples": 0, "wakeup_samples": 0}

    def _compute_adaptive_params(self, schedule_data: Dict[str, Any]) -> Dict[str, Any]:
        """根据学习到的作息规律计算自适应参数

        核心逻辑：
        - 深夜时段：从典型睡觉时间前2小时开始，到典型起床时间前2小时结束
        - 早上时段：从典型起床时间前2小时开始，到典型起床时间后2小时结束
        - 晚间时段：从典型睡觉时间前4小时开始，到24点结束
        - 沉默阈值：根据作息规律微调
        """
        typical_sleep = schedule_data.get("typical_sleep_hour", 23.0)
        typical_wakeup = schedule_data.get("typical_wakeup_hour", 8.0)

        # 如果没有学习到睡觉时间，使用默认值
        if typical_sleep < 0:
            typical_sleep = 23.0
        if typical_wakeup < 0:
            typical_wakeup = 8.0

        # 自适应深夜时段：典型睡觉前2小时 ~ 典型起床前2小时
        # 例如：用户通常2点睡9点起 → 深夜时段 0点-7点
        # 例如：用户通常23点睡7点起 → 深夜时段 21点-5点
        night_start = max(0, int(typical_sleep - 2.0))
        night_end = max(0, min(24, int(typical_wakeup - 2.0)))

        # 确保深夜时段至少4小时
        if night_end <= night_start + 4:
            night_end = min(24, night_start + 4)

        # 自适应早上时段：典型起床前2小时 ~ 典型起床后3小时
        # 例如：用户通常9点起 → 早上时段 7点-12点
        morning_start = max(0, int(typical_wakeup - 2.0))
        morning_end = min(24, int(typical_wakeup + 3.0))

        # 自适应晚间时段：典型睡觉前4小时 ~ 24点
        # 例如：用户通常2点睡 → 晚间时段 22点-24点（2-4=-2，取max(18,-2)=18不对，需要特殊处理）
        # 例如：用户通常23点睡 → 晚间时段 19点-24点
        if typical_sleep >= 4.0:
            # 正常作息（4点之前睡），晚间从睡觉前4小时开始
            evening_start = max(18, int(typical_sleep - 4.0))
        else:
            # 极端夜猫子（4点之后才睡），晚间从22点开始
            evening_start = 22
        evening_end = 24

        # 自适应沉默阈值
        # 夜猫子（睡觉晚）的深夜沉默阈值应该更长，因为他们可能凌晨还在活动
        # 早起鸟（起床早）的早上沉默阈值可以短一些
        # 计算睡觉时间偏差：将睡觉时间归一化到0-24范围，以23点为基准
        # 例如：2点睡 → 偏差=3小时（比23点晚3小时）
        # 例如：23点睡 → 偏差=0小时
        # 例如：1点睡 → 偏差=2小时
        if typical_sleep < 12.0:
            # 凌晨睡觉（0-12点），视为比23点晚 (typical_sleep + 1) 小时
            sleep_deviation = typical_sleep + 1.0
        else:
            sleep_deviation = max(0.0, typical_sleep - 23.0)
        wakeup_deviation = max(0.0, 8.0 - typical_wakeup)  # 相对于8点的偏移

        night_silence = int(PROBABLE_SLEEP_SILENCE_NIGHT_SECONDS * (1.0 + sleep_deviation * 0.3))
        morning_silence = int(PROBABLE_SLEEP_SILENCE_MORNING_SECONDS * (1.0 - wakeup_deviation * 0.1))
        evening_silence = int(PROBABLE_SLEEP_SILENCE_EVENING_SECONDS * (1.0 + sleep_deviation * 0.2))

        # 确保沉默阈值在合理范围内
        night_silence = max(3600, min(night_silence, 14400))  # 1-4小时
        morning_silence = max(5400, min(morning_silence, 14400))  # 1.5-4小时
        evening_silence = max(1800, min(evening_silence, 7200))  # 0.5-2小时

        logger.info(
            "ScheduleAdapter: 自适应参数 - 夜间=%d-%d点(沉默%d秒), "
            "早上=%d-%d点(沉默%d秒), 晚间=%d-%d点(沉默%d秒)",
            night_start, night_end, night_silence,
            morning_start, morning_end, morning_silence,
            evening_start, evening_end, evening_silence,
        )

        return {
            "night_hour_start": night_start,
            "night_hour_end": night_end,
            "morning_hour_start": morning_start,
            "morning_hour_end": morning_end,
            "evening_hour_start": evening_start,
            "evening_hour_end": evening_end,
            "night_silence_seconds": night_silence,
            "morning_silence_seconds": morning_silence,
            "evening_silence_seconds": evening_silence,
        }

    def _get_default_params(self) -> Dict[str, Any]:
        """返回默认的硬编码参数（与 constants.py 一致）"""
        return {
            "night_hour_start": PROBABLE_SLEEP_NIGHT_HOUR_START,
            "night_hour_end": PROBABLE_SLEEP_NIGHT_HOUR_END,
            "morning_hour_start": PROBABLE_SLEEP_MORNING_HOUR_START,
            "morning_hour_end": PROBABLE_SLEEP_MORNING_HOUR_END,
            "evening_hour_start": PROBABLE_SLEEP_EVENING_HOUR_START,
            "evening_hour_end": PROBABLE_SLEEP_EVENING_HOUR_END,
            "night_silence_seconds": PROBABLE_SLEEP_SILENCE_NIGHT_SECONDS,
            "morning_silence_seconds": PROBABLE_SLEEP_SILENCE_MORNING_SECONDS,
            "evening_silence_seconds": PROBABLE_SLEEP_SILENCE_EVENING_SECONDS,
        }

    @staticmethod
    def _parse_hour(time_str: str) -> Optional[float]:
        """解析 HH:MM 格式的时间字符串为小时数"""
        try:
            parts = str(time_str or "").strip().split(":")
            if len(parts) >= 2:
                h = int(parts[0])
                m = int(parts[1])
                return float(h) + float(m) / 60.0
        except (ValueError, IndexError):
            pass
        return None

    @staticmethod
    def _robust_median(values: List[float]) -> float:
        """计算鲁棒中位数（去除异常值后取中位数）"""
        if not values:
            return -1.0
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        median = sorted_vals[n // 2] if n % 2 == 1 else (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0

        # 去除偏离中位数超过阈值的异常值
        filtered = [v for v in sorted_vals if abs(v - median) <= _SLEEP_HOUR_OUTLIER_THRESHOLD]
        if not filtered:
            return median

        n2 = len(filtered)
        return filtered[n2 // 2] if n2 % 2 == 1 else (filtered[n2 // 2 - 1] + filtered[n2 // 2]) / 2.0

    def invalidate_cache(self):
        """手动清除缓存（在作息记录更新后调用）"""
        self._cache = None
        self._cache_ts = 0.0


# 单例
_instance: Optional[ScheduleAdapter] = None


def get_schedule_adapter() -> ScheduleAdapter:
    global _instance
    if _instance is None:
        _instance = ScheduleAdapter()
    return _instance
