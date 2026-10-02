package com.aveline.ai.mobile.presentation.companion

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.automirrored.filled.Sort
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.domain.models.MemorySortOrder
import com.aveline.ai.mobile.domain.models.MemoryType
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.memory.MemoryUiState
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary

/**
 * Companion 记忆 Tab。
 *
 * 展示记忆搜索框、过滤按钮(类型/重要/排序)和记忆卡片列表。
 * 支持点击重要标记切换、长按删除(显示确认对话框)。
 *
 * @param uiState 记忆页 UI 状态
 * @param onSearch 搜索回调
 * @param onTypeFilterChange 类型过滤回调
 * @param onToggleImportantOnly 切换只看重要回调
 * @param onSortOrderChange 排序回调
 * @param onDeleteMemory 删除记忆回调
 * @param onToggleImportant 切换重要标记回调
 * @param onConfirmDelete 确认删除回调
 * @param onCancelDelete 取消删除回调
 * @param onClearFilters 清除过滤回调
 * @param onMemoryClick 点击记忆卡片(查看详情)回调
 * @param onCloseDetail 关闭记忆详情弹窗回调
 */
@Composable
fun CompanionMemoryTab(
    uiState: MemoryUiState,
    onSearch: (String) -> Unit,
    onTypeFilterChange: (MemoryType?) -> Unit,
    onToggleImportantOnly: () -> Unit,
    onSortOrderChange: (MemorySortOrder) -> Unit,
    onDeleteMemory: (Memory) -> Unit,
    onToggleImportant: (Memory) -> Unit,
    onConfirmDelete: () -> Unit,
    onCancelDelete: () -> Unit,
    onClearFilters: () -> Unit,
    onMemoryClick: (Memory) -> Unit,
    onCloseDetail: () -> Unit
) {
    Box(modifier = Modifier.fillMaxSize()) {
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 16.dp),
            contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // 搜索 + 过滤区
            item {
                SectionCard(title = "搜索") {
                    SearchAndFilterContent(
                        uiState = uiState,
                        onSearch = onSearch,
                        onTypeFilterChange = onTypeFilterChange,
                        onToggleImportantOnly = onToggleImportantOnly,
                        onSortOrderChange = onSortOrderChange,
                        onClearFilters = onClearFilters
                    )
                }
            }

            // 记忆列表区
            // 修复 P0-7:原实现把整个记忆列表放在单个 item 的 Column+forEach 中渲染,
            // 所有卡片一次性测量,无法享受 LazyColumn 的懒加载,记忆多时性能差。
            // 改为:加载/空状态用 SectionCard 包裹;有数据时每个卡片作为 LazyColumn 的 items。
            when {
                uiState.isLoading -> {
                    item {
                        SectionCard(title = "记忆列表") {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 24.dp),
                                contentAlignment = Alignment.Center
                            ) {
                                CircularProgressIndicator(color = Primary)
                            }
                        }
                    }
                }
                uiState.filteredMemories.isEmpty() -> {
                    item {
                        SectionCard(title = "记忆列表") {
                            EmptyMemoryState(
                                hasFilters = uiState.hasFilters,
                                onClearFilters = onClearFilters
                            )
                        }
                    }
                }
                else -> {
                    item {
                        Text(
                            text = "记忆列表",
                            style = MaterialTheme.typography.titleSmall,
                            color = TextPrimary,
                            modifier = Modifier.padding(start = 4.dp, top = 8.dp)
                        )
                    }
                    items(
                        items = uiState.filteredMemories,
                        key = { memory -> memory.id }
                    ) { memory ->
                        MemoryCardItem(
                            memory = memory,
                            onClick = { onMemoryClick(memory) },
                            onToggleImportant = { onToggleImportant(memory) },
                            onDelete = { onDeleteMemory(memory) }
                        )
                    }
                }
            }
        }

        // 删除确认对话框
        if (uiState.showDeleteConfirm && uiState.memoryToDelete != null) {
            AlertDialog(
                onDismissRequest = onCancelDelete,
                title = { Text("删除记忆") },
                text = {
                    Text("确定要删除这条记忆吗?\n\n\"${uiState.memoryToDelete.content.take(100)}...\"")
                },
                confirmButton = {
                    TextButton(
                        onClick = onConfirmDelete,
                        colors = ButtonDefaults.textButtonColors(
                            contentColor = MaterialTheme.colorScheme.error
                        )
                    ) {
                        Text("删除")
                    }
                },
                dismissButton = {
                    TextButton(onClick = onCancelDelete) {
                        Text("取消")
                    }
                }
            )
        }

        // 记忆详情弹窗
        if (uiState.showMemoryDetail && uiState.selectedMemory != null) {
            MemoryDetailDialog(
                memory = uiState.selectedMemory,
                onClose = onCloseDetail,
                onToggleImportant = { onToggleImportant(uiState.selectedMemory) },
                onDelete = { onDeleteMemory(uiState.selectedMemory) }
            )
        }
    }
}

