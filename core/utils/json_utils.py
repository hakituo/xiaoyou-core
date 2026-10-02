import json
import re
from typing import Any, Dict, Optional, Union


def _loads_json_candidate(text: str) -> Optional[Union[Dict[str, Any], list]]:
    """尝试解析 JSON；如果拿到的是被再次序列化的 JSON 字符串，则继续解一层。"""
    raw = str(text or "").lstrip("\ufeff").strip()
    if not raw:
        return None

    current = raw
    for _ in range(2):
        try:
            parsed = json.loads(current)
        except json.JSONDecodeError:
            return None

        if isinstance(parsed, str):
            nested = parsed.lstrip("\ufeff").strip()
            if nested and nested != current and nested[:1] in {"{", "["}:
                current = nested
                continue

        if isinstance(parsed, (dict, list)):
            return parsed
        return None

    return None


_BRACE_PAIRS = {"{{": "}}", "[[": "]]"}

_REFUSAL_HINTS = (
    "i can't help",
    "i can’t help",
    "i cannot help",
    "i can't assist",
    "i cannot assist",
    "i can’t assist",
    "i won't",
    "i will not",
    "i'm unable to",
    "i am unable to",
    "i'm not able to",
    "as an ai language model",
    "i do not feel comfortable",
    "抱歉，我不能",
    "抱歉，我无法",
    "对不起，我不能",
    "对不起，我无法",
    "我无法帮助",
    "我不能帮",
    "无法为您提取",
)


def unwrap_redundant_brackets(text: str) -> str:
    """剥掉被整段双写的括号：{{"people": [{{...}}]}} -> {"people": [{...}]}。

    起因：prompt 模板为了兼容 str.format 会把示例 JSON 写成双大括号，模型照抄
    示例时原样输出双括号，json.loads 直接抛 "Expecting property name"。
    只在原串本身不是合法 JSON 时才动手，避免误伤 {"a": {"b": 1}} 这类正常结尾。
    """
    raw = str(text or "").strip()
    if len(raw) < 4:
        return raw
    closer = _BRACE_PAIRS.get(raw[:2])
    if not closer or not raw.endswith(closer):
        return raw
    try:
        json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass
    else:
        return raw
    unwrapped = re.sub(r"\}\}", "}", re.sub(r"\{\{", "{", raw)).strip()
    try:
        json.loads(unwrapped)
    except (json.JSONDecodeError, ValueError):
        return raw
    return unwrapped


def looks_like_refusal(text: str) -> bool:
    """判断 LLM 回复是不是安全拒答/道歉文案（而不是 JSON）。

    只在这段文本里连一个 { 或 [ 都没有时才判定为拒答，避免把正文里含
    "I can't" 的合法 JSON 误判。
    """
    raw = str(text or "").strip()
    if not raw:
        return False
    if "{" in raw or "[" in raw:
        return False
    lowered = raw.lower()
    return any(hint in lowered for hint in _REFUSAL_HINTS)


def _iter_balanced_json_candidates(text: str):
    """枚举文本中的平衡 JSON 片段，忽略字符串内部的括号。"""
    source = str(text or "")
    total = len(source)

    for start_idx, start_char in enumerate(source):
        if start_char not in "{[":
            continue

        stack = [start_char]
        in_string = False
        escape = False

        for index in range(start_idx + 1, total):
            char = source[index]

            if escape:
                escape = False
                continue

            if in_string:
                if char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue

            if char in "{[":
                stack.append(char)
                continue

            if char in "}]":
                if not stack:
                    break

                last = stack[-1]
                if (char == "}" and last != "{") or (char == "]" and last != "["):
                    break

                stack.pop()
                if not stack:
                    yield source[start_idx : index + 1]
                    break


def extract_json_block(text: str) -> str:
    """
    从 LLM 输出文本中提取 JSON 块字符串

    处理以下情况：
    - Markdown 围栏包裹 (```json ... ```)
    - 裸 JSON 对象
    - 推理模型输出中的思考标签干扰

    Args:
        text: LLM 原始输出文本

    Returns:
        提取出的 JSON 字符串，如果无法提取则返回原始文本
    """
    raw = str(text or "").strip()
    if not raw:
        return ""

    # 清除 Markdown 围栏
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines:
            first = lines[0].strip().lower()
            if first in {"```", "```json", "```jsonc"}:
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()

    # 尝试匹配 ```json ... ``` 围栏
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if json_match:
        return str(json_match.group(1) or "").strip()

    # 使用栈匹配提取完整的 JSON 对象
    start = raw.find("{")
    if start != -1:
        stack = []
        for i, char in enumerate(raw[start:], start=start):
            if char == '{':
                stack.append(char)
            elif char == '}':
                if stack:
                    stack.pop()
                    if not stack:
                        # 找到完整的 JSON 对象
                        return raw[start : i + 1]

    # 兜底：找最外层花括号
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end >= start:
        return raw[start : end + 1]

    return raw


def extract_json_object(text: str) -> Optional[Union[Dict[str, Any], list]]:
    """
    从文本中提取并解析 JSON 对象或数组

    使用栈匹配括号，正确处理嵌套结构。
    支持 Markdown 围栏包裹的 JSON。

    Args:
        text: 可能包含 JSON 的文本

    Returns:
        解析后的 dict/list，解析失败返回 None
    """
    text = str(text or "").lstrip("\ufeff").strip()
    if not text:
        return None

    # Fast path: if the whole text is valid JSON
    parsed = _loads_json_candidate(text)
    if parsed is not None:
        return parsed

    # 先尝试解析围栏或最外层提取块
    json_block = extract_json_block(text)
    if json_block and json_block != text:
        parsed = _loads_json_candidate(json_block)
        if parsed is not None:
            return parsed

    first_list: Optional[list] = None
    for json_str in _iter_balanced_json_candidates(text):
        parsed = _loads_json_candidate(json_str)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and first_list is None:
            first_list = parsed

    # Fallback: simple regex for code blocks
    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if code_block:
        parsed = _loads_json_candidate(code_block.group(1))
        if parsed is not None:
            return parsed

    return first_list
