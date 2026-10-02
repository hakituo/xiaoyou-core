package com.aveline.ai.mobile.utils.text

/**
 * 行内编号列表识别与归一化（`1. xxx 2. xxx 3. xxx`）。
 *
 * 把编号列表切成多行后，由 [ChatMessageSplitter] 的换行逻辑逐行处理，
 * 每个编号项成为独立气泡，不会出现"第一项说了一半就断句、下一条又接上 2."的割裂感。
 */
object NumberedListSplitter {

    private const val LEAD_MERGE_LIMIT = 24
    private val LEAD_MERGE_ENDINGS = arrayOf("：", ":", "——", "—", "-", "～", "~")

    /** 编号前允许出现的字符：行首、空白或中英文标点（数字与句点会先被排除）。 */
    private const val ITEM_ALLOWED_PREV = "。.!！?？,，;；:：、…~～()（）[]【】{}<>《》\"'“”‘’——-—*·/|"

    /** 判断 idx 处的数字是否可能是编号列表项的起点。 */
    private fun isNumberedItemStart(s: String, idx: Int): Boolean {
        if (idx <= 0) return true
        val prev = s[idx - 1]
        if (prev.isWhitespace()) return true
        if (prev.isDigit() || prev == '.') return false
        return prev in ITEM_ALLOWED_PREV
    }

    /** 找出编号列表各项的起始下标。 */
    private fun findStarts(s: String): List<Int> {
        val candidates = mutableListOf<Pair<Int, Int>>()
        for (m in TextSegmentRules.NUMBERED_ITEM_REGEX.findAll(s)) {
            val start = m.range.first
            if (!isNumberedItemStart(s, start)) continue
            var look = m.range.last + 1
            while (look < s.length && s[look].isWhitespace()) look++
            val nextChar = if (look < s.length) s[look] else TextSegmentRules.NO_CHAR
            if (!(nextChar != TextSegmentRules.NO_CHAR && (nextChar.isLetter() || nextChar.code in 0x4E00..0x9FFF))) {
                continue
            }
            val num = m.groupValues[1].toIntOrNull() ?: continue
            candidates.add(start to num)
        }
        if (candidates.size < 2) return emptyList()

        // 只认编号严格递增的最长连续段（1. 2. 3.），至少两项才认为是编号列表，
        // 避免误伤小数、版本号、日期等
        var best = listOf<Pair<Int, Int>>()
        var idx = 0
        while (idx < candidates.size) {
            val seq = mutableListOf(candidates[idx])
            var nxt = idx + 1
            while (nxt < candidates.size && candidates[nxt].second > seq.last().second) {
                seq.add(candidates[nxt])
                nxt++
            }
            if (seq.size > best.size) best = seq
            idx = nxt
        }
        if (best.size < 2) return emptyList()
        return best.map { it.first }
    }

    /** 把行内编号列表按编号切成多行；没有编号列表时原样返回。 */
    fun normalizeNumberedList(s: String): String {
        val starts = findStarts(s)
        if (starts.isEmpty()) return s

        val segments = mutableListOf<String>()
        for (idx in starts.indices) {
            val end = if (idx + 1 < starts.size) starts[idx + 1] else s.length
            segments.add(s.substring(starts[idx], end))
        }

        // 前言与首个编号项合并，避免"你可以这样做：1. ..."只发一个冒号
        val lead = s.substring(0, starts.first())
        val leadStripped = lead.trim()
        val leadHasNewline = lead.trimEnd(' ', '\t').endsWith("\n")
        val mergeLead = leadStripped.isNotEmpty() && !leadHasNewline && (
            leadStripped.length <= LEAD_MERGE_LIMIT || LEAD_MERGE_ENDINGS.any { leadStripped.endsWith(it) }
            )

        if (leadStripped.isNotEmpty()) {
            if (mergeLead) {
                val gap = if (lead.isNotEmpty() && lead.last().isWhitespace()) "" else " "
                segments[0] = "$leadStripped$gap${segments[0]}"
            } else {
                segments.add(0, leadStripped)
            }
        }

        return segments.map { it.trim() }.filter { it.isNotEmpty() }.joinToString("\n")
    }
}
