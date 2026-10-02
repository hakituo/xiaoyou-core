package com.aveline.ai.mobile.services.endpoint

import android.content.Context
import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.services.endpoint.resolver.ChannelPriority
import com.aveline.ai.mobile.services.endpoint.resolver.EndpointChannel
import com.aveline.ai.mobile.services.endpoint.resolver.EndpointProber
import com.aveline.ai.mobile.services.endpoint.resolver.NetworkTransportInspector
import com.aveline.ai.mobile.services.endpoint.resolver.NetworkWatcher
import com.aveline.ai.mobile.services.endpoint.resolver.ResolvedEndpoint
import com.aveline.ai.mobile.utils.BackendAddressRules
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.concurrent.atomic.AtomicLong
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 后端地址裁决器（薄壳门面）：在「局域网 / 组网 / 公网域名」之间自动选一个能用的。
 *
 * 解决的问题：后端同时监听 0.0.0.0:8000（局域网入口）、Tailscale 组网地址（点对点入口）
 * 和 Cloudflare Tunnel（公网入口），客户端不该让用户手动切换，而应
 * 「在家走局域网、出门走组网、组网不通再退公网」。
 *
 * 本类只做三件事：持有生效地址状态与广播、按优先级链裁决、对外提供触发入口。
 * 具体职责在 `resolver/` 子目录里，改哪一层就只动哪个文件：
 * - [EndpointProber]：探测某个地址是不是本项目后端；
 * - [NetworkTransportInspector]：链路类型判定（含「开 VPN 时也能找回底层 WiFi」）；
 * - [ChannelPriority]：候选排序判据（纯函数，有 host 单测）；
 * - [NetworkWatcher]：网络变化监听 + 去抖 + 周期重探；
 * - [BackendAddressRules]：地址分类（私网 / 组网 / 公网）。
 *
 * 候选优先级**随当前网络类型变化**（这是「出门自动切通道」能做对的关键）：
 * - 手动锁定（AppPreferences.backendUrl 非空）—— 用户明确指定，不探测；
 * - WiFi / 以太网：局域网（lanUrl）优先，组网（vpnUrl）次之，公网域名（tunnelUrl）兜底；
 * - 蜂窝数据：组网优先，公网域名次之，局域网排到最后。
 *
 * 组网与公网是**并存的两条远程通道**，不是互斥开关：手机开了 Tailscale 就走点对点直连
 * （不经公网边缘、无隧道抖动），没开或探不通时自动退到 Cloudflare 域名。
 *
 * **组网槽位留空 = 未启用该通道**：`vpnUrl` 默认是空串，[resolve] 会直接跳过这一档，
 * 绝不会去猜地址。地址来源有三个：设置页手填、槽位迁移时把已有组网地址升格进槽位、
 * 局域网发现时后端通过 UDP 信标自报（见 `ServerDiscoveryManager`）。
 *
 * 为什么顺序要随网络变：蜂窝网络下 192.168.x.x / 10.x.x.x 在物理上就不可达，
 * 先探局域网只是白等一个 connect 超时，而这段等待正是「开了流量却迟迟切不过去」
 * 的直接体感。反过来在家里 WiFi 下先探局域网，几十毫秒就有结果，不会误走公网绕远。
 *
 * 另外有一层物理兜底：蜂窝网络下如果生效地址仍是私网地址，即使远程通道这次没探通
 * （隧道冷启动、健康检查偶发慢）也强制切过去，否则一次探测抖动就会让用户
 * 整个出门期间都卡在内网地址上。
 *
 * 裁决结果写进 AppPreferences.activeUrl，所有网络消费方统一读
 * AppPreferences.effectiveBackendUrl。
 *
 * 探测触发时机（五处）：
 * - App 启动（AvelineApplication.onCreate → [startMonitoring] 的初始回调）；
 * - 网络变化（[NetworkWatcher] 的默认网络与物理链路两层回调）；
 * - 连接失败降级（WebSocketManager / 聊天请求 → [resolveOnFailure]）；
 * - 设置页手动点「重新探测」；
 * - 周期重探（[NetworkWatcher] 的定时器，补上「组网从不可用变成可用」这类没有回调的事件）。
 */
