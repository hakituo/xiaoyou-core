package com.aveline.ai.mobile.presentation.wellbeing

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.data.remote.dto.AppLimitDto
import com.aveline.ai.mobile.presentation.theme.CardBackground
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 每日限额预设 (分钟)。
 */
private val PRESET_DURATIONS = listOf(
    15 to "15 分钟",
    30 to "30 分钟",
    45 to "45 分钟",
    60 to "1 小时",
    90 to "1.5 小时",
    120 to "2 小时",
    180 to "3 小时"
)

/**
 * 单次限额预设 (分钟)。0 = 不限制单次。
 */
private val PRESET_SESSION_LIMITS = listOf(
    0 to "不限制",
    5 to "5 分钟",
    10 to "10 分钟",
    20 to "20 分钟",
    30 to "30 分钟"
)

/**
 * 超时休息预设 (分钟)。单次超限后必须休息多久才能重新打开。
 */
private val PRESET_COOLDOWNS = listOf(
    1 to "1 分钟",
    3 to "3 分钟",
    5 to "5 分钟",
    10 to "10 分钟"
)

/**
 * 添加/编辑应用限额对话框。
 *
 * 暴露给用户的三个概念: 每日限额 / 单次限额 / 超时休息。
 * 会话间隔 (离开多久算新的一次) 不暴露, 用默认 2 分钟, 避免 UI 过载。
 *
 * @param installedApps 已安装应用列表 (用于选择应用)
 * @param editing 正在编辑的限额 (null=新增)
 * @param onDismiss 关闭回调
 * @param onSave 保存回调 (packageName, appName, dailyLimitMs, sessionLimitMs, cooldownMs)
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun AppLimitDialog(
    installedApps: List<InstalledApp>,
    editing: AppLimitDto?,
    onDismiss: () -> Unit,
    onSave: (
        packageName: String,
        appName: String,
        dailyLimitMs: Long,
        sessionLimitMs: Long,
        cooldownMs: Long
    ) -> Unit
) {
    var selectedApp by remember { mutableStateOf<InstalledApp?>(null) }
    var packageName by remember { mutableStateOf(editing?.packageName ?: "") }
    var appName by remember { mutableStateOf(editing?.appName ?: "") }
    var expanded by remember { mutableStateOf(false) }

    // ── 每日限额 ──
    var dailyMinutesText by remember {
        mutableStateOf(if (editing != null) (editing.limitMs / 60000).toString() else "60")
    }
    val editingDailyMinutes: Long? = editing?.let { it.limitMs / 60000 }
    var customDailyMinutes by remember {
        mutableStateOf(
            if (editingDailyMinutes != null &&
                editingDailyMinutes !in PRESET_DURATIONS.map { it.first.toLong() }
            ) {
                editingDailyMinutes.toString()
            } else ""
        )
    }

    // ── 单次限额 (0 = 不限制, 默认不限制) ──
    // 必须默认不限制: 用户多数时候只想设每日额度, 若默认带 10 分钟单次额度,
    // 每个被设限的应用都会"连续用 10 分钟就被踢", 体验等同于全局限时。
    var sessionMinutes by remember {
        mutableStateOf(editing?.effectiveSessionLimitMs()?.div(60000) ?: 0L)
    }
    // ── 超时休息 ──
    var cooldownMinutes by remember {
        mutableStateOf(editing?.cooldownMs?.takeIf { it > 0 }?.div(60000) ?: 5L)
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = Color(0xFF121214),
        title = {
            Text(
                text = if (editing != null) "编辑应用限额" else "添加应用限额",
                color = TextPrimary,
                style = MaterialTheme.typography.titleMedium
            )
        },
        text = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                // 应用选择 (仅新增时可选; 编辑时固定显示)
                if (editing == null) {
                    Text("选择应用", color = TextSecondary, style = MaterialTheme.typography.bodyMedium)
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(12.dp))
                            .background(CardBackground)
                            .clickable { expanded = !expanded }
                            .padding(14.dp)
                    ) {
                        Text(
                            text = selectedApp?.let { "${it.appName} (${it.packageName})" }
                                ?: "点击选择应用",
                            color = if (selectedApp != null) TextPrimary else TextTertiary
                        )
                    }
                    if (expanded) {
                        LazyColumn(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(240.dp)
                                .clip(RoundedCornerShape(12.dp))
                                .background(CardBackground)
                                .padding(4.dp)
                        ) {
                            if (installedApps.isEmpty()) {
                                item {
                                    Text(
                                        "未读取到已安装应用",
                                        color = TextTertiary,
                                        modifier = Modifier.padding(12.dp)
                                    )
                                }
                            }
                            items(installedApps) { app ->
                                Column(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clickable {
                                            selectedApp = app
                                            packageName = app.packageName
                                            appName = app.appName
                                            expanded = false
                                        }
                                        .padding(horizontal = 12.dp, vertical = 10.dp)
                                ) {
                                    Text(app.appName, color = TextPrimary)
                                    Text(
                                        app.packageName,
                                        color = TextTertiary,
                                        style = MaterialTheme.typography.bodySmall
                                    )
                                }
                            }
                        }
                    }
                } else {
                    Text(
                        text = "${editing.appName.ifBlank { editing.packageName }} (${editing.packageName})",
                        color = TextPrimary
                    )
                }

                // ── 每日限额 ──
                Text(
                    "每日限额 (今天总共能用多久)",
                    color = TextSecondary,
                    style = MaterialTheme.typography.bodyMedium
                )
                FlowRow(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    PRESET_DURATIONS.forEach { (minutes, label) ->
                        val selected =
                            dailyMinutesText == minutes.toString() && customDailyMinutes.isEmpty()
                        DurationChip(
                            label = label,
                            selected = selected,
                            onClick = {
                                dailyMinutesText = minutes.toString()
                                customDailyMinutes = ""
                            }
                        )
                    }
                }

                // 自定义每日分钟
                OutlinedTextField(
                    value = customDailyMinutes,
                    onValueChange = {
                        if (it.all { c -> c.isDigit() }) {
                            customDailyMinutes = it
                            if (it.isNotEmpty()) dailyMinutesText = it
                        }
                    },
                    label = { Text("自定义每日分钟数", color = TextSecondary) },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = Primary,
                        unfocusedBorderColor = Color(0xFF27272A),
                        cursorColor = Primary
                    ),
                    modifier = Modifier.fillMaxWidth()
                )

                // ── 单次限额 ──
                Text(
                    "单次限额 (一次连续最多用多久)",
                    color = TextSecondary,
                    style = MaterialTheme.typography.bodyMedium
                )
                FlowRow(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    PRESET_SESSION_LIMITS.forEach { (minutes, label) ->
                        DurationChip(
                            label = label,
                            selected = sessionMinutes == minutes.toLong(),
                            onClick = { sessionMinutes = minutes.toLong() }
                        )
                    }
                }

                // ── 超时休息 ──
                if (sessionMinutes > 0) {
                    Text(
                        "超时休息 (单次用完后多久才能重新打开)",
                        color = TextSecondary,
                        style = MaterialTheme.typography.bodyMedium
                    )
                    FlowRow(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        PRESET_COOLDOWNS.forEach { (minutes, label) ->
                            DurationChip(
                                label = label,
                                selected = cooldownMinutes == minutes.toLong(),
                                onClick = { cooldownMinutes = minutes.toLong() }
                            )
                        }
                    }
                    Text(
                        "离开超过 2 分钟才算\"新的一次\"，否则继续累计本次用时",
                        color = TextTertiary,
                        style = MaterialTheme.typography.labelSmall
                    )
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    val dailyMinutes = dailyMinutesText.toLongOrNull() ?: 0
                    val dailyMs = dailyMinutes * 60_000L
                    val sessionMs = sessionMinutes * 60_000L
                    val cooldownMs = cooldownMinutes * 60_000L
                    if (packageName.isBlank()) return@TextButton
                    if (dailyMs <= 0 && sessionMs <= 0) return@TextButton
                    onSave(
                        packageName.trim(),
                        appName.ifBlank { packageName.trim() },
                        dailyMs,
                        sessionMs,
                        cooldownMs
                    )
                }
            ) {
                Text("保存", color = Primary)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消", color = TextSecondary)
            }
        }
    )
}

@Composable
private fun DurationChip(label: String, selected: Boolean, onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(10.dp))
            .background(if (selected) Primary else CardBackground)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 8.dp)
    ) {
        Text(
            text = label,
            color = if (selected) Color.White else TextSecondary,
            style = MaterialTheme.typography.bodySmall
        )
    }
}
