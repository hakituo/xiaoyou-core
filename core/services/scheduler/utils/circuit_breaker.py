"""
断路器（Circuit Breaker）机制
提供资源隔离保护，防止级联故障
"""

import time
import logging
from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class BreakerState:
    """单个断路器状态"""
    failures: int = 0
    open_until: float = 0.0
    cooldown_s: float = 5.0

    def is_open(self) -> bool:
        return time.time() < self.open_until

    def reset(self, min_cooldown_s: float):
        self.failures = 0
        self.open_until = 0.0
        self.cooldown_s = min_cooldown_s

    def record_failure(self, threshold: int, min_cooldown_s: float, max_cooldown_s: float,
                       logger: logging.Logger, kind: str) -> None:
        self.failures += 1
        if self.failures < threshold:
            return
        cooldown_s = min(max(min_cooldown_s, self.cooldown_s), max_cooldown_s)
        self.open_until = time.time() + cooldown_s
        self.cooldown_s = min(cooldown_s * 2.0, max_cooldown_s)
        logger.warning(
            "Circuit Breaker 触发熔断 (kind=%s, failures=%d, cooldown=%.1fs)",
            kind, self.failures, cooldown_s,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_open": self.is_open(),
            "failures": self.failures,
            "cooldown_s": self.cooldown_s,
            "open_until": self.open_until,
        }


class BreakerRegistry:
    """断路器注册表"""

    def __init__(self):
        self._breakers: Dict[str, BreakerState] = {}

    def get_or_create(self, kind: str, min_cooldown_s: float = 5.0) -> BreakerState:
        if kind not in self._breakers:
            self._breakers[kind] = BreakerState(cooldown_s=min_cooldown_s)
        return self._breakers[kind]

    def is_open(self, kind: str) -> bool:
        state = self._breakers.get(kind)
        return state.is_open() if state else False

    def on_success(self, kind: str, min_cooldown_s: float) -> None:
        state = self._breakers.get(kind)
        if state:
            state.reset(min_cooldown_s)

    def on_failure(self, kind: str, threshold: int, min_cooldown_s: float,
                   max_cooldown_s: float, logger: logging.Logger) -> None:
        state = self._breakers.get(kind)
        if state:
            state.record_failure(threshold, min_cooldown_s, max_cooldown_s, logger, kind)

    def get_status(self) -> Dict[str, Dict[str, Any]]:
        return {kind: state.to_dict() for kind, state in self._breakers.items()}


def create_breaker_state(min_cooldown_s: float) -> Dict[str, Dict[str, Any]]:
    """创建断路器初始状态（兼容旧接口，返回dict格式）"""
    return {
        "llm": {"failures": 0, "open_until": 0.0, "cooldown_s": min_cooldown_s},
        "image": {"failures": 0, "open_until": 0.0, "cooldown_s": min_cooldown_s},
    }


def breaker_is_open(breaker: Dict[str, Dict[str, Any]], kind: str) -> bool:
    """检查断路器是否处于熔断状态"""
    state = breaker.get(kind)
    if not isinstance(state, dict):
        return False
    return time.time() < float(state.get("open_until", 0.0) or 0.0)


def breaker_on_success(
    breaker: Dict[str, Dict[str, Any]], kind: str, min_cooldown_s: float
) -> None:
    """成功时重置断路器"""
    state = breaker.get(kind)
    if not isinstance(state, dict):
        return
    state["failures"] = 0
    state["open_until"] = 0.0
    state["cooldown_s"] = min_cooldown_s


def breaker_on_failure(
    breaker: Dict[str, Dict[str, Any]],
    kind: str,
    threshold: int,
    min_cooldown_s: float,
    max_cooldown_s: float,
    logger: logging.Logger,
) -> None:
    """失败时增加计数，达到阈值触发熔断（指数退避冷却）"""
    state = breaker.get(kind)
    if not isinstance(state, dict):
        return

    state["failures"] = int(state.get("failures", 0) or 0) + 1
    if int(state["failures"]) < int(threshold):
        return

    cooldown_s = float(state.get("cooldown_s", min_cooldown_s) or min_cooldown_s)
    cooldown_s = min(max(min_cooldown_s, cooldown_s), max_cooldown_s)
    state["open_until"] = time.time() + cooldown_s
    state["cooldown_s"] = min(cooldown_s * 2.0, max_cooldown_s)
    logger.warning(
        "Circuit Breaker 触发熔断 (kind=%s, failures=%d, cooldown=%.1fs)",
        kind,
        int(state["failures"]),
        cooldown_s,
    )


def get_breaker_status(breaker: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """获取所有断路器的状态快照"""
    status: Dict[str, Dict[str, Any]] = {}
    for kind, state in breaker.items():
        if not isinstance(state, dict):
            continue
        status[kind] = {
            "is_open": time.time() < float(state.get("open_until", 0.0) or 0.0),
            "failures": int(state.get("failures", 0) or 0),
            "cooldown_s": float(state.get("cooldown_s", 0.0) or 0.0),
            "open_until": float(state.get("open_until", 0.0) or 0.0),
        }
    return status
