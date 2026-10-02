package com.aveline.ai.mobile.presentation.conversations

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 人设面板里的「语音音色」选择器。
 *
 * 候选来自后端 `GET /api/v1/media/voices`（即 app.yaml 的 `voice_map` 角色名），
 * 默认值是该 persona 的 `default_voice`，与 QQ 端 VoiceService 同一个源；
 * 用户一旦手选就写进本地覆盖（AppPreferences.setPersonaVoice），
 * 优先级高于角色默认音色，不会被接口返回值盖掉。
 *
 * Android 侧不维护任何"角色 -> 音色"表，候选与默认值全部来自后端。
 *
 * 这里刻意只收 `List<String>`（音色名）而不是 DTO：调用方无需引入网络层类型。
 *
 * @param voiceNames 可选音色名（后端返回，空表示没拉到）
 * @param selectedVoice 当前生效的音色名（用户手选 > 角色默认）
 * @param isOverridden 当前值是否为用户手选（决定要不要显示"恢复默认"）
 * @param onSelectVoice 选择一个音色
 * @param onResetVoice 清除手选，恢复跟随角色默认音色
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PersonaVoiceSelector(
    voiceNames: List<String>,
    selectedVoice: String,
    isOverridden: Boolean,
    onSelectVoice: (String) -> Unit,
    onResetVoice: () -> Unit,
    modifier: Modifier = Modifier,
    /** 是否自带标题。嵌在已有标题的 SectionCard 里时传 false，避免标题重复。 */
    showTitle: Boolean = true
) {
    Column(modifier = modifier.fillMaxWidth()) {
        if (showTitle) {
            Text(
                text = "语音音色",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurface
            )
        }

        if (voiceNames.isEmpty()) {
            Text(
                text = "未读取到可用音色（后端未配置或未连接）",
                style = MaterialTheme.typography.labelSmall,
                color = TextTertiary
            )
            return@Column
        }

        FlowRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            voiceNames.forEach { voiceName ->
                FilterChip(
                    selected = voiceName == selectedVoice,
                    onClick = { onSelectVoice(voiceName) },
                    label = { Text(voiceName) }
                )
            }
        }

        if (isOverridden) {
            TextButton(onClick = onResetVoice) {
                Text(
                    text = "恢复角色默认音色",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextTertiary
                )
            }
        } else {
            Text(
                text = "当前跟随角色默认音色",
                style = MaterialTheme.typography.labelSmall,
                color = TextTertiary
            )
        }
    }
}
