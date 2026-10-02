package com.aveline.ai.mobile.presentation.study

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.automirrored.filled.Sort
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.EmojiEvents
import androidx.compose.material.icons.filled.LocalFireDepartment
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.School
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 词汇 Tab。
 *
 * 展示词汇仪表盘、复习总览（含记忆曲线）、词典搜索、错题本和手动记录。
 *
 * @param uiState 词汇复习域 UI 状态
 * @param onStartReview 开始复习
 * @param onStartNewWords 开始背新单词
 * @param onToggleOrder 切换排序模式
 * @param onAddManualStudy 手动记录当天背诵单词数
 * @param onSearch 词典搜索
 * @param onClearSearch 清空搜索结果
 * @param onOpenBooks 打开词书列表
 */
@Composable
fun StudyVocabTab(
    uiState: VocabUiState,
    onStartReview: () -> Unit,
    onStartNewWords: () -> Unit = {},
    onToggleOrder: () -> Unit = {},
    onAddManualStudy: (Int) -> Unit = {},
    onOpenBooks: () -> Unit = {},
    onSearch: (String) -> Unit = {},
    onClearSearch: () -> Unit = {}
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // 词汇仪表盘（含词书入口、背新单词按钮）
        VocabDashboard(
            uiState = uiState,
            onStartReview = onStartReview,
            onStartNewWords = onStartNewWords,
            onToggleOrder = onToggleOrder,
            onOpenBooks = onOpenBooks
        )

        // 复习总览（连续天数 + 记忆曲线）
        ReviewOverviewCard(uiState = uiState)

        // 词典搜索
        DictionarySearchCard(
            uiState = uiState,
            onSearch = onSearch,
            onClearSearch = onClearSearch
        )

        // 错题本
        MistakesCard(uiState = uiState)

        // 手动记录背诵量
        ManualStudyCard(
            todayCount = uiState.manualStudyToday,
            onAddManualStudy = onAddManualStudy
        )
    }
}

/** 词汇仪表盘:今日待学文案 + 统计卡 + 词书入口 + 排序切换 + 复习/背新词按钮 */
@Composable
private fun VocabDashboard(
    uiState: VocabUiState,
    onStartReview: () -> Unit,
    onStartNewWords: () -> Unit,
    onToggleOrder: () -> Unit = {},
    onOpenBooks: () -> Unit = {}
) {
    val reviewCount = uiState.learnWords.count { it.status == "review" }
    val newCount = uiState.learnWords.count { it.status == "new" }
    val isShuffle = uiState.wordOrder == "shuffle"
    val overview = uiState.reviewOverview

    SectionCard(title = "词汇仪表盘") {
        // 今日学习目标文案
        Text(
            text = when {
                reviewCount > 0 && newCount > 0 -> "今日有 ${reviewCount + newCount} 个词汇待学习（${newCount} 新词 + ${reviewCount} 复习）"
                reviewCount > 0 -> "今日有 $reviewCount 个词汇待复习"
                newCount > 0 -> "今日有 $newCount 个新词待学习"
                else -> "今日没有待学习的词汇，做得好！"
            },
            style = MaterialTheme.typography.bodyMedium,
            color = TextSecondary
        )

        Spacer(modifier = Modifier.height(16.dp))

        // 待复习 / 新词 / 已掌握：等宽卡片
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            VocabStatCard(
                modifier = Modifier.weight(1f),
                icon = Icons.Default.Schedule,
                label = "待复习",
                value = reviewCount.toString(),
                color = Color(0xFF3B82F6)
            )
            VocabStatCard(
                modifier = Modifier.weight(1f),
                icon = Icons.Default.School,
                label = "新词",
                value = newCount.toString(),
                color = Color(0xFFF59E0B)
            )
            VocabStatCard(
                modifier = Modifier.weight(1f),
                icon = Icons.Default.EmojiEvents,
                label = "已掌握",
                value = (overview?.masteredWords ?: 0).toString(),
                color = EmotionGreen
            )
        }

        Spacer(modifier = Modifier.height(16.dp))

        // 词书入口：平铺一行
        BookEntryRow(
            currentBook = uiState.currentBook,
            bookCount = uiState.vocabBooks.size,
            onClick = onOpenBooks
        )

        Spacer(modifier = Modifier.height(20.dp))

        // 排序切换
        TextButton(
            onClick = onToggleOrder,
            modifier = Modifier.fillMaxWidth()
        ) {
            Icon(
                imageVector = if (isShuffle) Icons.Default.Shuffle else Icons.AutoMirrored.Filled.Sort,
                contentDescription = null,
                tint = EmotionGreen
            )
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                text = if (isShuffle) "当前：乱序 · 点击切顺序" else "当前：顺序 · 点击切乱序",
                color = EmotionGreen
            )
        }

        Spacer(modifier = Modifier.height(4.dp))

        // 复习 + 背新词按钮并排
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Button(
                onClick = onStartReview,
                modifier = Modifier.weight(1f),
                enabled = reviewCount > 0,
                colors = ButtonDefaults.buttonColors(containerColor = EmotionGreen)
            ) {
                Icon(Icons.Default.PlayArrow, contentDescription = null)
                Spacer(modifier = Modifier.width(8.dp))
                Text("开始复习")
            }
            Button(
                onClick = onStartNewWords,
                modifier = Modifier.weight(1f),
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFF59E0B))
            ) {
                Icon(Icons.Default.School, contentDescription = null)
                Spacer(modifier = Modifier.width(8.dp))
                Text("背新单词")
            }
        }
    }
}

