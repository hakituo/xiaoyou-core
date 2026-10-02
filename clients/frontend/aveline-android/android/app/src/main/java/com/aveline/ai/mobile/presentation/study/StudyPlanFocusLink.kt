package com.aveline.ai.mobile.presentation.study

import com.aveline.ai.mobile.domain.models.StudyPlanItem

data class StudyPlanFocusTarget(
    val itemId: String,
    val planDate: String? = null
)

/**
 * Study Plan 与 Focus 之间的轻量进程内桥。
 *
 * 新 Today UI 会先用 [select] 显式写入用户点击的稳定 plan_item_id；Focus 随后消费它。
 * 标题索引只保留给旧计划页调用链做兼容兜底，避免同名任务成为新链路的定位方式。
 * 同时保留该 ID 所属的 plan date，后端 finish 时才能精确回写对应日期的 plan.json。
 */
object StudyPlanFocusLink {
    @Volatile
    private var idsByTitle: Map<String, List<String>> = emptyMap()

    @Volatile
    private var planDateById: Map<String, String> = emptyMap()

    @Volatile
    private var selectedPlanItemId: String? = null

    fun replace(items: List<StudyPlanItem>, planDate: String = "") {
        idsByTitle = items
            .filter { it.id.isNotBlank() && it.content.isNotBlank() }
            .groupBy({ it.content.trim() }, { it.id })
        val stableDate = planDate.trim()
        planDateById = if (stableDate.isBlank()) {
            emptyMap()
        } else {
            items
                .asSequence()
                .map { it.id.trim() }
                .filter { it.isNotBlank() }
                .associateWith { stableDate }
        }
    }

    fun select(itemId: String) {
        selectedPlanItemId = itemId.trim().takeIf { it.isNotBlank() }
    }

    fun consumeSelectedTarget(): StudyPlanFocusTarget? {
        val selected = selectedPlanItemId
        selectedPlanItemId = null
        return selected?.let {
            StudyPlanFocusTarget(
                itemId = it,
                planDate = planDateById[it]
            )
        }
    }

    fun consumeSelected(): String? = consumeSelectedTarget()?.itemId

    fun resolveUniqueTarget(title: String): StudyPlanFocusTarget? {
        // Today/新计划页显式选择的 ID 优先；标题只用于旧调用链兜底。
        consumeSelectedTarget()?.let { return it }
        val ids = idsByTitle[title.trim()].orEmpty().distinct()
        val itemId = ids.singleOrNull() ?: return null
        return StudyPlanFocusTarget(
            itemId = itemId,
            planDate = planDateById[itemId]
        )
    }

    fun resolveUnique(title: String): String? = resolveUniqueTarget(title)?.itemId
}
