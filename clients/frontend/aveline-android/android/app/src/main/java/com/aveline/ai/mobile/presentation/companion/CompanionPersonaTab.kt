package com.aveline.ai.mobile.presentation.companion

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.persona.PersonaUiState
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import com.aveline.ai.mobile.presentation.theme.EmotionPurple
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * Companion 人设 Tab。
 *
 * 展示当前激活人设信息(名称/描述/特征)和**当前角色范围内**的人设列表（可点击切换）。
 *
 * 人设切换只在当前角色范围内进行——例如当前是 Aveline 角色，只显示 Aveline 的几个 persona
 * （core_aveline/Aveline_Obsidian/Aveline_QQ_Master 等），不显示其他角色（Ling/小鹿）的 persona。
 * 跨角色切换通过会话列表点击角色进 Chat 实现。
 *
 * @param uiState 人设页 UI 状态
 * @param onSwitchPersona 切换人设回调(filename)
 */
@Composable
fun CompanionPersonaTab(
    uiState: PersonaUiState,
    viewingFilename: String? = null,
    onSwitchPersona: (String) -> Unit
) {
    // 伴侣详情直接展示当前聊天角色的人设列表，点击可切换。
    val personaList = remember(uiState.personas, viewingFilename, uiState.activeFilename) {
        // 解析所有 persona
        val all = uiState.personas.mapNotNull { p ->
            try { p.jsonObject } catch (_: Exception) { null }
        }
        // 找“正在查看角色”的 role（进哪个角色的聊天就按哪个角色过滤列表），
        // 回退到全局 active persona。
        val targetFilename = viewingFilename ?: uiState.activeFilename
        val activePersona = all.firstOrNull { p ->
            try { p["filename"]?.jsonPrimitive?.content == targetFilename } catch (_: Exception) { false }
        }
        val activeRole = if (activePersona != null) {
            try {
                val name = activePersona["name"]?.jsonPrimitive?.content ?: ""
                activePersona["role"]?.jsonPrimitive?.content
                    ?: name.split("(")[0].split("（")[0].trim().ifEmpty { name }
            } catch (_: Exception) { null }
        } else null
        // 只显示当前角色范围内的 persona（同 role）
        if (activeRole.isNullOrBlank()) {
            all // 兜底：role 拿不到时显示全部
        } else {
            all.filter { p ->
                try {
                    val name = p["name"]?.jsonPrimitive?.content ?: ""
                    val pRole = p["role"]?.jsonPrimitive?.content
                        ?: name.split("(")[0].split("（")[0].trim().ifEmpty { name }
                    pRole == activeRole
                } catch (_: Exception) { false }
            }
        }
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp),
        contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // 切换中加载指示器
        item {
            if (uiState.isSwitching) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    CircularProgressIndicator(
                        color = EmotionGreen,
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = "正在切换人设...",
                        style = MaterialTheme.typography.labelMedium,
                        color = TextSecondary
                    )
                }
            }
        }

        // 直接展示人设卡片
        if (uiState.personas.isEmpty()) {
            item {
                SectionCard(title = "人设") {
                    Text(
                        text = "暂无可选人设",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextTertiary
                    )
                }
            }
        } else {
            itemsIndexed(
                items = personaList,
                key = { index, persona ->
                    try { persona["filename"]?.jsonPrimitive?.content } catch (_: Exception) { null } ?: "persona_$index"
                }
            ) { _, persona ->
                val filename = try { persona["filename"]?.jsonPrimitive?.content } catch (_: Exception) { null } ?: ""
                val name = try { persona["name"]?.jsonPrimitive?.content } catch (_: Exception) { null } ?: "Unknown"
                val version = try { persona["version"]?.jsonPrimitive?.content } catch (_: Exception) { null } ?: "?.?.?"
                // 用“正在查看的角色”判定是否选中（纯查看，不切对话人设）。
                val isActive = filename == (viewingFilename ?: uiState.activeFilename)

                PersonaListItem(
                    name = name,
                    version = version,
                    isActive = isActive,
                    isSwitching = uiState.isSwitching,
                    onClick = { onSwitchPersona(filename) }
                )
            }
        }
    }
}

/**
 * 单个人设列表项卡片（可点击切换，仅限当前角色范围内）。
 */
@Composable
private fun PersonaListItem(
    name: String,
    version: String,
    isActive: Boolean,
    isSwitching: Boolean,
    onClick: () -> Unit
) {
    val containerColor = if (isActive) EmotionGreen.copy(alpha = 0.12f) else Color(0x14000000)
    val borderColor = if (isActive) EmotionGreen.copy(alpha = 0.3f) else Color(0x14FFFFFF)
    val textColor = if (isActive) EmotionGreen.copy(alpha = 0.9f) else TextPrimary

    Card(
        onClick = onClick,
        enabled = !isSwitching && !isActive,
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = containerColor),
        border = BorderStroke(1.dp, borderColor),
        shape = RoundedCornerShape(10.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = name,
                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold),
                    color = textColor,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    text = "版本: $version",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextTertiary
                )
            }
            if (isActive) {
                Icon(
                    imageVector = Icons.Default.Check,
                    contentDescription = "当前人设",
                    tint = EmotionGreen,
                    modifier = Modifier.size(18.dp)
                )
            }
        }
    }
}
