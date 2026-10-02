"""主动关怀 send / defer 输出协议（Active Care Prompt v2）

2026-09-04 决策协议收敛为一行：
    Decision 只回答“发送还是延后”，不负责写最终给用户看的 text。

两个出口：
    send_active_care  → 现在值得联系（最终文本由生成层在 send 后产出）
    defer_active_care → 现在不值得联系，给出 retry_after_seconds 下次重判

双通道归一化（保留工具调用 + JSON 兜底）：
    1. function calling：模型支持工具调用时，调用 send_active_care /
       defer_active_care 两个终止型工具（send 工具不再带 text 参数）；
    2. JSON fallback：不支持工具调用的模型按 schema 输出
       {action, intent, reason_code, retry_after_seconds}。

两条通道统一归一化为 `ActiveCareDecisionAction`，下游只认这一个结构。
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

# 两个出口的工具名 / action 取值
SEND_TOOL = "send_active_care"
DEFER_TOOL = "defer_active_care"
ACTION_SEND = SEND_TOOL
ACTION_DEFER = DEFER_TOOL

# 终止型工具：命中即结束决策循环，不需要真正的工具执行
TERMINAL_TOOL_NAMES = frozenset({SEND_TOOL, DEFER_TOOL})

# retry_after_seconds 合法区间
MIN_RETRY_AFTER_SECONDS = 60
MAX_RETRY_AFTER_SECONDS = 4 * 3600
DEFAULT_RETRY_AFTER_SECONDS = 30 * 60


@dataclass
class ActiveCareDecisionAction:
    """一次决策的归一化出口结果（工具调用与 JSON 两条通道共用）。

    Attributes:
        action: ACTION_SEND / ACTION_DEFER。
                解析失败时为 ACTION_DEFER（默认不发送，宁可不发也不错发）。
        intent: 本次候选意图（由上游动作选择器已选定的 chosen_action）。
        reason_code: send 的理由/状态码；defer 时的简短原因。
        retry_after_seconds: defer 时下次重判间隔（秒），>= 60。
        source: 来源标记（tool_call / json / fallback），便于排查。
    """

    action: str = ACTION_DEFER
    intent: str = ""
    reason_code: str = ""
    retry_after_seconds: int = DEFAULT_RETRY_AFTER_SECONDS
    source: str = ""

    @property
    def should_send(self) -> bool:
        return self.action == ACTION_SEND


def clamp_retry_after_seconds(value: Any) -> int:
    """把任意输入规整到合法的重判间隔（秒）。"""
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return DEFAULT_RETRY_AFTER_SECONDS
    return max(MIN_RETRY_AFTER_SECONDS, min(MAX_RETRY_AFTER_SECONDS, seconds))


def build_send_action(
    reason_code: str = "", *, intent: str = "", source: str = ""
) -> ActiveCareDecisionAction:
    """构造 send 出口（不再携带 text；最终文本由生成层产出）。"""
    return ActiveCareDecisionAction(
        action=ACTION_SEND,
        intent=str(intent or "").strip(),
        reason_code=str(reason_code or "").strip()[:80],
        retry_after_seconds=0,
        source=source,
    )


def build_defer_action(
    reason: str,
    retry_after_seconds: Any = None,
    *,
    intent: str = "",
    source: str = "",
) -> ActiveCareDecisionAction:
    """构造 defer 出口。"""
    return ActiveCareDecisionAction(
        action=ACTION_DEFER,
        intent=str(intent or "").strip(),
        reason_code=str(reason or "").strip()[:300],
        retry_after_seconds=clamp_retry_after_seconds(
            DEFAULT_RETRY_AFTER_SECONDS
            if retry_after_seconds is None
            else retry_after_seconds
        ),
        source=source,
    )


def parse_terminal_tool_call(
    tool_name: str,
    arguments: Optional[Dict[str, Any]],
    *,
    intent: str = "",
) -> Optional[ActiveCareDecisionAction]:
    """把一次终止型工具调用解析为归一化决策出口。

    Args:
        tool_name: 工具名，只处理 send_active_care / defer_active_care。
        arguments: 工具参数字典（可能已被 json.loads 解析过）。
        intent: 上游已选定的候选意图。

    Returns:
        归一化出口；非终止型工具返回 None。
    """
    name = str(tool_name or "").strip()
    if name not in TERMINAL_TOOL_NAMES:
        return None
    args = arguments if isinstance(arguments, dict) else {}

    if name == SEND_TOOL:
        return build_send_action(
            reason_code=str(args.get("reason_code") or "").strip(),
            intent=intent,
            source="tool_call",
        )

    return build_defer_action(
        str(args.get("reason") or "").strip() or "未给出原因",
        args.get("retry_after_seconds"),
        intent=intent,
        source="tool_call",
    )


def decision_action_to_dict(action: ActiveCareDecisionAction) -> Dict[str, Any]:
    """把归一化出口转成下游（checker / execute_send_or_skip）消费的决策字典。

    保留 should_send / next_check_seconds 兼容键，老调用方无需改动。
    """
    if action.action == ACTION_SEND:
        next_check_seconds = 600
    else:
        next_check_seconds = int(action.retry_after_seconds)
    return {
        "action": action.action,
        "intent": action.intent,
        "reason_code": action.reason_code,
        "retry_after_seconds": int(action.retry_after_seconds),
        "should_send": action.should_send,
        "next_check_seconds": max(30, next_check_seconds),
        "source": action.source,
    }


__all__ = [
    "SEND_TOOL",
    "DEFER_TOOL",
    "ACTION_SEND",
    "ACTION_DEFER",
    "TERMINAL_TOOL_NAMES",
    "MIN_RETRY_AFTER_SECONDS",
    "MAX_RETRY_AFTER_SECONDS",
    "DEFAULT_RETRY_AFTER_SECONDS",
    "ActiveCareDecisionAction",
    "clamp_retry_after_seconds",
    "build_send_action",
    "build_defer_action",
    "parse_terminal_tool_call",
    "decision_action_to_dict",
]
