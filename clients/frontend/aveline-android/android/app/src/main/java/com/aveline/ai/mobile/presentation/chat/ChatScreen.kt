package com.aveline.ai.mobile.presentation.chat

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.animation.core.tween
import kotlin.math.abs
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.aveline.ai.mobile.data.local.storage.PersonaAvatarStorage
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.presentation.components.HorizontalContentGestureState
import com.aveline.ai.mobile.presentation.components.InputArea
import com.aveline.ai.mobile.presentation.components.LocalHorizontalContentGestureState
import com.aveline.ai.mobile.presentation.components.MessageBubble
import com.aveline.ai.mobile.presentation.components.MessageData
import com.aveline.ai.mobile.presentation.components.MessageType
import com.aveline.ai.mobile.presentation.components.PeerChatHeader
import com.aveline.ai.mobile.presentation.components.PeerChatMessageList
import com.aveline.ai.mobile.presentation.components.PullableDismissPanel
import com.aveline.ai.mobile.presentation.components.TimeSeparator
import com.aveline.ai.mobile.presentation.components.TypingIndicator
import com.aveline.ai.mobile.presentation.components.rememberPullableDismissPanelState
import com.aveline.ai.mobile.presentation.components.shouldShowTimeSeparator
import com.aveline.ai.mobile.presentation.companion.CompanionScreen
import com.aveline.ai.mobile.presentation.conversations.ConversationItem
import com.aveline.ai.mobile.presentation.conversations.PersonaEditSheet
import com.aveline.ai.mobile.presentation.memory.MemoryViewModel
import com.aveline.ai.mobile.presentation.persona.PersonaViewModel
import com.aveline.ai.mobile.presentation.settings.SettingsViewModel
import com.aveline.ai.mobile.presentation.status.StatusViewModel
import com.aveline.ai.mobile.presentation.theme.OverlayLight
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.services.UploadState
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * 聊天界面（QQ 风格详情页）
 *
 * 主要组件：
 * - 顶部栏：返回按钮 + 当前 persona 头像/昵称 + 点击头像打开伴侣详情
 * - 消息列表（LazyColumn，按时间正序：早→上，新→下；新消息到底部）
 * - 底部输入区：语音按钮 + 输入框 + "+"（直接打开相册）/ 发送按钮
 * - 打字指示器
 *
 * 导航：通过 NavController 进入/退出，转场动画由 NavGraph 的 slideIn/slideOut 提供（QQ 风格 push/pop）。
 *
 * @param viewModel Chat ViewModel
 * @param onBackClick 返回会话列表
 */
