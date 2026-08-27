package com.aveline.ai.mobile.presentation.chat

import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.services.TTSEngine
import com.aveline.ai.mobile.services.TTSState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 负责 TTS（语音播报）的状态观察与播放控制。
 *
 * 从 ChatViewModel 拆出，职责：
 * - 监听 [TTSEngine.state]，把"正在播放的消息 id"写入 uiState
 * - 单条消息播报：togglePlay / pause / resume / stop
 * - 流式边收边播：startStreamingIfEnabled / appendStreamingChunk /
 *   finishStreamingIfEnabled / stopIfEnabled（供 sendMessage 的 HTTP SSE 路径调用）
 *
 * 所有"是否开启自动播报 / 用哪个音色"的决策都内聚在本类，
 * 调用方无需感知 AppPreferences 细节。
 *
 * 角色默认语音（与 QQ 对齐）：每个角色有自己的默认音色（参考音频），
 * 通过 [getPersonaFilename] 拿到当前 persona filename，再按 [PERSONA_VOICE_MAP]
 * 解析对应参考音频；未命中时回退到全局 [AppPreferences.selectedVoiceId]。
 *
 * @param scope ViewModel 的协程作用域
 * @param uiState UI 状态流，播放状态写入此流
 * @param ttsEngine 底层 TTS 引擎
 * @param appPreferences 读取自动播报开关与所选音色
 * @param getPersonaFilename 获取当前 persona filename 的回调（用于按角色解析默认音色）
 */
class ChatTtsController(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val ttsEngine: TTSEngine,
    private val appPreferences: AppPreferences,
    private val getPersonaFilename: () -> String? = { null }
) {
    companion object {
        private const val TAG = "ChatTtsController"

        /**
         * persona filename 关键词 -> 默认参考音频（克隆音色）。
         * 与后端 config/settings_model.py 的 persona_audio_map 对齐，
         * 让 App 端角色聊天像 QQ 一样按角色使用各自默认的语音。
         */
        private val PERSONA_VOICE_MAP: Map<String, String> = mapOf(
            "aveline" to "ref_audio/female/ref_calm.wav",
            "ling" to "ref_audio/female/玲.wav"
        )
    }
    /** 监听 TTS 状态：把正在播放的消息 id 同步到 uiState（UI 据此显示播放态图标）。 */
    fun observeState() {
        scope.launch {
            ttsEngine.state.collect { state ->
                val playingId = when (state) {
                    is TTSState.Playing -> state.messageId
                    is TTSState.Paused -> state.messageId
                    else -> null
                }
                uiState.update { it.copy(playingMessageId = playingId) }
            }
        }
    }

    /** 点击消息气泡上的播报按钮：正在播放则停止，否则开始播报（用户消息不播）。 */
    fun togglePlay(messageId: String) {
        val message = uiState.value.messages.find { it.id == messageId }
        if (message == null || message.isUser) return
        if (uiState.value.playingMessageId == messageId) {
            ttsEngine.stop()
        } else {
            ttsEngine.playMessage(messageId, message.text, selectedVoiceId())
        }
    }

    fun pause() { ttsEngine.pause() }

    fun resume() { ttsEngine.resume() }

    fun stop() { ttsEngine.stop() }

    /** 自动播报开启时，为流式消息启动边收边播。 */
    fun startStreamingIfEnabled(messageId: String) {
        if (appPreferences.autoTtsEnabled) {
            ttsEngine.startStreamingPlayback(messageId, selectedVoiceId())
        }
    }

    /** 自动播报开启时，把流式增量文本喂给 TTS 分句合成。 */
    fun appendStreamingChunk(content: String) {
        if (appPreferences.autoTtsEnabled) {
            ttsEngine.appendStreamingChunk(content)
        }
    }

    /** 自动播报开启时，流式结束冲刷剩余缓冲并关闭合成通道。 */
    fun finishStreamingIfEnabled() {
        if (appPreferences.autoTtsEnabled) {
            ttsEngine.finishStreamingPlayback()
        }
    }

    /** 自动播报开启时，停止播放（生成失败等异常路径）。 */
    fun stopIfEnabled() {
        if (appPreferences.autoTtsEnabled) {
            ttsEngine.stop()
        }
    }

    /**
     * 解析当前语音（参考音频）：
     * 1. 优先按当前 persona filename 匹配角色默认音色（与 QQ 对齐）；
     * 2. 未命中或用户手动设置了全局音色时，回退到全局 [AppPreferences.selectedVoiceId]。
     */
    private fun selectedVoiceId(): String? {
        val personaFilename = getPersonaFilename()
        if (!personaFilename.isNullOrBlank()) {
            val lower = personaFilename.lowercase()
            for ((key, voicePath) in PERSONA_VOICE_MAP) {
                if (key in lower) {
                    return voicePath
                }
            }
        }
        return appPreferences.selectedVoiceId.ifEmpty { null }
    }
}
