package com.aveline.ai.mobile.utils.text

/**
 * 分段合并：断句之后把不自然的断点合回去，并控制气泡数量。
 *
 * 对应 Python 端 `core/utils/text_segmenter.py` 的
 * `merge_chunks_to_limit` / `merge_continuation_chunks` / `merge_space_chunks_to_limit` /
 * `looks_like_manual_space_split`。
 */
object ChunkMerger {

    /** 合并分段以确保不超过 [maxChunks] 条，按"合并后最短"的相邻段优先。 */
    fun mergeChunksToLimit(chunks: List<String>, maxChunks: Int = 7): List<String> {
        if (chunks.size <= maxChunks) return chunks
        val result = chunks.toMutableList()
        val neededMerges = result.size - maxChunks
        repeat(neededMerges) {
            var minLen = Int.MAX_VALUE
            var mergeIdx = -1
            for (i in 0 until result.size - 1) {
                val combined = result[i].length + result[i + 1].length
                if (combined < minLen) {
                    minLen = combined
                    mergeIdx = i
                }
            }
            if (mergeIdx < 0) return@repeat
            result[mergeIdx] = result[mergeIdx] + result[mergeIdx + 1]
            result.removeAt(mergeIdx + 1)
        }
        return result
    }

    /**
     * 合并不自然的断点：
     * 1. 下一段以续接词（"而且/但是/然后..."）开头，且上一段较短 → 合并
     * 2. 上一段以未完标点（冒号、破折号）结尾 → 合并下一段
     */
    fun mergeContinuationChunks(
        chunks: List<String>,
        maxMergeLen: Int = 300,
        minSplitLen: Int = 40,
    ): List<String> {
        if (chunks.size <= 1) return chunks
        val result = mutableListOf(chunks.first())
        for (i in 1 until chunks.size) {
            val prev = result.last()
            val curr = chunks[i]
            val currStripped = curr.trim()
            val prevStripped = prev.trim()

            var shouldMerge = false
            if (ContinuationWords.isContinuationStart(currStripped)) {
                val prevEndsWithSentPunct = prevStripped.isNotEmpty() &&
                    TextSegmentRules.EXPLICIT_SPACE_BOUNDARY_ENDINGS.any { prevStripped.endsWith(it) }
                if (!prevEndsWithSentPunct && prevStripped.length < minSplitLen) shouldMerge = true
            }
            if (prevStripped.isNotEmpty() && TextSegmentRules.CONTINUATION_ENDINGS.any { prevStripped.endsWith(it) }) {
                shouldMerge = true
            }

            if (shouldMerge && prev.length + curr.length <= maxMergeLen) {
                result[result.lastIndex] = prev + curr
            } else {
                result.add(curr)
            }
        }
        return result
    }

    /** 判断一段无标点文本是否像"人工用空格分泡泡"的短语串。 */
    fun looksLikeManualSpaceSplit(text: String): Boolean {
        val normalized = text.trim()
        if (normalized.isEmpty() || normalized.contains('\n')) return false
        if (normalized.any { it in TextSegmentRules.PUNCTUATION_FOR_SPACE_GUARD }) return false

        val parts = normalized.split(TextSegmentRules.WHITESPACE_REGEX).map { it.trim() }.filter { it.isNotEmpty() }
        if (parts.size < 3) return false

        val cjkCount = TextSegmentRules.CJK_REGEX.findAll(normalized).count()
        if (cjkCount < maxOf(6, normalized.replace(" ", "").length / 3)) return false
        if (parts.any { it.length > 12 }) return false

        val avgLen = parts.sumOf { it.length }.toDouble() / maxOf(1, parts.size)
        return avgLen <= 8
    }

    /** 按空格重新合并短语块，避免纯空格断句生成过多气泡。 */
    fun mergeSpaceChunksToLimit(chunks: List<String>, maxChunks: Int = 6): List<String> {
        val cleaned = chunks.map { it.trim() }.filter { it.isNotEmpty() }
        if (cleaned.size <= maxChunks) return cleaned
        val result = cleaned.toMutableList()
        while (result.size > maxChunks) {
            var minLen = Int.MAX_VALUE
            var mergeIdx = -1
            for (i in 0 until result.size - 1) {
                val combined = result[i].length + result[i + 1].length
                if (combined < minLen) {
                    minLen = combined
                    mergeIdx = i
                }
            }
            if (mergeIdx < 0) break
            result[mergeIdx] = "${result[mergeIdx]} ${result[mergeIdx + 1]}".trim()
            result.removeAt(mergeIdx + 1)
        }
        return result
    }
}