@Composable
fun ChatScreen(
    viewModel: ChatViewModel,
    onBackClick: () -> Unit = {}
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val listState = rememberLazyListState()
    val snackbarHostState = remember { SnackbarHostState() }
    var editingMessageId by remember { mutableStateOf<String?>(null) }
    var editingMessageText by remember { mutableStateOf("") }

    if (editingMessageId != null) {
        AlertDialog(
            onDismissRequest = { editingMessageId = null },
            title = { Text("编辑请求") },
            text = {
                OutlinedTextField(
                    value = editingMessageText,
                    onValueChange = { editingMessageText = it },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 3,
                    maxLines = 8
                )
            },
            confirmButton = {
                TextButton(
                    enabled = editingMessageText.isNotBlank(),
                    onClick = {
                        editingMessageId?.let {
                            viewModel.editUserMessage(it, editingMessageText)
                        }
                        editingMessageId = null
                    }
                ) {
                    Text("提交并生成")
                }
            },
            dismissButton = {
                TextButton(onClick = { editingMessageId = null }) {
                    Text("取消")
                }
            }
        )
    }

    // 伴侣详情面板开关：点击顶部头像打开全屏覆盖
    var showCompanionPanel by remember { mutableStateOf(false) }
    var companionDismissGestureEnabled by remember { mutableStateOf(true) }
    // 屏幕宽度（px），用于判断手势起点是否在右半屏
    val screenWidthPx = with(LocalDensity.current) {
        LocalConfiguration.current.screenWidthDp.dp.toPx()
    }
    // 手势判定参数：方向锁定后直接驱动面板位移，松手时再按速度或 12% 展开进度吸附。
    val touchSlopPx = with(LocalDensity.current) { 16.dp.toPx() }
    val openVelocityThresholdPx = with(LocalDensity.current) { 125.dp.toPx() }

    // 顶部栏需要的 persona 数据
    val personaViewModel: PersonaViewModel = hiltViewModel()
    val personaUiState by personaViewModel.uiState.collectAsStateWithLifecycle()

    // Companion 的 ViewModel
    val statusViewModel: StatusViewModel = hiltViewModel()
    val memoryViewModel: MemoryViewModel = hiltViewModel()
    val settingsViewModel: SettingsViewModel = hiltViewModel()
    val statusUiState by statusViewModel.uiState.collectAsStateWithLifecycle()
    val memoryUiState by memoryViewModel.uiState.collectAsStateWithLifecycle()
    val settingsUiState by settingsViewModel.uiState.collectAsStateWithLifecycle()

    // 伴侣详情的"正在查看角色"跟随当前聊天会话：进哪个角色的聊天，详情就显示哪个角色。
    // 纯只读推送，不切对话人设（切人设仍由发消息触发）。
    val viewingPersona by viewModel.viewingPersonaFilename.collectAsStateWithLifecycle()
    LaunchedEffect(viewingPersona, uiState.currentSession?.id) {
        viewingPersona?.let { fn ->
            memoryViewModel.setViewingPersona(fn)
            statusViewModel.setControlContext(fn, uiState.currentSession?.id)
        }
    }

    // 头像本地存储（用于 Chat 顶部头像，如果用户给 persona 设了自定义头像）
    val avatarStorageHolder: ChatAvatarStorageHolder = hiltViewModel()
    val avatarStorage = avatarStorageHolder.avatarStorage
    val localMeta: PersonaLocalMetaRepository = avatarStorageHolder.localMeta
    val localAvatarMap by avatarStorageHolder.localAvatarMap.collectAsStateWithLifecycle()

    // 伴侣详情页"编辑资料"（昵称/头像）面板状态
    var editingItem by remember { mutableStateOf<ConversationItem?>(null) }
    val companionEditScope = rememberCoroutineScope()
    val companionPanelState = rememberPullableDismissPanelState()
    val horizontalContentGestureState = remember { HorizontalContentGestureState() }
    val openCompanionPanel: () -> Unit = {
        companionEditScope.launch {
            // 面板常驻在屏幕右侧隐藏锚点，点击头像时直接动画到可见位置。
            showCompanionPanel = true
            statusViewModel.refreshStatus()
            companionPanelState.show()
        }
    }
    val closeCompanionPanel: () -> Unit = {
        companionEditScope.launch {
            companionPanelState.dismiss()
        }
    }

    // 文件选择器 - 通用文件（保留入口，但当前输入栏 "+"号 = 直接打开相册，文件入口暂未暴露）
    val filePickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent()
    ) { uri: Uri? ->
        uri?.let {
            viewModel.uploadFile(it, isImage = false)
        }
    }

    // 图片选择器：+ 号直接打开相册
    val imagePickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent()
    ) { uri: Uri? ->
        uri?.let {
            viewModel.uploadImage(it)
        }
    }

    // 录音权限请求：用户首次点麦克风时弹权限对话框
    val recordAudioPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { granted: Boolean ->
        if (granted) {
            // 权限授予，立即开始录音
            viewModel.startVoiceRecording()
        } else {
            viewModel.setError("缺少录音权限，请在系统设置中授予")
        }
    }

    // 显示错误信息（带"复制"按钮）
    val context = LocalContext.current
    LaunchedEffect(uiState.error) {
        uiState.error?.let { error ->
            val result = snackbarHostState.showSnackbar(
                message = error,
                actionLabel = "复制",
                duration = SnackbarDuration.Long
            )
            if (result == SnackbarResult.ActionPerformed) {
                val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clipboard.setPrimaryClip(ClipData.newPlainText("error", error))
                Toast.makeText(context, "已复制错误信息", Toast.LENGTH_SHORT).show()
            }
            viewModel.clearError()
        }
    }

    // 消息列表定位：
    // 1. 首次进入会话（或切换会话后消息首次加载完成）时，直接跳到最新消息（最后聊天位置），
    //    否则列表停留在最顶端，看起来像"从最开始聊天的地方开始"。用 scrollToItem 瞬时跳转，
    //    历史消息多时避免长滚动动画；先等列表布局出目标项再跳，避免在 LazyColumn 尚未布局
    //    item 时跳转失效。
    // 2. 之后新消息到达时，仅在用户已接近底部时平滑滚动跟随，不打断向上翻看历史。
    val sessionId = uiState.currentSession?.id
    var positionedToLatest by remember(sessionId) { mutableStateOf(false) }
    LaunchedEffect(sessionId, uiState.messages.size) {
        if (uiState.messages.isNotEmpty()) {
            val lastIndex = uiState.messages.lastIndex
            val firstVisibleIndex = listState.firstVisibleItemIndex
            if (!positionedToLatest) {
                snapshotFlow { listState.layoutInfo.totalItemsCount }
                    .first { it >= lastIndex + 1 }
                listState.scrollToItem(lastIndex)
                positionedToLatest = true
            } else if (firstVisibleIndex >= lastIndex - 1) {
                listState.animateScrollToItem(lastIndex)
            }
        }
    }

    // 显示上传成功提示
    LaunchedEffect(uiState.uploadState) {
        when (val state = uiState.uploadState) {
            is UploadState.Success -> {
                snackbarHostState.showSnackbar(
                    message = "文件上传成功: ${state.fileName}",
                    duration = SnackbarDuration.Short
                )
                viewModel.resetUploadState()
            }
            is UploadState.Error -> {
                snackbarHostState.showSnackbar(
                    message = "上传失败: ${state.message}",
                    duration = SnackbarDuration.Short
                )
            }
            else -> {}
        }
    }

    // 当前激活 persona 的显示数据（名字 + 头像）：跟随"正在查看的角色"
    val activePersonaInfo = remember(viewingPersona, personaUiState.activeFilename, personaUiState.personas, localAvatarMap) {
        extractActivePersonaInfo(personaUiState, localAvatarMap, viewingPersona)
    }

    Box(modifier = Modifier.fillMaxSize()) {
        // ========== 聊天界面（底层）==========
        Scaffold(
            containerColor = MaterialTheme.colorScheme.background.copy(alpha = 0f),
            contentWindowInsets = WindowInsets(0, 0, 0, 0),
            snackbarHost = {
                SnackbarHost(hostState = snackbarHostState) { data ->
                    Snackbar(
                        snackbarData = data,
                        containerColor = MaterialTheme.colorScheme.surfaceVariant,
                        contentColor = TextPrimary
                    )
                }
            },
            topBar = {
                ChatTopBar(
                    displayName = activePersonaInfo.first,
                    avatarUrl = activePersonaInfo.second,
                    avatarPath = activePersonaInfo.third,
                    avatarStorage = avatarStorage,
                    onBackClick = onBackClick,
                    onAvatarClick = openCompanionPanel
                )
            },
            bottomBar = {
                Column {
                    // 上传进度指示器
                    UploadProgressIndicator(
                        uploadState = uiState.uploadState,
                        modifier = Modifier.fillMaxWidth()
                    )

                    ChatBottomBar(
                        text = uiState.inputText,
                        onTextChange = { viewModel.updateInputText(it) },
                        onSend = { viewModel.sendMessage(it) },
                        onImagePick = { imagePickerLauncher.launch("image/*") },
                        onVoiceInput = {
                            // 点击麦克风：开始/停止录音切换
                            if (uiState.isRecording) {
                                viewModel.stopVoiceRecording()
                            } else {
                                // 先检查权限，没权限则请求
                                if (viewModel.hasRecordAudioPermission()) {
                                    viewModel.startVoiceRecording()
                                } else {
                                    recordAudioPermissionLauncher.launch(
                                        android.Manifest.permission.RECORD_AUDIO
                                    )
                                }
                            }
                        },
                        isTyping = uiState.isTyping,
                        isRecording = uiState.isRecording,
                        connectionState = uiState.connectionState
                    )
                }
            }
        ) { paddingValues ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues)
                    // 向左滑打开伴侣详情面板。
                    // 最左侧 12% 留给侧边栏，其余聊天区域都可触发。
                    // 方向锁定后详情页从右侧跟随手指进入，松手后才决定展开或收回。
                    .pointerInput(screenWidthPx, touchSlopPx, openVelocityThresholdPx) {
                        awaitEachGesture {
                            val down = awaitFirstDown(requireUnconsumed = false)
                            val startX = down.position.x
                            val startY = down.position.y
                            // 左边缘起手留给 MainActivity 内容根节点的手势仲裁，
                            // 避免与侧边栏右滑手势争抢方向。
                            if (startX <= screenWidthPx * 0.12f) return@awaitEachGesture
                            var decided = false
                            var lastX = startX
                            var lastTime = down.uptimeMillis
                            var velocity = 0f
                            var childConsumedHorizontalDrag = false
                            var openingDragStarted = false
                            while (true) {
                                val event = awaitPointerEvent()
                                val change = event.changes.firstOrNull() ?: break
                                val dx = change.position.x - startX
                                val dy = change.position.y - startY
                                val deltaX = change.position.x - lastX
                                // 只有表格/代码块/宽公式会显式声明手势所有权。
                                // 不再使用通用 isConsumed，避免 clickable/LazyColumn 屏蔽页面左滑。
                                if (horizontalContentGestureState.isActive) {
                                    childConsumedHorizontalDrag = true
                                }
                                val dt = (change.uptimeMillis - lastTime).toFloat().coerceAtLeast(1f)
                                if (abs(deltaX) > 0.5f) {
                                    velocity = deltaX / dt * 1000f
                                }
                                if (!decided && (abs(dx) > touchSlopPx || abs(dy) > touchSlopPx)) {
                                    // 左滑（dx < 0）且主要在水平方向，且面板未打开。
                                    if (dx < 0f && abs(dx) >= abs(dy) &&
                                        !showCompanionPanel && !childConsumedHorizontalDrag
                                    ) {
                                        // 面板已经停在右侧隐藏锚点，方向锁定后直接补上已走位移。
                                        showCompanionPanel = true
                                        companionPanelState.dispatchOpeningDelta(dx)
                                        openingDragStarted = true
                                        change.consume()
                                    }
                                    decided = true
                                } else if (openingDragStarted) {
                                    companionPanelState.dispatchOpeningDelta(deltaX)
                                    change.consume()
                                }
                                lastX = change.position.x
                                lastTime = change.uptimeMillis
                                if (event.changes.all { !it.pressed }) break
                            }
                            if (openingDragStarted) {
                                // AwaitPointerEventScope 是受限协程；吸附动画交给普通 UI 协程执行。
                                companionEditScope.launch {
                                    val opened = companionPanelState.settleOpeningDrag(
                                        releaseVelocityX = velocity,
                                        panelWidthPx = screenWidthPx,
                                        velocityThresholdPx = openVelocityThresholdPx
                                    )
                                    if (!opened) showCompanionPanel = false
                                }
                            }
                        }
                    }
            ) {
                // 双角色对话区域
                AnimatedVisibility(
                    visible = uiState.showPeerChat && uiState.peerChatMessages.isNotEmpty(),
                    enter = slideInVertically(initialOffsetY = { -it }) + fadeIn(),
                    exit = slideOutVertically(targetOffsetY = { -it }) + fadeOut()
                ) {
                    Column {
                        PeerChatHeader(
                            topic = uiState.peerChatTopic,
                            participant1 = "七濑澪",
                            participant2 = "Ling",
                            isActive = uiState.isPeerChatActive,
                            progress = if (uiState.peerChatMessages.isNotEmpty()) {
                                uiState.peerChatMessages.size.toFloat() / 10f
                            } else 0f,
                            onClose = { viewModel.togglePeerChat() }
                        )

                        PeerChatMessageList(
                            messages = uiState.peerChatMessages,
                            modifier = Modifier
                                .fillMaxWidth()
                                .heightIn(max = 200.dp)
                        )

                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(1.dp)
                                .background(Color(0x1AFFFFFF))
                        )
                    }
                }

                // 消息列表
                LazyColumn(
                    state = listState,
                    modifier = Modifier
                        .fillMaxSize()
                        .weight(1f),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    items(
                        count = uiState.messages.size,
                        key = { index -> uiState.messages[index].id }
                    ) { index ->
                        val message = uiState.messages[index]
                        val previousMessage = uiState.messages.getOrNull(index - 1)
                        val showSeparator = shouldShowTimeSeparator(
                            previousTimestamp = previousMessage?.timestamp,
                            currentTimestamp = message.timestamp
                        )
                        val isRetraction = !message.isUser && message.messageType == "retraction"
                        val isSystemNarration = !message.isUser && !isRetraction && (
                            message.text == "新话题已开启。" || message.text.contains("系统就绪")
                        )

                        Column {
                            if (showSeparator && !isSystemNarration && !isRetraction) {
                                TimeSeparator(timestamp = message.timestamp)
                            }

                            if (isSystemNarration) {
                                CenteredNarration(text = message.text)
                            } else {
                                CompositionLocalProvider(
                                    LocalHorizontalContentGestureState provides horizontalContentGestureState
                                ) {
                                    MessageBubble(
                                        message = MessageData(
                                            id = message.id,
                                            text = message.text,
                                            isUser = message.isUser,
                                            timestamp = message.timestamp,
                                            imageUrl = message.imageUrl,
                                            isPlaying = uiState.playingMessageId == message.id,
                                            emotion = message.emotion,
                                            variantIndex = message.variantIndex,
                                            variantCount = message.variantCount,
                                            messageType = if (isRetraction) MessageType.RETRACTION else if (message.isUser) MessageType.USER else MessageType.AI
                                        ),
                                        onPlayTTS = { viewModel.toggleTTS(it) },
                                        onCopy = { viewModel.copyMessage(it) },
                                        onDelete = { viewModel.deleteMessage(it) },
                                        onRegenerate = { viewModel.regenerateMessage(it) },
                                        onEdit = { id, text ->
                                            editingMessageId = id
                                            editingMessageText = text
                                        },
                                        onPreviousVariant = { viewModel.selectMessageVariant(it, -1) },
                                        onNextVariant = { viewModel.selectMessageVariant(it, 1) }
                                    )
                                }
                            }
                        }
                    }

                    if (uiState.showTypingIndicator) {
                        item {
                            TypingIndicator(
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)
                            )
                        }
                    }

                    if (uiState.messages.isEmpty() && !uiState.isLoading) {
                        item {
                            when (uiState.loadingState) {
                                is LoadingState.NotLoaded -> {
                                    EmptyChatState(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(vertical = 48.dp)
                                    )
                                }
                                is LoadingState.Loading -> { /* 等待数据 */ }
                                is LoadingState.Loaded -> { /* 已连接无消息 */ }
                            }
                        }
                    }
                }
            }
        }

        // ========== 伴侣详情全屏覆盖（点击顶部头像打开，从右侧滑入）==========
        // 拦截返回键/全面屏手势滑动返回：只关闭覆盖层，不 popBackStack 回会话列表
        BackHandler(enabled = showCompanionPanel) {
            closeCompanionPanel()
        }
        // 面板常驻组合树并停在屏幕右侧隐藏锚点，使聊天页手势可以同步驱动首帧位移。
        PullableDismissPanel(
            state = companionPanelState,
            onDismissed = { showCompanionPanel = false },
            gesturesEnabled = companionDismissGestureEnabled
        ) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.surface
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .statusBarsPadding()
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 8.dp, vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            IconButton(onClick = closeCompanionPanel) {
                                Icon(
                                    Icons.AutoMirrored.Filled.ArrowBack,
                                    contentDescription = "返回",
                                    tint = TextPrimary
                                )
                            }
                            Text(
                                text = "伴侣详情",
                                style = MaterialTheme.typography.titleMedium,
                                color = TextPrimary,
                                fontWeight = FontWeight.Bold,
                                modifier = Modifier.weight(1f)
                            )
                            // 编辑资料：自定义昵称 / 头像
                            IconButton(
                                onClick = {
                                    val info = extractActivePersonaInfo(personaUiState, localAvatarMap)
                                    val role = runCatching {
                                        personaUiState.personas.firstOrNull { el ->
                                            el.jsonObject["filename"]?.jsonPrimitive?.content ==
                                                personaUiState.activeFilename
                                        }?.jsonObject?.get("role")?.jsonPrimitive?.content
                                    }.getOrNull() ?: ""
                                    editingItem = ConversationItem(
                                        filename = personaUiState.activeFilename,
                                        displayName = info.first,
                                        role = role,
                                        description = "",
                                        avatarUrl = info.second,
                                        localAvatarPath = info.third,
                                        lastMessagePreview = null,
                                        lastMessageAt = null,
                                        isActive = true
                                    )
                                }
                            ) {
                                Icon(
                                    Icons.Filled.Edit,
                                    contentDescription = "编辑资料",
                                    tint = TextPrimary
                                )
                            }
                        }

                        CompanionScreen(
                            statusUiState = statusUiState,
                            personaUiState = personaUiState,
                            memoryUiState = memoryUiState,
                            availableModels = settingsUiState.availableModels,
                            selectedModel = settingsUiState.selectedModel,
                            modelLoading = settingsUiState.isLoadingModels,
                            modelError = settingsUiState.modelLoadError,
                            onModelSelected = { id ->
                                settingsUiState.availableModels
                                    .firstOrNull { it.id == id }
                                    ?.let { settingsViewModel.selectModel(it) }
                            },
                            viewingFilename = viewingPersona,
                            onRefreshStatus = statusViewModel::refreshStatus,
                            onWakeCompanion = statusViewModel::wakeCompanion,
                            onInterruptCompanion = statusViewModel::interruptCompanion,
                            onSkipCompanionActivity = statusViewModel::skipCompanionActivity,
                            onDismissGestureEnabledChange = {
                                companionDismissGestureEnabled = it
                            },
                            onSwitchPersona = { fn ->
                                // 真正切换人设：调后端 selectPersona（PersonaViewModel.switchPersona）
                                personaViewModel.switchPersona(fn)
                                // 同步"正在查看的角色"，让 UI 高亮立即跟随
                                viewModel.setViewingPersona(fn)
                            },
                            onSearchMemory = memoryViewModel::search,
                            onMemoryTypeFilterChange = memoryViewModel::setTypeFilter,
                            onToggleImportantOnly = memoryViewModel::toggleImportantOnly,
                            onMemorySortOrderChange = memoryViewModel::setSortOrder,
                            onDeleteMemory = memoryViewModel::deleteMemory,
                            onToggleImportant = memoryViewModel::toggleImportant,
                            onConfirmDeleteMemory = memoryViewModel::confirmDelete,
                            onCancelDeleteMemory = memoryViewModel::cancelDelete,
                            onClearMemoryFilters = memoryViewModel::clearFilters,
                            onOpenMemoryDetail = memoryViewModel::openMemoryDetail,
                            onCloseMemoryDetail = memoryViewModel::closeMemoryDetail
                        )
                    }

                    // 编辑资料弹窗：自定义昵称 / 头像（位于伴侣详情面板内）
                    editingItem?.let { item ->
                        PersonaEditSheet(
                            item = item,
                            avatarStorage = avatarStorage,
                            onDismiss = { editingItem = null },
                            onSaveName = { newName ->
                                companionEditScope.launch {
                                    localMeta.setCustomName(item.filename, newName)
                                }
                                personaViewModel.loadPersonas()
                            },
                            onPickAvatar = { uri ->
                                companionEditScope.launch { localMeta.setAvatar(item.filename, uri) }
                                personaViewModel.loadPersonas()
                            },
                            onClearAvatar = {
                                companionEditScope.launch { localMeta.clearAvatar(item.filename) }
                                personaViewModel.loadPersonas()
                            }
                        )
                    }
                }
        }
    }
}

