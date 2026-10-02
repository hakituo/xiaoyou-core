package com.aveline.ai.mobile.data.local.database.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import com.aveline.ai.mobile.data.local.database.entity.HealthDataEntity

@Dao
interface HealthDataDao {
    @Insert
    suspend fun insert(healthData: HealthDataEntity)

    @Query("SELECT * FROM health_data WHERE isSent = 0 ORDER BY timestamp ASC")
    suspend fun getUnsentData(): List<HealthDataEntity>

    @Query("UPDATE health_data SET isSent = 1 WHERE id IN (:ids)")
    suspend fun markAsSent(ids: List<Long>)

    @Query("DELETE FROM health_data WHERE isSent = 1 AND timestamp < :olderThan")
    suspend fun deleteOldSent(olderThan: Long)
}
