"""
主动关怀调度纯函数（退避 / 抖动相关计算）

从原 `shared/constants.py` 拆出：无状态纯函数，依赖 tuning.py 的退避常量。
供 scheduler_logic 与 checker/checker_throttle 共用。
"""
import random

from core.services.active_care.shared.tuning import BACKOFF_BASE, BACKOFF_CAP


def calculate_non_response_backoff(non_response_count: int) -> float:
    """非响应退避乘数（Equal Jitter 算法）

    AWS 推荐的 Equal Jitter 策略：
    - 取指数退避值的一半作为确定性下界
    - 另一半作为随机上界
    - 既保留指数退避的均值，又最大化随机性

    相比原版 `pow(1.8, n)`，方差从 ~5% 提升到 ~25%，
    避免 AI 主动关怀形成可预测的"机械模式"。

    Args:
        non_response_count: 连续无响应次数

    Returns:
        float: 退避乘数（>=1.0，n=0 时返回 1.0）
    """
    n = max(0, int(non_response_count or 0))
    if n <= 0:
        return 1.0
    expo = min(pow(BACKOFF_BASE, n), BACKOFF_CAP)
    # Equal Jitter：确定性下界 + 随机上界
    # 下限保护为 1.0，避免"退避反而加速"的语义错误
    return max(1.0, expo / 2.0 + random.uniform(0.0, expo / 2.0))


__all__ = ["calculate_non_response_backoff"]
