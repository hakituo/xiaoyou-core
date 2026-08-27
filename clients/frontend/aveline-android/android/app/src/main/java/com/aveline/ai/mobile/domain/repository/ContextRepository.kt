package com.aveline.ai.mobile.domain.repository

import com.aveline.ai.mobile.domain.models.AppUsageInfo
import com.aveline.ai.mobile.domain.models.DeviceContext
import com.aveline.ai.mobile.domain.models.FullContext
import com.aveline.ai.mobile.domain.models.NotificationInfo
import kotlinx.coroutines.flow.Flow
import kotlinx.serialization.json.JsonObject

/**
 * 设备上下文仓库接口
 * 
 * 定义设备数据收集操作
 * 
 * Requirements: 16.1, 16.2, 16.3, 16.4
 */
interface ContextRepository {
    
    /**
     * 获取设备上下文
     */
    suspend fun getDeviceContext(): DeviceContext
    
    /**
     * 获取应用使用统计
     * 
     * @param hours 过去多少小时的数据
     */
    suspend fun getAppUsage(hours: Int = 24): List<AppUsageInfo>
    
    /**
     * 获取从指定时刻到现在的应用使用统计 (用于"会话限额"计算)。
     * 
     * @param startTimeMs 起始时刻 (epoch 毫秒), 统计 [startTimeMs, now] 区间内的用量
     */
    suspend fun getAppUsageSince(startTimeMs: Long): List<AppUsageInfo>
    
    /**
     * 获取最近通知
     * 
     * @param limit 最大数量
     */
    suspend fun getRecentNotifications(limit: Int = 10): List<NotificationInfo>
    
    /**
     * 获取完整上下文
     */
    suspend fun getFullContext(): FullContext
    
    /**
     * 观察设备上下文变化
     */
    fun observeDeviceContext(): Flow<DeviceContext>
    
    /**
     * 检查是否有应用使用统计权限
     */
    fun hasUsageStatsPermission(): Boolean
    
    /**
     * 检查是否有通知监听权限
     */
    fun hasNotificationListenerPermission(): Boolean
    
    /**
     * 打开应用使用统计权限设置
     */
    fun openUsageStatsSettings()
    
    /**
     * 打开通知监听权限设置
     */
    fun openNotificationListenerSettings()
    
    /**
     * 同步上下文到后端
     */
    suspend fun syncToBackend(context: FullContext): Result<Unit>

    /** 记录体重 */
    suspend fun recordBodyMetrics(weight: Double?, height: Double?): Result<JsonObject>

    /** 上传单条设备上下文 */
    suspend fun uploadDeviceSnapshot(): Result<JsonObject>
}
