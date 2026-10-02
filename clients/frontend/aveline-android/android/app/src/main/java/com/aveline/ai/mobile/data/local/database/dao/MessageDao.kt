package com.aveline.ai.mobile.data.local.database.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import com.aveline.ai.mobile.data.local.database.entity.MessageEntity
import com.aveline.ai.mobile.data.local.database.entity.MessageTreeNode
import com.aveline.ai.mobile.data.local.database.RoleHistoryMergePlan
import com.aveline.ai.mobile.data.local.database.planRoleHistoryMerge
import kotlinx.coroutines.flow.Flow

/**
 * Data Access Object for message operations.
 * 
 * Provides methods to insert, query, and delete messages from the local database.
 * Supports reactive queries using Flow for real-time updates.
 */
@Dao
interface MessageDao {
    
    /**
     * Observes messages for a specific session, ordered by timestamp ascending (oldest first).
     *
     * 时间正序排列（最早的在前，最新的在后）让 UI 用普通 LazyColumn 即可：index 0 = 最旧，
     * index last = 最新，自动滚动到 lastIndex 就是"滚到底部看最新"。
     * 之前用 DESC 配合 reverseLayout=true 看似成立，但 ChatViewModel 用 `+ newMessage` append
     * 新消息（用户消息、AI 占位、流式累积），append 落到数组末尾；reverseLayout=true 让
     * index 0 渲染到底部，所以历史 AI 消息堆到底部，刚发的用户消息反而跑到顶部，表现为"消息反了"。
     * 改 ASC 后，append 的消息天然落到数组尾部，UI 自然渲染到底部，无需 reverseLayout。
     *
     * @param sessionId The session ID to filter messages
     * @return Flow of message list that updates automatically
     */
    @Query("SELECT * FROM messages WHERE sessionId = :sessionId ORDER BY timestamp ASC")
    fun observeMessages(sessionId: String): Flow<List<MessageEntity>>

    @Query("SELECT id, sessionId, parentId, timestamp, isUser, variantIndex, isActiveVariant FROM messages WHERE sessionId = :sessionId ORDER BY timestamp ASC, id ASC")
    fun observeMessageTree(sessionId: String): Flow<List<MessageTreeNode>>

    @Query("SELECT id, sessionId, parentId, timestamp, isUser, variantIndex, isActiveVariant FROM messages WHERE sessionId = :sessionId ORDER BY timestamp ASC, id ASC")
    suspend fun getMessageTree(sessionId: String): List<MessageTreeNode>

    @Query("SELECT * FROM messages WHERE sessionId = :sessionId AND id IN (:ids)")
    suspend fun getMessagesByIds(sessionId: String, ids: List<String>): List<MessageEntity>

    @Query("SELECT * FROM messages WHERE sessionId = :sessionId ORDER BY timestamp ASC")
    suspend fun getAllMessages(sessionId: String): List<MessageEntity>
    
    /**
     * Inserts a message, replacing if it already exists.
     *
     * @param message The message to insert
     */
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertMessage(message: MessageEntity)

    /**
     * 批量插入消息,单事务提交,避免逐条写入的 IO 放大。
     *
     * @param messages 消息列表
     */
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertMessages(messages: List<MessageEntity>)

    @Query("SELECT * FROM messages WHERE id = :messageId")
    suspend fun getMessageById(messageId: String): MessageEntity?

    /** 回复完成只更新内容，不能用生成开始时的快照重新激活旧版本或改写父链。 */
    @Transaction
    suspend fun upsertMessageContent(message: MessageEntity) {
        val existing = getMessageById(message.id)
        insertMessage(preserveMessageBranch(message, existing))
    }

    /** 网络历史只用于空库初始化；请求等待期间收到本地消息后，旧快照必须作废。 */
    @Transaction
    suspend fun insertHistoryIfEmpty(sessionId: String, messages: List<MessageEntity>): Boolean {
        if (getMessageCount(sessionId) > 0) return false
        insertMessages(messages)
        return true
    }

    /** 先生成并校验完整计划，再在同一个事务里发布；失败整笔回滚。旧容器不删除。 */
    @Transaction
    suspend fun mergeRoleHistory(targetSessionId: String, sourceSessionIds: List<String>): RoleHistoryMergePlan {
        val sources = (sourceSessionIds + targetSessionId).distinct().associateWith { getAllMessages(it) }
        val plan = planRoleHistoryMerge(targetSessionId, sources)
        if (plan.messages.isNotEmpty()) {
            android.util.Log.i("RoleHistoryMigration", "迁移预览: ${plan.sourceCounts}, 目标=$targetSessionId, 新增=${plan.addedCount}")
            insertMessages(plan.messages)
            check(getMessageCount(targetSessionId) == sources[targetSessionId].orEmpty().size + plan.addedCount) {
                "迁移消息数量校验失败"
            }
        }
        sources.filter { it.key != targetSessionId && it.value.isNotEmpty() }.forEach { (source, _) ->
            val archive = "archive_role_merge:$targetSessionId:$source"
            createArchiveSession(source, archive)
            archiveSourceMessages(source, archive)
        }
        return plan
    }

    @Query("INSERT OR IGNORE INTO sessions (id, title, createdAt, updatedAt, isPinned) SELECT :archiveId, '迁移前备份：' || title, createdAt, updatedAt, 0 FROM sessions WHERE id = :sourceId")
    suspend fun createArchiveSession(sourceId: String, archiveId: String)

