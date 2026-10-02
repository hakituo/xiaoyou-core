package com.aveline.ai.mobile.presentation.chat

import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import com.aveline.ai.mobile.presentation.components.HorizontalContentGestureState

/**
 * 聊天页内容区（从 ChatScreen.kt 拆出）：双角色对话折叠区 + 消息列表 + 消息动作。
 *
 * 左滑手势的参数仍在 ChatScreen 组装（那里才有屏幕尺寸与面板状态），
 * 通过 [modifier] 传进来，所以这里不感知手势细节。
 *
 * @param forceFollowLatestRequest 用户主动发送的事件序号（只影响滚动语义）
 * @param onEditMessage 点某条消息的"编辑"时回调 (messageId, text)，用于打开编辑对话框
 */
@Composable
internal fun ChatContentArea(
    viewModel: ChatViewModel,
    uiState: ChatUiState,
    displayName: String,
    forceFollowLatestRequest: Int,
    horizontalContentGestureState: HorizontalContentGestureState,
    onEditMessage: (String, String) -> Unit,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier) {
        ChatPeerChatArea(
            messages = uiState.peerChatMessages,
            topic = uiState.peerChatTopic,
            isActive = uiState.isPeerChatActive,
            visible = uiState.showPeerChat,
            onClose = { viewModel.togglePeerChat() }
        )

        ChatMessageList(
            messages = uiState.messages,
            sessionId = uiState.currentSession?.id,
            isLoading = uiState.isLoading,
            loadingState = uiState.loadingState,
            showTypingIndicator = uiState.showTypingIndicator,
            playingMessageId = uiState.playingMessageId,
            ttsLoadingMessageId = uiState.ttsLoadingMessageId,
            displayName = displayName,
            horizontalContentGestureState = horizontalContentGestureState,
            forceFollowLatestRequest = forceFollowLatestRequest,
            hasOlderMessages = uiState.hasOlderMessages,
            onLoadOlderMessages = viewModel::loadOlderMessages,
            actions = remember(viewModel) {
                ChatMessageActions(
                    onPlayTTS = viewModel::toggleTTS,
                    onCopy = viewModel::copyMessage,
                    onDelete = viewModel::deleteMessage,
                    onRegenerate = { viewModel.regenerateMessage(it) },
                    onEdit = { id, text -> onEditMessage(id, text) },
                    onSwitchVariant = viewModel::selectMessageVariant
                )
            },
            modifier = Modifier.weight(1f)
        )
    }
}
