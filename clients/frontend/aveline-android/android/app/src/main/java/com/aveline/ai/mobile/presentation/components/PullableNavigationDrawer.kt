@file:OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)

package com.aveline.ai.mobile.presentation.components

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.AnchoredDraggableDefaults
import androidx.compose.foundation.gestures.AnchoredDraggableState
import androidx.compose.foundation.gestures.DraggableAnchors
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.anchoredDraggable
import androidx.compose.foundation.gestures.animateTo
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Velocity
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import kotlin.math.abs

enum class PullableDrawerValue {
    Closed,
    Open
}

@Stable
class PullableDrawerState internal constructor(
    internal val dragState: AnchoredDraggableState<PullableDrawerValue>
) {
    val isOpen: Boolean
        get() = dragState.currentValue == PullableDrawerValue.Open

    val isVisible: Boolean
        get() = dragState.currentValue != PullableDrawerValue.Closed ||
            dragState.targetValue != PullableDrawerValue.Closed ||
            dragState.isAnimationRunning

    suspend fun open() {
        dragState.animateTo(PullableDrawerValue.Open)
    }

    suspend fun close() {
        dragState.animateTo(PullableDrawerValue.Closed)
    }
}

@Composable
fun rememberPullableDrawerState(): PullableDrawerState {
    return remember {
        PullableDrawerState(
            AnchoredDraggableState(initialValue = PullableDrawerValue.Closed)
        )
    }
}

/**
 * 支持 Pager 边界手势接力的跟手侧边栏。
 *
 * 普通页面由 anchoredDraggable 直接驱动；HorizontalPager 到达第一页后，无法消费的
 * 右滑会经 NestedScrollConnection 传给同一状态，因此两条路径拥有完全一致的位移和吸附动画。
 *
 * 软键盘显示期间禁用抽屉拖拽。聊天输入状态下横向手势优先留给正文/系统返回，
 * 避免打字时误把全局侧边栏拖出来。
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun PullableNavigationDrawer(
    state: PullableDrawerState,
    modifier: Modifier = Modifier,
    drawerWidthGap: androidx.compose.ui.unit.Dp = 56.dp,
    scrimColor: Color = Color(0xCC020617),
    onDismissRequest: () -> Unit,
    drawerContent: @Composable () -> Unit,
    content: @Composable () -> Unit
) {
    BoxWithConstraints(modifier = modifier.fillMaxSize()) {
        val density = LocalDensity.current
        val drawerWidth = maxWidth - drawerWidthGap
        val drawerWidthPx = with(density) { drawerWidth.toPx() }
        val velocityThresholdPx = with(density) { 125.dp.toPx() }
        val drawerGesturesEnabled = WindowInsets.ime.getBottom(density) == 0
        val anchors = remember(drawerWidthPx) {
            DraggableAnchors {
                PullableDrawerValue.Closed at -drawerWidthPx
                PullableDrawerValue.Open at 0f
            }
        }
        SideEffect {
            state.dragState.updateAnchors(anchors)
        }

        val flingBehavior = AnchoredDraggableDefaults.flingBehavior(
            state = state.dragState,
            positionalThreshold = { distance -> distance * 0.12f }
        )
        val nestedScrollConnection = remember(
            state,
            drawerWidthPx,
            velocityThresholdPx,
            drawerGesturesEnabled
        ) {
            object : NestedScrollConnection {
                private var originalFlingVelocityX = 0f

                override fun onPreScroll(
                    available: Offset,
                    source: NestedScrollSource
                ): Offset {
                    if (!drawerGesturesEnabled) return Offset.Zero
                    val offset = state.dragState.offset
                    val drawerHasLeftClosedAnchor = !offset.isNaN() &&
                        offset > -drawerWidthPx + 0.5f
                    val isHorizontal = abs(available.x) > abs(available.y) * 1.2f
                    if (source != NestedScrollSource.UserInput ||
                        !drawerHasLeftClosedAnchor ||
                        !isHorizontal
                    ) {
                        return Offset.Zero
                    }
                    val consumedX = state.dragState.dispatchRawDelta(available.x)
                    return Offset(consumedX, 0f)
                }

                override fun onPostScroll(
                    consumed: Offset,
                    available: Offset,
                    source: NestedScrollSource
                ): Offset {
                    if (!drawerGesturesEnabled) return Offset.Zero
                    if (source != NestedScrollSource.UserInput || available.x <= 0f) {
                        return Offset.Zero
                    }
                    if (abs(available.x) <= abs(available.y) * 1.2f) {
                        return Offset.Zero
                    }
                    val consumedX = state.dragState.dispatchRawDelta(available.x)
                    return Offset(consumedX, 0f)
                }

                override suspend fun onPostFling(
                    consumed: Velocity,
                    available: Velocity
                ): Velocity {
                    if (!drawerGesturesEnabled) {
                        originalFlingVelocityX = 0f
                        return Velocity.Zero
                    }
                    val offset = state.dragState.offset
                    if (offset.isNaN()) return Velocity.Zero
                    val drawerHasMoved = offset > -drawerWidthPx + 0.5f
                    if (!drawerHasMoved) {
                        originalFlingVelocityX = 0f
                        return Velocity.Zero
                    }
                    val progress = ((offset + drawerWidthPx) / drawerWidthPx).coerceIn(0f, 1f)
                    val releaseVelocityX = if (
                        abs(originalFlingVelocityX) > abs(available.x)
                    ) {
                        originalFlingVelocityX
                    } else {
                        available.x
                    }
                    originalFlingVelocityX = 0f
                    val target = when {
                        releaseVelocityX >= velocityThresholdPx -> PullableDrawerValue.Open
                        releaseVelocityX <= -velocityThresholdPx -> PullableDrawerValue.Closed
                        progress >= 0.12f -> PullableDrawerValue.Open
                        else -> PullableDrawerValue.Closed
                    }
                    state.dragState.animateTo(target)
                    return available
                }

                override suspend fun onPreFling(available: Velocity): Velocity {
                    if (!drawerGesturesEnabled) {
                        originalFlingVelocityX = 0f
                        return Velocity.Zero
                    }
                    val offset = state.dragState.offset
                    val drawerHasMoved = !offset.isNaN() && offset > -drawerWidthPx + 0.5f
                    originalFlingVelocityX = if (drawerHasMoved) available.x else 0f
                    return Velocity.Zero
                }
            }
        }

        Box(
            modifier = Modifier
                .fillMaxSize()
                .nestedScroll(nestedScrollConnection)
                .anchoredDraggable(
                    state = state.dragState,
                    orientation = Orientation.Horizontal,
                    enabled = drawerGesturesEnabled,
                    flingBehavior = flingBehavior
                )
        ) {
            content()

            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .graphicsLayer {
                        val offset = state.dragState.offset
                        alpha = if (offset.isNaN() || drawerWidthPx <= 0f) {
                            0f
                        } else {
                            ((offset + drawerWidthPx) / drawerWidthPx).coerceIn(0f, 1f)
                        }
                    }
                    .background(scrimColor)
            )

            if (state.isVisible) {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .clickable(onClick = onDismissRequest)
                        .zIndex(1f)
                )
            }

            Box(
                modifier = Modifier
                    .width(drawerWidth)
                    .fillMaxHeight()
                    .graphicsLayer {
                        translationX = state.dragState.offset.takeUnless { it.isNaN() }
                            ?: -drawerWidthPx
                    }
                    .zIndex(2f)
            ) {
                drawerContent()
            }
        }
    }
}
