"""裸 base64 防泄漏与含 CQ 码长文本分割。"""

from __future__ import annotations

import re

# 连续 base64 字符串（长度 >=40 才匹配，再按 threshold 过滤）
_BASE64_PATTERN = re.compile(r'[A-Za-z0-9+/]{40,}={0,2}')


def _contains_raw_base64(text: str, threshold: int = 80) -> bool:
    """检测文本中是否包含裸 base64 数据（非 CQ 码内的合法 base64）。

    判定逻辑：
    1. 先移除所有合法的 [CQ:xxx,file=base64://...] CQ 码
    2. 在剩余文本中搜索长度 >= threshold 的连续 base64 字符串
    3. 如果找到，说明有裸 base64 泄露
    """
    text = str(text or "")
    if not text:
        return False
    cleaned = re.sub(r'\[CQ:[a-zA-Z]+,[^\]]*file=base64://[^\]]+\]', '', text)
    cleaned = re.sub(
        r'data:[a-zA-Z]+/[a-zA-Z+]+;base64,[A-Za-z0-9+/=]+', '', cleaned
    )
    matches = _BASE64_PATTERN.findall(cleaned)
    for m in matches:
        if len(m) >= threshold:
            return True
    return False


def _strip_base64_from_text(text: str, threshold: int = 80) -> str:
    """从文本中剥离裸 base64 数据，保留合法 CQ 码与 Data URI。

    处理策略：
    1. 保留 [CQ:xxx,file=base64://...] 格式的合法 CQ 码
    2. 保留 data:mime;base64,... 格式的 Data URI
    3. 剥离其他所有长度 >= threshold 的连续 base64 字符串
    """
    text = str(text or "")
    if not text:
        return ""

    placeholders = {}
    counter = [0]

    def _placeholder(match):
        key = f"__B64PLACEHOLDER_{counter[0]}__"
        counter[0] += 1
        placeholders[key] = match.group(0)
        return key

    text = re.sub(
        r'\[CQ:[a-zA-Z]+,[^\]]*file=base64://[^\]]+\]', _placeholder, text
    )
    text = re.sub(
        r'data:[a-zA-Z]+/[a-zA-Z+]+;base64,[A-Za-z0-9+/=]+',
        _placeholder, text
    )

    text = re.sub(r'[A-Za-z0-9+/]{40,}={0,2}', '', text)

    for key, val in placeholders.items():
        text = text.replace(key, val)

    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text


def _is_base64_cq_code(text: str) -> bool:
    """判断文本是否是一个包含 base64 数据的 CQ 码（如语音/图片）。

    用于区分「合法的 base64 CQ 码」和「泄露的裸 base64 文本」。
    """
    text = str(text or "").strip()
    if not text.startswith("[CQ:"):
        return False
    if "base64://" not in text:
        return False
    if not text.endswith("]"):
        return False
    return bool(re.match(r'^\[CQ:[a-zA-Z]+,[^\]]*file=base64://[^\]]+\]$', text))


def _split_plain_text(text: str, max_len: int = 1200) -> list[str]:
    """将纯文本按长度分割，用于 NapCat 发送长消息。

    QQ 单条消息有长度限制，超过时需要分割。
    注意：不会拆碎 [CQ:...] 码，CQ 码始终作为整体保留。
    """
    text = str(text or "")
    if not text:
        return []
    max_len = max(100, int(max_len or 1200))
    if len(text) <= max_len:
        return [text]

    if "[CQ:" in text:
        return _split_text_with_cq_codes(text, max_len)

    result = []
    while text:
        if len(text) <= max_len:
            result.append(text)
            break
        split_pos = text.rfind('\n', 0, max_len)
        if split_pos <= 0:
            split_pos = text.rfind(' ', 0, max_len)
        if split_pos <= 0:
            split_pos = max_len
        result.append(text[:split_pos])
        text = text[split_pos:].lstrip('\n ')
    return result


def _split_text_with_cq_codes(text: str, max_len: int = 1200) -> list[str]:
    """将含 CQ 码的文本按长度分割，确保 CQ 码不被拆碎。

    策略：先提取所有 CQ 码替换为占位符，对纯文本部分做分割，再还原 CQ 码。
    如果单个 CQ 码超过 max_len，它仍作为独立片段保留（NapCat 能处理）。
    """
    cq_codes = []
    counter = [0]

    def _replace_cq(match):
        key = f"__CQPH_{counter[0]}__"
        counter[0] += 1
        cq_codes.append((key, match.group(0)))
        return key

    cleaned = re.sub(r'\[CQ:[a-zA-Z]+,[^\]]*\]', _replace_cq, text)

    if len(cleaned) <= max_len:
        for key, cq in cq_codes:
            cleaned = cleaned.replace(key, cq)
        return [cleaned]

    result = []
    while cleaned:
        if len(cleaned) <= max_len:
            result.append(cleaned)
            break
        split_pos = cleaned.rfind('\n', 0, max_len)
        if split_pos <= 0:
            split_pos = cleaned.rfind(' ', 0, max_len)
        if split_pos <= 0:
            split_pos = max_len
        result.append(cleaned[:split_pos])
        cleaned = cleaned[split_pos:].lstrip('\n ')

    final = []
    for chunk in result:
        for key, cq in cq_codes:
            chunk = chunk.replace(key, cq)
        if chunk.strip():
            final.append(chunk)

    return final if final else [text]
