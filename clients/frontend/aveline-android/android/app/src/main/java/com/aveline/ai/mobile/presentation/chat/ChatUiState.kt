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
    val currentSession: Session? = null,
    val isTyping: Boolean = false,
    val showTypingIndicator: Boolean = false,
    val isLoading: Boolean = false,
    val error: String? = null,
    val inputText: String = "",
    val currentEmotion: Emotion? = null,
    val connectionState: WebSocketManager.ConnectionState = WebSocketManager.ConnectionState.DISCONNECTED,
    val playingMessageId: String? = null,
    val voiceInputState: VoiceInputState = VoiceInputState.Idle,
    val voiceAmplitude: Float = 0f,
    val voicePartialText: String = "",
    val isRecording: Boolean = false,
    val uploadState: UploadState = UploadState.Idle,
    val lastUploadedImageUrl: String? = null,
    val loadingState: LoadingState = LoadingState.NotLoaded,
    // 双角色对话相关状态
    val peerChatMessages: List<PeerChatMessage> = emptyList(),
    val isPeerChatActive: Boolean = false,
    val peerChatScriptId: String? = null,
    val peerChatTopic: String = "",
    val showPeerChat: Boolean = false  // 是否显示双角色对话
)
