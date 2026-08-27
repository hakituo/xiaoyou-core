package com.aveline.ai.mobile.presentation.companion

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.outlined.SmartToy
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.AIModel
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * Companion 模型 Tab。
 *
 * 放在「状态」与「人设」之间。像人设列表一样把所有可用模型以卡片形式全部展示，
 * 当前选中模型高亮并显示对勾；数据跟随后端当前使用模型（/v1/models 的 current），
 * 修改后全端生效。
 *
 * @param availableModels 可用模型列表
 * @param selectedModel 当前选中模型
 * @param isLoading 列表加载中
 * @param error 加载错误
 * @param onModelSelected 选中模型回调（传模型 id）
 */
@Composable
fun CompanionModelTab(
    availableModels: List<AIModel>,
    selectedModel: AIModel?,
    isLoading: Boolean,
    error: String?,
    onModelSelected: (String) -> Unit
) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp),
        contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item {
            SectionCard(
                title = "模型设置",
                icon = Icons.Outlined.SmartToy,
                subtitle = "跟随后端当前使用模型，修改后全端生效"
            ) {
                if (error != null) {
                    Text(
                        text = error,
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary
                    )
                } else if (isLoading && availableModels.isEmpty()) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 16.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        androidx.compose.material3.CircularProgressIndicator(
                            color = EmotionGreen,
                            modifier = Modifier.size(20.dp),
                            strokeWidth = 2.dp
                        )
                    }
                } else if (availableModels.isEmpty()) {
                    Text(
                        text = "暂无可用模型",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextTertiary
                    )
                } else {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        availableModels.forEach { model ->
                            val isSelected = model.id == selectedModel?.id
                            ModelListItem(
                                model = model,
                                isSelected = isSelected,
                                onClick = { onModelSelected(model.id) }
                            )
                        }
                    }
                }
            }
        }
    }
}

/**
 * 单个模型列表项卡片：模型名 + provider 副标题，选中时绿框高亮并显示对勾。
 */
@Composable
private fun ModelListItem(
    model: AIModel,
    isSelected: Boolean,
    onClick: () -> Unit
) {
    val cardBg = if (isSelected) EmotionGreen.copy(alpha = 0.08f) else Color.Transparent
    val cardBorder = if (isSelected) {
        androidx.compose.foundation.BorderStroke(1.5.dp, EmotionGreen)
    } else {
        androidx.compose.foundation.BorderStroke(1.dp, TextSecondary.copy(alpha = 0.15f))
    }
    val textColor = if (isSelected) EmotionGreen else TextPrimary

    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp)),
        shape = RoundedCornerShape(10.dp),
        color = cardBg,
        border = cardBorder,
        onClick = onClick
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
                    text = model.name,
                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold),
                    color = textColor,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(modifier = Modifier.height(2.dp))
                Text(
                    text = model.provider,
                    style = MaterialTheme.typography.labelSmall,
                    color = TextSecondary
                )
            }
            if (isSelected) {
                Icon(
                    imageVector = Icons.Default.Check,
                    contentDescription = "当前模型",
                    tint = EmotionGreen,
                    modifier = Modifier.size(18.dp)
                )
            }
        }
    }
}
