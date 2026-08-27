package com.aveline.ai.mobile.presentation.settings

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.aveline.ai.mobile.presentation.components.AvelineTabRow
import com.aveline.ai.mobile.presentation.components.ModuleHeader
import com.aveline.ai.mobile.presentation.plugins.PluginsUiState
import com.aveline.ai.mobile.presentation.tools.ToolsUiState
import kotlinx.coroutines.launch

/**
 * 设置模块 V2 的 5 个 tab。
 *
 * 合并 Plugins + Tools 的设置功能,统一入口:
 * - 常规:网络 / 模型 / 语音 / 响应 / 情绪 / 学习模式 / 敏感模式
 * - 权限: 使用情况访问 / 通知访问
 * - 隐私:上下文同步 / 常驻模式
 * - 数据:聊天记录 / 关于
 * - 高级:图像生成 / 视觉分析 / 系统资源(调试工具,默认折叠)
 */
private enum class SettingsTabV2(val title: String) {
    GENERAL("常规"),
    ACCESS("权限"),
    PRIVACY("隐私"),
    DATA("数据"),
    ADVANCED("高级")
}

/**
 * 设置主界面 V2。
 *
 * 使用 TabRow + HorizontalPager 组织 5 个 tab,支持左右滑动切换。
 * 复用现有 [SettingsUiState] / [PluginsUiState] / [ToolsUiState],不修改旧文件。
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SettingsScreenV2(
    settingsUiState: SettingsUiState,
    pluginsUiState: PluginsUiState,
    toolsUiState: ToolsUiState,
    // Settings 回调
    onOpenUsageStatsSettings: () -> Unit,
    onOpenNotificationSettings: () -> Unit,
    onToggleContextSync: () -> Unit,
    onBackendUrlChange: (String) -> Unit,
    onTokenChange: (String) -> Unit,
    onTestConnection: () -> Unit,
    onSaveBackendUrl: () -> Unit,
    onTunnelUrlChange: (String) -> Unit,
    onToggleTunnel: (Boolean) -> Unit,
    onModelChange: (String) -> Unit,
    onVoiceIdChange: (String) -> Unit,
    onResponseLengthChange: (String) -> Unit,
    onToggleAutoTts: () -> Unit,
    onToggleResidentMode: () -> Unit,
    onConfirmBatteryOptimization: () -> Unit,
    onDismissBatteryOptimization: () -> Unit,
    onClearHistory: () -> Unit,
    onShowClearConfirm: () -> Unit,
    onHideClearConfirm: () -> Unit,
    onHideSaveConfirm: () -> Unit,
    // Plugins 回调(合并进来)
    onSetManualEmotion: (String) -> Unit,
    onToggleStudyMode: () -> Unit,
    onToggleAutoEmotion: () -> Unit,
    onShowEmotionSelector: () -> Unit,
    onHideEmotionSelector: () -> Unit,
    onToggleSensitive: (Boolean) -> Unit,
    onRefreshSensitive: () -> Unit,
    // Tools 回调(调试工具部分)
    onLoadImageModels: () -> Unit,
    onGenerateImage: () -> Unit,
    onImagePromptChange: (String) -> Unit,
    onImageModelChange: (String) -> Unit,
    onVisionInputChange: (String) -> Unit,
    onVisionPromptChange: (String) -> Unit,
    onDescribeVision: () -> Unit,
    onLoadSystemResources: () -> Unit,
    onLoadSystemStats: () -> Unit,
    onClearError: () -> Unit,
    onRefreshPermissions: () -> Unit = {}
) {
    val tabs = SettingsTabV2.values()
    val pagerState = rememberPagerState(initialPage = 0) { tabs.size }
    val scope = rememberCoroutineScope()

    // 监听 ON_RESUME: 用户从系统设置授权完返回时重新检测权限状态
    // 修复: 之前只在 init 检测一次, 授权后 UI 仍显示 ×, 必须杀进程才刷新
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                onRefreshPermissions()
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
            title = "Settings",
            subtitle = "应用设置"
        )

        AvelineTabRow(
            titles = tabs.map { it.title },
            selectedTabIndex = pagerState.currentPage,
            onTabSelected = { index ->
                scope.launch { pagerState.animateScrollToPage(index) }
            },
            modifier = Modifier.fillMaxWidth()
        )

        // Tab 内容区域:HorizontalPager 支持左右滑动
        HorizontalPager(
            state = pagerState,
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 16.dp)
        ) { page ->
            when (tabs[page]) {
                SettingsTabV2.GENERAL -> SettingsGeneralTab(
                    settingsUiState = settingsUiState,
                    pluginsUiState = pluginsUiState,
                    onBackendUrlChange = onBackendUrlChange,
                    onTokenChange = onTokenChange,
                    onTestConnection = onTestConnection,
                    onSaveBackendUrl = onSaveBackendUrl,
                    onTunnelUrlChange = onTunnelUrlChange,
                    onToggleTunnel = onToggleTunnel,
                    onModelChange = onModelChange,
                    onVoiceIdChange = onVoiceIdChange,
                    onResponseLengthChange = onResponseLengthChange,
                    onToggleAutoTts = onToggleAutoTts,
                    onSetManualEmotion = onSetManualEmotion,
                    onToggleStudyMode = onToggleStudyMode,
                    onToggleAutoEmotion = onToggleAutoEmotion,
                    onShowEmotionSelector = onShowEmotionSelector,
                    onHideEmotionSelector = onHideEmotionSelector,
                    onToggleSensitive = onToggleSensitive,
                    onRefreshSensitive = onRefreshSensitive,
                    onHideSaveConfirm = onHideSaveConfirm
                )

                SettingsTabV2.ACCESS -> SettingsAccessTab(
                    settingsUiState = settingsUiState,
                    onOpenUsageStatsSettings = onOpenUsageStatsSettings,
                    onOpenNotificationSettings = onOpenNotificationSettings
                )

                SettingsTabV2.PRIVACY -> SettingsPrivacyTab(
                    settingsUiState = settingsUiState,
                    onToggleContextSync = onToggleContextSync,
                    onToggleResidentMode = onToggleResidentMode,
                    onConfirmBatteryOptimization = onConfirmBatteryOptimization,
                    onDismissBatteryOptimization = onDismissBatteryOptimization
                )

                SettingsTabV2.DATA -> SettingsDataTab(
                    settingsUiState = settingsUiState,
                    onClearHistory = onClearHistory,
                    onShowClearConfirm = onShowClearConfirm,
                    onHideClearConfirm = onHideClearConfirm
                )

                SettingsTabV2.ADVANCED -> SettingsAdvancedTab(
                    toolsUiState = toolsUiState,
                    onLoadImageModels = onLoadImageModels,
                    onGenerateImage = onGenerateImage,
                    onImagePromptChange = onImagePromptChange,
                    onImageModelChange = onImageModelChange,
                    onVisionInputChange = onVisionInputChange,
                    onVisionPromptChange = onVisionPromptChange,
                    onDescribeVision = onDescribeVision,
                    onLoadSystemResources = onLoadSystemResources,
                    onLoadSystemStats = onLoadSystemStats,
                    onClearError = onClearError
                )
            }
        }
    }
}
