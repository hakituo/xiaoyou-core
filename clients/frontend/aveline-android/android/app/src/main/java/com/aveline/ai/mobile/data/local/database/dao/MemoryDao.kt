package com.aveline.ai.mobile.data.local.database.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.aveline.ai.mobile.data.local.database.entity.MemoryEntity
import kotlinx.coroutines.flow.Flow

/**
 * Data Access Object for memory operations.
 * 
 * Provides methods to manage AI memories in the local database.
 */
@Dao
interface MemoryDao {
    
    /**
     * Observes all memories, ordered by importance and timestamp.
     * 
     * @return Flow of memory list that updates automatically
     */
    @Query("SELECT * FROM memories ORDER BY importance DESC, timestamp DESC")
    fun observeMemories(): Flow<List<MemoryEntity>>
    
    /**
     * Inserts a memory, replacing if it already exists.
     * 
     * @param memory The memory to insert
     */
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertMemory(memory: MemoryEntity)
    
    /**
     * Deletes a specific memory by ID.
     * 
     * @param memoryId The ID of the memory to delete
     */
    @Query("DELETE FROM memories WHERE id = :memoryId")
    suspend fun deleteMemory(memoryId: String)
    
    /**
     * Searches memories by content or tags.
     * 
     * @param query The search query
     * @return List of matching memories
     */
    @Query("SELECT * FROM memories WHERE content LIKE '%' || :query || '%' OR tags LIKE '%' || :query || '%' ORDER BY importance DESC")
    suspend fun searchMemories(query: String): List<MemoryEntity>
}
