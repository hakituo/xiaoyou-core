package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.input.pointer.pointerInput
import kotlin.math.abs

/**
 * 二级板块内的横向滑动手势：右滑 → [onPrevious]，左滑 → [onNext]。
 *
 * 它存在的意义不只是"翻上一个 / 下一个"，更重要的是**把这次横向拖拽消费掉**：
 *
 * 顶层 [com.aveline.ai.mobile.presentation.components.PullableNavigationDrawer] 用
 * `nestedScroll` + `anchoredDraggable` 承接所有没被子页面消费掉的横向手势
 * （本来是给外层 pager 翻到第一页后的手势接力用的）。外层 pager 在二级板块里关掉
 * 手势后，子页面的横滑就会一路冒泡上去把全局侧边栏拖出来 —— 手势一旦被这里消费，
 * 父层的 `anchoredDraggable` 不会再触发，父层的 nestedScroll 也拿不到位移。
 *
 * 方向判定交给触摸斜率：纵向手势子层 LazyColumn 先拿到，列表照旧上下滚动；
 * 更内层可横向滚动的区域（如笔记里的公式 / 表格、日记的作者 chips）是更深的节点，
 * 会先于本手势拿到事件并消费，因此不会被抢走。
 */
@Composable
fun Modifier.horizontalPagingSwipe(
    onPrevious: () -> Unit,
    onNext: () -> Unit,
): Modifier {
    val currentPrevious by rememberUpdatedState(onPrevious)
    val currentNext by rememberUpdatedState(onNext)
    // 兜底第二条通路：侧边栏除了自己的 anchoredDraggable，还从子层 scrollable 的
    // nestedScroll 里收"没人要的"横向位移。这里把子层没消费完的横向位移吃掉，
    // 保证无论手势走哪条通路都不会冒泡成"拖出侧边栏"。
    // 只在 onPostScroll（子层之后）吃，不抢内层横向滚动自己的位移。
    val connection = remember {
        object : NestedScrollConnection {
            override fun onPostScroll(
                consumed: Offset,
                available: Offset,
                source: NestedScrollSource
            ): Offset {
                if (source != NestedScrollSource.UserInput) return Offset.Zero
                return Offset(available.x, 0f)
            }
        }
    }
    return this
        .nestedScroll(connection)
        .pointerInput(Unit) {
            // 触摸斜率的三倍作为翻页门槛，避免点到为止的一下误触发
            val threshold = viewConfiguration.touchSlop * 3f
            var dragDistance = 0f
            detectHorizontalDragGestures(
                onDragStart = { dragDistance = 0f },
                onDragEnd = {
                    if (abs(dragDistance) >= threshold) {
                        if (dragDistance < 0f) currentNext() else currentPrevious()
                    }
                },
                onDragCancel = { dragDistance = 0f },
            ) { change, dragAmount ->
                change.consume()
                dragDistance += dragAmount
            }
        }
}

/** 只吞掉横向滑动、不做翻页：没有"上一个 / 下一个"概念的二级板块用它挡住侧边栏。 */
@Composable
fun Modifier.consumeHorizontalSwipe(): Modifier =
    horizontalPagingSwipe(onPrevious = {}, onNext = {})
