package com.aveline.ai.mobile.presentation.components

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput

/** 聊天富文本横向组件与页面级导航手势之间的显式仲裁状态。 */
@Stable
class HorizontalContentGestureState {
    var isActive: Boolean = false
        internal set
}

/** 非聊天页面默认为 null，因此笔记页复用 Markdown 渲染器时不会产生额外状态。 */
val LocalHorizontalContentGestureState = staticCompositionLocalOf<HorizontalContentGestureState?> {
    null
}

/**
 * 声明当前区域拥有从按下到抬起的整次横向浏览手势。
 *
 * 页面级手势只读取这个显式状态，不再依赖 Compose 的通用 consumed 标志；后者也会被
 * clickable、LazyColumn 等普通组件使用，无法准确区分表格滚动。
 */
@Composable
fun Modifier.claimHorizontalContentGesture(): Modifier {
    val gestureState = LocalHorizontalContentGestureState.current ?: return this
    return pointerInput(gestureState) {
        awaitEachGesture {
            awaitFirstDown(requireUnconsumed = false)
            gestureState.isActive = true
            try {
                do {
                    val event = awaitPointerEvent()
                } while (event.changes.any { it.pressed })
            } finally {
                gestureState.isActive = false
            }
        }
    }
}
