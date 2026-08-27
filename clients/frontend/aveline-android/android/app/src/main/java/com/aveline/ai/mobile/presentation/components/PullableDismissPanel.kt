@file:OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)

package com.aveline.ai.mobile.presentation.components

import androidx.compose.foundation.gestures.AnchoredDraggableDefaults
import androidx.compose.foundation.gestures.AnchoredDraggableState
import androidx.compose.foundation.gestures.DraggableAnchors
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.anchoredDraggable
import androidx.compose.foundation.gestures.animateTo
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Velocity
import androidx.compose.ui.unit.dp
import kotlin.math.abs

internal enum class DismissPanelValue {
    Visible,
    Dismissed
}

@Stable
class PullableDismissPanelState internal constructor(
    private val dragState: AnchoredDraggableState<DismissPanelValue>
) {
    internal val anchoredState: AnchoredDraggableState<DismissPanelValue>
        get() = dragState

    suspend fun show() {
        dragState.animateTo(DismissPanelValue.Visible)
    }

    suspend fun dismiss() {
        dragState.animateTo(DismissPanelValue.Dismissed)
    }

    /** 把聊天页的左滑位移交给与详情页退出手势相同的锚点状态。 */
    fun dispatchOpeningDelta(deltaX: Float): Float {
        return dragState.dispatchRawDelta(deltaX)
    }

    /**
     * 打开手势松开后的吸附判定。
     *
     * 返回 true 表示停在详情页，false 表示回到屏幕右侧隐藏位置。
     */
    suspend fun settleOpeningDrag(
        releaseVelocityX: Float,
        panelWidthPx: Float,
        velocityThresholdPx: Float
    ): Boolean {
        val offset = dragState.offset
        if (offset.isNaN() || panelWidthPx <= 0f) return false
        val revealProgress = ((panelWidthPx - offset) / panelWidthPx).coerceIn(0f, 1f)
        val target = when {
            releaseVelocityX <= -velocityThresholdPx -> DismissPanelValue.Visible
            releaseVelocityX >= velocityThresholdPx -> DismissPanelValue.Dismissed
            revealProgress >= 0.12f -> DismissPanelValue.Visible
            else -> DismissPanelValue.Dismissed
        }
        dragState.animateTo(target)
        return target == DismissPanelValue.Visible
    }
}

@Composable
fun rememberPullableDismissPanelState(): PullableDismissPanelState {
    return remember {
        PullableDismissPanelState(
            AnchoredDraggableState(initialValue = DismissPanelValue.Dismissed)
        )
    }
}

/**
 * 从右侧退出的全屏跟手面板。
 *
 * 直接右滑由 anchoredDraggable 驱动；内部 HorizontalPager 位于第一页时，未消费的
 * 右滑通过 NestedScroll 接力到同一状态。面板整体跟随手指，松手后再吸附或退出。
 */
