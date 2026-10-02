package com.aveline.ai.mobile.services.endpoint.resolver

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities

/**
 * 链路类型判定：把一份 [NetworkCapabilities] 归成传输类型，并回答「设备现在能不能到局域网」。
 *
 * 只表达「这条网络自己是什么」与「设备有没有局域网链路」两件事，不碰候选排序，
 * 也不碰地址槽位 —— 那些是 [ChannelPriority] 与门面的事。
 */
internal class NetworkTransportInspector(private val context: Context) {

    /**
     * 把一份网络能力归成传输类型字符串。
     *
     * 蜂窝即使一直连着，只要默认网络是 WiFi，局域网候选就仍然值得优先探。
     * VPN / 蓝牙共享等一律归到 `other`：它们不是「能到局域网」的判据，
     * 但在 [NetworkWatcher] 里仍算一次传输类型变化，会触发重探。
     */
    fun transportOf(caps: NetworkCapabilities?): String {
        if (caps == null) return TRANSPORT_NONE
        return when {
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> TRANSPORT_WIFI
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> TRANSPORT_ETHERNET
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> TRANSPORT_CELLULAR
            else -> TRANSPORT_OTHER
        }
    }

    /** 给定网络的能力是不是「能到局域网」的 WiFi / 以太网。 */
    fun isLanTransport(caps: NetworkCapabilities?): Boolean {
        val transport = transportOf(caps)
        return transport == TRANSPORT_WIFI || transport == TRANSPORT_ETHERNET
    }

    /**
     * 当前设备有没有可能访问局域网后端（WiFi / 有线；只有蜂窝一律认为没有）。
     *
     * **不能只看 activeNetwork**：手机开着 Tailscale / 任意 VPN 时，`activeNetwork` 会是
     * 那条 VPN 网络，它的 capabilities 只有 `TRANSPORT_VPN`，[transportOf] 落到
     * `TRANSPORT_OTHER` → 只盯着默认网络的话会判成「没有局域网链路」，
     * 结果是**人在家里 WiFi 下、却绕走远程通道**（组网或公网域名）。
     * 这在加了组网槽位后从「无所谓」变成「天天发生」：Tailscale 是常开的。
     *
     * 所以先看默认网络（绝大多数情况一步出结果），没命中再遍历 [ConnectivityManager.getAllNetworks]
     * 把底层的 WiFi / 以太网找回来 —— VPN 并不会让底层网络消失，它只是不再当默认网络。
     *
     * 反过来也成立：蜂窝 + VPN 时 allNetworks 里只有 CELLULAR 和 VPN，没有 WiFi，
     * 仍然判 false，出门该走远程通道还是走远程通道。
     *
     * 判 true 不等于局域网一定通（比如 WiFi 连着但没过 captive portal 校验），
     * 但局域网探测只有 800ms 超时，误判的代价远小于漏判。
     */
    fun hasLanTransport(): Boolean {
        val cm = connectivityManager() ?: return false
        if (isLanTransport(cm.getNetworkCapabilities(cm.activeNetwork))) return true
        return runCatching { cm.allNetworks }
            .getOrNull()
            ?.any { isLanTransport(cm.getNetworkCapabilities(it)) }
            ?: false
    }

    /** 取 ConnectivityManager；拿不到返回 null（权限缺失或系统服务异常）。 */
    fun connectivityManager(): ConnectivityManager? = context.applicationContext
        .getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager

    companion object {
        const val TRANSPORT_WIFI = "wifi"
        const val TRANSPORT_ETHERNET = "ethernet"
        const val TRANSPORT_CELLULAR = "cellular"
        const val TRANSPORT_OTHER = "other"
        const val TRANSPORT_NONE = "none"
    }
}
