package com.aveline.ai.mobile.presentation.conversations

import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.background
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.data.local.storage.PersonaAvatarStorage
import com.aveline.ai.mobile.presentation.components.ModuleHeader
import com.aveline.ai.mobile.presentation.components.PersonaAvatar
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.StatusOnline
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 会话列表页（QQ 风格）
 *
 * 显示所有 persona，每行：头像 + 昵称 + 描述 + 当前激活角标。
 * - 点击 → 切换 persona + 进聊天页
 * - 长按 → 弹出编辑面板（改昵称、改头像）
 *
 * @param uiState 列表 UI 状态
 * @param onReload 重新加载（仅在列表为空时以"重新加载"按钮出现，不是常驻刷新按钮）
 * @param onOpenChat 打开聊天页回调（传 role 角色名 + 当前列表显示用的 persona filename +
 *                   displayName 展示名，让聊天页首帧就能显示正确标题）
 * @param onUpdateDisplayName 改昵称
 * @param onUpdateAvatar 改头像（传 Uri，存储在 ViewModel 内做）
 * @param onClearAvatar 恢复默认头像
 * @param onClearError 清除错误
 * @param avatarStorage 头像存储（用于加载本地图片）
 */
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
@Composable
fun ConversationListScreen(
    uiState: ConversationListUiState,
    onReload: () -> Unit,
    onOpenChat: (String, String, String) -> Unit,
    onUpdateDisplayName: (String, String?) -> Unit,
    onUpdateAvatar: (String, Uri) -> Unit,
    onClearAvatar: (String) -> Unit,
    onClearError: () -> Unit,
    avatarStorage: PersonaAvatarStorage,
    /** 可选语音音色名（后端 /media/voices）。空列表则不显示音色区（例如伴侣详情面板入口）。 */
    voiceNames: List<String> = emptyList(),
    /** persona filename -> 用户手选的音色名（本地覆盖，优先级高于角色默认）。 */
    personaVoiceOverrides: Map<String, String> = emptyMap(),
    /** persona filename -> 后端下发的角色默认音色（default_voice）。 */
    personaDefaultVoices: Map<String, String> = emptyMap(),
    /** 手选音色：(persona filename, 音色名)。 */
    onSelectVoice: (String, String) -> Unit = { _, _ -> },
    /** 恢复跟随角色默认音色：(persona filename)。 */
    onResetVoice: (String) -> Unit = {}
) {
    // 当前编辑的 persona（长按弹出编辑面板）
    var editingItem by remember { mutableStateOf<ConversationItem?>(null) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        // 不放置常驻刷新按钮：会话列表在 ViewModel init 时自动拉一次，本地改昵称/头像后
        // 也会自动重渲染（见 ConversationListViewModel.init），不需要用户手动点。
        ModuleHeader(title = "消息")

        // 错误条
        uiState.error?.takeIf { it.isNotBlank() }?.let { error ->
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 4.dp),
                color = MaterialTheme.colorScheme.errorContainer,
                shape = RoundedCornerShape(8.dp)
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = error,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onErrorContainer,
                        modifier = Modifier.weight(1f)
                    )
                    Text(
                        text = "关闭",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onErrorContainer,
                        modifier = Modifier
                            .clickable { onClearError() }
                            .padding(horizontal = 8.dp)
                    )
                }
            }
        }

        // 加载中（首次）
        if (uiState.isLoading && uiState.items.isEmpty()) {
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center
            ) {
                CircularProgressIndicator()
            }
        } else if (uiState.items.isEmpty()) {
            // 空态：可能是真的没有 persona，也可能是首次加载失败（启动瞬间后端未就绪 / 网络抖动）。
            // 常驻刷新按钮已移除，这里必须留一个"按需重试"入口：否则错误条一被关掉，
            // 列表就永久停在空态且无从恢复（init 之后只有本地 meta 变化才会再触发 refresh）。
            val loadError = uiState.error?.takeIf { it.isNotBlank() }
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 24.dp, vertical = 48.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Text(
                    text = "暂无角色",
                    style = MaterialTheme.typography.titleMedium,
                    color = TextSecondary
                )
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "去设置页添加 persona",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextTertiary
                )
                if (loadError != null) {
                    Spacer(modifier = Modifier.height(16.dp))
                    Text(
                        text = "加载失败：$loadError",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                        textAlign = TextAlign.Center
                    )
                }
                Spacer(modifier = Modifier.height(16.dp))
                TextButton(onClick = onReload) {
                    Text("重新加载")
                }
            }
        } else {
            // 只展示角色（每个角色一行，不展开 persona）
            // 点击角色 → 进 Chat（带 role 参数）；ChatScreen 内部选该角色的激活 persona
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(vertical = 8.dp)
            ) {
                items(
                    items = uiState.roleItems,
                    key = { it.role }
                ) { roleItem ->
                    RoleRow(
                        roleItem = roleItem,
                        avatarStorage = avatarStorage,
                        onClick = {
                            onOpenChat(
                                roleItem.role,
                                roleItem.activeFilename,
                                roleItem.displayName
                            )
                        },
                        onLongClick = {
                            // 长按编辑：把 RoleItem 转成 ConversationItem 传给 PersonaEditSheet
                            // 编辑的是该角色的代表 persona（activeFilename）
                            editingItem = ConversationItem(
                                filename = roleItem.activeFilename,
                                displayName = roleItem.displayName,
                                role = roleItem.role,
                                description = "",
                                avatarUrl = roleItem.avatarUrl,
                                localAvatarPath = roleItem.localAvatarPath,
                                lastMessagePreview = null,
                                lastMessageAt = null,
                                unreadCount = 0,
                                isActive = roleItem.isActive
                            )
                        }
                    )
                }
            }
        }
    }

    // 编辑面板
    editingItem?.let { item ->
        PersonaEditSheet(
            item = item,
            avatarStorage = avatarStorage,
            onDismiss = { editingItem = null },
            onSaveName = { newName ->
                onUpdateDisplayName(item.filename, newName)
            },
            onPickAvatar = { uri ->
                onUpdateAvatar(item.filename, uri)
            },
            onClearAvatar = {
                onClearAvatar(item.filename)
            },
            voices = voiceNames,
            // 手选优先；没手选就显示该角色后端下发的默认音色，用户能看到当前实际用哪个
            selectedVoice = personaVoiceOverrides[item.filename]
                ?: personaDefaultVoices[item.filename].orEmpty(),
            isVoiceOverridden = personaVoiceOverrides.containsKey(item.filename),
            onSelectVoice = { voice -> onSelectVoice(item.filename, voice) },
            onResetVoice = { onResetVoice(item.filename) }
        )
    }
}

