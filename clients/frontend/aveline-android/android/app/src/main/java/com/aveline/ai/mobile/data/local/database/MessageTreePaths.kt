package com.aveline.ai.mobile.data.local.database

import com.aveline.ai.mobile.data.local.database.entity.MessageEntity

/** 页面、上下文和迁移共用相同的分支选择规则。 */
internal fun selectActiveMessageEntities(
    entities: List<MessageEntity>,
    rootId: String? = null
): List<MessageEntity> {
    val ordered = entities.sortedWith(compareBy<MessageEntity> { it.timestamp }.thenBy { it.id })
    val children = ordered.groupBy { it.parentId }
    var current = rootId?.let { id -> ordered.firstOrNull { it.id == id } }
        ?: children[null]?.firstOrNull { it.isActiveVariant }
        ?: children[null]?.firstOrNull() ?: ordered.firstOrNull()
    val visited = mutableSetOf<String>()
    val result = mutableListOf<MessageEntity>()
    while (current != null && visited.add(current.id)) {
        result += current
        current = children[current.id]?.firstOrNull { it.isActiveVariant }
            ?: children[current.id]?.firstOrNull()
    }
    return result
}
