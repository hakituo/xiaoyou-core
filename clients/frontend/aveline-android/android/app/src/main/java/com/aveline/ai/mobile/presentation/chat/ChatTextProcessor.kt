package com.aveline.ai.mobile.presentation.chat

/**
 * 文本处理工具
 *
 * 负责将 AI 回复文本按标点和括号进行智能分段，
 * 区分普通文本段和"撤回/内心独白"段（括号内容）。
 */
object ChatTextProcessor {

    /**
     * 单个分段：文本内容 + 是否为括号内撤回段
     */
    data class TextSegment(val text: String, val isRetraction: Boolean)

    // 正则预编译,避免每条消息重复编译的开销
    private val BRACKET_REGEX = Regex("（[\\s\\S]*?）|\\([\\s\\S]*?\\)")
    private val PUNCT_REGEX = Regex("([。！？.!?]+)")

    /**
     * 智能分段：将文本按括号和标点切分为多个片段
     *
     * - 括号（中文/英文）内的内容标记为 isRetraction = true
     * - 括号外的内容按句末标点（。！？.!?）进一步切分
     *
     * @param text 原始文本
     * @return 分段列表，空文本返回空列表
     */
    fun smartSegmentText(text: String): List<TextSegment> {
        if (text.isBlank()) return emptyList()

        val segments = mutableListOf<TextSegment>()
        var lastIndex = 0

        for (match in BRACKET_REGEX.findAll(text)) {
            if (match.range.first > lastIndex) {
                val before = text.substring(lastIndex, match.range.first)
                splitByPunctuation(before).forEach { segments.add(TextSegment(it, false)) }
            }
            val innerText = match.value.substring(1, match.value.length - 1).trim()
            if (innerText.isNotEmpty()) {
                segments.add(TextSegment(innerText, true))
            }
            lastIndex = match.range.last + 1
        }

        if (lastIndex < text.length) {
            splitByPunctuation(text.substring(lastIndex)).forEach { segments.add(TextSegment(it, false)) }
        }

        return segments
    }

    /**
     * 按句末标点切分文本，保留 ！？!? 但丢弃 。.
     *
     * @param text 待切分文本
     * @return 切分后的句子列表
     */
    private fun splitByPunctuation(text: String): List<String> {
        if (text.isBlank()) return emptyList()

        val result = mutableListOf<String>()
        val matches = PUNCT_REGEX.findAll(text).toList()
        var lastEnd = 0

        for (match in matches) {
            val before = text.substring(lastEnd, match.range.first).trim()
            val punct = match.value
            val keptPunct = punct.filter { it == '！' || it == '？' || it == '!' || it == '?' }
            if (before.isNotEmpty() || keptPunct.isNotEmpty()) {
                result.add(before + keptPunct)
            }
            lastEnd = match.range.last + 1
        }

        val remaining = text.substring(lastEnd).trim()
        if (remaining.isNotEmpty()) {
            result.add(remaining)
        }

        return result.filter { it.isNotBlank() }
    }
}
