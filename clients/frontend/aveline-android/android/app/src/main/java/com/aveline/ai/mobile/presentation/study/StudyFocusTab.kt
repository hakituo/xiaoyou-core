package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FastForward
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.SurfaceVariant
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary

/**
 * 番茄钟（专注）Tab。
 *
 * 提供可配置工作 / 休息 / 长休息时长的倒计时器，支持开始、暂停、重置、跳过阶段。
 */
@Composable
fun StudyFocusTab(
    focusState: StudyFocusState,
    onToggleTimer: () -> Unit,
    onReset: () -> Unit,
    onSkipPhase: () -> Unit,
    onWorkMinutesChange: (Int) -> Unit,
    onBreakMinutesChange: (Int) -> Unit,
    onLongBreakMinutesChange: (Int) -> Unit,
    onFocusNameChange: (String) -> Unit = {}
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Top
    ) {
        Spacer(modifier = Modifier.height(16.dp))

        // 自定义专注事项名：完成番茄后作为科目上报后端，与概览"今日学习"联动
        OutlinedTextField(
            value = focusState.focusName,
            onValueChange = onFocusNameChange,
            label = { Text("专注事项（如：数学复习）") },
            singleLine = true,
            enabled = !focusState.isRunning,
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(modifier = Modifier.height(16.dp))

        // 阶段标签
        Text(
            text = when (focusState.phase) {
                FocusPhase.WORK -> if (focusState.focusName.isNotBlank()) {
                    "专注中 · ${focusState.focusName}"
                } else {
                    "专注中"
                }
                FocusPhase.BREAK -> "休息一下"
                FocusPhase.LONG_BREAK -> "长休息"
            },
            color = when (focusState.phase) {
                FocusPhase.WORK -> Primary
                FocusPhase.BREAK -> EmotionGreen
                FocusPhase.LONG_BREAK -> Color(0xFF64B5F6)
            },
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Bold
        )

        Spacer(modifier = Modifier.height(24.dp))

        // 倒计时圆环
        val totalSeconds = when (focusState.phase) {
            FocusPhase.WORK -> focusState.workMinutes * 60
            FocusPhase.BREAK -> focusState.breakMinutes * 60
            FocusPhase.LONG_BREAK -> focusState.longBreakMinutes * 60
        }.coerceAtLeast(1)
        val progress = 1f - (focusState.remainingSeconds.toFloat() / totalSeconds).coerceIn(0f, 1f)

        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier.size(240.dp)
        ) {
            CircularProgressIndicator(
                progress = { 1f },
                modifier = Modifier.fillMaxSize(),
                color = SurfaceVariant,
                strokeWidth = 12.dp,
                trackColor = Color.Transparent
            )
            CircularProgressIndicator(
                progress = { progress },
                modifier = Modifier.fillMaxSize(),
                color = when (focusState.phase) {
                    FocusPhase.WORK -> Primary
                    FocusPhase.BREAK -> EmotionGreen
                    FocusPhase.LONG_BREAK -> Color(0xFF64B5F6)
                },
                strokeWidth = 12.dp,
                trackColor = Color.Transparent
            )
            Text(
                text = formatFocusTime(focusState.remainingSeconds),
                color = TextPrimary,
                fontSize = 56.sp,
                fontWeight = FontWeight.Bold
            )
        }

        Spacer(modifier = Modifier.height(32.dp))

        // 控制按钮
        Row(
            horizontalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterHorizontally),
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.fillMaxWidth()
        ) {
            FilledTonalIconButton(
                onClick = onReset,
                modifier = Modifier.size(56.dp),
                colors = IconButtonDefaults.filledTonalIconButtonColors(
                    containerColor = SurfaceVariant
                )
            ) {
                Icon(
                    Icons.Filled.Refresh,
                    contentDescription = "重置",
                    tint = TextPrimary
                )
            }

            FilledIconButton(
                onClick = onToggleTimer,
                modifier = Modifier.size(72.dp),
                colors = IconButtonDefaults.filledIconButtonColors(
                    containerColor = Primary
                )
            ) {
                Icon(
                    imageVector = if (focusState.isRunning) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                    contentDescription = if (focusState.isRunning) "暂停" else "开始",
                    tint = Color.White,
                    modifier = Modifier.size(32.dp)
                )
            }

            FilledTonalIconButton(
                onClick = onSkipPhase,
                modifier = Modifier.size(56.dp),
                colors = IconButtonDefaults.filledTonalIconButtonColors(
                    containerColor = SurfaceVariant
                )
            ) {
                Icon(
                    Icons.Filled.FastForward,
                    contentDescription = "跳过",
                    tint = TextPrimary
                )
            }
        }

        Spacer(modifier = Modifier.height(24.dp))

        // 今日统计
        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(16.dp),
            colors = CardDefaults.cardColors(containerColor = SurfaceVariant)
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp),
                horizontalArrangement = Arrangement.SpaceAround,
                verticalAlignment = Alignment.CenterVertically
            ) {
                StatItem(value = "${focusState.todayTomatoes}", label = "今日番茄")
                StatItem(value = "${focusState.completedCycles}", label = "本次专注")
            }
        }

        Spacer(modifier = Modifier.height(24.dp))

        // 时长设置
        Text(
            text = "时长设置（分钟）",
            color = TextPrimary,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.align(Alignment.Start)
        )

        Spacer(modifier = Modifier.height(12.dp))

        DurationStepper(
            label = "专注",
            value = focusState.workMinutes,
            onValueChange = onWorkMinutesChange,
            enabled = !focusState.isRunning
        )
        Spacer(modifier = Modifier.height(8.dp))
        DurationStepper(
            label = "短休息",
            value = focusState.breakMinutes,
            onValueChange = onBreakMinutesChange,
            enabled = !focusState.isRunning
        )
        Spacer(modifier = Modifier.height(8.dp))
        DurationStepper(
            label = "长休息",
            value = focusState.longBreakMinutes,
            onValueChange = onLongBreakMinutesChange,
            enabled = !focusState.isRunning
        )

        Spacer(modifier = Modifier.height(24.dp))
    }
}

@Composable
private fun StatItem(value: String, label: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            text = value,
            color = Primary,
            fontSize = 28.sp,
            fontWeight = FontWeight.Bold
        )
        Text(
            text = label,
            color = TextSecondary,
            style = MaterialTheme.typography.bodyMedium
        )
    }
}

@Composable
private fun DurationStepper(
    label: String,
    value: Int,
    onValueChange: (Int) -> Unit,
    enabled: Boolean
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = label,
            color = TextPrimary,
            style = MaterialTheme.typography.bodyLarge
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(
                onClick = { onValueChange((value - 1).coerceAtLeast(1)) },
                enabled = enabled && value > 1
            ) {
                Text("-", fontSize = 20.sp)
            }
            Text(
                text = value.toString(),
                modifier = Modifier.padding(horizontal = 16.dp),
                color = TextPrimary,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold
            )
            OutlinedButton(
                onClick = { onValueChange((value + 1).coerceAtMost(120)) },
                enabled = enabled && value < 120
            ) {
                Text("+", fontSize = 20.sp)
            }
        }
    }
}

private fun formatFocusTime(totalSeconds: Int): String {
    val minutes = totalSeconds / 60
    val seconds = totalSeconds % 60
    return "%02d:%02d".format(minutes, seconds)
}
