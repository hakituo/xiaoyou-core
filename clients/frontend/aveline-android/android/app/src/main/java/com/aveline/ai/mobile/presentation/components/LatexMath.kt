package com.aveline.ai.mobile.presentation.components

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import com.agog.mathdisplay.MTMathView

/**
 * 使用原生 Canvas View 渲染 LaTeX 数学公式。
 *
 * AndroidMath 在本地解析公式，不依赖 WebView、JavaScript 或运行时网络；解析失败时由
 * [MTMathView] 直接显示错误信息，避免整个 Markdown 消息渲染失败。
 */
@Composable
fun LatexMath(
    formula: String,
    displayMode: Boolean,
    modifier: Modifier = Modifier
) {
    val density = LocalDensity.current
    val textColor = MaterialTheme.colorScheme.onSurface.toArgb()
    val fontSizePx = with(density) {
        (if (displayMode) 20.sp else 16.sp).toPx()
    }

    AndroidView(
        modifier = modifier,
        factory = { context ->
            MTMathView(context).apply {
                displayErrorInline = true
                labelMode = if (displayMode) {
                    MTMathView.MTMathViewMode.KMTMathViewModeDisplay
                } else {
                    MTMathView.MTMathViewMode.KMTMathViewModeText
                }
                textAlignment = MTMathView.MTTextAlignment.KMTTextAlignmentLeft
            }
        },
        update = { view ->
            view.fontSize = fontSizePx
            view.textColor = textColor
            view.labelMode = if (displayMode) {
                MTMathView.MTMathViewMode.KMTMathViewModeDisplay
            } else {
                MTMathView.MTMathViewMode.KMTMathViewModeText
            }
            if (view.latex != formula) {
                view.latex = formula
            }
        }
    )
}
