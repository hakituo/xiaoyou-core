"""
主动关怀检查器 - 检查节流与时间调度

负责检查间隔的抖动计算和非响应退避策略，包括：
- 间隔抖动（避免固定模式）
- 非响应退避乘数计算
"""
import random

from core.services.active_care.shared.constants import calculate_non_response_backoff


class CheckerThrottle:
    """主动关怀检查器 - 检查节流与时间调度

    封装节流和调度相关的纯计算逻辑，无状态依赖。
    """

    @staticmethod
    def apply_interval_jitter(
        base_seconds: float,
        *,
        min_seconds: int = 30,
        jitter_ratio: float = 0.20,
    ) -> int:
        """对基础间隔施加随机抖动

        Args:
            base_seconds: 基础间隔秒数
            min_seconds: 最小间隔秒数
            jitter_ratio: 抖动比例（0~0.45）

        Returns:
            抖动后的间隔秒数（向下取整，不低于 min_seconds）
        """
        base = max(float(min_seconds), float(base_seconds or 0.0))
        ratio = max(0.0, min(float(jitter_ratio or 0.0), 0.45))
        if ratio <= 0.0:
            return int(base)
        low = max(float(min_seconds), base * (1.0 - ratio))
        high = max(low, base * (1.0 + ratio))
        return int(max(float(min_seconds), random.uniform(low, high)))

    @staticmethod
    def non_response_backoff_multiplier(non_response_count: int) -> float:
        """计算非响应退避乘数

        连续无响应次数越多，下次检查间隔越长
        """
        return calculate_non_response_backoff(non_response_count)
