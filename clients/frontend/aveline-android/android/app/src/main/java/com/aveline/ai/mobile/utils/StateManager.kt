package com.aveline.ai.mobile.utils

import android.content.Context
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import java.util.concurrent.Executors
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 应用状态数据
 */
@Serializable
data class AppState(
    val currentScreen: String = "chat",
    val currentSessionId: String? = null,
    val scrollPosition: Int = 0,
    val lastActiveTime: Long = System.currentTimeMillis()
)

/**
 * 状态管理器
 * 
 * 管理应用状态的保存和恢复
 * 
 * Requirements: 23.3, 23.4
 */
@Singleton
class StateManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val appPreferences: AppPreferences,
    private val json: Json
) {
    private val stateFile: File by lazy {
        File(context.filesDir, "app_state.json")
    }

    /**
     * 单线程执行器,用于后台执行文件 IO,避免阻塞主线程。
     * 单线程保证写顺序一致(后写的状态不会先落盘覆盖新状态)。
     */
    private val ioExecutor = Executors.newSingleThreadExecutor { r ->
        Thread(r, "StateManager-IO").apply { isDaemon = true }
    }

    private val _appState = MutableStateFlow(AppState())
    val appState: StateFlow<AppState> = _appState.asStateFlow()

    init {
        // 修复 P0-30: 原实现 restoreState() 在 init 同步执行,导致 Hilt 注入(主线程)时
        // stateFile.readText() + json.decodeFromString 阻塞 UI,冷启动阶段可感知卡顿。
        // 改为后台单线程异步读取,读取完成后通过 StateFlow 发布,UI 层以默认 AppState 为
        // 初始值随后自动过渡到持久化状态(与写入采用的 ioExecutor 是同一个,保证可见性)。
        ioExecutor.execute {
            restoreState()
        }
    }

    /**
     * 保存当前状态。
     *
     * 修复 P0-19: 原实现 stateFile.writeText 在调用线程(可能是主线程)同步 IO,
     * 频繁调用(updateCurrentScreen/updateCurrentSession)会卡 UI。
     * 改为提交到后台单线程执行器,序列化在调用线程(快),写文件在后台(慢)。
     */
    fun saveState() {
        try {
            val stateJson = json.encodeToString(_appState.value)
            ioExecutor.execute {
                try {
                    stateFile.writeText(stateJson)
                } catch (e: Exception) {
                    // 后台写入失败忽略,下次保存会覆盖
                }
            }
        } catch (e: Exception) {
            // 序列化失败忽略
        }
    }
    
    /**
     * 恢复状态
     */
    private fun restoreState() {
        try {
            if (stateFile.exists()) {
                val stateJson = stateFile.readText()
                val state = json.decodeFromString<AppState>(stateJson)
                _appState.value = state

                // 同步到 AppPreferences：仅在当前尚无会话时兜底恢复。
                // restoreState 在后台线程异步执行，可能晚于用户进入某角色聊天页
                // （那时已切好 currentSessionId）；若无条件覆盖会把会话冲回旧值，
                // 表现为聊天窗口显示别的角色的记录。
                state.currentSessionId?.let { restored ->
                    if (appPreferences.currentSessionId.isNullOrBlank()) {
                        appPreferences.currentSessionId = restored
                    }
                }
            }
        } catch (e: Exception) {
            // 恢复失败，使用默认状态
            _appState.value = AppState()
        }
    }
    
    /**
     * 更新当前页面
     */
    fun updateCurrentScreen(screen: String) {
        _appState.value = _appState.value.copy(
            currentScreen = screen,
            lastActiveTime = System.currentTimeMillis()
        )
        saveState()
    }
    
    /**
     * 更新当前会话 ID
     */
    fun updateCurrentSession(sessionId: String?) {
        _appState.value = _appState.value.copy(
            currentSessionId = sessionId,
            lastActiveTime = System.currentTimeMillis()
        )
        appPreferences.currentSessionId = sessionId
        saveState()
    }
    
    /**
     * 更新滚动位置
     */
    fun updateScrollPosition(position: Int) {
        _appState.value = _appState.value.copy(
            scrollPosition = position
        )
        // 不立即保存，避免频繁 IO
    }
    
    /**
     * 记录活动时间
     */
    fun recordActivity() {
        _appState.value = _appState.value.copy(
            lastActiveTime = System.currentTimeMillis()
        )
    }
    
    /**
     * 获取当前会话 ID
     */
    fun getCurrentSessionId(): String? {
        return _appState.value.currentSessionId
    }
    
    /**
     * 获取当前页面
     */
    fun getCurrentScreen(): String {
        return _appState.value.currentScreen
    }
    
    /**
     * 获取滚动位置
     */
    fun getScrollPosition(): Int {
        return _appState.value.scrollPosition
    }
    
    /**
     * 获取上次活动时间
     */
    fun getLastActiveTime(): Long {
        return _appState.value.lastActiveTime
    }
    
    /**
     * 检查是否需要恢复状态
     * 
     * @param thresholdMs 阈值（毫秒），默认 5 分钟
     */
    fun shouldRestoreState(thresholdMs: Long = 5 * 60 * 1000): Boolean {
        val elapsed = System.currentTimeMillis() - _appState.value.lastActiveTime
        return elapsed < thresholdMs && _appState.value.currentSessionId != null
    }
    
    /**
     * 清除状态
     */
    fun clearState() {
        _appState.value = AppState()
        if (stateFile.exists()) {
            stateFile.delete()
        }
        appPreferences.currentSessionId = null
    }
    
    /**
     * 重置为默认状态
     */
    fun resetToDefault() {
        _appState.value = AppState()
        saveState()
    }
}
