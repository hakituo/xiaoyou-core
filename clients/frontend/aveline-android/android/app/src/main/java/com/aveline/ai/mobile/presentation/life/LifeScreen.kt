package com.aveline.ai.mobile.presentation.life

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.aveline.ai.mobile.presentation.components.AvelineTabRow
import com.aveline.ai.mobile.presentation.components.ModuleHeader
import com.aveline.ai.mobile.presentation.components.ModuleHeaderActionContainer
import com.aveline.ai.mobile.presentation.health.DailyDataUiState
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import kotlinx.coroutines.launch

/**
 * Life 模块 Tab 枚举。
 *
 * 说明:现有 [com.aveline.ai.mobile.presentation.health.DailyTab] 仅包含
 * PORTRAIT / SCHEDULE / FILES 三个值,无法表达"饮水 / 餐食"两个独立 tab。
 * 为遵循"只创建新文件、不修改旧文件"的约束,这里新建 LifeTab 枚举。
 */
enum class LifeTab(val title: String) {
    HEALTH("健康"),
    SCHEDULE("日程"),
    WATER("饮水"),
    MEAL("餐食")
}

/**
 * Life 模块主界面。
 *
 * 用 TabRow + HorizontalPager 组织 4 个 tab:健康 / 饮水 / 日程 / 餐食。
 * 复用现有 [DailyDataUiState] 作为数据源,支持左右滑动切换。
 *
 * @param uiState 日常生活数据状态
 * @param onRefresh 刷新回调
 * @param onSyncSamsungHealth 从 Samsung Health 同步数据
 * @param onTabChange Tab 切换回调
 * @param onUpdateSchedule 更新作息回调(睡觉/起床时间)
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun LifeScreen(
    uiState: DailyDataUiState,
    onRefresh: () -> Unit,
    onSyncSamsungHealth: () -> Unit,
    onTabChange: (LifeTab) -> Unit,
    onUpdateSchedule: (sleep: String?, wakeup: String?) -> Unit
) {
    val tabs = LifeTab.values()
    val pagerState = rememberPagerState(initialPage = 0) { tabs.size }
    val scope = rememberCoroutineScope()

    // 监听 pager 页面变化,通知外部
    LaunchedEffect(pagerState.currentPage) {
        onTabChange(tabs[pagerState.currentPage])
    }

    // 进入 HEALTH tab 时检查是否需要立即同步(距上次同步超过 30 秒)
    LaunchedEffect(pagerState.currentPage) {
        if (pagerState.currentPage == LifeTab.HEALTH.ordinal) {
            val elapsed = System.currentTimeMillis() - uiState.lastRefreshTime
            if (elapsed > 30_000L) {
                onSyncSamsungHealth()
            }
        }
    }

    // HEALTH tab 可见时定时自动刷新:
    // 活动状态(有活动消耗热量) 1 分钟刷新,非活动状态 5 分钟刷新
    // 用 lastRefreshTime 作为 key: 同步完成后 key 变化, effect 重启重新计时
    LaunchedEffect(pagerState.currentPage, uiState.lastRefreshTime) {
        if (pagerState.currentPage != LifeTab.HEALTH.ordinal) return@LaunchedEffect
        val isActive = (uiState.activeCaloriesBurned ?: 0.0) > 0
        val intervalMs = if (isActive) 60_000L else 300_000L
        kotlinx.coroutines.delay(intervalMs)
        onSyncSamsungHealth()
    }

    // ON_RESUME 重新拉数据: 用户从 Health Connect 设置页授权完返回时,
    // 电池/网络/设备上下文等数据需要重新读取 (与 Settings 页权限重检同理)
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                onRefresh()
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        // 顶部模块标题
        ModuleHeader(
            title = "Life",
            subtitle = "日常生活"
        ) {
            ModuleHeaderActionContainer {
                IconButton(onClick = onRefresh) {
                    if (uiState.isLoading) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            color = Color.White,
                            strokeWidth = 2.dp
                        )
                    } else {
                        Icon(
                            imageVector = Icons.Default.Refresh,
                            contentDescription = "刷新",
                            tint = Color.White
                        )
                    }
                }
            }
        }

        AvelineTabRow(
            titles = tabs.map { it.title },
            selectedTabIndex = pagerState.currentPage,
            onTabSelected = { index ->
                scope.launch { pagerState.animateScrollToPage(index) }
            },
            modifier = Modifier.fillMaxWidth()
        )

        // 消息提示
        uiState.message?.takeIf { it.isNotBlank() }?.let { message ->
            Text(
                text = message,
                color = EmotionGreen,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
            )
        }

        // 错误提示
        uiState.error?.takeIf { it.isNotBlank() }?.let { error ->
            Text(
                text = error,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
            )
        }

        // Tab 内容区域:HorizontalPager 支持左右滑动
        HorizontalPager(
            state = pagerState,
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 16.dp)
        ) { page ->
            val tab = tabs[page]
            // 与 Companion 一致:内层 Box 无 padding,只做容器对齐
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.TopStart
            ) {
                when (tab) {
                    LifeTab.HEALTH -> Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .verticalScroll(rememberScrollState())
                            .padding(horizontal = 16.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp)
                    ) {
                        Spacer(modifier = Modifier.height(8.dp))
                        LifeHealthTab(
                            uiState = uiState,
                            onSyncSamsungHealth = onSyncSamsungHealth
                        )
                        Spacer(modifier = Modifier.height(24.dp))
                    }

                    LifeTab.WATER -> Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .verticalScroll(rememberScrollState())
                            .padding(horizontal = 16.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp)
                    ) {
                        Spacer(modifier = Modifier.height(8.dp))
                        LifeWaterTab(
                            uiState = uiState
                        )
                        Spacer(modifier = Modifier.height(24.dp))
                    }

                    LifeTab.SCHEDULE -> Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .verticalScroll(rememberScrollState())
                            .padding(horizontal = 16.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp)
                    ) {
                        Spacer(modifier = Modifier.height(8.dp))
                        LifeScheduleTab(
                            uiState = uiState,
                            onUpdateSchedule = onUpdateSchedule
                        )
                        Spacer(modifier = Modifier.height(24.dp))
                    }

                    LifeTab.MEAL -> Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .verticalScroll(rememberScrollState())
                            .padding(horizontal = 16.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp)
                    ) {
                        Spacer(modifier = Modifier.height(8.dp))
                        LifeMealTab(
                            uiState = uiState
                        )
                        Spacer(modifier = Modifier.height(24.dp))
                    }
                }
            }
        }
    }
}
