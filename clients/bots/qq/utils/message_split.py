"""QQ 消息断句（兼容层）。

通用断句逻辑已下沉到 `core.utils.text_segmenter`，QQ 与安卓端共用同一套规则
（详见该模块文档）。本模块只保留 QQ 特有的两处输入：

- 断句前剥离 markdown（`_strip_markdown_for_qq`）：QQ 是纯文本通道，
  `**加粗**` 这类标记对用户没有意义，且会让断句把成对的标记拆散。
- 命中 `[CQ:` 码时整段直返：CQ 码被拆碎后无法解析。

对外暴露的私有名与 `random` 符号全部保留，避免改动外部/测试代码。
"""

from __future__ import annotations

from clients.bots.qq.utils.text_cleaners import _strip_markdown_for_qq
from core.utils.text_segmenter import (
    CONTINUATION_ADVERBS as _CONTINUATION_ADVERBS,
)
from core.utils.text_segmenter import (
    CONTINUATION_ENDINGS as _CONTINUATION_ENDINGS,
)
from core.utils.text_segmenter import (
    ELLIPSIS_MERGE_PREFIX_LIMIT as _ELLIPSIS_MERGE_PREFIX_LIMIT,
)
from core.utils.text_segmenter import (
    EXPLICIT_SPACE_BOUNDARY_ENDINGS as _EXPLICIT_SPACE_BOUNDARY_ENDINGS,
)
from core.utils.text_segmenter import (
    HARD_BUBBLE_BOUNDARY_ENDINGS as _HARD_BUBBLE_BOUNDARY_ENDINGS,
)
from core.utils.text_segmenter import (
    PUNCTUATION_FOR_SPACE_GUARD as _PUNCTUATION_FOR_SPACE_GUARD,
)
from core.utils.text_segmenter import (
    find_numbered_list_starts as _find_numbered_list_starts,
)
from core.utils.text_segmenter import (
    force_split_long_sentence as _force_split_long_sentence,
)
from core.utils.text_segmenter import (
    is_continuation_start as _is_continuation_start,
)
from core.utils.text_segmenter import (
    is_numbered_item_start as _is_numbered_item_start,
)
from core.utils.text_segmenter import (
    looks_like_manual_space_split as _looks_like_manual_space_split,
)
from core.utils.text_segmenter import (
    merge_chunks_to_limit as _merge_chunks_to_limit,
)
from core.utils.text_segmenter import (
    merge_continuation_chunks as _merge_continuation_chunks,
)
from core.utils.text_segmenter import (
    merge_space_chunks_to_limit as _merge_space_chunks_to_limit,
)
from core.utils.text_segmenter import (
    normalize_numbered_list as _normalize_numbered_list_for_qq,
)
from core.utils.text_segmenter import (
    split_chat_message,
)

# 兼容旧测试：patch("clients.bots.qq.utils.random.random") 与
# patch("clients.bots.qq.utils.message_split.random.random") 仍能定位到断句用的 random
from core.utils.text_segmenter import random  # noqa: F401

__all__ = [
    "_CONTINUATION_ADVERBS",
    "_CONTINUATION_ENDINGS",
    "_ELLIPSIS_MERGE_PREFIX_LIMIT",
    "_EXPLICIT_SPACE_BOUNDARY_ENDINGS",
    "_HARD_BUBBLE_BOUNDARY_ENDINGS",
    "_PUNCTUATION_FOR_SPACE_GUARD",
    "_find_numbered_list_starts",
    "_force_split_long_sentence",
    "_is_continuation_start",
    "_is_numbered_item_start",
    "_looks_like_manual_space_split",
    "_merge_chunks_to_limit",
    "_merge_continuation_chunks",
    "_merge_space_chunks_to_limit",
    "_normalize_numbered_list_for_qq",
    "_split_message_for_qq",
    "random",
]


def _split_message_for_qq(
    text,
    max_len: int = 150,
    comma_split_prob: float = 0.2,
    min_split_len: int = 40,
) -> list[str]:
    """QQ 消息流式断句：转发到 core 公共实现，带上 QQ 的 markdown 预处理与 CQ 码直通。"""
    return split_chat_message(
        text,
        max_len=max_len,
        comma_split_prob=comma_split_prob,
        min_split_len=min_split_len,
        preprocess=_strip_markdown_for_qq,
        pass_through_markers=("[CQ:",),
    )
