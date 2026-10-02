package com.aveline.ai.mobile.utils.text

/**
 * 聊天文本清洗：时间戳剥离、句尾标点清理。
 *
 * 对应 Python 端 `core/utils/text_segmenter.py` 的
 * `strip_ai_timestamp` / `strip_trailing_punctuation` / `clean_chat_text`，
 * QQ 端与安卓端共用同一套规则。
 */
object TextCleaners {

    /** 剥离模型模仿历史消息格式输出的时间戳（全局匹配，不只行首）。 */
    fun stripAiTimestamp(text: String): String {
        if (text.isEmpty()) return text
        return TextSegmentRules.AI_TIMESTAMP_REGEX.replace(text, "").trim()
    }

    /**
     * 去除句尾多余标点，让消息结尾更自然：
     * - "。（" → "（"（括号前的句号）
     * - "（xxx。）" → "（xxx）"（括号内部末尾的句号）
     * - "好呀好呀。" → "好呀好呀"、"好呀好呀，" → "好呀好呀"
     *
     * 只清结尾拖尾，句中的逗号/句号保留，不影响语义。
     */
    fun stripTrailingPunctuation(text: String): String {
        if (text.isEmpty()) return text
        var t = TextSegmentRules.PERIOD_BEFORE_BRACKET_REGEX.replace(text, "")
        t = TextSegmentRules.PERIOD_INSIDE_BRACKET_REGEX.replace(t) { m -> m.groupValues[1] }
        t = t.trimEnd { it in TextSegmentRules.TRAILING_PUNCT_CHARS }
        t = t.trim()
        t = TextSegmentRules.TRAILING_DOTS_REGEX.replace(t, "")
        return t.trim()
    }

    /** 展示/发送前的统一清洗：剥时间戳 + 去句尾多余标点。 */
    fun cleanText(text: String): String = stripTrailingPunctuation(stripAiTimestamp(text))
}
