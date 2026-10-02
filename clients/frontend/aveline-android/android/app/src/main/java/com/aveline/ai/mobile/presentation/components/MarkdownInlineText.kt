package com.aveline.ai.mobile.presentation.components

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.text.InlineTextContent
import androidx.compose.foundation.text.appendInlineContent
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.Placeholder
import androidx.compose.ui.text.PlaceholderVerticalAlign
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.em
import com.aveline.ai.mobile.utils.text.MarkdownInlineNode

/**
 * 单一 Compose Text 布局中的 Markdown 行内富文本。
 *
 * 普通文本、粗体、斜体、删除线都写入同一个 [AnnotatedString]；LaTeX 使用 [InlineTextContent]
 * 占位并嵌入 [LatexMath]。这样公式前后的长文本仍由同一个 paragraph 负责换行，不再出现
 * `Row + 多个 Text/AndroidView child` 导致的剩余宽度竖排问题。
 */
@Composable
internal fun MarkdownInlineText(
    nodes: List<MarkdownInlineNode>,
    style: TextStyle,
    color: Color,
    modifier: Modifier = Modifier,
) {
    val layout = remember(nodes) { buildInlineLayout(nodes) }
    Text(
        text = layout.text,
        inlineContent = layout.inlineContent,
        style = style,
        color = color,
        modifier = modifier,
    )
}

private data class InlineLayout(
    val text: AnnotatedString,
    val inlineContent: Map<String, InlineTextContent>,
)

private fun buildInlineLayout(nodes: List<MarkdownInlineNode>): InlineLayout {
    val content = linkedMapOf<String, InlineTextContent>()
    var mathIndex = 0

    val annotated = buildAnnotatedString {
        nodes.forEach { node ->
            when (node) {
                is MarkdownInlineNode.Text -> {
                    val span = SpanStyle(
                        fontWeight = if (node.bold) FontWeight.Bold else null,
                        fontStyle = if (node.italic) FontStyle.Italic else null,
                        textDecoration = if (node.strike) TextDecoration.LineThrough else null,
                    )
                    withStyle(span) { append(node.text) }
                }

                is MarkdownInlineNode.Math -> {
                    val id = "inline-math-${mathIndex++}"
                    appendInlineContent(id = id, alternateText = "${'$'}${node.formula}${'$'}")
                    content[id] = InlineTextContent(
                        placeholder = Placeholder(
                            width = estimateMathWidthEm(node.formula).em,
                            height = estimateMathHeightEm(node.formula).em,
                            placeholderVerticalAlign = PlaceholderVerticalAlign.TextCenter,
                        ),
                    ) {
                        LatexMath(
                            formula = node.formula,
                            displayMode = false,
                            modifier = Modifier.fillMaxSize(),
                        )
                    }
                }
            }
        }
    }

    return InlineLayout(text = annotated, inlineContent = content)
}

/**
 * MTMathView 需要在 Text 排版前拿到占位尺寸。这里按公式可见复杂度给出保守估算，
 * 让常见高中公式在行内完整显示；特别长的公式应由模型使用 $$ 块级公式输出。
 */
private fun estimateMathWidthEm(formula: String): Float {
    val simplified = formula
        .replace(Regex("\\\\[A-Za-z]+"), "M")
        .replace("{", "")
        .replace("}", "")
    return (simplified.length * 0.62f + 0.8f).coerceIn(1.2f, 18f)
}

private fun estimateMathHeightEm(formula: String): Float {
    val tall = TALL_MATH_MARKERS.any(formula::contains)
    return if (tall) 2.0f else 1.45f
}

private val TALL_MATH_MARKERS = listOf(
    "\\frac",
    "\\sum",
    "\\prod",
    "\\int",
    "\\begin",
    "^",
    "_",
)
