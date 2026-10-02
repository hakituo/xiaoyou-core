package com.aveline.ai.mobile.data.local.database.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import com.aveline.ai.mobile.data.local.database.entity.SessionEntity
import kotlinx.coroutines.flow.Flow

/**
 * Data Access Object for session operations.
 * 
 * Provides methods to manage chat sessions in the local database.
 */
@Dao
interface SessionDao {
    
    /**
     * Observes all sessions, ordered by update time (newest first).
     * Pinned sessions appear first.
     * 
     * @return Flow of session list that updates automatically
     */
    @Query("SELECT * FROM sessions ORDER BY isPinned DESC, updatedAt DESC")
    fun observeSessions(): Flow<List<SessionEntity>>
    
    /**
     * Inserts a session, replacing if it already exists.
     * 
     * @param session The session to insert
     */
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertSession(session: SessionEntity)
    
    /**
     * 批量插入会话,单事务提交,供数据导入使用。
     *
     * @param sessions 会话列表
     */
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertSessions(sessions: List<SessionEntity>)
    
    /**
     * Deletes a specific session by ID.
     * 
     * @param sessionId The ID of the session to delete
     */
    @Query("DELETE FROM sessions WHERE id = :sessionId")
    suspend fun deleteSession(sessionId: String)
    
    /**
     * Updates an existing session.
     * 
     * @param session The session with updated data
     */
    @Update
    suspend fun updateSession(session: SessionEntity)
    
    /**
     * Gets a specific session by ID.
     * 
     * @param sessionId The session ID
     * @return The session entity, or null if not found
     */
    @Query("SELECT * FROM sessions WHERE id = :sessionId")
    suspend fun getSessionById(sessionId: String): SessionEntity?

    @Query("SELECT * FROM sessions ORDER BY isPinned DESC, updatedAt DESC")
    suspend fun getAllSessionsOnce(): List<SessionEntity>

    /**
     * 删除所有会话(用于清除全部数据)。
     * 注意:调用方应先清除 messages 表(外键关系)。
     */
    @Query("DELETE FROM sessions")
    suspend fun deleteAllSessions()
}
