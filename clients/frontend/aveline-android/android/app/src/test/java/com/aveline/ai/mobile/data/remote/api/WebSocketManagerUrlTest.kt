package com.aveline.ai.mobile.data.remote.api

import org.junit.Test
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse

/**
 * WebSocketManager.normalizeWsScheme 的回归测试。
 *
 * 覆盖历史 bug：旧实现用 replaceFirst("^http", "ws") 做字面量匹配，
 * 导致带 http(s):// 前缀的 URL 没有被正确转换成 ws(s)://，最终拼成
 * "wss://http://host" 的畸形 URL，OkHttp 解析后 host 被当成 "http"，
 * 真正的 "//host:port/api/v1/ws" 全部落入 path，服务端收到畸形 path
 * 匹配不到 /api/v1/ws 路由，落入静态文件挂载点被拒（403）。
 */
class WebSocketManagerUrlTest {

    @Test
    fun `http 前缀转 ws`() {
        assertEquals(
            "ws://192.0.2.1:8000",
            WebSocketManager.normalizeWsScheme("http://192.0.2.1:8000")
        )
    }

    @Test
    fun `https 前缀转 wss`() {
        assertEquals(
            "wss://tunnel.example.com",
            WebSocketManager.normalizeWsScheme("https://tunnel.example.com")
        )
    }

    @Test
    fun `https 前缀带端口转 wss`() {
        assertEquals(
            "wss://tunnel.example.com:8443",
            WebSocketManager.normalizeWsScheme("https://tunnel.example.com:8443")
        )
    }

    @Test
    fun `ws 前缀保持不变`() {
        assertEquals(
            "ws://192.0.2.1:8000",
            WebSocketManager.normalizeWsScheme("ws://192.0.2.1:8000")
        )
    }

    @Test
    fun `wss 前缀保持不变`() {
        assertEquals(
            "wss://tunnel.example.com",
            WebSocketManager.normalizeWsScheme("wss://tunnel.example.com")
        )
    }

    @Test
    fun `无协议头补 wss`() {
        assertEquals(
            "wss://192.0.2.1:8000",
            WebSocketManager.normalizeWsScheme("192.0.2.1:8000")
        )
    }

    @Test
    fun `无协议头域名补 wss`() {
        assertEquals(
            "wss://xxx.trycloudflare.com",
            WebSocketManager.normalizeWsScheme("xxx.trycloudflare.com")
        )
    }

    @Test
    fun `协议相对写法去掉前导斜杠`() {
        assertEquals(
            "wss://192.0.2.1:8000",
            WebSocketManager.normalizeWsScheme("//192.0.2.1:8000")
        )
    }

    /**
     * 关键回归测试：确保不会产生 "wss://http://host" 这种畸形 URL。
     * 这正是 403 bug 的根因。
     */
    @Test
    fun `http 前缀不会产生畸形 wss 拼接`() {
        val result = WebSocketManager.normalizeWsScheme("http://192.0.2.1:8000")
        assertFalse("结果不应包含 'http://' 残留: $result", result.contains("http://"))
        assertFalse("结果不应是畸形 wss://http://: $result", result.startsWith("wss://http"))
    }

    @Test
    fun `https 前缀不会产生畸形 wss 拼接`() {
        val result = WebSocketManager.normalizeWsScheme("https://tunnel.example.com")
        assertFalse("结果不应包含 'https://' 残留: $result", result.contains("https://"))
        assertFalse("结果不应是畸形 wss://https://: $result", result.startsWith("wss://https"))
    }

    /**
     * 验证修复后 URL 能被 OkHttp 正确解析出 host 段（而非把 host 当 path）。
     * 这里用 java.net.URI 模拟 OkHttp 的解析：合法的 ws(s):// URL 的 host 应为实际 IP/域名。
     */
    @Test
    fun `修复后 URL 的 host 段可被正确解析`() {
        val cases = listOf(
            "http://192.0.2.1:8000" to "192.0.2.1",
            "https://tunnel.example.com" to "tunnel.example.com",
            "192.0.2.1:8000" to "192.0.2.1"
        )
        for ((input, expectedHost) in cases) {
            val wsUrl = WebSocketManager.normalizeWsScheme(input)
            // 补全 path 以便构造合法 ws(s) URL
            val fullUrl = wsUrl.trimEnd('/') + "/api/v1/ws"
            val uri = java.net.URI(fullUrl)
            assertEquals("input=$input → wsUrl=$wsUrl → host 解析错误", expectedHost, uri.host)
            assertEquals("input=$input → path 解析错误", "/api/v1/ws", uri.path)
        }
    }
}
