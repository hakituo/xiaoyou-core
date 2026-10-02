package com.aveline.ai.mobile.services.discovery

/**
 * UDP 信标载荷的解析（纯函数，可直接跑 JVM 单测）。
 *
 * 格式与后端 `core/services/discovery/udp_beacon.py` 的 `build_message()` 是一对**线上契约**，
 * 两侧必须同步：
 * ```
 * AVELINE_SERVER|<局域网地址>[|<组网地址>]
 * ```
 * 后端侧的拼装由 `tests/unit/test_discovery_udp_beacon.py` 钉住，这里钉住解析。
 *
 * 之所以单独成文件：解析逻辑原本混在 `ServerDiscoveryManager` 里，而那个类需要 Context，
 * 在 host 单测里构造不出来 —— 契约型代码恰恰是最该被单测钉住的。
 */
internal object BeaconPayload {

    /** 载荷首段标识，用于把本项目信标与端口上其他 UDP 流量区分开。 */
    const val MAGIC = "AVELINE_SERVER"

    /** 字段下标：0 = magic，1 = 局域网地址，2 = 组网地址（可选）。 */
    private const val FIELD_LAN_URL = 1
    private const val FIELD_VPN_URL = 2

    /** 一次解析结果：局域网地址 + 可选的组网地址。 */
    data class Beacon(val lanUrl: String, val vpnUrl: String?)

    /**
     * 解析一条信标载荷。不是本项目信标、或局域网地址不合法时返回 null。
     *
     * 组网地址缺失 / 格式非法时只把该字段置空，不整条丢弃：局域网地址是必需的，
     * 组网地址是加分项，不能因为后端没启用组网就放弃这次发现。
     */
    fun parse(message: String): Beacon? {
        if (!message.startsWith(MAGIC)) return null
        val parts = message.split("|")
        val lanUrl = parts.getOrNull(FIELD_LAN_URL)?.trim().orEmpty()
        if (!isValidServerUrl(lanUrl)) return null
        val vpnUrl = parts.getOrNull(FIELD_VPN_URL)?.trim()?.takeIf { isValidServerUrl(it) }
        return Beacon(lanUrl, vpnUrl)
    }

    /** 只接受带协议头的绝对地址：后续会直接拿它当 baseUrl 拼请求。 */
    private fun isValidServerUrl(url: String): Boolean =
        url.startsWith("http://") || url.startsWith("https://")
}
