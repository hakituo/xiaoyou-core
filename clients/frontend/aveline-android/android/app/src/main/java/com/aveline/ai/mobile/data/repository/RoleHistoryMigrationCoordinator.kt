package com.aveline.ai.mobile.data.repository

import com.aveline.ai.mobile.domain.repository.ChatRepository
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import javax.inject.Inject
import javax.inject.Singleton

/** 角色列表发布前完成本地迁移，使列表、聊天页和主动消息看到同一份会话映射。 */
@Singleton
class RoleHistoryMigrationCoordinator @Inject constructor(
    private val chatRepository: ChatRepository
) {
    private val mutex = Mutex()
    private val completed = mutableSetOf<String>()

    suspend fun migrate(personas: JsonArray) = mutex.withLock {
        val rows = personas.map { it.jsonObject }
        val groups = rows.filter { !it["role_id"]?.jsonPrimitive?.contentOrNull.isNullOrBlank() }
            .groupBy { it.getValue("role_id").jsonPrimitive.content }
        // 同名不同角色不能靠名字合并；只接纳此响应里唯一归属的旧名称。
        val aliasOwners = groups.flatMap { (roleId, items) ->
            items.flatMap { row ->
                (row["role_aliases"] as? JsonArray).orEmpty().map { it.jsonPrimitive.content to roleId }
            }
        }.groupBy({ it.first }, { it.second })
        for ((roleId, items) in groups) {
            val filenames = items.mapNotNull { it["filename"]?.jsonPrimitive?.contentOrNull }.toSet()
            val aliases = aliasOwners.filterValues { it.distinct() == listOf(roleId) }.keys + roleId
            val key = listOf(roleId, aliases.sorted().joinToString("|"), filenames.sorted().joinToString("|")).joinToString("\n")
            if (key in completed) continue
            chatRepository.mergeRoleHistory(roleId, aliases, filenames).getOrThrow()
            completed += key
        }
    }
}
