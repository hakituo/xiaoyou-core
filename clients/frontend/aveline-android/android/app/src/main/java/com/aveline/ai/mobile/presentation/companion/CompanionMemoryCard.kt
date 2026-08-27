package com.aveline.ai.mobile.presentation.companion

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.StarBorder
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.domain.models.MemoryType
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 单个记忆卡片:点击查看完整详情,点击重要标记切换、长按或点删除按钮删除。
 *
 * @param memory 记忆数据
 * @param onClick 点击卡片(查看详情)回调
 * @param onToggleImportant 切换重要标记回调
 * @param onDelete 删除回调
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun MemoryCardItem(
    memory: Memory,
    onClick: () -> Unit,
    onToggleImportant: () -> Unit,
    onDelete: () -> Unit
) {
    val typeColor = getTypeColor(memory.type)
    val cardColor = if (memory.isImportant) {
        Color(0xFFFFC107).copy(alpha = 0.1f)
    } else {
        Color(0x33000000)
    }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(
                onClick = onClick,
                onLongClick = onDelete
            ),
        colors = CardDefaults.cardColors(containerColor = cardColor),
        shape = RoundedCornerShape(12.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp)
        ) {
            // 顶部:类型标签 + 操作按钮
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Surface(
                    color = typeColor.copy(alpha = 0.2f),
                    shape = RoundedCornerShape(4.dp)
                ) {
                    Text(
                        text = memory.formattedType,
                        style = MaterialTheme.typography.labelSmall,
                        color = typeColor,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)
                    )
                }
                Row {
                    // 重要标记切换
                    IconButton(
                        onClick = onToggleImportant,
                        modifier = Modifier.size(28.dp)
                    ) {
                        Icon(
                            imageVector = if (memory.isImportant) Icons.Default.Star else Icons.Default.StarBorder,
                            contentDescription = if (memory.isImportant) "取消重要" else "标记重要",
                            tint = if (memory.isImportant) Color(0xFFFFC107) else TextTertiary,
                            modifier = Modifier.size(18.dp)
                        )
                    }
                    // 删除按钮
                    IconButton(
                        onClick = onDelete,
                        modifier = Modifier.size(28.dp)
                    ) {
                        Icon(
                            imageVector = Icons.Default.Delete,
                            contentDescription = "删除",
                            tint = Color(0xFFEF4444),
                            modifier = Modifier.size(18.dp)
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            // 记忆内容
            Text(
                text = memory.content,
                style = MaterialTheme.typography.bodyMedium,
                color = TextPrimary,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis
            )

            // 标签
            if (memory.tags.isNotEmpty()) {
                Spacer(modifier = Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    memory.tags.take(3).forEach { tag ->
                        Surface(
                            color = Color(0x1A000000),
                            shape = RoundedCornerShape(4.dp)
                        ) {
                            Text(
                                text = "#$tag",
                                style = MaterialTheme.typography.labelSmall,
                                color = TextSecondary,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                            )
                        }
                    }
                    if (memory.tags.size > 3) {
                        Text(
                            text = "+${memory.tags.size - 3}",
                            style = MaterialTheme.typography.labelSmall,
                            color = TextTertiary,
                            modifier = Modifier.align(Alignment.CenterVertically)
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            // 底部:创建时间 + 访问次数
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = memory.formattedCreatedAt,
                    style = MaterialTheme.typography.labelSmall,
                    color = TextTertiary
                )
                if (memory.accessCount > 0) {
                    Text(
                        text = "访问 ${memory.accessCount} 次",
                        style = MaterialTheme.typography.labelSmall,
                        color = TextTertiary
                    )
                }
            }
        }
    }
}

/** 记忆类型对应颜色（与后端 taxonomy 分类对齐） */
internal fun getTypeColor(type: MemoryType): Color = when (type) {
    MemoryType.DAILY -> Color(0xFF2196F3)
    MemoryType.LEARNING -> Color(0xFF9C27B0)
    MemoryType.WORK -> Color(0xFF4CAF50)
    MemoryType.FESTIVAL -> Color(0xFFFF9800)
    MemoryType.HEALTH -> Color(0xFFF44336)
    MemoryType.PROFILE -> Color(0xFF00BCD4)
    MemoryType.ENTERTAINMENT -> Color(0xFFE91E63)
    MemoryType.FINANCE -> Color(0xFF3F51B5)
    MemoryType.TECH -> Color(0xFF009688)
    MemoryType.EMOTION -> Color(0xFFFF5722)
    MemoryType.RELATIONSHIP -> Color(0xFF795548)
    MemoryType.SENSITIVE -> Color(0xFFC62828)
    MemoryType.PREFERENCE -> Color(0xFF9C27B0)
    MemoryType.THINKING -> Color(0xFF607D8B)
    MemoryType.UNCATEGORIZED -> Color(0xFF9E9E9E)
    MemoryType.UNKNOWN -> Color(0xFF9E9E9E)
}

/**
 * 记忆类型的中文显示名。
 */
internal fun getTypeDisplayName(type: MemoryType): String = when (type) {
    MemoryType.DAILY -> "日常"
    MemoryType.LEARNING -> "学习"
    MemoryType.WORK -> "工作"
    MemoryType.FESTIVAL -> "节日"
    MemoryType.HEALTH -> "健康"
    MemoryType.PROFILE -> "画像"
    MemoryType.ENTERTAINMENT -> "娱乐"
    MemoryType.FINANCE -> "财务"
    MemoryType.TECH -> "科技"
    MemoryType.EMOTION -> "情绪"
    MemoryType.RELATIONSHIP -> "关系"
    MemoryType.SENSITIVE -> "敏感"
    MemoryType.PREFERENCE -> "偏好"
    MemoryType.THINKING -> "思考"
    MemoryType.UNCATEGORIZED -> "未分类"
    MemoryType.UNKNOWN -> "未知"
}

/**
 * 空记忆状态。
 *
 * @param hasFilters 是否有过滤条件
 * @param onClearFilters 清除过滤回调
 */
@Composable
internal fun EmptyMemoryState(
    hasFilters: Boolean,
    onClearFilters: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = if (hasFilters) "没有找到匹配的记忆" else "暂无记忆",
            style = MaterialTheme.typography.bodyMedium,
            color = TextSecondary
        )
        if (hasFilters) {
            Spacer(modifier = Modifier.height(8.dp))
            TextButton(onClick = onClearFilters) {
                Text("清除过滤条件")
            }
        }
    }
}
