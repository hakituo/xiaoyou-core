package com.aveline.ai.mobile.presentation.companion

import androidx.compose.foundation.background
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material.icons.outlined.Cloud
import androidx.compose.material.icons.outlined.FavoriteBorder
import androidx.compose.material.icons.outlined.Mood
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.LifeStatus
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.status.StatusUiState
import com.aveline.ai.mobile.presentation.theme.EmotionColors
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import com.aveline.ai.mobile.presentation.theme.EmotionRed
import com.aveline.ai.mobile.presentation.theme.LifeEnergy
import com.aveline.ai.mobile.presentation.theme.LifeHappiness
import com.aveline.ai.mobile.presentation.theme.LifeHealth
import com.aveline.ai.mobile.presentation.theme.LifeHunger
import com.aveline.ai.mobile.presentation.theme.SelectionSurface
import com.aveline.ai.mobile.presentation.theme.StatusOffline
import com.aveline.ai.mobile.presentation.theme.StatusOnline
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import com.aveline.ai.mobile.presentation.utils.EmotionResolver

/**
 * Companion 状态 Tab。
 *
 * 展示 AI 生命状态(健康/饥饿/幸福/能量)、当前情绪、连接状态。
 *
 * @param uiState 状态页 UI 状态
 * @param onRefresh 刷新回调
 */
@Composable
fun CompanionStatusTab(
    uiState: StatusUiState,
    onRefresh: () -> Unit,
    onWake: () -> Unit,
    onInterrupt: () -> Unit,
    onSkip: () -> Unit
) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp),
        contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        // 错误信息 + 重试按钮
        item {
            uiState.error?.let { errorMsg ->
                ErrorBanner(
                    message = errorMsg,
                    onRetry = onRefresh
                )
            }
        }

        item {
            SectionCard(
                title = "此刻",
                icon = Icons.Outlined.Schedule,
                subtitle = "当前活动与实际回复方式"
            ) {
                ActivityControlContent(
                    lifeStatus = uiState.lifeStatus,
                    isLoading = uiState.isActionRunning,
                    actionMessage = uiState.actionMessage,
                    onWake = onWake,
                    onInterrupt = onInterrupt,
                    onSkip = onSkip
                )
            }
        }

        // 生命状态卡片:健康 / 饥饿 / 幸福 / 能量
        item {
            SectionCard(
                title = "生命状态",
                icon = Icons.Outlined.FavoriteBorder,
                subtitle = "健康 · 饥饿 · 幸福 · 能量"
            ) {
                if (uiState.isLoading && uiState.lifeStatus == null) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 16.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        CircularProgressIndicator(color = EmotionGreen)
                    }
                } else {
                    LifeStatusContent(lifeStatus = uiState.lifeStatus)
                }
            }
        }

        // 情绪卡片:当前情绪 + 混合比例
        item {
            SectionCard(
                title = "情绪",
                icon = Icons.Outlined.Mood,
                subtitle = "当前情绪与混合比例"
            ) {
                EmotionContent(
                    emotionPrimary = uiState.emotion.primary,
                    emotionIntensity = uiState.emotion.intensity,
                    emotionMix = uiState.emotionMix
                )
            }
        }

        // 连接卡片:WebSocket 连接状态 + 系统时钟
        item {
            SectionCard(
                title = "连接",
                icon = Icons.Outlined.Cloud,
                subtitle = "WebSocket 连接状态"
            ) {
                ConnectionContent(
                    connected = uiState.connected,
                    clock = uiState.clock
                )
            }
        }
    }
}

/**
 * 错误提示横幅,带重试按钮。
 */
@Composable
private fun ErrorBanner(
    message: String,
    onRetry: () -> Unit
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = EmotionRed.copy(alpha = 0.1f),
        shape = RoundedCornerShape(12.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Icon(
                imageVector = Icons.Default.Warning,
                contentDescription = null,
                tint = EmotionRed,
                modifier = Modifier.size(20.dp)
            )
            Text(
                text = message,
                style = MaterialTheme.typography.bodySmall,
                color = EmotionRed,
                modifier = Modifier.weight(1f)
            )
            Button(
                onClick = onRetry,
                colors = ButtonDefaults.buttonColors(
                    containerColor = EmotionRed.copy(alpha = 0.2f),
                    contentColor = EmotionRed
                ),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp)
            ) {
                Icon(
                    Icons.Default.Refresh,
                    contentDescription = "重试",
                    modifier = Modifier.size(16.dp)
                )
                Spacer(modifier = Modifier.width(4.dp))
                Text("重试", style = MaterialTheme.typography.labelMedium)
            }
        }
    }
}