/** 复习总览卡片：连续天数 + 待复习数 + 记忆曲线 */
@Composable
private fun ReviewOverviewCard(uiState: VocabUiState) {
    val overview = uiState.reviewOverview ?: return

    SectionCard(title = "复习总览", subtitle = "记忆保持趋势") {
        // 统计行
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            OverviewStatItem(
                modifier = Modifier.weight(1f),
                icon = Icons.Default.LocalFireDepartment,
                label = "连续天数",
                value = "${overview.streakDays}",
                color = Color(0xFFF59E0B)
            )
            OverviewStatItem(
                modifier = Modifier.weight(1f),
                icon = Icons.Default.Schedule,
                label = "今日待复习",
                value = "${overview.dueTodayCount}",
                color = Color(0xFF3B82F6)
            )
            OverviewStatItem(
                modifier = Modifier.weight(1f),
                icon = Icons.Default.EmojiEvents,
                label = "已学",
                value = "${overview.learnedWords}",
                color = EmotionGreen
            )
        }

        // 记忆曲线
        if (overview.memoryCurve.isNotEmpty()) {
            Spacer(modifier = Modifier.height(20.dp))
            Text(
                text = "记忆保持曲线预测",
                style = MaterialTheme.typography.labelMedium,
                color = TextSecondary
            )
            Spacer(modifier = Modifier.height(8.dp))
            MemoryCurveChart(points = overview.memoryCurve)
        }
    }
}

/** 记忆保持曲线折线图 */
@Composable
private fun MemoryCurveChart(points: List<MemoryCurvePoint>) {
    val maxValue = 100f
    val animationProgress = remember { Animatable(0f) }

    LaunchedEffect(points) {
        animationProgress.snapTo(0f)
        animationProgress.animateTo(1f, tween(800))
    }

    androidx.compose.foundation.Canvas(
        modifier = Modifier
            .fillMaxWidth()
            .height(120.dp)
            .clip(RoundedCornerShape(8.dp))
            .background(Color(0x0AFFFFFF))
    ) {
        if (points.size < 2) return@Canvas

        val w = size.width
        val h = size.height
        val padding = 16f
        val chartW = w - padding * 2
        val chartH = h - padding * 2

        // 绘制折线
        val path = Path()
        val visibleCount = (points.size * animationProgress.value).toInt()
            .coerceIn(2, points.size)

        for (i in 0 until visibleCount) {
            val p = points[i]
            val x = padding + (chartW * i / (points.size - 1).coerceAtLeast(1))
            val y = padding + chartH * (1f - (p.retention / maxValue).coerceIn(0f, 1f))
            if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }

        drawPath(
            path = path,
            color = EmotionGreen,
            style = Stroke(width = 3f)
        )

        // 绘制端点
        if (visibleCount > 0) {
            val lastP = points[visibleCount - 1]
            val lastX = padding + (chartW * (visibleCount - 1) / (points.size - 1).coerceAtLeast(1))
            val lastY = padding + chartH * (1f - (lastP.retention / maxValue).coerceIn(0f, 1f))
            drawCircle(
                color = EmotionGreen,
                radius = 5f,
                center = Offset(lastX, lastY)
            )
        }
    }
    // X 轴标签
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text("第1天", style = MaterialTheme.typography.labelSmall, color = TextTertiary)
        Text("第${points.size}天", style = MaterialTheme.typography.labelSmall, color = TextTertiary)
    }
}

