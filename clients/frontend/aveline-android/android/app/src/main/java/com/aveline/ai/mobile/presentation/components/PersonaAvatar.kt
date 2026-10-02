package com.aveline.ai.mobile.presentation.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.aveline.ai.mobile.data.local.storage.PersonaAvatarStorage
import com.aveline.ai.mobile.presentation.theme.OverlayLight
import com.aveline.ai.mobile.presentation.theme.Primary

/**
 * persona 头像：本地自定义头像 > 网络 URL > 昵称首字符兜底。
 *
 * 此前会话列表（52dp）、聊天页顶栏（36dp）、资料编辑页（96dp）各写了一份
 * 结构完全相同的实现，只有尺寸和字号不同。同一套「本地 > 网络 > 首字母」逻辑
 * 散落三处容易各自漂移，统一收敛到这里，调用方只传尺寸。
 *
 * @param localAvatarPath 本地自定义头像文件名（由 [PersonaAvatarStorage] 解析成文件）
 * @param avatarUrl 后端下发的头像地址
 * @param displayName 展示名，用于无障碍描述与首字母兜底
 * @param size 头像边长
 * @param fallbackFontSize 首字母字号，默认按 [size] 的 ~42% 取值
 */
@Composable
fun PersonaAvatar(
    displayName: String,
    avatarUrl: String?,
    localAvatarPath: String?,
    avatarStorage: PersonaAvatarStorage,
    modifier: Modifier = Modifier,
    size: Dp = DEFAULT_AVATAR_SIZE,
    fallbackFontSize: TextUnit = DEFAULT_AVATAR_FONT_SIZE
) {
    val context = LocalContext.current
    Box(
        modifier = modifier
            .size(size)
            .clip(CircleShape)
            .background(OverlayLight),
        contentAlignment = Alignment.Center
    ) {
        when {
            // 1. 本地自定义头像（文件可能已被清理，取不到时回退到兜底）
            !localAvatarPath.isNullOrBlank() -> {
                val file = avatarStorage.getAvatarFile(localAvatarPath)
                if (file != null) {
                    AsyncImage(
                        model = ImageRequest.Builder(context)
                            .data(file)
                            .crossfade(true)
                            .build(),
                        contentDescription = displayName,
                        modifier = Modifier
                            .size(size)
                            .clip(CircleShape),
                        contentScale = ContentScale.Crop
                    )
                } else {
                    AvatarTextFallback(
                        name = displayName,
                        size = size,
                        fontSize = fallbackFontSize
                    )
                }
            }
            // 2. 网络头像
            !avatarUrl.isNullOrBlank() -> {
                AsyncImage(
                    model = ImageRequest.Builder(context)
                        .data(avatarUrl)
                        .crossfade(true)
                        .build(),
                    contentDescription = displayName,
                    modifier = Modifier
                        .size(size)
                        .clip(CircleShape),
                    contentScale = ContentScale.Crop
                )
            }
            // 3. 兜底：昵称首字符
            else -> AvatarTextFallback(
                name = displayName,
                size = size,
                fontSize = fallbackFontSize
            )
        }
    }
}

/**
 * 昵称首字符兜底头像：没有本地/网络头像时用它占位。
 *
 * @param size 边长，需与调用处期望的头像尺寸一致
 * @param fontSize 首字符字号
 */
@Composable
fun AvatarTextFallback(
    name: String,
    size: Dp,
    fontSize: TextUnit,
    modifier: Modifier = Modifier
) {
    val initial = name.firstOrNull()?.toString() ?: "?"
    Box(
        modifier = modifier
            .size(size)
            .clip(CircleShape)
            .background(Primary.copy(alpha = 0.3f)),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = initial,
            fontSize = fontSize,
            fontWeight = FontWeight.Bold,
            color = Color.White
        )
    }
}

/** 默认头像边长（会话列表尺寸）。 */
val DEFAULT_AVATAR_SIZE: Dp = 52.dp

/** 默认首字母字号，约为 [DEFAULT_AVATAR_SIZE] 的 42%。 */
val DEFAULT_AVATAR_FONT_SIZE: TextUnit = 22.sp
