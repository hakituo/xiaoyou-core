package com.aveline.ai.mobile.presentation.chat

import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.domain.models.PeerChatMessage
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update

/**
 * 双角色对话处理器
 *
 * 负责处理 WebSocket 推送的双角色对话消息（剧本开始/消息/剧本结束），
 * 以及 UI 层的显示切换和清空操作。
 *
 * @param uiState          UI 状态流
 * @param generateMessageId 生成唯一消息 ID 的回调
 */
class ChatPeerChatHandler(
    private val uiState: MutableStateFlow<ChatUiState>,
    private val generateMessageId: () -> String
) {
    /**
     * 处理双角色对话消息：追加到 peerChatMessages 并显示
     */
    fun handlePeerChatMessage(message: WebSocketMessage.PeerChatMessage) {
        val peerMessage = PeerChatMessage(
            id = generateMessageId(),
            scriptId = message.scriptId,
            role = message.role,
            roleName = message.roleName,
            text = message.text,
            emotion = message.emotion,
            roundIndex = message.roundIndex,
            timestamp = message.timestamp
        )

        uiState.update { state ->
            state.copy(
                peerChatMessages = state.peerChatMessages + peerMessage,
                showPeerChat = true
            )
        }
    }

    /**
     * 处理双角色对话剧本开始：重置状态并设置剧本信息
     */
    fun handlePeerChatScriptStart(message: WebSocketMessage.PeerChatScriptStart) {
        uiState.update { state ->
            state.copy(
                isPeerChatActive = true,
                peerChatScriptId = message.scriptId,
                peerChatTopic = message.topic,
                peerChatMessages = emptyList(),
                showPeerChat = true
            )
        }
    }

    /**
     * 处理双角色对话剧本结束：标记结束，若提及用户则提示
     */
    fun handlePeerChatScriptEnd(message: WebSocketMessage.PeerChatScriptEnd) {
        uiState.update { state ->
            state.copy(
                isPeerChatActive = false,
                peerChatScriptId = null
            )
        }

        // 如果提及用户，显示提示
        if (message.mentionedUser) {
            uiState.update { it.copy(error = "她们聊到了你哦~") }
        }
    }

    /** 切换双角色对话显示 */
    fun togglePeerChat() {
        uiState.update { it.copy(showPeerChat = !it.showPeerChat) }
    }

    /** 清空双角色对话消息 */
    fun clearPeerChatMessages() {
        uiState.update { it.copy(peerChatMessages = emptyList()) }
    }
}