/**
 * 从 PersonaUiState 提取当前激活 persona 的显示信息。
 *
 * @return Triple(显示名, 网络头像URL, 本地头像文件名)
 */
private fun extractActivePersonaInfo(
    personaUiState: com.aveline.ai.mobile.presentation.persona.PersonaUiState,
    localAvatarMap: Map<String, String>,
    viewingFilename: String? = null
): Triple<String, String?, String?> {
    // 优先用"正在查看的角色"（进哪个角色的聊天就显示哪个，纯展示，不切后端人设）
    val activeFilename = (viewingFilename ?: personaUiState.activeFilename)
    if (activeFilename.isBlank()) return Triple("聊天", null, null)

    // 从 personas 列表找当前 persona 的 name / avatar_url
    val personaObj = personaUiState.personas.firstOrNull { element ->
        runCatching {
            element.jsonObject["filename"]?.jsonPrimitive?.content == activeFilename
        }.getOrDefault(false)
    }?.jsonObject

    val name = personaObj?.get("name")?.jsonPrimitive?.content ?: "聊天"
    val avatarUrl = personaObj?.get("avatar_url")?.jsonPrimitive?.content
    val localAvatarPath = localAvatarMap[activeFilename]
    return Triple(name, avatarUrl, localAvatarPath)
}

