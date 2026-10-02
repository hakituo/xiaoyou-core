package com.aveline.ai.mobile.data.local.database.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Room entity for storing AI memory entries.
 * 
 * Memories are facts, preferences, events, or relationships that the AI learns
 * about the user over time.
 */
@Entity(tableName = "memories")
data class MemoryEntity(
    @PrimaryKey
    val id: String,
    val content: String,
    val type: String, // "fact", "preference", "event", "relationship"
    val importance: Float,
    val timestamp: Long,
    val tags: String // Comma-separated tags
)
