"""主动关怀决策输出解析模块

从 decision.py 拆分而来，包含：
- Active Care / Peer Chat 的 JSON Schema 常量
- 输出格式构建函数
- JSON 提取、修复、解析、正则兜底等纯函数
"""

import json
import re
import ast
from typing import Any, Dict, Optional

from core.utils.logger import get_logger

logger = get_logger("ACTIVE_CARE_DECISION")

# 决策调试信息最大字符数
MAX_DECISION_DEBUG_THOUGHT_CHARS = 100000
# 原始输出预览最大字符数
MAX_DECISION_RAW_PREVIEW_CHARS = 400


# ============================================================
# JSON Schema 常量
# ============================================================

# JSON Schema 用于 Active Care 决策输出
ACTIVE_CARE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {
            "type": "string",
            "description": "你的内心独白，如果决定不发送请说明原因"
        },
        "should_send": {
            "type": "boolean",
            "description": "是否发送消息，默认true"
        },
        "intent": {
            "type": "string",
            "description": "当前动作意图"
        },
        "next_check_seconds": {
            "type": "integer",
            "minimum": 30,
            "description": "下次检查间隔秒数，如果现在不适合发消息请设置延迟时间"
        },
        "planned_topic": {
            "type": "string",
            "description": "计划的话题（可选）"
        },
        "planned_delay_seconds": {
            "type": "integer",
            "minimum": 0,
            "description": "计划延迟秒数"
        }
    },
    "required": ["thought", "should_send", "intent"]
}


# ============================================================
# Peer Chat（双角色互聊）决策专用 schema 与解析
# 与主动关怀决策分离：peer chat 需要 situation/opening_idea/topic 字段，
# 不需要 next_check_seconds/planned_delay_seconds。
# ============================================================

PEER_CHAT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {
            "type": "string",
            "description": "你的内心独白，为什么想聊/不想聊",
        },
        "should_send": {
            "type": "boolean",
            "description": "是否发起这次互聊，默认true",
        },
        "situation": {
            "type": "string",
            "description": "具体情境描述（为什么现在想找对方聊），不要泛泛的'日常'",
        },
        "opening_idea": {
            "type": "string",
            "description": "开场思路（不是完整台词，是想法）",
        },
        "topic": {
            "type": "string",
            "description": "话题关键词",
        },
    },
    "required": ["thought", "should_send"],
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
{{"thought": "刚看到她在摸鱼，正好想问问她手办的事", "should_send": true, "situation": "看到Ling在房间里看手机，想起上次她说想买限定手办", "opening_idea": "直接问手办到货了没", "topic": "限定手办"}}
示例输出（should_send=false）：
{{"thought": "太晚了，她应该睡了", "should_send": false, "situation": "", "opening_idea": "", "topic": ""}}
"""


def _build_output_format_schema(chosen_action: str) -> str:
    """构建 JSON Schema 格式说明"""
    schema_str = json.dumps(ACTIVE_CARE_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
    return f"""【输出格式 - 严格 JSON】
