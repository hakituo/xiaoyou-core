package com.aveline.ai.mobile.data.remote.api

import com.aveline.ai.mobile.data.remote.dto.*
import kotlinx.serialization.json.JsonObject
import okhttp3.MultipartBody
import okhttp3.ResponseBody
import retrofit2.Response
import retrofit2.http.*

/**
 * Retrofit API service interface for Aveline backend communication.
 *
 * This interface defines all REST API endpoints for the Aveline AI Assistant.
 * All endpoints use JSON for request/response bodies with Kotlin Serialization.
 *
 * Authentication is handled via Bearer token in HTTP headers (added by interceptor).
 *
 * Study/Daily 相关端点已拆分到 [StudyDailyApiService],本接口通过继承方式聚合,
 * 现有注入 AvelineApiService 的代码无需改动即可调用全部方法。
 */
interface AvelineApiService : StudyDailyApiService {

    // ==================== Message Endpoints ====================

    /**
     * Send a message to the AI assistant.
     *
     * @param request Message request containing text, session ID, and model
     * @return Message response with AI reply and emotion state
     */
    @POST("/api/v1/chat/message")
    suspend fun sendMessage(@Body request: MessageRequest): MessageResponse

    /**
     * 流式发送消息 (SSE)
     * 后端 stream=true 时返回 text/event-stream, 每行 data: {json}
     * 用 @Streaming 保持连接不断开
     */
    @Streaming
    @POST("/api/v1/chat/message")
    suspend fun sendMessageStreaming(@Body request: MessageRequest): Response<ResponseBody>

    @POST("/api/v1/chat/regenerate")
    suspend fun regenerateMessage(@Body payload: JsonObject): MessageResponse

    // ==================== Session Endpoints ====================

    /**
     * Get list of all chat sessions.
     *
     * @return List of sessions with metadata
     */
    @GET("/api/v1/sessions")
    suspend fun getSessions(): SessionsResponse

    /**
     * Create a new chat session.
     *
     * @param request Session creation request with title
     * @return Created session object
     */
    @POST("/api/v1/sessions")
    suspend fun createSession(@Body request: CreateSessionRequest): SessionResponse

    /**
     * Get message history for a specific session.
     *
     * @param sessionId The session ID to retrieve history for
     * @return List of messages in the session
     */
    @GET("/api/v1/sessions/{id}/history")
    suspend fun getSessionHistory(@Path("id") sessionId: String): HistoryResponse

    @DELETE("/api/v1/sessions/{id}")
    suspend fun deleteSession(@Path("id") sessionId: String): Response<Unit>

    @PUT("/api/v1/sessions/{id}")
    suspend fun updateSession(
        @Path("id") sessionId: String,
        @Body updates: Map<String, String>
    ): Response<Unit>

    // ==================== Status Endpoints ====================

    /**
     * Get AI assistant's life status metrics.
     *
     * @return Life status with health, hunger, happiness, energy levels
     */
    @GET("/api/v1/life/status")
    suspend fun getLifeStatus(
        @Query("scope") scope: String? = null,
        @Query("persona") persona: String? = null
    ): LifeStatusResponse

    /** 立即唤醒当前角色。 */
    @POST("/api/v1/life/sleep/wake")
    suspend fun wakeCompanion(@Body payload: JsonObject): JsonObject

    /** 打断当前活动并进入临时聊天窗口。 */
    @POST("/api/v1/life/activity/interrupt")
    suspend fun interruptCompanion(@Body payload: JsonObject): JsonObject

    /** 跳过当前活动，不再提醒返回。 */
    @POST("/api/v1/life/activity/skip")
    suspend fun skipCompanionActivity(@Body payload: JsonObject): JsonObject

    // ==================== Context Endpoints ====================

    /**
     * Sync device context data to backend.
     *
     * @param request Full context sync request including device, app usage, notifications
     * @return Response indicating sync success
     */
    @POST("/api/v1/context/sync")
    suspend fun syncContext(@Body request: ContextSyncRequest): Response<ContextSyncResponse>

    // ==================== 数字健康: 应用使用时长限额 ====================

    /**
     * 获取应用使用时长限额列表 (及今日用量进度)。
     *
     * @param targetDate 目标日期 YYYY-MM-DD, 不传默认明天
     * @return 限额列表响应
     */
    @GET("/api/v1/context/wellbeing/app-limits")
    suspend fun getAppLimits(
        @Query("target_date") targetDate: String? = null
    ): AppLimitResponse

