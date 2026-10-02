package com.aveline.ai.mobile.services.endpoint

import android.util.Log
import java.net.HttpURLConnection
import java.net.URL

/**
 * 后端身份探测：判断某个地址上跑的到底是不是我们的后端。
 *
 * 为什么必须校验响应体身份，而不是只看端口 / HTTP 状态码：
 * 端口通不等于后端 —— 局域网里任意开 8000 的设备都能连通，只有响应体里出现服务标识才认。
 *
 * 为什么必须读到 marker 出现为止，而不是只读前 N 个字符（历史 bug 的根因）：
 * `/api/v1/health` 的 payload 顺序是 `status` → `services`（一整坨服务明细）→ `metrics`
 * → `timestamp` → `service: "AI Agent Core"` → …，服务标识实际落在 **1000 字符之后**
 * （实测某次真实响应：总长 5470 字节，marker 偏移 1058）。
 * 旧实现在两个调用点都写着「只读前 1024 字符判断身份」，于是**必然**匹配不到 marker，
 * 所有候选地址一律被判成「不可达」。用户看到的现象就是：
 * - 设置页点「重新检测」永远提示「所有候选地址都不可达」（地址明明是好的）；
 * - 开流量切公网要靠失败重连里的物理兜底才勉强切过去，慢且不稳定；
 * - 回家后完全切不回局域网（WiFi 下不满足「蜂窝 + 私网地址」的强制降级条件，于是一直
 *   沿用公网地址）。
 *
 * 这里把判据收敛成唯一实现，两个调用点（EndpointResolver / ServerDiscoveryManager）
 * 共用，避免再次各自分叉出不同的判据。
 */
object BackendIdentityProbe {

    private const val TAG = "BackendIdentityProbe"

    /** 健康检查端点：后端唯一注册在 routers/v1/health.py，经 api_v1_router 挂载后前缀是 /api/v1。 */
    const val HEALTH_PATH = "/api/v1/health"

    /** 后端健康检查返回体里的服务标识（routers/v1/health.py 的 "service" 字段）。 */
    const val HEALTH_MARKER = "AI Agent Core"

    /**
     * 单次探测最多读取的字符数。
     *
     * 正常 payload 只有几 KB，这里留足余量；同时给异常响应封顶
     * （例如被中间设备换成超大错误页时，不要在探测里把内存吃掉）。
     */
    private const val MAX_IDENTITY_CHARS = 256 * 1024

    /** 分块读取的块大小。 */
    private const val CHUNK_SIZE = 4096

    /**
     * 探测某个候选地址上是不是我们的后端。
     *
     * 阻塞式实现，调用方负责放到 IO 线程并加超时。只认「HTTP 200 且响应体含服务标识」。
     *
     * @param baseUrl 归一化前的地址，如 `http://192.0.2.1:8000` 或 `https://xxx.example.com`
     * @param accessToken 访问令牌；`/api/v1/health` 在受保护路径名单里，无令牌会被拒
     * @return true 表示该地址确实是本项目后端
     */
    fun probe(
        baseUrl: String,
        connectTimeoutMs: Int,
        readTimeoutMs: Int,
        accessToken: String
    ): Boolean {
        val base = normalize(baseUrl) ?: return false
        return try {
            val conn = URL(base + HEALTH_PATH).openConnection() as HttpURLConnection
            try {
                conn.connectTimeout = connectTimeoutMs
                conn.readTimeout = readTimeoutMs
                conn.requestMethod = "GET"
                if (accessToken.isNotEmpty()) {
                    conn.setRequestProperty("Authorization", "Bearer $accessToken")
                    conn.setRequestProperty("x-internal-token", accessToken)
                }
                val code = conn.responseCode
                if (code != HttpURLConnection.HTTP_OK) {
                    // 401 / 503 说明地址是通的，只是令牌不对或后端没配令牌 ——
                    // 这和「连不上」是完全不同的问题，日志里区分开，排查时不用猜。
                    Log.d(TAG, "探测 $base 返回 HTTP $code（地址可达，但未通过认证）")
                    return false
                }
                if (!readUntilMarker(conn)) {
                    Log.d(TAG, "探测 $base 响应体不含服务标识，可能不是本项目后端")
                    return false
                }
                true
            } finally {
                conn.disconnect()
            }
        } catch (e: Exception) {
            Log.d(TAG, "探测失败 $base (${e.javaClass.simpleName}: ${e.message})")
            false
        }
    }

    /** 归一化成 `scheme://host[:port]`；空地址返回 null。 */
    private fun normalize(raw: String): String? {
        val trimmed = raw.trim().trimEnd('/')
        if (trimmed.isEmpty()) return null
        return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
            trimmed
        } else {
            "http://$trimmed"
        }
    }

    /**
     * 分块读响应体，直到读到服务标识或用完读取额度。
     *
     * 不能用「一次 read(CharArray(N)) 然后 contains」：一次 read 不保证填满缓冲区，
     * 也不保证读到指定位置，marker 直接落在未读区间里就会被漏判（这正是旧实现的问题）。
     */
    private fun readUntilMarker(conn: HttpURLConnection): Boolean {
        conn.inputStream.bufferedReader().use { reader ->
            val chunkBuffer = CharArray(CHUNK_SIZE)
            var remaining = MAX_IDENTITY_CHARS
            val chunks = sequence {
                while (remaining > 0) {
                    val count = reader.read(chunkBuffer, 0, minOf(chunkBuffer.size, remaining))
                    if (count <= 0) break
                    remaining -= count
                    yield(String(chunkBuffer, 0, count))
                }
            }
            return containsMarkerInChunks(chunks)
        }
    }

    /**
     * 在分块文本里查找服务标识，跨块边界也能命中。
     *
     * 每读完一块只保留末尾 `marker.length - 1` 个字符参与下一块匹配，
     * 这样 marker 被切在两块之间时（分块读取的常见形态）不会漏判，
     * 同时不把整段响应拼进内存。internal 便于单元测试直接覆盖。
     */
    internal fun containsMarkerInChunks(chunks: Sequence<String>): Boolean {
        val keep = HEALTH_MARKER.length - 1
        var tail = ""
        for (chunk in chunks) {
            val text = tail + chunk
            if (text.contains(HEALTH_MARKER)) return true
            tail = text.takeLast(minOf(text.length, keep))
        }
        return false
    }
}
