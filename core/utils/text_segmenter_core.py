"""主断句函数 ``split_chat_message``：把模型回复切成多个气泡。

从 ``text_segmenter.py`` 拆出，是本模块最长的一段（原样搬移，未做函数级拆分）。
"""
from __future__ import annotations

import random
import re

from core.utils.text_segmenter_emoji import is_emoji_char
from core.utils.text_segmenter_force import (
    force_split_long_sentence,
    repair_broken_inline_spans,
)
from core.utils.text_segmenter_merge import (
    looks_like_manual_space_split,
    merge_chunks_to_limit,
    merge_continuation_chunks,
    merge_space_chunks_to_limit,
)
from core.utils.text_segmenter_numbered import normalize_numbered_list
from core.utils.text_segmenter_rules import (
    ELLIPSIS_MERGE_PREFIX_LIMIT,
    EXPLICIT_SPACE_BOUNDARY_ENDINGS,
    HARD_BUBBLE_BOUNDARY_ENDINGS,
)


# ==========================================================================
# 主断句函数
# ==========================================================================

def split_chat_message(
    text: str,
    max_len: int = 150,
    comma_split_prob: float = 0.2,
    min_split_len: int = 40,
    preprocess=None,
    pass_through_markers: tuple[str, ...] = (),
) -> list[str]:
    """聊天消息断句：把模型回复切成多个气泡，模拟真人碎句聊天节奏。

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
        preprocess: 断句前对文本做的预处理（如 QQ 需要剥离 markdown）
        pass_through_markers: 命中即整段返回的标记（如 QQ 的 `[CQ:`）

    Returns:
        断句后的文本列表
    """
    s = str(text or "")
    if not s:
        return []
    for marker in pass_through_markers:
        if marker and marker in s:
            return [s]

    if preprocess is not None:
        s = preprocess(s)
        s = str(s or "")
        if not s:
            return []

    # 统一把显式换行标记转成真正换行，兼容 `/n`、`\n` 和重复转义后的 `\\n`
    s = re.sub(r"(?:\\+|[／/])[nN]", "\n", s)

    if looks_like_manual_space_split(s):
        parts = [part.strip() for part in re.split(r"\s+", s) if part.strip()]
        return merge_space_chunks_to_limit(parts, max_chunks=6)

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
    s = re.sub(r"([\u201c\u2018\u300c\u300e])\s*\n", r"\1", s)
    s = re.sub(r"\n\s*([\u201d\u2019\u300d\u300f])", r"\1", s)

    if s.startswith("[") and "]" in s:
        first_close_idx = s.find("]")
        if first_close_idx == len(s) - 1:
            return [s]
        if len(s) - first_close_idx <= 10:
            return [s]

    # 行内编号列表（1. xxx 2. xxx 3. xxx）按编号切成独立气泡，
    # 避免在第一项中间断句、下一条又接上 2.
    s = normalize_numbered_list(s)

    max_len = max(20, int(max_len or 150))
    comma_split_prob = max(0.0, min(1.0, float(comma_split_prob)))
    min_split_len = max(10, int(min_split_len or 40))
    if "\n" in s:
        lines = s.split("\n")
        merged: list[str] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            merged.extend(
                split_chat_message(
                    line,
                    max_len,
                    comma_split_prob,
                    min_split_len,
                    preprocess=preprocess,
                    pass_through_markers=pass_through_markers,
                )
            )
        # 用户明确用换行分隔内容，不进行续接合并和块数限制，保留原始换行意图
        return merged

    result: list[str] = []
    current = ""
    i = 0
    stack: list[str] = []
    closing_to_opening = {
        "）": "（",
        ")": "(",
        "]": "[",
        "}": "{",
        "】": "【",
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
                prev_char = s[i - 1]
                next_char = s[i + 1]
                if prev_char.isalpha() and next_char.isalpha():
                    is_contraction = True

            if not is_contraction:
                if stack and stack[-1] == char:
                    stack.pop()
                else:
                    stack.append(char)
        # 方括号/花括号/方头括号也要配对跟踪：模型输出数学区间 [1, 3]、
        # 集合 {1, 2} 时是英文排版习惯（逗号后带空格），若不进栈，
        # 会被"逗号+空格=用户主动分泡"的显式边界规则误断成 [1 / 3]
        elif char in ["（", "(", "[", "{", "【", "\u201c", "\u2018"]:
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
            while look_ahead < len(s) and s[look_ahead].isspace() and s[look_ahead] != "\n":
                look_ahead += 1
            # 检查是否是省略号开头
            if look_ahead < len(s) and s[look_ahead] == "…":
                # 找到省略号结束位置
                while look_ahead < len(s) and s[look_ahead] == "…":
                    look_ahead += 1
                # 跳过省略号后的空白
                after_ellipsis = look_ahead
                while after_ellipsis < len(s) and s[after_ellipsis].isspace() and s[after_ellipsis] != "\n":
                    after_ellipsis += 1
                next_char = s[after_ellipsis] if after_ellipsis < len(s) else ""
                # 如果后面是普通句子（不是感叹词+标点模式），在括号处断句
                exclamation_words_check = ("哈", "啊", "哇", "哎", "唉", "唔", "嗯", "哼", "咦", "嘿", "噢")
                if (
                    next_char
                    and next_char not in HARD_BUBBLE_BOUNDARY_ENDINGS
                    and next_char not in exclamation_words_check
                    and next_char != "\n"
                ):
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
                while look_ahead < len(s) and s[look_ahead].isspace() and s[look_ahead] != "\n":
                    look_ahead += 1
                next_char = s[look_ahead] if look_ahead < len(s) else ""

                # 检测「感叹词+标点」模式
                exclamation_words_en = (
                    "哈", "啊", "哇", "哎", "唉", "唔", "嗯", "哼", "咦", "嘿", "噢",
                    "ha", "Ha", "HA", "ah", "Ah", "AH", "oh", "Oh", "OH",
                    "wow", "Wow", "WOW",
                )
                is_exclamation_pattern = False
                if next_char and next_char in exclamation_words_en:
                    after_word = look_ahead + 1
                    while after_word < len(s) and s[after_word] not in HARD_BUBBLE_BOUNDARY_ENDINGS:
                        if s[after_word].isspace() and s[after_word] != "\n":
                            after_word += 1
                            continue
                        break
                    if after_word < len(s) and s[after_word] in HARD_BUBBLE_BOUNDARY_ENDINGS:
                        is_exclamation_pattern = True

                should_split = (
                    not stack
                    and len(result) < 2
                    and not is_exclamation_pattern
                    and (
                        next_char == ""
                        or next_char == "\n"
                        or (look_ahead > i + dot_count and s[look_ahead - 1] == " ")
                        or (
                            next_char not in HARD_BUBBLE_BOUNDARY_ENDINGS
                            and next_char not in exclamation_words_en
                        )
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
            while look_ahead < len(s) and s[look_ahead].isspace() and s[look_ahead] != "\n":
                look_ahead += 1
            next_char = s[look_ahead] if look_ahead < len(s) else ""

            # 检测「感叹词+标点」模式（如"哈？！"、"啊！"、"哇？"）
            exclamation_words = ("哈", "啊", "哇", "哎", "唉", "唔", "嗯", "哼", "咦", "嘿", "噢")
            is_exclamation_pattern = False
            if next_char and next_char in exclamation_words:
                # 检查感叹词后面是否有结束标点
                after_word = look_ahead + 1
                while after_word < len(s) and s[after_word] not in HARD_BUBBLE_BOUNDARY_ENDINGS:
                    if s[after_word].isspace() and s[after_word] != "\n":
                        after_word += 1
                        continue
                    # 感叹词后面有其他文字，不是纯感叹词模式
                    break
                if after_word < len(s) and s[after_word] in HARD_BUBBLE_BOUNDARY_ENDINGS:
                    is_exclamation_pattern = True

            # 检测「短促前缀 + 省略号 + 普通句子」模式
            # 例如："就是……戳废了两个半成品" 中"就是"只是短促前缀，
            # 省略号后应和后续句子合并为同一气泡，而不是在省略号处断成"就是……"。
            # 仅当省略号前的实质内容很短（<= ELLIPSIS_MERGE_PREFIX_LIMIT）才合并，
            # 避免影响"倒是你，声音听起来有点飘……是困了"这类完整句拖音的断句。
            ellipsis_core = current.rstrip("…").strip()
            is_ellipsis_only = bool(ellipsis_core) and len(ellipsis_core) <= ELLIPSIS_MERGE_PREFIX_LIMIT
            is_normal_sentence_after = (
                next_char
                and next_char not in HARD_BUBBLE_BOUNDARY_ENDINGS
                and next_char not in exclamation_words
                and next_char != "\n"
            )
            # 省略号后的显式空格是用户主动分泡泡的意图，优先级高于短促前缀合并
            has_explicit_space_after = look_ahead > i + ellipsis_count and s[look_ahead - 1] == " "

            should_split = (
                not stack
                and len(result) < 2
                and not is_exclamation_pattern
                and not (is_ellipsis_only and is_normal_sentence_after and not has_explicit_space_after)
                and (
                    next_char == ""  # 省略号后面没有内容
                    or next_char == "\n"  # 省略号后面是换行
                    or has_explicit_space_after  # 省略号后面有显式空格
                    or (
                        next_char not in HARD_BUBBLE_BOUNDARY_ENDINGS
                        and next_char not in exclamation_words
                    )  # 普通文字开头
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
                if emo_look < len(s) and is_emoji_char(s[emo_look]):
                    # 把紧跟的 emoji（含可能的连续 emoji）吸收进 current
                    while emo_look < len(s) and is_emoji_char(s[emo_look]):
                        current += s[emo_look]
                        emo_look += 1
                    i = emo_look - 1
                    # emoji 后若紧跟空格或换行，则按显式空格边界规则在 emoji 后断句；
                    # 否则不断句，让后续内容继续累积到当前句
                    if emo_look < len(s) and s[emo_look] == "\n":
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
            exclamation_words_punct = ("哈", "啊", "哇", "哎", "唉", "唔", "嗯", "哼", "咦", "嘿", "噢")
            is_ellipsis_exclamation = False
            stripped_current = current.strip()
            if stripped_current.startswith("……") or stripped_current.startswith("..."):
                # 检查省略号后面是否是感叹词
                after_ellipsis = stripped_current.lstrip("……").lstrip("...")
                if after_ellipsis and after_ellipsis[0] in exclamation_words_punct:
                    is_ellipsis_exclamation = True
            if is_ellipsis_exclamation and char in ["?", "？", "!", "！"]:
                # 检查后面是否还有标点，如果有则不断句
                look_ahead_punct = i + 1
                while look_ahead_punct < len(s) and s[look_ahead_punct].isspace():
                    look_ahead_punct += 1
                if look_ahead_punct < len(s) and s[look_ahead_punct] in HARD_BUBBLE_BOUNDARY_ENDINGS:
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
                # 1. 极短句子（<10字）在句号处断句，如"啊。"
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
                    current.strip().endswith(ending) for ending in EXPLICIT_SPACE_BOUNDARY_ENDINGS
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
        result = merge_continuation_chunks(result, max_merge_len=max_len * 2, min_split_len=min_split_len)
        if len(result) > 6:
            result = merge_chunks_to_limit(result, max_chunks=6)
        return repair_broken_inline_spans(result)

    if len(s) > max_len * 2:
        forced_split_result = force_split_long_sentence(s, max_len=max_len, max_chunks=6)
        if len(forced_split_result) > 1:
            return repair_broken_inline_spans(forced_split_result)

    return [s]
