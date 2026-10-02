package com.aveline.ai.mobile.services.endpoint.resolver

import android.util.Log
import com.aveline.ai.mobile.services.endpoint.BackendIdentityProbe
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout

/**
 * 候选地址探测：判断某个地址上跑的到底是不是本项目后端。
 *
 * 三个要点，缺一个都会误判：
 * 1. **走裸连接，不能复用业务 OkHttpClient** —— 业务 client 挂了 baseUrlInterceptor，
 *    会把请求地址重写成当前生效地址，探测就变成「自己测自己」，永远通过；
 * 2. **必须带访问令牌** —— /api/v1/health 在 is_protected_path 名单里
 *    （core/middleware/security.py），无令牌会被 401/503 拒掉；
 * 3. **必须校验响应体身份** —— 端口通不等于后端，局域网里任意开 8000 的设备都能连通，
 *    只有 body 里出现服务标识才认。
 *
 * 判据本身收敛在 [BackendIdentityProbe]，这里只负责放到 IO 线程 + 套一层兜底超时。
 * 历史上调用点各自实现过一份「只读前 1024 字符」的判断，而 marker 实际在 1000 字符之后
 * （见 BackendIdentityProbe 的注释），导致所有候选一律被判不可达。
 *
 * @param accessTokenProvider 令牌读取器。用 lambda 而不是构造时取快照：用户在设置页
 *   改完令牌会立刻重探，快照会让这次重探仍然拿旧令牌。
 */
internal class EndpointProber(private val accessTokenProvider: () -> String) {

    /**
     * @return true 表示该地址确实是本项目后端
     */
    suspend fun probe(baseUrl: String, connectTimeoutMs: Int, readTimeoutMs: Int): Boolean =
        withContext(Dispatchers.IO) {
            val base = normalize(baseUrl) ?: return@withContext false
            try {
                // 兜底超时：HttpURLConnection 的 connect/read 超时在部分机型上不严格生效，
                // 外层再套一层协程超时，保证探测不会无限挂住。
                withTimeout((connectTimeoutMs + readTimeoutMs).toLong() + TIMEOUT_GRACE_MS) {
                    BackendIdentityProbe.probe(
                        baseUrl = base,
                        connectTimeoutMs = connectTimeoutMs,
                        readTimeoutMs = readTimeoutMs,
                        accessToken = accessTokenProvider()
                    )
                }
            } catch (e: TimeoutCancellationException) {
                // 探测自身超时：属于「这个候选不通」，不是上层被取消
                Log.d(TAG, "探测超时 $base (${connectTimeoutMs + readTimeoutMs}ms)")
                false
            } catch (e: CancellationException) {
                // 上层协程被取消（如重连任务被 connect() 取消）时必须原样抛出，
                // 吞掉会让结构化并发失效、协程无法正常结束
                throw e
            } catch (e: Exception) {
                Log.d(TAG, "探测失败 $base (${e.javaClass.simpleName}: ${e.message})")
                false
            }
        }

    companion object {
        private const val TAG = "EndpointProber"

        /** 外层兜底超时相对 connect + read 的宽限。 */
        private const val TIMEOUT_GRACE_MS = 500L

        /** 归一化成 "scheme://host[:port]"；空地址返回 null。 */
        fun normalize(raw: String): String? {
            val trimmed = raw.trim().trimEnd('/')
            if (trimmed.isEmpty()) return null
            return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
                trimmed
            } else {
                "http://$trimmed"
            }
        }
    }
}
