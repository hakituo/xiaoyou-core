package com.aveline.ai.mobile.presentation.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Language
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.School
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material.icons.outlined.Mood
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.EmotionType
import com.aveline.ai.mobile.domain.models.ResponseLength
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.plugins.PluginsUiState
import com.aveline.ai.mobile.presentation.theme.CardBackground
import com.aveline.ai.mobile.presentation.theme.CardBorder
import com.aveline.ai.mobile.presentation.theme.EmotionColorMapping
import com.aveline.ai.mobile.presentation.theme.EmotionState
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 常规 tab:合并 Settings + Plugins + Tools 的常规设置。
 *
 * 分区:网络 / 模型 / 语音 / 响应 / 情绪 / 学习模式 / 敏感模式。
 * 响应长度在此处为唯一入口,统一使用 Settings 的 [onResponseLengthChange]。
 * 网络与模型分区实现见 [SettingsGeneralSections.kt]。
 */
@Composable
fun SettingsGeneralTab(
    settingsUiState: SettingsUiState,
    pluginsUiState: PluginsUiState,
    onBackendUrlChange: (String) -> Unit,
    onTokenChange: (String) -> Unit,
    onTestConnection: () -> Unit,
    onSaveBackendUrl: () -> Unit,
    onTunnelUrlChange: (String) -> Unit,
    onToggleTunnel: (Boolean) -> Unit,
    onModelChange: (String) -> Unit,
    onVoiceIdChange: (String) -> Unit,
    onResponseLengthChange: (String) -> Unit,
    onToggleAutoTts: () -> Unit,
    onSetManualEmotion: (String) -> Unit,
    onToggleStudyMode: () -> Unit,
    onToggleAutoEmotion: () -> Unit,
    onShowEmotionSelector: () -> Unit,
    onHideEmotionSelector: () -> Unit,
    onToggleSensitive: (Boolean) -> Unit,
    onRefreshSensitive: () -> Unit,
    onHideSaveConfirm: () -> Unit,
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

        // 网络
        SectionCard(
            title = "网络",
            icon = Icons.Default.Language,
            subtitle = "后端连接与认证"
        ) {
            NetworkSection(
                backendUrl = settingsUiState.backendUrl,
                accessToken = settingsUiState.accessToken,
                isValid = settingsUiState.isBackendUrlValid,
                isTesting = settingsUiState.isTestingConnection,
                testResult = settingsUiState.connectionTestResult,
                onUrlChange = onBackendUrlChange,
                onTokenChange = onTokenChange,
                onTestConnection = onTestConnection,
                onSave = onSaveBackendUrl,
                tunnelUrl = settingsUiState.tunnelUrl,
                isUsingTunnel = settingsUiState.isUsingTunnel,
                onTunnelUrlChange = onTunnelUrlChange,
                onToggleTunnel = onToggleTunnel
            )
        }

        // 模型
        SectionCard(
            title = "模型",
            icon = Icons.Default.SmartToy,
            subtitle = "语言模型选择"
        ) {
            ModelSection(
                availableModels = settingsUiState.availableModels,
                selectedModel = settingsUiState.selectedModel,
                isLoading = settingsUiState.isLoadingModels,
                error = settingsUiState.modelLoadError,
                onModelSelected = { onModelChange(it) }
            )
        }

        // 语音(标题行承载自动 TTS 开关,内容区保留语音 ID 输入)
        SectionCard(
            title = "语音",
            icon = Icons.Default.Mic,
            subtitle = "语音合成与播报",
            trailingContent = {
                Switch(
                    checked = settingsUiState.autoTtsEnabled,
                    onCheckedChange = { onToggleAutoTts() }
                )
            }
        ) {
            OutlinedTextField(
                value = settingsUiState.selectedVoiceId,
                onValueChange = onVoiceIdChange,
                label = { Text("语音 ID") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
        }

        // 响应(统一入口,仅此一处)
        SectionCard(
            title = "响应",
            icon = Icons.Default.Speed,
            subtitle = "回复长度(统一入口)"
        ) {
            ResponseLengthSection(
                currentLength = settingsUiState.responseLength,
                onLengthChange = { onResponseLengthChange(it.name) }
            )
        }

        // 情绪
        SectionCard(
            title = "情绪",
            icon = Icons.Outlined.Mood,
            subtitle = "情绪与呼吸灯"
        ) {
            EmotionSection(
                currentEmotion = pluginsUiState.settings.manualEmotion,
                autoEmotion = pluginsUiState.settings.autoEmotion,
                onEmotionClick = onShowEmotionSelector,
                onToggleAutoEmotion = onToggleAutoEmotion
            )
        }

        // 学习模式(标题行承载开关,避免内容区重复标题)
        SectionCard(
            title = "结构化学习",
            icon = Icons.Default.School,
            subtitle = if (pluginsUiState.studyModeEnabled) {
                "活跃文件 ${pluginsUiState.activeStudyFileCount} · 分块 ${pluginsUiState.studyChunkCount}"
            } else {
                "学习模式当前空闲"
            },
            trailingContent = {
                Switch(
                    checked = pluginsUiState.studyModeEnabled,
                    onCheckedChange = { onToggleStudyMode() }
                )
            }
        ) {
        }

        // 敏感模式(标题行承载开关,刷新按钮放在内容区)
        SectionCard(
            title = "敏感模式",
            icon = Icons.Default.Security,
            subtitle = if (pluginsUiState.sensitiveEnabled == true) "完整内容访问" else "标准过滤",
            trailingContent = {
                Switch(
                    checked = pluginsUiState.sensitiveEnabled == true,
                    onCheckedChange = { onToggleSensitive(it) },
                    enabled = !pluginsUiState.isSensitiveLoading
                )
            }
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = if (pluginsUiState.sensitiveEnabled == true) "本地模式已启用" else "云端模式已启用",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextTertiary
                )
                IconButton(
                    onClick = onRefreshSensitive,
                    enabled = !pluginsUiState.isSensitiveLoading
                ) {
                    if (pluginsUiState.isSensitiveLoading) {
                        CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                    } else {
                        Icon(Icons.Default.Refresh, contentDescription = "刷新", tint = TextTertiary, modifier = Modifier.size(20.dp))
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(16.dp))
    }

    // 保存确认对话框
    if (settingsUiState.showSaveConfirm) {
        AlertDialog(
            onDismissRequest = onHideSaveConfirm,
            title = { Text("设置已保存") },
            text = { Text("后端地址已更新,请重启应用以生效。") },
            confirmButton = { TextButton(onClick = onHideSaveConfirm) { Text("确定") } }
        )
    }

    // 情绪选择对话框
    if (pluginsUiState.showEmotionSelector) {
        EmotionSelectorDialog(
            selectedEmotion = pluginsUiState.settings.manualEmotion,
            onSelect = { onSetManualEmotion(it.name) },
            onDismiss = onHideEmotionSelector
        )
    }
}

/** 响应长度分区:单选按钮。 */
@Composable
private fun ResponseLengthSection(
    currentLength: ResponseLength,
    onLengthChange: (ResponseLength) -> Unit
) {
    Column {
        ResponseLength.values().forEach { length ->
            Row(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                RadioButton(selected = currentLength == length, onClick = { onLengthChange(length) })
                Spacer(modifier = Modifier.width(8.dp))
                Column {
                    Text(text = length.label, style = MaterialTheme.typography.bodyMedium, color = TextPrimary)
                    Text(text = length.description, style = MaterialTheme.typography.bodySmall, color = TextTertiary)
                }
            }
        }
    }
}

/** 情绪分区:自动情绪开关 + 手动情绪选择入口(始终可点击)。 */
@Composable
private fun EmotionSection(
    currentEmotion: EmotionType?,
    autoEmotion: Boolean,
    onEmotionClick: () -> Unit,
    onToggleAutoEmotion: () -> Unit
) {
    Column {
        GeneralSwitchRow(
            title = "自动情绪",
            subtitle = "随后端情绪更新同步呼吸灯状态",
            checked = autoEmotion,
            onToggle = onToggleAutoEmotion
        )
        // 手动情绪选择入口(始终可点击,点击时若自动情绪开启会先关闭)
        Spacer(modifier = Modifier.height(12.dp))
        Text(text = "手动情绪(呼吸灯颜色)", style = MaterialTheme.typography.bodyMedium, color = TextPrimary)
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = if (autoEmotion) "点击切换(将自动关闭自动情绪)" else "点击下方按钮切换呼吸灯颜色",
            style = MaterialTheme.typography.labelSmall,
            color = TextTertiary
        )
        Spacer(modifier = Modifier.height(8.dp))
        val emotion = currentEmotion ?: EmotionType.NEUTRAL
        Card(
            onClick = onEmotionClick,
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(containerColor = CardBackground),
            border = BorderStroke(1.dp, CardBorder)
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(emotion.label, color = TextPrimary)
                Spacer(modifier = Modifier.width(8.dp))
                EmotionColorPreview(emotion = emotion)
                Spacer(modifier = Modifier.weight(1f))
                Text("点击切换", style = MaterialTheme.typography.labelSmall, color = TextTertiary)
            }
        }
    }
}

