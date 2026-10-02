package com.aveline.ai.mobile.data.remote.api

import kotlinx.serialization.json.JsonObject
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * Study/Daily 文件夹适配 API。
 * 从 AvelineApiService 拆出,避免单文件超500行。
 */
interface StudyDailyApiService {

    @GET("/api/v1/study-daily/calendar")
    suspend fun getStudyDailyCalendar(
        @Query("year") year: Int,
        @Query("month") month: Int
    ): JsonObject

    /** 旧聚合读取：diary / plan.md / progress。 */
    @GET("/api/v1/study-daily/date/{date}")
    suspend fun getStudyDailyDate(@Path("date") date: String): JsonObject

    /**
     * 结构化读取计划真源。
     *
     * 返回 DailyPlan typed JSON；Android 计划页应使用本接口，而不是解析 plan.md。
     */
    @GET("/api/v1/study-daily/plan")
    suspend fun getStudyDailyPlan(@Query("date") date: String): JsonObject

    @GET("/api/v1/study-daily/notes")
    suspend fun getStudyDailyNotes(): JsonObject

    @GET("/api/v1/study-daily/notes/{filename}")
    suspend fun getStudyDailyNote(@Path("filename") filename: String): JsonObject

    @GET("/api/v1/study-daily/latest-progress")
    suspend fun getStudyDailyLatestProgress(): JsonObject

    @GET("/api/v1/study-daily/library")
    suspend fun getStudyLibrary(): JsonObject

    @GET("/api/v1/study-daily/library/note")
    suspend fun getStudyLibraryNote(@Query("path") path: String): JsonObject

    /** 新客户端请求体:{date, item_id, done}；旧 time/title 仍由后端兼容。 */
    @POST("/api/v1/study-daily/plan/item/status")
    suspend fun updateStudyPlanItemStatus(@Body payload: JsonObject): JsonObject

    /** 请求体:{date, time, title, duration_minutes}。 */
    @POST("/api/v1/study-daily/plan/item/add")
    suspend fun addStudyPlanItem(@Body payload: JsonObject): JsonObject

    /** 新客户端请求体:{date, item_id, time, title, duration_minutes}。 */
    @POST("/api/v1/study-daily/plan/item/update")
    suspend fun updateStudyPlanItem(@Body payload: JsonObject): JsonObject

    /** 新客户端请求体:{date, item_id}。 */
    @POST("/api/v1/study-daily/plan/item/remove")
    suspend fun removeStudyPlanItem(@Body payload: JsonObject): JsonObject
}
