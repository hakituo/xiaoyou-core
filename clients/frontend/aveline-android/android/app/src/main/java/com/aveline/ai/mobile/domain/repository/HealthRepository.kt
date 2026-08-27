package com.aveline.ai.mobile.domain.repository

import com.aveline.ai.mobile.domain.models.HealthConnectAvailability
import com.aveline.ai.mobile.domain.models.HealthData
import com.aveline.ai.mobile.domain.models.HealthPermissionState
import kotlinx.coroutines.flow.Flow
import kotlinx.serialization.json.JsonObject

/**
 * 健康数据仓库接口
 * 
 * 定义健康数据的读取和权限管理操作
 * 
 * Requirements: 8.1, 8.2
 */
interface HealthRepository {
    
    /**
     * 获取 Health Connect 可用性状态
     */
    suspend fun checkAvailability(): HealthConnectAvailability
    
    /**
     * 获取当前权限状态
     */
    suspend fun getPermissionState(): HealthPermissionState
    
    /**
     * 获取所需的权限集合
     */
    fun getRequiredPermissions(): Set<String>
    
    /**
     * 检查是否拥有所有权限
     */
    suspend fun hasAllPermissions(): Boolean

    /**
     * 获取当前 Health Connect SDK 可用性(缓存友好, 不抛异常)。
     */
    suspend fun getCurrentAvailability(): HealthConnectAvailability

    /**
     * 读取健康数据
     *
     * @return HealthData 或 null（如果没有权限）
     */
    suspend fun readHealthData(): HealthData?
    
    /**
     * 读取生命体征数据（步数、心率、血氧）
     */
    suspend fun readVitalSigns(): HealthData?
    
    /**
     * 读取身体指标数据（体重、身高、睡眠）
     */
    suspend fun readBodyMetrics(): HealthData?
    
    /**
     * 观察健康数据变化
     */
    fun observeHealthData(): Flow<HealthData>
    
    /**
     * 打开 Health Connect 应用设置
     */
    fun openHealthConnectSettings()

    // ==================== 每日画像与记录相关接口 ====================

    /** 获取今日每日画像（含作息、饮水、学习、模式等） */
    suspend fun getDailyPortraitToday(): Result<JsonObject>

    /** 获取最近的每日记录文件列表 */
    suspend fun getDailyRecent(limit: Int = 12): Result<JsonObject>

    /** 记录每日喝水 */
    suspend fun recordDailyDrink(payload: JsonObject): Result<JsonObject>

    /** 记录每日学习（开始学习会话） */
    suspend fun recordDailyStudy(payload: JsonObject): Result<JsonObject>

    /** 结束每日学习会话 */
    suspend fun finishDailyStudy(): Result<JsonObject>

    /** 更新每日作息（睡觉/起床时间） */
    suspend fun recordDailySchedule(payload: JsonObject): Result<JsonObject>

    /** 同步 Health Connect 健康数据到后端 */
    suspend fun syncHealthData(payload: JsonObject): Result<JsonObject>
}
