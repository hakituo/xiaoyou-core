package com.aveline.ai.mobile.presentation.navigation

import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.core.tween
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import androidx.navigation.navDeepLink
import com.aveline.ai.mobile.data.local.storage.PersonaAvatarStorage
import com.aveline.ai.mobile.presentation.chat.ChatScreen
import com.aveline.ai.mobile.presentation.chat.ChatViewModel
import com.aveline.ai.mobile.presentation.companion.CompanionScreen
import com.aveline.ai.mobile.presentation.conversations.ConversationAvatarStorageHolder
import com.aveline.ai.mobile.presentation.conversations.ConversationListScreen
import com.aveline.ai.mobile.presentation.conversations.ConversationListViewModel
import com.aveline.ai.mobile.presentation.food.FoodScreen
import com.aveline.ai.mobile.presentation.health.DailyDataViewModel
import com.aveline.ai.mobile.presentation.life.LifeScreen
import com.aveline.ai.mobile.presentation.memory.MemoryViewModel
import com.aveline.ai.mobile.presentation.persona.PersonaViewModel
import com.aveline.ai.mobile.presentation.plugins.PluginsViewModel
import com.aveline.ai.mobile.presentation.settings.SettingsScreenV2
import com.aveline.ai.mobile.presentation.settings.SettingsViewModel
import com.aveline.ai.mobile.presentation.shop.ShopViewModel
import com.aveline.ai.mobile.presentation.wellbeing.WellbeingScreen
import com.aveline.ai.mobile.presentation.wellbeing.WellbeingViewModel
import com.aveline.ai.mobile.presentation.status.StatusViewModel
import com.aveline.ai.mobile.presentation.study.StudyDailyViewModel
import com.aveline.ai.mobile.presentation.study.StudyFocusViewModel
import com.aveline.ai.mobile.presentation.study.StudyNotesViewModel
import com.aveline.ai.mobile.presentation.study.StudyPlanViewModel
import com.aveline.ai.mobile.presentation.study.StudyScreenV2
import com.aveline.ai.mobile.presentation.study.StudyTabV2
import com.aveline.ai.mobile.presentation.study.StudyViewModel
import com.aveline.ai.mobile.presentation.tools.ToolsViewModel
import com.aveline.ai.mobile.domain.models.EmotionType
import com.aveline.ai.mobile.domain.models.ResponseLength
import com.aveline.ai.mobile.presentation.utils.EmotionResolver

/**
 * 应用导航路由。
 *
 * 单元职责:
 * - Conversations: 会话列表（主页，QQ 风格，每个 persona 一项）
 * - Chat: 聊天详情页（从会话列表点入）
 * - Companion: AI 伴侣(状态 / 人设 / 记忆)
 * - Study: 学习(概览 / 计划 / 日记 / 笔记 / 文件 / 词汇)
 * - Life: 日常生活(健康 / 饮水 / 日程 / 餐食)
 * - Food: 食物商店(购买 + 食用)
 * - Settings: 设置(常规 / 权限 / 隐私 / 数据 / 高级)
 */
object Routes {
    const val CONVERSATIONS = "conversations"
    const val CHAT = "chat"
    const val COMPANION = "companion"
    const val STUDY = "study"
    const val LIFE = "life"
    const val FOOD = "food"
    const val SETTINGS = "settings"
    const val WELLBEING = "wellbeing"

    // 深链查询参数
    const val CHAT_TEXT_PARAM = "text"
}

/**
 * 导航参数名。
 */
object NavArgs {
    const val TEXT = "text"
    const val ROLE = "role"
    const val PERSONA_FILENAME = "persona_filename"
}

/**
 * 页面切换动画时长(毫秒)。fade 用于 tab 切换，slide 用于会话列表 ↔ 聊天详情。
 */
private const val ANIM_DURATION = 300

/**
 * 创建 Aveline 主导航图。
 *
 * @param navController 导航控制器
 * @param onMenuClick 菜单按钮点击回调
 * @param startDestination 起始目的地路由（默认会话列表）
 */