    /**
     * 设置/覆盖单个应用的使用时长限额。
     */
    @POST("/api/v1/context/wellbeing/app-limit")
    suspend fun setAppLimit(@Body request: AppLimitSetRequest): AppLimitActionResponse

    /**
     * 移除单个应用的使用时长限额。
     */
    @DELETE("/api/v1/context/wellbeing/app-limit/{package_name}")
    suspend fun deleteAppLimit(
        @Path("package_name") packageName: String,
        @Query("target_date") targetDate: String? = null
    ): AppLimitActionResponse

    // ==================== TTS Endpoints ====================

    @POST("/api/v1/media/tts")
    suspend fun synthesizeTTS(@Body request: TTSRequest): TTSResponse

    @GET("/api/v1/media/voices")
    suspend fun getVoices(): VoicesResponse

    // ==================== Upload Endpoints ====================

    /**
     * Upload a file (image, document, etc.).
     *
     * @param file Multipart file data
     * @return Upload response with file URL and metadata
     */
    @POST("/api/v1/media/upload")
    @Multipart
    suspend fun uploadFile(@Part file: MultipartBody.Part): UploadResponse

    // ==================== Memory Endpoints ====================

    /**
     * Get list of memories, optionally filtered by search query.
     *
     * @param query Optional search query to filter memories
     * @return List of memories matching the query
     */
    @GET("/api/v1/memories")
    suspend fun getMemories(@Query("query") query: String? = null): MemoryListResponse

    /**
     * Get memories with filters.
     *
     * 后端 GET /api/v1/memories 实际参数契约:
     * - category: 单值字符串, 按分类过滤 (前端类型筛选时取第一个)
     * - min_weight: 按最小权重过滤
     * - include_thinking: 是否包含 thinking 分类, 默认 true (让用户看到 AI 思考类记忆)
     * - limit: 返回条数上限, 默认 100 (后端默认 50, 提到 100 让用户看更多)
     * - emotion: 按情绪过滤 (前端未用, 保留接口)
     *
     * 注意: 前端原 `types`/`important_only`/`min_importance`/`page`/`page_size`
     * 后端一个都不认, 导致参数完全失效且无法看到 thinking 分类记忆。
     *
     * @param category 单个分类名 (小写)
     * @param minWeight 最小权重阈值
     * @param includeThinking 是否包含 thinking 分类 (默认 true)
     * @param limit 返回条数上限
     * @param emotion 情绪过滤 (可选)
     * @return List of memories matching filters
     */
    @GET("/api/v1/memories")
    suspend fun getMemories(
        @Query("category") category: String? = null,
        @Query("min_weight") minWeight: Double? = null,
        @Query("include_thinking") includeThinking: Boolean? = true,
        @Query("limit") limit: Int? = 100,
        @Query("emotion") emotion: String? = null,
        // 按 persona 查询记忆：传人格文件名（如 qq/Aveline_QQ_Master.json），
        // 由后端权威解析成 shared__scope__{scope}，保证按角色隔离且跨平台互通。
        @Query("persona") persona: String? = null
    ): MemoryListResponse

    /**
     * Get a specific memory by ID.
     *
     * @param memoryId The memory ID to retrieve
     * @return Memory details
     */
    @GET("/api/v1/memories/{id}")
    suspend fun getMemory(@Path("id") memoryId: String): MemoryDto

    /**
     * Search memories by keyword.
     *
     * @param query Search keyword
     * @return List of matching memories
     */
    @GET("/api/v1/memories")  // 后端 memories 列表支持 category/emotion 过滤
    suspend fun searchMemories(@Query("q") query: String): MemoryListResponse

    /**
     * Delete a specific memory.
     *
     * @param memoryId The memory ID to delete
     * @return Response indicating deletion success
     */
    @DELETE("/api/v1/memories/{id}")
    suspend fun deleteMemory(@Path("id") memoryId: String): Response<Unit>

    /**
     * Mark a memory as important or not.
     *
     * @param memoryId The memory ID to update
     * @param request Request with important flag
     * @return Response indicating update success
     */
    @PATCH("/api/v1/memories/{id}/important")  // TODO: 后端暂无此端点，需补
    suspend fun markMemoryImportant(
        @Path("id") memoryId: String,
        @Body request: MarkImportantRequest
    ): Response<Unit>

    /**
     * Get memory statistics.
     *
     * @return Memory statistics
     */
    @GET("/api/v1/memories/stats")
    suspend fun getMemoryStats(
        @Query("persona") persona: String? = null
    ): MemoryStatsResponse

