package com.aveline.ai.mobile.utils.text

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MarkdownBlockParserTest {

    @Test
    fun `多行块公式保持为一个数学块`() {
        val blocks = MarkdownBlockParser.parse(
            "胡克定律是\n\n\$\$\nF=-kx\n\$\$\n\n负号表示方向相反",
        )

        val math = blocks.filterIsInstance<MarkdownBlock.Math>()
        assertEquals(1, math.size)
        assertEquals("F=-kx", math.single().formula)
    }

    @Test
    fun `单行双美元公式直接识别为块公式`() {
        val blocks = MarkdownBlockParser.parse("\$\$E=mc^2\$\$")

        assertEquals(listOf(MarkdownBlock.Math("E=mc^2")), blocks)
    }

    @Test
    fun `代码块里的双美元符号永远只是代码`() {
        val blocks = MarkdownBlockParser.parse("```text\n\$\$\nhello\n\$\$\n```")

        val code = blocks.single() as MarkdownBlock.Code
        assertEquals("text", code.language)
        assertEquals("\$\$\nhello\n\$\$", code.code)
        assertFalse(blocks.any { it is MarkdownBlock.Math })
    }

    @Test
    fun `GFM带冒号对齐分隔行不会变成数据`() {
        val blocks = MarkdownBlockParser.parse(
            "| 量 | 公式 |\n|:---|---:|\n| 力 | \$F=ma\$ |",
        )

        val table = blocks.single() as MarkdownBlock.Table
        assertEquals(2, table.rows.size)
        assertEquals(2, table.rows[0].size)
        assertTrue(table.rows[1][1].any { it == MarkdownInlineNode.Math("F=ma") })
    }

    @Test
    fun `标题里的粗体和公式进入统一行内节点`() {
        val blocks = MarkdownBlockParser.parse("## **动能** \$E_k=mv^2/2\$")

        val heading = blocks.single() as MarkdownBlock.Heading
        assertEquals(2, heading.level)
        assertTrue(heading.content.filterIsInstance<MarkdownInlineNode.Text>().any { it.bold && it.text == "动能" })
        assertTrue(heading.content.any { it == MarkdownInlineNode.Math("E_k=mv^2/2") })
    }

    @Test
    fun `子项里的单星号斜体进入行内节点`() {
        val blocks = MarkdownBlockParser.parse("- 这一步*很关键*，别跳过")

        val bullet = blocks.single() as MarkdownBlock.Bullet
        assertTrue(
            bullet.content.filterIsInstance<MarkdownInlineNode.Text>()
                .any { it.italic && it.text == "很关键" },
        )
    }

    @Test
    fun `子项里的块级公式渲染为数学节点而不是字面美元符号`() {
        val blocks = MarkdownBlockParser.parse(
            "- 胡克定律：\$\$F=-kx\$\$\n- 弹性势能：\$E_p=kx^2/2\$",
        )

        val bullets = blocks.filterIsInstance<MarkdownBlock.Bullet>()
        assertEquals(2, bullets.size)
        assertTrue(bullets[0].content.any { it == MarkdownInlineNode.Math("F=-kx") })
        assertTrue(bullets[1].content.any { it == MarkdownInlineNode.Math("E_p=kx^2/2") })
    }

    @Test
    fun `标准表格分隔单元格识别冒号与横线`() {
        assertTrue(MarkdownBlockParser.isTableSeparatorRow(listOf(":---", "---:", ":---:")))
        assertFalse(MarkdownBlockParser.isTableSeparatorRow(listOf("---", "data")))
    }
}
