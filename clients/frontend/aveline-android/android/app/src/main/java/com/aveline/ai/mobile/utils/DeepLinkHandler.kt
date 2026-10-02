package com.aveline.ai.mobile.utils

import android.content.Intent
import android.net.Uri
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 深度链接数据
 * 
 * @property action 要执行的操作
 * @property screen 目标页面
 * @property params 参数映射
 */
data class DeepLinkData(
    val action: String? = null,
    val screen: String? = null,
    val params: Map<String, String> = emptyMap()
) {
    val hasAction: Boolean
        get() = !action.isNullOrEmpty()
    
    val hasScreen: Boolean
        get() = !screen.isNullOrEmpty()
    
    val prefillText: String?
        get() = params["text"]
    
    val sessionId: String?
        get() = params["session_id"]
    
    val itemId: String?
        get() = params["item_id"]
}

/**
 * 深度链接处理器
 * 
 * 处理 aveline:// 协议的深度链接
 * 
 * 支持的链接格式：
 * - aveline://chat?text=hello - 打开聊天并预填文本
 * - aveline://chat?session_id=123 - 打开指定会话
 * - aveline://status - 打开状态页面
 * - aveline://shop?item_id=456 - 打开商店指定商品
 * - aveline://settings - 打开设置页面
 * 
 * Requirements: 19.3
 */
@Singleton
class DeepLinkHandler @Inject constructor() {
    
    companion object {
        const val SCHEME = "aveline"

        // 支持的路径
        const val PATH_CHAT = "chat"
        const val PATH_STATUS = "status"
        const val PATH_SHOP = "shop"
        const val PATH_SETTINGS = "settings"
        const val PATH_PLUGINS = "plugins"
        const val PATH_MEMORY = "memory"
        const val PATH_STUDY = "study"
        const val PATH_PERSONA = "persona"
        const val PATH_TOOLS = "tools"

        // path 白名单:不在其中的 deeplink 一律拒绝,防止 deeplink 劫持跳转到非预期页面
        private val ALLOWED_PATHS = setOf(
            PATH_CHAT, PATH_STATUS, PATH_SHOP, PATH_SETTINGS,
            PATH_PLUGINS, PATH_MEMORY, PATH_STUDY, PATH_PERSONA, PATH_TOOLS
        )
    }
    
    private val _pendingDeepLink = MutableStateFlow<DeepLinkData?>(null)
    val pendingDeepLink: StateFlow<DeepLinkData?> = _pendingDeepLink.asStateFlow()
    
    /**
     * 处理 Intent 中的深度链接
     * 
     * @param intent 应用接收到的 Intent
     * @return 解析后的深度链接数据，如果不是深度链接则返回 null
     */
    fun handleIntent(intent: Intent): DeepLinkData? {
        val uri = intent.data ?: return null

        if (uri.scheme != SCHEME) {
            return null
        }

        val deepLinkData = parseUri(uri) ?: return null  // path 不在白名单时拒绝

        // 设置待处理的深度链接
        _pendingDeepLink.value = deepLinkData

        return deepLinkData
    }
    
    /**
     * 解析 URI
     *
     * 安全加固:path 必须在白名单内,否则返回 null 拒绝处理。
     */
    private fun parseUri(uri: Uri): DeepLinkData? {
        val path = uri.host ?: uri.path?.removePrefix("/") ?: ""
        if (path.lowercase() !in ALLOWED_PATHS) return null
        val params = parseQueryParams(uri)

        return DeepLinkData(
            action = determineAction(path, params),
            screen = determineScreen(path),
            params = params
        )
    }
    
    /**
     * 解析查询参数。
     *
     * 安全加固:对参数值做长度限制(单个值最多 2000 字符),
     * 防止恶意 deeplink 塞超长文本导致 UI OOM 或 ANR。
     */
    private fun parseQueryParams(uri: Uri): Map<String, String> {
        val params = mutableMapOf<String, String>()

        uri.queryParameterNames.forEach { name ->
            uri.getQueryParameter(name)?.let { value ->
                params[name] = value.take(2000)
            }
        }

        return params
    }
    
    /**
     * 确定操作
     */
    private fun determineAction(@Suppress("UNUSED_PARAMETER") path: String, params: Map<String, String>): String {
        return when {
            params.containsKey("text") -> "prefill"
            params.containsKey("session_id") -> "open_session"
            params.containsKey("item_id") -> "open_item"
            else -> "navigate"
        }
    }
    
    /**
     * 确定目标页面
     */
    private fun determineScreen(path: String): String {
        return when (path.lowercase()) {
            PATH_CHAT -> "chat"
            PATH_STATUS -> "status"
            PATH_SHOP -> "shop"
            PATH_SETTINGS -> "settings"
            PATH_PLUGINS -> "plugins"
            PATH_MEMORY -> "memory"
            PATH_STUDY -> "study"
            PATH_PERSONA -> "persona"
            PATH_TOOLS -> "tools"
            else -> "chat"
        }
    }
    
    /**
     * 清除待处理的深度链接
     */
    fun clearPendingDeepLink() {
        _pendingDeepLink.value = null
    }
    
    /**
     * 构建聊天深度链接
     */
    fun buildChatDeepLink(
        prefillText: String? = null,
        sessionId: String? = null
    ): Uri {
        val uriBuilder = Uri.Builder()
            .scheme(SCHEME)
            .authority(PATH_CHAT)
        
        prefillText?.let { uriBuilder.appendQueryParameter("text", it) }
        sessionId?.let { uriBuilder.appendQueryParameter("session_id", it) }
        
        return uriBuilder.build()
    }
    
    /**
     * 构建商店深度链接
     */
    fun buildShopDeepLink(itemId: String? = null): Uri {
        val uriBuilder = Uri.Builder()
            .scheme(SCHEME)
            .authority(PATH_SHOP)
        
        itemId?.let { uriBuilder.appendQueryParameter("item_id", it) }
        
        return uriBuilder.build()
    }
}
