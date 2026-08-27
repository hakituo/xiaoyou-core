package com.aveline.ai.mobile.domain

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
}
