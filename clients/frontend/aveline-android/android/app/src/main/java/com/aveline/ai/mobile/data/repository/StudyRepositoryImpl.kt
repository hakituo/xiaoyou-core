package com.aveline.ai.mobile.data.repository

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.dto.SetActiveFilesRequest
import com.aveline.ai.mobile.data.remote.dto.SetStudyModeRequest
import com.aveline.ai.mobile.data.remote.dto.StudyFileDto
import com.aveline.ai.mobile.data.remote.dto.StudyModeResponse
import com.aveline.ai.mobile.domain.models.CalendarDay
import com.aveline.ai.mobile.domain.models.DailyContent
import com.aveline.ai.mobile.domain.models.DailyNote
import com.aveline.ai.mobile.domain.models.DailyNoteContent
import com.aveline.ai.mobile.domain.models.DiaryEntry
import com.aveline.ai.mobile.domain.models.FileStatus
import com.aveline.ai.mobile.domain.models.LatestProgress
import com.aveline.ai.mobile.domain.models.LibraryNote
import com.aveline.ai.mobile.domain.models.StudyFile
import com.aveline.ai.mobile.domain.models.StudyModeState
import com.aveline.ai.mobile.domain.repository.StudyRepository
import com.aveline.ai.mobile.presentation.study.boolean
import com.aveline.ai.mobile.presentation.study.int
import com.aveline.ai.mobile.presentation.study.long
import com.aveline.ai.mobile.presentation.study.string
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File
import java.io.FileOutputStream
import java.time.Instant
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 学习模块仓库实现
 * 
 * 管理学习文件的上传、删除和学习模式
 * 
 * Requirements: 10.1, 10.2, 10.5, 10.7
 */
