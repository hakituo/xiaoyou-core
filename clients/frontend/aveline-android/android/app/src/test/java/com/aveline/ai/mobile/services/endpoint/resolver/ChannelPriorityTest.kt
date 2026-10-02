package com.aveline.ai.mobile.services.endpoint.resolver

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [ChannelPriority] 的回归测试：它决定「后台周期定时器要不要真的发探测请求」。
 *
 * 判错方向的代价不对称：
 * - 该探却判 false → 通道卡在低优先级候选上（用户体感「开着组网却一直走公网」）；
 * - 不该探却判 true → 每 5 分钟白跑一轮探测（局域网候选必然超时，白耗电）。
 *
 * 所以每一档都要把「已经是最优」和「还有更优」两侧钉住。
 */
class ChannelPriorityTest {

    private fun hasBetter(
        current: EndpointChannel,
        lanTransport: Boolean,
        lanUrl: String = "",
        vpnUrl: String = "",
        tunnelUrl: String = ""
    ) = ChannelPriority.hasBetterCandidate(current, lanTransport, lanUrl, vpnUrl, tunnelUrl)

    @Test
    fun `手动锁定永不重选`() {
        // 用户明确指定的地址不该被后台任务悄悄改掉，槽位再全也不探
        assertFalse(hasBetter(EndpointChannel.MANUAL, true, "http://192.168.1.5:8000", "http://100.64.0.1:8000", "https://a.example.com"))
        assertFalse(hasBetter(EndpointChannel.MANUAL, false, "http://192.168.1.5:8000", "http://100.64.0.1:8000", "https://a.example.com"))
    }

    @Test
    fun `局域网是最高优先级 还连得上就不重选`() {
        assertFalse(hasBetter(EndpointChannel.LAN, lanTransport = true, vpnUrl = "http://100.64.0.1:8000", tunnelUrl = "https://a.example.com"))
    }

    @Test
    fun `局域网还在但链路已不是局域网 应重选`() {
        // 出门了：私网地址必然不通，只要配了远程通道就值得重选
        assertTrue(hasBetter(EndpointChannel.LAN, lanTransport = false, vpnUrl = "http://100.64.0.1:8000"))
        assertTrue(hasBetter(EndpointChannel.LAN, lanTransport = false, tunnelUrl = "https://a.example.com"))
    }

    @Test
    fun `局域网还在且没有任何远程通道 不必重选`() {
        assertFalse(hasBetter(EndpointChannel.LAN, lanTransport = false))
    }

    @Test
    fun `组网只在回家后才值得重选`() {
        // 局域网是唯一比组网更优的候选，且只有真的有局域网链路时才可能探通
        assertTrue(hasBetter(EndpointChannel.VPN, lanTransport = true, lanUrl = "http://192.168.1.5:8000"))
        assertFalse(hasBetter(EndpointChannel.VPN, lanTransport = true))
        assertFalse(hasBetter(EndpointChannel.VPN, lanTransport = false, lanUrl = "http://192.168.1.5:8000"))
    }

    @Test
    fun `公网是最低优先级 上面任何一条可用都该升上去`() {
        assertTrue(hasBetter(EndpointChannel.TUNNEL, lanTransport = true, lanUrl = "http://192.168.1.5:8000"))
        assertTrue(hasBetter(EndpointChannel.TUNNEL, lanTransport = false, vpnUrl = "http://100.64.0.1:8000"))
    }

    @Test
    fun `公网且没有更优候选时不重选`() {
        // 蜂窝 + 组网槽位空 = 已经在唯一可用通道上，再探也是白跑
        assertFalse(hasBetter(EndpointChannel.TUNNEL, lanTransport = false))
        assertFalse(hasBetter(EndpointChannel.TUNNEL, lanTransport = true))
    }

    @Test
    fun `尚未裁决时总要探一次`() {
        assertTrue(hasBetter(EndpointChannel.NONE, lanTransport = false))
        assertTrue(hasBetter(EndpointChannel.NONE, lanTransport = true))
    }
}
