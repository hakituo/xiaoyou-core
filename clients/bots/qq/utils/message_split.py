"""QQ 消息断句核心。

把模型回复按句号/问号/感叹号/逗号/省略号/换行等切成多个气泡，
模拟真人碎句聊天节奏。保留标点符号让消息读起来完整。

断句概率受 `comma_split_prob` 控制：逗号处是否断句是随机的，
测试通过 patch 本模块的 `random.random` 来固定随机结果。
"""

from __future__ import annotations

import random
import re

import jieba
import jieba.posseg as pseg

from clients.bots.qq import emoji_filter as _emoji_filter
from clients.bots.qq.utils.text_cleaners import _strip_markdown_for_qq

jieba.setLogLevel(jieba.logging.INFO)

# emoji 判定（用于把硬边界标点后紧跟的 emoji 粘到当前句尾）
_is_emoji_char = _emoji_filter._is_emoji_char


# ===== 断句常量 =====

_CONTINUATION_ADVERBS = frozenset({"再", "又", "还", "更"})

_CONTINUATION_ENDINGS = (
    "：", ":", "——", "—",
)

_HARD_BUBBLE_BOUNDARY_ENDINGS = (
    "。",
    ".",
    "！",
    "!",
    "？",
    "?",
    "…",
)

_EXPLICIT_SPACE_BOUNDARY_ENDINGS = _HARD_BUBBLE_BOUNDARY_ENDINGS + (
    "，",
    ",",
    "；",
    ";",
)

_PUNCTUATION_FOR_SPACE_GUARD = frozenset(
    "。.!！?？,，;；:：、…~～()（）[]【】{}<>《》\"'“”‘’"
)

# 省略号前若只是这么短（字符数）的"短促前缀"，不在省略号处断句，
# 而是与后续普通句子合并为同一气泡（例如"就是……戳废了"应合一，而非断成"就是……"）。
_ELLIPSIS_MERGE_PREFIX_LIMIT = 6


# ===== 续接词识别 =====

def _is_continuation_start(text: str) -> bool:
    """使用 jieba 词性标注判断文本是否以续接词开头。

    连词(c)视为续接词；首词以特定副词字根开头也视为续接（如"还有"/v、"再到"/v）。
    跳过前导标点。
    """
    if not text or not text.strip():
        return False

    stripped = text.strip()[:30]
    for word, flag in pseg.cut(stripped):
        if not word.strip():
            continue
        if flag in ("x", "w"):
            continue
        if flag == "c":
            return True
        if any(word.startswith(a) for a in _CONTINUATION_ADVERBS):
            return True
        return False

    return False


# ===== 分段合并 =====

def _merge_chunks_to_limit(chunks: list[str], max_chunks: int = 7) -> list[str]:
    """合并分段以确保不超过指定数量。

    策略：尽可能按原文的语义边界合并相邻分段，确保最终数量不超过 max_chunks。
    """
    if len(chunks) <= max_chunks:
        return chunks

    result = list(chunks)
    needed_merges = len(result) - max_chunks

    for _ in range(needed_merges):
        min_len = float('inf')
        merge_idx = -1
        for i in range(len(result) - 1):
            combined_len = len(result[i]) + len(result[i + 1])
            if combined_len < min_len:
                min_len = combined_len
                merge_idx = i
        if merge_idx < 0:
            break
        result[merge_idx] = result[merge_idx] + result[merge_idx + 1]
        result.pop(merge_idx + 1)

    return result


