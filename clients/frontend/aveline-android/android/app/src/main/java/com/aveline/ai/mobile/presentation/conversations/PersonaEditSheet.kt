package com.aveline.ai.mobile.presentation.conversations

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.aveline.ai.mobile.data.local.storage.PersonaAvatarStorage
import com.aveline.ai.mobile.presentation.theme.OverlayLight
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.PrimaryVariant
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * Persona 编辑面板（弹窗形式）
 *
 * 功能：
 * - 改昵称（customName）
 * - 改头像（图片选择器 + 本地存储）
 * - 恢复默认头像
 *
 * @param item 当前编辑的 persona 列表项
 * @param avatarStorage 头像本地存储
 * @param onDismiss 关闭面板
 * @param onSaveName 保存昵称（传 null/空 = 恢复后端默认）
 * @param onPickAvatar 选择头像（传 Uri）
 * @param onClearAvatar 清空自定义头像（恢复默认）
 */
@Composable
fun PersonaEditSheet(
    item: ConversationItem,
    avatarStorage: PersonaAvatarStorage,
    onDismiss: () -> Unit,
    onSaveName: (String?) -> Unit,
    onPickAvatar: (Uri) -> Unit,
    onClearAvatar: () -> Unit
) {
    var nameInput by remember(item.filename) { mutableStateOf(item.displayName) }

    // 图片选择器
    val imagePicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent()
    ) { uri: Uri? ->
        uri?.let { onPickAvatar(it) }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("编辑角色") },
        text = {
            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                // 头像预览 + 点击换图
                Box(
                    modifier = Modifier
                        .size(96.dp)
                        .clip(CircleShape)
                        .background(OverlayLight)
                        .clickable { imagePicker.launch("image/*") },
                    contentAlignment = Alignment.Center
                ) {
                    EditAvatarPreview(item = item, avatarStorage = avatarStorage)
                    // 右下角编辑角标
                    Box(
                        modifier = Modifier
                            .align(Alignment.BottomEnd)
                            .size(28.dp)
                            .clip(CircleShape)
                            .background(Primary),
                        contentAlignment = Alignment.Center
                    ) {
                        Icon(
                            imageVector = Icons.Default.Edit,
                            contentDescription = "更换头像",
                            tint = Color.White,
                            modifier = Modifier.size(14.dp)
                        )
                    }
                }

                Spacer(modifier = Modifier.height(8.dp))

                Text(
                    text = "点击头像更换图片",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextTertiary
                )

                // 恢复默认头像按钮（仅当有自定义头像时显示）
                if (!item.localAvatarPath.isNullOrBlank()) {
                    Spacer(modifier = Modifier.height(4.dp))
                    TextButton(onClick = onClearAvatar) {
                        Text(
                            text = "恢复默认头像",
                            style = MaterialTheme.typography.labelSmall,
                            color = PrimaryVariant
                        )
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                // 昵称输入框
                OutlinedTextField(
                    value = nameInput,
                    onValueChange = { nameInput = it },
                    label = { Text("昵称") },
                    placeholder = { Text("留空恢复默认") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )

                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "昵称只在本设备生效，不影响后端 persona 名称",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextTertiary
                )
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    onSaveName(nameInput.trim().takeIf { it.isNotEmpty() })
                    onDismiss()
                },
                colors = ButtonDefaults.buttonColors(containerColor = Primary)
            ) {
                Text("保存")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消", color = TextSecondary)
            }
        }
    )
}

/**
 * 编辑面板的头像预览（逻辑同 ConversationAvatar，但尺寸更大）
 */
@Composable
private fun EditAvatarPreview(
    item: ConversationItem,
    avatarStorage: PersonaAvatarStorage
) {
    val context = LocalContext.current
    when {
        !item.localAvatarPath.isNullOrBlank() -> {
            val file = avatarStorage.getAvatarFile(item.localAvatarPath)
            if (file != null) {
                AsyncImage(
                    model = ImageRequest.Builder(context)
                        .data(file)
                        .crossfade(true)
                        .build(),
                    contentDescription = null,
                    modifier = Modifier
                        .size(96.dp)
                        .clip(CircleShape),
                    contentScale = ContentScale.Crop
                )
            } else {
                EditAvatarFallback(name = item.displayName)
            }
        }
        !item.avatarUrl.isNullOrBlank() -> {
            AsyncImage(
                model = ImageRequest.Builder(context)
                    .data(item.avatarUrl)
                    .crossfade(true)
                    .build(),
                contentDescription = null,
                modifier = Modifier
                    .size(96.dp)
                    .clip(CircleShape),
                contentScale = ContentScale.Crop
            )
        }
        else -> EditAvatarFallback(name = item.displayName)
    }
}

@Composable
private fun EditAvatarFallback(name: String) {
    val initial = name.firstOrNull()?.toString() ?: "?"
    Box(
        modifier = Modifier
            .size(96.dp)
            .clip(CircleShape)
            .background(Primary.copy(alpha = 0.3f)),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = initial,
            fontSize = 40.sp,
            fontWeight = FontWeight.Bold,
            color = Color.White
        )
    }
}
