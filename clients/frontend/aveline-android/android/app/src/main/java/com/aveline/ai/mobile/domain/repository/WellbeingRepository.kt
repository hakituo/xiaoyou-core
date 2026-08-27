package com.aveline.ai.mobile.domain.repository

import com.aveline.ai.mobile.data.remote.dto.AppLimitDto

/**
 * 数字健康(应用使用时长限额)数据仓库接口。
 *
 * 定义应用限额的读取与写入操作。底层走后端 REST 接口
 * (/api/v1/context/wellbeing/app-limits), 与 nightly 自动设定 / Aveline 的
 * set_app_limit 工具同源 (DigitalWellbeingService), 互相覆盖生效。
 */
interface WellbeingRepository {

    /**
     * 获取应用限额列表 (及今日用量进度)。
     *
     * @param targetDate 目标日期 YYYY-MM-DD, 不传默认明天
     * @return 限额列表 (已按超限比例降序)
     */
    suspend fun getAppLimits(targetDate: String? = null): Result<List<AppLimitDto>>

    /**
     * 设置/覆盖单个应用的使用时长限额。
     *
     * @param packageName 应用包名
     * @param appName 应用展示名 (可选)
     * @param limitMs 限额毫秒, <=0 表示移除
     * @param targetDate 目标日期 (默认明天)
     */
    suspend fun setAppLimit(
        packageName: String,
        appName: String,
        limitMs: Long,
        targetDate: String? = null
    ): Result<Unit>

    /**
     * 移除单个应用的使用时长限额。
     */
    suspend fun deleteAppLimit(
        packageName: String,
        targetDate: String? = null
    ): Result<Unit>
}
