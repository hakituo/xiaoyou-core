"""主动关怀决策输出解析模块

从 decision.py 拆分而来，包含：
- Active Care / Peer Chat 的 JSON Schema 常量
- 输出格式构建函数
- JSON 提取、修复、解析、正则兜底等纯函数
"""

import json
import re
import ast
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger

logger = get_logger("ACTIVE_CARE_DECISION")

# 决策调试信息最大字符数
MAX_DECISION_DEBUG_THOUGHT_CHARS = 100000
# 原始输出预览最大字符数
MAX_DECISION_RAW_PREVIEW_CHARS = 400


# ============================================================
# JSON Schema 常量
# ============================================================

# JSON Schema 用于 Active Care 决策输出（Prompt v2 单一真相源）
#
# 决策只回答"发送还是延后"，不产最终文本：
#   {action, intent, reason_code, retry_after_seconds}
# should_send 等旧字段已从 schema 移除；解析器仍容忍旧格式（向后兼容），
# 但统一按 action 归一化。intent 不允许模型改写成其他动作。
ACTIVE_CARE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["send_active_care", "defer_active_care"],
            "description": (
                "二选一出口：现在值得联系用 send_active_care，"
                "不值得用 defer_active_care。大多数轮次应为 defer_active_care"
            ),
        },
        "intent": {
            "type": "string",
            "description": "本候选意图（必须固定，不可改写成其他动作）",
        },
        "reason_code": {
            "type": "string",
            "description": "简短内部原因代码，只进日志，不进用户消息链路",
        },
        "retry_after_seconds": {
            "type": "integer",
            "description": (
                "defer_active_care 时的下次重判间隔（秒），必须 >= 60；"
                "send_active_care 时填 0"
            ),
        },
    },
    "required": ["action", "intent", "reason_code", "retry_after_seconds"]
}


# 自然语言里"模型在表达不发送"的典型说法。
# 这些只应该出现在 defer_reason 里，出现在 text 里就必须被降级为 defer。
_DEFER_LEAK_MARKERS = (
    "先不发了", "先不发", "不发了", "等他回复", "等他回", "稍后再看",
    "稍后再说", "这轮不适合", "这轮不发", "这轮不发", "这轮跳过",
    "我先不打扰", "不打扰", "这次不发送", "不适合发送", "暂不发送",
    "先不发消息", "等他先", "等会儿再说",
)


# ============================================================
# Peer Chat（双角色互聊）决策专用 schema 与解析
# 与主动关怀决策分离：peer chat 需要 situation/opening_idea/topic 字段，
# 不需要 next_check_seconds/planned_delay_seconds。
# ============================================================

PEER_CHAT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "should_send": {
            "type": "boolean",
            "description": "是否发起这次互聊，默认true",
        },
        "reason_code": {
            "type": "string",
            "description": "触发理由编码（调试用），如 recent_life_event / observable_activity / cooldown_over / no_reason",
        },
        "reason": {
            "type": "string",
            "description": "一句短的事实依据（为什么现在聊），不要长篇自我解释",
        },
        "trigger": {
            "type": "string",
            "description": "为什么现在想找对方聊（具体情境，不是泛泛的'日常'）",
        },
        "intent": {
            "type": "string",
            "description": "这一轮想完成的社交动作（吐槽/关心/分享/约吃饭等）",
        },
        "conversation_seed": {
            "type": "string",
            "description": "用哪个具体内容起头（一个具体细节/事件）",
        },
        "avoid": {
            "type": "array",
            "items": {"type": "string"},
            "description": "要避免的方向（可选），如 ['不要问泛泛的你在干嘛']",
        },
    },
    "required": ["should_send"],
}


# ============================================================
# 关键词推断常量
# ============================================================

_NO_SEND_KEYWORDS = [
    "不应该", "不应打扰", "不要打扰", "不应发送", "不发送",
    "保持安静", "用户可能已入睡", "用户在睡觉", "深夜",
    "睡眠模式", "静默时段", "低打扰", "等待", "skip",
]
_YES_SEND_KEYWORDS = [
    "应该发送", "可以发送", "发送消息", "主动联系",
    "用户还醒着", "用户未入睡", "可以打扰",
]


