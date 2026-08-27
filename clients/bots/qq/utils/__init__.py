"""QQ 适配器工具包（门面）。

历史上下文：
- 本包由原 `utils.py`（1129 行单文件）拆分而来，按职责拆成 8 个子模块。
- 本 `__init__.py` 作为门面，re-export 全部公共/私有符号，保持向后兼容：
  外部 `from clients.bots.qq.utils import xxx` 的代码无需改动。

子模块职责：
- session_ids:        会话 ID 解析与跨平台 conversation_id
- emotion_labels:     情绪/表情标签映射
- cq_codes:           CQ 码构建、URL/路径工具、表情标签位置规范化
- message_split:      消息断句核心（句号/逗号/省略号/换行等切气泡）
- text_cleaners:      markdown/think/timestamp/动作描写/尾随标点清洗
- base64_guard:        裸 base64 防泄漏与含 CQ 码长文本分割
- reaction_delay:      反应延迟标签 [DELAY:s] 处理
- transport_helpers:   WebSocket 连接与文本截断
"""

# ---- emoji 兼容导出（原 utils.py 顶部从 emoji_filter re-export 的符号）----
from clients.bots.qq.emoji_filter import (
    _allowed_emoji_cache,
    _collect_allowed_emojis_from_persona,
    _extract_emojis_from_text,
    _is_emoji_char,
    clear_allowed_emoji_cache,
    get_allowed_emojis,
    strip_ooc_emoji,
)

# ---- session_ids ----
from clients.bots.qq.utils.session_ids import (
    build_persona_conversation_id,
    parse_session_user_id,
)

# ---- emotion_labels ----
from clients.bots.qq.utils.emotion_labels import (
    EMOTION_LABEL_NORMALIZATION,
    EMOTION_TO_FACE_LABEL,
    resolve_emotion_face_label,
)

# ---- cq_codes ----
from clients.bots.qq.utils.cq_codes import (
    _append_query_param,
    _build_cq_image,
    _build_cq_record,
    _build_cq_video,
    _normalize_qq_face_position,
    _to_forward_slashes,
)

# ---- message_split（断句全套）----
from clients.bots.qq.utils.message_split import (
    _CONTINUATION_ADVERBS,
    _CONTINUATION_ENDINGS,
    _ELLIPSIS_MERGE_PREFIX_LIMIT,
    _EXPLICIT_SPACE_BOUNDARY_ENDINGS,
    _HARD_BUBBLE_BOUNDARY_ENDINGS,
    _PUNCTUATION_FOR_SPACE_GUARD,
    _force_split_long_sentence,
    _is_continuation_start,
    _looks_like_manual_space_split,
    _merge_chunks_to_limit,
    _merge_continuation_chunks,
    _merge_space_chunks_to_limit,
    _split_message_for_qq,
)
# 兼容旧测试：patch("clients.bots.qq.utils.random.random") 仍能定位到断句用的 random
from clients.bots.qq.utils.message_split import random

# ---- text_cleaners ----
from clients.bots.qq.utils.text_cleaners import (
    _AI_TS_PATTERN,
    _TRAILING_PUNCT_CHARS,
    _strip_action_descriptions,
    _strip_markdown_for_qq,
    _strip_think_for_qq,
    _strip_trailing_periods_for_qq,
    strip_ai_timestamp,
)

# ---- base64_guard ----
from clients.bots.qq.utils.base64_guard import (
    _BASE64_PATTERN,
    _contains_raw_base64,
    _is_base64_cq_code,
    _split_plain_text,
    _split_text_with_cq_codes,
    _strip_base64_from_text,
)

# ---- reaction_delay ----
from clients.bots.qq.utils.reaction_delay import (
    DEFAULT_QQ_REACTION_DELAY_MAX_SECONDS,
    _LEADING_REACTION_DELAY_RE,
    _REACTION_DELAY_TAG_RE,
    extract_leading_reaction_delay,
    strip_all_reaction_delay_tags,
)

# ---- transport_helpers ----
from clients.bots.qq.utils.transport_helpers import (
    _truncate_text,
    _ws_connect,
)

__all__ = [
    # session_ids
    "parse_session_user_id",
    "build_persona_conversation_id",
    # emotion_labels
    "EMOTION_TO_FACE_LABEL",
    "EMOTION_LABEL_NORMALIZATION",
    "resolve_emotion_face_label",
    # cq_codes
    "_append_query_param",
    "_build_cq_image",
    "_build_cq_record",
    "_build_cq_video",
    "_normalize_qq_face_position",
    "_to_forward_slashes",
    # message_split
    "_split_message_for_qq",
    "_force_split_long_sentence",
    "_merge_chunks_to_limit",
    "_merge_continuation_chunks",
    "_is_continuation_start",
    "_looks_like_manual_space_split",
    "_merge_space_chunks_to_limit",
    "_CONTINUATION_ADVERBS",
    "_CONTINUATION_ENDINGS",
    "_HARD_BUBBLE_BOUNDARY_ENDINGS",
    "_EXPLICIT_SPACE_BOUNDARY_ENDINGS",
    "_PUNCTUATION_FOR_SPACE_GUARD",
    "_ELLIPSIS_MERGE_PREFIX_LIMIT",
    # text_cleaners
    "_strip_action_descriptions",
    "_strip_think_for_qq",
    "strip_ai_timestamp",
    "_strip_markdown_for_qq",
    "_strip_trailing_periods_for_qq",
    "_AI_TS_PATTERN",
    "_TRAILING_PUNCT_CHARS",
    # base64_guard
    "_split_plain_text",
    "_split_text_with_cq_codes",
    "_contains_raw_base64",
    "_strip_base64_from_text",
    "_is_base64_cq_code",
    "_BASE64_PATTERN",
    # reaction_delay
    "extract_leading_reaction_delay",
    "strip_all_reaction_delay_tags",
    "DEFAULT_QQ_REACTION_DELAY_MAX_SECONDS",
    "_REACTION_DELAY_TAG_RE",
    "_LEADING_REACTION_DELAY_RE",
    # transport_helpers
    "_ws_connect",
    "_truncate_text",
    # emoji 兼容
    "strip_ooc_emoji",
    "get_allowed_emojis",
    "clear_allowed_emoji_cache",
    "_allowed_emoji_cache",
    "_collect_allowed_emojis_from_persona",
    "_extract_emojis_from_text",
    "_is_emoji_char",
]
