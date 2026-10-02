package com.aveline.ai.mobile.services.endpoint.resolver

/**
 * 生效地址所属的通道，用于日志、设置页展示与候选排序。
 *
 * 从 [com.aveline.ai.mobile.services.endpoint.EndpointResolver] 的嵌套类型提出来，
 * 是因为候选排序判据（[ChannelPriority]）与网络监听（[NetworkWatcher]）都要用它，
 * 留在门面里会让子模块反向依赖门面，形成环。
 */
enum class EndpointChannel {
    /** 用户手动锁定的地址 */
    MANUAL,

    /** 局域网 */
    LAN,

    /** 组网通道（Tailscale 等点对点 VPN 的 100.x 地址） */
    VPN,

    /** 公网域名（Cloudflare Tunnel） */
    TUNNEL,

    /** 尚未裁决（进程刚起、槽位为空） */
    NONE
}

/** 一次裁决的结果：生效地址 + 它属于哪条通道。 */
data class ResolvedEndpoint(val url: String, val channel: EndpointChannel)
