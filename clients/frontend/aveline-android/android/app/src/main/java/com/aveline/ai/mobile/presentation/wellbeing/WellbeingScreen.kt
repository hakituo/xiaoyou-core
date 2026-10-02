package com.aveline.ai.mobile.presentation.wellbeing

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.aveline.ai.mobile.data.remote.dto.AppLimitDto
import com.aveline.ai.mobile.presentation.components.ModuleHeader
import com.aveline.ai.mobile.presentation.components.ModuleHeaderActionContainer
import com.aveline.ai.mobile.presentation.theme.CardBackground
import com.aveline.ai.mobile.presentation.theme.CardBorder
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import com.aveline.ai.mobile.presentation.theme.EmotionRed
import com.aveline.ai.mobile.presentation.theme.EmotionYellow
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 数字健康(应用使用时长限额)主界面。
 *
 * 展示当前生效的限额列表(含今日用量进度), 支持新增/编辑/移除限额。
 * 限额由后端统一管理: Aveline nightly 会自动根据昨日用量设定, 用户也可在此手动覆盖。
 * 手机端本地定时检查, 超限时强制退出该应用并触发主动关怀消息。
 */

/** 前台时自动刷新本地用量的间隔 (毫秒)。 */
private const val USAGE_REFRESH_INTERVAL_MS = 15_000L
@Composable
fun WellbeingScreen(
    viewModel: WellbeingViewModel = hiltViewModel(),
    onBackClick: () -> Unit = {}
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val lifecycleOwner = LocalLifecycleOwner.current
    var isResumed by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf(false) }

    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_RESUME -> {
                    isResumed = true
                    // 回到页面时拉一次最新限额与用量, 避免停留在旧数据
                    viewModel.refresh()
                }
                Lifecycle.Event.ON_PAUSE -> isResumed = false
                else -> {}
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    // 页面在前台时定时刷新本地用量, 让"今日已用"随时间实时增长, 无需手动点刷新
    LaunchedEffect(isResumed) {
        if (!isResumed) return@LaunchedEffect
        while (true) {
            kotlinx.coroutines.delay(USAGE_REFRESH_INTERVAL_MS)
            viewModel.refreshUsage()
        }
    }

    LaunchedEffect(uiState.successMessage, uiState.error) {
        if (uiState.successMessage != null || uiState.error != null) {
            kotlinx.coroutines.delay(2500)
            viewModel.clearMessages()
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        ModuleHeader(
            title = "数字健康",
            subtitle = "应用使用时长限额",
            height = 128.dp
        ) {
            ModuleHeaderActionContainer {
                IconButton(onClick = viewModel::refresh) {
                    if (uiState.isLoading) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            color = Color.White,
                            strokeWidth = 2.dp
                        )
                    } else {
                        Icon(
                            imageVector = Icons.Default.Refresh,
                            contentDescription = "刷新",
                            tint = Color.White
                        )
                    }
                }
            }
            ModuleHeaderActionContainer {
                IconButton(onClick = viewModel::openAddDialog) {
                    Icon(
                        imageVector = Icons.Default.Add,
                        contentDescription = "添加限额",
                        tint = Color.White
                    )
                }
            }
        }

        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            item {
                EnforcementStatusCard(
                    hasUsageStatsPermission = uiState.hasUsageStatsPermission,
                    hasAccessibilityService = uiState.hasAccessibilityService,
                    onOpenUsageStats = viewModel::openUsageStatsSettings,
                    onOpenAccessibility = viewModel::openAccessibilitySettings
                )
            }
            // 提示信息(单行)
            uiState.successMessage?.takeIf { it.isNotBlank() }?.let { msg ->
                item {
                    Text(
                        text = msg,
                        color = EmotionGreen,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(vertical = 2.dp)
                    )
                }
            }
            uiState.error?.takeIf { it.isNotBlank() }?.let { err ->
                item {
                    Text(
                        text = err,
                        color = EmotionRed,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(vertical = 2.dp)
                    )
                }
            }

            if (uiState.limits.isEmpty() && !uiState.isLoading) {
                item { EmptyLimitHint(onAdd = viewModel::openAddDialog) }
            } else {
                items(uiState.limits, key = { it.packageName }) { limit ->
                    AppLimitCard(
                        limit = limit,
                        onEdit = { viewModel.openEditDialog(limit) },
                        onRemove = { viewModel.removeLimit(limit.packageName) }
                    )
                }
            }
            item { Spacer(modifier = Modifier.height(24.dp)) }
        }
    }

    if (uiState.showAddDialog) {
        AppLimitDialog(
            installedApps = uiState.installedApps,
            editing = uiState.editingLimit,
            onDismiss = viewModel::dismissAddDialog,
            onSave = { pkg, name, dailyMs, sessionMs, cooldownMs ->
                viewModel.saveLimit(pkg, name, dailyMs, sessionMs, cooldownMs)
            }
        )
    }
}