/**
 * 聊天顶部栏：返回按钮 + 头像 + 昵称
 */
@Composable
private fun ChatTopBar(
    displayName: String,
    avatarUrl: String?,
    avatarPath: String?,
    avatarStorage: PersonaAvatarStorage,
    onBackClick: () -> Unit,
    onAvatarClick: () -> Unit
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = Color.Transparent,
        tonalElevation = 0.dp
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .statusBarsPadding()
                .padding(horizontal = 8.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(onClick = onBackClick) {
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = "返回",
                    tint = TextPrimary
                )
            }

            // 中部：头像 + 昵称（点击头像打开伴侣详情）
            Row(
                modifier = Modifier
                    .weight(1f)
                    .clickable { onAvatarClick() },
                verticalAlignment = Alignment.CenterVertically
            ) {
                ChatPersonaAvatar(
                    displayName = displayName,
                    avatarUrl = avatarUrl,
                    avatarPath = avatarPath,
                    avatarStorage = avatarStorage
                )
                Spacer(modifier = Modifier.width(10.dp))
                Text(
                    text = displayName,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Medium,
                    color = TextPrimary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
    }
}

@Composable
private fun ChatPersonaAvatar(
    displayName: String,
    avatarUrl: String?,
    avatarPath: String?,
    avatarStorage: PersonaAvatarStorage
) {
    val context = LocalContext.current
    Box(
        modifier = Modifier
            .size(36.dp)
            .clip(CircleShape)
            .background(OverlayLight),
        contentAlignment = Alignment.Center
    ) {
        when {
            !avatarPath.isNullOrBlank() -> {
                val file = avatarStorage.getAvatarFile(avatarPath)
                if (file != null) {
                    AsyncImage(
                        model = ImageRequest.Builder(context)
                            .data(file)
                            .crossfade(true)
                            .build(),
                        contentDescription = displayName,
                        modifier = Modifier
                            .size(36.dp)
                            .clip(CircleShape),
                        contentScale = ContentScale.Crop
                    )
                } else {
                    AvatarTextFallback(name = displayName, size = 36)
                }
            }
            !avatarUrl.isNullOrBlank() -> {
                AsyncImage(
                    model = ImageRequest.Builder(context)
                        .data(avatarUrl)
                        .crossfade(true)
                        .build(),
                    contentDescription = displayName,
                    modifier = Modifier
                        .size(36.dp)
                        .clip(CircleShape),
                    contentScale = ContentScale.Crop
                )
            }
            else -> AvatarTextFallback(name = displayName, size = 36)
        }
    }
}

@Composable
private fun AvatarTextFallback(name: String, size: Int) {
    val initial = name.firstOrNull()?.toString() ?: "?"
    Box(
        modifier = Modifier
            .size(size.dp)
            .clip(CircleShape)
            .background(Primary.copy(alpha = 0.3f)),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = initial,
            fontSize = (size * 0.45).sp,
            fontWeight = FontWeight.Bold,
            color = Color.White
        )
    }
}

