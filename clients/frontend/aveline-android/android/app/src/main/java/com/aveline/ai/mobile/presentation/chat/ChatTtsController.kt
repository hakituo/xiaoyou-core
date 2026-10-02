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
 * 角色默认语音与 QQ VoiceService 对齐：persona 命中时使用后端注册的 voice 名称；
 * 未命中时回退到全局 [AppPreferences.selectedVoiceId]（通常是参考音频路径）。
 *
 * @param scope ViewModel 的协程作用域
 * @param uiState UI 状态流，播放状态写入此流
 * @param ttsEngine 底层 TTS 引擎
 * @param appPreferences 读取自动播报开关与所选音色
 * @param getPersonaDefaultVoice 获取当前对话 persona 默认音色名的回调（后端 default_voice）
 */
class ChatTtsController(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val ttsEngine: TTSEngine,
    private val appPreferences: AppPreferences,
    /** 用户为当前对话 persona 手选的音色名（优先于角色默认音色）。 */
    private val getPersonaVoiceOverride: () -> String? = { null },
    /** 当前对话 persona 的默认音色名，来自后端 persona API 的 default_voice。 */
    private val getPersonaDefaultVoice: () -> String? = { null }
) {
    companion object {
        private const val VOICE_SELECTOR_PREFIX = "voice:"
    }

    /** 监听 TTS 状态：把正在播放/正在合成的消息 id 同步到 uiState（UI 据此显示播放态）。 */
    fun observeState() {
        scope.launch {
            ttsEngine.state.collect { state ->
                val playingId = when (state) {
                    is TTSState.Playing -> state.messageId
                    is TTSState.Paused -> state.messageId
                    else -> null
                }
                // 合成期间（Loading）也要带出 messageId，否则 UI 不知道哪条消息在加载，
                // 表现就是"点了播放键毫无反应"。
                val loadingId = (state as? TTSState.Loading)?.messageId
                uiState.update {
                    it.copy(
                        playingMessageId = playingId,
                        ttsLoadingMessageId = loadingId
                    )
                }
            }
        }
    }

    /** 点击消息气泡上的播报按钮：正在播放则停止，否则开始播报（用户消息不播）。 */
    fun togglePlay(messageId: String) {
        val message = uiState.value.messages.find { it.id == messageId }
        if (message == null || message.isUser) return
        // 播放中或合成中再点一次都视为"停止"，否则用户点了转圈却取消不掉。
        if (uiState.value.playingMessageId == messageId ||
            uiState.value.ttsLoadingMessageId == messageId
        ) {
            ttsEngine.stop()
        } else {
            ttsEngine.playMessage(messageId, message.text, selectedVoiceSelector())
        }
    }

    fun pause() { ttsEngine.pause() }

    fun resume() { ttsEngine.resume() }

    fun stop() { ttsEngine.stop() }

    /** 自动播报开启时，为流式消息启动边收边播。 */
    fun startStreamingIfEnabled(messageId: String) {
        if (appPreferences.autoTtsEnabled) {
            ttsEngine.startStreamingPlayback(messageId, selectedVoiceSelector())
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
     * 解析当前语音选择：
     * 1. 后端给出了当前 persona 的默认音色（app.yaml voice_map 里的角色名）→ voice:<角色名>，
     *    由 TTSRequest 转成真正的 voice 字段，与 QQ 端 VoiceService 走同一个源；
     * 2. 未命中时保留用户全局音色设置，继续作为 reference_audio 使用。
     *
     * 这里刻意不再维护"角色 -> 音色"硬编码表：历史上抄了 QQ 的 role_id 映射却把
     * fallback 写成全局音色，导致Ye / Aveline 等未登记角色解析失败。
     */
    private fun selectedVoiceSelector(): String? {
        // 1. 用户手选（最高优先级，后端返回值不会覆盖它）
        getPersonaVoiceOverride()?.takeIf { it.isNotBlank() }?.let {
            return "$VOICE_SELECTOR_PREFIX$it"
        }
        // 2. 后端下发的角色默认音色（app.yaml voice_map 的角色名）
        getPersonaDefaultVoice()?.takeIf { it.isNotBlank() }?.let {
            return "$VOICE_SELECTOR_PREFIX$it"
        }
        // 3. 全局音色设置（参考音频等），交后端兜底
        return appPreferences.selectedVoiceId.ifEmpty { null }
    }
}