/**
 * 生命状态内容:4 个指标进度条。
 */
@Composable
private fun LifeStatusContent(lifeStatus: LifeStatus?) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        LifeMetricRow(
            label = "健康",
            value = lifeStatus?.health ?: 0f,
            color = LifeHealth
        )
        LifeMetricRow(
            label = "饥饿",
            value = lifeStatus?.hunger ?: 0f,
            color = LifeHunger
        )
        LifeMetricRow(
            label = "幸福",
            value = lifeStatus?.happiness ?: 0f,
            color = LifeHappiness
        )
        LifeMetricRow(
            label = "能量",
            value = lifeStatus?.energy ?: 0f,
            color = LifeEnergy
        )
    }
}

/**
 * 单个生命指标行:标签 + 进度条 + 百分比。
 */
@Composable
private fun LifeMetricRow(
    label: String,
    value: Float,
    color: Color
) {
    val percent = (value * 100).toInt().coerceIn(0, 100)
    Column {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = label,
                style = MaterialTheme.typography.bodyMedium,
                color = TextSecondary
            )
            Text(
                text = "$percent%",
                style = MaterialTheme.typography.labelLarge.copy(fontWeight = FontWeight.Bold),
                color = TextPrimary
            )
        }
        Spacer(modifier = Modifier.height(6.dp))
        LinearProgressIndicator(
            progress = { value.coerceIn(0f, 1f) },
            modifier = Modifier
                .fillMaxWidth()
                .height(7.dp)
                .clip(RoundedCornerShape(4.dp)),
            color = color,
            trackColor = Color.White.copy(alpha = 0.055f)
        )
    }
}

@Composable
private fun ActivityControlContent(
    lifeStatus: LifeStatus?,
    isLoading: Boolean,
    actionMessage: String?,
    onWake: () -> Unit,
    onInterrupt: () -> Unit,
    onSkip: () -> Unit
) {
    val activity = lifeStatus?.activity.orEmpty().ifBlank { "idle" }
    val sleeping = lifeStatus?.isSleeping == true ||
        activity in setOf("sleeping", "napping", "waking_up")
    val replyMode = lifeStatus?.replyMode ?: "immediate"
    val statusColor = when {
        sleeping -> LifeEnergy
        replyMode == "silent" -> LifeHunger
        replyMode == "delayed" -> LifeHappiness
        else -> LifeHealth
    }
    val statusHint = when {
        sleeping -> "睡眠中，消息暂不回复"
        replyMode == "silent" -> "专注中，消息会留到活动结束后处理"
        replyMode == "delayed" -> formatReplyDelay(lifeStatus)
        else -> "会正常回复"
    }

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(9.dp)
                    .clip(CircleShape)
                    .background(statusColor.copy(alpha = 0.9f))
            )
            Spacer(modifier = Modifier.width(10.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = companionActivityLabel(activity),
                    style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.SemiBold),
                    color = TextPrimary
                )
                Text(
                    text = statusHint,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextTertiary
                )
            }
            if (isLoading) {
                CircularProgressIndicator(
                    modifier = Modifier.size(18.dp),
                    color = statusColor,
                    strokeWidth = 2.dp
                )
            }
        }

        if (!isLoading && sleeping) {
            CompanionControlButton(label = "唤醒", onClick = onWake)
        } else if (!isLoading && replyMode == "silent") {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CompanionControlButton(
                    label = "打断",
                    onClick = onInterrupt,
                    modifier = Modifier.weight(1f)
                )
                CompanionControlButton(
                    label = "跳过活动",
                    onClick = onSkip,
                    modifier = Modifier.weight(1f)
                )
            }
        }

        actionMessage?.let { message ->
            Text(
                text = message,
                style = MaterialTheme.typography.bodySmall,
                color = LifeHealth
            )
        }
    }
}

@Composable
private fun CompanionControlButton(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Surface(
        onClick = onClick,
        modifier = modifier,
        shape = RoundedCornerShape(10.dp),
        color = SelectionSurface,
        contentColor = TextPrimary,
        border = BorderStroke(1.dp, Color.White.copy(alpha = 0.08f))
    ) {
        Text(
            text = label,
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
            style = MaterialTheme.typography.labelLarge.copy(fontWeight = FontWeight.SemiBold)
        )
    }
}

