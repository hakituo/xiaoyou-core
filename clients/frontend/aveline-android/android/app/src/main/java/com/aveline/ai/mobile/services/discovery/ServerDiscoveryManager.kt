@file:Suppress("DEPRECATION")

package com.aveline.ai.mobile.services.discovery

import android.content.Context
import android.net.wifi.WifiManager
import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.services.endpoint.BackendIdentityProbe
import com.aveline.ai.mobile.services.endpoint.resolver.NetworkTransportInspector
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import java.io.IOException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import java.net.Socket
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 服务端自动发现管理器
 *
 * 实现零配置启动：
 * 1. 优先监听 UDP 广播（后端主动宣告，载荷里同时带局域网地址与可选的组网地址）
 * 2. 备选扫描常见网段（兜底）
 * 3. 发现后自动保存到 AppPreferences（局域网 → lanUrl，组网 → vpnUrl）
 */
@Singleton
class ServerDiscoveryManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val appPreferences: AppPreferences
) {
    companion object {
        private const val TAG = "ServerDiscovery"

        // UDP 广播配置
        private const val DISCOVERY_PORT = 28899
        private const val UDP_TIMEOUT_MS = 5000L

        // 扫描配置
        private const val TCP_TIMEOUT_MS = 300

        /**
         * 健康检查超时。读超时不能沿用 [TCP_TIMEOUT_MS]：该接口内部会汇总多个监控组件，
         * 首次调用可能远超 300ms，用 300ms 会把真后端误判成假后端。
         */
        private const val HEALTH_CONNECT_TIMEOUT_MS = 500
        private const val HEALTH_READ_TIMEOUT_MS = 2500
        private const val HEALTH_PROBE_TIMEOUT_MS = 3500L

        private val COMMON_GATEWAYS = listOf(
            "192.168.1.1", "192.168.0.1", "192.168.31.1",
            "192.168.50.1", "192.168.10.1", "10.0.0.1",
            "192.168.2.1", "192.168.3.1", "192.168.100.1"
        )
        private val COMMON_SUBNETS = listOf(
            "192.168.1", "192.168.0", "192.168.31",
            "192.168.50", "192.168.10", "10.0.0",
            "192.168.2", "192.168.3", "192.168.100"
        )
        // 后端固定端口 8000,无需尝试其他端口
        private val PORTS_TO_TRY = listOf(8000)
        // 分批并行扫描的批次大小
        private const val SCAN_BATCH_SIZE = 30
    }

    private var discoverySocket: DatagramSocket? = null
    private var multicastLock: WifiManager.MulticastLock? = null

    /** 链路类型判定复用裁决器那套（含「开 VPN 时也要找回底层 WiFi」）。 */
    private val inspector = NetworkTransportInspector(context)

    /**
     * 服务器身份校验：请求 {url}/api/v1/health, 要求 HTTP 200 且返回体包含服务标识。
     *
     * 仅 TCP 端口可达不能证明是后端(任意设备开 8000 端口都算"可达"),
     * 必须在 HTTP 层校验才能真正鉴权, 防止局域网内冒充后端的恶意设备被自动采纳。
     *
     * 判据收敛在 [BackendIdentityProbe]，这里只负责放 IO 线程 + 兜底超时。
     * 历史上这里自己实现过一份「只读响应体前 1024 字符」的判断，而服务标识实际在
     * 1000 字符之后（实测偏移 1058），于是自动发现永远认不出真后端 —— 这也是
     * 「回家后自动切不回局域网」的原因之一。
     */
    private suspend fun verifyBackendIdentity(url: String): Boolean = withContext(Dispatchers.IO) {
        try {
            withTimeout(HEALTH_PROBE_TIMEOUT_MS) {
                BackendIdentityProbe.probe(
                    baseUrl = url,
                    connectTimeoutMs = HEALTH_CONNECT_TIMEOUT_MS,
                    readTimeoutMs = HEALTH_READ_TIMEOUT_MS,
                    accessToken = appPreferences.accessToken
                )
            }
        } catch (e: Exception) {
            Log.w(TAG, "服务器身份校验失败: $url (${e.message})")
            false
        }
    }

    /**
     * 主入口：自动发现局域网后端，并顺手补齐组网槽位。
     * @return 发现的局域网地址，或 null（未发现）。
     *
     * 结果写入 [AppPreferences.lanUrl] 槽位，**不再写 backendUrl**。
     * 是否真的采用由 EndpointResolver 按优先级裁决（用户手动锁定时不会被用上），
     * 所以这里可以放心地每次覆盖局域网槽位 —— 旧实现「用户配过地址就不覆盖」
     * 正是「设了公网域名后回家永远切不回局域网」的根因。
     *
     * 信标里还带后端的组网地址（可选段），会在槽位为空时补进 [AppPreferences.vpnUrl] ——
     * 这是客户端唯一能问到组网地址的时机：广播只发得进局域网，出门后手机收不到。
     */
    suspend fun discoverServer(): String? = withContext(Dispatchers.IO) {
        // -1. 没有局域网链路（走蜂窝数据）就别找了。
        //     子网扫描会并发探测 9 个子网 × 254 个地址，每个最多等一个连接超时；
        //     蜂窝网络下这些地址一个都不可能通，整轮扫描要空转几十秒，
        //     还会把 Dispatchers.IO 的线程池占满 —— 用户感知就是「点了发送卡半天没反应」。
        if (!inspector.hasLanTransport()) {
            Log.d(TAG, "当前非局域网链路（蜂窝网络），跳过局域网发现")
            return@withContext null
        }

        // 0. 已配的局域网地址还通就直接用，省掉一次广播等待。
        //    例外：组网槽位还是空的 —— 信标是唯一能问到「后端组网地址」的途径，
        //    而它只在局域网里发得出来，所以在家这次必须听一遍，否则出门永远只剩公网可用。
        //    补上之后 needVpnAddress 恒为 false，这个额外等待只发生一次。
        val currentLan = appPreferences.lanUrl
        val currentLanOk = currentLan.isNotEmpty() && verifyBackendIdentity(currentLan)
        val needVpnAddress = appPreferences.vpnUrl.trim().isEmpty()
        if (currentLanOk && !needVpnAddress) {
            Log.d(TAG, "已配置的局域网地址仍可用: $currentLan")
            return@withContext currentLan
        }

        // 1. 尝试 UDP 广播发现（最快）
        Log.d(TAG, "开始 UDP 广播发现...")
        // 修复 multicastLock 泄漏:用 try-finally 确保异常情况下锁也能释放,避免 WiFi 模块资源泄漏耗电
        acquireMulticastLock()
        val beacon = try {
            tryDiscoverByUdp()
        } finally {
            releaseMulticastLock()
        }
        if (beacon != null) {
            // 必须通过身份校验才接受, 防止恶意设备冒充后端
            if (verifyBackendIdentity(beacon.lanUrl)) {
                Log.i(TAG, "UDP 发现并通过身份校验的服务器: ${beacon.lanUrl}")
                saveDiscoveredLan(beacon.lanUrl)
                saveDiscoveredVpn(beacon.vpnUrl)
                return@withContext beacon.lanUrl
            }
            Log.w(TAG, "UDP 发现但未通过身份校验, 忽略: ${beacon.lanUrl}")
        }

        // 局域网地址本来就是通的，只是这次没问到组网地址（后端未启用组网 / 信标还没广播）：
        // 保持原样返回，别为了一次补槽位失败触发整轮子网扫描。
        if (currentLanOk) {
            Log.d(TAG, "信标未提供组网地址，沿用已可用的局域网地址: $currentLan")
            return@withContext currentLan
        }

        // 2. 备选：网段扫描（候选仍需身份校验）
        Log.d(TAG, "UDP 未发现，开始网段扫描...")
        val discoveredByScan = scanForServer()
        if (discoveredByScan != null) {
            Log.i(TAG, "扫描发现并通过身份校验的服务器: $discoveredByScan")
            saveDiscoveredLan(discoveredByScan)
            return@withContext discoveredByScan
        }

        Log.w(TAG, "未发现局域网服务器")
        return@withContext null
    }

    /**
     * 把发现结果写进局域网槽位。
     *
     * 只有地址真的变了才写，避免每次启动都触发一次 SharedPreferences 写入与
     * EndpointResolver 的响应式广播（那会让 WebSocket 做一次无意义的重连）。
     */
    private fun saveDiscoveredLan(url: String) {
        val normalized = url.trimEnd('/')
        if (appPreferences.lanUrl == normalized) {
            Log.d(TAG, "局域网槽位已是该地址, 不重复写入: $normalized")
            return
        }
        appPreferences.lanUrl = normalized
        Log.i(TAG, "已更新局域网槽位: $normalized")
    }

    /**
     * 把信标自报的组网地址补进组网槽位（**仅在槽位为空时**）。
     *
     * 不覆盖用户已填的值：槽位语义就是「用户可覆盖的候选」，用户可能故意指向别的组网地址
     * （另一台机器、WireGuard 等），空槽位才是「没人配过，帮我填一个」。
     *
     * **不做身份校验**：信标是明文 UDP，局域网里谁都能伪造，但组网地址只是**候选** ——
     * 真正采纳前要过 EndpointResolver 的探测（HTTP 200 + 响应体含服务标识 + 令牌），
     * 伪造一个假地址最多让探测白跑 1.5 秒，劫持不了连接。反过来，在这里做校验会让
     * 「手机当前没开组网 → 探测必然失败 → 槽位永远填不上」，正好错过唯一能问到地址的时机。
     */
    private fun saveDiscoveredVpn(url: String?) {
        if (url.isNullOrEmpty()) {
            Log.d(TAG, "信标未带组网地址（后端未启用组网），跳过")
            return
        }
        if (appPreferences.vpnUrl.trim().isNotEmpty()) {
            Log.d(TAG, "组网槽位已由用户填写，不覆盖: ${appPreferences.vpnUrl}")
            return
        }
        val normalized = url.trimEnd('/')
        appPreferences.vpnUrl = normalized
        Log.i(TAG, "已从信标补齐组网槽位: $normalized")
    }

    /**
     * 获取 WiFi 多播锁
     * Android 默认会过滤 UDP 广播包，必须获取多播锁才能接收
     */
    private fun acquireMulticastLock() {
        try {
            val wifiManager = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
            if (wifiManager != null) {
                val lock = wifiManager.createMulticastLock("AvelineDiscovery")
                lock.setReferenceCounted(false)
                lock.acquire()
                multicastLock = lock
                Log.d(TAG, "已获取 WiFi 多播锁")
            }
        } catch (e: Exception) {
            Log.w(TAG, "获取多播锁失败: ${e.message}")
        }
    }

    private fun releaseMulticastLock() {
        try {
            multicastLock?.let {
                if (it.isHeld) {
                    it.release()
                }
            }
            multicastLock = null
        } catch (e: Exception) {
            Log.w(TAG, "释放多播锁失败: ${e.message}")
        }
    }

    /**
     * UDP 广播发现。
     *
     * 载荷格式见后端 `core/services/discovery/udp_beacon.py`：
     * `AVELINE_SERVER|<局域网地址>[|<组网地址>]`。第三段是可选的（老后端不发），
     * 缺失即「后端没有组网入口」，不是「信标没发全」。
     */
    private suspend fun tryDiscoverByUdp(): BeaconPayload.Beacon? = withContext(Dispatchers.IO) {
        try {
            withTimeout(UDP_TIMEOUT_MS) {
                val socket = DatagramSocket(null).apply {
                    reuseAddress = true
                    bind(InetSocketAddress(DISCOVERY_PORT))
                    soTimeout = 1000
                }
                discoverySocket = socket

                val buffer = ByteArray(1024)
                val packet = DatagramPacket(buffer, buffer.size)

                // 持续监听直到超时
                while (isActive) {
                    try {
                        socket.receive(packet)
                        val message = String(packet.data, 0, packet.length)

                        val beacon = BeaconPayload.parse(message)
                        if (beacon != null) {
                            socket.close()
                            discoverySocket = null
                            return@withTimeout beacon
                        }
                    } catch (e: java.net.SocketTimeoutException) {
                        // 继续监听，等外层 withTimeout 超时
                    } catch (e: IOException) {
                        // 继续监听
                    }
                }
                return@withTimeout null
            }
        } catch (e: TimeoutCancellationException) {
            Log.d(TAG, "UDP 监听超时（${UDP_TIMEOUT_MS}ms）")
            discoverySocket?.close()
            discoverySocket = null
            return@withContext null
        } catch (e: Exception) {
            Log.e(TAG, "UDP 发现失败: ${e.message}")
            discoverySocket?.close()
            discoverySocket = null
            return@withContext null
        }
    }

    /**
     * 网段扫描兜底
     * 先用 WifiManager 获取实际网关和子网，再扫描
     */
    private suspend fun scanForServer(): String? = withContext(Dispatchers.IO) {
        // 获取实际网段
        val actualSubnet = getLocalSubnet()
        val actualGateway = getLocalGateway()

        // 构建扫描列表：实际网段优先
        val subnetsToScan = mutableListOf<String>()
        if (actualSubnet != null && actualSubnet !in COMMON_SUBNETS) {
            subnetsToScan.add(actualSubnet)
        }
        subnetsToScan.addAll(COMMON_SUBNETS)

        val gatewaysToScan = mutableListOf<String>()
        if (actualGateway != null && actualGateway !in COMMON_GATEWAYS) {
            gatewaysToScan.add(actualGateway)
        }
        gatewaysToScan.addAll(COMMON_GATEWAYS)

        // 先扫网关 (候选须通过身份校验, 跳过非后端主机)
        val gatewayResults = gatewaysToScan.map { gateway ->
            async {
                for (port in PORTS_TO_TRY) {
                    val url = "http://$gateway:$port"
                    if (verifyBackendIdentity(url)) return@async url
                }
                null
            }
        }.awaitAll().firstOrNull { it != null }

        if (gatewayResults != null) return@withContext gatewayResults

        // 扫子网，分批并行扫描以加速
        val subnetResults = subnetsToScan.map { subnet ->
            async {
                // 分批并行:每批 SCAN_BATCH_SIZE 个 IP 并行扫描
                for (batchStart in 1..254 step SCAN_BATCH_SIZE) {
                    if (!isActive) return@async null
                    val batchEnd = minOf(batchStart + SCAN_BATCH_SIZE - 1, 254)
                    val jobs = (batchStart..batchEnd).map { host ->
                        async batch@{
                            for (port in PORTS_TO_TRY) {
                                val url = "http://$subnet.$host:$port"
                                if (verifyBackendIdentity(url)) return@batch url
                            }
                            null
                        }
                    }
                    val result = jobs.awaitAll().firstOrNull { it != null }
                    if (result != null) return@async result
                }
                null
            }
        }.awaitAll().firstOrNull { it != null }

        return@withContext subnetResults
    }

    /**
     * 测试服务器是否可达（TCP 连接测试）
     */
    private suspend fun isServerReachable(url: String): Boolean = withContext(Dispatchers.IO) {
        // 不再对 "localhost" 直接返回 false：地址槽位默认值已是空串，
        // 这条短路只会让「当前地址是否可用」的检查无意义地跳过。
        if (url.isBlank()) return@withContext false

        try {
            withTimeout(TCP_TIMEOUT_MS.toLong()) {
                val host = extractHost(url) ?: return@withTimeout false
                val port = extractPort(url) ?: if (url.startsWith("https://")) 443 else 80

                Socket().use { socket ->
                    socket.connect(InetSocketAddress(host, port), TCP_TIMEOUT_MS)
                    socket.isConnected
                }
            }
        } catch (e: Exception) {
            false
        }
    }

    /**
     * 更精确的健康检查（HTTP /health）
     */
    suspend fun checkServerHealth(url: String): Boolean = withContext(Dispatchers.IO) {
        isServerReachable(url)
    }

    /**
     * 获取本机 IP 子网（通过 WifiManager）
     */
    fun getLocalSubnet(): String? {
        val wifiManager = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
        val dhcpInfo = wifiManager?.dhcpInfo

        if (dhcpInfo != null) {
            val gateway = dhcpInfo.gateway
            val subnet = "${(gateway and 0xFF)}.${(gateway shr 8 and 0xFF)}.${(gateway shr 16 and 0xFF)}"
            return subnet
        }
        return null
    }

    /**
     * 获取本机网关 IP
     */
    fun getLocalGateway(): String? {
        val wifiManager = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
        val dhcpInfo = wifiManager?.dhcpInfo

        if (dhcpInfo != null) {
            val gateway = dhcpInfo.gateway
            return "${(gateway and 0xFF)}.${(gateway shr 8 and 0xFF)}.${(gateway shr 16 and 0xFF)}.${(gateway shr 24 and 0xFF)}"
        }
        return null
    }

    private fun extractHost(url: String): String? {
        return try {
            val withoutProtocol = url.replace(Regex("^https?://"), "")
            withoutProtocol.substringBefore(":").substringBefore("/")
        } catch (e: Exception) {
            null
        }
    }

    private fun extractPort(url: String): Int? {
        return try {
            val withoutProtocol = url.replace(Regex("^https?://"), "")
            val afterHost = withoutProtocol.substringAfter(":", "")
            if (afterHost.isEmpty()) return null
            afterHost.substringBefore("/").toIntOrNull()
        } catch (e: Exception) {
            null
        }
    }

    fun stopDiscovery() {
        discoverySocket?.close()
        discoverySocket = null
        releaseMulticastLock()
    }
}
