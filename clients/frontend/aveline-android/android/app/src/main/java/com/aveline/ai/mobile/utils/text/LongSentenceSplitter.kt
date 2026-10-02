package com.aveline.ai.mobile.utils.text

/**
 * 强制长句分割：句子超过阈值且没有可用的标点断点时，按长度硬切。
 *
 * 对应 Python 端 `core/utils/text_segmenter.py` 的 `force_split_long_sentence`。
 * 优先在 [maxLen] 字附近的最近标点处折断，最终分段数不超过 [maxChunks]。
 */
object LongSentenceSplitter {

    private val FORCE_SPLIT_PUNCT =
        charArrayOf(',', '，', ' ', '\u3000', '.', '。', ';', '；', '!', '！', '?', '？')

    fun forceSplitLongSentence(s: String, maxLen: Int = 100, maxChunks: Int = 7): List<String> {
        if (s.length <= maxLen) return listOf(s)
        val result = mutableListOf<String>()
        var position = 0
        while (position < s.length) {
            val remaining = s.length - position
            if (remaining <= maxLen) {
                if (remaining > 0) result.add(s.substring(position).trim())
                break
            }
            var targetEnd = position + maxLen
            if (targetEnd >= s.length) targetEnd = s.length

            var splitFound = false
            // 先往前找：在 [maxLen/2, maxLen] 区间内取最近的标点
            for (i in (targetEnd - 1) downTo (maxOf(position + maxLen / 2, position) + 1)) {
                if (s[i] in FORCE_SPLIT_PUNCT) {
                    val chunk = s.substring(position, i + 1).trim()
                    if (chunk.isNotEmpty()) result.add(chunk)
                    position = i + 1
                    splitFound = true
                    break
                }
            }
            // 再往后找：标点刚好落在断点附近时放宽 20 字
            if (!splitFound) {
                for (i in targetEnd until minOf(targetEnd + 20, s.length)) {
                    if (s[i] in FORCE_SPLIT_PUNCT) {
                        val chunk = s.substring(position, i + 1).trim()
                        if (chunk.isNotEmpty()) result.add(chunk)
                        position = i + 1
                        splitFound = true
                        break
                    }
                }
            }
            // 连标点都没有：只能硬切
            if (!splitFound) {
                val chunk = s.substring(position, targetEnd).trim()
                if (chunk.isNotEmpty()) result.add(chunk)
                position = targetEnd
            }
        }

        if (result.size > maxChunks) {
            val avgChunkSize = s.length / maxChunks
            val newResult = mutableListOf<String>()
            var currentChunk = ""
            for (chunk in result) {
                if (currentChunk.length + chunk.length <= avgChunkSize + 20) {
                    currentChunk += chunk
                } else {
                    if (currentChunk.isNotEmpty()) newResult.add(currentChunk.trim())
                    currentChunk = chunk
                }
            }
            if (currentChunk.isNotEmpty()) newResult.add(currentChunk.trim())
            result.clear()
            if (newResult.size <= maxChunks) {
                result.addAll(newResult)
            } else {
                // 等长切分兜底（Python 版此处 len//maxChunks 为 0 会抛错，这里保证步长 >= 1）
                val step = maxOf(1, s.length / maxChunks)
                var i = 0
                while (i < s.length) {
                    val chunk = s.substring(i, minOf(i + step, s.length)).trim()
                    if (chunk.isNotEmpty()) result.add(chunk)
                    i += step
                }
            }
        }

        return if (result.isEmpty()) listOf(s) else result
    }
}
