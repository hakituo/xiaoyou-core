package com.aveline.ai.mobile.services.endpoint.resolver

/**
 * 候选通道的排序判据。
 *
 * 纯函数、无 Android 依赖，可直接跑 JVM 单测 —— 这些判据原本藏在门面的私有方法里，
 * 只能靠真机验证，而它们决定的是「后台定时器要不要发探测请求」这种耗电行为。
 *
 * 候选优先级（见 `EndpointResolver.resolve()`）：
 * 手动锁定 > 局域网（仅 WiFi / 以太网）> 组网 > 公网域名。
 */
internal object ChannelPriority {

    /**
     * 当前通道之外，还有没有「更优、且在当前网络下有可能可用」的候选。
     *
     * 只做省电的前置判断，不改变裁决顺序：判 true 时仍走完整探测，探不通就保持原通道。
     * 判 false 的三种情况 —— 手动锁定（用户指定的地址不该被后台改掉）、
     * 局域网（它已是最高优先级）、组网且没回家（组网已是当前最优的远程通道）。
     */
    fun hasBetterCandidate(
        current: EndpointChannel,
        lanTransport: Boolean,
        lanUrl: String,
        vpnUrl: String,
        tunnelUrl: String
    ): Boolean = when (current) {
        // 用户强制指定的地址不该被后台任务悄悄改掉
        EndpointChannel.MANUAL -> false
        // 局域网是最高优先级：还连得上就没必要探；出门了（lanTransport=false）才值得重选
        EndpointChannel.LAN -> !lanTransport && (vpnUrl.isNotEmpty() || tunnelUrl.isNotEmpty())
        // 组网已是最优远程通道，唯一值得试的是「回家后切回局域网」
        EndpointChannel.VPN -> lanTransport && lanUrl.isNotEmpty()
        // 公网是最低优先级：上面任何一条可用都该升上去
        EndpointChannel.TUNNEL -> (lanTransport && lanUrl.isNotEmpty()) || vpnUrl.isNotEmpty()
        // 进程刚起、还没裁决过，值得探一次
        EndpointChannel.NONE -> true
    }
}
