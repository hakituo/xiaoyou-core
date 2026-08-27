package com.aveline.ai.mobile.utils

import android.content.Context
import android.net.Uri
import android.os.Environment
import androidx.core.content.FileProvider
import com.aveline.ai.mobile.data.local.database.AvelineDatabase
import com.aveline.ai.mobile.data.local.database.dao.MessageDao
import com.aveline.ai.mobile.data.local.database.dao.SessionDao
import com.aveline.ai.mobile.data.local.database.entity.MessageEntity
import com.aveline.ai.mobile.data.local.database.entity.SessionEntity
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import androidx.room.withTransaction
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 导出数据模型
 */
@Serializable
data class ExportData(
    val version: Int = 1,
    val exportTime: String,
    val appVersion: String,
    val sessions: List<SessionExport>,
    val settings: SettingsExport
)

@Serializable
data class SessionExport(
    val id: String,
    val title: String,
    val createdAt: String,
    val messages: List<MessageExport>
)

@Serializable
data class MessageExport(
    val id: String,
    val role: String,
    val content: String,
    val timestamp: String
)

@Serializable
data class SettingsExport(
    val backendUrl: String,
    val selectedVoiceId: String,
    val responseLength: String,
    val autoTtsEnabled: Boolean,
    val residentModeEnabled: Boolean,
    val hapticFeedbackEnabled: Boolean,
    val isContextSyncEnabled: Boolean
)

/**
 * 数据导出管理器
 * 
 * 提供数据导出和导入功能
 * 
 * Requirements: 23.7, 23.8
 */
