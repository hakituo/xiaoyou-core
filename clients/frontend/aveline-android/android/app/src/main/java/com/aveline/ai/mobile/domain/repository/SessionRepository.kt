package com.aveline.ai.mobile.domain.repository

import com.aveline.ai.mobile.domain.models.Session
import kotlinx.coroutines.flow.Flow

/**
 * Repository interface for session management operations.
 * Abstracts data sources for session CRUD operations.
 */
interface SessionRepository {
    /**
     * Get all sessions from the backend.
     * @return Result containing list of sessions or error
     */
    suspend fun getSessions(): Result<List<Session>>
    
    /**
     * Create a new session.
     * @param title The title for the new session
     * @return Result containing the created session or error
     */
    suspend fun createSession(title: String): Result<Session>
    
    /**
     * Delete a session.
     * @param sessionId The ID of the session to delete
     * @return Result indicating success or failure
     */
    suspend fun deleteSession(sessionId: String): Result<Unit>
    
    /**
     * Update an existing session.
     * @param session The session with updated data
     * @return Result indicating success or failure
     */
    suspend fun updateSession(session: Session): Result<Unit>
    
    /**
     * Observe the current active session.
     * @return Flow that emits the current session when it changes
     */
    fun observeCurrentSession(): Flow<Session?>

    /**
     * 在本地 DB 中创建或替换一个 session（不同步到后端）。
     *
     * 用于 Android 端按 persona 隔离本地消息：让 messages.sessionId = "web_{personaFilename}"
     * 区分不同 persona 的消息。跨平台共享由后端 conversation_id 规范化处理，与本地 sessionId
     * 是不同维度。
     *
     * @param session 完整的 Session 域对象（含 id/title/createdAt/...）
     * @return Result indicating success or failure
     */
    suspend fun upsertLocalSession(session: Session): Result<Unit>
}
