package com.aveline.ai.mobile.data.local.database.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Persona 本地元数据：用户为该 persona 自定义的昵称和头像。
 *
 * 与后端 persona 数据分离的原因：后端 PersonaDto 不存用户的"显示偏好"
 * （改名/改头像属于本地 UI 层数据），且后端端点暂不支持上传头像图片。
 *
 * 后端 persona.filename 作为外键关联（稳定，不随改名变化）。
 * 存储的头像图片保存到 [context.filesDir]/avatars/ 下，这里存相对文件名。
 *
 * @param personaFilename 后端 persona 的 filename（唯一标识）
 * @param customName 用户自定义昵称；null 表示用后端默认 name
 * @param avatarPath 用户自定义头像的本地文件名（相对 avatars/ 目录）；null 表示用后端默认 avatarUrl / emoji
 * @param lastMessagePreview 最后一条消息预览文本（截断后），null 表示无；用于会话列表页副标题
 * @param lastMessageAt 最后一条消息的时间戳（毫秒），null 表示无；用于排序和"X 分钟前"显示
 * @param unreadCount 角色主动消息未读数；归档主动消息时 +1，用户进入该角色聊天页时清零
 * @param updatedAt 最近修改时间戳（毫秒）
 */
@Entity(tableName = "persona_local_meta")
data class PersonaLocalMetaEntity(
    @PrimaryKey
    val personaFilename: String,
    val customName: String? = null,
    val avatarPath: String? = null,
    val lastMessagePreview: String? = null,
    val lastMessageAt: Long? = null,
    val unreadCount: Int = 0,
    val updatedAt: Long = System.currentTimeMillis()
)