def _merge_continuation_chunks(chunks: list[str], max_merge_len: int = 300, min_split_len: int = 40) -> list[str]:
    """合并因续接词或未完标点而不自然断开的分段。

    规则：
    1. 如果下一个分段以续接词（jieba 词性标注识别）开头，且前一个分段较短（< min_split_len），
       说明断点不自然，合并到前一个分段
    2. 如果前一个分段以未完标点（如冒号、破折号）结尾，合并下一个分段
    3. 合并后的分段不超过 max_merge_len
    """
    if len(chunks) <= 1:
        return chunks

    result = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = result[-1]
        curr = chunks[i]
        curr_stripped = curr.strip()
        prev_stripped = prev.strip()

        should_merge = False

        if _is_continuation_start(curr_stripped):
            prev_ends_with_sent_punct = (
                prev_stripped
                and any(prev_stripped.endswith(ending) for ending in _EXPLICIT_SPACE_BOUNDARY_ENDINGS)
            )
            if not prev_ends_with_sent_punct and len(prev_stripped) < min_split_len:
                should_merge = True

        if prev_stripped and any(prev_stripped.endswith(e) for e in _CONTINUATION_ENDINGS):
            should_merge = True

        if should_merge and len(prev) + len(curr) <= max_merge_len:
            result[-1] = prev + curr
        else:
            result.append(curr)

    return result