/** 词典搜索卡片 */
@Composable
private fun DictionarySearchCard(
    uiState: VocabUiState,
    onSearch: (String) -> Unit,
    onClearSearch: () -> Unit
) {
    var query by remember { mutableStateOf("") }

    SectionCard(title = "词典搜索", subtitle = "查询单词释义") {
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            label = { Text("输入单词") },
            singleLine = true,
            trailingIcon = {
                if (query.isNotEmpty()) {
                    IconButton(onClick = {
                        query = ""
                        onClearSearch()
                    }) {
                        Icon(Icons.Default.Close, contentDescription = "清除")
                    }
                }
            },
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(modifier = Modifier.height(12.dp))
        Button(
            onClick = { onSearch(query) },
            modifier = Modifier.fillMaxWidth(),
            enabled = query.isNotBlank() && !uiState.isSearching,
            colors = ButtonDefaults.buttonColors(containerColor = EmotionGreen)
        ) {
            if (uiState.isSearching) {
                CircularProgressIndicator(
                    modifier = Modifier.size(16.dp),
                    strokeWidth = 2.dp,
                    color = Color.White
                )
            } else {
                Icon(Icons.Default.Search, contentDescription = null)
            }
            Spacer(modifier = Modifier.width(8.dp))
            Text("搜索")
        }

        // 搜索结果
        if (uiState.searchResults.isNotEmpty()) {
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = "搜索结果 (${uiState.searchResults.size})",
                style = MaterialTheme.typography.labelMedium,
                color = TextSecondary
            )
            Spacer(modifier = Modifier.height(8.dp))
            uiState.searchResults.forEach { result ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(8.dp))
                        .background(Color(0x14000000))
                        .padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = result.word,
                        style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold),
                        color = TextPrimary,
                        modifier = Modifier.width(110.dp)
                    )
                    Text(
                        text = result.translation,
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextSecondary,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f)
                    )
                }
                Spacer(modifier = Modifier.height(6.dp))
            }
        }
    }
}

/** 错题本卡片 */
@Composable
private fun MistakesCard(uiState: VocabUiState) {
    if (uiState.mistakes.isEmpty()) return

    SectionCard(
        title = "错题本",
        subtitle = "高频错误词",
        collapsible = true,
        defaultExpanded = false
    ) {
        uiState.mistakes.take(20).forEach { mistake ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(8.dp))
                    .background(Color(0x14000000))
                    .padding(12.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = mistake.word,
                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold),
                    color = TextPrimary,
                    modifier = Modifier.width(110.dp)
                )
                Text(
                    text = mistake.translation,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f)
                )
                Spacer(modifier = Modifier.width(8.dp))
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(4.dp))
                        .background(Color(0x1AEF4444))
                        .padding(horizontal = 6.dp, vertical = 2.dp)
                ) {
                    Text(
                        text = "×${mistake.errorCount}",
                        style = MaterialTheme.typography.labelSmall,
                        color = Color(0xFFEF4444),
                        fontWeight = FontWeight.Bold
                    )
                }
            }
            Spacer(modifier = Modifier.height(6.dp))
        }
    }
}

