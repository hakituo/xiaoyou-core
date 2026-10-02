package com.aveline.ai.mobile.data.local.database.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "health_data")
data class HealthDataEntity(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val type: String, // 例如 "vital_signs"(生命体征)、"body_metrics"(身体指标)
    val jsonData: String,
    val timestamp: Long,
    val isSent: Boolean = false
)
