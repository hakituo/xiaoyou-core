package com.aveline.ai.mobile.data.repository

import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.dto.PersonaDto
import com.aveline.ai.mobile.data.remote.dto.SelectPersonaRequest
import com.aveline.ai.mobile.domain.models.Persona
import com.aveline.ai.mobile.domain.models.PersonaRequest
import com.aveline.ai.mobile.domain.repository.PersonaRepository
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import java.time.Instant
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 人格仓库实现
 * 
 * 管理人格配置的选择和创建
 * 
 * Requirements: 11.1, 11.2, 11.3, 11.4, 11.5
 */
@Singleton
class PersonaRepositoryImpl @Inject constructor(
    private val apiService: AvelineApiService,
    private val historyMigration: RoleHistoryMigrationCoordinator
) : PersonaRepository {
    
    private val _personasFlow = MutableSharedFlow<List<Persona>>(replay = 1)
    private val _activePersonaFlow = MutableSharedFlow<Persona?>(replay = 1)
    
    @Volatile
    private var cachedPersonas: List<Persona> = emptyList()
    @Volatile
    private var cachedActivePersona: Persona? = null
    
    override suspend fun getPersonas(): List<Persona> {
        return try {
            val response = apiService.getPersonas()
            val personas = response.map { it.toDomain() }
            cachedPersonas = personas
            _personasFlow.tryEmit(personas)
            personas
        } catch (e: Exception) {
            cachedPersonas
        }
    }
    
    override suspend fun getActivePersona(): Persona? {
        return try {
            val response = apiService.getActivePersona()
            val persona = response.data?.toDomain()
            if (persona != null) {
                cachedActivePersona = persona
                _activePersonaFlow.tryEmit(persona)
            }
            persona
        } catch (e: Exception) {
            cachedActivePersona
        }
    }
    
    override suspend fun selectPersona(personaId: String): Result<Unit> {
        return try {
            val response = apiService.selectPersona(SelectPersonaRequest(personaId))
            
            if (response.isSuccessful) {
                // 刷新激活的人格
                getActivePersona()
                Result.success(Unit)
            } else {
                Result.failure(Exception("选择失败: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    override suspend fun createPersona(request: PersonaRequest): Result<Persona> {
        return try {
            val persona = apiService.createPersona(request.toDto()).toDomain()
            invalidatePersonasRawCache()
            refreshPersonas()
            Result.success(persona)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    override suspend fun updatePersona(personaId: String, request: PersonaRequest): Result<Persona> {
        return try {
            val persona = apiService.updatePersona(personaId, request.toDto()).toDomain()
            invalidatePersonasRawCache()
            refreshPersonas()
            Result.success(persona)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    override suspend fun deletePersona(personaId: String): Result<Unit> {
        return try {
            val response = apiService.deletePersona(personaId)
            
            if (response.isSuccessful) {
                invalidatePersonasRawCache()
                refreshPersonas()
                Result.success(Unit)
            } else {
                Result.failure(Exception("删除失败: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    override fun observePersonas(): Flow<List<Persona>> = _personasFlow.asSharedFlow()
    
    override fun observeActivePersona(): Flow<Persona?> = _activePersonaFlow.asSharedFlow()

    override suspend fun getPersonasRaw(): Result<JsonArray> {
        return try {
            val personas = apiService.getPersonasRaw()
            historyMigration.migrate(personas)
            Result.success(personas)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /** 进程级 persona 原始列表快照；见 [getPersonasRawCached]。 */
    @Volatile
    private var cachedPersonasRaw: JsonArray? = null

    /** 单飞锁：并发调用只放一个请求出去，其余等它的结果。 */
    private val personasRawMutex = Mutex()

    override suspend fun getPersonasRawCached(): Result<JsonArray> {
        cachedPersonasRaw?.let { return Result.success(it) }
        return personasRawMutex.withLock {
            cachedPersonasRaw?.let { return@withLock Result.success(it) }
            getPersonasRaw().onSuccess { cachedPersonasRaw = it }
        }
    }

    /** persona 列表内容发生变化时作废快照，避免缓存住旧的角色/默认值。 */
    private fun invalidatePersonasRawCache() {
        cachedPersonasRaw = null
    }

    override suspend fun getAvailableVoices(): Result<List<String>> {
        return try {
            val names = apiService.getVoices().allVoices
                .map { it.name.ifBlank { it.id } }
                .filter { it.isNotBlank() }
            Result.success(names)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getActivePersonaRaw(): Result<JsonObject> {
        return try {
            Result.success(apiService.getActivePersonaRaw())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    private suspend fun refreshPersonas() {
        val personas = getPersonas()
        _personasFlow.tryEmit(personas)
    }
}

/**
 * 扩展函数：DTO 转换为 Domain
 */
private fun PersonaDto.toDomain(): Persona {
    return Persona(
        id = id,
        name = name ?: "",
        description = description ?: "",
        systemPrompt = systemPrompt ?: "",
        avatarUrl = avatarUrl,
        traits = traits ?: emptyList(),
        isDefault = isDefault ?: false,
        isCustom = isCustom ?: false,
        createdAt = createdAt?.let { Instant.parse(it) } ?: Instant.now(),
        updatedAt = updatedAt?.let { Instant.parse(it) } ?: Instant.now()
    )
}

private fun PersonaRequest.toDto(): com.aveline.ai.mobile.data.remote.dto.PersonaRequest {
    return com.aveline.ai.mobile.data.remote.dto.PersonaRequest(
        name = name,
        description = description,
        systemPrompt = systemPrompt,
        avatarUrl = avatarUrl,
        traits = traits
    )
}
