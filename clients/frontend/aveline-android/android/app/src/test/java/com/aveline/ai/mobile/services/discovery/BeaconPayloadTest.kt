package com.aveline.ai.mobile.services.discovery

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * [BeaconPayload] 的回归测试：它解析的是后端 UDP 信标的线上契约。
 *
 * 契约两侧必须同步 —— 后端 `core/services/discovery/udp_beacon.py` 的拼装由
 * `tests/unit/test_discovery_udp_beacon.py` 钉住，这里钉住解析。格式一旦分叉，
 * 现象是「自动发现静默失效」，日志里只看到「未发现局域网服务器」，很难定位。
 */
class BeaconPayloadTest {

    @Test
    fun `三段载荷解析出局域网与组网地址`() {
        val beacon = BeaconPayload.parse(
            "AVELINE_SERVER|http://192.0.2.1:8000|http://100.64.0.1:8000"
        )
        assertEquals("http://192.0.2.1:8000", beacon?.lanUrl)
        assertEquals("http://100.64.0.1:8000", beacon?.vpnUrl)
    }

    @Test
    fun `两段载荷只解析出局域网地址`() {
        // 老后端 / 后端未启用组网都发两段：组网地址为空，但这次发现依然有效
        val beacon = BeaconPayload.parse("AVELINE_SERVER|http://192.0.2.1:8000")
        assertEquals("http://192.0.2.1:8000", beacon?.lanUrl)
        assertNull(beacon?.vpnUrl)
    }

    @Test
    fun `组网段非法时只丢该字段 不丢整条发现`() {
        listOf("", "100.64.0.1:8000", "not a url", "   ").forEach { broken ->
            val beacon = BeaconPayload.parse("AVELINE_SERVER|http://192.0.2.1:8000|$broken")
            assertEquals("$broken: 局域网地址应仍然可用", "http://192.0.2.1:8000", beacon?.lanUrl)
            assertNull("$broken: 非法组网地址应为空", beacon?.vpnUrl)
        }
    }

    @Test
    fun `局域网段缺失或非法时整条丢弃`() {
        listOf(
            "AVELINE_SERVER",
            "AVELINE_SERVER|",
            "AVELINE_SERVER|192.0.2.1:8000",
            "AVELINE_SERVER||http://100.64.0.1:8000"
        ).forEach { payload ->
            assertNull("$payload 不应被解析出结果", BeaconPayload.parse(payload))
        }
    }

    @Test
    fun `非本项目信标一律丢弃`() {
        listOf(
            "",
            "OTHER_MAGIC|http://192.0.2.1:8000",
            "  AVELINE_SERVER|http://192.0.2.1:8000",
            "aveline_server|http://192.0.2.1:8000"
        ).forEach { payload ->
            assertNull("$payload 不应被解析出结果", BeaconPayload.parse(payload))
        }
    }

    @Test
    fun `字段两侧空白被裁掉`() {
        val beacon = BeaconPayload.parse(
            "AVELINE_SERVER| http://192.0.2.1:8000 | http://100.64.0.1:8000 "
        )
        assertEquals("http://192.0.2.1:8000", beacon?.lanUrl)
        assertEquals("http://100.64.0.1:8000", beacon?.vpnUrl)
    }

    @Test
    fun `多出的段被忽略 便于后端后续扩展`() {
        val beacon = BeaconPayload.parse(
            "AVELINE_SERVER|http://192.0.2.1:8000|http://100.64.0.1:8000|future"
        )
        assertEquals("http://192.0.2.1:8000", beacon?.lanUrl)
        assertEquals("http://100.64.0.1:8000", beacon?.vpnUrl)
    }

    @Test
    fun `https 形式的地址同样接受`() {
        val beacon = BeaconPayload.parse(
            "AVELINE_SERVER|https://lan.example.com|https://vpn.example.com"
        )
        assertEquals("https://lan.example.com", beacon?.lanUrl)
        assertEquals("https://vpn.example.com", beacon?.vpnUrl)
    }
}
