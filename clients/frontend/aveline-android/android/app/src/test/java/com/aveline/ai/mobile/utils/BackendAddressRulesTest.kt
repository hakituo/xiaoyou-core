package com.aveline.ai.mobile.utils

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * BackendAddressRules 的回归测试：地址分类是「通道裁决」与「槽位迁移」共用的判据。
 *
 * 三类地址必须互不混淆，判错方向的代价各不相同：
 * - 组网地址（CGNAT `100.64.0.0/10`）误判成私网 → 蜂窝下「私网地址就强制降级」的兜底
 *   会把生效地址从组网切走；误判成公网 → 「出门时组网优先于公网」的排序失去依据；
 * - 私网地址漏判 → 回到「开了流量切不过去」的老问题；
 * - 公网域名误判成私网 → 在家 WiFi 下被强行切走，属严重误伤。
 */
class BackendAddressRulesTest {

    @Test
    fun `Tailscale 组网段判定为组网地址`() {
        // 100.64.0.0/10 的完整边界：100.64.0.0 ~ 100.127.255.255
        listOf(
            "http://100.64.0.1:8000",
            "http://100.64.0.1:8000",
            "http://100.127.255.254:8000",
            "http://100.64.0.0:8000",
            "https://100.127.255.255",
            "100.64.0.1:8000",
            "http://100.64.0.1:8000/api/v1"
        ).forEach { url ->
            assertTrue("$url 应被判定为组网地址", BackendAddressRules.isVpnHost(url))
        }
    }

    @Test
    fun `组网段之外的 100 段地址不判定为组网`() {
        // 100.64.0.0/10 之外仍属公网，判成组网会让槽位迁移把公网地址塞进组网槽位
        listOf(
            "http://100.63.255.255:8000",
            "http://100.128.0.0:8000",
            "http://100.0.0.1:8000",
            "http://100.255.255.255:8000"
        ).forEach { url ->
            assertFalse("$url 不属于 CGNAT 组网段，不应判定为组网地址", BackendAddressRules.isVpnHost(url))
        }
    }

    @Test
    fun `私网与公网地址都不判定为组网`() {
        listOf(
            "http://192.0.2.1:8000",
            "http://10.0.0.5:8000",
            "https://ai.example.com",
            "http://8.8.8.8:8000",
            "http://localhost:8000"
        ).forEach { url ->
            assertFalse("$url 不应判定为组网地址", BackendAddressRules.isVpnHost(url))
        }
    }

    @Test
    fun `组网地址与局域网专用地址互斥`() {
        // 两条判据各自对应一条兜底分支，同时为真会让「蜂窝 + 私网 → 强制降级」
        // 把组网地址也一起切走，这是新通道最容易踩的坑
        val vpn = "http://100.64.0.1:8000"
        assertTrue(BackendAddressRules.isVpnHost(vpn))
        assertFalse(BackendAddressRules.isLanOnlyHost(vpn))
    }

    @Test
    fun `局域网专用判据与运行时兜底保持一致`() {
        listOf(
            "http://192.0.2.1:8000",
            "http://10.0.0.5:8000",
            "http://172.16.0.1:8000",
            "http://172.31.255.254:8000",
            "http://localhost:8000",
            "http://xiaoyou.local:8000",
            "192.0.2.1:8000",
            "http://192.0.2.1:8000/api/v1"
        ).forEach { url ->
            assertTrue("$url 应被判定为局域网专用地址", BackendAddressRules.isLanOnlyHost(url))
        }
        listOf(
            "https://ai.example.com",
            "https://xxx.trycloudflare.com",
            "http://8.8.8.8:8000",
            "http://114.114.114.114",
            "http://172.15.0.1:8000",
            "http://172.32.0.1:8000",
            "http://192.169.1.1:8000",
            "http://11.0.0.1:8000",
            "http://192.168.31.256:8000",
            "http://192.168.31:8000",
            "tunnel.example.com/api/v1"
        ).forEach { url ->
            assertFalse("$url 不应被判定为局域网专用地址", BackendAddressRules.isLanOnlyHost(url))
        }
    }

    @Test
    fun `空地址与非法地址对两条判据都安全返回 false`() {
        listOf("", "   ", "http://", "not a url").forEach { url ->
            assertFalse("空/非法地址不应判定为局域网专用: '$url'", BackendAddressRules.isLanOnlyHost(url))
            assertFalse("空/非法地址不应判定为组网地址: '$url'", BackendAddressRules.isVpnHost(url))
        }
    }

    @Test
    fun `hostOf 去掉协议头 路径 端口并统一小写`() {
        assertEquals("ai.example.com", BackendAddressRules.hostOf("HTTPS://Ai.Example.COM:443/api/v1"))
        assertEquals("192.0.2.1", BackendAddressRules.hostOf("  http://192.0.2.1:8000/api/v1  "))
        assertEquals("", BackendAddressRules.hostOf(""))
    }
}
