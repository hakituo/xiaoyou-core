package com.aveline.ai.mobile.presentation.study

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.LocalFireDepartment
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 词汇复习会话(全屏覆盖层)。
 *
 * Anki 风格翻卡:点击卡片显示答案,然后选择 Again/Hard/Good/Easy 评分。
 *
 * @param uiState 词汇复习域 UI 状态
 * @param onSetShowAnswer 设置是否显示答案
 * @param onSubmitReview 提交评分("1"=Again "2"=Hard "3"=Good "4"=Easy)
 * @param onSetIsReviewMode 设置复习模式
 */
@Composable
fun VocabReviewSession(
    uiState: VocabUiState,
    onSetShowAnswer: (Boolean) -> Unit,
    onSubmitReview: (String) -> Unit,
    onSetIsReviewMode: (Boolean) -> Unit
) {
    val currentWord = uiState.learnWords.getOrNull(uiState.currentCardIndex) ?: run {
        // 无词汇时显示空状态
        Box(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .padding(24.dp),
            contentAlignment = Alignment.Center
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    text = if (uiState.isNewWordsMode) "当前词书没有新词了" else "没有待复习的词汇",
                    style = MaterialTheme.typography.titleMedium,
                    color = TextSecondary
                )
                Spacer(modifier = Modifier.height(16.dp))
                Button(
                    onClick = { onSetIsReviewMode(false) },
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0x1A000000))
                ) {
                    Text("返回")
                }
            }
        }
        return
    }

    val progress by animateFloatAsState(
        targetValue = (uiState.currentCardIndex + 1f) / uiState.learnWords.size,
        label = "review_progress"
    )
    var showExtendedTranslations by remember(currentWord.word) { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .padding(16.dp)
    ) {
        // 进度条
        LinearProgressIndicator(
            progress = { progress },
            modifier = Modifier
                .fillMaxWidth()
                .height(4.dp)
                .clip(RoundedCornerShape(2.dp)),
            color = EmotionGreen,
            trackColor = Color(0x1AFFFFFF)
        )
        Spacer(modifier = Modifier.height(16.dp))

        // 顶部信息栏:进度 + 连续正确 + 关闭
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "${uiState.currentCardIndex + 1} / ${uiState.learnWords.size}",
                style = MaterialTheme.typography.labelSmall,
                color = TextTertiary
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.LocalFireDepartment, contentDescription = null, tint = Color(0xFFF59E0B), modifier = Modifier.size(16.dp))
                Spacer(modifier = Modifier.width(4.dp))
                Text(
                    text = uiState.sessionStats?.streak?.toString() ?: "0",
                    style = MaterialTheme.typography.labelSmall,
                    color = Color(0xFFF59E0B),
                    fontWeight = FontWeight.Bold
                )
                Spacer(modifier = Modifier.width(16.dp))
                IconButton(onClick = { onSetIsReviewMode(false) }) {
                    Icon(Icons.Default.Close, contentDescription = "关闭", tint = TextTertiary)
                }
            }
        }
        Spacer(modifier = Modifier.height(16.dp))

        // 翻卡区域
        Box(modifier = Modifier.weight(1f).fillMaxWidth()) {
            if (!uiState.showAnswer) {
                // 问题面:点击翻卡
                Card(
                    modifier = Modifier.fillMaxSize().clickable { onSetShowAnswer(true) },
                    colors = CardDefaults.cardColors(containerColor = Color(0x14000000)),
                    shape = RoundedCornerShape(16.dp),
                    border = BorderStroke(1.dp, Color(0x1AFFFFFF))
                ) {
                    Column(
                        modifier = Modifier.fillMaxSize().padding(24.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.Center
                    ) {
                        Box(
                            modifier = Modifier
                                .clip(RoundedCornerShape(4.dp))
                                .background(if (currentWord.status == "new") Color(0x1A10B981) else Color(0x1AF59E0B))
                                .padding(horizontal = 8.dp, vertical = 4.dp)
                        ) {
                            Text(
                                text = if (currentWord.status == "new") "新词" else "复习",
                                style = MaterialTheme.typography.labelSmall,
                                color = if (currentWord.status == "new") EmotionGreen else Color(0xFFF59E0B),
                                fontWeight = FontWeight.Bold
                            )
                        }
                        Spacer(modifier = Modifier.height(24.dp))
                        Text(
                            text = currentWord.word,
                            style = MaterialTheme.typography.displayMedium.copy(fontWeight = FontWeight.Bold),
                            color = TextPrimary
                        )
                        // 音标展示
                        if (!currentWord.us.isNullOrBlank() || !currentWord.uk.isNullOrBlank()) {
                            Spacer(modifier = Modifier.height(12.dp))
                            Row(
                                horizontalArrangement = Arrangement.spacedBy(16.dp)
                            ) {
                                currentWord.us?.takeIf { it.isNotBlank() }?.let {
                                    Text(
                                        text = "美 /$it/",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = TextTertiary
                                    )
                                }
                                currentWord.uk?.takeIf { it.isNotBlank() }?.let {
                                    Text(
                                        text = "英 /$it/",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = TextTertiary
                                    )
                                }
                            }
                        }
                        Spacer(modifier = Modifier.height(16.dp))
                        Text("点击翻卡", style = MaterialTheme.typography.bodySmall, color = TextTertiary)
                    }
                }
            } else {
                // 答案面:显示翻译、短语、例句
                Card(
                    modifier = Modifier.fillMaxSize(),
                    colors = CardDefaults.cardColors(containerColor = Color(0x14000000)),
                    shape = RoundedCornerShape(16.dp),
                    border = BorderStroke(1.dp, Color(0x1AFFFFFF))
                ) {
                    // 内容可能很长(多义词+短语+例句),用 verticalScroll 让卡片内部可滚动,
                    // 避免溢出版面导致短语/例句看不到
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .verticalScroll(rememberScrollState())
                            .padding(24.dp)
                    ) {
                        Text(
                            text = currentWord.word,
                            style = MaterialTheme.typography.headlineMedium.copy(fontWeight = FontWeight.Bold),
                            color = TextPrimary
                        )
                        // 音标展示
                        if (!currentWord.us.isNullOrBlank() || !currentWord.uk.isNullOrBlank()) {
                            Spacer(modifier = Modifier.height(8.dp))
                            Row(
                                horizontalArrangement = Arrangement.spacedBy(16.dp)
                            ) {
                                currentWord.us?.takeIf { it.isNotBlank() }?.let {
                                    Text(
                                        text = "美 /$it/",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = TextTertiary
                                    )
                                }
                                currentWord.uk?.takeIf { it.isNotBlank() }?.let {
                                    Text(
                                        text = "英 /$it/",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = TextTertiary
                                    )
                                }
                            }
                        }
                        Spacer(modifier = Modifier.height(20.dp))
                        // 释义
                        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            currentWord.translations.forEach { translation ->
                                TranslationRow(translation = translation)
                            }
                        }

                        // 专业义、旧义和人工覆盖词的来源释义默认折叠，避免压过常用义。
                        val extendedTranslations = currentWord.extendedTranslations
                        if (extendedTranslations.isNotEmpty()) {
                            Spacer(modifier = Modifier.height(12.dp))
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(8.dp))
                                    .clickable {
                                        showExtendedTranslations = !showExtendedTranslations
                                    }
                                    .background(Color(0x05FFFFFF))
                                    .padding(12.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(
                                    text = "更多/专业释义（${extendedTranslations.size}）",
                                    style = MaterialTheme.typography.labelMedium,
                                    color = TextSecondary,
                                    modifier = Modifier.weight(1f)
                                )
                                Text(
                                    text = if (showExtendedTranslations) "收起" else "展开",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = EmotionGreen
                                )
                            }
                            if (showExtendedTranslations) {
                                Spacer(modifier = Modifier.height(8.dp))
                                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                    extendedTranslations.forEach { translation ->
                                        TranslationRow(
                                            translation = translation,
                                            isExtended = true
                                        )
                                    }
                                }
                            }
                        }

                        // 短语区
                        val phrases = currentWord.phrases
                        if (phrases?.isNotEmpty() == true) {
                            Spacer(modifier = Modifier.height(20.dp))
                            Text(
                                text = "短语",
                                style = MaterialTheme.typography.labelMedium,
                                color = TextSecondary
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                phrases.take(5).forEach { p ->
                                    Column(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .clip(RoundedCornerShape(8.dp))
                                            .background(Color(0x08FFFFFF))
                                            .padding(12.dp)
                                    ) {
                                        Text(
                                            text = p.phrase,
                                            style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold),
                                            color = TextPrimary
                                        )
                                        if (p.translation.isNotBlank()) {
                                            Spacer(modifier = Modifier.height(4.dp))
                                            Text(
                                                text = p.translation,
                                                style = MaterialTheme.typography.bodySmall,
                                                color = TextSecondary
                                            )
                                        }
                                    }
                                }
                            }
                        }

                        // 例句区
                        val sentences = currentWord.sentences
                        if (sentences?.isNotEmpty() == true) {
                            Spacer(modifier = Modifier.height(20.dp))
                            Text(
                                text = "例句",
                                style = MaterialTheme.typography.labelMedium,
                                color = TextSecondary
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                                sentences.take(3).forEach { s ->
                                    Column(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .clip(RoundedCornerShape(8.dp))
                                            .background(Color(0x08FFFFFF))
                                            .padding(12.dp)
                                    ) {
                                        Text(
                                            text = s.sentence,
                                            style = MaterialTheme.typography.bodyMedium,
                                            color = TextPrimary
                                        )
                                        if (s.translation.isNotBlank()) {
                                            Spacer(modifier = Modifier.height(4.dp))
                                            Text(
                                                text = s.translation,
                                                style = MaterialTheme.typography.bodySmall,
                                                color = TextSecondary
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        // 底部操作区:评分按钮或显示答案按钮
        Box(modifier = Modifier.fillMaxWidth().height(72.dp)) {
            if (uiState.showAnswer) {
                Row(
                    modifier = Modifier.fillMaxSize(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    ReviewButton("Again", "1m", Color(0xFFEF4444), Modifier.weight(1f)) { onSubmitReview("1") }
                    ReviewButton("Hard", "10m", Color(0xFFF97316), Modifier.weight(1f)) { onSubmitReview("2") }
                    ReviewButton("Good", "1d", Color(0xFF3B82F6), Modifier.weight(1f)) { onSubmitReview("3") }
                    ReviewButton("Easy", "3d", EmotionGreen, Modifier.weight(1f)) { onSubmitReview("4") }
                }
            } else {
                Button(
                    onClick = { onSetShowAnswer(true) },
                    modifier = Modifier.fillMaxSize(),
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0x1A000000))
                ) {
                    Text("显示答案")
                }
            }
        }
    }
}

/** 评分按钮(Again/Hard/Good/Easy) */
@Composable
private fun ReviewButton(
    label: String,
    subLabel: String,
    color: Color,
    modifier: Modifier = Modifier,
    onClick: () -> Unit
) {
    Card(
        onClick = onClick,
        modifier = modifier.fillMaxSize(),
        colors = CardDefaults.cardColors(containerColor = color.copy(alpha = 0.1f)),
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(1.dp, color.copy(alpha = 0.3f))
    ) {
        Column(
            modifier = Modifier.fillMaxSize(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Text(label, style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold), color = color)
            Text(subLabel, style = MaterialTheme.typography.labelSmall, color = color.copy(alpha = 0.6f))
        }
    }
}

/** 单条释义展示；只有后端明确标记 primary 的释义才加粗。 */
@Composable
private fun TranslationRow(
    translation: WordTranslation,
    isExtended: Boolean = false
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(Color(0x05FFFFFF))
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        val (type, trans) = parseWordType(translation)
        if (type.isNotBlank()) {
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(4.dp))
                    .background(EmotionGreen.copy(alpha = 0.15f))
                    .padding(horizontal = 8.dp, vertical = 4.dp)
            ) {
                Text(
                    text = type.uppercase(),
                    style = MaterialTheme.typography.labelMedium,
                    color = EmotionGreen,
                    fontWeight = FontWeight.Bold
                )
            }
            Spacer(modifier = Modifier.width(10.dp))
        }
        Column(modifier = Modifier.weight(1f)) {
            if (isExtended && translation.domains.isNotEmpty()) {
                Text(
                    text = translation.domains.joinToString(" · ") { "[$it]" },
                    style = MaterialTheme.typography.labelSmall,
                    color = TextTertiary
                )
                Spacer(modifier = Modifier.height(2.dp))
            }
            Text(
                text = trans,
                style = MaterialTheme.typography.bodyMedium.copy(
                    fontWeight = if (translation.primary) {
                        FontWeight.Bold
                    } else {
                        FontWeight.Normal
                    }
                ),
                color = if (isExtended) TextSecondary else TextPrimary
            )
        }
    }
}

