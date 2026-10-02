"""通用聊天文本断句与清洗（Core 公共实现，QQ / 安卓共用同一套规则）。

历史背景：
- 这套规则最初只服务于 QQ 适配器（`clients/bots/qq/utils/message_split.py` 与
  `text_cleaners.py`），跟着真实聊天体验打磨了很久：什么时候该切气泡、
  什么时候不能切（省略号后的感叹词、括号内的舞台描写、编号列表、emoji 粘连等）。
- 安卓端此前只有一套简化分段（`ChatTextProcessor.smartSegmentText`），
  句末句号不过滤、模型模仿历史格式输出的时间戳也不剥，观感和 QQ 明显不一致。

现在把「通用且与渠道无关」的部分下沉到 core：
- Python 侧：QQ 适配器经 `clients/bots/qq/utils/message_split.py` 薄封装调用本模块。
- Kotlin 侧：`clients/frontend/aveline-android/.../utils/TextSegmenter.kt` 是等价实现，
  两端规则常量必须保持一致，由
  `tests/scripts/android_frontend/verify_text_segmenter_parity.py` 做对齐校验。

渠道特有输入通过参数注入，core 不依赖任何客户端实现：
- `preprocess`：断句前的文本预处理（QQ 需要剥离 markdown，安卓端要渲染 markdown 所以不剥）。
- `pass_through_markers`：命中即整段返回的标记（QQ 的 `[CQ:` 码不能被拆碎）。

拆分说明（薄壳门面 + 按职责拆子模块）
--------------------------------------
原 1161 行单文件按职责拆成下列子模块，本文件只做门面转发，
**对外路径与符号名不变**（``from core.utils.text_segmenter import ...`` 照旧可用）：

| 子模块 | 职责 | 安卓端对应 |
|---|---|---|
| ``text_segmenter_rules.py``    | 规则常量（尾随标点 / 硬边界 / 时间戳正则 / Markdown 正则 / 编号列表常量） | ``TextSegmentRules.kt`` |
| ``text_segmenter_emoji.py``    | emoji 范围表与判定 | ``EmojiRanges.kt`` |
| ``text_segmenter_clean.py``    | 清洗 + 展示前按 Markdown 结构分组 | ``TextSegmenter.kt`` |
| ``text_segmenter_numbered.py`` | 编号列表识别与切分 | — |
| ``text_segmenter_merge.py``    | 续接词识别与分段合并 | ``ChatMessageSplitter.kt`` |
| ``text_segmenter_force.py``    | 强制长句分割 + 行内 span 修复 | ``ChatMessageSplitter.kt`` |
| ``text_segmenter_core.py``     | 主断句函数 ``split_chat_message`` | ``ChatMessageSplitter.kt`` |

⚠️ 两端常量对齐校验脚本 ``tests/scripts/android_frontend/verify_text_segmenter_parity.py``
按**源码文本**扫描这一组文件，因此常量放在哪个子模块都可以，但不能改常量名与写法。

拆分是**纯搬家**：未改逻辑、命名与断言。
"""
from __future__ import annotations

# 兼容：clients/bots/qq/utils/message_split.py 会 `from core.utils.text_segmenter import random`，
# 让 patch("clients.bots.qq.utils.message_split.random.random") 仍能命中断句用的 random
import random  # noqa: F401

# 公开 API（对外路径与符号名不变）
from core.utils.text_segmenter_clean import (
    clean_chat_text,
    split_for_display,
    strip_ai_timestamp,
    strip_trailing_punctuation,
)
from core.utils.text_segmenter_core import split_chat_message
from core.utils.text_segmenter_emoji import EMOJI_RANGES, is_emoji_char
from core.utils.text_segmenter_force import (
    force_split_long_sentence,
    has_unclosed_inline_span,
    repair_broken_inline_spans,
)
from core.utils.text_segmenter_merge import (
    is_continuation_start,
    looks_like_manual_space_split,
    merge_chunks_to_limit,
    merge_continuation_chunks,
    merge_space_chunks_to_limit,
)
from core.utils.text_segmenter_numbered import (
    find_numbered_list_starts,
    is_numbered_item_start,
    normalize_numbered_list,
)
from core.utils.text_segmenter_rules import (
    AI_TIMESTAMP_PATTERN,
    AI_TIMESTAMP_PATTERN_SOURCE,
    CONTINUATION_ADVERBS,
    CONTINUATION_ENDINGS,
    ELLIPSIS_MERGE_PREFIX_LIMIT,
    EXPLICIT_SPACE_BOUNDARY_ENDINGS,
    HARD_BUBBLE_BOUNDARY_ENDINGS,
    PUNCTUATION_FOR_SPACE_GUARD,
    TRAILING_PUNCT_CHARS,
)

# 兼容入口：原模块的私有助手与私有正则，仅供排查脚本按旧路径引用
from core.utils.text_segmenter_clean import (
    _group_display_lines as _group_display_lines,
)
from core.utils.text_segmenter_rules import (
    _LATEX_MARKER_RE as _LATEX_MARKER_RE,
)
from core.utils.text_segmenter_rules import (
    _MARKDOWN_BLOCK_START_RE as _MARKDOWN_BLOCK_START_RE,
)
from core.utils.text_segmenter_rules import (
    _MARKDOWN_TABLE_LINE_RE as _MARKDOWN_TABLE_LINE_RE,
)
from core.utils.text_segmenter_rules import (
    _NUMBERED_ITEM_ALLOWED_PREV as _NUMBERED_ITEM_ALLOWED_PREV,
)
from core.utils.text_segmenter_rules import (
    _NUMBERED_ITEM_RE as _NUMBERED_ITEM_RE,
)
from core.utils.text_segmenter_rules import (
    _NUMBERED_LIST_LEAD_MERGE_ENDINGS as _NUMBERED_LIST_LEAD_MERGE_ENDINGS,
)
from core.utils.text_segmenter_rules import (
    _NUMBERED_LIST_LEAD_MERGE_LIMIT as _NUMBERED_LIST_LEAD_MERGE_LIMIT,
)

# 对外契约：与原单文件时期的 27 个顶层公开符号一一对应，一个不少。
__all__ = [
    # 常量 / 正则
    "AI_TIMESTAMP_PATTERN",
    "AI_TIMESTAMP_PATTERN_SOURCE",
    "CONTINUATION_ADVERBS",
    "CONTINUATION_ENDINGS",
    "ELLIPSIS_MERGE_PREFIX_LIMIT",
    "EMOJI_RANGES",
    "EXPLICIT_SPACE_BOUNDARY_ENDINGS",
    "HARD_BUBBLE_BOUNDARY_ENDINGS",
    "PUNCTUATION_FOR_SPACE_GUARD",
    "TRAILING_PUNCT_CHARS",
    # 清洗与展示
    "clean_chat_text",
    "split_for_display",
    "strip_ai_timestamp",
    "strip_trailing_punctuation",
    # 断句主流程
    "split_chat_message",
    "force_split_long_sentence",
    "repair_broken_inline_spans",
    "has_unclosed_inline_span",
    # emoji
    "is_emoji_char",
    # 编号列表
    "find_numbered_list_starts",
    "is_numbered_item_start",
    "normalize_numbered_list",
    # 续接词 / 分段合并
    "is_continuation_start",
    "looks_like_manual_space_split",
    "merge_chunks_to_limit",
    "merge_continuation_chunks",
    "merge_space_chunks_to_limit",
]