@Singleton
class EndpointResolver @Inject constructor(
    @ApplicationContext private val context: Context,
    private val appPreferences: AppPreferences
) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val inspector = NetworkTransportInspector(context)

    private val prober = EndpointProber { appPreferences.accessToken }

    /** 网络监听交给 [NetworkWatcher]；它只在「有更优候选」时才让门面真的发探测请求。 */
    private val watcher = NetworkWatcher(
        scope = scope,
        inspector = inspector,
        periodicReprobeIntervalMs = PERIODIC_REPROBE_INTERVAL_MS,
        onResolve = { trigger -> resolve(trigger) },
        onPeriodicTick = { if (hasBetterCandidate()) resolve("周期重探") }
    )

    /** 当前生效地址。初值取 effectiveBackendUrl，让冷启动立刻按上次的结果连上。 */
    private val _active = MutableStateFlow(
        ResolvedEndpoint(appPreferences.effectiveBackendUrl, EndpointChannel.NONE)
    )
    val active: StateFlow<ResolvedEndpoint> = _active.asStateFlow()

    private val _changes = MutableSharedFlow<String>(
        extraBufferCapacity = 8,
        onBufferOverflow = BufferOverflow.DROP_OLDEST
    )

    /** 生效地址发生变化的通知（新地址），供 WebSocketManager 强制重连。 */
    val changes: SharedFlow<String> = _changes.asSharedFlow()

    /** 串行化探测：并发探测会互相覆盖 activeUrl，也会把网络堆满。 */
    private val resolveMutex = Mutex()

    /** 上次「失败降级」探测的时间戳，用于节流。 */
    private val lastFailureProbeAt = AtomicLong(0L)

    /**
     * 按优先级探测并采纳第一个可用候选。
     *
     * @param trigger 触发来源，只进日志，便于排查「为什么切到公网了」。
     * @return 本次裁决后的生效地址；**null 表示所有候选都不可达**（此时 [active] 仍保留
     *         原地址不变，避免把配置清成空）。调用方需要区分「探测成功」和「全都不通」
     *         时必须判 null，不能拿返回地址非空当成功 —— 全失败时返回的是沿用中的旧地址。
     */
    suspend fun resolve(trigger: String): ResolvedEndpoint? = resolveMutex.withLock {
        // 1. 手动锁定：用户明确指定，不做任何探测（也是「强制走公网测链路」的出口）
        val manual = appPreferences.backendUrl.trim()
        if (manual.isNotEmpty()) {
            return@withLock adopt(manual, EndpointChannel.MANUAL, trigger)
        }

        val lan = appPreferences.lanUrl.trim()
        val tunnel = appPreferences.tunnelUrl.trim()
        val vpn = appPreferences.vpnUrl.trim()
        // 有没有「能到局域网」的链路。蜂窝数据下没有，此时私网地址必然不通。
        val lanTransport = inspector.hasLanTransport()
        if (!lanTransport && tunnel.isEmpty() && vpn.isEmpty()) {
            // 「开流量切不过去」最常见的原因就是这个：远程通道槽位都是空的，
            // 根本没有可切的候选。打一条明确日志，免得每次都要翻代码才能确认。
            Log.w(TAG, "[$trigger] 当前非局域网链路，但未配置任何远程通道（tunnelUrl / vpnUrl 均为空）")
        }

        // 2. WiFi / 以太网：局域网优先。短超时，在家里几十毫秒就出结果。
        if (lanTransport && lan.isNotEmpty() &&
            prober.probe(lan, LAN_CONNECT_TIMEOUT_MS, LAN_READ_TIMEOUT_MS)
        ) {
            return@withLock adopt(lan, EndpointChannel.LAN, trigger)
        }

        // 3. 组网通道（Tailscale 等点对点 VPN）。
        //    排在公网域名之前：两条都是「出门能用」的远程通道，但组网是手机直连电脑，
        //    不过公网边缘，既没有 Cloudflare 隧道的抖动/530，延迟也低得多。
        //    蜂窝下局域网候选已跳过，它实质就是第一候选。
        if (vpn.isNotEmpty() &&
            prober.probe(vpn, VPN_CONNECT_TIMEOUT_MS, VPN_READ_TIMEOUT_MS)
        ) {
            return@withLock adopt(vpn, EndpointChannel.VPN, trigger)
        }

        // 4. 公网兜底。组网没配或没探通时仍然可用；TLS 握手 + 边缘节点回源，超时给宽一些。
        if (tunnel.isNotEmpty() &&
            prober.probe(tunnel, WAN_CONNECT_TIMEOUT_MS, WAN_READ_TIMEOUT_MS)
        ) {
            return@withLock adopt(tunnel, EndpointChannel.TUNNEL, trigger)
        }

        // 5. 蜂窝下再补一次局域网：手机热点、USB 网络共享等场景下「蜂窝 + 私网可达」
        //    是成立的，不能因为传输类型是蜂窝就彻底放弃局域网候选。
        if (!lanTransport && lan.isNotEmpty() &&
            prober.probe(lan, LAN_CONNECT_TIMEOUT_MS, LAN_READ_TIMEOUT_MS)
        ) {
            return@withLock adopt(lan, EndpointChannel.LAN, trigger)
        }

        // 6. 全都不通时的物理兜底。
        //    蜂窝网络下生效地址仍是私网地址（在外面还挂着家里的内网 IP）时，
        //    哪怕远程通道这次也没探通，也要切过去：留在这个地址上是 100% 发不出消息的，
        //    而远程通道只是「这次没探通」（隧道冷启动、健康检查偶发超时都可能导致）。
        //    少了这一步，一次探测抖动就会让用户整个出门期间都卡在内网地址上。
        if (!lanTransport && BackendAddressRules.isLanOnlyHost(_active.value.url)) {
            // 组网优先于公网：两条都能出公网，先挑更稳的那条；没配组网才退到公网域名。
            val remoteUrl = vpn.ifEmpty { tunnel }
            if (remoteUrl.isNotEmpty()) {
                Log.w(TAG, "[$trigger] 蜂窝网络下仍指向私网地址，强制降级远程通道: $remoteUrl")
                return@withLock adopt(
                    remoteUrl,
                    if (vpn.isNotEmpty()) EndpointChannel.VPN else EndpointChannel.TUNNEL,
                    "$trigger(强制降级)"
                )
            }
        }

        Log.w(TAG, "[$trigger] 所有候选均不可达，沿用当前地址: ${_active.value.url}")
        null
    }

    /**
     * 请求 / WebSocket 连接失败后的降级探测。
     *
     * 候选顺序与 [resolve] 一致（随网络类型变化），所以两个方向都覆盖：
     * 出门时局域网失效 → 降到公网；回家后 WiFi 恢复 → 换回局域网。
     *
     * 与 [resolve] 的区别是节流：失败回调在重连期间可能密集触发，
     * 没有间隔限制的话每次失败都串一遍完整探测（含一次必然超时的局域网探测），
     * 白白耗电。节流窗口内直接跳过（返回 null）。
     *
     * 例外：「当前地址在物理上不可能通」时不受节流限制 —— 例如蜂窝网络下生效地址
     * 还是家里的内网 IP。这种情况每多等一秒，用户就多一秒发不出消息。
     *
     * @return 裁决结果；null 表示本次被节流跳过或所有候选都不可达
     */
    suspend fun resolveOnFailure(): ResolvedEndpoint? {
        val urgent = !inspector.hasLanTransport() &&
            BackendAddressRules.isLanOnlyHost(_active.value.url)
        if (!urgent) {
            val now = System.currentTimeMillis()
            val last = lastFailureProbeAt.get()
            if (now - last < FAILURE_PROBE_MIN_INTERVAL_MS) return null
            if (!lastFailureProbeAt.compareAndSet(last, now)) return null
        } else {
            // 紧急重探也要更新时间戳，避免紧接着的普通失败再探一次。
            lastFailureProbeAt.set(System.currentTimeMillis())
        }
        return resolve("失败降级")
    }

    /**
     * 开始监听网络变化并触发重探测。幂等，重复调用无副作用。
     *
     * 放在 Application 而不是只在 Activity 里调用，是为了兜住「界面还没打开」的场景
     * （开机自启、被推送唤醒、服务先于界面启动），否则那段时间会一直用着上次的旧通道。
     */
    fun startMonitoring() {
        watcher.start()
    }

    /** 门面只做参数收集，判据在 [ChannelPriority]（纯函数，有 host 单测）。 */
    private fun hasBetterCandidate(): Boolean = ChannelPriority.hasBetterCandidate(
        current = _active.value.channel,
        lanTransport = inspector.hasLanTransport(),
        lanUrl = appPreferences.lanUrl.trim(),
        vpnUrl = appPreferences.vpnUrl.trim(),
        tunnelUrl = appPreferences.tunnelUrl.trim()
    )

    /** 采纳一个候选：落盘 + 更新状态 + 地址真变了才广播。 */
    private fun adopt(url: String, channel: EndpointChannel, trigger: String): ResolvedEndpoint {
        val previous = _active.value
        val endpoint = ResolvedEndpoint(url, channel)

        // 先落盘再广播：订阅者收到通知后会立刻读 effectiveBackendUrl，
        // 此时 activeUrl 必须已经是新值，否则会拿旧地址去重连。
        appPreferences.activeUrl = url
        _active.value = endpoint

        if (previous.url != url) {
            Log.i(TAG, "[$trigger] 通道切换 ${previous.channel}(${previous.url}) -> $channel($url)")
            _changes.tryEmit(url)
        } else {
            Log.d(TAG, "[$trigger] 通道确认 $channel($url)")
        }
        return endpoint
    }

    companion object {
        private const val TAG = "EndpointResolver"

        /**
         * 局域网探测超时。**必须短**：出门在外时局域网候选是必然连不上的，
         * 超时多长，用户就要多等多久才能降到公网。局域网正常应在 100ms 内返回。
         */
        private const val LAN_CONNECT_TIMEOUT_MS = 800
        private const val LAN_READ_TIMEOUT_MS = 800

        /**
         * 组网通道探测超时：Tailscale 打洞成功时是几十毫秒的直连，走 DERP 中继多一跳
         * 也就几百毫秒，1.5s 富余。
         *
         * 比公网（3s）短是刻意的：手机端没开 Tailscale 时，100.x 地址在蜂窝网络下不可达，
         * 连接会一直挂到超时才转公网候选。这段等待是用户能感知的「切换卡顿」，能短就短。
         */
        private const val VPN_CONNECT_TIMEOUT_MS = 1500
        private const val VPN_READ_TIMEOUT_MS = 1500

        /** 公网探测超时：TLS 握手 + Cloudflare 边缘回源，需要给宽一些。 */
        private const val WAN_CONNECT_TIMEOUT_MS = 3000
        private const val WAN_READ_TIMEOUT_MS = 3000

        /** 「失败降级」探测的最小间隔，避免重连风暴把探测打成高频任务。 */
        private const val FAILURE_PROBE_MIN_INTERVAL_MS = 20_000L

        /**
         * 周期重探间隔。5 分钟是权衡：够短，走到半路就能自动升回组网；
         * 够长，不会把探测打成高频任务（且只在有更优候选时才真的探测）。
         */
        private const val PERIODIC_REPROBE_INTERVAL_MS = 5 * 60 * 1000L
    }
}
