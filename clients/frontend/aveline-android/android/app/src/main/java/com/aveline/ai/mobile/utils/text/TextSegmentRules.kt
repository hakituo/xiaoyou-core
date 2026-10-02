package com.aveline.ai.mobile.utils.text

/**
 * 断句/清洗的规则常量与预编译正则（单点真源）。
 *
 * 与 Python 端 `core/utils/text_segmenter.py` 的同名常量**严格一致**，
 * 两端是否漂移由 `tests/scripts/android_frontend/verify_text_segmenter_parity.py`
 * 逐项比对；改这里（或改 Python 侧）必须同步另一端。
 *
 * 具体怎么用这些规则见：
 * - [TextCleaners] 清洗
 * - [ChatMessageSplitter] 断句主循环
 * - [TextSegmenter] 对外门面
 */
object TextSegmentRules {

    /** 哨兵值：表示"没有字符"（对应 Python 版的空串判断）。 */
    const val NO_CHAR = '\u0000'

    /** 句尾需要清掉的拖尾多余标点：句号、逗号、英文点/逗号、省略号、分号等。 */
    const val TRAILING_PUNCT_CHARS = "。.，,．、；;…"

    /** 省略号前"短促前缀"的判定长度，见 [ChatMessageSplitter.splitMessage]。 */
    const val ELLIPSIS_MERGE_PREFIX_LIMIT = 6

    /**
     * 模型模仿历史消息格式输出的时间戳（如 `[09-11 23:40]` / `[今天 20:00]` / `[3天前 08:00]`）。
     *
     * 历史消息在喂给模型前会被统一加上 `[今天/昨天/X天前 HH:MM] ` 前缀，模型很容易把这个
     * 格式学过去写进回复里，因此所有端都要在展示/发送前剥掉。
     */
    const val AI_TIMESTAMP_PATTERN_SOURCE =
        "\\[(?:(?:\\d{2,4}(?:-\\d{2}){1,2}|今天|昨天|\\d+天前)\\s+)?\\d{2}:\\d{2}(?::\\d{2})?(?:\\s*\\([^)]+\\))?\\]\\s*"

    /** 硬气泡边界：句号 / 感叹号 / 问号 / 省略号，这些位置天然是"一句话说完了"。 */
    val HARD_BUBBLE_BOUNDARY_ENDINGS = charArrayOf(
        '。',
        '.',
        '！',
        '!',
        '？',
        '?',
        '…',
    )

    /** 显式空格边界：硬边界之外，逗号/分号后跟空格也算用户主动分泡泡。 */
    val EXPLICIT_SPACE_BOUNDARY_ENDINGS = charArrayOf(
        '。',
        '.',
        '！',
        '!',
        '？',
        '?',
        '…',
        '，',
        ',',
        '；',
        ';',
    )

    /** 未完标点：以这些结尾说明话没说完，必须与下一段合并。 */
    val CONTINUATION_ENDINGS = arrayOf(
        "：",
        ":",
        "——",
        "—",
    )

    /** 续接副词字根：段落以这些字开头的副词起头时，视作上一段的续接。 */
    val CONTINUATION_ADVERBS = charArrayOf(
        '再',
        '又',
        '还',
        '更',
    )

    /** 出现在文本里就算"有标点"，用于判断某段是否像人工空格分泡泡。 */
    val PUNCTUATION_FOR_SPACE_GUARD = "。.!！?？,，;；:：、…~～()（）[]【】{}<>《》\"'“”‘’"

    /** 判断字符是否是"硬气泡边界"标点（。.！!？?…）。 */
    fun isHardBoundary(ch: Char): Boolean = ch in HARD_BUBBLE_BOUNDARY_ENDINGS

    /** 判断字符是否是逗号/分号一类的软边界标点。 */
    fun isSoftBoundary(ch: Char): Boolean = ch == '，' || ch == ',' || ch == '；' || ch == ';'

    // ------------------------------------------------------------------
    // 预编译正则（避免每条消息重复编译）
    // ------------------------------------------------------------------

    val AI_TIMESTAMP_REGEX = Regex(AI_TIMESTAMP_PATTERN_SOURCE)
    val PERIOD_BEFORE_BRACKET_REGEX = Regex("[。.]\\s*(?=[（(])")
    val PERIOD_INSIDE_BRACKET_REGEX = Regex("[。.]+\\s*([）)])")
    val TRAILING_DOTS_REGEX = Regex("[。.]+$")

    /** 字面 `\n` / `/n` 归一成真正的换行（兼容重复转义后的 `\\n`）。 */
    val ESCAPED_NEWLINE_REGEX = Regex("(?:\\\\+|[／/])[nN]")

    val BRACKET_NEWLINE_REGEX = Regex("([（(][^）)\\n]{1,120})\\n([^）)\\n]{0,120}[）)])")
    val OPEN_QUOTE_NEWLINE_REGEX = Regex("([\u201c\u2018\u300c\u300e])\\s*\\n")
    val CLOSE_QUOTE_NEWLINE_REGEX = Regex("\\n\\s*([\u201d\u2019\u300d\u300f])")
    val NUMBERED_ITEM_REGEX = Regex("(\\d{1,2})([.．、)）])")
    val CJK_REGEX = Regex("[\\u4e00-\\u9fff]")
    val WHITESPACE_REGEX = Regex("\\s+")
}
