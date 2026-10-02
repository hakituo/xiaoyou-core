package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * 应用使用时长限额项 (数字健康)。
 *
 * 对应后端 GET /api/v1/context/wellbeing/app-limits 返回的 limits[i]。
 * usage_today_ms / ratio 由后端基于"今日实际用量"算好, 前端直接画进度条。
 *
 * 两类限制同时生效、取更严格的那个:
 * - limit_ms        每日总额度 (当天 00:00 起算, 次日 00:00 重置)
 * - session_limit_ms 单次连续使用额度 (离开超过 session_gap_ms 才算新的一次)
 *
 * session_cap_ms 是旧版"一次性 cap"字段, 仅用于兼容老后端。
 * session_used_ms / blocked_until_ms / block_reason 由手机端本地计算后回填, 后端不返回。
 */
@Serializable
data class AppLimitDto(
    @SerialName("package_name")
    val packageName: String,

    @SerialName("app_name")
    val appName: String = "",

    @SerialName("limit_ms")
    val limitMs: Long,

    @SerialName("source")
    val source: String = "user",

    @SerialName("usage_today_ms")
    val usageTodayMs: Long = 0,

    @SerialName("ratio")
    val ratio: Double = 0.0,

    @SerialName("session_limit_ms")
    val sessionLimitMs: Long = 0,

    @SerialName("session_gap_ms")
    val sessionGapMs: Long = 0,

    @SerialName("cooldown_ms")
    val cooldownMs: Long = 0,

    @Deprecated("改用 session_limit_ms; 仅用于兼容老后端")
    @SerialName("session_cap_ms")
    val sessionCapMs: Long = 0,

    /** [本地回填] 本次连续使用已用时 (毫秒)。 */
    val sessionUsedMs: Long = 0,

    /** [本地回填] 解禁时刻 (epoch 毫秒); 0 表示未拦截。 */
    val blockedUntilMs: Long = 0,

    /** [本地回填] 拦截原因: "" / "daily" / "session" / "cooldown"。 */
    val blockReason: String = "",
) {

    /** 生效的单次额度 (兼容旧版 session_cap_ms)。 */
    @Suppress("DEPRECATION")
    fun effectiveSessionLimitMs(): Long = sessionLimitMs.takeIf { it > 0 } ?: sessionCapMs
}

/**
 * GET /api/v1/context/wellbeing/app-limits 响应。
 *
 * date 为该批限额所属日期(默认明天), limits 为限额列表。
 */
@Serializable
data class AppLimitResponse(
    @SerialName("status")
    val status: String = "success",

    @SerialName("date")
    val date: String = "",

    @SerialName("limits")
    val limits: List<AppLimitDto> = emptyList()
)

/**
 * POST /api/v1/context/wellbeing/app-limit 请求体。
 *
 * limit_ms <= 0 且 session_limit_ms <= 0 表示移除该应用的所有限额。
 * target_date 不传时后端默认存"明天"。
 * session_gap_ms / cooldown_ms 不传时后端用默认值 (离开 2 分钟算结束 / 休息 5 分钟)。
 */
@Serializable
data class AppLimitSetRequest(
    @SerialName("package_name")
    val packageName: String,

    @SerialName("app_name")
    val appName: String = "",

    @SerialName("limit_ms")
    val limitMs: Long,

    @SerialName("session_limit_ms")
    val sessionLimitMs: Long = 0,

    @SerialName("session_gap_ms")
    val sessionGapMs: Long = 0,

    @SerialName("cooldown_ms")
    val cooldownMs: Long = 0,

    @SerialName("target_date")
    val targetDate: String? = null
)

/**
 * 通用操作结果 (设置/移除限额的响应)。
 */
@Serializable
data class AppLimitActionResponse(
    @SerialName("status")
    val status: String = "success",

    @SerialName("message")
    val message: String = "",

    @SerialName("package_name")
    val packageName: String = ""
)
