package com.aveline.ai.mobile.presentation.chat

import com.aveline.ai.mobile.utils.text.TextSegmenter

/**
 * 文本处理工具
 *
 * 负责将 AI 回复文本按标点和括号进行智能分段，
 * 区分普通文本段和"撤回/内心独白"段（括号内容）。
 *
 * 断句规则不再在本文件手写，统一走 [TextSegmenter]——它是 QQ 端
 * `core/utils/text_segmenter.py` 的 Kotlin 等价实现，两端共用同一套规则。
 */
object ChatTextProcessor {

    /**
     * 单个分段：文本内容 + 是否为括号内撤回段
     */
    data class TextSegment(val text: String, val isRetraction: Boolean)

    // 正则预编译,避免每条消息重复编译的开销
    private val BRACKET_REGEX = Regex("（[\\s\\S]*?）|\\([\\s\\S]*?\\)")

    /**
     * 智能分段：将文本按括号和标点切分为多个片段
     *
     * - 先剥掉模型模仿历史格式输出的时间戳（如 `[09-11 23:40]`）
     * - 括号（中文/英文）内的内容标记为 isRetraction = true
     * - 括号外的内容按 [TextSegmenter.splitMessage] 的断句规则切分，
     *   并清掉每段句尾的多余标点（句号/逗号/省略号等）
     *
     * @param text 原始文本
     * @return 分段列表，空文本返回空列表
     */
    fun smartSegmentText(text: String): List<TextSegment> {
        if (text.isBlank()) return emptyList()
        val cleaned = TextSegmenter.stripAiTimestamp(text)
        if (cleaned.isBlank()) return emptyList()

        val segments = mutableListOf<TextSegment>()
        var lastIndex = 0

        for (match in BRACKET_REGEX.findAll(cleaned)) {
            if (match.range.first > lastIndex) {
                val before = cleaned.substring(lastIndex, match.range.first)
                splitByChatRules(before).forEach { segments.add(TextSegment(it, false)) }
            }
            val innerText = match.value.substring(1, match.value.length - 1).trim()
            if (innerText.isNotEmpty()) {
                segments.add(TextSegment(innerText, true))
            }
            lastIndex = match.range.last + 1
        }

        if (lastIndex < cleaned.length) {
            splitByChatRules(cleaned.substring(lastIndex)).forEach { segments.add(TextSegment(it, false)) }
        }

        return segments
    }

    /**
     * 按聊天断句规则切分括号外的普通文本。
     *
     * 与 QQ 端一致：句号/逗号/分号处的断点会把这些标点吃掉，
     * 感叹号/问号保留（"好呀"而不是"好呀。"；"真的？"保留问号）。
     */
    private fun splitByChatRules(text: String): List<String> {
        if (text.isBlank()) return emptyList()
        return TextSegmenter.splitMessage(text)
            .map { TextSegmenter.stripTrailingPunctuation(it) }
            .filter { it.isNotBlank() }
    }
}