/** 手动记录当天背了多少个单词 */
@Composable
private fun ManualStudyCard(
    todayCount: Int = 0,
    onAddManualStudy: (Int) -> Unit
) {
    var text by remember { mutableStateOf("") }
    SectionCard(title = "手动记录") {
        Text(
            text = "记录今天在单词书/APP 之外实际背的单词数量",
            style = MaterialTheme.typography.bodySmall,
            color = TextSecondary
        )
        Spacer(modifier = Modifier.height(12.dp))
        // 今日累计展示
        if (todayCount > 0) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(8.dp))
                    .background(EmotionGreen.copy(alpha = 0.12f))
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    imageVector = Icons.Default.EmojiEvents,
                    contentDescription = null,
                    tint = EmotionGreen,
                    modifier = Modifier.size(18.dp)
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = "今日已记录 $todayCount 个",
                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold),
                    color = EmotionGreen
                )
            }
            Spacer(modifier = Modifier.height(12.dp))
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            OutlinedTextField(
                value = text,
                onValueChange = { text = it.filter { c -> c.isDigit() }.take(5) },
                label = { Text("数量") },
                singleLine = true,
                modifier = Modifier.weight(1f)
            )
            Button(
                onClick = {
                    val n = text.toIntOrNull()
                    if (n != null && n > 0) {
                        onAddManualStudy(n)
                        text = ""
                    }
                },
                enabled = text.toIntOrNull()?.let { it > 0 } ?: false,
                colors = ButtonDefaults.buttonColors(containerColor = EmotionGreen)
            ) {
                Text("记录")
            }
        }
    }
}

/** 词书入口行:显示当前词书与可选词书数量,点击进入词书列表 */
@Composable
private fun BookEntryRow(
    currentBook: String,
    bookCount: Int,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(Color(0x14000000))
            .clickable { onClick() }
            .padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = Icons.AutoMirrored.Filled.MenuBook,
            contentDescription = null,
            tint = EmotionGreen,
            modifier = Modifier.size(20.dp)
        )
        Spacer(modifier = Modifier.width(10.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = currentBook.ifBlank { "未选词书" },
                style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.Bold),
                color = TextPrimary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Text(
                text = if (bookCount > 0) "$bookCount 本可选" else "无可用词书",
                style = MaterialTheme.typography.labelSmall,
                color = TextTertiary
            )
        }
        Icon(
            imageVector = Icons.AutoMirrored.Filled.Sort,
            contentDescription = null,
            tint = TextTertiary,
            modifier = Modifier.size(16.dp)
        )
    }
}

/** 词汇统计卡片:等宽,图标 + 标签 + 大数字 */
@Composable
private fun VocabStatCard(
    modifier: Modifier = Modifier,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    value: String,
    color: Color
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(12.dp))
            .background(color.copy(alpha = 0.10f))
            .padding(16.dp),
        horizontalAlignment = Alignment.Start
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(imageVector = icon, contentDescription = null, tint = color, modifier = Modifier.size(18.dp))
            Spacer(modifier = Modifier.width(6.dp))
            Text(label, style = MaterialTheme.typography.labelSmall, color = color)
        }
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = value,
            style = MaterialTheme.typography.headlineMedium.copy(fontWeight = FontWeight.Bold),
            color = TextPrimary
        )
    }
}

/** 总览统计项：图标+标签+数值，无背景 */
@Composable
private fun OverviewStatItem(
    modifier: Modifier = Modifier,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    value: String,
    color: Color
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(10.dp))
            .background(color.copy(alpha = 0.08f))
            .padding(12.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Icon(imageVector = icon, contentDescription = null, tint = color, modifier = Modifier.size(20.dp))
        Spacer(modifier = Modifier.height(6.dp))
        Text(
            text = value,
            style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold),
            color = color
        )
        Text(label, style = MaterialTheme.typography.labelSmall, color = TextTertiary)
    }
}