/** 通用开关行:标题/副标题 + Switch。 */
@Composable
private fun GeneralSwitchRow(
    title: String,
    subtitle: String,
    checked: Boolean,
    onToggle: () -> Unit
) {
    Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(modifier = Modifier.weight(1f)) {
            Text(text = title, style = MaterialTheme.typography.bodyMedium, color = TextPrimary)
            Text(text = subtitle, style = MaterialTheme.typography.bodySmall, color = TextTertiary)
        }
        Switch(checked = checked, onCheckedChange = { onToggle() })
    }
}

/** 情绪选择对话框:单选列表。 */
@Composable
private fun EmotionSelectorDialog(
    selectedEmotion: EmotionType?,
    onSelect: (EmotionType) -> Unit,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("选择情绪") },
        text = {
            Column {
                EmotionType.values().forEach { emotion ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onSelect(emotion); onDismiss() }
                            .padding(vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        RadioButton(
                            selected = selectedEmotion == emotion,
                            onClick = null
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(emotion.label, style = MaterialTheme.typography.bodyLarge)
                        Spacer(modifier = Modifier.width(8.dp))
                        EmotionColorPreview(emotion = emotion)
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("关闭") } }
    )
}

/**
 * 情绪颜色预览:把呼吸灯 4 个颜色以小圆点形式并排展示,替代 emoji。
 */
@Composable
private fun EmotionColorPreview(
    emotion: EmotionType,
    modifier: Modifier = Modifier
) {
    val emotionState = EmotionState.fromString(emotion.name.lowercase())
    val colors = EmotionColorMapping.getColorsForEmotion(emotionState)

    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        colors.colors.forEach { color ->
            Box(
                modifier = Modifier
                    .size(14.dp)
                    .clip(CircleShape)
                    .background(color)
            )
        }
    }
}
