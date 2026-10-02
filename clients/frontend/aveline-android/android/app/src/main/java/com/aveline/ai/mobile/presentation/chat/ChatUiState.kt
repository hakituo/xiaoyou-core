package com.aveline.ai.mobile.presentation.chat

import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.domain.models.PeerChatMessage
import com.aveline.ai.mobile.domain.models.Session
import com.aveline.ai.mobile.services.UploadState
import com.aveline.ai.mobile.services.VoiceInputState

/**
 * 聊天界面加载状态
 */
sealed class LoadingState {
    object NotLoaded : LoadingState()
    object Loading : LoadingState()
    data class Loaded(val data: List<Message>) : LoadingState()
}

/**
 * 聊天界面 UI 状态
 */
data class ChatUiState(
    val messages: List<Message> = emptyList(),
    val hasOlderMessages: Boolean = false,
    val currentSession: Session? = null,
    val isTyping: Boolean = false,
    val showTypingIndicator: Boolean = false,
    /**
     * 有**本地发起的生成**在跑的会话 id；没有则为 null。
     *
     * 为什么不能只看 [isTyping]：isTyping 同时被 WebSocket 通道置位（角色主动关怀、
     * 对方角色发来的消息，见 ChatFlushManager.handleResponseChunk / onResponseReset），
     * 那种回复是服务端推过来的，本地没有任务可取消。输入栏只有在
     * `generatingSessionId == currentSession?.id` 时才把按钮切成「停止」，
     * 否则会画出一个按下去毫无反应的停止键；在别的会话页面上更会去停错人。
     */
    val generatingSessionId: String? = null,
    val isLoading: Boolean = false,
    val error: String? = null,
    val inputText: String = "",
    val currentEmotion: Emotion? = null,
    val connectionState: WebSocketManager.ConnectionState = WebSocketManager.ConnectionState.DISCONNECTED,
    val playingMessageId: String? = null,
    /** 正在合成语音的消息 id（UI 用它显示转圈；与"正在播放"区分开）。 */
    val ttsLoadingMessageId: String? = null,
    val voiceInputState: VoiceInputState = VoiceInputState.Idle,
    val voiceAmplitude: Float = 0f,
    val voicePartialText: String = "",
    val isRecording: Boolean = false,
    val uploadState: UploadState = UploadState.Idle,
    /** 已上传、等待用户点发送的图片地址（点发送或取消后清空）。 */
    val lastUploadedImageUrl: String? = null,
    /**
     * 已上传、等待用户点发送的视频地址（点发送或取消后清空）。
     *
     * 注意：底部输入栏已按要求下线录像入口（只保留麦克风与"+"），该字段当前不会被写入；
     * 发送链路（[ChatUploadHelper.sendVideoMessage]、sendPendingOrText 的视频分支）保留，
     * 便于后续恢复入口时无需重写。
     */
    val pendingVideoUrl: String? = null,
    /** 图片消息发送前的视觉识别中（让 UI 显示"正在识别图片"）。 */
    val isAnalyzingImage: Boolean = false,
    val loadingState: LoadingState = LoadingState.NotLoaded,
    /** 其他角色的主动消息未读总数（>0 时聊天页返回键右上角显示小圆点） */
    val unreadFromOthers: Int = 0,
    // 双角色对话相关状态
    val peerChatMessages: List<PeerChatMessage> = emptyList(),
    val isPeerChatActive: Boolean = false,
    val peerChatScriptId: String? = null,
    val peerChatTopic: String = "",
    val showPeerChat: Boolean = false  // 是否显示双角色对话
)
