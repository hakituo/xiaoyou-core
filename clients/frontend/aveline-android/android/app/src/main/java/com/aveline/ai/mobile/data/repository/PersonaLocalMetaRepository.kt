package com.aveline.ai.mobile.data.repository

import android.net.Uri
import com.aveline.ai.mobile.data.local.database.dao.PersonaLocalMetaDao
import com.aveline.ai.mobile.data.local.database.entity.PersonaLocalMetaEntity
import com.aveline.ai.mobile.data.local.storage.PersonaAvatarStorage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Persona 本地元数据仓库：管理用户为 persona 自定义的昵称与头像。
 *
 * 与 [PersonaRepositoryImpl] 的关系：
 * - PersonaRepositoryImpl 对接后端 persona 数据（filename/name/description）
 * - 本仓库只负责本地的"显示偏好"覆盖（customName + avatarPath）
 * UI 层把两者合并后展示。
 */
@Singleton
class PersonaLocalMetaRepository @Inject constructor(
    private val dao: PersonaLocalMetaDao,
    private val avatarStorage: PersonaAvatarStorage
) {

    /** 观察所有 persona 的本地元数据 */
    fun observeAll(): Flow<List<PersonaLocalMetaEntity>> = dao.observeAll()

    /**
     * 一次性修复历史脏数据：清理多个 persona 共用同一头像文件的记录。
     *
     * 背景：旧版 [PersonaAvatarStorage] 生成本地文件名时只做字符替换，
     * persona filename 里的中文全部变成 "_"，同长度中文名（如
     * "sensitive/Mian.json" 与 "sensitive/Frost.json"）会算出完全相同的
     * 文件名，后设置的头像直接覆盖前一个，表现为两个角色头像变成同一张。
     *
     * 新版文件名已带哈希后缀不再冲突，但旧记录仍指向被覆盖的同一文件，
     * 因此这里把冲突记录的 avatarPath 清空（回退到后端默认头像/首字兜底），
     * 由用户重新设置即可。只清数据库指向，物理文件一并删除。
     */
    suspend fun repairDuplicatedAvatars() = withContext(Dispatchers.IO) {
        val all = dao.getAllOnce()
        val duplicated = all
            .mapNotNull { entity -> entity.avatarPath?.let { it to entity } }
            .groupBy({ it.first }, { it.second })
            .filterValues { it.size > 1 }

        if (duplicated.isEmpty()) return@withContext

        duplicated.forEach { (path, entities) ->
            avatarStorage.deleteAvatar(path)
            entities.forEach { entity ->
                dao.upsert(entity.copy(avatarPath = null, updatedAt = System.currentTimeMillis()))
            }
        }
    }

    /** 按 filename 观察单条 */
    fun observeByFilename(filename: String): Flow<PersonaLocalMetaEntity?> = dao.observeByFilename(filename)

    /**
     * 更新昵称；传 null 或空串表示清除自定义（用回后端默认 name）
     */
    suspend fun setCustomName(personaFilename: String, name: String?) =
        withContext(Dispatchers.IO) {
            val trimmed = name?.trim()?.takeIf { it.isNotEmpty() }
            val existing = dao.getByFilename(personaFilename)
            val entity = (existing ?: PersonaLocalMetaEntity(personaFilename = personaFilename))
                .copy(customName = trimmed, updatedAt = System.currentTimeMillis())
            dao.upsert(entity)
        }

    /**
     * 设置头像：把 sourceUri 复制到本地存储并更新数据库
     *
     * @return true 成功，false 失败
     */
    suspend fun setAvatar(personaFilename: String, sourceUri: Uri): Boolean {
        val saved = avatarStorage.saveAvatar(personaFilename, sourceUri) ?: return false
        val existing = dao.getByFilename(personaFilename)
        // 删除旧文件（如果文件名不同）
        existing?.avatarPath?.takeIf { it != saved }?.let { old ->
            avatarStorage.deleteAvatar(old)
        }
        val entity = (existing ?: PersonaLocalMetaEntity(personaFilename = personaFilename))
            .copy(avatarPath = saved, updatedAt = System.currentTimeMillis())
        dao.upsert(entity)
        return true
    }

    /**
     * 清空头像（恢复用后端默认 avatarUrl / emoji）
     */
    suspend fun clearAvatar(personaFilename: String) {
        val existing = dao.getByFilename(personaFilename) ?: return
        existing.avatarPath?.let { avatarStorage.deleteAvatar(it) }
        dao.upsert(existing.copy(avatarPath = null, updatedAt = System.currentTimeMillis()))
    }

    /** 删除 persona 的所有本地元数据 */
    suspend fun clearAll(personaFilename: String) = withContext(Dispatchers.IO) {
        dao.getByFilename(personaFilename)?.avatarPath?.let { avatarStorage.deleteAvatar(it) }
        dao.delete(personaFilename)
    }

    /** 一次性读取单个 persona 的本地元数据（通知标题/头像解析用），无记录返回 null。 */
    suspend fun getMetaOnce(personaFilename: String): PersonaLocalMetaEntity? =
        withContext(Dispatchers.IO) { dao.getByFilename(personaFilename) }

    /**
     * 未读数 +1（角色主动消息归档时调用）。
     * 无记录时会创建一条只含未读数的 meta，让会话列表在用户还没进过
     * 该角色聊天页（meta 表无记录）时也能看到未读提示。
     */
    suspend fun incrementUnread(personaFilename: String) = withContext(Dispatchers.IO) {
        val existing = dao.getByFilename(personaFilename)
        val entity = (existing ?: PersonaLocalMetaEntity(personaFilename = personaFilename))
            .copy(unreadCount = (existing?.unreadCount ?: 0) + 1)
        dao.upsert(entity)
    }

    /**
     * 清零未读数（用户进入该角色聊天页时调用）。
     * 已是 0 时直接返回，避免重复写库触发 Flow 抖动。
     *
     * 注意：会话列表是**按角色聚合**的（同一角色的多个 persona 未读数相加），
     * 而主动消息可能落在同角色的任意一个 persona 上。只清"当前打开的那一个"
     * 会留下同角色其他 persona 的未读，表现为"点进去看了，列表徽章还在"。
     * 清未读请以角色为单位，用 [clearUnreadFor]。
     */
    suspend fun clearUnread(personaFilename: String) = withContext(Dispatchers.IO) {
        val existing = dao.getByFilename(personaFilename) ?: return@withContext
        if (existing.unreadCount == 0) return@withContext
        dao.upsert(existing.copy(unreadCount = 0))
    }

    /**
     * 批量清零未读数（用户进入某角色聊天页时，按角色整体清零）。
     *
     * 会话列表的徽章是 `该角色下所有 persona 的 unreadCount 之和`，
     * 所以只要用户进过这个角色的聊天页，整个角色的未读都应当清掉，
     * 否则会出现"点进去没有新消息、返回后徽章还在"的顽固红点。
     *
     * @param personaFilenames 需要清零的 persona 集合
     */
    suspend fun clearUnreadFor(personaFilenames: Collection<String>) = withContext(Dispatchers.IO) {
        personaFilenames.forEach { filename ->
            val existing = dao.getByFilename(filename) ?: return@forEach
            if (existing.unreadCount == 0) return@forEach
            dao.upsert(existing.copy(unreadCount = 0))
        }
    }

    /**
     * 解析 persona 的本地头像文件（通知 largeIcon 用）。
     * 未设置头像或文件不存在时返回 null。
     */
    suspend fun resolveAvatarFile(personaFilename: String): java.io.File? =
        withContext(Dispatchers.IO) { avatarStorage.getAvatarFile(dao.getByFilename(personaFilename)?.avatarPath) }

    /**
     * 更新最后一条消息预览（用于会话列表页副标题）。
     *
     * 仅在 preview 或时间变化时写入，避免相同消息重复写库触发 Flow 抖动。
     *
     * @param personaFilename persona 标识
     * @param preview 截断后的预览文本（调用方负责截断）；传 null 表示清空
     * @param timestamp 消息时间戳（毫秒）
     */
    suspend fun updateLastMessage(
        personaFilename: String,
        preview: String?,
        timestamp: Long?
    ) = withContext(Dispatchers.IO) {
        val existing = dao.getByFilename(personaFilename)
        // 避免无变化写入触发 Flow 抖动
        if (existing != null &&
            existing.lastMessagePreview == preview &&
            existing.lastMessageAt == timestamp
        ) {
            return@withContext
        }
        val entity = (existing ?: PersonaLocalMetaEntity(personaFilename = personaFilename))
            .copy(
                lastMessagePreview = preview,
                lastMessageAt = timestamp,
                updatedAt = System.currentTimeMillis()
            )
        dao.upsert(entity)
    }
}
