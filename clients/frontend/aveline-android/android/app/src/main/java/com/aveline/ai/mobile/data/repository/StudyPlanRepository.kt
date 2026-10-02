package com.aveline.ai.mobile.data.repository

import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.domain.models.StudyPlan
import com.aveline.ai.mobile.domain.models.StudyPlanItem
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import javax.inject.Inject
import javax.inject.Singleton

/**
 * DailyPlan typed contract 的 Android 数据层。
 *
 * 计划页从这里直接读取后端 plan.json / DailyPlan 投影，不再解析 plan.md。
 * 旧 StudyRepository 中的 Markdown/兼容 CRUD 保留给历史调用点，本类是新计划 UI 的主路径。
 */
@Singleton
class StudyPlanRepository @Inject constructor(
    private val apiService: AvelineApiService
) {

    suspend fun getPlan(date: String): Result<StudyPlan> = runCatching {
        val response = apiService.getStudyDailyPlan(date)
        requireSuccess(response, "加载计划失败")
        val data = response["data"] as? JsonObject ?: response
        data.toStudyPlan(fallbackDate = date)
    }

    suspend fun updateItemStatus(
        date: String,
        itemId: String,
        done: Boolean
    ): Result<Unit> = write("更新计划项失败") {
        requireStableId(itemId)
        apiService.updateStudyPlanItemStatus(
            buildJsonObject {
                put("date", date)
                put("item_id", itemId)
                put("done", done)
            }
        )
    }

    suspend fun addItem(
        date: String,
        time: String,
        title: String,
        durationMinutes: Int?
    ): Result<Unit> = write("新增计划项失败") {
        apiService.addStudyPlanItem(
            buildJsonObject {
                put("date", date)
                put("time", time)
                put("title", title)
                durationMinutes?.let { put("duration_minutes", it) }
            }
        )
    }

    suspend fun updateItem(
        date: String,
        itemId: String,
        time: String,
        title: String,
        durationMinutes: Int?
    ): Result<Unit> = write("编辑计划项失败") {
        requireStableId(itemId)
        apiService.updateStudyPlanItem(
            buildJsonObject {
                put("date", date)
                put("item_id", itemId)
                put("time", time)
                put("title", title)
                durationMinutes?.let { put("duration_minutes", it) }
            }
        )
    }

    suspend fun removeItem(date: String, itemId: String): Result<Unit> =
        write("删除计划项失败") {
            requireStableId(itemId)
            apiService.removeStudyPlanItem(
                buildJsonObject {
                    put("date", date)
                    put("item_id", itemId)
                }
            )
        }

    private suspend fun write(
        fallbackMessage: String,
        call: suspend () -> JsonObject
    ): Result<Unit> = runCatching {
        val response = call()
        requireSuccess(response, fallbackMessage)
    }

    private fun requireSuccess(response: JsonObject, fallbackMessage: String) {
        val status = response.string("status")
        if (status == "error") {
            throw IllegalStateException(response.string("message").ifBlank { fallbackMessage })
        }
    }

    private fun requireStableId(itemId: String) {
        require(itemId.isNotBlank()) { "计划项缺少稳定 ID，请刷新计划后重试" }
    }
}

internal fun JsonObject.toStudyPlan(fallbackDate: String): StudyPlan {
    val items = (this["items"] as? JsonArray).orEmpty().mapNotNull { element ->
        (element as? JsonObject)?.toStudyPlanItem()
    }
    val checkpointReviews = (this["checkpoint_reviews"] as? JsonObject)
        ?.mapValues { (_, value) -> (value as? JsonPrimitive)?.doubleOrNull ?: 0.0 }
        .orEmpty()

    return StudyPlan(
        date = string("date").ifBlank { fallbackDate },
        dailyGoalMinutes = (int("daily_goal_minutes") ?: 0).coerceAtLeast(0),
        items = items,
        notes = nullableString("notes"),
        source = string("source"),
        checkpointReviews = checkpointReviews,
        revisionCount = int("revision_count") ?: 0,
        generatedAt = double("generated_at") ?: 0.0,
        updatedAt = double("updated_at") ?: 0.0
    )
}

private fun JsonObject.toStudyPlanItem(): StudyPlanItem {
    val durationMinutes = (int("estimated_duration_minutes") ?: 60).coerceAtLeast(1)
    val status = string("status").ifBlank { "pending" }
    return StudyPlanItem(
        id = string("id"),
        time = nullableString("time").orEmpty(),
        content = string("title"),
        duration = "${durationMinutes}分钟",
        isDone = status == "completed",
        description = nullableString("description"),
        category = string("category").ifBlank { "study" },
        subject = nullableString("subject"),
        priority = string("priority").ifBlank { "normal" },
        estimatedDurationMinutes = durationMinutes,
        actualMinutes = (double("actual_minutes") ?: 0.0).coerceAtLeast(0.0),
        status = status,
        reminderId = nullableString("reminder_id"),
        endReminderId = nullableString("end_reminder_id"),
        sourceKey = string("source_key"),
        sourceType = string("source_type").ifBlank { "algorithm" },
        score = double("score") ?: 0.0,
        carryoverCount = int("carryover_count") ?: 0,
        deferredFromDate = nullableString("deferred_from_date"),
        settlementReason = nullableString("settlement_reason"),
        createdAt = double("created_at") ?: 0.0,
        updatedAt = double("updated_at") ?: 0.0
    )
}

private fun JsonObject.string(key: String): String =
    (this[key] as? JsonPrimitive)?.contentOrNull.orEmpty()

private fun JsonObject.nullableString(key: String): String? =
    (this[key] as? JsonPrimitive)?.contentOrNull

private fun JsonObject.int(key: String): Int? =
    (this[key] as? JsonPrimitive)?.intOrNull

private fun JsonObject.double(key: String): Double? =
    (this[key] as? JsonPrimitive)?.doubleOrNull