/**
 * 记忆详情弹窗:展示记忆的完整内容、元信息与操作按钮。
 *
 * @param memory 待展示的记忆
 * @param onClose 关闭回调
 * @param onToggleImportant 切换重要标记回调
 * @param onDelete 删除回调
 */
@Composable
private fun MemoryDetailDialog(
    memory: Memory,
    onClose: () -> Unit,
    onToggleImportant: () -> Unit,
    onDelete: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onClose,
        title = {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text(
                    text = getTypeDisplayName(memory.type),
                    style = MaterialTheme.typography.titleMedium,
                    color = getTypeColor(memory.type)
                )
                if (memory.isImportant) {
                    AssistChip(
                        onClick = {},
                        label = { Text("重要") },
                        leadingIcon = {
                            Icon(
                                imageVector = Icons.Filled.Star,
                                contentDescription = null,
                                tint = Color(0xFFFFC107),
                                modifier = Modifier.size(16.dp)
                            )
                        },
                        colors = AssistChipDefaults.assistChipColors(
                            containerColor = Color(0xFFFFC107).copy(alpha = 0.15f)
                        )
                    )
                }
            }
        },
        text = {
            LazyColumn(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                item {
                    Text(
                        text = memory.content,
                        style = MaterialTheme.typography.bodyLarge,
                        color = TextPrimary
                    )
                }
                item {
                    Column(
                        modifier = Modifier.fillMaxWidth(),
                        verticalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
                        Text(
                            text = "标签: ${if (memory.tags.isNotEmpty()) memory.tags.joinToString("、") else "无"}",
                            style = MaterialTheme.typography.bodySmall,
                            color = TextSecondary
                        )
                        Text(
                            text = "访问次数: ${memory.accessCount}",
                            style = MaterialTheme.typography.bodySmall,
                            color = TextSecondary
                        )
                        Text(
                            text = "创建时间: ${memory.formattedCreatedAt}",
                            style = MaterialTheme.typography.bodySmall,
                            color = TextSecondary
                        )
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onToggleImportant) {
                Text(if (memory.isImportant) "取消重要" else "标为重要")
            }
        },
        dismissButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(
                    onClick = onDelete,
                    colors = ButtonDefaults.textButtonColors(
                        contentColor = MaterialTheme.colorScheme.error
                    )
                ) {
                    Text("删除")
                }
                TextButton(onClick = onClose) {
                    Text("关闭")
                }
            }
        }
    )
}

/**
 * 搜索框 + 过滤按钮(类型/重要/排序)。
 */