@Composable
private fun EnforcementStatusCard(
    hasUsageStatsPermission: Boolean,
    hasAccessibilityService: Boolean,
    onOpenUsageStats: () -> Unit,
    onOpenAccessibility: () -> Unit
) {
    val (message, color, action) = when {
        !hasUsageStatsPermission -> Triple(
            "未授权使用情况访问，当前无法统计和执行限额。点此授权",
            EmotionRed,
            onOpenUsageStats
        )
        !hasAccessibilityService -> Triple(
            "计时已就绪；开启无障碍后可实时拦截，单次限额精确到秒",
            EmotionYellow,
            onOpenAccessibility
        )
        else -> Triple(
            "实时拦截已就绪：每日额度用完或单次时间到，应用会被立即退回桌面",
            EmotionGreen,
            {}
        )
    }
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(enabled = !hasUsageStatsPermission || !hasAccessibilityService, onClick = action),
        colors = CardDefaults.cardColors(containerColor = color.copy(alpha = 0.12f)),
        border = BorderStroke(1.dp, color.copy(alpha = 0.45f)),
        shape = RoundedCornerShape(14.dp)
    ) {
        Text(
            text = message,
            color = color,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.padding(14.dp)
        )
    }
}

/**
 * 单个应用的限额卡片。
 *
 * 用户只需要理解三个概念: 每日限额 / 单次限额 / 超时休息。
 * 不暴露 sessionCap、窗口之类内部概念。
 */
@Composable
private fun AppLimitCard(
    limit: AppLimitDto,
    onEdit: () -> Unit,
    onRemove: () -> Unit
) {
    val dailyRatio = limit.ratio.coerceIn(0.0, 1.5)
    val dailyColor = progressColor(dailyRatio)
    val dailyExceeded = limit.ratio >= 1.0 || limit.blockReason == "daily"

    val sessionLimit = limit.effectiveSessionLimitMs()
    val sessionRatio = if (sessionLimit > 0) {
        limit.sessionUsedMs.toDouble() / sessionLimit.toDouble()
    } else {
        0.0
    }
    val sessionExceeded = limit.blockReason == "session" || limit.blockReason == "cooldown"

    Card(
        onClick = onEdit,
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = CardBackground),
        border = androidx.compose.foundation.BorderStroke(1.dp, CardBorder),
        shape = RoundedCornerShape(16.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = limit.appName.ifBlank { limit.packageName },
                        color = TextPrimary,
                        style = MaterialTheme.typography.bodyLarge,
                        fontWeight = FontWeight.Medium
                    )
                    Text(
                        text = limit.packageName,
                        color = TextTertiary,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
                when {
                    dailyExceeded -> StatusChip("今日已用完", EmotionRed)
                    limit.blockReason == "cooldown" -> StatusChip(
                        "休息中 · 还需 ${formatDuration(remainingMs(limit))}",
                        EmotionYellow
                    )
                    sessionExceeded -> StatusChip("本次时间到", EmotionYellow)
                    limit.ratio >= 1.0 -> StatusChip("已超限", EmotionRed)
                }
                IconButton(onClick = onRemove) {
                    Icon(
                        imageVector = Icons.Default.Delete,
                        contentDescription = "移除",
                        tint = TextTertiary,
                        modifier = Modifier.size(18.dp)
                    )
                }
            }

            Spacer(modifier = Modifier.height(10.dp))

            // ── 今日使用 ──────────────────────────────
            UsageRow(
                label = "今日使用",
                usedMs = limit.usageTodayMs,
                limitMs = limit.limitMs
            )
            if (limit.limitMs > 0) {
                Spacer(modifier = Modifier.height(6.dp))
                LinearProgressIndicator(
                    progress = { dailyRatio.toFloat().coerceIn(0f, 1f) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(8.dp)
                        .clip(RoundedCornerShape(4.dp)),
                    color = dailyColor,
                    trackColor = Color(0xFF27272A)
                )
            } else {
                // 明确标注"不限制", 避免用户把 0m 误读成"限 0 分钟=直接打不开"
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "无每日限制",
                    color = EmotionGreen,
                    style = MaterialTheme.typography.labelSmall,
                    fontWeight = FontWeight.Medium,
                    modifier = Modifier
                        .clip(RoundedCornerShape(8.dp))
                        .background(EmotionGreen.copy(alpha = 0.15f))
                        .padding(horizontal = 8.dp, vertical = 4.dp)
                )
            }

            // ── 单次使用 ──────────────────────────────
            if (sessionLimit > 0) {
                Spacer(modifier = Modifier.height(12.dp))
                UsageRow(
                    label = "单次使用",
                    usedMs = limit.sessionUsedMs,
                    limitMs = sessionLimit
                )
                Spacer(modifier = Modifier.height(6.dp))
                LinearProgressIndicator(
                    progress = { sessionRatio.toFloat().coerceIn(0f, 1f) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(6.dp)
                        .clip(RoundedCornerShape(3.dp)),
                    color = progressColor(sessionRatio),
                    trackColor = Color(0xFF27272A)
                )
            }

            Spacer(modifier = Modifier.height(12.dp))

            // ── 策略摘要 ──────────────────────────────
            PolicySummary(limit = limit)
        }
    }
}

