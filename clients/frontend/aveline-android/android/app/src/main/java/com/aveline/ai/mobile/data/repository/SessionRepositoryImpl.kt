package com.aveline.ai.mobile.data.repository

import com.aveline.ai.mobile.data.local.database.dao.SessionDao
import com.aveline.ai.mobile.data.local.database.entity.SessionEntity
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.dto.CreateSessionRequest
import com.aveline.ai.mobile.data.remote.dto.SessionDto
import com.aveline.ai.mobile.domain.models.Session
import com.aveline.ai.mobile.domain.repository.SessionRepository
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CoroutineScope
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SessionRepositoryImpl @Inject constructor(
    private val apiService: AvelineApiService,
    private val sessionDao: SessionDao,
    private val appPreferences: AppPreferences
) : SessionRepository {

    private val scope = CoroutineScope(Dispatchers.IO)

    private val _currentSession = MutableStateFlow<Session?>(null)
    val currentSessionFlow = _currentSession.asStateFlow()

    private var lastSyncTime: Long = 0

    companion object {
        private const val SYNC_INTERVAL_MS = 30_000L
    }

    override suspend fun getSessions(): Result<List<Session>> {
        return try {
            val response = apiService.getSessions()
            val source = if (response.sessions.isNotEmpty()) response.sessions else response.data
            val sessions = source
                .filter { it.id.isNotBlank() }
                .map { it.toDomainModel() }

            sessions.forEach { session ->
                sessionDao.insertSession(session.toEntity())
            }

            lastSyncTime = System.currentTimeMillis()
            Result.success(sessions)
        } catch (e: Exception) {
            try {
                val localSessions = getLocalSessions()
                if (localSessions.isNotEmpty()) {
                    return Result.success(localSessions)
                }
            } catch (_: Exception) {
            }
            Result.failure(e)
        }
    }

    private suspend fun getLocalSessions(): List<Session> {
        return withContext(Dispatchers.IO) {
            val entities = sessionDao.getAllSessionsOnce()
            entities.map { it.toDomainModel() }
        }
    }

    override suspend fun createSession(title: String): Result<Session> {
        return try {
            val request = CreateSessionRequest(title = title)
            val response = apiService.createSession(request)
            val sessionDto = response.session ?: response.data
            val session = (sessionDto ?: SessionDto(id = System.currentTimeMillis().toString(), title = title)).toDomainModel()
            sessionDao.insertSession(session.toEntity())
            Result.success(session)
        } catch (e: Exception) {
            val localSession = Session(
                id = "local_${System.currentTimeMillis()}",
                title = title,
                createdAt = System.currentTimeMillis(),
                updatedAt = System.currentTimeMillis(),
                isPinned = false
            )
            sessionDao.insertSession(localSession.toEntity())
            Result.success(localSession)
        }
    }

    override suspend fun deleteSession(sessionId: String): Result<Unit> {
        return try {
            sessionDao.deleteSession(sessionId)

            if (appPreferences.currentSessionId == sessionId) {
                appPreferences.currentSessionId = null
            }

            try {
                apiService.deleteSession(sessionId)
            } catch (_: Exception) {
            }

            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun updateSession(session: Session): Result<Unit> {
        return try {
            sessionDao.updateSession(session.toEntity())

            try {
                apiService.updateSession(session.id, mapOf("title" to session.title))
            } catch (_: Exception) {
            }

            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * 在本地 DB 中 upsert session（不同步后端）。
     * 用于 Android 端按 persona 隔离消息（sessionId = "web_{personaFilename}"）。
     */
    override suspend fun upsertLocalSession(session: Session): Result<Unit> {
        return try {
            withContext(Dispatchers.IO) {
                sessionDao.insertSession(session.toEntity())
            }
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * 观察“当前会话”，会跟随 [AppPreferences.currentSessionId] 的变化重新发射。
     *
     * 关键：sessionId 必须来自响应式流而非一次性快照。早期实现把 sessionId 读成局部
     * 变量，Flow 建立后就锁死在首个会话上；切换角色改写 currentSessionId 时下游
     * 感知不到，于是所有角色的聊天窗口都渲染同一个 session 的消息。
     */
    @OptIn(ExperimentalCoroutinesApi::class)
    override fun observeCurrentSession(): Flow<Session?> {
        if (appPreferences.currentSessionId == null) {
            appPreferences.currentSessionId = "default"
        }

        return appPreferences.currentSessionIdFlow
            .map { it ?: "default" }
            .distinctUntilChanged()
            .flatMapLatest { sessionId ->
                ensureDefaultSessionExists(sessionId)
                sessionDao.observeSessions()
                    .map { entities ->
                        entities.find { it.id == sessionId }?.toDomainModel()
                    }
            }
    }

    private fun ensureDefaultSessionExists(sessionId: String) {
        scope.launch {
            val existing = sessionDao.getSessionById(sessionId)
            if (existing == null && sessionId == "default") {
                val defaultSession = Session(
                    id = "default",
                    title = "默认会话",
                    createdAt = System.currentTimeMillis(),
                    updatedAt = System.currentTimeMillis(),
                    isPinned = false
                )
                sessionDao.insertSession(defaultSession.toEntity())
            }
        }
    }

    suspend fun syncFromBackendIfNeeded() {
        val currentTime = System.currentTimeMillis()
        if (currentTime - lastSyncTime < SYNC_INTERVAL_MS) return

        try {
            val response = apiService.getSessions()
            val source = if (response.sessions.isNotEmpty()) response.sessions else response.data
            val sessions = source
                .filter { it.id.isNotBlank() }
                .map { it.toDomainModel() }

            sessions.forEach { session ->
                sessionDao.insertSession(session.toEntity())
            }

            lastSyncTime = currentTime
        } catch (_: Exception) {
        }
    }
}

private fun SessionDto.toDomainModel(): Session {
    val now = System.currentTimeMillis()
    val created = if (createdAt > 0) createdAt else now
    val updated = if (updatedAt > 0) updatedAt else created
    return Session(
        id = id,
        title = title,
        createdAt = created,
        updatedAt = updated,
        isPinned = isPinned
    )
}

private fun Session.toEntity(): SessionEntity {
    return SessionEntity(
        id = id,
        title = title,
        createdAt = createdAt,
        updatedAt = updatedAt,
        isPinned = isPinned
    )
}

private fun SessionEntity.toDomainModel(): Session {
    return Session(
        id = id,
        title = title,
        createdAt = createdAt,
        updatedAt = updatedAt,
        isPinned = isPinned
    )
}