@Singleton
class DataExportManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val database: AvelineDatabase,
    private val sessionDao: SessionDao,
    private val messageDao: MessageDao,
    private val appPreferences: AppPreferences,
    private val json: Json
) {
    private val dateFormat = SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", Locale.getDefault())

    /**
     * 用 [password] 加密 [plain] 的字节, 返回导出文本格式。
     * 加密实现见 [ExportCipher](PBKDF2 + AES-GCM), 导出文件在磁盘/分享链路中不再明文可见。
     */
    private fun encryptPlaintext(plain: ByteArray, password: String): String =
        ExportCipher.encrypt(plain, password)

    /**
     * 解密导出内容。密码错误或数据被篡改时抛异常(由调用方捕获)。
     */
    private fun decryptPayload(payload: String, password: String): ByteArray =
        ExportCipher.decrypt(payload, password)

    /**
     * 判断导入内容是否为加密格式, 决定走解密还是兼容旧版明文。
     */
    private fun isEncrypted(content: String): Boolean = ExportCipher.isEncrypted(content)

    /**
     * 生成导出文件路径。
     *
     * 写入 app 外部私有目录 (getExternalFilesDir)，与 file_paths.xml 的 external-files-path
     * 映射匹配 (FileProvider 才能安全分享)，同时兼容 scoped storage (targetSdk 35 下无法再
     * 直接用 File API 写公共 Download 目录)。
     *
     * @param fileName 文件名
     */
    private fun createExportFile(fileName: String): File {
        val baseDir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
            ?: File(context.filesDir, "downloads")
        if (!baseDir.exists()) baseDir.mkdirs()
        return File(baseDir, fileName)
    }
    
    /**
     * 导出聊天历史
     *
     * 导出文件用 [password] 做 AES-GCM 加密, 磁盘上不再是明文(修复"公开导出为明文")。
     *
     * @param password 加密口令, 用于后续导入解密; 非空才启用加密
     * @return 导出文件的 Uri
     */
    suspend fun exportChatHistory(password: String = ""): Result<Uri> = withContext(Dispatchers.IO) {
        try {
            // 获取所有会话和消息
            val sessions = sessionDao.observeSessions().first()
            val sessionExports = sessions.map { session ->
                // 全量正序导出, 不用 getRecentMessages (只取最近 200 条且 DESC 倒序)
                val messages = messageDao.getMessagesAscending(session.id)
                SessionExport(
                    id = session.id,
                    title = session.title,
                    // 用时间戳字符串而非 Date.toString(),导入时能可靠解析
                    createdAt = session.createdAt.toString(),
                    messages = messages.map { msg ->
                        MessageExport(
                            id = msg.id,
                            role = if (msg.isUser) "user" else "assistant",
                            content = msg.text,
                            timestamp = msg.timestamp.toString()
                        )
                    }
                )
            }

            // 创建导出数据
            val exportData = ExportData(
                exportTime = System.currentTimeMillis().toString(),
                appVersion = getAppVersion(),
                sessions = sessionExports,
                settings = buildSettingsExport()
            )
            
            // 写入文件 (app 外部私有目录, 与 FileProvider 匹配)
            val fileName = "aveline_export_${dateFormat.format(Date())}.json"
            val exportFile = createExportFile(fileName)
            
            val plainBytes = json.encodeToString(exportData).toByteArray()
            FileOutputStream(exportFile).use { output ->
                // 口令非空才加密, 否则(调试场景)直接写明文
                val bytes = if (password.isNotEmpty()) {
                    encryptPlaintext(plainBytes, password).toByteArray()
                } else {
                    plainBytes
                }
                output.write(bytes)
            }
            
            // 获取 FileProvider Uri
            val uri = FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                exportFile
            )
            
            Result.success(uri)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    /**
     * 导出设置
     */
    private fun buildSettingsExport(): SettingsExport {
        return SettingsExport(
            backendUrl = appPreferences.backendUrl,
            selectedVoiceId = appPreferences.selectedVoiceId,
            responseLength = appPreferences.responseLength.name,
            autoTtsEnabled = appPreferences.autoTtsEnabled,
            residentModeEnabled = appPreferences.residentModeEnabled,
            hapticFeedbackEnabled = appPreferences.hapticFeedbackEnabled,
            isContextSyncEnabled = appPreferences.isContextSyncEnabled
        )
    }
    
    /**
     * 导入数据。
     *
     * 修复 P0-17c: 原实现是空 TODO,importedCount 只累加但根本没插入数据库。
     * 现在真正实现会话和消息的插入,支持 merge 模式(合并)与覆盖模式(先清后插)。
     *
     * 注意:导出时 createdAt/timestamp 用 Date().toString() 格式,不可靠。
     * 导入时尝试解析,失败回退为当前时间,避免导入中断。
     *
     * @param uri 导入文件的 Uri
     * @param password 解密口令: 用于解封"加密导出"文件; 若文件是旧版明文则忽略
     * @param merge true=合并(保留现有数据,追加导入);false=覆盖(先清空再导入)
     */
    suspend fun importData(
        uri: Uri,
        password: String = "",
        merge: Boolean = false
    ): Result<Int> = withContext(Dispatchers.IO) {
        try {
            // 读取文件内容
            val rawContent = context.contentResolver.openInputStream(uri)?.use { input ->
                input.bufferedReader().readText()
            } ?: throw Exception("Unable to read import file")

            // 加密格式 -> 需口令解密; 口令为空或解密失败冒出明确异常
            val content = if (isEncrypted(rawContent)) {
                if (password.isEmpty()) {
                    throw Exception("导入文件已加密, 请输入加密时设置的密码")
                }
                String(decryptPayload(rawContent, password), Charsets.UTF_8)
            } else {
                // 旧版明文(兼容): 明文直接解析
                rawContent
            }

            // 解析 JSON
            val importData = json.decodeFromString<ExportData>(content)

            // 验证版本
            if (importData.version > 1) {
                throw Exception("Unsupported export version: ${importData.version}")
            }

            // 导入设置
            importSettings(importData.settings)

            // 整个导入(覆盖清空 + 会话/消息插入)放在同一事务里,任一步失败整体回滚,
            // 避免半导入状态(只导入了一部分会话就失败)。
            val importedCount = database.withTransaction {
                // 覆盖模式:先清空现有会话和消息(放事务内,失败一起回滚)
                if (!merge) {
                    messageDao.deleteAllMessages()
                    sessionDao.deleteAllSessions()
                }

                var count = 0
                val now = System.currentTimeMillis()

                // 先批量插会话,再批量插消息,Room 会按返回顺序回填外键
                val sessionEntities = importData.sessions.map { sessionExport ->
                    val sessionCreatedAt = parseDateOrNow(sessionExport.createdAt, now)
                    SessionEntity(
                        id = sessionExport.id,
                        title = sessionExport.title,
                        createdAt = sessionCreatedAt,
                        updatedAt = sessionCreatedAt,
                        isPinned = false
                    )
                }
                sessionDao.insertSessions(sessionEntities)

                // 拼装所有消息并批量插入
                val allMessages = mutableListOf<MessageEntity>()
                importData.sessions.forEach { sessionExport ->
                    sessionExport.messages.forEach { msgExport ->
                        allMessages.add(
                            MessageEntity(
                                id = msgExport.id,
                                text = msgExport.content,
                                isUser = msgExport.role == "user",
                                timestamp = parseDateOrNow(msgExport.timestamp, now),
                                messageType = "text",
                                sessionId = sessionExport.id
                            )
                        )
                    }
                }
                messageDao.insertMessages(allMessages)
                count = allMessages.size
                count
            }

            Result.success(importedCount)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * 尝试解析导出时的日期字符串,失败则返回 [fallback]。
     * 导出用的是 Date.toString() 格式(如 "Mon Jul 28 16:30:00 CST 2026"),
     * 不同 Locale/时区下格式不稳定,所以做容错。
     */
    private fun parseDateOrNow(dateStr: String, fallback: Long): Long {
        return try {
            // 尝试解析为 long 时间戳(理想情况)
            dateStr.toLongOrNull() ?: fallback
        } catch (e: Exception) {
            fallback
        }
    }
    
    /**
     * 导入设置
     */
    private fun importSettings(settings: SettingsExport) {
        appPreferences.backendUrl = settings.backendUrl
        appPreferences.selectedVoiceId = settings.selectedVoiceId
        appPreferences.autoTtsEnabled = settings.autoTtsEnabled
        appPreferences.residentModeEnabled = settings.residentModeEnabled
        appPreferences.hapticFeedbackEnabled = settings.hapticFeedbackEnabled
        appPreferences.isContextSyncEnabled = settings.isContextSyncEnabled
    }
    
    /**
     * 导出设置到文件
     */
    suspend fun exportSettings(password: String = ""): Result<Uri> = withContext(Dispatchers.IO) {
        try {
            val settingsExport = buildSettingsExport()
            val fileName = "aveline_settings_${dateFormat.format(Date())}.json"
            val exportFile = createExportFile(fileName)
            
            val plainBytes = json.encodeToString(settingsExport).toByteArray()
            FileOutputStream(exportFile).use { output ->
                val bytes = if (password.isNotEmpty()) {
                    encryptPlaintext(plainBytes, password).toByteArray()
                } else {
                    plainBytes
                }
                output.write(bytes)
            }
            
            val uri = FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                exportFile
            )
            
            Result.success(uri)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    /**
     * 获取应用版本
     */
    private fun getAppVersion(): String {
        return try {
            val packageInfo = context.packageManager.getPackageInfo(context.packageName, 0)
            packageInfo.versionName ?: "1.0.0"
        } catch (e: Exception) {
            "1.0.0"
        }
    }
    
    /**
     * 清除所有数据。
     *
     * 修复 P0-17b: 原实现是空 TODO,UI 假装成功但数据未清除。
     * 现在先删消息(外键依赖),再删会话,最后清设置。
     */
    suspend fun clearAllData(): Result<Unit> = withContext(Dispatchers.IO) {
        try {
            // 先删消息(避免外键约束,虽然 Room 默认不强制外键,但保持顺序更安全)
            messageDao.deleteAllMessages()
            // 再删会话
            sessionDao.deleteAllSessions()
            // 最后清设置
            appPreferences.clearAll()

            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
