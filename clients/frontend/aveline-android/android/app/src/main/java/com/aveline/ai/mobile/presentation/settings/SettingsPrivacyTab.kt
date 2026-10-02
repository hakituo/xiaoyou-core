package com.aveline.ai.mobile.presentation.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PrivacyTip
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 隐私 tab:上下文同步 / 常驻模式。
 *
 * 从 Settings 提取隐私相关开关。
 */
@Composable
fun SettingsPrivacyTab(
    settingsUiState: SettingsUiState,
    onToggleContextSync: () -> Unit,
    onToggleResidentMode: () -> Unit,
    onConfirmBatteryOptimization: () -> Unit,
    onDismissBatteryOptimization: () -> Unit,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Spacer(modifier = Modifier.height(8.dp))

        // 上下文同步
        SectionCard(title = "上下文同步", subtitle = "设备上下文与活动数据") {
            PrivacySwitchRow(
                icon = Icons.Default.PrivacyTip,
                title = "上下文同步",
                subtitle = "将设备上下文与活动数据同步到后端",
                checked = settingsUiState.isContextSyncEnabled,
                onToggle = { onToggleContextSync() }
            )
        }

        // 常驻模式
        SectionCard(title = "常驻模式", subtitle = "后台保活与持续消息") {
            PrivacySwitchRow(
                icon = Icons.Default.Speed,
                title = "常驻模式",
                subtitle = "保持应用后台运行以接收持续消息",
                checked = settingsUiState.residentModeEnabled,
                onToggle = { onToggleResidentMode() }
            )
        }

        Spacer(modifier = Modifier.height(16.dp))
    }

    // 开启常驻模式时,若不在电池优化白名单则弹引导对话框(国产 ROM 后台保活必备)
    if (settingsUiState.showBatteryOptimizationRequest) {
        AlertDialog(
            onDismissRequest = onDismissBatteryOptimization,
            title = { Text("加入电池优化白名单") },
            text = {
                Text("常驻模式需要加入电池优化白名单才能稳定后台运行,否则系统可能限制后台活动。是否现在前往设置?")
            },
            confirmButton = {
                TextButton(onClick = onConfirmBatteryOptimization) {
                    Text("前往设置")
                }
            },
            dismissButton = {
                TextButton(onClick = onDismissBatteryOptimization) {
                    Text("稍后")
                }
            }
        )
    }
}

/**
 * 隐私开关行:图标 + 标题/副标题 + Switch。
 */
@Composable
private fun PrivacySwitchRow(
    icon: ImageVector,
    title: String,
    subtitle: String,
    checked: Boolean,
    onToggle: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(Color(0x12000000))
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = if (checked) MaterialTheme.colorScheme.primary else TextTertiary,
            modifier = Modifier.size(24.dp)
        )
        Spacer(modifier = Modifier.width(16.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(text = title, style = MaterialTheme.typography.bodyLarge, color = TextPrimary)
            Text(text = subtitle, style = MaterialTheme.typography.bodySmall, color = TextTertiary)
        }
        Switch(checked = checked, onCheckedChange = { onToggle() })
    }
}
