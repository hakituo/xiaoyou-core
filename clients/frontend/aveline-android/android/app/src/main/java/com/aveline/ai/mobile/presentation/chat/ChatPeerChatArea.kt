package com.aveline.ai.mobile.presentation.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.PeerChatMessage
import com.aveline.ai.mobile.presentation.components.PeerChatHeader
import com.aveline.ai.mobile.presentation.components.PeerChatMessageList

/** 双角色对话的进度按"满 10 轮"估算（与后端剧本长度一致）。 */
private const val PEER_CHAT_TOTAL_ROUNDS = 10f

/**
 * 双角色对话区域（两个角色互聊，主聊天区上方折叠展示）。
 *
 * @param visible 是否显示（由页面的 showPeerChat 开关控制）
 * @param messages 互聊消息；为空时整块隐藏
 */
@Composable
fun ChatPeerChatArea(
    messages: List<PeerChatMessage>,
    topic: String,
    isActive: Boolean,
    visible: Boolean,
    onClose: () -> Unit,
    modifier: Modifier = Modifier
) {
    AnimatedVisibility(
        visible = visible && messages.isNotEmpty(),
        enter = slideInVertically(initialOffsetY = { -it }) + fadeIn(),
        exit = slideOutVertically(targetOffsetY = { -it }) + fadeOut()
    ) {
        Column(modifier = modifier) {
            PeerChatHeader(
                topic = topic,
                // TODO: 参与者目前由后端剧本固定，待后端在 peer_chat 状态里下发后再改成动态取值
                participant1 = "Aveline",
                participant2 = "Ling",
                isActive = isActive,
                progress = if (messages.isNotEmpty()) {
                    messages.size.toFloat() / PEER_CHAT_TOTAL_ROUNDS
                } else 0f,
                onClose = onClose
            )

            PeerChatMessageList(
                messages = messages,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 200.dp)
            )

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(1.dp)
                    .background(Color(0x1AFFFFFF))
            )
        }
    }
}
