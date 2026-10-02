package com.aveline.ai.mobile.utils.text

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 覆盖 [TextSegmenter]：它必须与 QQ 端（`core/utils/text_segmenter.py`）行为一致，
 * 期望值直接取 Python 版同一批用例的输出，
 * 两端常量是否漂移由 `tests/scripts/android_frontend/verify_text_segmenter_parity.py` 兜底。
 */
class TextSegmenterTest {

    @Test
    fun `剥掉模型模仿历史格式输出的时间戳`() {
        assertEquals("前面后面", TextSegmenter.stripAiTimestamp("前面[09-11 23:40] 后面"))
        assertEquals("好呀", TextSegmenter.stripAiTimestamp("[09-11 23:40] 好呀"))
        assertEquals("没有时间戳", TextSegmenter.stripAiTimestamp("没有时间戳"))
    }

    @Test
    fun `清掉句末多余标点但保留句中标点`() {
        assertEquals("好呀好呀", TextSegmenter.stripTrailingPunctuation("好呀好呀。"))
        assertEquals("好呀好呀", TextSegmenter.stripTrailingPunctuation("好呀好呀，"))
        assertEquals("噢噢，好呀好呀", TextSegmenter.stripTrailingPunctuation("噢噢，好呀好呀，"))
        assertEquals("（摸了摸头）", TextSegmenter.stripTrailingPunctuation("（摸了摸头。）"))
    }

    @Test
    fun `展示前清洗同时剥时间戳与句末句号`() {
        assertEquals("好呀", TextSegmenter.clean("[09-11 23:40] 好呀。"))
    }

    @Test
    fun `极短句在句号处断句且不保留句号`() {
        assertEquals(
            listOf("啊", "我忘了"),
            TextSegmenter.splitMessage("啊。我忘了", commaSplitProb = 0.0)
        )
    }

    @Test
    fun `省略号后接普通句子时在省略号处断句`() {
        assertEquals(
            listOf("倒是你，声音听起来有点飘……", "是困了，还是有心事？"),
            TextSegmenter.splitMessage(
                "倒是你，声音听起来有点飘……是困了，还是有心事？",
                commaSplitProb = 0.0
            )
        )
    }

    @Test
    fun `换行是硬气泡边界且括号内舞台描写单独成泡`() {
        val chunks = TextSegmenter.splitMessage(
            "（轻笑一声）\n我这边一切正常。倒是你，刚才说焦虑……现在感觉好点了吗？",
            commaSplitProb = 0.0
        )
        assertEquals(4, chunks.size)
        assertEquals("（轻笑一声）", chunks[0])
        assertEquals("我这边一切正常", chunks[1])
        assertEquals("现在感觉好点了吗？", chunks[3])
    }

    @Test
    fun `短句不拆且方括号标记整段直返`() {
        assertEquals(
            listOf("你好啊，今天天气不错。"),
            TextSegmenter.splitMessage("你好啊，今天天气不错。", commaSplitProb = 0.0)
        )
        assertEquals(
            listOf("[THINK_STORE: 他需要燃料]"),
            TextSegmenter.splitMessage("[THINK_STORE: 他需要燃料]", commaSplitProb = 0.0)
        )
    }

    @Test
    fun `方括号内逗号加空格不断句`() {
        // 数学区间 [1, 3] 是英文排版习惯（逗号后带空格），
        // 不能被"逗号+空格=用户主动分泡"的显式边界规则误断成 [1 / 3]
        val interval = "1. 已知 f(x) = x^2 - 2ax + 3 在区间 [1, 3] 上的最小值为 g(a)，求 g(a)"
        assertEquals(listOf(interval), TextSegmenter.splitForDisplay(interval))
        assertEquals(
            listOf("集合 {1, 2, 3} 的并集"),
            TextSegmenter.splitForDisplay("集合 {1, 2, 3} 的并集")
        )
    }

    @Test
    fun `跨行连续的 Markdown 结构整组保留不被拆散`() {
        val code = "```kotlin\nval a = 1\nval b = 2\n```"
        assertEquals(listOf(code), TextSegmenter.splitForDisplay(code))

        val math = "$$\nE = mc^2\n$$"
        assertEquals(listOf(math), TextSegmenter.splitForDisplay(math))

        val table = "| 列一 | 列二 |\n| --- | --- |\n| a | b |"
        assertEquals(listOf(table), TextSegmenter.splitForDisplay(table))
    }

    @Test
    fun `单行块级标记只保住自己那一行不再拖累整条消息`() {
        // 回归用例：旧实现命中任一 markdown 标记就整条透传，模型这一轮只要用了 `- `
        // 列表，整条回复就退化成一个大气泡、换行原样显示；同一套措辞没用 markdown 时
        // 却又被正常切成多个气泡——"一会能断句一会不能断句"就是这么来的。
        assertEquals(
            listOf("## 标题", "第一行", "第二行"),
            TextSegmenter.splitForDisplay("## 标题\n\n第一行。\n\n第二行。")
        )
        assertEquals(
            listOf("你看这两点", "- 莲 → 主语", "- 出淤泥而不染 → 谓语"),
            TextSegmenter.splitForDisplay("你看这两点。\n- 莲 → 主语\n- 出淤泥而不染 → 谓语")
        )
    }

    @Test
    fun `加粗里自带句号时不把星号拆到两个气泡`() {
        // 旧行为：切成 "**古之人 / 不 / 余 / 欺" + "** 顺便…"，两段各剩一个 `**`，
        // 渲染时星号落单、原样显示出来。
        val text =
            "所以整句主语就是「古之人」这三个字，一个整体： **古之人 / 不 / 余 / 欺。** 顺便给你一个判断顺序，以后见到「之」先过一遍："
        val segments = TextSegmenter.splitForDisplay(text)
        segments.forEach { segment ->
            val starPairs = segment.split("**").size - 1
            assertEquals(0, starPairs % 2, "段落里出现落单的 **：$segment")
        }
        assertTrue(segments.joinToString("").contains("**古之人 / 不 / 余 / 欺**"))
    }

    @Test
    fun `普通聊天回复会拆成多个气泡并去掉句末句号`() {
        val segments = TextSegmenter.splitForDisplay("好呀。那你早点睡吧。晚安哦。")
        assertEquals(3, segments.size)
        assertEquals("好呀", segments[0])
        assertEquals("晚安哦", segments[2])
    }

    @Test
    fun `每个气泡都要去掉句末句号而不只是最后一段`() {
        // 断句只在断点处吃掉句号：某段只产出 1 块时会原样返回带句号的原文。
        // QQ 是断句后对每条消息单独 strip，安卓端必须同样处理，
        // 否则气泡里会残留"你要求的。"这类句末句号。
        val segments = TextSegmenter.splitForDisplay("你要求的。\n\n以前那套我也没打算收着，是你嫌吵。")
        assertEquals(2, segments.size)
        assertEquals("你要求的", segments[0])
        assertEquals("以前那套我也没打算收着，是你嫌吵", segments[1])
    }
}
