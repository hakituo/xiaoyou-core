package com.aveline.ai.mobile.domain.repository

import android.net.Uri
import com.aveline.ai.mobile.domain.models.CalendarDay
import com.aveline.ai.mobile.domain.models.DailyContent
import com.aveline.ai.mobile.domain.models.DiaryEntry
import com.aveline.ai.mobile.domain.models.DailyNote
import com.aveline.ai.mobile.domain.models.DailyNoteContent
import com.aveline.ai.mobile.domain.models.LatestProgress
import com.aveline.ai.mobile.domain.models.LibraryNote
import com.aveline.ai.mobile.domain.models.StudyFile
import com.aveline.ai.mobile.domain.models.StudyModeState
import kotlinx.coroutines.flow.Flow
import kotlinx.serialization.json.JsonObject

/**
 * 学习模块仓库接口
 * 
 * 定义学习文件的管理操作
 * 
 * Requirements: 10.1, 10.2, 10.5, 10.7
 */
interface StudyRepository {
    
    /**
     * 获取所有学习文件
     */
    suspend fun getFiles(): List<StudyFile>
    
    /**
     * 上传学习文件
     * 
     * @param uri 文件 URI
     * @param onProgress 进度回调
     */
    suspend fun uploadFile(
        uri: Uri,
        onProgress: (Float) -> Unit = {}
    ): Result<StudyFile>
    
    /**
     * 删除学习文件
     */
    suspend fun deleteFile(fileId: String): Result<Unit>
    
    /**
     * 获取学习模式状态
     */
    suspend fun getStudyModeState(): StudyModeState
    
    /**
     * 启用/禁用学习模式
     */
    suspend fun setStudyModeEnabled(enabled: Boolean): Result<Unit>
    
    /**
     * 设置活跃的学习文件
     */
    suspend fun setActiveFiles(fileIds: Set<String>): Result<Unit>
    
    /**
     * 观察学习文件变化
     */
    fun observeFiles(): Flow<List<StudyFile>>
    
    /**
     * 观察学习模式状态
     */
    fun observeStudyMode(): Flow<StudyModeState>

    /** 获取学科列表 */
    suspend fun getSubjects(): Result<JsonObject>

    /** 添加单词到学习队列 */
    suspend fun addVocabulary(word: String, definition: String? = null): Result<JsonObject>

    /** 搜索词典 */
    suspend fun searchDictionary(query: String): Result<JsonObject>

    // ==================== 词汇复习会话相关接口 ====================

    /** 获取每日词汇列表（含翻译、短语、例句等完整信息）
     * @param order 新词排序: sequential(顺序) / shuffle(乱序)
     */
    suspend fun getDailyVocabulary(count: Int = 20, order: String = "sequential"): Result<JsonObject>

    /** 获取从未学过的新词（不在 progress 里的词） */
    suspend fun getNewWords(count: Int = 20, order: String = "sequential"): Result<JsonObject>

    /** 获取复习总览（今日待复习数、连续天数、记忆曲线等） */
    suspend fun getReviewOverview(): Result<JsonObject>

    /** 获取记忆保持曲线数据 */
    suspend fun getMemoryCurve(): Result<JsonObject>

    /** 获取高错词列表 */
    suspend fun getMistakes(): Result<JsonObject>

    /** 手动记录当天背了多少个单词 */
    suspend fun addManualStudy(count: Int, date: String? = null): Result<JsonObject>

    /** 获取手动背诵统计 */
    suspend fun getManualStudyStats(days: Int = 7, date: String? = null): Result<JsonObject>

    /** 获取词书统计:可用词书列表与当前词书 */
    suspend fun getVocabBookStats(): Result<JsonObject>

    /** 获取词书内单词分页列表 */
    suspend fun getBookWords(page: Int = 1, pageSize: Int = 50): Result<JsonObject>

    /** 切换当前词书 */
    suspend fun switchVocabBook(filename: String): Result<JsonObject>

    /** 开始一次词汇复习会话 */
    suspend fun startReviewSession(): Result<JsonObject>

