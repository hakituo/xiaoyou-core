package com.aveline.ai.mobile.presentation.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.PeerChatMessage

/**
 * 双角色对话消息气泡
 */
@Composable
fun PeerChatMessageBubble(
    message: PeerChatMessage,
    modifier: Modifier = Modifier
) {
    val roleColor = Color(PeerChatMessage.getRoleColor(message.role))
    val avatar = PeerChatMessage.getRoleAvatar(message.role)
    
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        // 角色头像
        Box(
            modifier = Modifier
                .size(36.dp)
                .clip(CircleShape)
                .background(roleColor.copy(alpha = 0.2f))
                .border(1.dp, roleColor.copy(alpha = 0.3f), CircleShape),
            contentAlignment = Alignment.Center
        ) {
            Text(
                text = avatar,
                fontSize = 18.sp
            )
        }
        
        // 消息内容
        Column(
            modifier = Modifier.weight(1f)
        ) {
            // 角色名称
            Text(
                text = message.roleName,
                style = MaterialTheme.typography.labelSmall.copy(
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 0.5.sp
                ),
                color = roleColor
            )
            
            Spacer(modifier = Modifier.height(2.dp))
            
            // 消息气泡
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = roleColor.copy(alpha = 0.1f)
                ),
                shape = RoundedCornerShape(12.dp, 12.dp, 12.dp, 4.dp)
            ) {
                Text(
                    text = message.text,
                    style = MaterialTheme.typography.bodyMedium,
                    color = Color.White,
                    modifier = Modifier.padding(10.dp)
                )
            }
        }
    }
}

/**
 * 双角色对话头部
 */
@Composable
fun PeerChatHeader(
    topic: String,
    participant1: String,
    participant2: String,
    isActive: Boolean,
    progress: Float,
    onClose: () -> Unit,
    modifier: Modifier = Modifier
) {
    Card(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 8.dp, vertical = 4.dp),
        colors = CardDefaults.cardColors(
            containerColor = Color(0x1A9C27B0)
        ),
        shape = RoundedCornerShape(12.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    // 双人图标
                    Icon(
                        imageVector = Icons.Default.Person,
                        contentDescription = null,
                        tint = Color(0xFF9C27B0),
                        modifier = Modifier.size(16.dp)
                    )
                    
                    Text(
                        text = "双角色对话",
                        style = MaterialTheme.typography.labelMedium.copy(
                            fontWeight = FontWeight.Bold,
                            letterSpacing = 1.sp
                        ),
                        color = Color(0xFF9C27B0)
                    )
                    
                    if (isActive) {
                        Box(
                            modifier = Modifier
                                .size(6.dp)
                                .clip(CircleShape)
                                .background(Color(0xFF4CAF50))
                        )
                    }
                }
                
                IconButton(
                    onClick = onClose,
                    modifier = Modifier.size(24.dp)
                ) {
                    Icon(
                        imageVector = Icons.Default.Close,
                        contentDescription = "关闭",
                        tint = Color(0x80FFFFFF),
                        modifier = Modifier.size(16.dp)
                    )
                }
            }
            
            if (topic.isNotBlank()) {
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "话题: $topic",
                    style = MaterialTheme.typography.labelSmall,
                    color = Color(0x80FFFFFF)
                )
            }
            
            if (isActive && progress > 0) {
                Spacer(modifier = Modifier.height(8.dp))
                LinearProgressIndicator(
                    progress = { progress },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(2.dp)
                        .clip(RoundedCornerShape(1.dp)),
                    color = Color(0xFF9C27B0),
                    trackColor = Color(0x1A9C27B0)
                )
            }
            
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = "$participant1 ↔ $participant2",
                style = MaterialTheme.typography.labelSmall,
                color = Color(0x60FFFFFF)
            )
        }
    }
}

/**
 * 双角色对话列表
 *
 * 使用 LazyColumn 懒加载:peer_chat 消息可能持续累积,
 * Column+forEach 会在每帧全量组合所有气泡,消息多了会卡顿。
 * 这里外层是固定高度容器(heightIn(max=200.dp)),适合用 LazyColumn。
 */
@Composable
fun PeerChatMessageList(
    messages: List<PeerChatMessage>,
    modifier: Modifier = Modifier
) {
    LazyColumn(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(2.dp)
    ) {
        items(
            items = messages,
            // 用消息 id 做 key,避免 LazyColumn 复用 item 时状态错乱
            key = { it.id }
        ) { message ->
            PeerChatMessageBubble(message = message)
        }
    }
}
