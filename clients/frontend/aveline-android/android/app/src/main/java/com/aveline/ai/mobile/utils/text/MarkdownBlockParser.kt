package com.aveline.ai.mobile.utils.text

/** 预解析后的 Markdown 块；Compose 只消费结构，不在每次重组时重新扫描全文。 */
internal sealed interface MarkdownBlock {
    data object Blank : MarkdownBlock
    data object Divider : MarkdownBlock

    data class Paragraph(val content: List<MarkdownInlineNode>) : MarkdownBlock
    data class Heading(val level: Int, val content: List<MarkdownInlineNode>) : MarkdownBlock
    data class Bullet(val content: List<MarkdownInlineNode>) : MarkdownBlock
    data class Quote(val depth: Int, val content: List<MarkdownInlineNode>) : MarkdownBlock
    data class Code(val language: String, val code: String) : MarkdownBlock
    data class Math(val formula: String) : MarkdownBlock
    data class Table(val rows: List<List<List<MarkdownInlineNode>>>) : MarkdownBlock
}

/**
 * 聊天/笔记共用的块级 Markdown + LaTeX 解析器。
 *
 * 状态机优先级固定为 fenced code > math block > table/heading/list/quote/paragraph，确保代码块中的
 * `$$` 永远只是代码文本。`$$E=mc^2$$` 与多行 `$$ ... $$` 都会生成 [MarkdownBlock.Math]。
 */
internal object MarkdownBlockParser {

    fun parse(text: String): List<MarkdownBlock> {
        if (text.isEmpty()) return emptyList()

        val blocks = mutableListOf<MarkdownBlock>()
        val tableLines = mutableListOf<String>()
        val codeLines = mutableListOf<String>()
        val mathLines = mutableListOf<String>()

        var codeFence: String? = null
        var codeLanguage = ""
        var inMathBlock = false

        fun flushTable() {
            if (tableLines.isEmpty()) return
            parseTable(tableLines)?.let(blocks::add)
            tableLines.clear()
        }

        text.lines().forEach { line ->
            val trimmed = line.trim()

            // 代码块状态优先级最高：代码内部的 $$、表格、标题等都必须原样保留。
            val activeFence = codeFence
            if (activeFence != null) {
                if (trimmed.startsWith(activeFence)) {
                    blocks += MarkdownBlock.Code(
                        language = codeLanguage,
                        code = codeLines.joinToString("\n"),
                    )
                    codeLines.clear()
                    codeFence = null
                    codeLanguage = ""
                } else {
                    codeLines += line
                }
                return@forEach
            }

            if (inMathBlock) {
                if (trimmed == "$$") {
                    blocks += MarkdownBlock.Math(mathLines.joinToString("\n").trim())
                    mathLines.clear()
                    inMathBlock = false
                } else {
                    mathLines += line
                }
                return@forEach
            }

            val fence = detectFence(trimmed)
            if (fence != null) {
                flushTable()
                codeFence = fence
                codeLanguage = trimmed.removePrefix(fence).trim()
                return@forEach
            }

            val singleLineMath = parseSingleLineMath(trimmed)
            if (singleLineMath != null) {
                flushTable()
                blocks += MarkdownBlock.Math(singleLineMath)
                return@forEach
            }

            if (trimmed == "$$") {
                flushTable()
                inMathBlock = true
                return@forEach
            }

            if (isTableLine(trimmed)) {
                tableLines += trimmed
                return@forEach
            }
            flushTable()

            val heading = parseHeading(trimmed)
            val quote = parseQuote(trimmed)
            val bullet = parseBullet(trimmed)
            when {
                trimmed.isEmpty() -> blocks += MarkdownBlock.Blank
                isDivider(trimmed) -> blocks += MarkdownBlock.Divider
                heading != null -> blocks += heading
                quote != null -> blocks += quote
                bullet != null -> blocks += bullet
                else -> blocks += MarkdownBlock.Paragraph(MarkdownInlineParser.parse(trimmed))
            }
        }

        flushTable()

        // 流式输出时可能暂时没有闭合 fence；已有内容继续按对应块展示，避免跳回普通文本。
        if (codeFence != null) {
            blocks += MarkdownBlock.Code(
                language = codeLanguage,
                code = codeLines.joinToString("\n"),
            )
        }
        if (inMathBlock) {
            if (mathLines.isEmpty()) {
                blocks += MarkdownBlock.Paragraph(MarkdownInlineParser.parse("$$"))
            } else {
                blocks += MarkdownBlock.Math(mathLines.joinToString("\n").trim())
            }
        }

        return blocks
    }