@Composable
fun PullableDismissPanel(
    state: PullableDismissPanelState,
    onDismissed: () -> Unit,
    gesturesEnabled: Boolean = true,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit
) {
    BoxWithConstraints(modifier = modifier.fillMaxSize()) {
        val density = LocalDensity.current
        val panelWidthPx = with(density) { maxWidth.toPx() }
        val velocityThresholdPx = with(density) { 125.dp.toPx() }
        val hasReachedVisible = remember { mutableStateOf(false) }
        val anchors = remember(panelWidthPx) {
            DraggableAnchors {
                DismissPanelValue.Visible at 0f
                DismissPanelValue.Dismissed at panelWidthPx
            }
        }
        SideEffect {
            state.anchoredState.updateAnchors(anchors)
        }

        LaunchedEffect(state.anchoredState.settledValue) {
            when (state.anchoredState.settledValue) {
                DismissPanelValue.Visible -> hasReachedVisible.value = true
                DismissPanelValue.Dismissed -> {
                    // 初次以隐藏锚点加入组合树时不回调；只有真正展示过后再退出才关闭覆盖层。
                    if (hasReachedVisible.value) onDismissed()
                }
            }
        }

        val flingBehavior = AnchoredDraggableDefaults.flingBehavior(
            state = state.anchoredState,
            // 详情页是整屏宽度，35% 会要求拖动一百多 dp；12% 与 Pager 翻页/旧版
            // 轻推手感接近，通常拖动约 45dp 即可退出。
            positionalThreshold = { distance -> distance * 0.12f }
        )
        val nestedScrollConnection = remember(
            state,
            panelWidthPx,
            velocityThresholdPx,
            gesturesEnabled
        ) {
            object : NestedScrollConnection {
                private var originalFlingVelocityX = 0f

                override fun onPreScroll(
                    available: Offset,
                    source: NestedScrollSource
                ): Offset {
                    val offset = state.anchoredState.offset
                    val panelHasMoved = !offset.isNaN() && offset > 0.5f
                    val isHorizontal = abs(available.x) > abs(available.y) * 1.2f
                    if (!gesturesEnabled || source != NestedScrollSource.UserInput ||
                        !panelHasMoved || !isHorizontal
                    ) {
                        return Offset.Zero
                    }
                    val consumedX = state.anchoredState.dispatchRawDelta(available.x)
                    return Offset(consumedX, 0f)
                }

                override fun onPostScroll(
                    consumed: Offset,
                    available: Offset,
                    source: NestedScrollSource
                ): Offset {
                    if (!gesturesEnabled || source != NestedScrollSource.UserInput ||
                        available.x <= 0f
                    ) {
                        return Offset.Zero
                    }
                    if (abs(available.x) <= abs(available.y) * 1.2f) {
                        return Offset.Zero
                    }
                    val consumedX = state.anchoredState.dispatchRawDelta(available.x)
                    return Offset(consumedX, 0f)
                }

                override suspend fun onPostFling(
                    consumed: Velocity,
                    available: Velocity
                ): Velocity {
                    if (!gesturesEnabled) {
                        originalFlingVelocityX = 0f
                        return Velocity.Zero
                    }
                    val offset = state.anchoredState.offset
                    if (offset.isNaN() || panelWidthPx <= 0f) return Velocity.Zero
                    val progress = (offset / panelWidthPx).coerceIn(0f, 1f)
                    val releaseVelocityX = if (
                        abs(originalFlingVelocityX) > abs(available.x)
                    ) {
                        originalFlingVelocityX
                    } else {
                        available.x
                    }
                    originalFlingVelocityX = 0f
                    val target = when {
                        releaseVelocityX >= velocityThresholdPx -> DismissPanelValue.Dismissed
                        releaseVelocityX <= -velocityThresholdPx -> DismissPanelValue.Visible
                        progress >= 0.12f -> DismissPanelValue.Dismissed
                        else -> DismissPanelValue.Visible
                    }
                    state.anchoredState.animateTo(target)
                    return available
                }

                override suspend fun onPreFling(available: Velocity): Velocity {
                    if (!gesturesEnabled) {
                        originalFlingVelocityX = 0f
                        return Velocity.Zero
                    }
                    originalFlingVelocityX = available.x
                    return Velocity.Zero
                }
            }
        }

        Box(
            modifier = Modifier
                .fillMaxSize()
                .graphicsLayer {
                    // 锚点首帧尚未安装时也保持在屏幕右侧，避免常驻面板短暂闪现。
                    translationX = state.anchoredState.offset.takeUnless { it.isNaN() }
                        ?: panelWidthPx
                }
                .nestedScroll(nestedScrollConnection)
                .anchoredDraggable(
                    state = state.anchoredState,
                    orientation = Orientation.Horizontal,
                    flingBehavior = flingBehavior,
                    enabled = gesturesEnabled
                )
        ) {
            content()
        }
    }
}