@Singleton
class StudyRepositoryImpl @Inject constructor(
    @ApplicationContext private val context: Context,
    private val apiService: AvelineApiService
) : StudyRepository {
    
    private val _filesFlow = MutableSharedFlow<List<StudyFile>>(replay = 1)
    private val _studyModeFlow = MutableSharedFlow<StudyModeState>(replay = 1)
    
    override suspend fun getFiles(): List<StudyFile> {
        return try {
            val response = apiService.getStudyFiles()
            response.files.map { it.toDomain() }
        } catch (e: Exception) {
            emptyList()
        }
    }
    
    override suspend fun uploadFile(
        uri: Uri,
        onProgress: (Float) -> Unit
    ): Result<StudyFile> {
        return try {
            onProgress(0f)
            
            // 获取文件信息
            val fileName = getFileName(uri)
            getFileSize(uri)
            val mimeType = context.contentResolver.getType(uri) ?: "application/octet-stream"
            
            // 复制文件到临时目录
            val tempFile = copyToTempFile(uri, fileName)
            
            onProgress(0.3f)
            
            // 创建 multipart 请求
            val requestBody = tempFile.asRequestBody(mimeType.toMediaTypeOrNull())
            val part = MultipartBody.Part.createFormData("file", fileName, requestBody)
            
            onProgress(0.5f)
            
            // 上传
            val response = apiService.uploadStudyFile(part)
            
            onProgress(0.9f)
            
            // 删除临时文件
            tempFile.delete()
            
            onProgress(1f)
            val file = response.toDomain()
            refreshFiles()
            Result.success(file)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    override suspend fun deleteFile(fileId: String): Result<Unit> {
        return try {
            val response = apiService.deleteStudyFile(fileId)
            
            if (response.isSuccessful) {
                refreshFiles()
                Result.success(Unit)
            } else {
                Result.failure(Exception("删除失败：${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    override suspend fun getStudyModeState(): StudyModeState {
        return try {
            apiService.getStudyMode().toDomain()
        } catch (e: Exception) {
            StudyModeState()
        }
    }
    
    override suspend fun setStudyModeEnabled(enabled: Boolean): Result<Unit> {
        return try {
            val response = apiService.setStudyMode(SetStudyModeRequest(enabled))
            
            if (response.isSuccessful) {
                refreshStudyMode()
                Result.success(Unit)
            } else {
                Result.failure(Exception("操作失败：${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    override suspend fun setActiveFiles(fileIds: Set<String>): Result<Unit> {
        return try {
            val response = apiService.setActiveStudyFiles(SetActiveFilesRequest(fileIds.toList()))
            
            if (response.isSuccessful) {
                refreshStudyMode()
                Result.success(Unit)
            } else {
                Result.failure(Exception("操作失败：${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    override fun observeFiles(): Flow<List<StudyFile>> = _filesFlow.asSharedFlow()
    
    override fun observeStudyMode(): Flow<StudyModeState> = _studyModeFlow.asSharedFlow()

    override suspend fun getSubjects(): Result<JsonObject> {
        return try {
            Result.success(apiService.getSubjects())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun addVocabulary(word: String, definition: String?): Result<JsonObject> {
        return try {
            val payload = buildJsonObject {
                put("word", word)
                definition?.let { put("definition", it) }
            }
            Result.success(apiService.addVocabulary(payload))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun searchDictionary(query: String): Result<JsonObject> {
        return try {
            Result.success(apiService.searchDictionary(query))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // ==================== 词汇复习会话相关实现 ====================

    override suspend fun getDailyVocabulary(count: Int, order: String): Result<JsonObject> {
        return try {
            Result.success(apiService.getDailyVocabulary(count, order))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getNewWords(count: Int, order: String): Result<JsonObject> {
        return try {
            Result.success(apiService.getNewWords(count, order))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getReviewOverview(): Result<JsonObject> {
        return try {
            Result.success(apiService.getReviewOverview())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getMemoryCurve(): Result<JsonObject> {
        return try {
            Result.success(apiService.getMemoryCurve())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getMistakes(): Result<JsonObject> {
        return try {
            Result.success(apiService.getMistakes())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun addManualStudy(count: Int, date: String?): Result<JsonObject> {
        return try {
            val payload = buildJsonObject {
                put("count", count)
                date?.let { put("date", it) }
            }
            Result.success(apiService.addManualStudy(payload))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getManualStudyStats(days: Int, date: String?): Result<JsonObject> {
        return try {
            Result.success(apiService.getManualStudyStats(days, date ?: ""))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getVocabBookStats(): Result<JsonObject> {
        return try {
            Result.success(apiService.getVocabBookStats())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getBookWords(page: Int, pageSize: Int): Result<JsonObject> {
        return try {
            Result.success(apiService.getBookWords(page, pageSize))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun switchVocabBook(filename: String): Result<JsonObject> {
        return try {
            val payload = buildJsonObject { put("filename", filename) }
            Result.success(apiService.switchVocabulary(payload))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun startReviewSession(): Result<JsonObject> {
        return try {
            Result.success(apiService.startSession())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun submitReview(word: String, quality: Int): Result<JsonObject> {
        return try {
            Result.success(
                apiService.submitReview(
                    buildJsonObject {
                        put("word", word)
                        put("quality", quality)
                    }
                )
            )
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun endReviewSession(): Result<JsonObject> {
        return try {
            Result.success(apiService.endSession())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // ==================== 工作区学习记录与会话相关实现 ====================

    override suspend fun getWorkspaceStudyPanel(historyLimit: Int): Result<JsonObject> {
        return try {
            Result.success(apiService.getWorkspaceStudyPanel(historyLimit = historyLimit))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun recordWorkspaceStudy(payload: JsonObject): Result<JsonObject> {
        return try {
            Result.success(apiService.recordWorkspaceStudy(payload))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun recordDailyStudy(payload: JsonObject): Result<JsonObject> {
        return try {
            Result.success(apiService.recordDailyStudy(payload))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun finishDailyStudy(): Result<JsonObject> {
        return try {
            Result.success(apiService.finishDailyStudy())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // ==================== Study/Daily 文件夹相关实现 ====================

    override suspend fun getCalendar(year: Int, month: Int): Result<List<CalendarDay>> {
        return try {
            val response = apiService.getStudyDailyCalendar(year, month)
            // 后端用 success_response 包装,真实数据在 data 字段下
            val data = response["data"]?.jsonObject ?: response
            val days = data["days"]?.jsonArray.orEmpty()
            val result = days.map { item ->
                val obj = item.jsonObject
                CalendarDay(
                    date = obj.string("date"),
                    day = obj.int("day") ?: 0,
                    hasDiary = obj.boolean("has_diary") ?: false,
                    hasPlan = obj.boolean("has_plan") ?: false,
                    hasProgress = obj.boolean("has_progress") ?: false
                )
            }
            Result.success(result)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getDateContent(date: String): Result<DailyContent> {
        return try {
            val response = apiService.getStudyDailyDate(date)
            val data = response["data"]?.jsonObject ?: response
            Result.success(
                DailyContent(
                    date = data.string("date").ifEmpty { date },
                    diary = data.string("diary"),
                    plan = data.string("plan"),
                    progress = data.string("progress")
                )
            )
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getNotes(): Result<List<DailyNote>> {
        return try {
            val response = apiService.getStudyDailyNotes()
            val data = response["data"]?.jsonObject ?: response
            val notes = data["notes"]?.jsonArray.orEmpty()
            val result = notes.map { item ->
                val obj = item.jsonObject
                DailyNote(
                    filename = obj.string("filename"),
                    path = obj.string("path"),
                    year = obj.int("year") ?: 0,
                    month = obj.int("month") ?: 0
                )
            }
            Result.success(result)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getNote(filename: String): Result<DailyNoteContent> {
        return try {
            val response = apiService.getStudyDailyNote(filename)
            val data = response["data"]?.jsonObject ?: response
            Result.success(
                DailyNoteContent(
                    filename = data.string("filename").ifEmpty { filename },
                    path = data.string("path"),
                    content = data.string("content")
                )
            )
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getLatestProgress(): Result<LatestProgress> {
        return try {
            val response = apiService.getStudyDailyLatestProgress()
            val data = response["data"]?.jsonObject ?: response
            Result.success(
                LatestProgress(
                    date = data.string("date"),
                    path = data.string("path"),
                    content = data.string("content")
                )
            )
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getLibraryNotes(): Result<List<LibraryNote>> {
        return try {
            val response = apiService.getStudyLibrary()
            val data = response["data"]?.jsonObject ?: response
            val notes = data["notes"]?.jsonArray.orEmpty()
            val result = notes.map { item ->
                val obj = item.jsonObject
                LibraryNote(
                    subject = obj.string("subject"),
                    filename = obj.string("filename"),
                    relPath = obj.string("rel_path"),
                    updatedTs = obj.long("updated_ts") ?: 0L
                )
            }
            Result.success(result)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getLibraryNote(path: String): Result<DailyNoteContent> {
        return try {
            val response = apiService.getStudyLibraryNote(path)
            val data = response["data"]?.jsonObject ?: response
            Result.success(
                DailyNoteContent(
                    filename = data.string("filename"),
                    path = data.string("path"),
                    content = data.string("content")
                )
            )
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * 计划项写接口统一处理:后端错误以 HTTP 200 + status=error 返回,
     * 不显式判定会表现为"点了没反应"的静默失败。
     */
    private fun planItemResult(response: JsonObject, fallbackMessage: String): Result<Unit> {
        return if (response.string("status") == "error") {
            Result.failure(
                IllegalStateException(response.string("message").ifEmpty { fallbackMessage })
            )
        } else {
            Result.success(Unit)
        }
    }

    override suspend fun updatePlanItemStatus(
        date: String,
        time: String,
        title: String,
        done: Boolean
    ): Result<Unit> {
        return try {
            val response = apiService.updateStudyPlanItemStatus(
                buildJsonObject {
                    put("date", date)
                    put("time", time)
                    put("title", title)
                    put("done", done)
                }
            )
            planItemResult(response, "更新计划项失败")
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun addPlanItem(
        date: String,
        time: String,
        title: String,
        durationMinutes: Int?
    ): Result<Unit> {
        return try {
            val response = apiService.addStudyPlanItem(
                buildJsonObject {
                    put("date", date)
                    put("time", time)
                    put("title", title)
                    durationMinutes?.let { put("duration_minutes", it) }
                }
            )
            planItemResult(response, "新增计划项失败")
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun updatePlanItem(
        date: String,
        targetTime: String,
        targetTitle: String,
        time: String,
        title: String,
        durationMinutes: Int?
    ): Result<Unit> {
        return try {
            val response = apiService.updateStudyPlanItem(
                buildJsonObject {
                    put("date", date)
                    put("target_time", targetTime)
                    put("target_title", targetTitle)
                    put("time", time)
                    put("title", title)
                    durationMinutes?.let { put("duration_minutes", it) }
                }
            )
            planItemResult(response, "编辑计划项失败")
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun removePlanItem(
        date: String,
        time: String,
        title: String
    ): Result<Unit> {
        return try {
            val response = apiService.removeStudyPlanItem(
                buildJsonObject {
                    put("date", date)
                    put("time", time)
                    put("title", title)
                }
            )
            planItemResult(response, "删除计划项失败")
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getDiaries(date: String?): Result<List<DiaryEntry>> {
        return try {
            // 后端 /api/v1/diary 直接返回 List[DiaryEntry]，无 {status, data} 包装
            val response = apiService.getDiaries(date)
            val result = response.map { obj ->
                DiaryEntry(
                    id = obj.string("id"),
                    timestamp = obj.long("timestamp") ?: 0L,
                    timeStr = obj.string("time_str"),
                    type = obj.string("type"),
                    content = obj.string("content"),
                    thought = obj["thought"]?.jsonPrimitive?.contentOrNull,
                    mood = obj.string("mood"),
                    tags = obj["tags"]?.jsonArray?.map { it.jsonPrimitive.content }.orEmpty(),
                    source = obj.string("source").ifEmpty { "user" },
                    // 作者展示名由后端权威画像给出；老后端没有该字段时留空，
                    // 由 DiaryEntry.authorLabel 回退到 source（UI 不做角色名硬编码）
                    sourceLabel = obj.string("source_label")
                )
            }
            Result.success(result)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // ==================== 专注番茄钟跨端同步实现 ====================

    override suspend fun getFocusSessionCurrent(userId: String): Result<JsonObject> {
        return try {
            // 后端返回 {status, session} 或空对象；无会话时 data 包装里 session 为 null
            val resp = apiService.getFocusSessionCurrent(userId)
            val data = resp["data"]?.jsonObject ?: resp
            val session = data["session"]?.jsonObject
            if (session == null) {
                // 包装成空对象,调用方据此判断无会话
                Result.success(JsonObject(emptyMap()))
            } else {
                Result.success(session)
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun startFocusSession(
        subject: String, plannedMinutes: Int, mode: String
    ): Result<JsonObject> {
        return try {
            val resp = apiService.startFocusSession(
                buildJsonObject {
                    put("subject", subject)
                    put("planned_minutes", plannedMinutes)
                    put("mode", mode)
                }
            )
            val data = resp["data"]?.jsonObject ?: resp
            Result.success(data["session"]?.jsonObject ?: data)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun pauseFocusSession(id: String): Result<JsonObject> {
        return try {
            Result.success(apiService.pauseFocusSession(id))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun resumeFocusSession(id: String): Result<JsonObject> {
        return try {
            Result.success(apiService.resumeFocusSession(id))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun finishFocusSession(
        id: String, selfRating: Int?, note: String?
    ): Result<JsonObject> {
        return try {
            val resp = apiService.finishFocusSession(
                id,
                buildJsonObject {
                    selfRating?.let { put("self_rating", it) }
                    note?.let { put("note", it) }
                }
            )
            val data = resp["data"]?.jsonObject ?: resp
            Result.success(data["session"]?.jsonObject ?: data)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getFocusSessionSummary(id: String): Result<JsonObject> {
        return try {
            val resp = apiService.getFocusSessionSummary(id)
            val data = resp["data"]?.jsonObject ?: resp
            Result.success(data["session"]?.jsonObject ?: data)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getFocusSessionHistory(userId: String, limit: Int): Result<JsonObject> {
        return try {
            val resp = apiService.getFocusSessionHistory(userId, limit)
            val data = resp["data"]?.jsonObject ?: resp
            Result.success(data["sessions"]?.jsonObject ?: data)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private suspend fun refreshFiles() {
        val files = getFiles()
        _filesFlow.tryEmit(files)
    }
    
    private suspend fun refreshStudyMode() {
        val state = getStudyModeState()
        _studyModeFlow.tryEmit(state)
    }
    
    private fun getFileName(uri: Uri): String {
        var name = "unknown"
        context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (cursor.moveToFirst() && nameIndex >= 0) {
                name = cursor.getString(nameIndex)
            }
        }
        return name
    }
    
    private fun getFileSize(uri: Uri): Long {
        var size = 0L
        context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
            if (cursor.moveToFirst() && sizeIndex >= 0) {
                size = cursor.getLong(sizeIndex)
            }
        }
        return size
    }
    
    private fun copyToTempFile(uri: Uri, fileName: String): File {
        val tempDir = File(context.cacheDir, "study_upload")
        tempDir.mkdirs()
        val tempFile = File(tempDir, fileName)
        
        context.contentResolver.openInputStream(uri)?.use { input ->
            FileOutputStream(tempFile).use { output ->
                input.copyTo(output)
            }
        }
        
        return tempFile
    }
}

/**
 * 扩展函数：DTO 转换为 Domain
 */
private fun StudyFileDto.toDomain(): StudyFile {
    return StudyFile(
        id = id,
        name = name,
        size = size ?: 0,
        type = type ?: "application/octet-stream",
        status = when (status?.lowercase()) {
            "uploading" -> FileStatus.UPLOADING
            "processing" -> FileStatus.PROCESSING
            "ready" -> FileStatus.READY
            "error" -> FileStatus.ERROR
            else -> FileStatus.READY
        },
        uploadProgress = uploadProgress ?: 1f,
        uploadedAt = uploadedAt?.let { Instant.parse(it) } ?: Instant.now(),
        processedAt = processedAt?.let { Instant.parse(it) },
        chunkCount = chunkCount ?: 0,
        errorMessage = errorMessage
    )
}

private fun StudyModeResponse.toDomain(): StudyModeState {
    return StudyModeState(
        isEnabled = enabled,
        activeFileIds = activeFileIds.toSet(),
        totalChunks = totalChunks
    )
}

// ==================== JsonObject 解析辅助扩展 ====================
// 后端返回 snake_case 字段,这里手动映射为 camelCase 领域模型。

/** 空数组兜底,避免 null JsonArray 导致 NPE */
private fun JsonArray?.orEmpty(): JsonArray = this ?: JsonArray(emptyList())

/** 从 JsonObject 取字符串字段,缺失或类型不匹配返回空串 */
private fun JsonObject.string(key: String): String =
    this[key]?.jsonPrimitive?.contentOrNull.orEmpty()

/** 从 JsonObject 取 Int 字段,缺失或类型不匹配返回 null */
private fun JsonObject.int(key: String): Int? =
    this[key]?.jsonPrimitive?.intOrNull

/** 从 JsonObject 取 Boolean 字段,缺失或类型不匹配返回 null */
private fun JsonObject.boolean(key: String): Boolean? =
    this[key]?.jsonPrimitive?.booleanOrNull
