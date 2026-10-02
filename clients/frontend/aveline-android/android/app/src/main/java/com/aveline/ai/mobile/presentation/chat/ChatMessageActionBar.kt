package com.aveline.ai.mobile.presentation.chat

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.rounded.KeyboardArrowRight
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material.icons.rounded.MoreHoriz
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * ChatGPT 风格的消息操作栏。
 *
 * 操作与版本切换放在同一行，不再塞进消息气泡内部，也不再额外悬一排版本按钮。
 * AI：复制 / TTS / 重新生成 / 版本导航 / 更多。
 * 用户：编辑 / 版本导航 / 更多。
 */
@Composable
fun ChatMessageActionBar(
    message: Message,
    isPlaying: Boolean,
    isTtsLoading: Boolean,
    actions: ChatMessageActions,
    modifier: Modifier = Modifier
) {
    var showMore by remember(message.id) { mutableStateOf(false) }

    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(
                start = 12.dp,
                end = 12.dp,
                top = 0.dp,
                bottom = 4.dp
            ),
        horizontalArrangement = if (message.isUser) Arrangement.End else Arrangement.Start,
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (message.isUser) {
            ToolbarButton(
                onClick = { actions.onEdit(message.id, message.text) },
                contentDescription = "编辑消息"
            ) {
                Icon(
                    imageVector = Icons.Rounded.Edit,
                    contentDescription = null,
                    tint = TextSecondary,
                    modifier = Modifier.size(18.dp)
                )
            }
        } else {
            ToolbarButton(
                onClick = { actions.onCopy(message.text) },
                contentDescription = "复制"
            ) {
                Icon(
                    imageVector = Icons.Rounded.ContentCopy,
                    contentDescription = null,
                    tint = TextSecondary,
                    modifier = Modifier.size(18.dp)
                )
            }

            ToolbarButton(
                onClick = { actions.onPlayTTS(message.id) },
                contentDescription = if (isPlaying) "停止播放" else "播放语音"
            ) {
                if (isTtsLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp,
                        color = TextSecondary
                    )
                } else {
                    Icon(
                        imageVector = if (isPlaying) Icons.Rounded.Stop else Icons.Rounded.PlayArrow,
                        contentDescription = null,
                        tint = TextSecondary,
                        modifier = Modifier.size(18.dp)
                    )
                }
            }

            ToolbarButton(
                onClick = { actions.onRegenerate(message.id) },
                contentDescription = "重新生成"
            ) {
                Icon(
                    imageVector = Icons.Rounded.Refresh,
                    contentDescription = null,
                    tint = TextSecondary,
                    modifier = Modifier.size(18.dp)
                )
            }
        }

        if (message.variantCount > 1) {
            ToolbarButton(
                onClick = { actions.onSwitchVariant(message.id, -1) },
                contentDescription = "上一个版本",
                enabled = message.variantIndex > 0
            ) {
                Icon(
                    imageVector = Icons.AutoMirrored.Rounded.KeyboardArrowLeft,
                    contentDescription = null,
                    tint = TextSecondary,
                    modifier = Modifier.size(20.dp)
                )
            }

            Text(
                text = "${message.variantIndex + 1}/${message.variantCount}",
                style = MaterialTheme.typography.labelMedium,
                color = TextSecondary,
                modifier = Modifier.padding(horizontal = 2.dp)
            )

            ToolbarButton(
                onClick = { actions.onSwitchVariant(message.id, 1) },
                contentDescription = "下一个版本",
                enabled = message.variantIndex < message.variantCount - 1
            ) {
                Icon(
                    imageVector = Icons.AutoMirrored.Rounded.KeyboardArrowRight,
                    contentDescription = null,
                    tint = TextSecondary,
                    modifier = Modifier.size(20.dp)
                )
            }
        }

        Box {
            ToolbarButton(
                onClick = { showMore = true },
                contentDescription = "更多"
            ) {
                Icon(
                    imageVector = Icons.Rounded.MoreHoriz,
                    contentDescription = null,
                    tint = TextSecondary,
                    modifier = Modifier.size(18.dp)
                )
            }

            DropdownMenu(
                expanded = showMore,
                onDismissRequest = { showMore = false }
            ) {
                if (message.isUser) {
                    DropdownMenuItem(
                        text = { Text("复制") },
                        leadingIcon = {
                            Icon(Icons.Rounded.ContentCopy, contentDescription = null)
                        },
                        onClick = {
                            showMore = false
                            actions.onCopy(message.text)
                        }
                    )
                }
                DropdownMenuItem(
                    text = { Text("删除") },
                    leadingIcon = {
                        Icon(
                            imageVector = Icons.Rounded.Delete,
                            contentDescription = null,
                            tint = TextTertiary
                        )
                    },
                    onClick = {
                        showMore = false
                        actions.onDelete(message.id)
                    }
                )
            }
        }
    }
}

@Composable
private fun ToolbarButton(
    onClick: () -> Unit,
    contentDescription: String,
    enabled: Boolean = true,
    content: @Composable () -> Unit
) {
    IconButton(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier
            .size(36.dp)
            .semantics { this.contentDescription = contentDescription }
    ) {
        Box(
            modifier = Modifier.size(24.dp),
            contentAlignment = Alignment.Center
        ) {
            content()
        }
    }
}