/**
 * 角色级别会话行：显示一个角色（不展开 persona）。
 *
 * - 左侧头像（角色激活 persona 的头像）
 * - 中部角色名 + 最新消息预览
 * - 右侧时间 + "当前" 标签（如果是激活角色）
 */
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
@Composable
private fun RoleRow(
    roleItem: RoleItem,
    avatarStorage: PersonaAvatarStorage,
    onClick: () -> Unit,
    onLongClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(
                onClick = onClick,
                onLongClick = onLongClick
            )
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        // 头像 + 未读徽章
        Box {
            RoleAvatar(
                item = roleItem,
                avatarStorage = avatarStorage,
                modifier = Modifier.size(48.dp)
            )
            if (roleItem.unreadCount > 0) {
                UnreadBadge(
                    count = roleItem.unreadCount,
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .offset(x = 6.dp, y = (-2).dp)
                )
            }
        }

        Spacer(modifier = Modifier.width(12.dp))

        // 中部：角色名 + 预览
        Column(modifier = Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = roleItem.displayName,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Medium,
                    color = TextPrimary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false)
                )
                roleItem.lastMessageAt?.let { ts ->
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = formatRelativeTime(ts),
                        style = MaterialTheme.typography.labelSmall,
                        color = TextTertiary,
                        maxLines = 1
                    )
                }
            }
            val subtitle = roleItem.lastMessagePreview?.takeIf { it.isNotBlank() }
            if (!subtitle.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(2.dp))
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
    }
}

/**
 * 未读徽章：品牌色实心胶囊 + 深色数字（QQ 徽章的形态，不用红色）。
 *
 * 配色说明：红色在本应用里已被"离线/错误"语义占用，而且高饱和红与整体
 * 低饱和深色配色冲突；这里用 Primary（品牌天蓝）做底、Background 深色做字，
 * 与 App 主题同源，深色字在天蓝上对比度也足够。
 */
