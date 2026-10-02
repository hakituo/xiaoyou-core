package com.aveline.ai.mobile.presentation.life

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Restaurant
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.data.samsung.NutritionEntry
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.health.DailyDataUiState
import com.aveline.ai.mobile.presentation.theme.OverlayLight
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * Life - 餐食 Tab。
 *
 * 纯 Samsung Health 数据展示: 今日逐条饮食记录(食物名/餐次/热量/时间) + 营养摄入总量。
 * 不再有手动记录餐食, 所有饮食数据来自 Samsung Health。
 *
 * @param uiState 日常生活数据状态
 */
@Composable
fun LifeMealTab(
    uiState: DailyDataUiState
) {
    // 今日饮食记录(数据来源: Samsung Health 营养数据逐条, 含食物名/餐次/热量)
    SectionCard(
        title = "今日饮食",
        icon = Icons.Default.Restaurant,
        subtitle = "来自 Samsung Health · ${uiState.nutritionEntries.size} 项"
    ) {
        if (uiState.nutritionEntries.isEmpty()) {
            Text(
                text = "今日暂无饮食记录",
                style = MaterialTheme.typography.bodySmall,
                color = TextTertiary
            )
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                uiState.nutritionEntries.forEach { entry ->
                    NutritionItem(entry = entry)
                }
            }
        }
    }

    // 营养摄入(数据来源: Samsung Health 总量)
    val hasNutrition = uiState.nutritionCalories != null || uiState.nutritionProtein != null ||
        uiState.nutritionCarbs != null || uiState.nutritionFat != null ||
        uiState.nutritionCholesterol != null || uiState.nutritionCalcium != null
    if (hasNutrition) {
        SectionCard(
            title = "营养摄入",
            subtitle = "来自 Samsung Health"
        ) {
            // 营养指标用两列网格呈现, 紧凑美观, 避免 15 行 MetricRow 过长
            NutritionGrid(
                pairs = listOfNotNull(
                    uiState.nutritionCalories?.let { "摄入热量" to String.format("%.0f kcal", it) },
                    uiState.nutritionProtein?.let { "蛋白质" to String.format("%.1f g", it) },
                    uiState.nutritionCarbs?.let { "碳水" to String.format("%.1f g", it) },
                    uiState.nutritionFat?.let { "脂肪" to String.format("%.1f g", it) },
                    uiState.nutritionSaturatedFat?.let { "饱和脂肪" to String.format("%.1f g", it) },
                    uiState.nutritionTransFat?.let { "反式脂肪" to String.format("%.1f g", it) },
                    uiState.nutritionDietaryFiber?.let { "膳食纤维" to String.format("%.1f g", it) },
                    uiState.nutritionSugar?.let { "糖" to String.format("%.1f g", it) },
                    uiState.nutritionCholesterol?.let { "胆固醇" to String.format("%.0f mg", it) },
                    uiState.nutritionSodium?.let { "钠" to String.format("%.0f mg", it) },
                    uiState.nutritionPotassium?.let { "钾" to String.format("%.0f mg", it) },
                    uiState.nutritionVitaminA?.let { "维A" to String.format("%.0f μg", it) },
                    uiState.nutritionVitaminC?.let { "维C" to String.format("%.1f mg", it) },
                    uiState.nutritionCalcium?.let { "钙" to String.format("%.0f mg", it) },
                    uiState.nutritionIron?.let { "铁" to String.format("%.1f mg", it) }
                )
            )
        }
    }
}

/**
 * 营养指标两列网格(标签 + 数值卡片), 紧凑美观。
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun NutritionGrid(pairs: List<Pair<String, String>>) {
    if (pairs.isEmpty()) return
    // 两列网格: 每格宽度 = (屏宽 - SectionCard 左右内边距 - 列间距) / 2
    val cellWidth = ((androidx.compose.ui.platform.LocalConfiguration.current.screenWidthDp.dp - 48.dp) / 2)
        .coerceAtLeast(0.dp)
    FlowRow(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        pairs.forEach { (label, value) ->
            NutriCell(
                label = label,
                value = value,
                modifier = Modifier.width(cellWidth)
            )
        }
    }
}

/**
 * 单个营养素小卡片(标签在上, 数值在下)。
 */
