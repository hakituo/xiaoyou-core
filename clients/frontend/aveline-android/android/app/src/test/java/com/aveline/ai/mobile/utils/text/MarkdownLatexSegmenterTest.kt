package com.aveline.ai.mobile.utils.text

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 块级 LaTeX 在展示层的保护。
 *
 * 这里断言的是「公式本身必须完整落在同一个消息段里」，而不是「整条回复必须是一个
 * 消息段」——后者是旧的全有全无守卫，会让正文也跟着挤成一个大气泡（断句时好时坏的
 * 根因）。改成按行分组后，公式前后的正文照常各成一个气泡，公式块仍是完整的一段。
 */
class MarkdownLatexSegmenterTest {

    @Test
    fun `多行块公式不会被拆散且前后正文各自成段`() {
        val source = "胡克定律是\n\n\$\$\nF=-kx\n\$\$\n\n负号表示方向相反"

        assertEquals(
            listOf("胡克定律是", "\$\$\nF=-kx\n\$\$", "负号表示方向相反"),
            TextSegmenter.splitForDisplay(source)
        )
    }

    @Test
    fun `流式阶段只有起始双美元时公式段仍保持完整`() {
        val source = "下面开始推导\n\$\$\nF=-k"

        assertEquals(
            listOf("下面开始推导", "\$\$\nF=-k"),
            TextSegmenter.splitForDisplay(source)
        )
    }

    @Test
    fun `单行块公式单独成段不被切开`() {
        val source = "结果：\n\$\$E=mc^2\$\$\n继续说明"

        assertEquals(
            listOf("结果：", "\$\$E=mc^2\$\$", "继续说明"),
            TextSegmenter.splitForDisplay(source)
        )
    }
}