@Composable
private fun SearchAndFilterContent(
    uiState: MemoryUiState,
    onSearch: (String) -> Unit,
    onTypeFilterChange: (MemoryType?) -> Unit,
    onToggleImportantOnly: () -> Unit,
    onSortOrderChange: (MemorySortOrder) -> Unit,
    onClearFilters: () -> Unit
) {
    var showTypeMenu by remember { mutableStateOf(false) }
    var showSortMenu by remember { mutableStateOf(false) }

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        // 搜索框
        TextField(
            value = uiState.searchQuery,
            onValueChange = onSearch,
            placeholder = {
                Text("搜索记忆...", style = MaterialTheme.typography.bodyMedium, color = TextSecondary)
            },
            leadingIcon = {
                Icon(Icons.Default.Search, contentDescription = null, tint = TextSecondary)
            },
            trailingIcon = {
                if (uiState.searchQuery.isNotEmpty()) {
                    IconButton(onClick = { onSearch("") }) {
                        Icon(Icons.Default.Clear, contentDescription = "清除", tint = TextSecondary)
                    }
                }
            },
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(12.dp)),
            colors = TextFieldDefaults.colors(
                focusedContainerColor = Color(0x33000000),
                unfocusedContainerColor = Color(0x1A000000),
                focusedIndicatorColor = Color.Transparent,
                unfocusedIndicatorColor = Color.Transparent,
                cursorColor = Primary,
                focusedTextColor = TextPrimary,
                unfocusedTextColor = TextPrimary
            ),
            singleLine = true
        )

        // 过滤按钮行:类型 / 重要 / 排序
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // 类型过滤
            Box {
                FilterChip(
                    selected = uiState.selectedType != null,
                    onClick = { showTypeMenu = true },
                    label = {
                        Text(
                            text = uiState.selectedType?.let { memoryTypeLabel(it) } ?: "类型",
                            color = if (uiState.selectedType != null) Color.White else TextSecondary
                        )
                    },
                    trailingIcon = {
                        Icon(Icons.Default.ArrowDropDown, contentDescription = null, modifier = Modifier.size(16.dp))
                    },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = Primary,
                        selectedLabelColor = Color.White,
                        containerColor = Color(0x1A000000)
                    )
                )
                DropdownMenu(
                    expanded = showTypeMenu,
                    onDismissRequest = { showTypeMenu = false }
                ) {
                    DropdownMenuItem(
                        text = { Text("全部", color = if (uiState.selectedType == null) Primary else TextPrimary) },
                        onClick = {
                            onTypeFilterChange(null)
                            showTypeMenu = false
                        }
                    )
                    MemoryType.values().forEach { type ->
                        DropdownMenuItem(
                            text = {
                                Text(
                                    memoryTypeLabel(type),
                                    color = if (uiState.selectedType == type) Primary else TextPrimary
                                )
                            },
                            onClick = {
                                onTypeFilterChange(type)
                                showTypeMenu = false
                            }
                        )
                    }
                }
            }

            // 重要过滤
            FilterChip(
                selected = uiState.showImportantOnly,
                onClick = onToggleImportantOnly,
                label = {
                    Text(
                        "重要",
                        color = if (uiState.showImportantOnly) Color.White else TextSecondary
                    )
                },
                leadingIcon = if (uiState.showImportantOnly) {
                    { Icon(Icons.Default.Star, contentDescription = null, modifier = Modifier.size(16.dp), tint = Color.White) }
                } else null,
                colors = FilterChipDefaults.filterChipColors(
                    selectedContainerColor = Color(0xFFFFC107),
                    selectedLabelColor = Color.White,
                    containerColor = Color(0x1A000000)
                )
            )

            // 排序
            Box {
                AssistChip(
                    onClick = { showSortMenu = true },
                    label = {
                        Text(
                            getSortOrderLabel(uiState.sortOrder),
                            color = TextSecondary
                        )
                    },
                    leadingIcon = {
                        Icon(Icons.AutoMirrored.Filled.Sort, contentDescription = null, modifier = Modifier.size(16.dp), tint = TextSecondary)
                    },
                    colors = AssistChipDefaults.assistChipColors(
                        containerColor = Color(0x1A000000)
                    )
                )
                DropdownMenu(
                    expanded = showSortMenu,
                    onDismissRequest = { showSortMenu = false }
                ) {
                    MemorySortOrder.values().forEach { order ->
                        DropdownMenuItem(
                            text = {
                                Text(
                                    getSortOrderLabel(order),
                                    color = if (uiState.sortOrder == order) Primary else TextPrimary
                                )
                            },
                            onClick = {
                                onSortOrderChange(order)
                                showSortMenu = false
                            }
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.weight(1f))

            // 清除过滤
            if (uiState.hasFilters) {
                TextButton(
                    onClick = onClearFilters,
                    colors = ButtonDefaults.textButtonColors(contentColor = TextSecondary)
                ) {
                    Text("清除", style = MaterialTheme.typography.labelMedium)
                }
            }
        }
    }
}

// ===== 辅助函数 =====

/** 记忆类型中文标签（与后端 taxonomy 分类对齐） */
private fun memoryTypeLabel(type: MemoryType): String = when (type) {
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

/** 排序方式中文标签 */
private fun getSortOrderLabel(order: MemorySortOrder): String = when (order) {
    MemorySortOrder.NEWEST_FIRST -> "最新优先"
    MemorySortOrder.OLDEST_FIRST -> "最早优先"
    MemorySortOrder.MOST_ACCESSED -> "访问最多"
    MemorySortOrder.MOST_IMPORTANT -> "最重要"
}