def _looks_like_manual_space_split(text: str) -> bool:
    """判断一段无标点文本是否像"人工用空格分泡泡"的短语串。"""
    normalized = str(text or "").strip()
    if not normalized or "\n" in normalized:
        return False
    if any(ch in _PUNCTUATION_FOR_SPACE_GUARD for ch in normalized):
        return False

    parts = [part.strip() for part in re.split(r"\s+", normalized) if part.strip()]
    if len(parts) < 3:
        return False

    cjk_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
    if len(cjk_chars) < max(6, len(normalized.replace(" ", "")) // 3):
        return False

    if any(len(part) > 12 for part in parts):
        return False

    avg_len = sum(len(part) for part in parts) / max(1, len(parts))
    return avg_len <= 8


def _merge_space_chunks_to_limit(chunks: list[str], max_chunks: int = 6) -> list[str]:
    """按空格重新合并短语块，避免纯空格断句生成过多气泡。"""
    cleaned = [str(chunk or "").strip() for chunk in chunks if str(chunk or "").strip()]
    if len(cleaned) <= max_chunks:
        return cleaned

    result = list(cleaned)
    while len(result) > max_chunks:
        min_len = float("inf")
        merge_idx = -1
        for i in range(len(result) - 1):
            combined_len = len(result[i]) + len(result[i + 1])
            if combined_len < min_len:
                min_len = combined_len
                merge_idx = i
        if merge_idx < 0:
            break
        result[merge_idx] = f"{result[merge_idx]} {result[merge_idx + 1]}".strip()
        result.pop(merge_idx + 1)
    return result


# ===== 强制长句分割 =====

def _force_split_long_sentence(s: str, max_len: int = 100, max_chunks: int = 7) -> list[str]:
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
                chunk = s[position:i + 1].strip()
                if chunk:
                    result.append(chunk)
                    position = i + 1
                    split_char_found = True
                    break

        if not split_char_found:
            for i in range(target_end, min(target_end + 20, len(s))):
                char = s[i]
                if char in [",", "，", " ", "\u3000", ".", "。", ";", "；", "!", "！", "?", "？"]:
                    chunk = s[position:i + 1].strip()
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
                chunk = s[i:i + len(s) // max_chunks].strip()
                if chunk:
                    result.append(chunk)

    return result if result else [s]


# ===== 主断句函数 =====

def _split_message_for_qq(text: str, max_len: int = 150, comma_split_prob: float = 0.2, min_split_len: int = 40) -> list[str]:
    """QQ 消息流式断句函数。

    规则：
    1. 优先在句号、问号、感叹号处断句（仅当当前累积长度 >= min_split_len）
    2. 其次在逗号、分号处断句（仅当当前累积长度 >= max_len）
    3. 超过 max_len*2 强制在最近的逗号/空格处折断
    4. 保留标点符号，让消息读起来更完整
    5. 方括号包裹的内容（如 [THINK_STORE: ...]）保持完整，不在内部断句

    Args:
        text: 待断句的文本
        max_len: 单个消息气泡的最大长度（默认 150 字）
        comma_split_prob: 逗号断句概率（默认 0.2）
        min_split_len: 最小断句长度，短于此长度不在标点处断句（默认 40 字）

    Returns:
        断句后的文本列表
    """
    s = str(text or "")
    if not s or "[CQ:" in s:
        return [s] if s else []

    # 先剥离 markdown 标记，避免 **...** 被断句拆散后无法匹配
    s = _strip_markdown_for_qq(s)

    # 统一把显式换行标记转成真正换行，兼容 `/n`、`\n` 和重复转义后的 `\\n`
    s = re.sub(r"(?:\\+|[／/])[nN]", "\n", s)

    if _looks_like_manual_space_split(s):
        parts = [part.strip() for part in re.split(r"\s+", s) if part.strip()]
        return _merge_space_chunks_to_limit(parts, max_chunks=6)

    s = re.sub(r"。\.{3,}", "......", s)
    s = re.sub(r"。…+", "……", s)

    for _ in range(3):
        merged = re.sub(
            r"([（(][^）)\n]{1,120})\n([^）)\n]{0,120}[）)])",
            r"\1 \2",
            s,
        )
        if merged == s:
            break
        s = merged

    # 处理引号内的换行符，把换行去掉避免被断成多条消息
    # 包括西文引号（" ' " '）和中文直角引号（「 」『 』）
    s = re.sub(r'([\u201c\u2018\u300c\u300e])\s*\n', r'\1', s)
    s = re.sub(r'\n\s*([\u201d\u2019\u300d\u300f])', r'\1', s)

    if s.startswith('[') and ']' in s:
        first_close_idx = s.find(']')
        if first_close_idx == len(s) - 1:
            return [s]
        if len(s) - first_close_idx <= 10:
            return [s]

    max_len = max(20, int(max_len or 150))
    comma_split_prob = max(0.0, min(1.0, float(comma_split_prob)))
    min_split_len = max(10, int(min_split_len or 40))
    if '\n' in s:
        lines = s.split('\n')
        merged = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            merged.extend(_split_message_for_qq(line, max_len, comma_split_prob, min_split_len))
        # 用户明确用换行分隔内容，不进行续接合并和块数限制，保留原始换行意图
        return merged

    result = []
    current = ""
    i = 0
    stack: list[str] = []
    closing_to_opening = {
        "）": "（",
        ")": "(",
        "\u201d": "\u201c",
        "\u2019": "\u2018",
        '"': '"',
        "'": "'",
    }
    while i < len(s):
        char = s[i]
        prev_char = s[i - 1] if i > 0 else ""
        next_char = s[i + 1] if i + 1 < len(s) else ""
        look_ahead = i + 1
        saw_space_after_punct = False
        while look_ahead < len(s) and s[look_ahead].isspace():
            saw_space_after_punct = True
            look_ahead += 1
        next_visible_char = s[look_ahead] if look_ahead < len(s) else ""
        explicit_space_boundary = saw_space_after_punct and bool(next_visible_char)
        if char == '"':
            if stack and stack[-1] == char:
                stack.pop()
            else:
                stack.append(char)
        elif char == "'":
            is_contraction = False
            if i > 0 and i < len(s) - 1:
                prev_char = s[i-1]
                next_char = s[i+1]
                if prev_char.isalpha() and next_char.isalpha():
                    is_contraction = True

            if not is_contraction:
                if stack and stack[-1] == char:
                    stack.pop()
                else:
                    stack.append(char)
        elif char in ["（", "(", "\u201c", "\u2018"]:
            stack.append(char)
        elif char in closing_to_opening:
            opening = closing_to_opening[char]
            if stack and stack[-1] == opening:
                stack.pop()
        current += char
        # 特殊处理：括号结束后，如果后面是省略号+普通句子（非感叹词模式），
        # 应该在括号处断句，把省略号留给后续句子
        # 例如："（动作描写） ……后续句子" -> ["（动作描写）", "……后续句子"]
        if char in ["）", ")"] and not stack:
            look_ahead = i + 1
            # 跳过空白（非换行）
            while look_ahead < len(s) and s[look_ahead].isspace() and s[look_ahead] != '\n':
                look_ahead += 1
            # 检查是否是省略号开头
            if look_ahead < len(s) and s[look_ahead] == "…":
                # 找到省略号结束位置
                ellipsis_start = look_ahead
                while look_ahead < len(s) and s[look_ahead] == "…":
                    look_ahead += 1
                # 跳过省略号后的空白
                after_ellipsis = look_ahead
                while after_ellipsis < len(s) and s[after_ellipsis].isspace() and s[after_ellipsis] != '\n':
                    after_ellipsis += 1
                next_char = s[after_ellipsis] if after_ellipsis < len(s) else ""
                # 如果后面是普通句子（不是感叹词+标点模式），在括号处断句
                _EXCLAMATION_WORDS_CHECK = ("哈", "啊", "哇", "哎", "唉", "唔", "嗯", "哼", "咦", "嘿", "噢")
                is_exclamation_after = next_char and next_char in _EXCLAMATION_WORDS_CHECK
                if next_char and next_char not in _HARD_BUBBLE_BOUNDARY_ENDINGS and next_char not in _EXCLAMATION_WORDS_CHECK and next_char != '\n':
                    # 后面是普通句子，在括号处断句
                    if current.strip() and len(result) < 2:
                        result.append(current.strip())
                        current = ""
        if char == ".":
            dot_count = 1
            while i + dot_count < len(s) and s[i + dot_count] == ".":
                dot_count += 1
            current += "." * (dot_count - 1)  # 第一个点已加入，只加剩余的
            # 英文省略号（>=3个点）断句规则：
            # 与中文省略号保持一致，检测「感叹词+标点」模式
            if dot_count >= 3:
                look_ahead = i + dot_count
                while look_ahead < len(s) and s[look_ahead].isspace() and s[look_ahead] != '\n':
                    look_ahead += 1
                next_char = s[look_ahead] if look_ahead < len(s) else ""

                # 检测「感叹词+标点」模式
                _EXCLAMATION_WORDS_EN = ("哈", "啊", "哇", "哎", "唉", "唔", "嗯", "哼", "咦", "嘿", "噢", "ha", "Ha", "HA", "ah", "Ah", "AH", "oh", "Oh", "OH", "wow", "Wow", "WOW")
                is_exclamation_pattern = False
                if next_char and next_char in _EXCLAMATION_WORDS_EN:
                    after_word = look_ahead + 1
                    while after_word < len(s) and s[after_word] not in _HARD_BUBBLE_BOUNDARY_ENDINGS:
                        if s[after_word].isspace() and s[after_word] != '\n':
                            after_word += 1
                            continue
                        break
                    if after_word < len(s) and s[after_word] in _HARD_BUBBLE_BOUNDARY_ENDINGS:
                        is_exclamation_pattern = True

                should_split = (
                    not stack
                    and len(result) < 2
                    and not is_exclamation_pattern
                    and (
                        next_char == ""
                        or next_char == '\n'
                        or (look_ahead > i + dot_count and s[look_ahead - 1] == ' ')
                        or (next_char not in _HARD_BUBBLE_BOUNDARY_ENDINGS and next_char not in _EXCLAMATION_WORDS_EN)
                    )
                )
                if should_split:
                    if current.strip():
                        result.append(current.strip())
                    current = ""
            i += dot_count
            continue
        elif char == "…":
            ellipsis_count = 1
            while i + ellipsis_count < len(s) and s[i + ellipsis_count] == "…":
                ellipsis_count += 1
            current += "…" * (ellipsis_count - 1)  # 第一个省略号已加入，只加剩余的
            # 省略号断句规则：
            # 1. 省略号后面是空白/换行/结束：断句
            # 2. 省略号后面是感叹词+标点（如"……哈？！"）：不断句，保持情感完整性
            # 3. 省略号后面是普通文字（如"……是困了"）：断句
            # 4. 特殊情况：如果 current 只有省略号（刚断过句），后面是普通句子，不断句
            look_ahead = i + ellipsis_count
            # 跳过非换行的空白字符
            while look_ahead < len(s) and s[look_ahead].isspace() and s[look_ahead] != '\n':
                look_ahead += 1
            next_char = s[look_ahead] if look_ahead < len(s) else ""

            # 检测「感叹词+标点」模式（如"哈？！"、"啊！"、"哇？"）
            _EXCLAMATION_WORDS = ("哈", "啊", "哇", "哎", "唉", "唔", "嗯", "哼", "咦", "嘿", "噢")
            is_exclamation_pattern = False
            if next_char and next_char in _EXCLAMATION_WORDS:
                # 检查感叹词后面是否有结束标点
                after_word = look_ahead + 1
                while after_word < len(s) and s[after_word] not in _HARD_BUBBLE_BOUNDARY_ENDINGS:
                    if s[after_word].isspace() and s[after_word] != '\n':
                        after_word += 1
                        continue
                    # 感叹词后面有其他文字，不是纯感叹词模式
                    break
                if after_word < len(s) and s[after_word] in _HARD_BUBBLE_BOUNDARY_ENDINGS:
                    is_exclamation_pattern = True

            # 检测「短促前缀 + 省略号 + 普通句子」模式
            # 例如："就是……戳废了两个半成品" 中"就是"只是短促前缀，
            # 省略号后应和后续句子合并为同一气泡，而不是在省略号处断成"就是……"。
            # 仅当省略号前的实质内容很短（<= _ELLIPSIS_MERGE_PREFIX_LIMIT）才合并，
            # 避免影响"倒是你，声音听起来有点飘……是困了"这类完整句拖音的断句。
            _ellipsis_core = current.rstrip("…").strip()
            is_ellipsis_only = bool(_ellipsis_core) and len(_ellipsis_core) <= _ELLIPSIS_MERGE_PREFIX_LIMIT
            is_normal_sentence_after = next_char and next_char not in _HARD_BUBBLE_BOUNDARY_ENDINGS and next_char not in _EXCLAMATION_WORDS and next_char != '\n'

            should_split = (
                not stack
                and len(result) < 2
                and not is_exclamation_pattern
                and not (is_ellipsis_only and is_normal_sentence_after)  # 新增：省略号+普通句子模式不断句
                and (
                    next_char == ""  # 省略号后面没有内容
                    or next_char == '\n'  # 省略号后面是换行
                    or (look_ahead > i + ellipsis_count and s[look_ahead - 1] == ' ')  # 省略号后面有显式空格
                    or (next_char not in _HARD_BUBBLE_BOUNDARY_ENDINGS and next_char not in _EXCLAMATION_WORDS)  # 普通文字开头
                )
            )
            if should_split:
                if current.strip():
                    result.append(current.strip())
                current = ""
            i += ellipsis_count
            continue

        if (not stack) and char in ["。", "!", "！", "?", "？", ",", "，", ".", ";", "；"]:
            if char == "." and prev_char.isdigit() and next_char.isdigit():
                i += 1
                continue
            if char == ".":
                numbered_prefix = current.strip()
                look_ahead = i + 1
                while look_ahead < len(s) and s[look_ahead].isspace():
                    look_ahead += 1
                if re.fullmatch(r"\d{1,3}\.", numbered_prefix):
                    if look_ahead < len(s) and (
                        s[look_ahead].isalpha() or "\u4e00" <= s[look_ahead] <= "\u9fff"
                    ):
                        i += 1
                        continue
            if char in ["?", "？", "!", "！"]:
                repeat_count = 1
                while i + repeat_count < len(s) and s[i + repeat_count] == char:
                    repeat_count += 1
                if repeat_count > 1:
                    current += char * (repeat_count - 1)
                    i += repeat_count - 1
            # 硬边界标点（? ！ 。 等）后面紧跟 emoji 时，把 emoji 粘到当前句尾，
            # 避免 emoji 被断到下一句开头。仅当 emoji 与标点之间无空格/换行时生效。
            if char in ["?", "？", "!", "！", "。", "."]:
                emo_look = i + 1
                if emo_look < len(s) and _is_emoji_char(s[emo_look]):
                    # 把紧跟的 emoji（含可能的连续 emoji）吸收进 current
                    while emo_look < len(s) and _is_emoji_char(s[emo_look]):
                        current += s[emo_look]
                        emo_look += 1
                    i = emo_look - 1
                    # emoji 后若紧跟空格或换行，则按显式空格边界规则在 emoji 后断句；
                    # 否则不断句，让后续内容继续累积到当前句
                    if emo_look < len(s) and s[emo_look] == '\n':
                        if current.strip():
                            result.append(current.strip())
                        current = ""
                    elif emo_look < len(s) and s[emo_look].isspace():
                        # 显式空格边界：在 emoji 之后断句
                        if current.strip() and len(result) < 2:
                            result.append(current.strip())
                            current = ""
                    i += 1
                    continue
            if char in [",", "，", ";", "；"]:
                first_chunk_prefix = current[:-1].strip()
                if len(result) == 0 and first_chunk_prefix in {"等等", "等下", "等一下", "稍等", "先等等", "先等下"}:
                    i += 1
                    continue
            current_len = len(current.strip())

            # 检测「省略号+感叹词」模式，这种情况下跳过标点断句
            # 例如："……哈？！" 不应该在"？"处断句
            _EXCLAMATION_WORDS_PUNCT = ("哈", "啊", "哇", "哎", "唉", "唔", "嗯", "哼", "咦", "嘿", "噢")
            is_ellipsis_exclamation = False
            stripped_current = current.strip()
            if stripped_current.startswith("……") or stripped_current.startswith("..."):
                # 检查省略号后面是否是感叹词
                after_ellipsis = stripped_current.lstrip("……").lstrip("...")
                if after_ellipsis and after_ellipsis[0] in _EXCLAMATION_WORDS_PUNCT:
                    is_ellipsis_exclamation = True
            if is_ellipsis_exclamation and char in ["?", "？", "!", "！"]:
                # 检查后面是否还有标点，如果有则不断句
                look_ahead_punct = i + 1
                while look_ahead_punct < len(s) and s[look_ahead_punct].isspace():
                    look_ahead_punct += 1
                if look_ahead_punct < len(s) and s[look_ahead_punct] in _HARD_BUBBLE_BOUNDARY_ENDINGS:
                    # 后面还有标点，不断句
                    i += 1
                    continue
                # 后面没有标点了，检查长度是否足够断句
                # 感叹词模式即使很短也允许断句（因为是情感表达）
                if current_len < 10 and len(result) >= 2:
                    i += 1
                    continue

            if char in [",", "，", ";", "；"]:
                if not explicit_space_boundary:
                    if current_len < max_len:
                        i += 1
                        continue
                    if random.random() > comma_split_prob:
                        i += 1
                        continue
            else:
                # 句号断句规则：
                # 1. 极短句子（<20字）在句号处断句，如"啊。"
                # 2. 长句子（>=min_split_len）在句号处断句
                # 3. 中等长度句子不在句号处断句，保持完整
                very_short_threshold = 10
                is_very_short = current_len < very_short_threshold
                is_long_enough = current_len >= min_split_len

                if not explicit_space_boundary and not is_very_short and not is_long_enough:
                    i += 1
                    continue
                if len(result) >= 2:
                    i += 1
                    continue
            if current.strip():
                if explicit_space_boundary and any(
                    current.strip().endswith(ending) for ending in _EXPLICIT_SPACE_BOUNDARY_ENDINGS
                ):
                    result.append(current.strip())
                elif char in [",", "，", "。", ";", "；"]:
                    result.append(current[:-1].strip())
                else:
                    result.append(current.strip())
            current = ""
        i += 1

    if current.strip():
        result.append(current.strip())

    if len(result) > 1:
        result = _merge_continuation_chunks(result, max_merge_len=max_len * 2, min_split_len=min_split_len)
        if len(result) > 6:
            result = _merge_chunks_to_limit(result, max_chunks=6)
        return result

    if len(s) > max_len * 2:
        forced_split_result = _force_split_long_sentence(s, max_len=max_len, max_chunks=6)
        if len(forced_split_result) > 1:
            return forced_split_result

    return [s]