    /**
     * Get all memory tags.
     *
     * @return List of tags
     */
    @GET("/api/v1/memories/tags")
    suspend fun getMemoryTags(
        @Query("persona") persona: String? = null
    ): TagsResponse

    // ==================== Study Endpoints ====================

    /**
     * Get list of study files.
     *
     * @return List of study files
     */
    @GET("/api/v1/vocab/files")
    suspend fun getStudyFiles(): StudyFilesResponse

    /**
     * Upload a study file.
     *
     * @param file Multipart file data
     * @return Uploaded file details
     */
    @POST("/api/v1/media/upload")  // study 文件上传走 media/upload
    @Multipart
    suspend fun uploadStudyFile(@Part file: MultipartBody.Part): StudyFileDto

    /**
     * Delete a study file.
     *
     * @param fileId The file ID to delete
     * @return Response indicating deletion success
     */
    @DELETE("/api/v1/study/files/{id}")  // TODO: 后端暂无此端点
    suspend fun deleteStudyFile(@Path("id") fileId: String): Response<Unit>

    /**
     * Get study mode state.
     *
     * @return Study mode state
     */
    @GET("/api/v1/vocab/mode")
    suspend fun getStudyMode(): StudyModeResponse

    /**
     * Enable or disable study mode.
     *
     * @param enabled Whether to enable study mode
     * @return Response indicating success
     */
    @POST("/api/v1/study/mode")  // TODO: 后端暂无此端点
    suspend fun setStudyMode(@Body request: SetStudyModeRequest): Response<Unit>

    /**
     * Set active study files.
     *
     * @param fileIds List of file IDs to activate
     * @return Response indicating success
     */
    @POST("/api/v1/study/files/active")  // TODO: 后端暂无此端点
    suspend fun setActiveStudyFiles(@Body request: SetActiveFilesRequest): Response<Unit>

    // ==================== Persona Endpoints ====================

    /**
     * Get list of available personas (完整的原始JSON，用于Web端UI)
     *
     * @return List of persona configurations (原始JSON)
     */
    @GET("/api/v1/personas")
    suspend fun getPersonasRaw(): kotlinx.serialization.json.JsonArray

    /**
     * Get currently active persona (完整的原始JSON，用于Web端UI)
     *
     * @return Active persona details (原始JSON)
     */
    @GET("/api/v1/personas/active")
    suspend fun getActivePersonaRaw(): kotlinx.serialization.json.JsonObject

    /**
     * Get list of available personas.
     *
     * @return List of persona configurations
     */
    @GET("/api/v1/personas")
    suspend fun getPersonas(): List<PersonaDto>

    /**
     * Get currently active persona.
     *
     * @return Active persona details
     */
    @GET("/api/v1/personas/active")
    suspend fun getActivePersona(): ActivePersonaResponse

    /**
     * Select and activate a persona.
     *
     * @param request Persona selection request with persona ID
     * @return Response indicating selection success
     */
    @POST("/api/v1/personas/switch")
    suspend fun selectPersona(@Body request: SelectPersonaRequest): Response<Unit>

    /**
     * Create a new custom persona.
     *
     * @param request Persona creation request
     * @return Created persona
     */
    @POST("/api/v1/personas")  // TODO: 后端暂无此端点
    suspend fun createPersona(@Body request: PersonaRequest): PersonaDto

    /**
     * Update an existing persona.
     *
     * @param personaId The persona ID to update
     * @param request Persona update request
     * @return Updated persona
     */
    @PUT("/api/v1/personas/{id}")  // TODO: 后端暂无此端点
    suspend fun updatePersona(
        @Path("id") personaId: String,
        @Body request: PersonaRequest
    ): PersonaDto

    /**
     * Delete a custom persona.
     *
     * @param personaId The persona ID to delete
     * @return Response indicating deletion success
     */
    @DELETE("/api/v1/personas/{id}")  // TODO: 后端暂无此端点
    suspend fun deletePersona(@Path("id") personaId: String): Response<Unit>

    // ==================== Model Endpoints ====================

    /**
     * Get list of available AI models.
     *
     * @return List of models (cloud and local)
     */
    @GET("/api/v1/models")
    suspend fun getModels(): ModelsResponse

    /**
     * Switch current LLM model globally (REST).
     *
     * 真正修改后端全局配置（settings.model.llm.provider/model/text_path），
     * 而不是 WebSocket 的会话级锁定。
     */
    @POST("/api/v1/models/switch")
    suspend fun switchModel(@Body request: SwitchModelRequest): SwitchModelResponse

