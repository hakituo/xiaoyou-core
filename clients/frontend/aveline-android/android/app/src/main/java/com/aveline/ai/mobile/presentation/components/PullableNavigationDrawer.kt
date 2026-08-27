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
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
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
            // 主页直接拖拽和 Route 内 Pager 边界接力必须使用同一短距离标准。
            // 12% 通常约 40～50dp，轻拉即可打开，不依赖 Pager 是否保留甩动速度。
            positionalThreshold = { distance -> distance * 0.12f }
        )
        val nestedScrollConnection = remember(
            state,
            drawerWidthPx,
            velocityThresholdPx
        ) {
            object : NestedScrollConnection {
                // Pager 会在 fling 阶段消费速度；必须在 pre-fling 先保存原始速度，
                // Route 内接力才能与主页 anchoredDraggable 使用同一轻甩判定。
                private var originalFlingVelocityX = 0f

                override fun onPreScroll(
                    available: Offset,
                    source: NestedScrollSource
                ): Offset {
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
                    val offset = state.dragState.offset
                    if (offset.isNaN()) return Velocity.Zero
                    val drawerHasMoved = offset > -drawerWidthPx + 0.5f
                    if (!drawerHasMoved) {
                        // 子页面（例如伴侣详情）已经独占并完成了右滑时，外层仍会收到
                        // NestedScroll 的 fling 回调。抽屉没有产生实际位移就不能只凭
                        // 子页面的甩动速度打开，否则一次手势会连续退出详情并呼出抽屉。
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

            // 关闭态不能保留全屏 clickable 节点，否则即使 enabled=false 也会位于
            // NavHost 上方参与命中测试，导致会话卡片等内容收不到点击。
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