    /** 原记录只改归档归属，不改正文和父链；归档不再参与重试，避免删除过的消息复活。 */
    @Query("UPDATE messages SET sessionId = :archiveId WHERE sessionId = :sourceId")
    suspend fun archiveSourceMessages(sourceId: String, archiveId: String)
    
    /**
     * Deletes a specific message by ID.
     * 
     * @param messageId The ID of the message to delete
     */
    @Query("DELETE FROM messages WHERE id = :messageId")
    suspend fun deleteMessage(messageId: String)
    
    /**
     * Clears all messages for a specific session.
     * 
     * @param sessionId The session ID to clear messages for
     */
    @Query("DELETE FROM messages WHERE sessionId = :sessionId")
    suspend fun clearSession(sessionId: String)
    
    /**
     * Gets the most recent messages for a session (limited to 200).
     * 
     * @param sessionId The session ID to get messages for
     * @return List of recent messages, newest first
     */
    @Query("SELECT * FROM messages WHERE sessionId = :sessionId ORDER BY timestamp DESC LIMIT 200")
    suspend fun getRecentMessages(sessionId: String): List<MessageEntity>

    /**
     * 获取某个会话的全量消息,时间正序(最早在前),供数据导出使用。
     * 相比 getRecentMessages: 不截断(全量)、顺序正确(ASC, 而非 DESC)。
     *
     * @param sessionId 会话 ID
     * @return 按 timeasc 全量排列的消息列表
     */
    @Query("SELECT * FROM messages WHERE sessionId = :sessionId ORDER BY timestamp ASC")
    suspend fun getMessagesAscending(sessionId: String): List<MessageEntity>

    @Query("UPDATE messages SET text = :newText WHERE id = :messageId")
    suspend fun updateMessageText(messageId: String, newText: String)

    @Query(
        "UPDATE messages SET isActiveVariant = 0 WHERE sessionId = :sessionId " +
            "AND isUser = :isUser AND ((:parentId IS NULL AND parentId IS NULL) OR parentId = :parentId)"
    )
    suspend fun deactivateSiblingVariants(sessionId: String, parentId: String?, isUser: Boolean)

    @Query("UPDATE messages SET isActiveVariant = 1 WHERE id = :messageId")
    suspend fun activateVariant(messageId: String)

    @Query(
        "SELECT * FROM messages WHERE sessionId = :sessionId AND isUser = :isUser " +
            "AND ((:parentId IS NULL AND parentId IS NULL) OR parentId = :parentId) " +
            "ORDER BY variantIndex ASC, timestamp ASC"
    )
    suspend fun getSiblingVariants(
        sessionId: String,
        parentId: String?,
        isUser: Boolean
    ): List<MessageEntity>

    @Transaction
    suspend fun insertActiveVariant(message: MessageEntity) {
        deactivateSiblingVariants(message.sessionId.orEmpty(), message.parentId, message.isUser)
        insertMessage(message)
    }

    @Transaction
    suspend fun selectVariant(
        sessionId: String,
        parentId: String?,
        isUser: Boolean,
        messageId: String
    ) {
        deactivateSiblingVariants(sessionId, parentId, isUser)
        activateVariant(messageId)
    }

    @Query("SELECT COUNT(*) FROM messages WHERE sessionId = :sessionId")
    suspend fun getMessageCount(sessionId: String): Int

    /**
     * 显式维护接口；聊天发送、回复完成和页面加载禁止调用它自动删除历史。
     * 保留最新的 [keep] 条,其余删除。
     */
    @Query(
        "DELETE FROM messages WHERE sessionId = :sessionId AND id NOT IN " +
            "(SELECT id FROM messages WHERE sessionId = :sessionId ORDER BY timestamp DESC LIMIT :keep)"
    )
    suspend fun deleteOldestMessages(sessionId: String, keep: Int)

    /**
     * 取会话中当前最旧的一条消息 id。
     *
     * 裁剪历史后用它重新作为消息树根：被删掉的最旧消息往往就是原来的根
     * （parentId = NULL），不重新置根会让整棵消息树失去入口，
     * selectActiveConversationPath 找不到根就会返回空列表 —— 表现为"聊天记录整屏消失"。
     */
    @Query(
        "SELECT id FROM messages WHERE sessionId = :sessionId " +
            "ORDER BY timestamp ASC, id ASC LIMIT 1"
    )
    suspend fun getOldestMessageId(sessionId: String): String?

    /**
     * 把某条消息断链，使其成为消息树的根节点。
     */
    @Query("UPDATE messages SET parentId = NULL WHERE id = :messageId")
    suspend fun clearParent(messageId: String)

    /**
     * 列出库里存在过的全部 sessionId，供启动时的断根体检扫描。
     */
    @Query("SELECT DISTINCT sessionId FROM messages WHERE sessionId IS NOT NULL")
    suspend fun getAllSessionIds(): List<String>

    /**
     * 删除所有消息(用于清除全部数据)。
     * 应在 SessionDao.deleteAllSessions 之前调用(避免外键约束)。
     */
    @Query("DELETE FROM messages")
    suspend fun deleteAllMessages()
}

/** 保留数据库里最新的归属和版本选择，后台生成仅拥有消息内容的更新权。 */
internal fun preserveMessageBranch(message: MessageEntity, existing: MessageEntity?): MessageEntity =
    if (existing == null) message else message.copy(
        sessionId = existing.sessionId,
        parentId = existing.parentId,
        variantIndex = existing.variantIndex,
        isActiveVariant = existing.isActiveVariant
    )