@Composable
private fun NutriCell(
    label: String,
    value: String,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .background(OverlayLight, RoundedCornerShape(12.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp)
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = TextTertiary
        )
        Spacer(modifier = Modifier.height(3.dp))
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold,
            color = TextPrimary
        )
    }
}

/**
 * 餐次类型枚举名转中文显示。
 */
private fun formatMealType(mealType: String?): String {
    if (mealType.isNullOrBlank()) return "饮食"
    return when (mealType.uppercase()) {
        "BREAKFAST" -> "早餐"
        "LUNCH" -> "午餐"
        "DINNER" -> "晚餐"
        "SNACK" -> "零食"
        else -> mealType.lowercase().replaceFirstChar { it.uppercase() }
    }
}

/**
 * 数值格式化: 去掉多余的 0, 保留最多 1 位小数, 如 520 -> "520", 6.12 -> "6.1"。
 */
private fun formatVal(value: Float, unit: String): String {
    val rounded = String.format("%.1f", value)
    val trimmed = if (rounded.endsWith(".0")) rounded.dropLast(2) else rounded
    return "$trimmed$unit"
}

/**
 * Samsung Health 饮食记录条目。
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun NutritionItem(entry: NutritionEntry) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(OverlayLight, RoundedCornerShape(14.dp))
            .padding(14.dp)
    ) {
        Text(
            text = formatMealType(entry.mealType),
            color = TextPrimary,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold
        )
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = entry.title?.takeIf { it.isNotBlank() } ?: "未命名食物",
            color = TextSecondary,
            style = MaterialTheme.typography.bodySmall
        )
        Spacer(modifier = Modifier.height(6.dp))
        // 热量 + 宏观营养素摘要
        val macros = buildString {
            entry.calories?.let { append(String.format("%.0f kcal", it)) }
            entry.protein?.let { if (isNotEmpty()) append(" · "); append(String.format("蛋白%.1fg", it)) }
            entry.carbs?.let { if (isNotEmpty()) append(" · "); append(String.format("碳水%.1fg", it)) }
            entry.fat?.let { if (isNotEmpty()) append(" · "); append(String.format("脂肪%.1fg", it)) }
        }
        if (macros.isNotEmpty()) {
            Text(
                text = macros,
                color = TextTertiary,
                style = MaterialTheme.typography.labelSmall
            )
        }
        // 完整微量营养素(膳食纤维/糖/胆固醇/钠/钾/维A/维C/钙/铁), 用 FlowRow 小标签展示
        val micros = buildList {
            entry.dietaryFiber?.let { add("纤维 ${formatVal(it, "g")}") }
            entry.sugar?.let { add("糖 ${formatVal(it, "g")}") }
            entry.cholesterol?.let { add("胆固醇 ${formatVal(it, "mg")}") }
            entry.sodium?.let { add("钠 ${formatVal(it, "mg")}") }
            entry.potassium?.let { add("钾 ${formatVal(it, "mg")}") }
            entry.vitaminA?.let { add("维A ${formatVal(it, "μg")}") }
            entry.vitaminC?.let { add("维C ${formatVal(it, "mg")}") }
            entry.calcium?.let { add("钙 ${formatVal(it, "mg")}") }
            entry.iron?.let { add("铁 ${formatVal(it, "mg")}") }
        }
        if (micros.isNotEmpty()) {
            FlowRow(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                micros.forEach { chip ->
                    Text(
                        text = chip,
                        modifier = Modifier
                            .background(OverlayLight, RoundedCornerShape(8.dp))
                            .padding(horizontal = 8.dp, vertical = 3.dp),
                        color = TextTertiary,
                        style = MaterialTheme.typography.labelSmall
                    )
                }
            }
        }
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = runCatching {
                java.text.SimpleDateFormat("HH:mm", java.util.Locale.getDefault())
                    .format(java.util.Date(entry.startTime.toEpochMilli()))
            }.getOrDefault("--:--"),
            color = TextTertiary,
            style = MaterialTheme.typography.labelSmall
        )
    }
}