@Suppress("UNUSED_PARAMETER")
fun NavGraphBuilder.avelineNavGraph(
    navController: NavHostController,
    onMenuClick: () -> Unit = {},
    startDestination: String = Routes.CONVERSATIONS
) {
    // ===== Conversations - 会话列表（主页，QQ 风格）=====
    composable(
        route = Routes.CONVERSATIONS,
        deepLinks = listOf(
            navDeepLink { uriPattern = "aveline://conversations" }
        ),
        enterTransition = { fadeIn(animationSpec = tween(ANIM_DURATION)) },
        exitTransition = {
            // 跳转到 Chat 时，会话列表向左滑出（QQ 风格）
            slideOutHorizontally(
                targetOffsetX = { -it / 3 },
                animationSpec = tween(ANIM_DURATION)
            ) + fadeOut(animationSpec = tween(ANIM_DURATION))
        },
        popEnterTransition = {
            // 从 Chat 返回时，会话列表从左侧滑入
            slideInHorizontally(
                initialOffsetX = { -it / 3 },
                animationSpec = tween(ANIM_DURATION)
            ) + fadeIn(animationSpec = tween(ANIM_DURATION))
        },
        popExitTransition = { fadeOut(animationSpec = tween(ANIM_DURATION)) }
    ) {
        val viewModel: ConversationListViewModel = hiltViewModel()
        val uiState by viewModel.uiState.collectAsStateWithLifecycle()
        val avatarStorage: PersonaAvatarStorage = hiltViewModel<ConversationAvatarStorageHolder>().avatarStorage

        Surface(modifier = Modifier.fillMaxSize(), color = Color.Transparent) {
        ConversationListScreen(
            uiState = uiState,
            onRefresh = viewModel::refresh,
            // 点击角色：navigate 进 Chat，带 role + personaFilename。
            // 优先切到消息列表里代表该角色显示的那个 persona，避免点进去变成其它版本。
            onOpenChat = { role, personaFilename ->
                val encodedRole = java.net.URLEncoder.encode(role, "UTF-8")
                val encodedFilename = java.net.URLEncoder.encode(personaFilename, "UTF-8")
                navController.navigate(
                    "${Routes.CHAT}?text=&role=$encodedRole&filename=$encodedFilename"
                )
            },
            onUpdateDisplayName = viewModel::updateDisplayName,
            onUpdateAvatar = viewModel::updateAvatar,
            onClearAvatar = viewModel::clearAvatar,
            onClearError = viewModel::clearError,
            avatarStorage = avatarStorage
        )
        }
    }

    // ===== Chat - 聊天详情页（从会话列表点入，QQ 风格 push/pop 转场）=====
    composable(
        route = "${Routes.CHAT}?text={${NavArgs.TEXT}}&role={${NavArgs.ROLE}}&filename={${NavArgs.PERSONA_FILENAME}}",
        arguments = listOf(
            navArgument(NavArgs.TEXT) {
                type = NavType.StringType
                nullable = true
                defaultValue = null
            },
            navArgument(NavArgs.ROLE) {
                type = NavType.StringType
                nullable = true
                defaultValue = null
            },
            navArgument(NavArgs.PERSONA_FILENAME) {
                type = NavType.StringType
                nullable = true
                defaultValue = null
            }
        ),
        deepLinks = listOf(
            navDeepLink { uriPattern = "aveline://chat" },
            navDeepLink { uriPattern = "aveline://chat?text={${NavArgs.TEXT}}" },
            navDeepLink { uriPattern = "aveline://chat?role={${NavArgs.ROLE}}" }
        ),
        enterTransition = {
            // 从会话列表进入：聊天页从右侧滑入（QQ push）
            slideInHorizontally(
                initialOffsetX = { it },
                animationSpec = tween(ANIM_DURATION)
            ) + fadeIn(animationSpec = tween(ANIM_DURATION))
        },
        exitTransition = { fadeOut(animationSpec = tween(ANIM_DURATION)) },
        popEnterTransition = { fadeIn(animationSpec = tween(ANIM_DURATION)) },
        popExitTransition = {
            // 返回会话列表：聊天页向右滑出（QQ pop）
            slideOutHorizontally(
                targetOffsetX = { it },
                animationSpec = tween(ANIM_DURATION)
            ) + fadeOut(animationSpec = tween(ANIM_DURATION))
        }
    ) { backStackEntry ->
        val chatViewModel: ChatViewModel = hiltViewModel()
        // 从 route 参数取 role + personaFilename。如果列表点击时带了 filename，
        // 优先切到列表里显示的那个 persona，避免点进去变成同一角色下的其它版本。
        val targetRole = backStackEntry.arguments?.getString(NavArgs.ROLE)
        val targetFilename = backStackEntry.arguments?.getString(NavArgs.PERSONA_FILENAME)
        // 进入聊天页只记录"待切换意图"，不立即切 persona；真正切人设推迟到用户首次发消息时，
        // 避免只是查看历史也打后端 API（减少 429）。用 LaunchedEffect(Unit) 保证只执行一次。
        LaunchedEffect(Unit) {
            if (!targetRole.isNullOrBlank()) {
                chatViewModel.setPendingSwitch(targetRole, targetFilename)
            }
        }
        ChatScreen(
            viewModel = chatViewModel,
            onBackClick = { navController.popBackStack() }
        )
    }

    // ===== Companion - 已合并到 Chat 内的伴侣详情面板,深链重定向到 Conversations（主页）=====
    composable(
        route = Routes.COMPANION,
        deepLinks = listOf(
            navDeepLink { uriPattern = "aveline://companion" }
        ),
        enterTransition = { fadeIn(animationSpec = tween(ANIM_DURATION)) },
        exitTransition = { fadeOut(animationSpec = tween(ANIM_DURATION)) },
        popEnterTransition = { fadeIn(animationSpec = tween(ANIM_DURATION)) },
        popExitTransition = { fadeOut(animationSpec = tween(ANIM_DURATION)) }
    ) {
        // Companion 已合并到 Chat 内的伴侣详情面板（点聊天页头像打开），深链回到主页
        LaunchedEffect(Unit) {
            navController.navigate(Routes.CONVERSATIONS) {
                popUpTo(Routes.COMPANION) { inclusive = true }
            }
        }
    }

    // ===== Study - 学习(整合 Daily 文件夹,6 tab) =====
    composable(
        route = Routes.STUDY,
        deepLinks = listOf(
            navDeepLink { uriPattern = "aveline://study" }
        ),
        enterTransition = { fadeIn(animationSpec = tween(ANIM_DURATION)) },
        exitTransition = { fadeOut(animationSpec = tween(ANIM_DURATION)) },
        popEnterTransition = { fadeIn(animationSpec = tween(ANIM_DURATION)) },
        popExitTransition = { fadeOut(animationSpec = tween(ANIM_DURATION)) }
    ) {
        val viewModel: StudyViewModel = hiltViewModel()
        val dailyViewModel: StudyDailyViewModel = hiltViewModel()
        val focusViewModel: StudyFocusViewModel = hiltViewModel()
        val planViewModel: StudyPlanViewModel = hiltViewModel()
        val notesViewModel: StudyNotesViewModel = hiltViewModel()
        val uiState by viewModel.uiState.collectAsStateWithLifecycle()
        val dailyUiState by dailyViewModel.uiState.collectAsStateWithLifecycle()
        val focusState by focusViewModel.uiState.collectAsStateWithLifecycle()
        val planUiState by planViewModel.uiState.collectAsStateWithLifecycle()
        val notesUiState by notesViewModel.uiState.collectAsStateWithLifecycle()
        val vocabUiState by viewModel.vocabUiState.collectAsStateWithLifecycle()

        Surface(modifier = Modifier.fillMaxSize(), color = Color.Transparent) {
            StudyScreenV2(
            uiState = uiState,
            dailyUiState = dailyUiState,
            focusState = focusState,
            planUiState = planUiState,
            notesUiState = notesUiState,
            vocabUiState = vocabUiState,
            onPlanStartFocus = { planItem ->
                focusViewModel.setFocusName(planItem.content)
                com.aveline.ai.mobile.presentation.study.parseDurationMinutes(
                    planItem.duration
                )?.let { minutes -> focusViewModel.setWorkMinutes(minutes) }
            },
                // Tab 切换:根据 tab 触发对应数据加载,不再依赖硬编码数据
                onTabChange = { tab ->
                    when (tab) {
                        StudyTabV2.VOCAB -> {
                            viewModel.loadLearnWords()
                            viewModel.loadManualStudyToday()
                            viewModel.loadVocabBooks()
                            // 拉取复习总览(连续天数+记忆曲线)与错题本
                            viewModel.loadReviewOverview()
                            viewModel.loadMistakes()
                        }
                        StudyTabV2.NOTES -> notesViewModel.loadLibraryNotes()
                        StudyTabV2.PLAN -> planViewModel.loadPlan(planViewModel.uiState.value.selectedDate)
                        StudyTabV2.DIARY -> dailyViewModel.loadDateContent(dailyViewModel.uiState.value.selectedDate)
                        else -> {}
                    }
                },
                onTopicChange = viewModel::setRecordTopic,
                onContentChange = viewModel::setRecordContent,
                // 时长:Int -> String
                onDurationChange = { duration ->
                    viewModel.setRecordDuration(duration.toString())
                },
                onRecordStudy = viewModel::recordStudyProgress,
                onStartStudy = viewModel::startStudySession,
                onFinishStudy = viewModel::finishStudySession,
                onClearError = viewModel::clearError,
                onStartReview = viewModel::startReview,
                onStartNewWords = viewModel::startNewWords,
                // 评分:String -> Int("1".."4" 映射到 1..4)
                onSubmitReview = { quality ->
                    viewModel.submitReview(quality.toIntOrNull() ?: 3)
                },
                onSetShowAnswer = viewModel::setShowAnswer,
                onSetIsReviewMode = viewModel::setIsReviewMode,
                // 会话总结:空字符串 -> null(清除总结)
                onSetSessionSummary = { summary ->
                    viewModel.setSessionSummary(if (summary.isBlank()) null else summary)
                },
                // 学习库笔记:打开/关闭阅读页
                onOpenLibraryNote = { path -> notesViewModel.openNote(path) },
                onCloseLibraryNoteReader = { notesViewModel.closeReader() },
                onSelectDate = { date ->
                    dailyViewModel.selectDate(date)
                    planViewModel.loadPlan(date)
                },
                onRefreshDaily = { dailyViewModel.refreshAll() },
                // 计划编辑:写回后端 plan.md（来自独立的 StudyPlanViewModel）
                onSavePlan = { items ->
                    planViewModel.savePlan(planViewModel.uiState.value.selectedDate, items)
                },
                // 番茄钟回调（来自独立的 StudyFocusViewModel）
                onToggleFocusTimer = focusViewModel::toggleTimer,
                onResetFocusTimer = focusViewModel::resetTimer,
                onSkipFocusPhase = focusViewModel::skipPhase,
                onFocusWorkMinutesChange = focusViewModel::setWorkMinutes,
                onFocusBreakMinutesChange = focusViewModel::setBreakMinutes,
                onFocusLongBreakMinutesChange = focusViewModel::setLongBreakMinutes,
                onFocusNameChange = focusViewModel::setFocusName,
                onToggleWordOrder = viewModel::toggleWordOrder,
                onAddManualStudy = viewModel::addManualStudy,
                onOpenBooks = viewModel::loadVocabBooks,
                onLoadBookWords = { viewModel.loadBookWords() },
                onSwitchBook = viewModel::switchVocabBook,
                onSearch = viewModel::searchDictionary,
                onClearSearch = viewModel::clearSearch
            )
        }
    }

    // ===== Life - 日常生活(健康 / 饮水 / 日程 / 餐食) =====
    composable(
        route = Routes.LIFE,
        deepLinks = listOf(
            navDeepLink { uriPattern = "aveline://life" }
        ),
        enterTransition = { fadeIn(animationSpec = tween(ANIM_DURATION)) },
        exitTransition = { fadeOut(animationSpec = tween(ANIM_DURATION)) },
        popEnterTransition = { fadeIn(animationSpec = tween(ANIM_DURATION)) },
        popExitTransition = { fadeOut(animationSpec = tween(ANIM_DURATION)) }
    ) {
        val viewModel: DailyDataViewModel = hiltViewModel()
        val uiState by viewModel.uiState.collectAsStateWithLifecycle()
        val context = androidx.compose.ui.platform.LocalContext.current

        Surface(modifier = Modifier.fillMaxSize(), color = Color.Transparent) {
            LifeScreen(
                uiState = uiState,
                // 右上角刷新: 同时触发 Samsung Health 读取 + 后端拉取
                // syncFromSamsungHealth 会推数据到后端, refreshData 拉后端最新状态
                onRefresh = {
                    (context as? android.app.Activity)?.let { activity ->
                        viewModel.syncFromSamsungHealth(activity)
                    }
                    viewModel.refreshData()
                },
                // Samsung Health 同步: 权限请求需要 Activity, 从 Context 获取
                onSyncSamsungHealth = {
                    (context as? android.app.Activity)?.let { activity ->
                        viewModel.syncFromSamsungHealth(activity)
                    }
                },
                // LifeTab 与 DailyTab 不兼容,LifeScreen 自管 pagerState,这里无需通知
                onTabChange = { _ -> },
                onUpdateSchedule = viewModel::updateSchedule
            )
        }
    }

    // ===== Mall - 商城(食物/礼物/玩具/书籍/服饰/科技/奢侈品) =====
    composable(
        route = Routes.FOOD,
        deepLinks = listOf(
            navDeepLink { uriPattern = "aveline://food" },
            navDeepLink { uriPattern = "aveline://mall" }
        ),
        enterTransition = { fadeIn(animationSpec = tween(ANIM_DURATION)) },
        exitTransition = { fadeOut(animationSpec = tween(ANIM_DURATION)) },
        popEnterTransition = { fadeIn(animationSpec = tween(ANIM_DURATION)) },
        popExitTransition = { fadeOut(animationSpec = tween(ANIM_DURATION)) }
    ) {
        val shopViewModel: ShopViewModel = hiltViewModel()
        val toolsViewModel: ToolsViewModel = hiltViewModel()
        val shopUiState by shopViewModel.uiState.collectAsStateWithLifecycle()

        Surface(modifier = Modifier.fillMaxSize(), color = Color.Transparent) {
            FoodScreen(
                shopUiState = shopUiState,
                onRefresh = shopViewModel::refreshItems,
                onSelectCategory = { category -> shopViewModel.selectCategory(category) },
                onLoadMore = shopViewModel::loadMore,
                onShowPurchaseConfirm = shopViewModel::showPurchaseConfirm,
                onHidePurchaseConfirm = shopViewModel::hidePurchaseConfirm,
                onConfirmPurchase = shopViewModel::confirmPurchase,
                onIncreaseQuantity = shopViewModel::increaseQuantity,
                onDecreaseQuantity = shopViewModel::decreaseQuantity,
                onSelectRecipient = shopViewModel::selectRecipient,
                onHidePurchaseResult = shopViewModel::hidePurchaseResult,
                onClearError = shopViewModel::clearError,
                onShowGiftInventory = shopViewModel::showGiftInventory,
                onHideGiftInventory = shopViewModel::hideGiftInventory,
                onUseGift = shopViewModel::useGift,
                onHideUseGiftResult = shopViewModel::hideUseGiftResult,
                // 食用功能来自 Tools
                onEatFood = toolsViewModel::eatFood
            )
        }
    }

    // ===== Settings - 设置(合并 Plugins + Tools 调试工具) =====
    composable(
        route = Routes.SETTINGS,
        deepLinks = listOf(
            navDeepLink { uriPattern = "aveline://settings" }
        ),
        enterTransition = { fadeIn(animationSpec = tween(ANIM_DURATION)) },
        exitTransition = { fadeOut(animationSpec = tween(ANIM_DURATION)) },
        popEnterTransition = { fadeIn(animationSpec = tween(ANIM_DURATION)) },
        popExitTransition = { fadeOut(animationSpec = tween(ANIM_DURATION)) }
    ) {
        val settingsViewModel: SettingsViewModel = hiltViewModel()
        val pluginsViewModel: PluginsViewModel = hiltViewModel()
        val toolsViewModel: ToolsViewModel = hiltViewModel()
        val settingsUiState by settingsViewModel.uiState.collectAsStateWithLifecycle()
        val pluginsUiState by pluginsViewModel.uiState.collectAsStateWithLifecycle()
        val toolsUiState by toolsViewModel.uiState.collectAsStateWithLifecycle()

        Surface(modifier = Modifier.fillMaxSize(), color = Color.Transparent) {
            SettingsScreenV2(
                settingsUiState = settingsUiState,
                pluginsUiState = pluginsUiState,
                toolsUiState = toolsUiState,
                // Settings 回调
                onOpenUsageStatsSettings = settingsViewModel::openUsageStatsSettings,
                onOpenNotificationSettings = settingsViewModel::openNotificationSettings,
                onToggleContextSync = { settingsViewModel.toggleContextSync(!settingsUiState.isContextSyncEnabled) },
                onBackendUrlChange = settingsViewModel::setBackendUrl,
                onTokenChange = settingsViewModel::setAccessToken,
                onTestConnection = settingsViewModel::testConnection,
                onSaveBackendUrl = settingsViewModel::saveBackendUrl,
                onTunnelUrlChange = settingsViewModel::setTunnelUrl,
                onToggleTunnel = settingsViewModel::toggleTunnel,
                onModelChange = { modelId ->
                    pluginsUiState.models.find { it.id == modelId }?.let {
                        settingsViewModel.selectModel(it)
                    }
                },
                onVoiceIdChange = settingsViewModel::setVoiceId,
                onResponseLengthChange = { lengthStr ->
                    settingsViewModel.setResponseLength(
                        ResponseLength.values().find {
                            it.name.equals(lengthStr, ignoreCase = true)
                        } ?: ResponseLength.NORMAL
                    )
                },
                onToggleAutoTts = { settingsViewModel.toggleAutoTts(!settingsUiState.autoTtsEnabled) },
                onToggleResidentMode = { settingsViewModel.toggleResidentMode(!settingsUiState.residentModeEnabled) },
                onConfirmBatteryOptimization = settingsViewModel::confirmBatteryOptimization,
                onDismissBatteryOptimization = settingsViewModel::dismissBatteryOptimization,
                onClearHistory = settingsViewModel::clearHistory,
                onShowClearConfirm = settingsViewModel::showClearHistoryConfirm,
                onHideClearConfirm = settingsViewModel::hideClearHistoryConfirm,
                onHideSaveConfirm = settingsViewModel::hideSaveConfirm,
                // Plugins 回调(情绪 / 学习模式 / 敏感模式)
                onSetManualEmotion = { emotionName ->
                    pluginsViewModel.setManualEmotion(
                        EmotionType.values().find {
                            it.name.equals(emotionName, ignoreCase = true)
                        }
                    )
                },
                onToggleStudyMode = pluginsViewModel::toggleStudyMode,
                onToggleAutoEmotion = pluginsViewModel::toggleAutoEmotion,
                onShowEmotionSelector = {
                    // 自动情绪开启时,先关闭它,否则手动选择会被后端推送覆盖
                    if (pluginsUiState.settings.autoEmotion) {
                        pluginsViewModel.toggleAutoEmotion()
                    }
                    pluginsViewModel.showEmotionSelector()
                },
                onHideEmotionSelector = pluginsViewModel::hideEmotionSelector,
                // toggleSensitive() 无参数,忽略 Boolean 入参
                onToggleSensitive = { _ -> pluginsViewModel.toggleSensitive() },
                onRefreshSensitive = pluginsViewModel::refreshSensitive,
                // Tools 回调(高级调试工具)
                onLoadImageModels = toolsViewModel::loadImageModels,
                onGenerateImage = toolsViewModel::generateImage,
                onImagePromptChange = toolsViewModel::setImagePrompt,
                onImageModelChange = toolsViewModel::setImageModelId,
                onVisionInputChange = toolsViewModel::setVisionInput,
                onVisionPromptChange = toolsViewModel::setVisionPrompt,
                onDescribeVision = toolsViewModel::describeVision,
                onLoadSystemResources = toolsViewModel::loadSystemResources,
                onLoadSystemStats = toolsViewModel::loadSystemStats,
                onClearError = toolsViewModel::clearError,
                // ON_RESUME 时重新检测 HC / Usage Stats / Notification 三个权限, 修复授权后仍显 ×
                onRefreshPermissions = settingsViewModel::refreshPermissions
            )
        }
    }

    // ===== Wellbeing - 数字健康(应用使用时长限额) =====
    composable(
        route = Routes.WELLBEING,
        deepLinks = listOf(
            navDeepLink { uriPattern = "aveline://wellbeing" }
        ),
        enterTransition = { fadeIn(animationSpec = tween(ANIM_DURATION)) },
        exitTransition = { fadeOut(animationSpec = tween(ANIM_DURATION)) },
        popEnterTransition = { fadeIn(animationSpec = tween(ANIM_DURATION)) },
        popExitTransition = { fadeOut(animationSpec = tween(ANIM_DURATION)) }
    ) {
        val viewModel: WellbeingViewModel = hiltViewModel()
        val uiState by viewModel.uiState.collectAsStateWithLifecycle()

        Surface(modifier = Modifier.fillMaxSize(), color = Color.Transparent) {
            WellbeingScreen(
                viewModel = viewModel,
                onBackClick = { navController.popBackStack() }
            )
        }
    }
}

/**
 * 导航到指定路由(单顶 + 恢复状态)。
 */
fun NavHostController.navigateTo(route: String) {
    navigate(route) {
        launchSingleTop = true
        restoreState = true
    }
}

/**
 * 导航到 Chat 并预填文本。
 */
fun NavHostController.navigateToChatWithText(text: String) {
    // 传完整 query 参数（role/filename 空占位），避免 Navigation Compose 因中间参数省略匹配失败
    val encodedText = java.net.URLEncoder.encode(text, "UTF-8")
    navigate("${Routes.CHAT}?text=$encodedText&role=&filename=")
}
