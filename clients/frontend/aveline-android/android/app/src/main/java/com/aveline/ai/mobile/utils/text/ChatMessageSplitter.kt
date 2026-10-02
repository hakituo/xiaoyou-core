package com.aveline.ai.mobile.utils.text

import kotlin.random.Random

/**
 * 断句主循环：把模型回复切成多个气泡，模拟真人碎句聊天节奏。
 *
 * 对应 Python 端 `core/utils/text_segmenter.py` 的 `split_chat_message`
 * （QQ 适配器经 `clients/bots/qq/utils/message_split.py` 薄封装调用）。
 * 规则常量真源在 [TextSegmentRules]，本文件只负责"什么时候切"的流程。
 */
object ChatMessageSplitter {

    /** "1. " 这类编号列表项的前缀（后面跟字母/汉字时不是句号）。 */
    private val NUMBERED_ONLY_REGEX = Regex("\\d{1,3}\\.")

    /** 这些标点后面紧跟 emoji 时，把 emoji 粘到当前句尾。 */
    private val EMOJI_GLUE_PUNCT = charArrayOf('?', '？', '!', '！', '。', '.')

    /** 开头单独成"催促词"时不在逗号处断句（"等等，我想想"不该切成两条）。 */
    private val WAIT_WORDS = setOf("等等", "等下", "等一下", "稍等", "先等等", "先等下")

    /**
     * 感叹词（"哈？！"、"啊！"、"哇？"这类）。
     *
     * Python 版这里的常量里还写了 "ha"/"wow" 等英文条目，但它的判定是
     * `next_char in 元组`（拿单个字符去比），多字符条目实际永远不会命中。
     * 端口保持一致，仍按单字符语义判定，避免两端行为分叉。
     */
    private val EXCLAMATION_CHARS =
        charArrayOf('哈', '啊', '哇', '哎', '唉', '唔', '嗯', '哼', '咦', '嘿', '噢')

    /** 判断 idx 处是否是"感叹词 + 结束标点"模式（如"……哈？！"）。 */
    private fun isExclamationPattern(s: String, idx: Int): Boolean {
        if (idx >= s.length) return false
        if (s[idx] !in EXCLAMATION_CHARS) return false
        var afterWord = idx + 1
        while (afterWord < s.length && s[afterWord] !in TextSegmentRules.HARD_BUBBLE_BOUNDARY_ENDINGS) {
            if (s[afterWord].isWhitespace() && s[afterWord] != '\n') {
                afterWord++
                continue
            }
            break
        }
        return afterWord < s.length && s[afterWord] in TextSegmentRules.HARD_BUBBLE_BOUNDARY_ENDINGS
    }

    /** 判断 idx 处是否以感叹词开头（用于"后面不是普通句子"的判定）。 */
    private fun isExclamationStart(s: String, idx: Int): Boolean {
        if (idx >= s.length) return false
        return s[idx] in EXCLAMATION_CHARS
    }

    /**
     * 段内 `**加粗**` 与反引号代码是否只闭合了一半。
     *
     * 只统计未转义的 `**` 和反引号（前面带反斜杠的跳过）；数量为奇数即说明配对被切开。
     */
    private fun hasUnclosedInlineSpan(text: String): Boolean {
        var count = 0
        var index = 0
        while (index < text.length) {
            when {
                text[index] == '\\' -> index += 2
                text.startsWith("**", index) -> {
                    count++
                    index += 2
                }
                text[index] == '`' -> {
                    count++
                    index++
                }
                else -> index++
            }
        }
        return count % 2 == 1
    }

    /**
     * 把被断句切坏的行内 Markdown span 拼回同一段。
     *
     * 断句器按标点切分，而加粗里可以自带句号——例如 `**古之人 / 不 / 余 / 欺。**`
     * 会被切成「`**古之人 / 不 / 余 / 欺`」+「`** 顺便…`」两段，两段各自只有一个 `**`，
     * 渲染时星号落单、原样显示出来。这里检测未闭合的 span，把后一段并回前一段再判断，
     * 直到配平为止。
     *
     * 并回时直接拼接不加分隔符：断点处的句号已被断句器吃掉，拼回去正好还原成
     * `**古之人 / 不 / 余 / 欺**` 这种合法闭合（闭合 `**` 前面不能有空格）。
     */
    private fun repairBrokenInlineSpans(chunks: List<String>): List<String> {
        if (chunks.size < 2) return chunks
        val result = mutableListOf<String>()
        var buffer: String? = null
        for (chunk in chunks) {
            val candidate = buffer?.let { it + chunk } ?: chunk
            if (hasUnclosedInlineSpan(candidate)) {
                buffer = candidate
            } else {
                result += candidate
                buffer = null
            }
        }
        buffer?.let(result::add)
        return result
    }