    /** 提交当前卡片的复习质量评分 */
    suspend fun submitReview(word: String, quality: Int): Result<JsonObject>

    /** 结束当前词汇复习会话 */
    suspend fun endReviewSession(): Result<JsonObject>

    // ==================== 工作区学习记录与会话相关接口 ====================

    /** 获取工作区学习概览面板（含连续天数、今日复习数、历史会话） */
    suspend fun getWorkspaceStudyPanel(historyLimit: Int = 20): Result<JsonObject>

    /** 写入一条工作区学习记录 */
    suspend fun recordWorkspaceStudy(payload: JsonObject): Result<JsonObject>

    /** 记录每日学习（开始学习会话） */
    suspend fun recordDailyStudy(payload: JsonObject): Result<JsonObject>

    /** 结束每日学习会话 */
    suspend fun finishDailyStudy(): Result<JsonObject>

    // ==================== Study/Daily 文件夹相关接口 ====================

    /**
     * 获取月度日历数据,返回每日是否有 diary/plan/progress。
     *
     * @param year 年份,如 2026
     * @param month 月份,如 6
     */
    suspend fun getCalendar(year: Int, month: Int): Result<List<CalendarDay>>

    /**
     * 获取指定日期的 diary/plan/progress 全部内容。
     *
     * @param date 日期字符串,格式 YYYY-MM-DD
     */
    suspend fun getDateContent(date: String): Result<DailyContent>

    /**
     * 获取所有专题笔记列表。
     */
    suspend fun getNotes(): Result<List<DailyNote>>

    /**
     * 读取指定专题笔记内容(按文件名查找)。
     *
     * @param filename 文件名,如 "知识网络与跨学科联系.md"
     */
    suspend fun getNote(filename: String): Result<DailyNoteContent>

    /**
     * 获取最新的学习进度文件内容。
     */
    suspend fun getLatestProgress(): Result<LatestProgress>

    /**
     * 获取学习库笔记列表(Study 根目录下各科目文件夹的 .md 文件)。
     */
    suspend fun getLibraryNotes(): Result<List<LibraryNote>>

    /**
     * 读取学习库中指定笔记内容(按相对路径)。
     *
     * @param path 相对于学习根目录的路径,如 "Mathematics/极限.md"
     */
    suspend fun getLibraryNote(path: String): Result<DailyNoteContent>

    /**
     * 覆盖写入指定日期的 plan.md(用于手动编辑计划后持久化)。
     *
     * @param date 日期字符串,格式 YYYY-MM-DD
     * @param plan 计划 Markdown 全文
     */
    suspend fun updatePlan(date: String, plan: String): Result<Unit>

    /**
     * 获取指定日期的日记列表（来自 journal 系统，按作者 source 分组）。
     *
     * 后端 /api/v1/diary 直接返回 List[DiaryEntry]，无 {status, data} 包装。
     *
     * @param date 日期字符串,格式 YYYY-MM-DD，null 则今天
     */
    suspend fun getDiaries(date: String?): Result<List<DiaryEntry>>

    // ==================== 专注番茄钟跨端同步接口 ====================

    /** 拉取当前进行中的专注会话（无则返回空对象，调用方据此判断是否有会话） */
    suspend fun getFocusSessionCurrent(userId: String = "default"): Result<JsonObject>

    /** 开始一个专注会话 */
    suspend fun startFocusSession(
        subject: String, plannedMinutes: Int, mode: String = "gentle"
    ): Result<JsonObject>

    /** 暂停当前专注会话 */
    suspend fun pauseFocusSession(id: String): Result<JsonObject>

    /** 恢复当前专注会话 */
    suspend fun resumeFocusSession(id: String): Result<JsonObject>

    /** 结束当前专注会话 */
    suspend fun finishFocusSession(id: String, selfRating: Int? = null, note: String? = null): Result<JsonObject>

    /** 查询某次会话总结 */
    suspend fun getFocusSessionSummary(id: String): Result<JsonObject>

    /** 查询历史会话列表 */
    suspend fun getFocusSessionHistory(userId: String = "default", limit: Int = 10): Result<JsonObject>
}
