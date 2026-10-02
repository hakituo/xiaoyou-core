package com.aveline.ai.mobile.presentation.chat

import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.RoleScopedPreferences
import com.aveline.ai.mobile.domain.models.AIModel
import com.aveline.ai.mobile.domain.repository.PluginsRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * 角色级模型状态控制器。
 *
 * 这里只维护 role -> model id/route，不再调用全局 /models/switch。
 * 真正生成时由 [requestModelRoute] 把该角色保存的 route 放进当前 HTTP 请求，
 * 因而多个角色、多个客户端或并发请求不会通过后端全局模型互相污染。
 *
 * [pluginsRepository] 仅在生产环境用于读取模型列表；JVM 单测可不提供它，避免为了
 * ViewModel 的纯逻辑测试去构造网络仓库。生产 Hilt 注入仍会提供真实实现。
 */
class RoleModelController(
    private val scope: CoroutineScope,
    private val preferences: RoleScopedPreferences,
    private val pluginsRepository: PluginsRepository?,
    private val getCurrentRole: () -> String?
) {
    companion object {
        private const val TAG = "RoleModelController"
    }

    private val _availableModels = MutableStateFlow<List<AIModel>>(emptyList())
    val availableModels: StateFlow<List<AIModel>> = _availableModels.asStateFlow()

    private val _selectedModel = MutableStateFlow<AIModel?>(null)
    val selectedModel: StateFlow<AIModel?> = _selectedModel.asStateFlow()

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    fun loadForRole(role: String) {
        if (role.isBlank()) return
        scope.launch {
            _isLoading.value = true
            _error.value = null

            val repository = pluginsRepository
            if (repository == null) {
                // 纯 JVM 单测不关心伴侣模型列表；保持空状态即可。
                if (getCurrentRole() == role) {
                    _availableModels.value = emptyList()
                    _selectedModel.value = null
                    _isLoading.value = false
                }
                return@launch
            }

            runCatching { repository.getModels() }
                .onSuccess { models ->
                    // 网络返回时如果用户已经去了另一个角色，旧请求不能覆盖新页面状态。
                    if (getCurrentRole() != role) return@onSuccess

                    _availableModels.value = models
                    val savedId = preferences.getModelId(role)
                    val selected = savedId?.let { id ->
                        models.firstOrNull { it.id == id && it.isAvailable }
                    }
                    _selectedModel.value = selected

                    // 兼容前一版只保存 model id 的角色偏好：拿到模型表后补齐真实 route。
                    if (selected != null) {
                        val route = selected.route.ifBlank { selected.id }
                        if (preferences.getModelRoute(role) != route) {
                            preferences.setModel(role, selected.id, route)
                        }
                    }

                    _isLoading.value = false
                    _error.value = if (savedId != null && selected == null) {
                        "该角色之前选择的模型已不可用，请重新选择"
                    } else null
                }
                .onFailure { e ->
                    if (getCurrentRole() != role) return@onFailure
                    _isLoading.value = false
                    _error.value = "模型加载失败: ${e.message ?: "未知错误"}"
                }
        }
    }

    /**
     * 只保存当前角色自己的模型，不再修改 AppPreferences 或后端全局模型。
     */
    fun selectForCurrentRole(modelId: String) {
        val role = getCurrentRole()?.takeIf { it.isNotBlank() } ?: run {
            _error.value = "当前聊天没有角色信息，无法保存角色模型"
            return
        }
        val model = _availableModels.value.firstOrNull { it.id == modelId && it.isAvailable } ?: run {
            _error.value = "模型列表中没有找到可用模型: $modelId"
            return
        }

        val route = model.route.ifBlank { model.id }
        preferences.setModel(role, model.id, route)
        _selectedModel.value = model
        _error.value = null
        Log.d(TAG, "保存角色模型: role=$role model=${model.id} route=$route")
    }

    /**
     * 返回当前角色本次生成应显式携带的模型 route。
     * 返回 null 表示该角色从未手选模型，继续让 persona/default 路由接管。
     */
    fun requestModelRoute(): String? {
        val role = getCurrentRole()?.takeIf { it.isNotBlank() } ?: return null
        preferences.getModelRoute(role)?.let { return it }

        // 兼容刚从旧偏好升级、模型表已经加载但 route 尚未落盘的极短窗口。
        val savedId = preferences.getModelId(role) ?: return null
        val model = _availableModels.value.firstOrNull { it.id == savedId && it.isAvailable } ?: return null
        val route = model.route.ifBlank { model.id }
        preferences.setModel(role, model.id, route)
        return route
    }
}
