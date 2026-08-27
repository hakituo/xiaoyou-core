"""QQ 消息文本清洗：markdown、思考标签、时间戳、动作描写、尾随标点。"""

from __future__ import annotations

import re

# 模型回复中模仿历史消息格式生成的时间戳（如 [05-22 01:45]），全局匹配
_AI_TS_PATTERN = re.compile(
    r"\[(?:\d{2,4}(?:-\d{2}){1,2}\s+)?\d{2}:\d{2}(?::\d{2})?(?:\s*\([^)]+\))?\]\s*"
)


def strip_ai_timestamp(text: str) -> str:
    """剥离模型回复中模仿历史消息格式生成的时间戳。

    全局匹配，不仅匹配行首，也匹配回复中间出现的时间戳。
    """
    text = str(text or "")
    text = _AI_TS_PATTERN.sub("", text)
    return text.strip()


def _strip_markdown_for_qq(text: str) -> str:
    """去除 QQ 消息中的 Markdown 格式标记。"""
    text = str(text or "")
    # 先处理三反引号代码块（可能跨行），再处理单反引号
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`([^`]+)`', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\*(.+?)\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'__(.+?)__', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'_(.+?)_', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'~~(.+?)~~', r'\1', text, flags=re.DOTALL)
    return text.strip()


def _strip_think_for_qq(text: str) -> str:
    """去除 QQ 消息中的思考过程标签（<think> 与 [THINK_STORE:...]）。"""
    text = str(text or "")
    text = re.sub(r'<think[^>]*>.*?</think\s*>', '', text, flags=re.DOTALL)
    text = re.sub(r'\[THINK_STORE:[^\]]*\]', '', text)
    return text.strip()


def _strip_action_descriptions(text: str) -> str:
    """去除文本开头的动作描写（圆括号包裹的内容），保留句子中间的括号内容。"""
    text = str(text or "")
    text = re.sub(r'^[（(][^）)]{1,80}[）)]\s*', '', text)
    return text.strip()


# 末尾尾随标点集合：句号、逗号、英文点/逗号、省略号、分号等。
# 仅当它们出现在句尾作为拖尾多余标点时清理，让气泡结尾更自然。
_TRAILING_PUNCT_CHARS = "。.，,．、；;…"


def _strip_trailing_periods_for_qq(text: str) -> str:
    """去除 QQ 消息末尾的尾随标点（句号、逗号等），让聊天消息更自然。

    - 去除括号前的句号（如"。（"→"（"）。
    - 去除括号内部末尾的句号（如"（xxx。）"→"（xxx）"）。
    - 去除句尾的尾随句号/逗号（如"好呀好呀。"→"好呀好呀"、"好呀好呀，"→"好呀好呀"）。
    - 仅清理末尾拖尾标点，句中逗号/句号等保留，不影响语义。
    """
    text = str(text or "")
    text = re.sub(r'[。.]\s*(?=[（(])', '', text)
    # 括号内部末尾的句号去除：（...。）→（...）
    text = re.sub(r'[。.]+\s*([）)])', r'\1', text)
    # 句尾尾随标点清理：保留最后一个非拖尾标点前的内容，
    # 例如"噢噢，好呀好呀，" -> "噢噢，好呀好呀"（结尾逗号去掉，句中逗号保留）
    text = text.rstrip(_TRAILING_PUNCT_CHARS).strip()
    # 兜底：去掉可能因 rstrip 后仍残留的句尾英文点
    text = re.sub(r'[。.]+$', '', text)
    return text.strip()