@Composable
private fun CenteredNarration(text: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 10.dp, horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center
    ) {
        Box(
            modifier = Modifier
                .weight(1f)
                .height(1.dp)
                .background(
                    androidx.compose.ui.graphics.Brush.horizontalGradient(
                        listOf(
                            androidx.compose.ui.graphics.Color.Transparent,
                            androidx.compose.ui.graphics.Color(0x33FFFFFF),
                            androidx.compose.ui.graphics.Color.Transparent
                        )
                    )
                )
        )
        Text(
            text = text.removePrefix("（").removePrefix("(").removeSuffix("）").removeSuffix(")"),
            color = TextSecondary.copy(alpha = 0.6f),
            fontSize = 12.sp,
            fontWeight = FontWeight.Light,
            letterSpacing = 1.2.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(horizontal = 12.dp)
        )
        Box(
            modifier = Modifier
                .weight(1f)
                .height(1.dp)
                .background(
                    androidx.compose.ui.graphics.Brush.horizontalGradient(
                        listOf(
                            androidx.compose.ui.graphics.Color.Transparent,
                            androidx.compose.ui.graphics.Color(0x33FFFFFF),
                            androidx.compose.ui.graphics.Color.Transparent
                        )
                    )
                )
        )
    }
}

/**
 * 聊天界面底部栏：语音输入 + 输入框 + "+"(打开相册) / 发送按钮
 */