    // ==================== Shop (商城) Endpoints ====================

    /**
     * 获取商城商品列表(分页+类别过滤)
     */
    @GET("/api/v1/food/shop/menu")
    suspend fun getShopMenu(
        @Query("category") category: String? = null,
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 20
    ): ShopMenuResponse

    /**
     * 购买商城商品(支持 recipient)
     */
    @POST("/api/v1/food/buy/{food_id}")
    suspend fun buyShopItem(
        @Path("food_id") itemId: String,
        @Query("quantity") quantity: Int = 1,
        @Query("recipient") recipient: String = "self"
    ): ShopBuyResponse

    /**
     * 获取礼物/非食物商品库存
     */
    @GET("/api/v1/food/gift-inventory")
    suspend fun getGiftInventory(): GiftInventoryResponse

    /**
     * 使用/赠送非食物商品
     */
    @POST("/api/v1/food/use-gift/{item_id}")
    suspend fun useGiftItem(
        @Path("item_id") itemId: String,
        @Query("recipient") recipient: String = "self"
    ): UseGiftResponse

    // ==================== Food Endpoints (旧,保留兼容) ====================

    /**
     * Get list of food items (menu).
     *
     * @return List of available food items
     */
    @GET("/api/v1/food/menu")
    suspend fun getFoodMenu(@Query("type") type: String? = null): List<FoodItemDto>

    /**
     * Get food inventory.
     *
     * @return Food inventory response
     */
    @GET("/api/v1/food/inventory")
    suspend fun getFoodInventory(): FoodInventoryResponse

    /**
     * Buy a food item.
     *
     * @param foodId The food item ID
     * @param quantity Number of items to buy
     * @return Food action response
     */
    @POST("/api/v1/food/buy/{food_id}")
    suspend fun buyFood(
        @Path("food_id") foodId: String,
        @Query("quantity") quantity: Int = 1
    ): FoodActionResponse

    /**
     * Eat a food item.
     *
     * @param foodId The food item ID
     * @param fromInventory Whether to eat from inventory
     * @return Food action response
     */
    @POST("/api/v1/food/eat/{food_id}")
    suspend fun eatFood(
        @Path("food_id") foodId: String,
        @Query("from_inventory") fromInventory: Boolean = true
    ): FoodActionResponse

    // ==================== Shop Endpoints (Deprecated - Use Food APIs instead) ====================

    /**
     * Get list of shop items.
     *
     * @return List of purchasable items with prices and effects
     * @deprecated Use /api/v1/food/menu instead
     */
    @GET("/api/v1/shop/items")
    suspend fun getShopItems(): ShopItemsResponse

    /**
     * Purchase a shop item.
     *
     * @param request Purchase request with item ID and quantity
     * @return Purchase response with new balance and applied effects
     * @deprecated Use /api/v1/food/buy/{food_id} instead
     */
    @POST("/api/v1/shop/purchase")
    suspend fun purchaseItem(@Body request: PurchaseRequest): PurchaseResponse

    // ==================== Health Endpoints ====================

    /**
     * Health check endpoint to verify backend connectivity.
     *
     * @return Response indicating backend health status
     */
    @GET("/api/v1/health")
    suspend fun healthCheck(): Response<Unit>

    @GET("/api/v1/vision/image/models")
    suspend fun getImageModels(): ImageModelsResponse

    @POST("/api/v1/vision/image/generate")
    suspend fun generateImage(@Body payload: JsonObject): ImageGenerateResponse

    @POST("/api/v1/vision/describe")
    suspend fun describeVision(@Body payload: JsonObject): VisionDescribeResponse

    @POST("/api/v1/vision/analyze-screen")
    suspend fun analyzeScreen(@Body payload: JsonObject): VisionDescribeResponse

    @GET("/api/v1/notifications")  // TODO: 后端暂无此端点
    suspend fun getNotifications(@Query("user_id") userId: String = "default"): NotificationsResponse

    @GET("/api/v1/system/preferences")
    suspend fun getSystemPreferences(): SystemPreferencesResponse

    @POST("/api/v1/system/preferences")
    suspend fun updateSystemPreferences(@Body payload: JsonObject): SystemPreferencesResponse

    @POST("/api/v1/system/mobile-push-token")
    suspend fun registerMobilePushToken(@Body payload: JsonObject): Response<Unit>

    @GET("/api/v1/context/daily/portrait/today")
    suspend fun getDailyPortraitToday(): JsonObject