/**
 * 从 [WordTranslation] 解析词性标签与纯净释义。
 *
 * 词库（CET4-顺序.json）里形容词等词性的 `type` 字段常为空字符串，
 * 词性缩写（a./adj./n./v. 等）被塞进 `translation` 前缀。
 * 本函数在 `type` 为空时从 `translation` 前缀拆出词性，保证绿框正常渲染。
 *
 * @return (词性, 去掉前缀的释义)
 */
private fun parseWordType(translation: WordTranslation): Pair<String, String> {
    if (translation.type.isNotBlank()) {
        return translation.type to translation.translation
    }
    // 匹配 translation 前缀的词性缩写
    val regex = Regex("^(a|adj|n|v|vt|vi|adv|prep|conj|int|art|num|pron|abbr)\\.\\s*")
    val match = regex.find(translation.translation) ?: return "" to translation.translation
    val type = match.groupValues[1]
    val rest = translation.translation.substring(match.range.last).trim()
    return type to rest
}

/**
 * 会话总结(全屏覆盖层)。
 *
 * 复习完成后展示统计信息:正确率、连续正确数，以及本轮逐词「会/不会」清单。
 *
 * @param sessionStats 会话统计
 * @param reviewResults 本轮逐词复习结果（会/不会）
 * @param onContinue 继续学习回调
 */
