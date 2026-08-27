"""
Prompt 清理和辅助工具
"""
import re
from typing import Optional


def finalize_and_clean_prompt(
    prompt: str,
    is_qq_source: bool = False,
    resolved_user_name: Optional[str] = None,
) -> str:
    """
    最终清理和优化 prompt

    Args:
        prompt: 原始 prompt
        is_qq_source: 是否是 QQ 来源
        resolved_user_name: 解析后的用户名

    Returns:
        清理后的 prompt
    """
    result = str(prompt or "").strip()

    if is_qq_source:
        forbidden_patterns = [
            (r"允许并鼓励在对话中加入细腻的动作描写.*?\n", ""),
            (r"[^\n\r]*动作与神态描写(?:必须|可用)用全角括\s*号[^\n\r]*\r?\n?", ""),
            (r"[^\n\r]*动作描写必须用全角括\s*号[^\n\r]*\r?\n?", ""),
            (r"环境氛围渲染与感官细节.*?\n", ""),
            (r"允许并鼓励详细的肢体接触、生理反应与官能描写.*?\n", ""),
            (r"[^\n\r]*动作与神态描写可用全角括\s*号[^\n\r]*\r?\n?", ""),
            (r"将作为特殊状态展示.*?\n", ""),
            (r"肢体接触、生理反应与官能描写", "语言层面的情感交互"),
        ]
        for pattern, repl in forbidden_patterns:
            result = re.sub(pattern, repl, result, flags=re.IGNORECASE)

    if resolved_user_name and resolved_user_name not in ["你", "Master", "Master", "主人"]:
        result = result.replace("Master", resolved_user_name)

    return result.strip()