    @GET("/api/v1/context/daily/recent")
    suspend fun getDailyRecent(@Query("limit") limit: Int = 12): JsonObject

    @POST("/api/v1/context/daily/record/drink")
    suspend fun recordDailyDrink(@Body payload: JsonObject): JsonObject

    @POST("/api/v1/context/daily/record/study")
    suspend fun recordDailyStudy(@Body payload: JsonObject): JsonObject

    @POST("/api/v1/context/daily/study/finish")
    suspend fun finishDailyStudy(@Body payload: JsonObject = JsonObject(emptyMap())): JsonObject

    @POST("/api/v1/context/daily/record/schedule")
    suspend fun recordDailySchedule(@Body payload: JsonObject): JsonObject

    @GET("/api/v1/workspace/study/panel")
    suspend fun getWorkspaceStudyPanel(
        @Query("conversation_id") conversationId: String = "default_user",
        @Query("date") date: String? = null,
        @Query("history_limit") historyLimit: Int = 20
    ): JsonObject

    @POST("/api/v1/workspace/study/record")
    suspend fun recordWorkspaceStudy(@Body payload: JsonObject): JsonObject

    @GET("/api/v1/vocab/daily")
    suspend fun getDailyVocabulary(
        @Query("count") count: Int = 20,
        @Query("order") order: String = "sequential"
    ): JsonObject

    /** 获取从未学过的新词（不在 progress 里的词） */
    @GET("/api/v1/vocab/new-words")
    suspend fun getNewWords(
        @Query("count") count: Int = 20,
        @Query("order") order: String = "sequential"
    ): JsonObject

    /** 手动记录当天背了多少个单词 */
    @POST("/api/v1/vocab/manual-study")
    suspend fun addManualStudy(@Body payload: JsonObject): JsonObject

    /** 获取手动背诵统计（days 或 date 二选一） */
    @GET("/api/v1/vocab/manual-study/stats")
    suspend fun getManualStudyStats(
        @Query("days") days: Int = 7,
        @Query("date") date: String = ""
    ): JsonObject

    @POST("/api/v1/vocab/sessions")
    suspend fun startSession(): JsonObject

    @POST("/api/v1/vocab/review")
    suspend fun submitReview(@Body payload: JsonObject): JsonObject

    @DELETE("/api/v1/vocab/sessions/current")
    suspend fun endSession(): JsonObject

    @GET("/api/v1/vocab/sessions/stats")
    suspend fun getSessionStats(): JsonObject

    // ==================== 专注番茄钟 (Focus Pomodoro) 跨端同步 ====================
    // 后端为权威计时，Android 拉取当前会话以展示/对齐，不本地累计。

    /** 查询当前进行中的专注会话（无则后端返回空对象或 error） */
    @GET("/api/v1/study/focus-sessions/current")
    suspend fun getFocusSessionCurrent(
        @Query("user_id") userId: String = "default"
    ): JsonObject

    /** 开始一个专注会话：subject 专注主题, planned_minutes 计划时长, mode gentle/strict */
    @POST("/api/v1/study/focus-sessions")
    suspend fun startFocusSession(@Body payload: JsonObject): JsonObject

    /** 暂停当前会话 */
    @POST("/api/v1/study/focus-sessions/{id}/pause")
    suspend fun pauseFocusSession(@Path("id") id: String): JsonObject

    /** 恢复当前会话 */
    @POST("/api/v1/study/focus-sessions/{id}/resume")
    suspend fun resumeFocusSession(@Path("id") id: String): JsonObject

    /** 结束当前会话 */
    @POST("/api/v1/study/focus-sessions/{id}/finish")
    suspend fun finishFocusSession(
        @Path("id") id: String,
        @Body payload: JsonObject = JsonObject(emptyMap())
    ): JsonObject

    /** 查询某次会话总结 */
    @GET("/api/v1/study/focus-sessions/{id}/summary")
    suspend fun getFocusSessionSummary(@Path("id") id: String): JsonObject

    /** 查询历史会话列表 */
    @GET("/api/v1/study/focus-sessions/history")
    suspend fun getFocusSessionHistory(
        @Query("user_id") userId: String = "default",
        @Query("limit") limit: Int = 10
    ): JsonObject

    @GET("/api/v1/vocab/dictionary/stats")
    suspend fun getDictStats(): JsonObject

    @GET("/api/v1/vocab/curve")
    suspend fun getMemoryCurve(): JsonObject