@Composable
private fun ChatBottomBar(
    text: String,
    onTextChange: (String) -> Unit,
    onSend: (String) -> Unit,
    onImagePick: () -> Unit,
    onVoiceInput: () -> Unit,
    isTyping: Boolean,
    isRecording: Boolean,
    @Suppress("UNUSED_PARAMETER") connectionState: WebSocketManager.ConnectionState = WebSocketManager.ConnectionState.DISCONNECTED,
    modifier: Modifier = Modifier
) {
    InputArea(
        text = text,
        onTextChange = onTextChange,
        onSend = { onSend(text) },
        onAttach = onImagePick, // "+" 号直接打开相册
        onImagePick = onImagePick,
        onVoiceInput = onVoiceInput,
        isTyping = isTyping,
        isRecording = isRecording,
        enabled = true,
        placeholder = "输入消息...",
        modifier = modifier
    )
}

/**
 * 上传进度指示器
 */
@Composable
private fun UploadProgressIndicator(
    uploadState: UploadState,
    modifier: Modifier = Modifier
) {
    AnimatedVisibility(
        visible = uploadState is UploadState.Uploading,
        enter = fadeIn() + slideInVertically(),
        exit = fadeOut() + slideOutVertically(),
        modifier = modifier
    ) {
        when (uploadState) {
            is UploadState.Uploading -> {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
                        .padding(horizontal = 16.dp, vertical = 8.dp)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.primary
                        )

                        Spacer(modifier = Modifier.width(8.dp))

                        Text(
                            text = "正在上传: ${uploadState.fileName}",
                            style = MaterialTheme.typography.labelMedium,
                            color = TextSecondary
                        )

                        Spacer(modifier = Modifier.weight(1f))

                        Text(
                            text = "${(uploadState.progress * 100).toInt()}%",
                            style = MaterialTheme.typography.labelMedium,
                            color = TextSecondary
                        )
                    }

                    Spacer(modifier = Modifier.height(4.dp))

                    LinearProgressIndicator(
                        progress = { uploadState.progress },
                        modifier = Modifier.fillMaxWidth(),
                        color = MaterialTheme.colorScheme.primary,
                        trackColor = MaterialTheme.colorScheme.surfaceVariant
                    )
                }
            }
            else -> {}
        }
    }
}

/**
 * 空聊天状态
 */
@Composable
private fun EmptyChatState(
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(
            text = "开始和 Aveline 聊天吧",
            style = MaterialTheme.typography.titleMedium,
            color = TextSecondary
        )

        Spacer(modifier = Modifier.height(8.dp))

        Text(
            text = "发送消息开始对话",
            style = MaterialTheme.typography.bodyMedium,
            color = TextSecondary.copy(alpha = 0.7f)
        )
    }
}
