"""
回复内容后处理清洗
从 streaming.py 解耦：泄漏 TOPIC 标签提取、think 块剥离、DSML 残留清理、
[TOOL_CALL] 块剥离、时间戳剥离、裸 base64 数据过滤
"""
import re
from typing import List

from core.utils.logger import get_logger

logger = get_logger("ChatAgent")

# AI 模仿上下文时间戳格式自行生成的时间戳（如 [23:10]、[05-22 01:45] 或 [2025-05-22 01:45]）
_TS_GLOBAL_PATTERN = re.compile(
    r"\[(?:\d{2,4}(?:-\d{2}){1,2}\s+)?\d{2}:\d{2}(?::\d{2})?(?:\s*\([^)]+\))?\]\s*"
)
_TOPIC_PATTERN = re.compile(r"\[TOPIC:\s*(.*?)\]", re.IGNORECASE | re.DOTALL)
_TOOL_CALL_PATTERN = re.compile(r"\[TOOL_CALL\](.*?)\[/TOOL_CALL\]", re.DOTALL)
_RAW_B64_PATTERN = re.compile(r'[A-Za-z0-9+/]{80,}={0,2}')


def extract_leaked_topics(content: str, extracted_topics: List[str]) -> str:
    """提取泄漏到正文中的 [TOPIC:] 标签并追加到 extracted_topics（就地修改）"""
    leaked_topic_matches = _TOPIC_PATTERN.findall(content)
    if leaked_topic_matches:
        for raw in leaked_topic_matches:
            topics = [t.strip() for t in re.split(r"[,，/、\s]+", str(raw)) if t.strip()]
            for topic in topics:
                if topic not in extracted_topics:
                    extracted_topics.append(topic)
        content = _TOPIC_PATTERN.sub("", content).strip()
    return content


def strip_think_blocks(content: str) -> str:
    """剥离残留的 <think>...</think> 块"""
    return re.sub(
        r"<think.*?</think\s*>", "", content, flags=re.DOTALL | re.IGNORECASE
    ).strip()


def clean_dsml_residue(content: str) -> str:
    """清理残留的 DSML 工具调用 token"""
    from core.llm.openai_compat.dsml_parser import has_dsml_tokens, parse_dsml_tool_calls
    if has_dsml_tokens(content):
        cleaned_content, _ = parse_dsml_tool_calls(content)
        logger.warning(
            "[STREAM] 后处理: 检测到残留DSML token，已清理 (原始长度=%d, 清理后=%d)",
            len(content),
            len(cleaned_content),
        )
        content = cleaned_content
    return content


def strip_tool_call_blocks(content: str) -> str:
    """剥离 MiniMax-M2.5 等模型输出的 [TOOL_CALL]...[/TOOL_CALL] 格式

    这是模型训练数据中自带的工具调用格式，项目未注册这些工具
    """
    if "[TOOL_CALL]" in content and "[/TOOL_CALL]" in content:
        _extracted = []
        for _m in _TOOL_CALL_PATTERN.finditer(content):
            _text_match = re.search(r'--text\s+["\u201c](.+?)["\u201d]', _m.group(1), re.DOTALL)
            if _text_match:
                _extracted.append(_text_match.group(1).strip())
        _cleaned = _TOOL_CALL_PATTERN.sub("", content).strip()
        if _extracted:
            content = " ".join(_extracted)
            logger.info(
                "StreamChat: 从[TOOL_CALL]中提取到文本，长度=%d",
                len(content),
            )
        elif _cleaned:
            content = _cleaned
    return content


def strip_inline_timestamps(content: str) -> str:
    """剥离AI模仿上下文时间戳格式自行生成的时间戳

    全局匹配，不仅匹配行首，也匹配回复中间出现的时间戳
    """
    _before_ts_strip = content
    content = _TS_GLOBAL_PATTERN.sub("", content).strip()
    if _before_ts_strip != content:
        logger.info(
            "StreamChat: 时间戳剥离: '%s' -> '%s'",
            _before_ts_strip[:80], content[:80],
        )
    return content


def strip_raw_base64(content: str) -> str:
    """过滤裸 base64 数据泄露（LLM 输出中不应包含 base64 编码数据）

    合法的 CQ 码图片和 data URI 会先被占位符保护，再剥离裸 base64
    """
    if not _RAW_B64_PATTERN.search(content):
        return content

    logger.warning(
        f"StreamChat: 检测到回复含裸 base64 数据，"
        f"尝试剥离 (长度={len(content)})"
    )
    cleaned = content
    placeholders_b64 = {}
    b64_counter = [0]

    def _b64_ph(m):
        k = f"__B64PH_{b64_counter[0]}__"
        b64_counter[0] += 1
        placeholders_b64[k] = m.group(0)
        return k

    cleaned = re.sub(
        r'\[CQ:[a-zA-Z]+,[^\]]*file=base64://[^\]]+\]',
        _b64_ph, cleaned
    )
    cleaned = re.sub(
        r'data:[a-zA-Z]+/[a-zA-Z+]+;base64,[A-Za-z0-9+/=]+',
        _b64_ph, cleaned
    )
    cleaned = re.sub(r'[A-Za-z0-9+/]{40,}={0,2}', '', cleaned)
    for k, v in placeholders_b64.items():
        cleaned = cleaned.replace(k, v)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    if cleaned:
        content = cleaned
        logger.info(
            f"StreamChat: base64 剥离成功 "
            f"(剩余长度={len(content)})"
        )
    else:
        logger.warning(
            "StreamChat: base64 剥离后内容为空，"
            "保留原始内容但移除 base64 段"
        )
        content = _RAW_B64_PATTERN.sub('[数据已过滤]', content)
    return content


def postprocess_response(content: str, extracted_topics: List[str]) -> str:
    """完整后处理链：按原 streaming.py 顺序依次执行各清洗步骤"""
    content = extract_leaked_topics(content, extracted_topics)
    content = strip_think_blocks(content)
    content = clean_dsml_residue(content)
    content = strip_tool_call_blocks(content)
    content = strip_inline_timestamps(content)
    content = strip_raw_base64(content)
    return content
