package com.aveline.ai.mobile.services.endpoint

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * BackendIdentityProbe 的回归测试。
 *
 * 覆盖历史 bug：两个探测调用点都写着「只读响应体前 1024 字符判断身份」，
 * 而 `/api/v1/health` 的 payload 顺序是 status → services（一整坨服务明细）→ metrics
 * → timestamp → service("AI Agent Core")，服务标识实际落在 1000 字符之后
 * （实测真实响应：总长 5470 字节，marker 偏移 1058）。
 * 结果所有候选地址一律被判「不可达」：设置页重新检测永远提示所有候选不可达、
 * 开流量切公网要靠兜底且很慢、回家后完全切不回局域网。
 */
class BackendIdentityProbeTest {

    /** 构造一个与真实响应同构的 payload：服务标识被挤到 [markerIndex] 之后。 */
    private fun buildHealthPayload(markerIndex: Int): String {
        val head = """{"status":"healthy","services":{"immune_system":{"status":"healthy","details":{""""
        val tail = """"}},"service":"AI Agent Core","version_tag":"v_debug_1"}"""
        val fillerLength = (markerIndex - head.length).coerceAtLeast(0)
        return head + "x".repeat(fillerLength) + tail
    }

    @Test
    fun `服务标识落在前 1024 字符之后仍能识别`() {
        val payload = buildHealthPayload(markerIndex = 1058)
        // 先把「marker 确实在 1024 之后」这件事钉住：这正是旧实现必然失败的区间
        assertTrue(
            "用例前提不成立：marker 应在 1024 字符之后",
            payload.indexOf(BackendIdentityProbe.HEALTH_MARKER) > 1024
        )
        assertTrue(
            "marker 在 1024 字符之后时也必须能识别（旧实现就是这里失败）",
            BackendIdentityProbe.containsMarkerInChunks(sequenceOf(payload).asSequence())
        )
    }

    @Test
    fun `响应体很大时也能识别`() {
        val payload = buildHealthPayload(markerIndex = 200_000)
        assertTrue(BackendIdentityProbe.containsMarkerInChunks(sequenceOf(payload).asSequence()))
    }

    @Test
    fun `服务标识被分块边界切开时仍能识别`() {
        val marker = BackendIdentityProbe.HEALTH_MARKER
        val splitAt = 6
        val left = "a".repeat(4096) + marker.substring(0, splitAt)
        val right = marker.substring(splitAt) + "b".repeat(32)
        assertTrue(
            "跨块边界也必须命中，否则分块读取会漏判",
            BackendIdentityProbe.containsMarkerInChunks(sequenceOf(left, right))
        )
    }

    @Test
    fun `不含服务标识的响应判为 false`() {
        assertFalse(
            BackendIdentityProbe.containsMarkerInChunks(
                sequenceOf("""{"status":"healthy","services":{},"metrics":{}}""")
            )
        )
    }

    @Test
    fun `空响应判为 false`() {
        assertFalse(BackendIdentityProbe.containsMarkerInChunks(emptySequence()))
        assertFalse(BackendIdentityProbe.containsMarkerInChunks(sequenceOf("")))
    }

    @Test
    fun `服务标识字符串本身就是判据`() {
        // 后端 routers/v1/health.py 的 payload 里 "service" 字段值；
        // 改动后端该字段时必须同步这里，否则客户端会认不出自家后端。
        assertTrue(BackendIdentityProbe.HEALTH_MARKER.isNotBlank())
        assertTrue(BackendIdentityProbe.containsMarkerInChunks(sequenceOf(BackendIdentityProbe.HEALTH_MARKER)))
    }
}