@Composable
private fun UnreadBadge(count: Int, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .background(Primary, RoundedCornerShape(50))
            .padding(horizontal = 5.dp, vertical = 1.dp)
    ) {
        Text(
            text = if (count > 99) "99+" else count.toString(),
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Bold,
            color = Background,
            maxLines = 1
        )
    }
}

/**
 * 单个会话行
 */
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
@Composable
private fun ConversationRow(
    item: ConversationItem,
    avatarStorage: PersonaAvatarStorage,
    onClick: () -> Unit,
    onLongClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(
                onClick = onClick,
                onLongClick = onLongClick
            )
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        // 头像：本地图片优先 → 网络 URL → emoji 兜底
        ConversationAvatar(item = item, avatarStorage = avatarStorage)

        Spacer(modifier = Modifier.width(12.dp))

            // 中部：昵称 + 预览/描述
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = item.displayName,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Medium,
                        color = TextPrimary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f, fill = false)
                    )
                    if (item.isActive) {
                        Spacer(modifier = Modifier.width(6.dp))
                        Surface(
                            shape = RoundedCornerShape(8.dp),
                            color = StatusOnline.copy(alpha = 0.2f)
                        ) {
                            Text(
                                text = "当前",
                                style = MaterialTheme.typography.labelSmall,
                                color = StatusOnline,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                            )
                        }
                    }
                    // 右侧时间（"X 分钟前"），无消息则不显示
                    item.lastMessageAt?.let { ts ->
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = formatRelativeTime(ts),
                            style = MaterialTheme.typography.labelSmall,
                            color = TextTertiary,
                            maxLines = 1
                        )
                    }
                }
                // 副标题：最后一条消息预览优先，无则显示 persona.description
                val subtitle = item.lastMessagePreview?.takeIf { it.isNotBlank() }
                    ?: item.description
                if (subtitle.isNotBlank()) {
                    Spacer(modifier = Modifier.height(2.dp))
                    Text(
                        text = subtitle,
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }

        // 右侧：编辑按钮（提示长按也可）
        Icon(
            imageVector = Icons.Default.Edit,
            contentDescription = "长按编辑",
            tint = TextTertiary,
            modifier = Modifier.size(16.dp)
        )
    }
}

/**
 * 会话头像：本地图片 → 网络 URL → 首字母兜底（实现见 [PersonaAvatar]）
 */
@Composable
private fun ConversationAvatar(
    item: ConversationItem,
    avatarStorage: PersonaAvatarStorage,
    modifier: Modifier = Modifier
) {
    PersonaAvatar(
        displayName = item.displayName,
        avatarUrl = item.avatarUrl,
        localAvatarPath = item.localAvatarPath,
        avatarStorage = avatarStorage,
        modifier = modifier
    )
}

/**
 * 角色级别头像（与 ConversationAvatar 视觉一致，但用 RoleItem 数据）
 */
@Composable
private fun RoleAvatar(
    item: RoleItem,
    avatarStorage: PersonaAvatarStorage,
    modifier: Modifier = Modifier
) {
    PersonaAvatar(
        displayName = item.displayName,
        avatarUrl = item.avatarUrl,
        localAvatarPath = item.localAvatarPath,
        avatarStorage = avatarStorage,
        modifier = modifier
    )
}

/**
 * 把时间戳格式化为相对时间（"X 分钟前 / X 小时前 / 昨天 / M-D）。
 *
 * - < 1 分钟：刚刚
 * - < 1 小时：X 分钟前
 * - < 24 小时：X 小时前
 * - < 48 小时：昨天
 * - 更早：M月D日
 */
private fun formatRelativeTime(timestampMillis: Long): String {
    val now = System.currentTimeMillis()
    val diff = now - timestampMillis
    if (diff < 60_000L) return "刚刚"
    val minutes = diff / 60_000L
    if (minutes < 60) return "${minutes}分钟前"
    val hours = minutes / 60
    if (hours < 24) return "${hours}小时前"
    if (hours < 48) return "昨天"
    val cal = java.util.Calendar.getInstance().apply {
        timeInMillis = timestampMillis
    }
    val month = cal.get(java.util.Calendar.MONTH) + 1
    val day = cal.get(java.util.Calendar.DAY_OF_MONTH)
    return "${month}月${day}日"
}
