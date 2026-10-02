package com.aveline.ai.mobile.domain.models

import kotlinx.serialization.Serializable

/**
 * Domain model for a chat session.
 * Represents a conversation session in the business logic layer.
 */
@Serializable
data class Session(
    val id: String,
    val title: String,
    val createdAt: Long,
    val updatedAt: Long,
    val isPinned: Boolean = false
)