private fun formatReplyDelay(lifeStatus: LifeStatus?): String {
    val minSeconds = lifeStatus?.replyDelayMinSeconds
    val maxSeconds = lifeStatus?.replyDelayMaxSeconds
    return if (minSeconds != null && maxSeconds != null) {
        "会延迟约 ${minSeconds}–${maxSeconds} 秒回复"
    } else {
        "会稍后回复"
    }
}

internal fun companionActivityLabel(activity: String): String = when (activity) {
    "sleeping" -> "正在睡觉"
    "waking_up" -> "正在起床洗漱"
    "breakfast" -> "正在吃早餐"
    "lunch" -> "正在吃午餐"
    "dinner" -> "正在吃晚餐"
    "cooking" -> "正在做饭"
    "studying" -> "正在学习"
    "reading" -> "正在阅读"
    "housework" -> "正在做家务"
    "napping" -> "正在午休"
    "walking" -> "正在散步"
    "phone_scrolling" -> "正在刷手机"
    "gardening" -> "正在打理植物"
    "exercising" -> "正在运动"
    "gaming" -> "正在玩游戏"
    "self_care" -> "正在洗漱整理"
    "creative_hobby" -> "正在做自己的兴趣"
    "shopping" -> "正在外出购物"
    "staying_up_late" -> "正在熬夜"
    "late_snack" -> "正在吃夜宵"
    "overslept_recovery" -> "刚睡醒，正在缓神"
    "sleep_recovery" -> "正在恢复精神"
    "peer_chat" -> "正在聊天"
    "idle" -> "正在放松"
    else -> "当前状态"
}

/**
 * 情绪内容:主情绪进度条 + 混合比例(标题行已在 SectionCard 中展示)。
 */
@Composable
private fun EmotionContent(
    emotionPrimary: String,
    emotionIntensity: Float,
    emotionMix: Map<String, Float>
) {
    val primaryColor = EmotionResolver.getColorForEmotion(emotionPrimary)

    // 主情绪占比
    Column {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text(
                text = emotionPrimary,
                style = MaterialTheme.typography.bodyMedium,
                color = TextSecondary
            )
            Text(
                text = "强度 ${(emotionIntensity * 100).toInt()}%",
                style = MaterialTheme.typography.labelSmall,
                color = TextPrimary
            )
        }
        Spacer(modifier = Modifier.height(4.dp))
        LinearProgressIndicator(
            progress = { emotionIntensity.coerceIn(0f, 1f) },
            modifier = Modifier
                .fillMaxWidth()
                .height(4.dp)
                .clip(RoundedCornerShape(2.dp)),
            color = primaryColor,
            trackColor = Color.White.copy(alpha = 0.05f)
        )
    }

    // 情绪混合比例
    if (emotionMix.isNotEmpty()) {
        Spacer(modifier = Modifier.height(12.dp))
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            emotionMix.forEach { (name, ratio) ->
                val mixColor = EmotionColors.getColorForEmotion(name)
                Column {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Text(name, style = MaterialTheme.typography.labelSmall, color = TextSecondary)
                        Text("${(ratio * 100).toInt()}%", style = MaterialTheme.typography.labelSmall, color = TextPrimary)
                    }
                    Spacer(modifier = Modifier.height(4.dp))
                    LinearProgressIndicator(
                        progress = { ratio.coerceIn(0f, 1f) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(4.dp)
                            .clip(RoundedCornerShape(2.dp)),
                        color = mixColor,
                        trackColor = Color.White.copy(alpha = 0.05f)
                    )
                }
            }
        }
    }
}

/**
 * 连接内容:WebSocket 连接状态 + 系统时钟。
 */
@Composable
private fun ConnectionContent(
    connected: Boolean,
    clock: String
) {
    val statusColor = if (connected) StatusOnline else StatusOffline
    val statusText = if (connected) "已连接" else "未连接"

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "WebSocket",
                style = MaterialTheme.typography.bodyMedium,
                color = TextSecondary
            )
            Surface(
                color = statusColor.copy(alpha = 0.15f),
                shape = RoundedCornerShape(8.dp)
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    Box(
                        modifier = Modifier
                            .size(6.dp)
                            .clip(CircleShape)
                            .background(statusColor)
                    )
                    Text(
                        text = statusText,
                        style = MaterialTheme.typography.labelSmall.copy(fontWeight = FontWeight.Bold),
                        color = statusColor
                    )
                }
            }
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "系统时钟",
                style = MaterialTheme.typography.bodyMedium,
                color = TextSecondary
            )
            Text(
                text = clock.ifBlank { "--:--:--" },
                style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold),
                color = TextPrimary
            )
        }
    }
}
