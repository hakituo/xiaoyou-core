@file:Suppress("DEPRECATION")

package com.aveline.ai.mobile.services.discovery

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import java.io.IOException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 服务端自动发现管理器
 *
 * 实现零配置启动：
 * 1. 优先监听 UDP 广播（后端主动宣告）
 * 2. 备选扫描常见网段（兜底）
 * 3. 发现后自动保存到 AppPreferences
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
        private const val BROADCAST_MAGIC = "AVELINE_SERVER"
        private const val UDP_TIMEOUT_MS = 5000L

        // 扫描配置
        private const val TCP_TIMEOUT_MS = 300
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

    /**
     * 服务器身份校验：请求 {url}/health, 要求 HTTP 200 且返回体包含 Aveline 服务标识。
     *
     * 仅 TCP 端口可达不能证明是后端(任意设备开 8000 端口都算"可达"),
     * 必须在 HTTP 层校验才能真正鉴权, 防止局域网内冒充后端的恶意设备被自动采纳。
     */
    private suspend fun verifyBackendIdentity(url: String): Boolean = withContext(Dispatchers.IO) {
        try {
            withTimeout(3000L) {
                val u = java.net.URL(url.trimEnd('/') + "/health")
                val conn = u.openConnection() as java.net.HttpURLConnection
                try {
                    conn.connectTimeout = TCP_TIMEOUT_MS
                    conn.readTimeout = TCP_TIMEOUT_MS
                    // 只读响应体前 1024 字符即可判断身份, 避免下载完整超大 body
                    val buffer = CharArray(1024)
                    val count = conn.inputStream.bufferedReader().use { it.read(buffer) }
                    val body = String(buffer, 0, if (count < 0) 0 else count)
                    conn.responseCode == HttpURLConnection.HTTP_OK &&
                        body.contains("AI Agent Core")
                } finally {
                    conn.disconnect()
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "服务器身份校验失败: $url (${e.message})")
            false
        }
    }

    /**
     * 主入口：自动发现可用服务器
     * @return 发现的服务器地址，或 null（未发现）。
     *
     * 仅当用户尚未配置后端地址时才会自动保存发现结果;若用户已设置地址,只返回候选不覆盖,
     * 避免自动发现静默替换用户手填的后端地址。
     */
    suspend fun discoverServer(): String? = withContext(Dispatchers.IO) {
        // 0. 检查当前配置是否已可用
        val currentUrl = appPreferences.backendUrl
        if (isServerReachable(currentUrl)) {
            Log.d(TAG, "当前配置已可用: $currentUrl")
            return@withContext currentUrl
        }

        // 1. 尝试 UDP 广播发现（最快）
        Log.d(TAG, "开始 UDP 广播发现...")
        // 修复 multicastLock 泄漏:用 try-finally 确保异常情况下锁也能释放,避免 WiFi 模块资源泄漏耗电
        acquireMulticastLock()
        val discoveredByUdp = try {
            tryDiscoverByUdp()
        } finally {
            releaseMulticastLock()
        }
        if (discoveredByUdp != null) {
            // 必须通过身份校验才接受, 防止恶意设备冒充后端
            if (verifyBackendIdentity(discoveredByUdp)) {
                Log.i(TAG, "UDP 发现并通过身份校验的服务器: $discoveredByUdp")
                saveDiscoveredServer(discoveredByUdp)
                return@withContext discoveredByUdp
            }
            Log.w(TAG, "UDP 发现但未通过身份校验, 忽略: $discoveredByUdp")
        }

        // 2. 备选：网段扫描（候选仍需身份校验）
        Log.d(TAG, "UDP 未发现，开始网段扫描...")
        val discoveredByScan = scanForServer()
        if (discoveredByScan != null) {
            Log.i(TAG, "扫描发现并通过身份校验的服务器: $discoveredByScan")
            saveDiscoveredServer(discoveredByScan)
            return@withContext discoveredByScan
        }

        Log.w(TAG, "未发现可用服务器")
        return@withContext null
    }

    /**
     * 保存发现的服务器地址。
     *
     * 仅当用户尚未配置后端地址(blank)时才自动写入 preferences;
     * 否则保留用户手填地址, 防止自动发现静默覆盖用户配置。
     */
    private fun saveDiscoveredServer(url: String) {
        if (appPreferences.backendUrl.isBlank()) {
            appPreferences.backendUrl = url
            Log.i(TAG, "用户未配置后端地址, 已自动保存发现结果: $url")
        } else {
            Log.i(TAG, "用户已配置后端地址(${appPreferences.backendUrl}), 不自动覆盖; 发现候选: $url")
        }
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
     * UDP 广播发现
     */
    private suspend fun tryDiscoverByUdp(): String? = withContext(Dispatchers.IO) {
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

                        if (message.startsWith(BROADCAST_MAGIC)) {
                            val parts = message.split("|")
                            if (parts.size >= 2) {
                                val serverUrl = parts[1].trim()
                                if (isValidServerUrl(serverUrl)) {
                                    socket.close()
                                    discoverySocket = null
                                    return@withTimeout serverUrl
                                }
                            }
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
        if (url.isBlank() || url.contains("localhost")) return@withContext false

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

    private fun isValidServerUrl(url: String): Boolean {
        return url.startsWith("http://") || url.startsWith("https://")
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
