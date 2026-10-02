package com.aveline.ai.mobile.data.local.database

import com.aveline.ai.mobile.data.local.database.entity.MessageEntity
import java.security.MessageDigest

/** 确定性副本 ID 使迁移重试不重复插入，旧容器原文和分支原样保留以便恢复。 */
internal fun mergedMessageId(sessionId: String, messageId: String): String {
    val bytes = MessageDigest.getInstance("SHA-256")
        .digest("$sessionId\u0000$messageId".toByteArray(Charsets.UTF_8))
    return "merged_" + bytes.joinToString("") { "%02x".format(it) }
}

data class RoleHistoryMergePlan(
    val targetSessionId: String,
    val sourceCounts: Map<String, Int>,
    val messages: List<MessageEntity>,
    val addedCount: Int
)

/**
 * 只处理调用方用 role_id 确认属于同一角色的容器。
 * 各源当前分支按时间交错接成连续历史，保留各源内部先后顺序及所有非当前版本。
 * 不按相似文本删除消息；相同迁移 ID 只复用已有副本，不拿旧内容覆盖新回复。
 */
internal fun planRoleHistoryMerge(
    targetSessionId: String,
    sources: Map<String, List<MessageEntity>>
): RoleHistoryMergePlan {
    require(sources.all { (session, rows) -> rows.all { it.sessionId == session } }) {
        "会话消息归属不一致，停止迁移"
    }
    val target = sources[targetSessionId].orEmpty()
    val targetIds = target.mapTo(mutableSetOf()) { it.id }
    val copies = linkedMapOf<String, MessageEntity>()
    val paths = mutableListOf<MutableList<MessageEntity>>()
    val siblingGroups = mutableMapOf<String, List<String>>()

    sources.toSortedMap().forEach { (session, rows) ->
        if (rows.isEmpty()) return@forEach
        val ids = rows.mapTo(mutableSetOf()) { it.id }
        val idMap = rows.associate { it.id to if (session == targetSessionId) it.id else mergedMessageId(session, it.id) }
        val grouped = rows.groupBy { it.parentId to it.isUser }
        val newIds = mutableSetOf<String>()
        rows.forEach { row ->
            val copiedId = idMap.getValue(row.id)
            if (session == targetSessionId || copiedId !in targetIds) {
                copies[copiedId] = row.copy(
                    id = copiedId, sessionId = targetSessionId,
                    parentId = row.parentId?.let { idMap[it] }
                )
                newIds += row.id
                siblingGroups[copiedId] = grouped.getValue(row.parentId to row.isUser)
                    .map { idMap.getValue(it.id) }
            }
        }
        // 断链片段也保留；不把因旧裁剪丢根的最新一段遗留在旧容器里。
        val roots = rows.filter { it.parentId == null || it.parentId !in ids }
        require(roots.isNotEmpty()) { "会话存在循环父链，停止迁移: $session" }
        val selectedRoots = roots.groupBy { it.parentId to it.isUser }.values.flatMap { group ->
            group.filter { it.isActiveVariant }.ifEmpty { listOf(group.minBy { it.timestamp }) }
        }
        // 旧版可能把多段历史都立为 active 根。这些是待拼接片段，不能互相重设父链。
        selectedRoots.groupBy { it.parentId to it.isUser }.values.filter { it.size > 1 }.flatten().forEach {
            val id = idMap.getValue(it.id)
            siblingGroups[id] = listOf(id)
        }
        selectedRoots.forEach { root ->
            val path = selectActiveMessageEntities(rows, root.id)
                .filter { it.id in newIds }.map { copies.getValue(idMap.getValue(it.id)) }
            if (path.isNotEmpty()) paths += path.toMutableList()
        }
    }
    val addedCount = copies.keys.count { it !in targetIds }
    // 迁移完成后再次刷新列表，不重置用户后来选中的分支。
    if (addedCount == 0) return RoleHistoryMergePlan(targetSessionId, sources.mapValues { it.value.size }, emptyList(), 0)

    var previous: String? = null
    val visited = mutableSetOf<String>()
    while (paths.any { it.isNotEmpty() }) {
        val path = paths.filter { it.isNotEmpty() }
            .minWith(compareBy<MutableList<MessageEntity>> { it.first().timestamp }.thenBy { it.first().id })
        val row = path.removeAt(0)
        if (!visited.add(row.id)) continue
        siblingGroups[row.id].orEmpty().forEach { id ->
            copies[id]?.let { sibling ->
                copies[id] = sibling.copy(parentId = previous, isActiveVariant = id == row.id)
            }
        }
        previous = row.id
    }
    return RoleHistoryMergePlan(targetSessionId, sources.mapValues { it.value.size }, copies.values.toList(), addedCount)
}
