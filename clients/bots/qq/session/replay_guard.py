"""离线重放消息的时效守卫。

服务端离线队列在 QQ 重连时会把暂存消息原样重放。主动关怀类内容
（晚安 / 早安 / 状态播报）时效性极强，重放一条几小时前的消息只是重复
打扰，因此接收端独立做一次时效判断，作为服务端 TTL 之外的双保险。
"""
import time
from typing import Any, Dict, Optional

# 离线重放消息的最大可接受年龄，与服务端 proactive_offline_ttl 对齐。
# 服务端已按 TTL 过滤，这里用于覆盖旧 payload、手动 flush、TTL 被调大
# 或两端版本不一致的情况。
OFFLINE_REPLAY_MAX_AGE_SECONDS = 10 * 60


def offline_replay_age(data: Dict[str, Any]) -> Optional[float]:
    """离线重放消息的年龄（秒）；非重放消息返回 None。"""
    if not data.get("is_offline_replay"):
        return None
    queued_at = data.get("offline_queued_at")
    if queued_at is None:
        queued_at = data.get("timestamp")
    try:
        return max(0.0, time.time() - float(queued_at))
    except (TypeError, ValueError):
        return None


def is_stale_offline_replay(data: Dict[str, Any]) -> bool:
    """判断一条重放消息是否已过时效（非重放消息一律视为新鲜）。"""
    age = offline_replay_age(data)
    return age is not None and age > OFFLINE_REPLAY_MAX_AGE_SECONDS
