"""
主动关怀时段分工解析器

职责：
- 从 peer chat 剧本原文中提取 <proactive_assignment>JSON</proactive_assignment> 块
- 解析 JSON 得到时段分工结果：[{time_slot, lead, reason}, ...]
- 鲁棒处理：JSON 解析失败时返回空列表，由调用方走兜底（轮流制）

剧本输出格式约定（由 PeerScriptGenerator 的 prompt 要求 LLM 输出）：

<proactive_assignment>
{
  "assignments": [
    {"time_slot": "morning", "lead": "aveline", "reason": "Aveline 上午精神好"},
    {"time_slot": "afternoon", "lead": "ling", "reason": "Ling 下午有空"},
    {"time_slot": "evening", "lead": "aveline", "reason": "Aveline 晚上更适合陪主人"}
  ]
}
</proactive_assignment>
"""
import json
import re
from typing import Any, Dict, List

from core.utils.logger import get_module_logger

# peer_chat 独立日志文件，与 active_care 主流程分离
logger = get_module_logger("PEER_CHAT", "peer_chat.log")

# 匹配 <proactive_assignment>{...}</proactive_assignment> 块（允许跨行，非贪婪）
_ASSIGNMENT_PATTERN = re.compile(
    r"<proactive_assignment>\s*(\{.*?\})\s*</proactive_assignment>",
    re.DOTALL | re.IGNORECASE,
)

# 兜底：匹配裸 JSON 块（如果 LLM 没用标签）
_FALLBACK_JSON_PATTERN = re.compile(
    r'\{\s*"assignments"\s*:\s*\[.*?"time_slot".*?"lead".*?\]\s*\}',
    re.DOTALL,
)


def parse_proactive_assignment_from_script(raw_text: str) -> List[Dict[str, Any]]:
    """从剧本原文中提取时段分工结果

    Args:
        raw_text: LLM 生成的剧本原文（可能包含对话 + <proactive_assignment> 块）

    Returns:
        分配列表，每个元素形如：
        {"time_slot": "morning", "lead": "aveline", "reason": "..."}
        解析失败返回空列表。
    """
    if not raw_text:
        return []

    # 1. 优先匹配 <proactive_assignment>...</proactive_assignment> 块
    match = _ASSIGNMENT_PATTERN.search(raw_text)
    if match:
        json_str = match.group(1).strip()
        assignments = _safe_parse_assignments(json_str)
        if assignments:
            logger.info(
                "ProactiveParser: 从 <proactive_assignment> 块解析到 %d 条分工",
                len(assignments),
            )
            return assignments

    # 2. 兜底：匹配裸 JSON 块
    match = _FALLBACK_JSON_PATTERN.search(raw_text)
    if match:
        json_str = match.group(0).strip()
        assignments = _safe_parse_assignments(json_str)
        if assignments:
            logger.info(
                "ProactiveParser: 从兜底 JSON 块解析到 %d 条分工",
                len(assignments),
            )
            return assignments

    logger.warning(
        "ProactiveParser: 未找到分工 JSON 块，raw_text 前 200 字: %s",
        raw_text[:200],
    )
    return []


def _safe_parse_assignments(json_str: str) -> List[Dict[str, Any]]:
    """安全解析 JSON，返回 assignments 列表"""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        try:
            fixed = _fix_common_json_errors(json_str)
            data = json.loads(fixed)
        except Exception as e:
            logger.warning("ProactiveParser: JSON 解析失败: %s", e)
            return []

    if isinstance(data, list):
        return _normalize_assignments(data)
    if isinstance(data, dict):
        assignments = data.get("assignments")
        if isinstance(assignments, list):
            return _normalize_assignments(assignments)

    return []


# 合法的时段名
_VALID_SLOTS = {"morning", "afternoon", "evening"}
# persona 别名映射
_PERSONA_ALIASES = {
    "七濑 澪": "aveline",
    "七濑澪": "aveline",
    "澪": "aveline",
    "aveline": "aveline",
    "Ling": "ling",
    "ling": "ling",
    "wang_ling": "ling",
}


def _normalize_assignments(items: List[Any]) -> List[Dict[str, Any]]:
    """规范化分配列表，过滤无效项"""
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        slot = str(item.get("time_slot") or item.get("slot") or "").strip().lower()
        lead = str(
            item.get("lead") or item.get("assigned_to") or item.get("persona") or ""
        ).strip().lower()
        reason = str(item.get("reason") or "").strip()

        if slot not in _VALID_SLOTS:
            logger.warning("ProactiveParser: 未知 time_slot=%s，跳过", slot)
            continue

        # 规范化 persona 名（支持中文别名）
        lead_normalized = _PERSONA_ALIASES.get(lead)
        if not lead_normalized:
            # 尝试匹配中文名
            for alias, canonical in _PERSONA_ALIASES.items():
                if alias in lead:
                    lead_normalized = canonical
                    break
        if not lead_normalized:
            logger.warning("ProactiveParser: 未知 lead=%s，跳过", lead)
            continue

        result.append({
            "time_slot": slot,
            "lead": lead_normalized,
            "reason": reason,
        })
    return result


def _fix_common_json_errors(json_str: str) -> str:
    """修复常见 JSON 错误"""
    fixed = re.sub(r",\s*([}\]])", r"\1", json_str)
    if "'" in fixed and '"' not in fixed:
        fixed = fixed.replace("'", '"')
    return fixed


def build_slot_list_text() -> str:
    """构建时段列表 prompt 文本（供协商 prompt 使用）

    Returns:
        prompt 文本，形如：
        - morning（上午 06:00-12:00）
        - afternoon（下午 12:00-18:00）
        - evening（晚上 18:00-24:00）
    """
    lines = [
        "- morning（上午 06:00-12:00）",
        "- afternoon（下午 12:00-18:00）",
        "- evening（晚上 18:00-24:00）",
    ]
    return "\n".join(lines)
