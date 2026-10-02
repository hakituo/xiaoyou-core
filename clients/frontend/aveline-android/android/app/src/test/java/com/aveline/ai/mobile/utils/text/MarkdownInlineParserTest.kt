package com.aveline.ai.mobile.utils.text

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MarkdownInlineParserTest {

    @Test
    fun `文字和行内公式解析为独立节点但保持单段布局语义`() {
        val nodes = MarkdownInlineParser.parse("速度满足 \$v=v_0+at\$，所以如果初速度很小，后面的长文字也要正常换行")

        assertEquals(3, nodes.size)
        assertEquals(MarkdownInlineNode.Text("速度满足 "), nodes[0])
        assertEquals(MarkdownInlineNode.Math("v=v_0+at"), nodes[1])
        assertEquals(
            MarkdownInlineNode.Text("，所以如果初速度很小，后面的长文字也要正常换行"),
            nodes[2],
        )
    }

    @Test
    fun `转义美元符号不会进入数学节点`() {
        val nodes = MarkdownInlineParser.parse("价格是 \\\$20，不是公式")

        assertEquals(listOf(MarkdownInlineNode.Text("价格是 \$20，不是公式")), nodes)
        assertFalse(nodes.any { it is MarkdownInlineNode.Math })
    }

    @Test
    fun `两个货币美元符号不会跨自然语言误配成公式`() {
        val nodes = MarkdownInlineParser.parse("这个套餐 \$20，另一个是 \$30")

        assertFalse(nodes.any { it is MarkdownInlineNode.Math })
        assertEquals("这个套餐 \$20，另一个是 \$30", (nodes.single() as MarkdownInlineNode.Text).text)
    }

    @Test
    fun `粗体删除线和公式可混合解析`() {
        val nodes = MarkdownInlineParser.parse("**动能**是 \$E_k=mv^2/2\$，~~旧说法~~不用")

        assertTrue(nodes.filterIsInstance<MarkdownInlineNode.Text>().any { it.bold && it.text == "动能" })
        assertTrue(nodes.any { it == MarkdownInlineNode.Math("E_k=mv^2/2") })
        assertTrue(nodes.filterIsInstance<MarkdownInlineNode.Text>().any { it.strike && it.text == "旧说法" })
    }

    @Test
    fun `单星号解析为斜体且不影响双星号粗体`() {
        val nodes = MarkdownInlineParser.parse("这个结论*其实*是**重点**")

        val texts = nodes.filterIsInstance<MarkdownInlineNode.Text>()
        assertTrue(texts.any { it.italic && it.text == "其实" })
        assertTrue(texts.any { it.bold && it.text == "重点" })
        assertEquals("这个结论其实是重点", texts.joinToString("") { it.text })
    }

    @Test
    fun `正文里的孤立星号不会被误判成斜体`() {
        val nodes = MarkdownInlineParser.parse("长是 2 * 3 * 4，标注*")

        val texts = nodes.filterIsInstance<MarkdownInlineNode.Text>()
        assertFalse(texts.any { it.italic })
        assertEquals("长是 2 * 3 * 4，标注*", texts.joinToString("") { it.text })
    }

    @Test
    fun `单星号不会抢走加粗的定界符`() {
        val nodes = MarkdownInlineParser.parse("*说明 **重点** 结束")

        val texts = nodes.filterIsInstance<MarkdownInlineNode.Text>()
        assertFalse(texts.any { it.italic })
        assertTrue(texts.any { it.bold && it.text == "重点" })
    }

    @Test
    fun `行内双美元公式解析为数学节点而不是字面美元符号`() {
        val nodes = MarkdownInlineParser.parse("胡克定律：\$\$F=-kx\$\$，负号表示方向")

        assertTrue(nodes.any { it == MarkdownInlineNode.Math("F=-kx") })
        assertFalse(nodes.filterIsInstance<MarkdownInlineNode.Text>().any { "\$\$" in it.text })
    }

    @Test
    fun `流式输出只到一半的块级公式退化成原样文本`() {
        val nodes = MarkdownInlineParser.parse("胡克定律：\$\$F=-kx")

        assertFalse(nodes.any { it is MarkdownInlineNode.Math })
        assertEquals("胡克定律：\$\$F=-kx", (nodes.single() as MarkdownInlineNode.Text).text)
    }
}
