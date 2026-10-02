package com.aveline.ai.mobile.utils

/**
 * 后端地址的静态判定规则：把一个地址字符串归类成「局域网 / 组网 / 公网」。
 *
 * 为什么要收敛成唯一实现：这套判据原先散在三处各写一份 —— `EndpointResolver` 的运行时
 * 物理兜底、`AppPreferences` 的槽位迁移、以及 `isLanOnlyHost` 的同类判断。任何一处改了
 * 判据，另外几处就会静默失效。最典型的是「Tailscale 的 `100.64.0.0/10` 段不算局域网」
 * 这条：漏掉一处，出门时就会把生效地址从组网强制切走，或让「组网优先于公网」的排序失效。
 *
 * 纯字符串函数，无 Android 依赖，可直接跑 JVM 单测（见 `BackendAddressRulesTest`）。
 */
internal object BackendAddressRules {

    /**
     * 取出 host 部分：去掉协议头、路径、端口，统一小写。空/非法地址返回空串。
     *
     * **先 lowercase 再去协议头**，顺序不能反：`removePrefix` 是大小写敏感的，
     * 反过来的话 `HTTPS://Host/x` 会在第一个 `/` 处截成 `HTTPS:`，最后得到 "https" 这种
     * 假 host —— 既不是私网也不是组网，被静默归成公网。
     */
    fun hostOf(raw: String): String = raw.trim()
        .lowercase()
        .removePrefix("https://")
        .removePrefix("http://")
        .substringBefore('/')
        .substringBefore(':')

    /**
     * 地址是否**只在局域网内才有意义**（私网 IPv4 / localhost / `.local`）。
     *
     * 用途是运行时的物理兜底：只要判定「私网地址 + 当前走蜂窝」，就可以断定这条链路
     * 物理上不通，不必再等探测结果。
     *
     * 域名（哪怕是内网 DNS）一律返回 false —— 它在蜂窝下也可能解析成功。
     */
    fun isLanOnlyHost(raw: String): Boolean {
        val host = hostOf(raw)
        if (host.isEmpty()) return false
        if (host == "localhost" || host.endsWith(".local")) return true

        val octets = ipv4Octets(host) ?: return false
        return octets[0] == 10 ||
            (octets[0] == 172 && octets[1] in 16..31) ||
            (octets[0] == 192 && octets[1] == 168)
    }

    /**
     * 地址是否属于**点对点组网段**（Tailscale / WireGuard 常用的 CGNAT `100.64.0.0/10`）。
     *
     * 这一段必须与私网判据分开，两个方向的误判都有害：
     * - 判成私网 → 「蜂窝 + 私网地址就强制降级」的兜底会把组网地址一起切走；
     * - 判成公网 → 「出门时组网优先于公网域名」的排序失去依据，组网槽位永远排在公网后面。
     *
     * 它外观像内网但在蜂窝下可达，所以既不能进局域网候选，也不能当普通公网地址。
     */
    fun isVpnHost(raw: String): Boolean {
        val octets = ipv4Octets(hostOf(raw)) ?: return false
        return octets[0] == 100 && octets[1] in 64..127
    }

    /** 解析成四段 IPv4；不是合法点分十进制（含域名）返回 null。 */
    private fun ipv4Octets(host: String): List<Int>? {
        if (host.isEmpty()) return null
        val octets = host.split('.').map { it.toIntOrNull() ?: return null }
        if (octets.size != 4 || octets.any { it !in 0..255 }) return null
        return octets
    }
}
