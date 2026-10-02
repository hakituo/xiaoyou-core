package com.aveline.ai.mobile.presentation.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.data.local.storage.PersonaAvatarStorage
import com.aveline.ai.mobile.presentation.components.PersonaAvatar
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextPrimary

/** 聊天页顶栏头像边长。 */
private val CHAT_TOP_BAR_AVATAR_SIZE = 36.dp

/** 聊天页顶栏头像的首字母字号（约为边长的 45%）。 */
private val CHAT_TOP_BAR_AVATAR_FONT_SIZE = 16.sp

/**
 * 聊天顶部栏：返回按钮 + 头像 + 昵称。
 *
 * 整块（头像 + 昵称）可点击，用于打开伴侣详情面板。
 *
 * @param displayName 标题展示名（昵称 > 角色名，见 [resolveActivePersonaInfo]）
 * @param avatarUrl 后端下发的头像地址
 * @param avatarPath 本地自定义头像文件名
 * @param unreadFromOthers 其他角色的主动消息未读总数，>0 时返回键右上角亮小圆点
 */
@Composable
fun ChatTopBar(
    displayName: String,
    avatarUrl: String?,
    avatarPath: String?,
    avatarStorage: PersonaAvatarStorage,
    onBackClick: () -> Unit,
    onAvatarClick: () -> Unit,
    unreadFromOthers: Int = 0
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
            // 返回键 + 其他角色未读小圆点：与列表徽章同一配色（品牌天蓝），
            // 融合在返回键右上角，正在聊天时也能知道有别的角色找
            Box {
                IconButton(onClick = onBackClick) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                        contentDescription = "返回",
                        tint = TextPrimary
                    )
                }
                if (unreadFromOthers > 0) {
                    Box(
                        modifier = Modifier
                            .align(Alignment.TopEnd)
                            .offset(x = 4.dp, y = 6.dp)
                            .size(9.dp)
                            .background(Primary, CircleShape)
                    )
                }
            }

            // 中部：头像 + 昵称（点击头像打开伴侣详情）
            Row(
                modifier = Modifier
                    .weight(1f)
                    .clickable { onAvatarClick() },
                verticalAlignment = Alignment.CenterVertically
            ) {
                PersonaAvatar(
                    displayName = displayName,
                    avatarUrl = avatarUrl,
                    localAvatarPath = avatarPath,
                    avatarStorage = avatarStorage,
                    size = CHAT_TOP_BAR_AVATAR_SIZE,
                    fallbackFontSize = CHAT_TOP_BAR_AVATAR_FONT_SIZE
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
