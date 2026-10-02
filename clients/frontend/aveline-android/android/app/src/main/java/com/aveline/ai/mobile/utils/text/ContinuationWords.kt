package com.aveline.ai.mobile.utils.text

/**
 * 续接词识别：判断一段文本是否是"上一段话说了一半的续接"。
 *
 * Python 端用 jieba 词性标注判断"首词是否为连词(c)"；安卓端没有分词库，
 * 这里用一张高频连词前缀表做近似：命中即认为是上一段的续接，不应在这里断开。
 *
 * 这是两端**唯一有意保留的实现差异**（无分词库），语义目标一致。
 */
object ContinuationWords {

    /** 续接副词字根：段落以这些字开头的副词起头时，视作上一段的续接（如"还有"/"再到"）。 */
    private val CONTINUATION_ADVERBS = TextSegmentRules.CONTINUATION_ADVERBS

    private val CONJUNCTION_PREFIXES = listOf(
        "而且", "但是", "不过", "然后", "所以", "因为", "可是", "虽然", "如果", "只要",
        "无论", "并且", "或者", "否则", "况且", "因此", "然而", "于是", "接着", "甚至",
        "以及", "与其", "宁可", "反正", "再说", "还有", "另外", "那么", "不如", "于是说",
    )

    /** 判断文本是否以续接词开头（跳过前导标点后看首字/首词）。 */
    fun isContinuationStart(text: String): Boolean {
        if (text.isBlank()) return false
        val stripped = text.trim().take(30)
        var start = 0
        while (start < stripped.length && !stripped[start].isLetterOrDigit()) start++
        val head = stripped.substring(start)
        if (head.isEmpty()) return false
        if (head[0] in CONTINUATION_ADVERBS) return true
        return CONJUNCTION_PREFIXES.any { head.startsWith(it) }
    }
}
