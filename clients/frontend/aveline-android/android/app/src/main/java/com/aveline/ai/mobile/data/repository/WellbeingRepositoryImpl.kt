package com.aveline.ai.mobile.data.repository

import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.dto.AppLimitActionResponse
import com.aveline.ai.mobile.data.remote.dto.AppLimitDto
import com.aveline.ai.mobile.data.remote.dto.AppLimitResponse
import com.aveline.ai.mobile.data.remote.dto.AppLimitSetRequest
import com.aveline.ai.mobile.domain.repository.WellbeingRepository
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 数字健康(应用使用时长限额)数据仓库实现。
 *
 * 通过后端 REST 接口读写限额, 与 nightly 自动设定 / set_app_limit 工具同源。
 */
@Singleton
class WellbeingRepositoryImpl @Inject constructor(
    private val apiService: AvelineApiService
) : WellbeingRepository {

    override suspend fun getAppLimits(targetDate: String?): Result<List<AppLimitDto>> {
        return runCatching {
            val resp: AppLimitResponse = apiService.getAppLimits(targetDate)
            resp.limits
        }
    }

    override suspend fun setAppLimit(
        packageName: String,
        appName: String,
        limitMs: Long,
        sessionLimitMs: Long,
        sessionGapMs: Long,
        cooldownMs: Long,
        targetDate: String?
    ): Result<Unit> {
        return runCatching {
            val resp: AppLimitActionResponse = apiService.setAppLimit(
                AppLimitSetRequest(
                    packageName = packageName,
                    appName = appName,
                    limitMs = limitMs,
                    sessionLimitMs = sessionLimitMs,
                    sessionGapMs = sessionGapMs,
                    cooldownMs = cooldownMs,
                    targetDate = targetDate
                )
            )
            if (resp.status != "success") {
                throw IllegalStateException(resp.message.ifBlank { "设置限额失败" })
            }
        }
    }

    override suspend fun deleteAppLimit(
        packageName: String,
        targetDate: String?
    ): Result<Unit> {
        return runCatching {
            val resp: AppLimitActionResponse = apiService.deleteAppLimit(packageName, targetDate)
            if (resp.status != "success") {
                throw IllegalStateException(resp.message.ifBlank { "移除限额失败" })
            }
        }
    }
}
