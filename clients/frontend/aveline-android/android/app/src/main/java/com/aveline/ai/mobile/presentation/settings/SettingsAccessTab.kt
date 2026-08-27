package com.aveline.ai.mobile.presentation.settings

import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 权限 tab: 使用情况访问 / 通知访问。
 *
 * 从 Settings 提取权限部分,展示授权状态并提供跳转系统设置的入口。
 */
@Composable
fun SettingsAccessTab(
    settingsUiState: SettingsUiState,
    onOpenUsageStatsSettings: () -> Unit,
    onOpenNotificationSettings: () -> Unit,
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

        // 使用情况访问权限
        SectionCard(title = "使用情况访问", subtitle = "行为感知所需权限") {
            PermissionItem(
                icon = Icons.Default.Storage,
                title = "使用情况访问",
                subtitle = if (settingsUiState.hasUsageStatsPermission) "已授权" else "未授权 - 用于行为感知",
                isGranted = settingsUiState.hasUsageStatsPermission,
                onClick = onOpenUsageStatsSettings
            )
        }

        // 通知访问权限
        SectionCard(title = "通知访问", subtitle = "主动提醒所需权限") {
            PermissionItem(
                icon = Icons.Default.Notifications,
                title = "通知访问",
                subtitle = if (settingsUiState.hasNotificationPermission) "已授权" else "未授权 - 用于主动提醒",
                isGranted = settingsUiState.hasNotificationPermission,
                onClick = onOpenNotificationSettings
            )
        }

        // Shizuku 高级权限引导卡片 (独立组件, 内部自管状态)
        ShizukuWizardCard()

        // 无障碍服务引导卡片 (用于 UI 自动化)
        AccessibilityWizardCard()

        // 权限缺失提示卡片
        if (!settingsUiState.allPermissionsGranted) {
            PermissionInfoCard(missingCount = settingsUiState.missingPermissionsCount)
        }

        Spacer(modifier = Modifier.height(16.dp))
    }
}

/**
 * 单条权限项:图标 + 标题/副标题 + 授权状态徽标 + 跳转按钮。
 */
@Composable
private fun PermissionItem(
    icon: ImageVector,
    title: String,
    subtitle: String,
    isGranted: Boolean,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(Color(0x12000000))
            .semantics { contentDescription = "$title: ${if (isGranted) "已授权" else "未授权"}" }
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = if (isGranted) MaterialTheme.colorScheme.primary else TextTertiary,
            modifier = Modifier.size(24.dp)
        )
        Spacer(modifier = Modifier.width(16.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(text = title, style = MaterialTheme.typography.bodyLarge, color = TextPrimary)
            Text(text = subtitle, style = MaterialTheme.typography.bodySmall, color = TextTertiary)
        }
        // 授权状态徽标
        Box(
            modifier = Modifier
                .size(24.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(
                    if (isGranted) MaterialTheme.colorScheme.primary.copy(alpha = 0.2f)
                    else MaterialTheme.colorScheme.error.copy(alpha = 0.2f)
                ),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = if (isGranted) Icons.Default.Check else Icons.Default.Close,
                contentDescription = null,
                tint = if (isGranted) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
                modifier = Modifier.size(16.dp)
            )
        }
        IconButton(onClick = onClick) {
            Icon(Icons.Default.ChevronRight, contentDescription = "打开设置", tint = TextTertiary)
        }
    }
}

/**
 * 权限缺失提示卡片。
 */
@Composable
private fun PermissionInfoCard(missingCount: Int) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.5f)
        ),
        shape = RoundedCornerShape(12.dp)
    ) {
        Row(modifier = Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(
                imageVector = Icons.Default.Info,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(24.dp)
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column {
                Text(
                    text = "权限提示",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onPrimaryContainer
                )
                Text(
                    text = "还有 $missingCount 项权限未授予,部分功能可能受限。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.7f)
                )
            }
        }
    }
}


