package com.aveline.ai.mobile.presentation.components

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import com.aveline.ai.mobile.presentation.theme.SelectionContent
import com.aveline.ai.mobile.presentation.theme.TextSecondary

/**
 * Route 内统一的纯文字 Tab 栏。
 *
 * 不绘制底色、边框或下划线，只通过文字亮度与字重区分选中态。
 * 单行约束避免 Study 等标签在窄屏下被挤成竖排。
 */
@Composable
fun AvelineTabRow(
    titles: List<String>,
    selectedTabIndex: Int,
    onTabSelected: (Int) -> Unit,
    modifier: Modifier = Modifier
) {
    TabRow(
        selectedTabIndex = selectedTabIndex,
        modifier = modifier,
        containerColor = Color.Transparent,
        contentColor = SelectionContent,
        indicator = {},
        divider = {}
    ) {
        titles.forEachIndexed { index, title ->
            val selected = selectedTabIndex == index
            Tab(
                selected = selected,
                onClick = { onTabSelected(index) },
                selectedContentColor = SelectionContent,
                unselectedContentColor = TextSecondary.copy(alpha = 0.62f),
                text = {
                    Text(
                        text = title,
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                        maxLines = 1,
                        softWrap = false
                    )
                }
            )
        }
    }
}
