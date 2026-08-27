package com.aveline.ai.mobile.services

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * ReplayGuard 重放防护单元测试。
 *
 * 验证: 同一 id 时间窗内去重、不同 id 正常放行、空 id 兜底、超过时间窗后允许再次通过、
 * 有界淘汰(超容量最旧记录被淘汰) 以及 clear() 复位。
 */
class ReplayGuardTest {

    @Test
    fun `首次到达的 id 判定为非重放, 并正常记录`() {
        val guard = ReplayGuard()
        assertFalse(guard.isReplay("cmd-1", nowMs = 1000))
    }

    @Test
    fun `同一 id 在时间窗内重复到达判定为重放`() {
        val guard = ReplayGuard()
        guard.isReplay("cmd-1", nowMs = 1000)
        assertTrue(guard.isReplay("cmd-1", nowMs = 2000))
        assertTrue(guard.isReplay("cmd-1", nowMs = 3000))
    }

    @Test
    fun `不同 id 互不影响`() {
        val guard = ReplayGuard()
        guard.isReplay("cmd-1", nowMs = 1000)
        assertFalse(guard.isReplay("cmd-2", nowMs = 1000))
    }

    @Test
    fun `超过时间窗后旧 id 允许再次通过`() {
        // 时间窗 5 分钟
        val guard = ReplayGuard(windowMs = 5 * 60 * 1000L)
        guard.isReplay("cmd-1", nowMs = 1000)
        // 超过 5 分钟后, 旧记录已过期, 应重新放行
        assertFalse(guard.isReplay("cmd-1", nowMs = 1000 + 5 * 60 * 1000L + 1))
    }

    @Test
    fun `空 id 一律放行, 不做记录`() {
        val guard = ReplayGuard()
        assertFalse(guard.isReplay(""))
        assertFalse(guard.isReplay("   "))
    }

    @Test
    fun `超过容量最旧记录被淘汰`() {
        val guard = ReplayGuard(maxSize = 3)
        guard.isReplay("a", nowMs = 1000)
        guard.isReplay("b", nowMs = 2000)
        guard.isReplay("c", nowMs = 3000)
        guard.isReplay("d", nowMs = 4000) // 触发淘汰最旧的 "a"
        // "a" 已被淘汰, 同窗口内再次到达应放行(非重放)
        assertFalse(guard.isReplay("a", nowMs = 5000))
    }

    @Test
    fun `clear 后所有 id 重置为非重放`() {
        val guard = ReplayGuard()
        guard.isReplay("cmd-1", nowMs = 1000)
        guard.clear()
        assertFalse(guard.isReplay("cmd-1", nowMs = 2000))
    }
}