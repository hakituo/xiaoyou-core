package com.aveline.ai.mobile.data.local.database

import androidx.room.Database
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import com.aveline.ai.mobile.data.local.database.dao.MessageDao
import com.aveline.ai.mobile.data.local.database.dao.MemoryDao
import com.aveline.ai.mobile.data.local.database.dao.SessionDao
import com.aveline.ai.mobile.data.local.database.dao.HealthDataDao
import com.aveline.ai.mobile.data.local.database.dao.NotificationDao
import com.aveline.ai.mobile.data.local.database.dao.PersonaLocalMetaDao
import com.aveline.ai.mobile.data.local.database.entity.MessageEntity
import com.aveline.ai.mobile.data.local.database.entity.MemoryEntity
import com.aveline.ai.mobile.data.local.database.entity.SessionEntity
import com.aveline.ai.mobile.data.local.database.entity.HealthDataEntity
import com.aveline.ai.mobile.data.local.database.entity.NotificationEntity
import com.aveline.ai.mobile.data.local.database.entity.PersonaLocalMetaEntity

/**
 * Aveline 应用 Room 数据库。
 *
 * 存储内容:
 * - Messages: 按会话组织的聊天消息
 * - Sessions: 聊天会话元数据
 * - Memories: AI 关于用户的记忆条目
 * - Notifications: 通知记录
 * - HealthData: 健康数据
 * - PersonaLocalMeta: persona 用户自定义元数据（昵称、本地头像路径）
 *
 * Version 2: 新增 persona_local_meta 表
 * Version 3: persona_local_meta 加 lastMessagePreview / lastMessageAt 两列（用于会话列表预览）
 * Version 4: messages 增加对话树父节点、版本序号和当前选中状态
 * Version 5: messages 增加 videoUrl（视频/动图消息）
 * Version 6: persona_local_meta 加 unreadCount（角色主动消息未读数）
 */
@Database(
    entities = [
        MessageEntity::class,
        SessionEntity::class,
        MemoryEntity::class,
        NotificationEntity::class,
        HealthDataEntity::class,
        PersonaLocalMetaEntity::class
    ],
    version = 6,
    exportSchema = true
)
abstract class AvelineDatabase : RoomDatabase() {

    abstract fun messageDao(): MessageDao

    abstract fun sessionDao(): SessionDao

    abstract fun memoryDao(): MemoryDao

    abstract fun notificationDao(): NotificationDao

    abstract fun healthDataDao(): HealthDataDao

    abstract fun personaLocalMetaDao(): PersonaLocalMetaDao

    companion object {
        const val DATABASE_NAME = "aveline_database"

        /**
         * v1 -> v2：新增 persona_local_meta 表（仅建表，不动旧表数据）
         */
        val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    """
                    CREATE TABLE IF NOT EXISTS persona_local_meta (
                        personaFilename TEXT NOT NULL PRIMARY KEY,
                        customName TEXT,
                        avatarPath TEXT,
                        updatedAt INTEGER NOT NULL
                    )
                    """.trimIndent()
                )
            }
        }

        /**
         * v2 -> v3：persona_local_meta 表加 lastMessagePreview / lastMessageAt 两列
         * （用于会话列表页显示最后一条消息预览；ALTER TABLE ADD COLUMN 默认 NULL，不动旧数据）
         */
        val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "ALTER TABLE persona_local_meta ADD COLUMN lastMessagePreview TEXT"
                )
                db.execSQL(
                    "ALTER TABLE persona_local_meta ADD COLUMN lastMessageAt INTEGER"
                )
            }
        }

        /** v3 -> v4：为旧的线性消息补齐对话树字段，原消息全部保留为默认版本。 */
        val MIGRATION_3_4 = object : Migration(3, 4) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE messages ADD COLUMN parentId TEXT")
                db.execSQL("ALTER TABLE messages ADD COLUMN variantIndex INTEGER NOT NULL DEFAULT 0")
                db.execSQL("ALTER TABLE messages ADD COLUMN isActiveVariant INTEGER NOT NULL DEFAULT 1")
                db.execSQL(
                    "UPDATE messages SET parentId = (" +
                        "SELECT previous.id FROM messages AS previous " +
                        "WHERE previous.sessionId = messages.sessionId " +
                        "AND (previous.timestamp < messages.timestamp OR " +
                        "(previous.timestamp = messages.timestamp AND previous.id < messages.id)) " +
                        "ORDER BY previous.timestamp DESC, previous.id DESC LIMIT 1)"
                )
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS index_messages_sessionId_parentId_isUser " +
                        "ON messages(sessionId, parentId, isUser)"
                )
            }
        }

        /** v4 -> v5：messages 增加 videoUrl 列（视频/动图消息），默认为 NULL，不动旧数据。 */
        val MIGRATION_4_5 = object : Migration(4, 5) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE messages ADD COLUMN videoUrl TEXT")
            }
        }

        /**
         * v5 -> v6：persona_local_meta 加 unreadCount 列（角色主动消息未读数）。
         * 旧行缺省 0，不影响既有数据。
         */
        val MIGRATION_5_6 = object : Migration(5, 6) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "ALTER TABLE persona_local_meta " +
                        "ADD COLUMN unreadCount INTEGER NOT NULL DEFAULT 0"
                )
            }
        }
    }
}
