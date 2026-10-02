package com.aveline.ai.mobile.data.local.database.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import com.aveline.ai.mobile.data.local.database.entity.NotificationEntity

@Dao
interface NotificationDao {
    @Insert
    suspend fun insert(notification: NotificationEntity)

    @Query("SELECT * FROM notifications WHERE isSent = 0 ORDER BY timestamp ASC")
    suspend fun getUnsentNotifications(): List<NotificationEntity>

    @Query("UPDATE notifications SET isSent = 1 WHERE id IN (:ids)")
    suspend fun markAsSent(ids: List<Long>)

    @Query("DELETE FROM notifications WHERE isSent = 1 AND timestamp < :olderThan")
    suspend fun deleteOldSent(olderThan: Long)
}
