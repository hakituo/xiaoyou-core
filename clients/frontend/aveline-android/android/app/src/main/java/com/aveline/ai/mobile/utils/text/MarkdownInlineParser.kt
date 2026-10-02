package com.aveline.ai.mobile.utils.text

/**
 * 行内 Markdown 节点。
 *
 * 文本样式与数学公式先解析成结构化节点，再由 Compose 渲染；避免把普通文本、粗体和
 * AndroidView 公式拆成 Row 的多个 child，导致后续长文本只能拿到剩余宽度。
 */
internal sealed interface MarkdownInlineNode {
    data class Text(
        val text: String,
        val bold: Boolean = false,
        val italic: Boolean = false,
        val strike: Boolean = false,
    ) : MarkdownInlineNode

    data class Math(val formula: String) : MarkdownInlineNode
}

/** 轻量行内 Markdown / LaTeX 解析器。 */
internal object MarkdownInlineParser {

    /**
     * 支持 `**粗体**`、`*斜体*`、`~~删除线~~`、`$...$`、`$$...$$` 和反斜杠转义。
     *
     * 整行以 `$$` 开头/结尾的块级公式由 [MarkdownBlockParser] 优先处理；但列表项、标题、表格 cell
     * 里的 `$$F=ma$$` 只能在这里兜住，否则会原样显示两个美元符号。
     * 对 `$20，另一个是 $30` 这类明显的货币/自然语言片段不会误判成公式。
     */
    fun parse(text: String): List<MarkdownInlineNode> {
        if (text.isEmpty()) return emptyList()

        val result = mutableListOf<MarkdownInlineNode>()
        val buffer = StringBuilder()
        var bold = false
        var italic = false
        var strike = false
        var index = 0

        fun flushText() {
            if (buffer.isEmpty()) return
            appendTextNode(result, buffer.toString(), bold, italic, strike)
            buffer.clear()
        }

        while (index < text.length) {
            val ch = text[index]

            if (ch == '\\' && index + 1 < text.length && text[index + 1] in ESCAPABLE_CHARS) {
                buffer.append(text[index + 1])
                index += 2
                continue
            }

            if (text.startsWith("**", index)) {
                // 已在粗体内时当前 delimiter 就是闭合标记；未进入粗体时必须先确认后面还有闭合标记。
                if (bold || hasClosingDelimiter(text, "**", index + 2)) {
                    flushText()
                    bold = !bold
                    index += 2
                    continue
                }
                // 没有闭合的 `**` 只是正文里的星号，一次吞掉两个会让后面的单星号配对错位。
                buffer.append(ch)
                index++
                continue
            }

            if (ch == '*') {
                // 单星号按 CommonMark 的 flank 规则判定：开标记右侧不能是空白、闭标记左侧不能是空白，
                // 否则 `2 * 3 * 4`、`注意 *` 这类正文会被整段斜体。
                val canOpen = index + 1 < text.length &&
                    !text[index + 1].isWhitespace() &&
                    hasClosingAsterisk(text, index + 1)
                if (italic || canOpen) {
                    flushText()
                    italic = !italic
                    index++
                    continue
                }
            }

            if (text.startsWith("~~", index)) {
                // 删除线与粗体使用相同的开闭状态规则，避免闭合 delimiter 被当成正文。
                if (strike || hasClosingDelimiter(text, "~~", index + 2)) {
                    flushText()
                    strike = !strike
                    index += 2
                    continue
                }
            }

            if (ch == '$') {
                if (text.startsWith("$$", index)) {
                    // 列表项/标题/表格里的块级公式：同一行内能找到收尾 `$$` 就渲染成公式，
                    // 找不到（流式输出只到了一半）时退化成原样文本，避免半截公式闪成乱码。
                    val blockClosing = findClosingDoubleDollar(text, index + 2)
                    if (blockClosing >= 0) {
                        val blockFormula = text.substring(index + 2, blockClosing).trim()
                        if (blockFormula.isNotEmpty() && looksLikeInlineMath(blockFormula)) {
                            flushText()
                            result += MarkdownInlineNode.Math(blockFormula)
                            index = blockClosing + 2
                            continue
                        }
                    }
                    buffer.append("$$")
                    index += 2
                    continue
                }

                val closing = findClosingMathDelimiter(text, index + 1)
                if (closing >= 0) {
                    val formula = text.substring(index + 1, closing).trim()
                    if (looksLikeInlineMath(formula)) {
                        flushText()
                        result += MarkdownInlineNode.Math(formula)
                        index = closing + 1
                        continue
                    }
                }
            }

            buffer.append(ch)
            index++
        }

        flushText()
        return result
    }

