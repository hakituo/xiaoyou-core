"""MEMORY.md 偏好的 LLM 语义合并器

夜间定时任务调用，用 LLM（默认 siliconflow MiniMax-M2.5）对 MEMORY.md 的偏好区做语义合并。
平时 add_item 走 embedding + 关键词桶去重（实时、低成本），但中文同义改写容易漏判；
LLM 合并器在夜间兜底，把 embedding 漏掉的语义重复条目合并掉。

设计原则：
- 只合并 PREFERENCES 区（用户偏好是最高频堆积的区，且措辞变化多）
- LLM 只输出"合并方案"（哪几条合并成什么），不直接改文件
- 合并方案经本地校验后才落盘（防止 LLM 误删/越界改其他区）
- 失败/超时/返回格式错都不影响 nightly 主流程
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from core.agents.chat_agent_components.persona_system.prompt.self_improvement_prompts import (
    PREFERENCE_MERGE_SYSTEM_PROMPT,
    PREFERENCE_MERGE_USER_PROMPT_TEMPLATE,
)
from core.utils.logger import get_logger

logger = get_logger(__name__)


def _build_items_text(items: List[str]) -> str:
    """构造带编号的条目文本"""
    return "\n".join(f"{i+1}. {item}" for i, item in enumerate(items))


def _parse_llm_response(response: str, item_count: int) -> List[Dict[str, Any]]:
    """解析 LLM 返回的 JSON，校验 indices 合法性

    返回 merge_groups 列表，每个元素是 {"indices": set, "merged_text": str}
    非法格式返回空列表（让调用方跳过合并）
    """
    if not response or not isinstance(response, str):
        return []

    # 去掉可能的 markdown 代码块包裹
    text = response.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("LLM 合并响应不是合法 JSON，跳过合并")
        return []

    groups = data.get("merge_groups") if isinstance(data, dict) else None
    if not isinstance(groups, list):
        return []

    valid_groups: List[Dict[str, Any]] = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        indices_raw = g.get("indices")
        merged_text = g.get("merged_text")
        if not isinstance(indices_raw, list) or not isinstance(merged_text, str):
            continue
        # 转成 0-based 索引并校验范围
        indices = set()
        for idx in indices_raw:
            try:
                i = int(idx) - 1  # LLM 输出是 1-based
                if 0 <= i < item_count:
                    indices.add(i)
            except (ValueError, TypeError):
                continue
        # 只保留有效合并组：至少 2 条，且合并文本非空
        if len(indices) >= 2 and merged_text.strip():
            valid_groups.append({"indices": indices, "merged_text": merged_text.strip()})

    return valid_groups


def _resolve_groups(valid_groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """处理组间冲突：同一条目被分到多个组时，只保留第一个组

    返回无冲突的组列表（每个索引最多出现在一个组里）
    """
    used: set = set()
    resolved: List[Dict[str, Any]] = []
    for g in valid_groups:
        if g["indices"] & used:
            # 跟已选组冲突，跳过（保守策略，不强行拆组）
            continue
        resolved.append(g)
        used |= g["indices"]
    return resolved


def _apply_merge(
    items: List[str], resolved_groups: List[Dict[str, Any]]
) -> Tuple[List[str], int]:
    """应用合并方案，返回 (新条目列表, 移除数量)

    合并后的条目放在原组中第一个条目的位置，保持原顺序。
    """
    if not resolved_groups:
        return items, 0

    # 标记每个索引要被哪个组合并、合并后放在哪个位置
    merge_into: Dict[int, Tuple[int, str]] = {}  # idx -> (keep_position, merged_text)
    consumed: set = set()
    for g in resolved_groups:
        sorted_indices = sorted(g["indices"])
        keep_pos = sorted_indices[0]
        for idx in sorted_indices:
            merge_into[idx] = (keep_pos, g["merged_text"])
            consumed.add(idx)

    new_items: List[str] = []
    for i, item in enumerate(items):
        if i in consumed:
            if i == merge_into[i][0]:
                # 这是组的保留位置，放合并后的文本
                new_items.append(merge_into[i][1])
            # 其他索引跳过（已被合并掉）
        else:
            new_items.append(item)

    removed = len(items) - len(new_items)
    return new_items, removed


async def _call_llm(
    system_prompt: str,
    user_prompt: str,
    model_hint: str,
    timeout: float = 30.0,
) -> Optional[str]:
    """调用 LLM，返回响应文本（失败返回 None）"""
    try:
        from core.llm import get_llm_module

        llm = get_llm_module()
        if not llm:
            logger.warning("LLM 模块不可用，跳过 LLM 合并")
            return None

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = await llm.chat(
            messages,
            max_tokens=800,
            temperature=0.2,  # 低温度保证格式稳定
            model_hint=model_hint,
        )

        if isinstance(response, dict):
            if response.get("status") == "success":
                return str(response.get("response") or "")
            return None
        if isinstance(response, str):
            return response
        return None
    except Exception as exc:
        logger.warning(f"LLM 调用失败: {exc}")
        return None


async def llm_merge_preferences(
    items: List[str],
    model_hint: Optional[str] = None,
) -> Tuple[List[str], int, Dict[str, Any]]:
    """对偏好条目列表做 LLM 语义合并

    Args:
        items: 偏好条目列表
        model_hint: LLM 模型提示（默认用 journal_model_hint，即 siliconflow MiniMax-M2.5）

    Returns:
        (合并后列表, 移除数量, 诊断信息)
        诊断信息包含 LLM 原始响应、解析出的组数、实际应用的组数等
    """
    if len(items) <= 1:
        return items, 0, {"skipped": "too_few_items"}

    # 模型路由以 model_routing.yaml 为真源，与 journal 共用稳定前缀缓存。
    if not model_hint:
        try:
            from config.model_config import get_journal_model

            model_hint = get_journal_model()
        except Exception:
            model_hint = ""
    if not model_hint:
        try:
            from config.integrated_config import get_settings

            settings = get_settings()
            model_hint = str(getattr(settings.model, "journal_model_hint", "")) or ""
        except Exception:
            model_hint = ""
    if not model_hint:
        model_hint = "cloud:siliconflow:Pro/MiniMaxAI/MiniMax-M2.5"

    items_text = _build_items_text(items)
    user_prompt = PREFERENCE_MERGE_USER_PROMPT_TEMPLATE.format(items_text=items_text)

    response = await _call_llm(
        PREFERENCE_MERGE_SYSTEM_PROMPT,
        user_prompt,
        model_hint,
    )
    if not response:
        return items, 0, {"skipped": "llm_no_response", "model_hint": model_hint}

    valid_groups = _parse_llm_response(response, len(items))
    if not valid_groups:
        return items, 0, {
            "skipped": "no_valid_groups",
            "raw_response": response[:200],
            "model_hint": model_hint,
        }

    resolved_groups = _resolve_groups(valid_groups)
    new_items, removed = _apply_merge(items, resolved_groups)

    return new_items, removed, {
        "raw_response": response[:200],
        "valid_groups_count": len(valid_groups),
        "applied_groups_count": len(resolved_groups),
        "removed": removed,
        "model_hint": model_hint,
    }