    private fun detectFence(trimmed: String): String? = when {
        trimmed.startsWith("```") -> "```"
        trimmed.startsWith("~~~") -> "~~~"
        else -> null
    }

    private fun parseSingleLineMath(trimmed: String): String? {
        if (trimmed.length <= 4 || !trimmed.startsWith("$$") || !trimmed.endsWith("$$")) return null
        val formula = trimmed.substring(2, trimmed.length - 2).trim()
        return formula.takeIf { it.isNotEmpty() }
    }

    private fun isTableLine(trimmed: String): Boolean =
        trimmed.length >= 2 && trimmed.startsWith('|') && trimmed.endsWith('|')

    private fun parseTable(lines: List<String>): MarkdownBlock.Table? {
        val parsedRows = lines.map(::parseTableCells)
        val dataRows = parsedRows.filterNot(::isTableSeparatorRow)
        if (dataRows.isEmpty()) return null
        return MarkdownBlock.Table(
            rows = dataRows.map { row -> row.map { cell -> MarkdownInlineParser.parse(cell) } },
        )
    }

    private fun parseTableCells(row: String): List<String> = row
        .trim()
        .removePrefix("|")
        .removeSuffix("|")
        .split('|')
        .map { it.trim() }

    internal fun isTableSeparatorRow(cells: List<String>): Boolean =
        cells.isNotEmpty() && cells.all { cell -> TABLE_SEPARATOR_CELL.matches(cell) }

    private fun parseHeading(trimmed: String): MarkdownBlock.Heading? {
        val match = HEADING_REGEX.matchEntire(trimmed) ?: return null
        return MarkdownBlock.Heading(
            level = match.groupValues[1].length,
            content = MarkdownInlineParser.parse(match.groupValues[2].trim()),
        )
    }

    private fun parseBullet(trimmed: String): MarkdownBlock.Bullet? {
        val match = BULLET_REGEX.matchEntire(trimmed) ?: return null
        return MarkdownBlock.Bullet(MarkdownInlineParser.parse(match.groupValues[1].trim()))
    }

    private fun parseQuote(trimmed: String): MarkdownBlock.Quote? {
        if (!trimmed.startsWith('>')) return null

        var cursor = 0
        var depth = 0
        while (cursor < trimmed.length) {
            while (cursor < trimmed.length && trimmed[cursor].isWhitespace()) cursor++
            if (cursor >= trimmed.length || trimmed[cursor] != '>') break
            depth++
            cursor++
        }
        if (depth == 0) return null
        return MarkdownBlock.Quote(
            depth = depth,
            content = MarkdownInlineParser.parse(trimmed.substring(cursor).trim()),
        )
    }

    private fun isDivider(trimmed: String): Boolean = DIVIDER_REGEX.matches(trimmed)

    private val HEADING_REGEX = Regex("^(#{1,6})\\s+(.+)$")
    private val BULLET_REGEX = Regex("^[-*+]\\s+(.+)$")
    private val DIVIDER_REGEX = Regex("^(?:-{3,}|\\*{3,}|_{3,})$")
    private val TABLE_SEPARATOR_CELL = Regex("^:?-{3,}:?$")
}
