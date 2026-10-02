package com.aveline.ai.mobile.presentation.components

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.CardBackground
import com.aveline.ai.mobile.presentation.theme.CardBorder
import com.aveline.ai.mobile.presentation.theme.CardRadius
import com.aveline.ai.mobile.presentation.theme.TextMuted
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 统一分区卡片组件。
 *
 * 所有 Screen 的分区卡片统一使用此组件,确保样式一致:
 * - 圆角 [CardRadius] (16.dp)
 * - 背景 [CardBackground] (0x33000000)
 * - 边框 1.dp [CardBorder] (0x14FFFFFF)
 * - 内容 padding 16.dp
 * - 标题: labelSmall + Bold + letterSpacing=2.sp + [TextTertiary]
 * - 标题底部间距 12.dp
 *
 * 支持:图标、副标题、可折叠。
 *
 * @param title 卡片标题(空字符串则不显示标题行)
 * @param icon 标题前图标(可选)
 * @param subtitle 标题下方副标题(可选)
 * @param collapsible 是否可折叠(点击标题切换)
 * @param defaultExpanded 默认是否展开(仅 collapsible=true 时生效)
 * @param trailingContent 标题行右侧内容(可选,如 Switch/按钮)
 * @param content 卡片内容
 */
@Composable
fun SectionCard(
    title: String,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    subtitle: String? = null,
    collapsible: Boolean = false,
    defaultExpanded: Boolean = true,
    trailingContent: @Composable (RowScope.() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit
) {
    var expanded by remember { mutableStateOf(defaultExpanded) }

    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(CardRadius),
        colors = CardDefaults.cardColors(containerColor = CardBackground),
        border = BorderStroke(1.dp, CardBorder)
    ) {
        Column(
            modifier = Modifier
                .padding(16.dp)
                .animateContentSize()
        ) {
            // 标题行(仅当 title 非空时显示)
            if (title.isNotBlank()) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(bottom = 12.dp)
                        .then(
                            if (collapsible) {
                                Modifier.clickable(
                                    interactionSource = remember { MutableInteractionSource() },
                                    indication = null,
                                    onClick = { expanded = !expanded }
                                )
                            } else {
                                Modifier
                            }
                        ),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    // 标题图标:未传入时保留 16dp 占位,保证所有卡片标题左对齐一致
                    if (icon != null) {
                        Icon(
                            imageVector = icon,
                            contentDescription = null,
                            tint = TextTertiary,
                            modifier = Modifier.size(16.dp)
                        )
                    } else {
                        Spacer(modifier = Modifier.size(16.dp))
                    }
                    Spacer(modifier = Modifier.width(8.dp))

                    // 标题 + 副标题
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = title,
                            style = MaterialTheme.typography.labelSmall.copy(
                                fontWeight = FontWeight.Bold,
                                letterSpacing = 2.sp
                            ),
                            color = TextTertiary
                        )
                        if (!subtitle.isNullOrBlank()) {
                            Text(
                                text = subtitle,
                                style = MaterialTheme.typography.bodySmall,
                                color = TextMuted,
                                modifier = Modifier.padding(top = 2.dp)
                            )
                        }
                    }

                    // 折叠/展开箭头
                    if (collapsible) {
                        Icon(
                            imageVector = if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                            contentDescription = if (expanded) "折叠" else "展开",
                            tint = TextTertiary,
                            modifier = Modifier.size(20.dp)
                        )
                    }

                    // 标题行右侧自定义内容
                    trailingContent?.invoke(this)
                }
            }

            // 内容区域(可折叠时直接条件渲染,避免 AnimatedVisibility 包装导致子组件位置异常)
            if (!collapsible || expanded) {
                content()
            }
        }
    }
}

/**
 * 统一指标行组件。
 *
 * 用于在卡片内展示"标签: 值"形式的数据行,确保文字对齐一致。
 *
 * @param label 标签(左侧)
 * @param value 值(右侧)
 * @param valueColor 值的颜色(默认 TextPrimary)
 */
@Composable
fun MetricRow(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    valueColor: androidx.compose.ui.graphics.Color = com.aveline.ai.mobile.presentation.theme.TextPrimary
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = TextTertiary
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            color = valueColor
        )
    }
}