/** 状态小标签。 */
@Composable
private fun StatusChip(text: String, color: Color) {
    Text(
        text = text,
        color = color,
        style = MaterialTheme.typography.labelSmall,
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(color.copy(alpha = 0.15f))
            .padding(horizontal = 8.dp, vertical = 4.dp)
    )
}

/** "标签  used / limit" 一行。limitMs <= 0 时右侧显示"无限制"。 */
@Composable
private fun UsageRow(label: String, usedMs: Long, limitMs: Long) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = label,
            color = TextSecondary,
            style = MaterialTheme.typography.bodySmall
        )
        if (limitMs > 0) {
            Text(
                text = "${formatDuration(usedMs)} / ${formatDuration(limitMs)}",
                color = TextSecondary,
                style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.Medium
            )
        } else {
            Text(
                text = "${formatDuration(usedMs)} · 无限制",
                color = TextSecondary,
                style = MaterialTheme.typography.bodySmall
            )
        }
    }
}

/** 策略摘要: 每日限额 / 单次限额 / 超时休息 / 离开多久算结束。 */
@Composable
private fun PolicySummary(limit: AppLimitDto) {
    val sessionLimit = limit.effectiveSessionLimitMs()
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        SummaryLine("每日限额", if (limit.limitMs > 0) formatDuration(limit.limitMs) else "不限制")
        SummaryLine("单次限额", if (sessionLimit > 0) formatDuration(sessionLimit) else "不限制")
        if (sessionLimit > 0) {
            SummaryLine("超时休息", formatDuration(limit.cooldownMs))
            SummaryLine("离开 ${formatDuration(limit.sessionGapMs)} 算作结束")
        }
    }
}

@Composable
private fun SummaryLine(label: String, value: String? = null) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = label,
            color = TextTertiary,
            style = MaterialTheme.typography.labelSmall
        )
        if (value != null) {
            Text(
                text = value,
                color = TextTertiary,
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Medium
            )
        }
    }
}

/** 进度条颜色: 绿(正常) → 黄(接近上限) → 红(超限)。 */
private fun progressColor(ratio: Double): Color = when {
    ratio >= 1.0 -> EmotionRed
    ratio >= 0.8 -> EmotionYellow
    else -> EmotionGreen
}

/** 冷却剩余时长 (毫秒)。 */
private fun remainingMs(limit: AppLimitDto): Long =
    (limit.blockedUntilMs - System.currentTimeMillis()).coerceAtLeast(0L)

@Composable
private fun EmptyLimitHint(onAdd: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = "还没有设置任何应用限额",
            color = TextPrimary,
            style = MaterialTheme.typography.bodyMedium
        )
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = "点右上角 + 添加，或等 Aveline 今晚自动帮你定",
            color = TextTertiary,
            style = MaterialTheme.typography.bodySmall
        )
        Spacer(modifier = Modifier.height(16.dp))
        Box(
            modifier = Modifier
                .clip(RoundedCornerShape(12.dp))
                .background(Primary.copy(alpha = 0.15f))
                .clickable(onClick = onAdd)
                .padding(horizontal = 20.dp, vertical = 10.dp)
        ) {
            Text(text = "添加限额", color = Primary)
        }
    }
}

/** 把毫秒格式化为 "Xh Ym" / "Ym" / "Xs"。 */
private fun formatDuration(ms: Long): String {
    if (ms <= 0) return "0m"
    if (ms < 60_000) return "<1m"
    val totalMin = ms / 60_000
    val h = totalMin / 60
    val m = totalMin % 60
    return if (h > 0) "${h}h${if (m > 0) "${m}m" else ""}" else "${m}m"
}