    private fun appendTextNode(
        result: MutableList<MarkdownInlineNode>,
        text: String,
        bold: Boolean,
        italic: Boolean,
        strike: Boolean,
    ) {
        if (text.isEmpty()) return
        val last = result.lastOrNull()
        if (last is MarkdownInlineNode.Text &&
            last.bold == bold &&
            last.italic == italic &&
            last.strike == strike
        ) {
            result[result.lastIndex] = last.copy(text = last.text + text)
        } else {
            result += MarkdownInlineNode.Text(
                text = text,
                bold = bold,
                italic = italic,
                strike = strike,
            )
        }
    }

    /**
     * 单星号的闭合标记。
     *
     * 左侧必须是非空白字符（CommonMark 右 flank 规则），且左右都不能紧贴另一个星号——否则
     * `2 * 3 * 4` 会被整段斜体，`*说明 **重点** 结束` 里加粗的定界符也会被斜体抢走。
     */
    private fun hasClosingAsterisk(text: String, start: Int): Boolean {
        var cursor = start
        while (cursor < text.length) {
            val found = text.indexOf('*', startIndex = cursor)
            if (found < 0) return false
            val leftOk = found > 0 && !text[found - 1].isWhitespace() && text[found - 1] != '*'
            val rightOk = found + 1 >= text.length || text[found + 1] != '*'
            if (!isEscaped(text, found) && leftOk && rightOk) return true
            cursor = found + 1
        }
        return false
    }

    private fun findClosingDoubleDollar(text: String, start: Int): Int {
        var cursor = start
        while (cursor <= text.length - 2) {
            val found = text.indexOf("$$", startIndex = cursor)
            if (found < 0) return -1
            if (!isEscaped(text, found)) return found
            cursor = found + 2
        }
        return -1
    }

    private fun hasClosingDelimiter(text: String, delimiter: String, start: Int): Boolean {
        var cursor = start
        while (cursor <= text.length - delimiter.length) {
            val found = text.indexOf(delimiter, startIndex = cursor)
            if (found < 0) return false
            if (!isEscaped(text, found)) return true
            cursor = found + delimiter.length
        }
        return false
    }

    private fun findClosingMathDelimiter(text: String, start: Int): Int {
        var cursor = start
        while (cursor < text.length) {
            val found = text.indexOf('$', startIndex = cursor)
            if (found < 0) return -1
            if (!isEscaped(text, found) && !text.startsWith("$$", found)) return found
            cursor = found + if (text.startsWith("$$", found)) 2 else 1
        }
        return -1
    }

    private fun isEscaped(text: String, index: Int): Boolean {
        var slashCount = 0
        var cursor = index - 1
        while (cursor >= 0 && text[cursor] == '\\') {
            slashCount++
            cursor--
        }
        return slashCount % 2 == 1
    }

    /**
     * 只拒绝明显是自然语言/货币误配的内容，不限制正常 LaTeX。
     *
     * 有 LaTeX 命令、运算符、上下标等数学信号时直接接受；单个紧凑 token（如 x、20、E_k）也接受。
     * 含中日韩自然语言或中文标点而又没有数学信号时拒绝，避免两个货币 `$` 被跨句配对。
     */
    private fun looksLikeInlineMath(formula: String): Boolean {
        if (formula.isBlank() || '\n' in formula || '\r' in formula) return false

        val hasMathSignal = formula.any { it in MATH_SIGNAL_CHARS } || '\\' in formula
        if (hasMathSignal) return true

        val hasCjk = formula.any { ch ->
            ch.code in 0x3400..0x9FFF ||
                ch.code in 0x3040..0x30FF ||
                ch.code in 0xAC00..0xD7AF
        }
        if (hasCjk || formula.any { it in CJK_PUNCTUATION }) return false

        if (formula.none { it.isWhitespace() }) return true

        // 纯自然语言单词被两个美元符号夹住时更像价格说明，而不是公式。
        val words = formula.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
        return words.all { token ->
            token.length == 1 || token.any { it.isDigit() } || token.any { it in MATH_SIGNAL_CHARS }
        }
    }

    private val ESCAPABLE_CHARS = setOf('$', '*', '~', '\\')
    private val MATH_SIGNAL_CHARS = setOf(
        '=', '+', '-', '*', '/', '^', '_', '{', '}', '[', ']', '(', ')',
        '<', '>', '|', '&', '%', '#', ':', ';', ',', '.',
    )
    private val CJK_PUNCTUATION = setOf('，', '。', '！', '？', '；', '：', '、', '“', '”', '‘', '’')
}
