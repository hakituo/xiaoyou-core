package com.aveline.ai.mobile.presentation.chat

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.aveline.ai.mobile.data.local.storage.PersonaAvatarStorage
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.presentation.companion.CompanionScreen
import com.aveline.ai.mobile.presentation.components.PullableDismissPanel
import com.aveline.ai.mobile.presentation.components.PullableDismissPanelState
import com.aveline.ai.mobile.presentation.conversations.ConversationItem
import com.aveline.ai.mobile.presentation.conversations.PersonaEditSheet
import com.aveline.ai.mobile.presentation.memory.MemoryViewModel
import com.aveline.ai.mobile.presentation.persona.PersonaUiState
import com.aveline.ai.mobile.presentation.persona.PersonaViewModel
import com.aveline.ai.mobile.presentation.settings.SettingsViewModel
import com.aveline.ai.mobile.presentation.status.StatusViewModel
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import kotlinx.coroutines.launch

/**
 * 伴侣详情全屏覆盖面板（点击聊天页顶栏头像打开，从右侧滑入）。
 *
 * 模型 Tab 使用 ChatViewModel 的 role 级状态，不再复用 SettingsViewModel 的应用级模型状态。
 */
@Composable
fun ChatCompanionPanel(
    chatViewModel: ChatViewModel,
    personaViewModel: PersonaViewModel,
    statusViewModel: StatusViewModel,
    memoryViewModel: MemoryViewModel,
    @Suppress("UNUSED_PARAMETER") settingsViewModel: SettingsViewModel,
    personaUiState: PersonaUiState,
    localAvatarMap: Map<String, String>,
    viewingFilename: String?,
    panelState: PullableDismissPanelState,
    visible: Boolean,
    gesturesEnabled: Boolean,
    avatarStorage: PersonaAvatarStorage,
    localMeta: PersonaLocalMetaRepository,
    onRequestClose: () -> Unit,
    onDismissed: () -> Unit,
    onDismissGestureEnabledChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier
) {
    val statusUiState by statusViewModel.uiState.collectAsStateWithLifecycle()
    val memoryUiState by memoryViewModel.uiState.collectAsStateWithLifecycle()
    val roleModels by chatViewModel.availableRoleModels.collectAsStateWithLifecycle()
    val selectedRoleModel by chatViewModel.selectedRoleModel.collectAsStateWithLifecycle()
    val roleModelLoading by chatViewModel.roleModelLoading.collectAsStateWithLifecycle()
    val roleModelError by chatViewModel.roleModelError.collectAsStateWithLifecycle()
    val editScope = rememberCoroutineScope()
    var editingItem by remember { mutableStateOf<ConversationItem?>(null) }

    // 刷新必须绑定“详情真正可见”，不能只绑头像点击回调：
    // 左滑打开同样会把面板设为 visible。显式传入当前 persona，避免面板可见与
    // ChatScreen 控制上下文 LaunchedEffect 同帧更新时误刷上一个角色。
    LaunchedEffect(visible, viewingFilename) {
        if (visible) {
            statusViewModel.refreshStatusForPersona(viewingFilename)
        }
    }

    BackHandler(enabled = visible) {
        onRequestClose()
    }

    PullableDismissPanel(
        state = panelState,
        onDismissed = onDismissed,
        gesturesEnabled = gesturesEnabled
    ) {
        Surface(
            modifier = modifier.fillMaxSize(),
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
                    IconButton(onClick = onRequestClose) {
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
                    IconButton(
                        onClick = {
                            val info = resolveActivePersonaInfo(personaUiState, localAvatarMap)
                            editingItem = ConversationItem(
                                filename = personaUiState.activeFilename,
                                displayName = info.displayName,
                                role = resolvePersonaRole(personaUiState, personaUiState.activeFilename),
                                description = "",
                                avatarUrl = info.avatarUrl,
                                localAvatarPath = info.localAvatarPath,
                                lastMessagePreview = null,
                                lastMessageAt = null,
                                unreadCount = 0,
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
                    availableModels = roleModels,
                    selectedModel = selectedRoleModel,
                    modelLoading = roleModelLoading,
                    modelError = roleModelError,
                    onModelSelected = chatViewModel::selectModelForCurrentRole,
                    viewingFilename = viewingFilename,
                    onRefreshStatus = statusViewModel::refreshStatus,
                    onWakeCompanion = statusViewModel::wakeCompanion,
                    onInterruptCompanion = statusViewModel::interruptCompanion,
                    onSkipCompanionActivity = statusViewModel::skipCompanionActivity,
                    onDismissGestureEnabledChange = onDismissGestureEnabledChange,
                    onSwitchPersona = { fn ->
                        personaViewModel.switchPersona(fn) { selected ->
                            chatViewModel.confirmPersonaSelection(selected)
                        }
                    },
                    onSelectVoice = personaViewModel::selectVoice,
                    onResetVoice = { fn -> personaViewModel.selectVoice(fn, "") },
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

            editingItem?.let { item ->
                PersonaEditSheet(
                    item = item,
                    avatarStorage = avatarStorage,
                    onDismiss = { editingItem = null },
                    onSaveName = { newName ->
                        editScope.launch {
                            localMeta.setCustomName(item.filename, newName)
                        }
                        personaViewModel.loadPersonas()
                    },
                    onPickAvatar = { uri ->
                        editScope.launch { localMeta.setAvatar(item.filename, uri) }
                        personaViewModel.loadPersonas()
                    },
                    onClearAvatar = {
                        editScope.launch { localMeta.clearAvatar(item.filename) }
                        personaViewModel.loadPersonas()
                    },
                    voices = personaUiState.voiceNames,
                    selectedVoice = personaUiState.personaVoiceOverrides[item.filename]
                        ?: personaUiState.personaDefaultVoices[item.filename].orEmpty(),
                    isVoiceOverridden = personaUiState.personaVoiceOverrides.containsKey(item.filename),
                    onSelectVoice = { voice -> personaViewModel.selectVoice(item.filename, voice) },
                    onResetVoice = { personaViewModel.selectVoice(item.filename, "") }
                )
            }
        }
    }
}
