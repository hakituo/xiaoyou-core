package com.aveline.ai.mobile.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PlanMarkdownCodecTest {

    @Test
    fun `历史 skipped checkbox 不会解析成已完成`() {
        val item = PlanMarkdownCodec.parse("- [x] 09:00 英语复习（60分钟） ⏭️").single()

        assertFalse(item.isDone)
    }

    @Test
    fun `completed checkbox 仍解析成已完成`() {
        val item = PlanMarkdownCodec.parse("- [x] 09:00 英语复习（60分钟） ✅").single()

        assertTrue(item.isDone)
    }

    @Test
    fun `行尾状态标记不进入名称,时长仍能解析`() {
        val item = PlanMarkdownCodec.parse("- [x] 09:00 英语复习（60分钟） ✅").single()

        assertEquals("09:00", item.time)
        assertEquals("英语复习", item.content)
        assertEquals("60分钟", item.duration)
    }

    @Test
    fun `进行中标记解析成未完成且名称干净`() {
        val item = PlanMarkdownCodec.parse("- [~] 19:00 复习数学（第1章） 🔄").single()

        assertFalse(item.isDone)
        assertEquals("19:00", item.time)
        assertEquals("复习数学", item.content)
    }

    @Test
    fun `灵活表示无固定时间,不再被跳过`() {
        val item = PlanMarkdownCodec.parse("- [ ] 灵活 巩固昨日重点：general（60分钟）").single()

        assertFalse(item.isDone)
        assertEquals("", item.time)
        assertEquals("巩固昨日重点：general", item.content)
        assertEquals("60分钟", item.duration)
    }

    @Test
    fun `无 checkbox 的行仍可解析`() {
        val item = PlanMarkdownCodec.parse("07:30 起床+早餐 (30分钟)").single()

        assertFalse(item.isDone)
        assertEquals("07:30", item.time)
        assertEquals("起床+早餐", item.content)
        assertEquals("30分钟", item.duration)
    }

    @Test
    fun `标题与备注行不产生计划项`() {
        val text = """
            # 2026-09-11 学习生活计划

            > 傍晚 18 点复盘自动重排
        """.trimIndent()

        assertTrue(PlanMarkdownCodec.parse(text).isEmpty())
    }
}
