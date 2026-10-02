package com.aveline.ai.mobile.utils.text

import dev.snipme.highlights.model.SyntaxLanguage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 覆盖 [CodeHighlighter]：fence 语言标记解析、无标签时的启发式识别、
 * 以及高亮降级（识别/着色失败时必须原样返回完整原文，渲染层不能拿到残缺文本）。
 */
class CodeHighlighterTest {

    @Test
    fun `常见 fence 语言标记映射到对应语言`() {
        assertEquals(SyntaxLanguage.PYTHON, CodeHighlighter.resolveLanguage("python", ""))
        assertEquals(SyntaxLanguage.PYTHON, CodeHighlighter.resolveLanguage("py", ""))
        assertEquals(SyntaxLanguage.JAVASCRIPT, CodeHighlighter.resolveLanguage("js", ""))
        assertEquals(SyntaxLanguage.TYPESCRIPT, CodeHighlighter.resolveLanguage("ts", ""))
        assertEquals(SyntaxLanguage.KOTLIN, CodeHighlighter.resolveLanguage("kt", ""))
        assertEquals(SyntaxLanguage.CPP, CodeHighlighter.resolveLanguage("c++", ""))
        assertEquals(SyntaxLanguage.CSHARP, CodeHighlighter.resolveLanguage("c#", ""))
        assertEquals(SyntaxLanguage.SHELL, CodeHighlighter.resolveLanguage("bash", ""))
        // JSON 是 JS 子集，按 JS 着色
        assertEquals(SyntaxLanguage.JAVASCRIPT, CodeHighlighter.resolveLanguage("json", ""))
    }

    @Test
    fun `标记大小写与空白不敏感`() {
        assertEquals(SyntaxLanguage.PYTHON, CodeHighlighter.resolveLanguage("  Python ", ""))
    }

    @Test
    fun `无标签时按特征 token 识别语言`() {
        val python = "def hello(name):\n    print(f'hi {name}')\n    return None"
        assertEquals(SyntaxLanguage.PYTHON, CodeHighlighter.resolveLanguage(null, python))
        assertEquals(SyntaxLanguage.PYTHON, CodeHighlighter.resolveLanguage("", python))

        val kotlin = "fun main() {\n    val x = 1\n    println(x)\n}"
        assertEquals(SyntaxLanguage.KOTLIN, CodeHighlighter.resolveLanguage(null, kotlin))

        val js = "const add = (a, b) => {\n  console.log(a + b)\n}"
        assertEquals(SyntaxLanguage.JAVASCRIPT, CodeHighlighter.resolveLanguage(null, js))
    }

    @Test
    fun `识别不了时回退 DEFAULT`() {
        assertEquals(SyntaxLanguage.DEFAULT, CodeHighlighter.resolveLanguage(null, ""))
        assertEquals(SyntaxLanguage.DEFAULT, CodeHighlighter.guessLanguage("   "))
    }

    @Test
    fun `展示名映射`() {
        assertEquals("Python", CodeHighlighter.displayName(SyntaxLanguage.PYTHON))
        assertEquals("C++", CodeHighlighter.displayName(SyntaxLanguage.CPP))
        assertEquals("JavaScript", CodeHighlighter.displayName(SyntaxLanguage.JAVASCRIPT))
        // DEFAULT 不显示标签
        assertEquals("", CodeHighlighter.displayName(SyntaxLanguage.DEFAULT))
    }

    @Test
    fun `高亮结果保留完整原文`() {
        val code = "def main():\n    print('hi')\n"
        val highlighted = CodeHighlighter.highlightCode(code, SyntaxLanguage.PYTHON)
        // 着色只能加 span，不能改动文本本身，否则气泡会丢字
        assertEquals(code, highlighted.text)
    }

    @Test
    fun `高亮成功时至少给关键字或结构着了色`() {
        val code = "def main():\n    print('hi')"
        val highlighted = CodeHighlighter.highlightCode(code, SyntaxLanguage.PYTHON)
        assertTrue("着色 span 不应少于 1 个", highlighted.spanStyles.isNotEmpty())
    }

    @Test
    fun `空文本不参与高亮`() {
        assertEquals(0, CodeHighlighter.highlightCode("", SyntaxLanguage.PYTHON).spanStyles.size)
    }
}