# ============================================================
# 输出格式构建
# ============================================================

def _build_peer_chat_output_format() -> str:
    """构建 peer chat 决策的 JSON 格式说明"""
    schema_str = json.dumps(PEER_CHAT_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
    return f"""【输出格式 - 严格 JSON】
你必须只输出一个符合以下 Schema 的合法 JSON 对象。
严禁输出任何 <think/> 标签，严禁输出推理过程，严禁包含任何 Markdown 围栏 (如 ```json)！
必须以 {{ 开始，以 }} 结束。

{schema_str}

示例输出（should_send=true）：
{{"should_send": true, "reason_code": "observable_activity", "reason": "看到她抱着手办盒回来", "trigger": "刚看到她拆新到的手办快递，想起她念叨了很久", "intent": "一起看看、顺便调侃她", "conversation_seed": "新到的手办盒子", "avoid": ["不要问泛泛的你在干嘛"]}}
示例输出（should_send=false）：
{{"should_send": false, "reason_code": "no_reason", "reason": "现在没有自然开口的理由", "trigger": "", "intent": "", "conversation_seed": "", "avoid": []}}
"""


def _build_output_format_schema(chosen_action: str) -> str:
    """构建 JSON Schema 格式说明（Prompt v2：action/intent/reason_code/retry_after_seconds）。"""
    schema_str = json.dumps(ACTIVE_CARE_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
    return f"""【输出格式 - 严格 JSON】
你必须只输出一个符合以下 Schema 的合法 JSON 对象。
严禁输出任何 <think/> 标签，严禁输出推理过程，严禁包含任何 Markdown 围栏 (如 ```json)！
必须以 {{ 开始，以 }} 结束。
不要输出任何思考过程，直接输出 JSON！

{schema_str}

其中 intent 必须为: "{chosen_action}"

【action 指导 - 二选一出口】
- action="send_active_care"：当前存在明确、具体、且有依据的联系价值。
  retry_after_seconds 填 0。最终文本不由本决策输出，发送前由生成层生成。
- action="defer_active_care"：当前不值得打扰用户。
  retry_after_seconds 填下次重判间隔（>= 60）。大多数检查轮次属于这种。
- 时间间隔本身不构成发送理由。
- reason_code 只进日志，绝不进入用户消息链路。
- 禁止输出 thought / text / reply_text / should_send / planned_delay_seconds 等多余字段。

【retry_after_seconds 指导】（defer 时使用）
- 刚互动完/用户活跃：600~1200
- 正常间隔：1200~2400
- 用户忙碌/低打扰：2400~4800
- 深夜/睡眠模式：3600~7200
- 必须在范围内随机取值，避免固定间隔

示例输出（send）：
{{"action": "send_active_care", "intent": "{chosen_action}", "reason_code": "recent_open_topic", "retry_after_seconds": 0}}
示例输出（defer）：
{{"action": "defer_active_care", "intent": "{chosen_action}", "reason_code": "no_grounded_value", "retry_after_seconds": 2700}}
"""


# ============================================================
# JSON 提取与修复
# ============================================================

def _extract_json_block(text: str) -> str:
    """从 LLM 输出中提取 JSON 块，统一委托给 json_utils.extract_json_block"""
    raw = str(text or "").strip()
    if not raw:
        return ""
    last_think_end = raw.rfind("</think")
    if last_think_end != -1:
        raw = raw[last_think_end + len("</think"):].strip()
    elif "<think" in raw:
        think_start = raw.find("<think")
        raw = raw[:think_start].strip()

    raw = re.sub(r"(?:>\s*\*\*)?(?:Thinking Process|思考过程)\s*:?(?:\*\*)?.*?(?=\{|\n\n|\Z)", "", raw, flags=re.DOTALL | re.IGNORECASE)

    from core.utils.json_utils import extract_json_block
    return extract_json_block(raw)


def _load_decision_dict(candidate: str) -> Optional[Dict[str, Any]]:
    """尝试将候选文本解析为字典，支持 JSON 和 Python literal 两种格式"""
    c = str(candidate or "").strip()
    if not c:
        return None
    try:
        obj = json.loads(c)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    try:
        obj2 = ast.literal_eval(c)
        if isinstance(obj2, dict):
            return obj2
    except Exception:
        pass
    return None


def _contains_defer_leak(text: str) -> bool:
    """text 中是否混入了"不发送决策过程"的表述（如'先不发了'）。

    这些词只允许出现在 defer_reason / thought 里，出现在要发的内容里
    说明模型把决策过程当成了消息，必须降级为 defer。
    """
    raw = str(text or "")
    return any(marker in raw for marker in _DEFER_LEAK_MARKERS)


def _resolve_action_from_dict(obj: Dict[str, Any], should_send: bool) -> str:
    """确定 action 字段：显式 action 优先，其次用 should_send 兜底兼容。"""
    action = str(obj.get("action") or "").strip()
    if action in ("send_active_care", "defer_active_care"):
        return action
    # 老字段兜底：should_send=false 一律视为 defer
    return "send_active_care" if should_send else "defer_active_care"


def _normalize_decision_dict(
    obj: Dict[str, Any], chosen_action: str
) -> Dict[str, Any]:
    """标准化决策字典（Prompt v2：action/intent/reason_code/retry_after_seconds）。

    解析规则：
    - intent 是上游动作选择器已选定的动作，不允许模型改写；
    - action 缺失时用旧字段 should_send 兜底兼容（send=true / defer=false）；
    - defer 的 retry 优先取 retry_after_seconds，兼容 retry_after_minutes /
      next_check_seconds 老字段；
    - 兼容旧模型仍在 text / reply_text 里塞"决策过程"的情况：一律丢弃文本，
      若文本含 defer 泄漏表述则把 send 降级为 defer（决策本就不产文本）。
    """
    intent = chosen_action
    action = _resolve_action_from_dict(obj, _parse_bool(obj.get("should_send", True)))

    # 兼容旧格式泄漏文本：Decision 不产 text，出现即视为越界
    leaked_text = str(obj.get("text") or obj.get("reply_text") or "").strip()
    if action == "send_active_care" and leaked_text and _contains_defer_leak(leaked_text):
        logger.warning(
            "Active Care: 决策输出混入决策过程表述（%r），强制降级为 defer。",
            leaked_text[:60],
        )
        action = "defer_active_care"

    reason_code = str(
        obj.get("reason_code")
        or obj.get("defer_reason")
        or obj.get("thought")
        or ""
    ).strip()

    retry_after_seconds = None
    retry_sec_raw = obj.get("retry_after_seconds")
    retry_min_raw = obj.get("retry_after_minutes")
    next_sec_raw = obj.get("next_check_seconds")
    if action == "defer_active_care":
        for candidate in (retry_sec_raw, next_sec_raw):
            try:
                if candidate not in (None, "", 0):
                    retry_after_seconds = max(60, int(float(candidate)))
                    break
            except (TypeError, ValueError):
                continue
        if retry_after_seconds is None:
            try:
                if retry_min_raw not in (None, "", 0):
                    retry_after_seconds = max(
                        60, int(float(retry_min_raw)) * 60
                    )
            except (TypeError, ValueError):
                retry_after_seconds = None
        if retry_after_seconds is None:
            retry_after_seconds = 1800

    if action == "send_active_care":
        retry_after_seconds = 0

    return {
        "action": action,
        "intent": intent,
        "reason_code": reason_code,
        "retry_after_seconds": int(retry_after_seconds or 0),
        "should_send": action == "send_active_care",
        "next_check_seconds": max(30, int(retry_after_seconds or 600)),
        "text": "",
        "defer_reason": reason_code,
        "specific_instruction": "",
    }


def _parse_bool(value: Any) -> bool:
    """宽松布尔解析（兼容字符串 'true'/'1'/'yes'）。"""
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _repair_json_text(text: str) -> str:
    """修复常见的 JSON 格式错误（缺失值、尾逗号、Python 布尔值等）"""
    repaired = str(text or "")
    repaired = re.sub(
        r'"(planned_delay_seconds|next_check_seconds)"\s*(?=[,}])',
        r'"\1": 0',
        repaired,
    )
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    repaired = re.sub(r'"\s*:\s*None', r'": null', repaired)
    repaired = re.sub(r'"\s*:\s*True', r'": true', repaired)
    repaired = re.sub(r'"\s*:\s*False', r'": false', repaired)
    return repaired


def _infer_should_send_from_keywords(text: str, current: bool) -> Optional[bool]:
    """基于关键词推断是否应该发送，返回 None 表示无法推断"""
    no_score = sum(1 for kw in _NO_SEND_KEYWORDS if kw in text)
    yes_score = sum(1 for kw in _YES_SEND_KEYWORDS if kw in text)
    if no_score > yes_score:
        return False
    if yes_score > no_score:
        return True
    return None


# ============================================================
# 主动关怀决策输出解析
# ============================================================

def _parse_decision_output(raw: str, chosen_action: str) -> Dict[str, Any]:
    """解析主动关怀决策 LLM 输出，返回标准化决策字典"""
    text = _extract_json_block(raw)

    for candidate_text in (text, _repair_json_text(text)):
        parsed = _load_decision_dict(candidate_text)
        if isinstance(parsed, dict):
            return _normalize_decision_dict(parsed, chosen_action)

    return _build_regex_fallback(text, raw, chosen_action)


def _build_regex_fallback(text: str, raw: str, chosen_action: str) -> Dict[str, Any]:
    """正则兜底解析：当 JSON 解析全部失败时，用正则从残缺文本中提取字段"""
    lower = str(text or "").lower()
    should_send = any(
        pattern in lower for pattern in (
            '"should_send": true', "'should_send': true",
            '"should_send":true', "'should_send':true",
        )
    )
    thought_match = re.search(
        r'["\']thought["\']\s*:\s*["\']([\s\S]*?)["\']\s*,\s*["\']should_send["\']', text,
    )
    next_match = re.search(r'["\']next_check_seconds["\']\s*:\s*([0-9]+)', text)
    planned_topic_match = re.search(
        r'["\']planned_topic["\']\s*:\s*["\']([\s\S]*?)["\']\s*(?:,|})', text,
    )

    raw_thought = str(raw or "").strip()
    inferred_thought = ""
    if not thought_match and raw_thought:
        should_send = _infer_should_send_from_keywords(raw_thought, should_send)
        if should_send is not None:
            inferred_thought = raw_thought[:MAX_DECISION_DEBUG_THOUGHT_CHARS]
        else:
            should_send = bool(should_send)

    action_match = re.search(r'["\']action["\']\s*:\s*["\']([^"\']+)["\']', text)
    action_name = str(action_match.group(1) if action_match else "").strip()
    if action_name in ("send_active_care", "defer_active_care"):
        should_send = action_name == "send_active_care"

    fallback_obj: Dict[str, Any] = {
        "thought": (str(thought_match.group(1) if thought_match else "").strip()
                    or inferred_thought
                    or f"LLM output format error. Raw text: {text[:MAX_DECISION_RAW_PREVIEW_CHARS]}"),
        "should_send": bool(should_send),
        "intent": chosen_action,
        "next_check_seconds": int(next_match.group(1)) if next_match else 1800,
        "planned_topic": str(
            planned_topic_match.group(1) if planned_topic_match else ""
        ).strip(),
    }

    if fallback_obj["should_send"] and fallback_obj["thought"].startswith("LLM output format error"):
        logger.warning(
            "Active Care: 格式解析失败但策略要求发送，保留上游已选动作 %s",
            chosen_action,
        )

    if not fallback_obj["should_send"] and fallback_obj["thought"] == "LLM output format error":
        fallback_obj["thought"] = f"LLM output format error. Raw text: {text[:MAX_DECISION_RAW_PREVIEW_CHARS]}"
    return _normalize_decision_dict(fallback_obj, chosen_action)


# ============================================================
# Peer Chat 决策输出解析
# ============================================================

def _normalize_avoid_list(value: Any) -> List[str]:
    """把 avoid 字段规范为字符串列表（兼容字符串/列表/JSON 字符串）"""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v or "").strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return _normalize_avoid_list(parsed)
        except Exception:
            pass
        return [value.strip()] if value.strip() else []
    return []


def _parse_peer_chat_output(raw: str) -> Dict[str, Any]:
    """解析 peer chat 决策输出（专用 parser，一次提取全部字段）

    决策输出已收敛为 trigger / intent / conversation_seed / avoid + reason_code；
    向后兼容：若模型仍输出旧的 situation / opening_idea / topic / thought，自动映射。

    Returns:
        {thought, should_send, intent(路由标记), reason_code, reason,
         situation, opening_idea, topic, social_action, avoid}
        其中 situation/opening_idea/topic 为向下游生成器传递的载体字段：
        trigger→situation、social_action→opening_idea、conversation_seed→topic
    """
    text = _extract_json_block(raw)

    # 优先尝试 JSON 解析（复用已有的修复逻辑）
    for candidate in (text, _repair_json_text(text)):
        parsed = _load_decision_dict(candidate)
        if isinstance(parsed, dict):
            should_send_raw = parsed.get("should_send", True)
            if isinstance(should_send_raw, str):
                should_send = should_send_raw.strip().lower() in {"true", "1", "yes"}
            else:
                should_send = bool(should_send_raw)
            social_action = str(
                parsed.get("intent") or parsed.get("opening_idea") or ""
            ).strip()
            return {
                "thought": str(parsed.get("thought") or "").strip(),
                "should_send": should_send,
                "intent": "peer_chat",
                "reason_code": str(parsed.get("reason_code") or "").strip(),
                "reason": str(parsed.get("reason") or "").strip(),
                "situation": str(
                    parsed.get("trigger") or parsed.get("situation") or ""
                ).strip(),
                "opening_idea": social_action,
                "topic": str(
                    parsed.get("conversation_seed") or parsed.get("topic") or ""
                ).strip(),
                "social_action": social_action,
                "avoid": _normalize_avoid_list(parsed.get("avoid")),
            }

    # JSON 解析全部失败，正则兜底提取字段
    return _build_peer_chat_regex_fallback(text, raw)


def _build_peer_chat_regex_fallback(text: str, raw: str) -> Dict[str, Any]:
    """peer chat 决策的正则兜底解析（主动关怀兜底不提取 trigger/seed，这里补上）"""
    lower = str(text or "").lower()
    should_send = any(
        pattern in lower for pattern in (
            '"should_send": true', "'should_send': true",
            '"should_send":true', "'should_send':true",
        )
    )

    def _match(key: str) -> str:
        m = re.search(
            rf'["\']{key}["\']\s*:\s*["\']([\s\S]*?)["\']\s*(?:,|}})',
            text,
        )
        return str(m.group(1) if m else "").strip()

    reason_code = _match("reason_code")
    reason = _match("reason")
    trigger = _match("trigger") or _match("situation")
    social_action = _match("intent") or _match("opening_idea")
    seed = _match("conversation_seed") or _match("topic")

    # 如果没明确解析到 should_send，用关键词推断
    raw_thought = str(raw or "").strip()
    if not trigger and not reason_code and raw_thought:
        inferred = _infer_should_send_from_keywords(raw_thought, should_send)
        if inferred is not None:
            should_send = inferred

    fallback_obj = {
        "thought": raw_thought[:MAX_DECISION_DEBUG_THOUGHT_CHARS]
        or f"LLM output format error. Raw text: {text[:MAX_DECISION_RAW_PREVIEW_CHARS]}",
        "should_send": bool(should_send),
        "intent": "peer_chat",
        "reason_code": reason_code,
        "reason": reason,
        "situation": trigger,
        "opening_idea": social_action,
        "topic": seed,
        "social_action": social_action,
        "avoid": [],
    }
    return fallback_obj