@Composable
fun VocabSessionSummary(
    sessionStats: SessionStats?,
    reviewResults: List<ReviewResultItem> = emptyList(),
    isNewWordsMode: Boolean = false,
    onContinue: () -> Unit
) {
    val knownCount = reviewResults.count { it.known }
    val unknownCount = reviewResults.size - knownCount
    Box(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .padding(24.dp)
    ) {
        Column(
            modifier = Modifier.fillMaxSize(),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            // 完成图标
            Box(
                modifier = Modifier
                    .size(96.dp)
                    .clip(RoundedCornerShape(48.dp))
                    .background(Color(0x2010B981)),
                contentAlignment = Alignment.Center
            ) {
                Icon(Icons.Default.CheckCircle, contentDescription = null, tint = EmotionGreen, modifier = Modifier.size(48.dp))
            }
            Spacer(modifier = Modifier.height(24.dp))
            Text(
                text = if (isNewWordsMode) "背新词完成!" else "复习完成!",
                style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold),
                color = TextPrimary
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = if (isNewWordsMode) {
                    "本次学习了 ${reviewResults.size} 个新词"
                } else {
                    "本次复习了 ${reviewResults.size} 个词汇"
                },
                style = MaterialTheme.typography.bodyMedium,
                color = TextSecondary
            )
            Spacer(modifier = Modifier.height(24.dp))

            // 统计卡片:正确率 + 连续正确
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                Card(
                    modifier = Modifier.weight(1f),
                    colors = CardDefaults.cardColors(containerColor = Color(0x14000000)),
                    shape = RoundedCornerShape(12.dp)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text("正确率", style = MaterialTheme.typography.labelSmall, color = TextTertiary)
                        val uniqueTotal = reviewResults.size
                        val uniqueKnown = reviewResults.count { it.known }
                        val accuracyPct = if (uniqueTotal > 0) (uniqueKnown * 100 / uniqueTotal) else 0
                        Text(
                            text = "$accuracyPct%",
                            style = MaterialTheme.typography.headlineSmall.copy(fontWeight = FontWeight.Bold),
                            color = TextPrimary
                        )
                    }
                }
                Card(
                    modifier = Modifier.weight(1f),
                    colors = CardDefaults.cardColors(containerColor = Color(0x14000000)),
                    shape = RoundedCornerShape(12.dp)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text("连续正确", style = MaterialTheme.typography.labelSmall, color = TextTertiary)
                        Text(
                            text = sessionStats?.streak?.toString() ?: "0",
                            style = MaterialTheme.typography.headlineSmall.copy(fontWeight = FontWeight.Bold),
                            color = Color(0xFFF59E0B)
                        )
                    }
                }
            }

            // 会 / 不会 概览
            Spacer(modifier = Modifier.height(16.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                Card(
                    modifier = Modifier.weight(1f),
                    colors = CardDefaults.cardColors(containerColor = Color(0x1010B981)),
                    shape = RoundedCornerShape(12.dp)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text("会", style = MaterialTheme.typography.labelSmall, color = TextTertiary)
                        Text(
                            text = knownCount.toString(),
                            style = MaterialTheme.typography.headlineSmall.copy(fontWeight = FontWeight.Bold),
                            color = EmotionGreen
                        )
                    }
                }
                Card(
                    modifier = Modifier.weight(1f),
                    colors = CardDefaults.cardColors(containerColor = Color(0x10EF4444)),
                    shape = RoundedCornerShape(12.dp)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text("不会", style = MaterialTheme.typography.labelSmall, color = TextTertiary)
                        Text(
                            text = unknownCount.toString(),
                            style = MaterialTheme.typography.headlineSmall.copy(fontWeight = FontWeight.Bold),
                            color = Color(0xFFEF4444)
                        )
                    }
                }
            }

            // 逐词会/不会清单（可滚动）
            if (reviewResults.isNotEmpty()) {
                Spacer(modifier = Modifier.height(16.dp))
                Text(
                    text = "本轮明细",
                    style = MaterialTheme.typography.labelMedium,
                    color = TextSecondary,
                    modifier = Modifier.align(Alignment.Start)
                )
                Spacer(modifier = Modifier.height(8.dp))
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f, fill = false)
                        .verticalScroll(rememberScrollState())
                        .clip(RoundedCornerShape(12.dp))
                ) {
                    reviewResults.forEach { item ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 8.dp, horizontal = 4.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(
                                imageVector = if (item.known) Icons.Default.CheckCircle else Icons.Default.Close,
                                contentDescription = null,
                                tint = if (item.known) EmotionGreen else Color(0xFFEF4444),
                                modifier = Modifier.size(18.dp)
                            )
                            Spacer(modifier = Modifier.width(10.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = item.word,
                                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold),
                                    color = TextPrimary
                                )
                                if (item.translation.isNotBlank()) {
                                    Text(
                                        text = item.translation,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = TextSecondary,
                                        maxLines = 1
                                    )
                                }
                            }
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(16.dp))
            Button(
                onClick = onContinue,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = Color(0x1A000000))
            ) {
                Text("继续学习")
            }
        }
    }
}
