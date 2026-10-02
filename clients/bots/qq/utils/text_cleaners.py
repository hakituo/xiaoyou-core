"""QQ 消息文本清洗：markdown、思考标签、时间戳、动作描写、尾随标点。

其中「时间戳剥离」与「句尾尾随标点清理」是所有聊天端都需要的通用规则，
已下沉到 `core.utils.text_segmenter`，本模块直接复用（安卓端用同一份规则的
Kotlin 实现），只保留 QQ 特有的 markdown / think / 动作描写清洗。
"""

from __future__ import annotations

import re

from core.utils.text_segmenter import (
    AI_TIMESTAMP_PATTERN as _AI_TS_PATTERN,
)
from core.utils.text_segmenter import (
    TRAILING_PUNCT_CHARS as _TRAILING_PUNCT_CHARS,
)
from core.utils.text_segmenter import (
    strip_ai_timestamp,
)
from core.utils.text_segmenter import (
    strip_trailing_punctuation as _strip_trailing_periods_for_qq,
)
# 渠道标注「（来自QQ）」是系统给历史消息加的，模型自己复述出来要剥掉。
# 与时间戳剥离同属「所有端都需要的通用规则」，实现在 core，这里直接复用。
from core.utils.data.chat_channel import (
    strip_model_channel_marks,
)
# 残留的工具调用标记（DSML token 及漂移形态）同为所有端通用规则，实现在 core，
# 这里直接复用：模型偶尔把内部工具调用 token 当正文吐出来，输出侧统一兜底。
from core.llm.openai_compat.dsml_parser import (
    strip_tool_mark_residue,
)


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


# 部分模型把推理写成段落而不是标签，例如：
# > **Thinking Process:** ... 或 思考过程：...
# 这类内容对用户没有意义，发送前需要连同其后的分隔线一起去掉。
# 只在行首（允许 "> " 引用前缀和 ** 加粗）识别推理段，
# 避免把正文里出现的"思考过程"当作推理块整段删掉。
_THINKING_BLOCK_RE = re.compile(
    r"^[ \t]*(?:>[ \t]*)?(?:\*\*)?(?:Thinking Process|思考过程)[ \t]*[:：]?[ \t]*(?:\*\*)?"
    r".*?(?=\n[ \t]*\n|\Z)",
    re.DOTALL | re.IGNORECASE | re.MULTILINE,
)

# 推理块之后常残留一条 Markdown 分隔线（---）
_LEADING_SEPARATOR_RE = re.compile(r"^(?:[ \t]*-{3,}[ \t]*(?:\r?\n)?)+")


def _strip_think_for_qq(text: str) -> str:
    """去除 QQ 消息中的思考过程（<think>、[THINK_STORE:...] 与 Thinking Process 段落）。"""
    text = str(text or "")
    # 兼容 <think>、<think/> 以及 </think/> 这类自闭合写法
    text = re.sub(r'<think[^>]*>.*?</think\s*/?>', '', text, flags=re.DOTALL)
    text = re.sub(r'\[THINK_STORE:[^\]]*\]', '', text)
    text = _THINKING_BLOCK_RE.sub('', text).strip()
    text = _LEADING_SEPARATOR_RE.sub('', text)
    return text.strip()


def _strip_action_descriptions(text: str) -> str:
    """去除文本开头的动作描写（圆括号包裹的内容），保留句子中间的括号内容。"""
    text = str(text or "")
    text = re.sub(r'^[（(][^）)]{1,80}[）)]\s*', '', text)
    return text.strip()


# 兼容旧导入：core 的通用实现即 QQ 使用的实现（安卓端用同一套规则的 Kotlin 版）。
# _TRAILING_PUNCT_CHARS、_AI_TS_PATTERN、strip_ai_timestamp、
# _strip_trailing_periods_for_qq 均由上方 core 导入提供。
__all__ = [
    "_AI_TS_PATTERN",
    "_LEADING_SEPARATOR_RE",
    "_THINKING_BLOCK_RE",
    "_TRAILING_PUNCT_CHARS",
    "_strip_action_descriptions",
    "_strip_markdown_for_qq",
    "_strip_think_for_qq",
    "_strip_trailing_periods_for_qq",
    "strip_ai_timestamp",
    "strip_model_channel_marks",
    "strip_tool_mark_residue",
]
