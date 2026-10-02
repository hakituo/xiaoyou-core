package com.aveline.ai.mobile.data.samsung

import android.util.Log
import com.samsung.android.sdk.health.data.HealthDataStore
import com.samsung.android.sdk.health.data.data.AggregateOperation
import com.samsung.android.sdk.health.data.request.AggregateRequest
import com.samsung.android.sdk.health.data.request.LocalDateFilter
import com.samsung.android.sdk.health.data.request.LocalTimeFilter
import java.time.LocalDate
import java.time.LocalDateTime

private const val TAG = "SamsungHealthQuery"

/**
 * 返回今日的 LocalDateTime 范围 [今日0点, 当前时刻]。
 * 用于 LocalTimeFilter 的今日范围查询。
 */
internal fun todayLocalTimeRange(): Pair<LocalDateTime, LocalDateTime> {
    val today = LocalDate.now()
    return today.atStartOfDay() to LocalDateTime.now()
}

/**
 * 通用聚合查询辅助: 使用 LocalTimeFilter(今日 LocalDateTime 范围)。
 * 适用于 STEPS / ACTIVITY_SUMMARY 等(LocalTimeBuilder)。
 */
internal suspend fun <T : Any> readLocalTimeAggregate(
    store: HealthDataStore,
    operation: AggregateOperation<T, AggregateRequest.LocalTimeBuilder<T>>,
    start: LocalDateTime,
    end: LocalDateTime,
    tagName: String
): T? = runCatching {
    val request = operation.requestBuilder
        .setLocalTimeFilter(LocalTimeFilter.of(start, end))
        .build()
    val response = store.aggregateData(request)
    response.dataList.firstOrNull()?.value
}.onFailure { e ->
    Log.w(TAG, "读取${tagName}失败: ${e.message}")
}.getOrNull()

/**
 * 通用聚合查询辅助: 使用 LocalDateFilter(单日, 开放区间)。
 * 适用于各类 GOAL(底层是 AllSourceLocalDateBuilder)。
 *
 * 修复: of(date, date) 在 SDK 内部被判定 "Time Range is invalid"(start==end),
 * 改用 since(date) 表示 [date, +∞) 开放区间。
 */
internal suspend fun <T : Any> readLocalDateAggregate(
    store: HealthDataStore,
    operation: AggregateOperation<T, AggregateRequest.AllSourceLocalDateBuilder<T>>,
    date: LocalDate,
    tagName: String
): T? = runCatching {
    val request = operation.requestBuilder
        .setLocalDateFilter(LocalDateFilter.since(date))
        .build()
    val response = store.aggregateData(request)
    response.dataList.firstOrNull()?.value
}.onFailure { e ->
    Log.w(TAG, "读取${tagName}失败: ${e.message}")
}.getOrNull()
