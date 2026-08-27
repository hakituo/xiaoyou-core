package com.aveline.ai.mobile.di

import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import android.content.Context
import android.content.pm.ApplicationInfo
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import java.util.concurrent.TimeUnit
import javax.inject.Named
import javax.inject.Singleton

/**
 * 网络相关依赖模块
 *
 * 负责提供：
 * - OkHttpClient（认证、日志、动态域名）
 * - Retrofit（REST API）
 * - WebSocketManager（实时通信）
 *
 * 依赖均为单例范围
 */
@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    private const val PLACEHOLDER_BASE_URL = "http://127.0.0.1/"

    private fun normalizeBackendUrl(raw: String): String {
        val trimmed = raw.trim().trimEnd('/')
        if (trimmed.isEmpty()) {
            return ""
        }
        return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
            trimmed
        } else {
            "http://$trimmed"
        }
    }
    
    /**
     * 提供 JSON 序列化配置
     */
    @Provides
    @Singleton
    fun provideJson(): Json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        encodeDefaults = true
    }
    
    /**
     * 提供鉴权拦截器
     *
     * @param appPreferences 访问令牌来源
     */
    @Provides
    @Singleton
    @Named("auth")
    fun provideAuthInterceptor(appPreferences: AppPreferences): Interceptor {
        return Interceptor { chain ->
            val originalRequest = chain.request()
            val token = appPreferences.accessToken
            
            val newRequest = if (token.isNotEmpty()) {
                originalRequest.newBuilder()
                    .addHeader("Authorization", "Bearer $token")
                    .addHeader("x-internal-token", token)
                    .build()
            } else {
                originalRequest
            }
            
            chain.proceed(newRequest)
        }
    }
    
    /**
     * 提供日志拦截器（完整 BODY 级别，用于普通请求）
     *
     * 注意：BODY 级别会缓冲整个响应体，**不能**用于 SSE 流式请求，
     * 否则 OkHttp 会等整个响应体接收完毕才返回，导致流式失效。
     */
    @Provides
    @Singleton
    @Named("loggingBody")
    fun provideLoggingInterceptor(@ApplicationContext context: Context): HttpLoggingInterceptor {
        val isDebug = (context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0
        return HttpLoggingInterceptor().apply {
            level = if (isDebug) {
                HttpLoggingInterceptor.Level.BODY
            } else {
                HttpLoggingInterceptor.Level.NONE
            }
        }
    }

    /**
     * 提供轻量日志拦截器（HEADERS 级别，用于 SSE 流式请求）
     *
     * 不读响应体，避免缓冲导致 SSE 流式失效。
     */
    @Provides
    @Singleton
    @Named("loggingStream")
    fun provideStreamLoggingInterceptor(@ApplicationContext context: Context): HttpLoggingInterceptor {
        val isDebug = (context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0
        return HttpLoggingInterceptor().apply {
            level = if (isDebug) {
                HttpLoggingInterceptor.Level.HEADERS
            } else {
                HttpLoggingInterceptor.Level.NONE
            }
        }
    }

    @Provides
    @Singleton
    @Named("baseUrl")
    fun provideBaseUrlInterceptor(appPreferences: AppPreferences): Interceptor {
        return Interceptor { chain ->
            val request = chain.request()
            val backendUrl = normalizeBackendUrl(appPreferences.backendUrl)
            val backendHttpUrl = backendUrl.toHttpUrlOrNull()
            if (backendHttpUrl == null) {
                return@Interceptor chain.proceed(request)
            }

            val newUrl = request.url.newBuilder()
                .scheme(backendHttpUrl.scheme)
                .host(backendHttpUrl.host)
                .port(backendHttpUrl.port)
                .build()

            val newRequest = request.newBuilder()
                .url(newUrl)
                .build()

            chain.proceed(newRequest)
        }
    }
    
    /**
     * 提供 OkHttpClient（普通请求用）
     *
     * 配置项：
     * - 连接/读/写超时
     * - 动态域名拦截器
     * - 鉴权拦截器
     * - 日志拦截器（BODY 级别，仅调试）
     * - WebSocket 心跳
     */
    @Provides
    @Singleton
    fun provideOkHttpClient(
        @Named("baseUrl") baseUrlInterceptor: Interceptor,
        @Named("auth") authInterceptor: Interceptor,
        @Named("loggingBody") loggingInterceptor: HttpLoggingInterceptor
    ): OkHttpClient {
        return OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            // 关闭 OkHttp 协议层 ping。
            // 原因：OkHttp 的协议层 ping 发出后会硬性等待 pong，超时窗口 = pingInterval（15s），
            // 且不可单独调整。此超时窗口从 ping 发出瞬间算起，与服务端应用层心跳、事件循环调度
            // 存在竞态，在局域网空闲直连场景下偶发 "sent ping but didn't receive pong within
            // 15000ms" 误杀健康连接（往往前若干次成功、某次临界点到即断）。
            // 探活完全交给 WebSocketManager 的应用层 {"type":"ping"}/{"type":"pong"} 心跳 +
            // scheduleReconnect 指数退避重连机制；局域网直连也无 NAT idle 超时之忧，无需协议层保活。
            // .pingInterval(15, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .addInterceptor(baseUrlInterceptor)
            .addInterceptor(authInterceptor)
            .addInterceptor(loggingInterceptor)
            .build()
    }

    /**
     * 提供 SSE 流式专用 OkHttpClient
     *
     * 关键区别：
     * - 使用 HEADERS 级别日志（不读响应体，避免缓冲整个 SSE 流）
     * - 更长的读超时（流式生成可能需要较长时间）
     *
     * 如果用 BODY 级别日志拦截器，OkHttp 会缓冲整个响应体再返回，
     * 导致 source.readUtf8Line() 无法逐行读取 SSE，流式完全失效。
     */
    @Provides
    @Singleton
    @Named("streaming")
    fun provideStreamingOkHttpClient(
        @Named("baseUrl") baseUrlInterceptor: Interceptor,
        @Named("auth") authInterceptor: Interceptor,
        @Named("loggingStream") loggingInterceptor: HttpLoggingInterceptor
    ): OkHttpClient {
        return OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)  // 流式生成可能需要较长时间
            .writeTimeout(30, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .addInterceptor(baseUrlInterceptor)
            .addInterceptor(authInterceptor)
            .addInterceptor(loggingInterceptor)
            .build()
    }
    
    /**
     * 提供 Retrofit 实例
     *
     * baseUrl 仅用于占位，真实请求地址由动态域名拦截器控制
     */
    @Provides
    @Singleton
    fun provideRetrofit(
        okHttpClient: OkHttpClient,
        json: Json
    ): Retrofit {
        val contentType = "application/json".toMediaType()

        return Retrofit.Builder()
            .baseUrl(PLACEHOLDER_BASE_URL)
            .client(okHttpClient)
            .addConverterFactory(json.asConverterFactory(contentType))
            .build()
    }

    /**
     * 提供 AvelineApiService
     */
    @Provides
    @Singleton
    fun provideAvelineApiService(retrofit: Retrofit): AvelineApiService {
        return retrofit.create(AvelineApiService::class.java)
    }

    /**
     * 提供 SSE 流式专用 Retrofit
     *
     * 使用流式专用 OkHttpClient（HEADERS 级别日志，不缓冲响应体），
     * 确保 sendMessageStreaming 的 SSE 流能逐行读取。
     */
    @Provides
    @Singleton
    @Named("streaming")
    fun provideStreamingRetrofit(
        @Named("streaming") okHttpClient: OkHttpClient,
        json: Json
    ): Retrofit {
        val contentType = "application/json".toMediaType()
        return Retrofit.Builder()
            .baseUrl(PLACEHOLDER_BASE_URL)
            .client(okHttpClient)
            .addConverterFactory(json.asConverterFactory(contentType))
            .build()
    }

    /**
     * 提供 SSE 流式专用 AvelineApiService
     *
     * ChatRepositoryImpl 用这个实例发流式请求，避免普通 client 的 BODY 日志
     * 拦截器缓冲整个 SSE 响应体导致流式失效。
     */
    @Provides
    @Singleton
    @Named("streaming")
    fun provideStreamingAvelineApiService(
        @Named("streaming") retrofit: Retrofit
    ): AvelineApiService {
        return retrofit.create(AvelineApiService::class.java)
    }
    
    /**
     * 提供 WebSocketManager
     */
    @Provides
    @Singleton
    fun provideWebSocketManager(
        okHttpClient: OkHttpClient,
        appPreferences: AppPreferences
    ): WebSocketManager {
        return WebSocketManager(okHttpClient, appPreferences)
    }
}
