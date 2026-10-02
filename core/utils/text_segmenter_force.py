"""强制长句分割与行内 Markdown span 修复。

从 ``text_segmenter.py`` 拆出：超长句按标点强制折断，以及把被断句切坏的
`**加粗**` / `` `代码` `` 拼回同一段。
"""
from __future__ import annotations


# ==========================================================================
# 强制长句分割
# ==========================================================================

def has_unclosed_inline_span(text: str) -> bool:
    """段内 `**加粗**` / `` `代码` `` 是否只闭合了一半。

    只统计未转义的 `**` 与反引号；`\\*`、`\\`` 跳过。数量为奇数即说明配对被切开。
    """
    count = 0
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if text.startswith("**", index):
            count += 1
            index += 2
            continue
        if char == "`":
            count += 1
            index += 1
            continue
        index += 1
    return count % 2 == 1


def repair_broken_inline_spans(chunks: list[str]) -> list[str]:
    """把被断句切坏的行内 Markdown span 拼回同一段。

    断句器按标点切分，而加粗里可以自带句号——例如
    `**古之人 / 不 / 余 / 欺。**` 会被切成「`**古之人 / 不 / 余 / 欺`」+
    「`** 顺便…`」两段，两段各自只有一个 `**`，渲染时星号落单、原样显示出来。
    这里检测未闭合的 span，把后一段并回前一段再判断，直到配平为止。

    并回时直接拼接不加分隔符：断点处的句号已被断句器吃掉，拼回去正好还原成
    `**古之人 / 不 / 余 / 欺**` 这种合法闭合（闭合 `**` 前面不能有空格）。
    """
    if len(chunks) < 2:
        return chunks
    result: list[str] = []
    buffer: str | None = None
    for chunk in chunks:
        candidate = chunk if buffer is None else buffer + chunk
        if has_unclosed_inline_span(candidate):
            buffer = candidate
        else:
            result.append(candidate)
            buffer = None
    if buffer is not None:
        result.append(buffer)
    return result


def force_split_long_sentence(s: str, max_len: int = 100, max_chunks: int = 7) -> list[str]:
    """强制分割长句子函数。

    当句子超过阈值时，每隔 max_len 字在最近的标点处断开，
    确保最终分段数量不超过 max_chunks。
    """
    if len(s) <= max_len:
        return [s]

    result = []
    target_chunk_size = max_len

    position = 0
    while position < len(s):
        remaining_length = len(s) - position

        if remaining_length <= max_len:
            if remaining_length > 0:
                result.append(s[position:].strip())
            break

        target_end = position + target_chunk_size
        if target_end >= len(s):
            target_end = len(s)

        split_char_found = False
        for i in range(target_end - 1, max(position + max_len // 2, position), -1):
            char = s[i]
            if char in [",", "，", " ", "\u3000", ".", "。", ";", "；", "!", "！", "?", "？"]:
                chunk = s[position : i + 1].strip()
                if chunk:
                    result.append(chunk)
                    position = i + 1
                    split_char_found = True
                    break

        if not split_char_found:
            for i in range(target_end, min(target_end + 20, len(s))):
                char = s[i]
                if char in [",", "，", " ", "\u3000", ".", "。", ";", "；", "!", "！", "?", "？"]:
                    chunk = s[position : i + 1].strip()
                    if chunk:
                        result.append(chunk)
                        position = i + 1
                        split_char_found = True
                        break

        if not split_char_found:
            chunk = s[position:target_end].strip()
            if chunk:
                result.append(chunk)
                position = target_end

    if len(result) > max_chunks:
        avg_chunk_size = len(s) // max_chunks
        new_result = []
        current_chunk = ""

        for chunk in result:
            if len(current_chunk) + len(chunk) <= avg_chunk_size + 20:
                current_chunk += chunk
            else:
                if current_chunk:
                    new_result.append(current_chunk.strip())
                current_chunk = chunk

        if current_chunk:
            new_result.append(current_chunk.strip())

        if len(new_result) <= max_chunks:
            result = new_result
        else:
            result = []
            for i in range(0, len(s), len(s) // max_chunks):
                chunk = s[i : i + len(s) // max_chunks].strip()
                if chunk:
                    result.append(chunk)

    return result if result else [s]