你必须只输出一个符合以下 Schema 的合法 JSON 对象。
严禁输出任何 <think/> 标签，严禁输出推理过程，严禁包含任何 Markdown 围栏 (如 ```json)！
必须以 {{ 开始，以 }} 结束。
不要输出任何思考过程，直接输出 JSON！

{schema_str}

其中 intent 必须为: "{chosen_action}"

【next_check_seconds 指导】
- 应该根据场景灵活设置，不要总是返回固定值（如1800或3600）
- 刚互动完/用户活跃：600~1200（10~20分钟）
- 正常间隔：1200~2400（20~40分钟）
- 用户忙碌/低打扰：2400~4800（40~80分钟）
- 深夜/睡眠模式：3600~7200（1~2小时）
- 必须在范围内随机取值，避免固定间隔

示例输出（should_send=true）：
{{"thought": "用户刚回复不久，可以自然跟进", "should_send": true, "intent": "{chosen_action}", "next_check_seconds": 900}}
示例输出（should_send=false）：
{{"thought": "用户可能正在忙，稍后再试", "should_send": false, "intent": "{chosen_action}", "next_check_seconds": 2700}}
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


def _normalize_decision_dict(
    obj: Dict[str, Any], chosen_action: str
) -> Dict[str, Any]:
    """标准化决策字典，确保字段类型和默认值正确"""
    thought = str(obj.get("thought") or "").strip()
    # intent 是上游策略层已经选定的动作，不允许文案模型擅自改写。
    # 否则会出现 MDP 选择健康提醒、模型却返回好奇提问的策略漂移。
    intent = chosen_action
    should_send_raw = obj.get("should_send", True)
    if isinstance(should_send_raw, str):
        should_send = should_send_raw.strip().lower() in {"true", "1", "yes"}
    else:
        should_send = bool(should_send_raw)
    next_check_raw = obj.get("next_check_seconds", 600)
    planned_delay_raw = obj.get("planned_delay_seconds", 0)
    try:
        next_check_seconds = max(30, int(float(next_check_raw)))
    except Exception:
        next_check_seconds = 600
    try:
        planned_delay_seconds = max(0, int(float(planned_delay_raw)))
    except Exception:
        planned_delay_seconds = 0
    planned_topic = str(obj.get("planned_topic") or "").strip()
    reply_text = str(obj.get("reply_text") or "").strip()
    return {
        "thought": thought,
        "should_send": should_send,
        "intent": intent,
        "next_check_seconds": next_check_seconds,
        "planned_topic": planned_topic,
        "planned_delay_seconds": planned_delay_seconds,
        "reply_text": reply_text,
        "specific_instruction": "",
    }


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

    fallback_obj: Dict[str, Any] = {
        "thought": (str(thought_match.group(1) if thought_match else "").strip()
                    or inferred_thought
                    or f"LLM output format error. Raw text: {text[:MAX_DECISION_RAW_PREVIEW_CHARS]}"),
        "should_send": bool(should_send),
        "intent": chosen_action,
        "next_check_seconds": int(next_match.group(1)) if next_match else 600,
        "planned_topic": str(
            planned_topic_match.group(1) if planned_topic_match else ""
        ).strip(),
        "planned_delay_seconds": 0,
        "reply_text": "",
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

def _parse_peer_chat_output(raw: str) -> Dict[str, Any]:
    """解析 peer chat 决策输出（专用 parser，一次提取全部字段）

    与主动关怀的 _parse_decision_output 分离：
    - 提取 peer chat 专用字段 situation / opening_idea / topic
    - 不需要 next_check_seconds / planned_delay_seconds
    - 正则兜底也能提取 situation / opening_idea（主动关怀兜底做不到）

    Returns:
        {thought, should_send, situation, opening_idea, topic}，解析失败给合理兜底
    """
    text = _extract_json_block(raw)

    # 优先尝试 JSON 解析（复用已有的修复逻辑）
    for candidate in (text, _repair_json_text(text)):
        parsed = _load_decision_dict(candidate)
        if isinstance(parsed, dict):
            thought = str(parsed.get("thought") or "").strip()
            should_send_raw = parsed.get("should_send", True)
            if isinstance(should_send_raw, str):
                should_send = should_send_raw.strip().lower() in {"true", "1", "yes"}
            else:
                should_send = bool(should_send_raw)
            return {
                "thought": thought,
                "should_send": should_send,
                "intent": "peer_chat",
                "situation": str(parsed.get("situation") or "").strip(),
                "opening_idea": str(parsed.get("opening_idea") or "").strip(),
                "topic": str(parsed.get("topic") or "").strip(),
            }

    # JSON 解析全部失败，正则兜底提取字段
    return _build_peer_chat_regex_fallback(text, raw)


def _build_peer_chat_regex_fallback(text: str, raw: str) -> Dict[str, Any]:
    """peer chat 决策的正则兜底解析（主动关怀兜底不提取 situation/opening_idea，这里补上）"""
    lower = str(text or "").lower()
    should_send = any(
        pattern in lower for pattern in (
            '"should_send": true', "'should_send': true",
            '"should_send":true', "'should_send':true",
        )
    )

    thought_match = re.search(
        r'["\']thought["\']\s*:\s*["\']([\s\S]*?)["\']\s*,\s*["\']should_send["\']',
        text,
    )
    situation_match = re.search(
        r'["\']situation["\']\s*:\s*["\']([\s\S]*?)["\']\s*(?:,|})', text,
    )
    opening_match = re.search(
        r'["\']opening_idea["\']\s*:\s*["\']([\s\S]*?)["\']\s*(?:,|})', text,
    )
    topic_match = re.search(
        r'["\']topic["\']\s*:\s*["\']([\s\S]*?)["\']\s*(?:,|})', text,
    )

    # 如果没明确解析到 should_send，用关键词推断
    raw_thought = str(raw or "").strip()
    if not thought_match and raw_thought:
        inferred = _infer_should_send_from_keywords(raw_thought, should_send)
        if inferred is not None:
            should_send = inferred

    fallback_obj = {
        "thought": (str(thought_match.group(1) if thought_match else "").strip()
                    or raw_thought[:MAX_DECISION_DEBUG_THOUGHT_CHARS]
                    or f"LLM output format error. Raw text: {text[:MAX_DECISION_RAW_PREVIEW_CHARS]}"),
        "should_send": bool(should_send),
        "intent": "peer_chat",
        "situation": str(situation_match.group(1) if situation_match else "").strip(),
        "opening_idea": str(opening_match.group(1) if opening_match else "").strip(),
        "topic": str(topic_match.group(1) if topic_match else "").strip(),
    }
    return fallback_obj