    @GET("/api/v1/vocab/mistakes")
    suspend fun getMistakes(): JsonObject

    /** 复习总览：今日待复习数、连续天数、到期分布、记忆曲线预测 */
    @GET("/api/v1/vocab/review-overview")
    suspend fun getReviewOverview(): JsonObject

    @GET("/api/v1/system/resources")
    suspend fun getSystemResources(): SystemResourcesResponse

    @GET("/api/v1/system/stats")
    suspend fun getSystemStats(): SystemStatsResponse

    @POST("/api/v1/context/intent/classify")
    suspend fun classifyIntent(@Body payload: JsonObject): IntentClassifyResponse

    @POST("/api/v1/system/search/web")
    suspend fun webSearch(@Body payload: JsonObject): JsonObject

    @POST("/api/v1/life/emotion/detect")
    suspend fun detectEmotion(@Body payload: JsonObject): JsonObject

    @GET("/api/v1/system/active-care/status")
    suspend fun getActiveCareStatus(): JsonObject

    @POST("/api/v1/system/active-care/check")
    suspend fun triggerActiveCareCheck(): JsonObject

    @POST("/api/v1/context/daily/record/body-metrics")
    suspend fun recordBodyMetrics(@Body payload: JsonObject): JsonObject

    @POST("/api/v1/context/health/sync")
    suspend fun syncHealthData(@Body payload: JsonObject): JsonObject

    @POST("/api/v1/context/device")
    suspend fun uploadDeviceContext(@Body payload: JsonObject): JsonObject

    @DELETE("/api/v1/memories")
    suspend fun clearAllMemories(@Query("user_id") userId: String = "default"): Response<Unit>

    @POST("/api/v1/memories/clear")
    suspend fun clearSessionHistory(@Body payload: JsonObject): JsonObject

    @GET("/api/v1/vocab/subjects")
    suspend fun getSubjects(): JsonObject

    @POST("/api/v1/vocab/vocabulary/add")
    suspend fun addVocabulary(@Body payload: JsonObject): JsonObject

    @GET("/api/v1/vocab/dictionary/search")
    suspend fun searchDictionary(@Query("query") query: String, @Query("limit") limit: Int = 20): JsonObject

    /** 词书统计:可用词书列表(available_word_files)与当前词书(current_dictionary) */
    @GET("/api/v1/vocab/dictionary/stats")
    suspend fun getVocabBookStats(): JsonObject

    /** 词书内单词分页列表 */
    @GET("/api/v1/vocab/dictionary/list")
    suspend fun getBookWords(
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 50
    ): JsonObject

    /** 切换当前词书(单词书) */
    @POST("/api/v1/vocab/vocabulary/switch")
    suspend fun switchVocabulary(@Body payload: JsonObject): JsonObject

    @GET("/api/v1/plugins/sensitive/status")
    suspend fun getSensitiveStatus(@Query("user_id") userId: String = "default"): SensitiveStatusResponse

    @POST("/api/v1/plugins/sensitive/toggle")
    suspend fun toggleSensitive(@Body payload: SensitiveToggleRequest): SensitiveToggleResponse

    // ==================== Peer Chat Endpoints ====================

    /**
     * 获取双角色对话历史
     *
     * @param limit 返回条数
     * @return 双角色对话历史
     */
    @GET("/api/v1/peer-chat/history")
    suspend fun getPeerChatHistory(
        @Query("limit") limit: Int = 20
    ): JsonObject

    /**
     * 触发双角色对话
     *
     * @param request 对话请求（包含话题等）
     * @return 对话结果
     */
    @POST("/api/v1/peer-chat/trigger")
    suspend fun triggerPeerChat(@Body request: JsonObject): JsonObject

    /**
     * 获取双角色对话状态
     *
     * @return 当前双角色对话状态
     */
    @GET("/api/v1/peer-chat/status")
    suspend fun getPeerChatStatus(): JsonObject

    // ==================== Diary Endpoints ====================

    /**
     * 获取日记列表（journal 系统，按日期查询）。
     *
     * 后端直接返回 List[DiaryEntry]（无 {status, data} 包装），
     * 每条含 id/timestamp/time_str/type/content/thought/mood/tags/source。
     * source 字段区分作者：user(用户自己) / aveline / ling(Ling)。
     *
     * @param date 日期(YYYY-MM-DD)，null 则今天
     * @return 日记条目列表
     */
    @GET("/api/v1/diary")
    suspend fun getDiaries(@Query("date") date: String?): List<JsonObject>
}
