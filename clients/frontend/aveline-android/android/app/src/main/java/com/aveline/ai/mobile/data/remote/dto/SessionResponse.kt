package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.Serializable
import kotlinx.serialization.SerialName

/**
 * Response DTO for session operations.
 * 
 * @property status Response status
 * @property session The session object
 */
@Serializable
data class SessionResponse(
    val status: String = "",
    val session: SessionDto? = null,
    val data: SessionDto? = null
)

/**
 * Response DTO for listing sessions.
 * 
 * @property status Response status
 * @property sessions List of session objects
 */
@Serializable
data class SessionsResponse(
    val status: String = "",
    val sessions: List<SessionDto> = emptyList(),
    val data: List<SessionDto> = emptyList()
)

/**
 * Session DTO representing a chat session.
 * 
 * @property id Unique session identifier
 * @property title Session title
 * @property createdAt Creation timestamp in milliseconds
 * @property updatedAt Last update timestamp in milliseconds
 * @property isPinned Whether the session is pinned
 */
@Serializable
data class SessionDto(
    val id: String = "",
    val title: String = "",
    @SerialName("created_at")
    val createdAt: Long = 0L,
    @SerialName("updated_at")
    val updatedAt: Long = 0L,
    val isPinned: Boolean = false
)

/**
 * Request DTO for creating a new session.
 * 
 * @property title Session title
 */
@Serializable
data class CreateSessionRequest(
    val title: String = "New Chat"
)

/**
 * Response DTO for session history.
 * 
 * @property status Response status
 * @property messages List of messages in the session
 */
@Serializable
data class HistoryResponse(
    val status: String = "",
    val messages: List<MessageDto> = emptyList(),
    val data: List<MessageDto> = emptyList()
)
