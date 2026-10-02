package com.aveline.ai.mobile.services.endpoint.resolver

import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * 网络变化监听：把「链路变化」翻译成「该重探了」。
 *
 * 事件来源有三层，缺一层都会漏掉真实场景：
 *
 * 1. **默认网络回调**（[ConnectivityManager.registerDefaultNetworkCallback]）：
 *    可用 / 能力变化 / 丢失。只留 onAvailable 会漏掉两类 —— `onCapabilitiesChanged`
 *    覆盖「默认网络对象没换、但链路类型变了」（WiFi ↔ 蜂窝的交接、WiFi 连上却没有
 *    Internet 校验），只盯 onAvailable 时蜂窝因为早就 available 过、切过去可能不再回调；
 *    `onLost` 覆盖「默认网络没了」，要么新网络马上接管（被去抖合并），要么就此断网。
 *
 * 2. **物理链路回调**（请求式，见 [registerPhysicalLinkCallback]）：只看默认网络会漏掉
 *    一整类切换 —— 开着 Tailscale 时默认网络恒为那条 VPN 网络、transport 恒为 `other`，
 *    底层 WiFi ↔ 蜂窝 的交接被第 1 层的去重挡掉，通道永远不重选。
 *
 * 3. **周期重探**：以上都是「事件」，而「组网从不可用变成可用」（Tailscale 连上、
 *    打洞完成）不产生任何 ConnectivityManager 回调。少了这个定时器，一次「组网还没就绪
 *    就探失败」的抖动就会让用户整个外出期间挂在公网域名上：公网一直好用 → WebSocket
 *    不失败 → 失败降级探测也不会被调用。
 *
 * @param onResolve 触发一次完整裁决（由门面提供，内部已串行化）
 * @param onPeriodicTick 周期到点时的回调；门面在里面先做省电判断，再决定要不要真探测
 */
internal class NetworkWatcher(
    private val scope: CoroutineScope,
    private val inspector: NetworkTransportInspector,
    private val periodicReprobeIntervalMs: Long,
    private val onResolve: suspend (trigger: String) -> Unit,
    private val onPeriodicTick: suspend () -> Unit
) {

    /** 去抖任务：新事件到来时取消上一个，把连发的事件合并成一次探测。 */
    private var debounceJob: Job? = null
    private var periodicJob: Job? = null
    private var defaultCallback: ConnectivityManager.NetworkCallback? = null
    private var linkCallback: ConnectivityManager.NetworkCallback? = null

    /**
     * 上一次观察到的传输类型（wifi / cellular / ...），用于默认网络回调的去重。
     *
     * `onCapabilitiesChanged` 在信号强度、链路带宽变化时就会触发，不做去重会把探测打成高频任务。
     * 只用于第 1 层：第 2 层的物理链路回调不需要去重（可用 / 丢失本身就是离散事件）。
     */
    @Volatile
    private var lastTransport: String? = null

    /** 开始监听。幂等，重复调用无副作用。 */
    fun start() {
        if (defaultCallback != null) return
        val cm = inspector.connectivityManager()
        if (cm == null) {
            Log.w(TAG, "拿不到 ConnectivityManager，网络变化自动重探测不可用")
            return
        }
        registerDefaultNetworkCallback(cm)
        registerPhysicalLinkCallback(cm)
        startPeriodicReprobe()
    }

    /** 第 1 层：默认网络（含 VPN 网络）的变化。 */
    private fun registerDefaultNetworkCallback(cm: ConnectivityManager) {
        lastTransport = inspector.transportOf(cm.getNetworkCapabilities(cm.activeNetwork))
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                Log.d(TAG, "默认网络可用，安排重探测")
                schedule("网络变化")
            }

            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                val transport = inspector.transportOf(caps)
                if (transport == lastTransport) return
                Log.d(TAG, "传输类型变化: $lastTransport -> $transport")
                lastTransport = transport
                schedule("网络类型变化")
            }

            override fun onLost(network: Network) {
                lastTransport = null
                Log.d(TAG, "默认网络丢失，安排重探测")
                schedule("网络丢失", LOST_DEBOUNCE_MS)
            }
        }
        try {
            cm.registerDefaultNetworkCallback(callback)
            defaultCallback = callback
            Log.i(TAG, "已开始监听默认网络变化")
        } catch (e: Exception) {
            Log.w(TAG, "注册默认网络回调失败: ${e.message}")
        }
    }

    /**
     * 第 2 层：物理链路（WiFi / 蜂窝 / 以太网）的可用与丢失。
     *
     * 为什么必须单独注册一层：开着 Tailscale 时默认网络是那条 VPN 网络，它一直存在、
     * transport 一直是 `other`，底层链路换掉了也不会让 [registerDefaultNetworkCallback]
     * 的 transport 去重放行。而「出门时 WiFi 掉了、切蜂窝」正是最需要重选通道的时刻 ——
     * 漏掉它就只能等 WebSocket 连接失败后的失败降级，慢且要多绕一次重连。
     *
     * 请求式回调只关心物理链路本身，不受「谁是默认网络」影响，注册时会对当前已匹配的
     * 网络各回调一次 onAvailable（等效于一次启动探测，与第 1 层的回调被去抖合并）。
     */
    private fun registerPhysicalLinkCallback(cm: ConnectivityManager) {
        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .addTransportType(NetworkCapabilities.TRANSPORT_CELLULAR)
            .addTransportType(NetworkCapabilities.TRANSPORT_ETHERNET)
            .build()
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                Log.d(TAG, "物理链路可用，安排重探测")
                schedule("底层链路变化")
            }

            override fun onLost(network: Network) {
                Log.d(TAG, "物理链路丢失，安排重探测")
                schedule("底层链路丢失", LOST_DEBOUNCE_MS)
            }
        }
        try {
            cm.registerNetworkCallback(request, callback)
            linkCallback = callback
            Log.i(TAG, "已开始监听物理链路变化")
        } catch (e: Exception) {
            Log.w(TAG, "注册物理链路回调失败: ${e.message}")
        }
    }

    /**
     * 第 3 层：周期重探。
     *
     * 只在 [onPeriodicTick] 内部判断过「有更优候选」时才真的发探测请求，
     * 所以这里可以放心按固定间隔空转。
     */
    private fun startPeriodicReprobe() {
        if (periodicJob?.isActive == true) return
        periodicJob = scope.launch {
            while (isActive) {
                delay(periodicReprobeIntervalMs)
                onPeriodicTick()
            }
        }
    }

    /**
     * 去抖后触发一次探测。
     *
     * onAvailable 在切换瞬间常连续回调多次，立刻探测容易撞上「路由/DNS 还没就绪」
     * 的窗口拿到假失败；等一小段再探更准。串行化由门面的 resolveMutex 保证。
     */
    private fun schedule(trigger: String, debounceMs: Long = DEFAULT_DEBOUNCE_MS) {
        debounceJob?.cancel()
        debounceJob = scope.launch {
            delay(debounceMs)
            onResolve(trigger)
        }
    }

    companion object {
        private const val TAG = "NetworkWatcher"

        /** 网络变化后的去抖时长。 */
        const val DEFAULT_DEBOUNCE_MS = 600L

        /** 「链路丢失」后的去抖：比网络变化短，新网络通常已经在同一时刻接管。 */
        const val LOST_DEBOUNCE_MS = 300L
    }
}
