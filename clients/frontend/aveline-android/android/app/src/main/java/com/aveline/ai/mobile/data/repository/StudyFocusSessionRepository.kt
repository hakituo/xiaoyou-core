package com.aveline.ai.mobile.data.repository

import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import javax.inject.Inject
import javax.inject.Singleton

/**
 * FocusSession 新合同的薄数据层。
 *
 * 旧 [com.aveline.ai.mobile.domain.repository.StudyRepository] 继续兼容不带计划 ID 的调用；
 * 新计划链路从这里创建带 `plan_item_id` / `plan_date` 的 FocusSession，避免 ViewModel 直接依赖 Retrofit。
 */
@Singleton
class StudyFocusSessionRepository @Inject constructor(
    private val apiService: AvelineApiService
) {
    suspend fun startFocusSession(
        subject: String,
        plannedMinutes: Int,
        mode: String = "gentle",
        planItemId: String? = null,
        planDate: String? = null
    ): Result<JsonObject> = runCatching {
        val response = apiService.startFocusSession(
            buildJsonObject {
                put("subject", subject)
                put("planned_minutes", plannedMinutes)
                put("mode", mode)
                put("monitoring", false)
                planItemId?.takeIf { it.isNotBlank() }?.let { put("plan_item_id", it) }
                planDate?.takeIf { it.isNotBlank() }?.let { put("plan_date", it) }
            }
        )
        val data = response["data"]?.jsonObject ?: response
        data["session"]?.jsonObject ?: data
    }
}