    /**
     * 断句主入口（对应 Python 版 `split_chat_message`）。
     *
     * 规则要点：
     * 1. 优先在句号、问号、感叹号处断句（仅当累积长度 >= [minSplitLen]，或极短句）
     * 2. 其次在逗号、分号处断句（仅当累积长度 >= [maxLen]，且按 [commaSplitProb] 概率）
     * 3. 超过 [maxLen] * 2 强制在最近的标点处折断
     * 4. 括号/引号内的内容不在内部断句，编号列表（1. 2. 3.）按编号成泡
     *
     * @param maxLen 单个气泡的最大长度
     * @param commaSplitProb 逗号断句概率
     * @param minSplitLen 最小断句长度，短于此长度不在标点处断句
     * @param passThroughMarkers 命中即整段返回的标记（如 QQ 的 `[CQ:` 码，整段不可拆分）
     * @param random 逗号断句的随机源，注入固定种子即可在测试里得到确定结果
     */
    fun splitMessage(
        text: String,
        maxLen: Int = 150,
        commaSplitProb: Double = 0.2,
        minSplitLen: Int = 40,
        passThroughMarkers: List<String> = emptyList(),
        random: Random = Random.Default,
    ): List<String> {
        var s = text
        if (s.isEmpty()) return emptyList()
        for (marker in passThroughMarkers) {
            if (marker.isNotEmpty() && s.contains(marker)) return listOf(s)
        }

        s = TextSegmentRules.ESCAPED_NEWLINE_REGEX.replace(s, "\n")

        if (ChunkMerger.looksLikeManualSpaceSplit(s)) {
            val parts = s.split(TextSegmentRules.WHITESPACE_REGEX).map { it.trim() }.filter { it.isNotEmpty() }
            return ChunkMerger.mergeSpaceChunksToLimit(parts, 6)
        }

        s = Regex("。\\.{3,}").replace(s, "......")
        s = Regex("。…+").replace(s, "……")

        // 括号内被换行拆开的舞台描写合并回一行（最多 3 轮）
        for (round in 0 until 3) {
            val merged = TextSegmentRules.BRACKET_NEWLINE_REGEX.replace(s) { m ->
                "${m.groupValues[1]} ${m.groupValues[2]}"
            }
            if (merged == s) break
            s = merged
        }

        // 引号内的换行去掉，避免被断成多条消息
        s = TextSegmentRules.OPEN_QUOTE_NEWLINE_REGEX.replace(s) { m -> m.groupValues[1] }
        s = TextSegmentRules.CLOSE_QUOTE_NEWLINE_REGEX.replace(s) { m -> m.groupValues[1] }

        // 方括号标记（如 [THINK_STORE: ...]）整体不拆
        if (s.startsWith("[") && s.contains("]")) {
            val firstClose = s.indexOf(']')
            if (firstClose == s.length - 1) return listOf(s)
            if (s.length - firstClose <= 10) return listOf(s)
        }

        // 行内编号列表按编号切成独立气泡
        s = NumberedListSplitter.normalizeNumberedList(s)

        val maxLen0 = maxOf(20, maxLen)
        val commaProb = commaSplitProb.coerceIn(0.0, 1.0)
        val minSplitLen0 = maxOf(10, minSplitLen)

        // 用户明确用换行分隔内容：按行递归，不做续接合并与块数限制，保留原始换行意图
        if (s.contains('\n')) {
            val merged = mutableListOf<String>()
            for (line in s.split('\n')) {
                val trimmed = line.trim()
                if (trimmed.isEmpty()) continue
                merged.addAll(splitMessage(trimmed, maxLen0, commaProb, minSplitLen0, passThroughMarkers, random))
            }
            return merged
        }

        val n = s.length
        val result = mutableListOf<String>()
        val current = StringBuilder()
        val stack = mutableListOf<Char>()
        val closingToOpening = mapOf(
            '）' to '（',
            ')' to '(',
            ']' to '[',
            '}' to '{',
            '】' to '【',
            '\u201D' to '\u201C',
            '\u2019' to '\u2018',
            '"' to '"',
            '\'' to '\'',
        )
        // 方括号/花括号/方头括号也要配对跟踪：模型输出数学区间 [1, 3]、
        // 集合 {1, 2} 时是英文排版习惯（逗号后带空格），若不进栈，
        // 会被"逗号+空格=用户主动分泡"的显式边界规则误断成 [1 / 3]
        val openers = charArrayOf('（', '(', '[', '{', '【', '\u201C', '\u2018')
        val noChar = TextSegmentRules.NO_CHAR

        var i = 0
        while (i < n) {
            val ch = s[i]
            val prevChar = if (i > 0) s[i - 1] else noChar
            val nextChar = if (i + 1 < n) s[i + 1] else noChar
            var lookAhead = i + 1
            var sawSpaceAfterPunct = false
            while (lookAhead < n && s[lookAhead].isWhitespace()) {
                sawSpaceAfterPunct = true
                lookAhead++
            }
            val nextVisibleChar = if (lookAhead < n) s[lookAhead] else noChar
            val explicitSpaceBoundary = sawSpaceAfterPunct && nextVisibleChar != noChar

            // 括号/引号配对计数：stack 非空说明当前处于括号内，不在内部断句
            when {
                ch == '"' -> {
                    if (stack.isNotEmpty() && stack.last() == ch) stack.removeAt(stack.lastIndex) else stack.add(ch)
                }
                ch == '\'' -> {
                    // 英文缩写（don't）里的撇号不是引号
                    val isContraction = i > 0 && i < n - 1 && s[i - 1].isLetter() && s[i + 1].isLetter()
                    if (!isContraction) {
                        if (stack.isNotEmpty() && stack.last() == ch) stack.removeAt(stack.lastIndex) else stack.add(ch)
                    }
                }
                ch in openers -> stack.add(ch)
                ch in closingToOpening -> {
                    val opening = closingToOpening[ch]
                    if (opening != null && stack.isNotEmpty() && stack.last() == opening) {
                        stack.removeAt(stack.lastIndex)
                    }
                }
            }
            current.append(ch)

            // 括号结束后紧跟"省略号 + 普通句子"时，在括号处断句，把省略号留给后续句子：
            // "（动作描写） ……后续句子" -> ["（动作描写）", "……后续句子"]
            if ((ch == '）' || ch == ')') && stack.isEmpty()) {
                var cursor = i + 1
                while (cursor < n && s[cursor].isWhitespace() && s[cursor] != '\n') cursor++
                if (cursor < n && s[cursor] == '…') {
                    while (cursor < n && s[cursor] == '…') cursor++
                    var afterEllipsis = cursor
                    while (afterEllipsis < n && s[afterEllipsis].isWhitespace() && s[afterEllipsis] != '\n') {
                        afterEllipsis++
                    }
                    val following = if (afterEllipsis < n) s[afterEllipsis] else noChar
                    if (following != noChar &&
                        following !in TextSegmentRules.HARD_BUBBLE_BOUNDARY_ENDINGS &&
                        following !in EXCLAMATION_CHARS &&
                        following != '\n'
                    ) {
                        val trimmed = current.toString().trim()
                        if (trimmed.isNotEmpty() && result.size < 2) {
                            result.add(trimmed)
                            current.clear()
                        }
                    }
                }
            }

            if (ch == '.') {
                var dotCount = 1
                while (i + dotCount < n && s[i + dotCount] == '.') dotCount++
                repeat(dotCount - 1) { current.append('.') }

                // 英文省略号（>=3 个点）与中文省略号同一套规则
                if (dotCount >= 3) {
                    var cursor = i + dotCount
                    while (cursor < n && s[cursor].isWhitespace() && s[cursor] != '\n') cursor++
                    val following = if (cursor < n) s[cursor] else noChar

                    val shouldSplit = stack.isEmpty() &&
                        result.size < 2 &&
                        !isExclamationPattern(s, cursor) &&
                        (
                            following == noChar ||
                                following == '\n' ||
                                (cursor > i + dotCount && s[cursor - 1] == ' ') ||
                                (following !in TextSegmentRules.HARD_BUBBLE_BOUNDARY_ENDINGS && !isExclamationStart(s, cursor))
                            )
                    if (shouldSplit) {
                        val trimmed = current.toString().trim()
                        if (trimmed.isNotEmpty()) result.add(trimmed)
                        current.clear()
                    }
                }
                i += dotCount
                continue
            }

            if (ch == '…') {
                var ellipsisCount = 1
                while (i + ellipsisCount < n && s[i + ellipsisCount] == '…') ellipsisCount++
                repeat(ellipsisCount - 1) { current.append('…') }

                var cursor = i + ellipsisCount
                while (cursor < n && s[cursor].isWhitespace() && s[cursor] != '\n') cursor++
                val following = if (cursor < n) s[cursor] else noChar

                // "就是……戳废了" 里"就是"只是短促前缀，不该断成"就是……"
                val ellipsisCore = current.toString().trimEnd('…').trim()
                val isEllipsisOnly =
                    ellipsisCore.isNotEmpty() && ellipsisCore.length <= TextSegmentRules.ELLIPSIS_MERGE_PREFIX_LIMIT
                val isNormalSentenceAfter = following != noChar &&
                    following !in TextSegmentRules.HARD_BUBBLE_BOUNDARY_ENDINGS &&
                    following !in EXCLAMATION_CHARS &&
                    following != '\n'
                // 省略号后的显式空格说明用户主动分泡泡，优先级高于短促前缀合并
                val hasExplicitSpaceAfter = cursor > i + ellipsisCount && s[cursor - 1] == ' '

                val shouldSplit = stack.isEmpty() &&
                    result.size < 2 &&
                    !isExclamationPattern(s, cursor) &&
                    !(isEllipsisOnly && isNormalSentenceAfter && !hasExplicitSpaceAfter) &&
                    (
                        following == noChar ||
                            following == '\n' ||
                            hasExplicitSpaceAfter ||
                            (following !in TextSegmentRules.HARD_BUBBLE_BOUNDARY_ENDINGS && following !in EXCLAMATION_CHARS)
                        )
                if (shouldSplit) {
                    val trimmed = current.toString().trim()
                    if (trimmed.isNotEmpty()) result.add(trimmed)
                    current.clear()
                }
                i += ellipsisCount
                continue
            }

            if (stack.isEmpty() &&
                (TextSegmentRules.isHardBoundary(ch) || TextSegmentRules.isSoftBoundary(ch))
            ) {
                // 3.14 / v1.2.3 里的点不是句号
                if (ch == '.' && prevChar.isDigit() && nextChar.isDigit()) {
                    i++
                    continue
                }
                // "1. xxx" 这类编号列表项开头的点也不是句号
                if (ch == '.') {
                    val numberedPrefix = current.toString().trim()
                    var cursor = i + 1
                    while (cursor < n && s[cursor].isWhitespace()) cursor++
                    if (NUMBERED_ONLY_REGEX.matches(numberedPrefix) &&
                        cursor < n && (s[cursor].isLetter() || s[cursor].code in 0x4E00..0x9FFF)
                    ) {
                        i++
                        continue
                    }
                }
                // 连着的"？！？"整体保留在当前气泡里
                if (ch == '?' || ch == '？' || ch == '!' || ch == '！') {
                    var repeatCount = 1
                    while (i + repeatCount < n && s[i + repeatCount] == ch) repeatCount++
                    if (repeatCount > 1) {
                        repeat(repeatCount - 1) { current.append(ch) }
                        i += repeatCount - 1
                    }
                }
                // 硬边界标点后紧跟 emoji 时，把 emoji 粘到当前句尾，避免被断到下一句开头
                if (ch in EMOJI_GLUE_PUNCT) {
                    var emoLook = i + 1
                    if (emoLook < n) {
                        val cp = s.codePointAt(emoLook)
                        if (EmojiRanges.isEmojiCodePoint(cp)) {
                            while (emoLook < n) {
                                val emojiCp = s.codePointAt(emoLook)
                                if (!EmojiRanges.isEmojiCodePoint(emojiCp)) break
                                current.append(s.substring(emoLook, emoLook + Character.charCount(emojiCp)))
                                emoLook += Character.charCount(emojiCp)
                            }
                            i = emoLook - 1
                            if (emoLook < n && s[emoLook] == '\n') {
                                val trimmed = current.toString().trim()
                                if (trimmed.isNotEmpty()) result.add(trimmed)
                                current.clear()
                            } else if (emoLook < n && s[emoLook].isWhitespace()) {
                                val trimmed = current.toString().trim()
                                if (trimmed.isNotEmpty() && result.size < 2) result.add(trimmed)
                                current.clear()
                            }
                            i++
                            continue
                        }
                    }
                }
                if (TextSegmentRules.isSoftBoundary(ch)) {
                    val firstChunkPrefix = current.toString().dropLast(1).trim()
                    if (result.isEmpty() && firstChunkPrefix in WAIT_WORDS) {
                        i++
                        continue
                    }
                }
                val currentLen = current.toString().trim().length

                // "……哈？！" 这类"省略号 + 感叹词"不该在问号处断句
                var isEllipsisExclamation = false
                val strippedCurrent = current.toString().trim()
                if (strippedCurrent.startsWith("……") || strippedCurrent.startsWith("...")) {
                    val afterEllipsis = strippedCurrent.trimStart('…').trimStart('.')
                    if (afterEllipsis.isNotEmpty() && afterEllipsis[0] in EXCLAMATION_CHARS) {
                        isEllipsisExclamation = true
                    }
                }
                if (isEllipsisExclamation && (ch == '?' || ch == '？' || ch == '!' || ch == '！')) {
                    var lookAheadPunct = i + 1
                    while (lookAheadPunct < n && s[lookAheadPunct].isWhitespace()) lookAheadPunct++
                    if (lookAheadPunct < n && s[lookAheadPunct] in TextSegmentRules.HARD_BUBBLE_BOUNDARY_ENDINGS) {
                        i++
                        continue
                    }
                    if (currentLen < 10 && result.size >= 2) {
                        i++
                        continue
                    }
                }

                if (TextSegmentRules.isSoftBoundary(ch)) {
                    if (!explicitSpaceBoundary) {
                        if (currentLen < maxLen0) {
                            i++
                            continue
                        }
                        if (random.nextDouble() > commaProb) {
                            i++
                            continue
                        }
                    }
                } else {
                    // 句号断句规则：极短句（<10 字）断、长句（>= minSplitLen）断、中间长度保持完整
                    val isVeryShort = currentLen < 10
                    val isLongEnough = currentLen >= minSplitLen0
                    if (!explicitSpaceBoundary && !isVeryShort && !isLongEnough) {
                        i++
                        continue
                    }
                    if (result.size >= 2) {
                        i++
                        continue
                    }
                }

                val trimmed = current.toString().trim()
                if (trimmed.isNotEmpty()) {
                    when {
                        explicitSpaceBoundary &&
                            TextSegmentRules.EXPLICIT_SPACE_BOUNDARY_ENDINGS.any { trimmed.endsWith(it) } -> {
                            result.add(trimmed)
                        }
                        // 断点处的句号/逗号/分号吃掉，感叹号/问号保留
                        TextSegmentRules.isSoftBoundary(ch) || ch == '。' -> {
                            result.add(current.toString().dropLast(1).trim())
                        }
                        else -> result.add(trimmed)
                    }
                }
                current.clear()
            }
            i++
        }

        val tail = current.toString().trim()
        if (tail.isNotEmpty()) result.add(tail)

        if (result.size > 1) {
            var chunks = ChunkMerger.mergeContinuationChunks(result, maxLen0 * 2, minSplitLen0)
            if (chunks.size > 6) chunks = ChunkMerger.mergeChunksToLimit(chunks, 6)
            return repairBrokenInlineSpans(chunks)
        }

        if (s.length > maxLen0 * 2) {
            val forced = LongSentenceSplitter.forceSplitLongSentence(s, maxLen0, 6)
            if (forced.size > 1) return repairBrokenInlineSpans(forced)
        }

        return listOf(s)
    }
}
