package com.aveline.ai.mobile.services

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * TTSState.Paused 回归测试
 *
 * 重点验证 P0-2 修复:Paused 状态新增 duration 字段后,
 * UI 应能正确计算 0-1 进度,而不是错误地用 position/1000f。
 *
 * 修复前: TTSComponents 用 `state.position / 1000f`,
 *   若 position 是毫秒,结果是秒数(可能 >1),进度条显示错误。
 * 修复后: Paused 加 duration 字段, UI 用 `position / duration` 得到 0-1 进度。
 */
class TTSStatePausedTest {

    @Test
    fun `Paused 默认 duration 为 0`() {
        val paused = TTSState.Paused(messageId = "msg-1", position = 5000)
        assertEquals(0, paused.duration)
        assertEquals(5000, paused.position)
        assertEquals("msg-1", paused.messageId)
    }

    @Test
    fun `Paused 可指定 duration`() {
        val paused = TTSState.Paused(messageId = "msg-1", position = 5000, duration = 20000)
        assertEquals(20000, paused.duration)
        assertEquals(5000, paused.position)
    }

    @Test
    fun `进度计算 - 中途暂停应得到正确比例`() {
        // 模拟 UI 计算逻辑:position/duration
        val paused = TTSState.Paused(messageId = "msg-1", position = 5000, duration = 20000)
        val progress = if (paused.duration > 0) {
            paused.position.toFloat() / paused.duration
        } else 0f
        assertEquals(0.25f, progress, 0.001f)
    }

    @Test
    fun `进度计算 - duration 为 0 时回退 0 不除零`() {
        val paused = TTSState.Paused(messageId = "msg-1", position = 5000, duration = 0)
        val progress = if (paused.duration > 0) {
            paused.position.toFloat() / paused.duration
        } else 0f
        assertEquals(0f, progress, 0.001f)
    }

    @Test
    fun `进度计算 - 暂停在末尾应得到接近 1`() {
        val paused = TTSState.Paused(messageId = "msg-1", position = 19900, duration = 20000)
        val progress = if (paused.duration > 0) {
            paused.position.toFloat() / paused.duration
        } else 0f
        assertEquals(0.995f, progress, 0.001f)
    }

    @Test
    fun `修复前的错误算法会得到错误结果`() {
        // 文档化修复前的 bug:position/1000f 把毫秒当秒数
        // 5000ms / 1000 = 5.0,远大于 1,进度条会溢出显示
        val paused = TTSState.Paused(messageId = "msg-1", position = 5000, duration = 20000)
        val buggyProgress = paused.position.toFloat() / 1000f
        // 修复前结果是 5.0,远超 1.0,UI 显示错误
        assertEquals(5.0f, buggyProgress, 0.001f)
        // 修复后正确结果是 0.25
        val correctProgress = if (paused.duration > 0) {
            paused.position.toFloat() / paused.duration
        } else 0f
        assertEquals(0.25f, correctProgress, 0.001f)
    }
}
