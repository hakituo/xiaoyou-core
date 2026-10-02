package com.aveline.ai.mobile.data.local.database.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.aveline.ai.mobile.data.local.database.entity.PersonaLocalMetaEntity
import kotlinx.coroutines.flow.Flow

/**
 * Persona 本地元数据 DAO：用户自定义昵称/头像的存储。
 */
@Dao
interface PersonaLocalMetaDao {

    /**
     * 观察所有 persona 的本地元数据。列表按 updatedAt 降序（最近改的在前），
     * 用于会话列表页合并显示。
     */
    @Query("SELECT * FROM persona_local_meta ORDER BY updatedAt DESC")
    fun observeAll(): Flow<List<PersonaLocalMetaEntity>>

    /** 一次性查询所有元数据 */
    @Query("SELECT * FROM persona_local_meta")
    suspend fun getAllOnce(): List<PersonaLocalMetaEntity>

    /** 按 persona filename 查询单条 */
    @Query("SELECT * FROM persona_local_meta WHERE personaFilename = :filename LIMIT 1")
    suspend fun getByFilename(filename: String): PersonaLocalMetaEntity?

    /** 按 persona filename 观察单条 */
    @Query("SELECT * FROM persona_local_meta WHERE personaFilename = :filename LIMIT 1")
    fun observeByFilename(filename: String): Flow<PersonaLocalMetaEntity?>

    /**
     * 保存或更新。filename 相同则覆盖（OnConflictStrategy.REPLACE）。
     */
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entity: PersonaLocalMetaEntity)

    /** 删除指定 persona 的本地元数据（如重置为默认） */
    @Query("DELETE FROM persona_local_meta WHERE personaFilename = :filename")
    suspend fun delete(filename: String)
}
