"""
提醒分工解析器

职责：
- 从 peer chat 剧本原文中提取 <assignment>JSON</assignment> 块
- 解析 JSON 得到分工结果：[{reminder_id, assigned_to, reason}, ...]
- 鲁棒处理：JSON 解析失败时返回空列表，由调用方走兜底（先到先得）

剧本输出格式约定（由 PeerScriptGenerator 的 prompt 要求 LLM 输出）：

<assignment>
{
  "assignments": [
    {"reminder_id": "study:review_due", "assigned_to": "aveline", "reason": "Aveline 学科背景更适合"},
    {"reminder_id": "task:xxx", "assigned_to": "ling", "reason": "Ling 跟进过这个任务"}
  ]
}
</assignment>
"""
import json
import re
from typing import Any, Dict, List

from core.utils.logger import get_module_logger

# peer_chat 独立日志文件，与 active_care 主流程分离
logger = get_module_logger("PEER_CHAT", "peer_chat.log")

# 匹配 <assignment>{...}</assignment> 块（允许跨行，非贪婪）
_ASSIGNMENT_PATTERN = re.compile(
    r"<assignment>\s*(\{.*?\})\s*</assignment>",
    re.DOTALL | re.IGNORECASE,
)

# 兜底：匹配 JSON 块（如果 LLM 没用标签）
_FALLBACK_JSON_PATTERN = re.compile(
    r'\{\s*"assignments"\s*:\s*\[.*?\]\s*\}',
    re.DOTALL,
)


def parse_assignments_from_script(raw_text: str) -> List[Dict[str, Any]]:
    """从剧本原文中提取分工结果

    Args:
        raw_text: LLM 生成的剧本原文（可能包含对话 + <assignment> 块）

    Returns:
        分配列表，每个元素形如：
        {"reminder_id": "study:review_due", "assigned_to": "aveline", "reason": "..."}
        解析失败返回空列表。
    """
    if not raw_text:
        return []

    # 1. 优先匹配 <assignment>...</assignment> 块
    match = _ASSIGNMENT_PATTERN.search(raw_text)
    if match:
        json_str = match.group(1).strip()
        assignments = _safe_parse_assignments(json_str)
        if assignments:
            logger.info(
                "NegotiationParser: 从 <assignment> 块解析到 %d 条分工",
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
                "NegotiationParser: 从兜底 JSON 块解析到 %d 条分工",
                len(assignments),
            )
            return assignments

    logger.warning(
        "NegotiationParser: 未找到分工 JSON 块，raw_text 前 200 字: %s",
        raw_text[:200],
    )
    return []


def _safe_parse_assignments(json_str: str) -> List[Dict[str, Any]]:
    """安全解析 JSON，返回 assignments 列表

    Args:
        json_str: JSON 字符串，形如 {"assignments": [...]} 或直接 [...]

    Returns:
        分配列表，解析失败返回空列表
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        # 尝试修复常见 JSON 错误（尾随逗号、单引号等）
        try:
            fixed = _fix_common_json_errors(json_str)
            data = json.loads(fixed)
        except Exception as e:
            logger.warning("NegotiationParser: JSON 解析失败: %s", e)
            return []

    if isinstance(data, list):
        # 直接是列表
        return _normalize_assignments(data)
    if isinstance(data, dict):
        assignments = data.get("assignments")
        if isinstance(assignments, list):
            return _normalize_assignments(assignments)

    return []


def _normalize_assignments(items: List[Any]) -> List[Dict[str, Any]]:
    """规范化分配列表，过滤无效项"""
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        reminder_id = str(item.get("reminder_id") or "").strip()
        assigned_to = str(item.get("assigned_to") or "").strip().lower()
        reason = str(item.get("reason") or "").strip()
        if not reminder_id or not assigned_to:
            continue
        # 规范化 persona 名
        if assigned_to in ("七濑 澪", "七濑澪", "澪", "aveline"):
            assigned_to = "aveline"
        elif assigned_to in ("Ling", "ling", "wang_ling"):
            assigned_to = "ling"
        else:
            # 未知 persona，跳过
            logger.warning(
                "NegotiationParser: 未知 assigned_to=%s，跳过",
                assigned_to,
            )
            continue
        result.append({
            "reminder_id": reminder_id,
            "assigned_to": assigned_to,
            "reason": reason,
        })
    return result


def _fix_common_json_errors(json_str: str) -> str:
    """修复常见 JSON 错误"""
    # 去除尾随逗号
    fixed = re.sub(r",\s*([}\]])", r"\1", json_str)
    # 单引号转双引号（简单情况，不处理值内的引号）
    if "'" in fixed and '"' not in fixed:
        fixed = fixed.replace("'", '"')
    return fixed


def build_reminder_list_text(reminders: List[Dict[str, Any]]) -> str:
    """把待发提醒列表转成 prompt 文本

    Args:
        reminders: 待发提醒列表，每项形如 {"reminder_id": "xxx", "title": "..."}

    Returns:
        prompt 文本，形如：
        1. [study:review_due] 学习复习提醒：3个知识点到期
        2. [task:xxx] 跟进任务：xxx
    """
    if not reminders:
        return "（今日暂无待发提醒）"
    lines = []
    for i, r in enumerate(reminders, 1):
        rid = str(r.get("reminder_id") or "").strip()
        title = str(r.get("title") or "").strip()
        lines.append(f"{i}. [{rid}] {title}")
    return "\n".join(lines)
