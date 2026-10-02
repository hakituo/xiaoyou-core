package com.aveline.ai.mobile.data.samsung

import android.util.Log
import com.samsung.android.sdk.health.data.HealthDataStore
import com.samsung.android.sdk.health.data.data.entries.SleepSession
import com.samsung.android.sdk.health.data.request.DataType
import com.samsung.android.sdk.health.data.request.DataTypes
import com.samsung.android.sdk.health.data.request.InstantTimeFilter
import java.time.Duration
import java.time.Instant
import java.time.temporal.ChronoUnit
import javax.inject.Inject
import javax.inject.Singleton

/** 睡眠会话汇总结果(一次查询提取所有信息,避免重复查询)。 */
internal data class SleepSessionsResult(
    val totalMinutes: Long,
    val startTime: Instant?,
    val endTime: Instant?,
    val stageMinutes: SleepStageMinutes?,
    val score: Int?
)

/** 用于选择睡眠记录的纯时间窗口,避免选择规则与 Samsung SDK 对象耦合。 */
internal data class SleepRecordWindow(
    val endTime: Instant,
    val durationMinutes: Long
)

/**
 * 选择最近结束的有效睡眠记录下标。
 *
 * 若没有已结束且达到最小时长的记录,回退到最长记录,保证 SDK 异常数据下仍可展示。
 */
internal fun selectLatestCompletedSleepRecordIndex(
    windows: List<SleepRecordWindow>,
    now: Instant,
    minSessionMinutes: Long = 30L
): Int? {
    if (windows.isEmpty()) return null

    val validIndices = windows.indices.filter { index ->
        val window = windows[index]
        window.endTime <= now && window.durationMinutes >= minSessionMinutes
    }
    return if (validIndices.isNotEmpty()) {
        validIndices.maxWithOrNull(
            compareBy<Int> { windows[it].endTime }
                .thenBy { windows[it].durationMinutes }
        )
    } else {
        windows.indices.maxByOrNull { windows[it].durationMinutes }
    }
}

/** 先合并阶段 Duration 再取整分钟,避免逐段取整造成累计误差。 */
internal fun sumDurationsInWholeMinutes(durations: Iterable<Duration>): Long? {
    val total = durations.fold(Duration.ZERO) { accumulated, duration ->
        accumulated.plus(duration)
    }
    return total.toMinutes().takeIf { it > 0 }
}

/**
 * Samsung SDK 的一条睡眠数据记录。
 *
 * 同一晚睡眠可能被拆成多个 [SleepSession],但 Samsung Health UI 会把这些子会话合并展示。
 */
private data class SleepRecordCandidate(
    val sessions: List<SleepSession>,
    val score: Int?
) {
    val startTime: Instant = sessions.minOf { it.startTime }
    val endTime: Instant = sessions.maxOf { it.endTime }
    val spanMinutes: Long = Duration.between(startTime, endTime).toMinutes()
}

/**
 * 睡眠会话读取器。
 *
 * Samsung Health 的一条睡眠数据记录可能包含多个 [SleepSession] 子会话,
 * 这里负责按"整条记录"选择最近结束的一晚, 并合并该记录内全部子会话的阶段时长,
 * 与 Samsung Health UI 对同一晚睡眠的展示口径保持一致。
 *
 * 方法统一为 internal: 对外只通过 [SamsungHealthReader] 门面暴露。
 */
@Singleton
class SamsungHealthSleepReader @Inject constructor(
    private val store: HealthDataStore
) {
    /**
     * 读取睡眠会话汇总(含阶段时长)。
     *
     * Samsung Health 的一条睡眠数据记录可能包含多个 SleepSession 子会话。
     * 先选择最近结束的整条数据记录,再合并该记录内的全部子会话,与 Samsung Health UI
     * 对同一晚睡眠的展示口径保持一致,同时避免把 48 小时窗口内不同晚的记录混在一起。
     */
    internal suspend fun readSleepSessions(now: Instant): SleepSessionsResult? = runCatching {
        val since = now.minus(48, ChronoUnit.HOURS)
        val request = DataTypes.SLEEP.readDataRequestBuilder
            .setInstantTimeFilter(InstantTimeFilter.of(since, now))
            .build()
        val response = store.readData(request)
        val candidates = response.dataList.mapNotNull { dp ->
            val score = dp.getValue<Int>(DataType.SleepType.SLEEP_SCORE)
            val sessions = dp.getValue<List<SleepSession>>(DataType.SleepType.SESSIONS) ?: emptyList()
            sessions.takeIf { it.isNotEmpty() }?.let {
                SleepRecordCandidate(sessions = it, score = score)
            }
        }
        if (candidates.isEmpty()) {
            Log.d(TAG, "未读取到睡眠记录")
            return@runCatching null
        }

        // 记录原始数据点和其中的子 session,便于排查 Samsung Health 展示差异。
        candidates.forEachIndexed { index, candidate ->
            Log.d(
                TAG,
                "睡眠记录[$index]: start=${candidate.startTime}, end=${candidate.endTime}, " +
                    "span=${candidate.spanMinutes}min, sessions=${candidate.sessions.size}, " +
                    "score=${candidate.score}"
            )
            candidate.sessions.forEachIndexed { sessionIndex, session ->
                Log.d(
                    TAG,
                    "睡眠记录[$index].session[$sessionIndex]: start=${session.startTime}, " +
                        "end=${session.endTime}, duration=${session.duration.toMinutes()}min, " +
                        "stages=${session.stages?.size ?: 0}"
                )
            }
        }

        // 选择最新的完整睡眠记录:
        // 1. 过滤结束时间超过当前时间的数据(避免异常未来数据)
        // 2. 过滤时长 < 30 分钟的碎片(午睡/小憩仍保留,夜间睡眠通常更长)
        // 3. 优先选择结束时间最接近当前时间,相同时选时长更长
        val selectedIndex = selectLatestCompletedSleepRecordIndex(
            windows = candidates.map { candidate ->
                SleepRecordWindow(
                    endTime = candidate.endTime,
                    durationMinutes = candidate.spanMinutes
                )
            },
            now = now
        ) ?: return@runCatching null
        val selectedRecord = candidates[selectedIndex]

        Log.d(
            TAG,
            "选定睡眠记录: start=${selectedRecord.startTime}, end=${selectedRecord.endTime}, " +
                "span=${selectedRecord.spanMinutes}min, sessions=${selectedRecord.sessions.size}"
        )

        val startTime = selectedRecord.startTime
        val endTime = selectedRecord.endTime

        // 合并同一睡眠记录内所有子 session 的阶段数据。
        val stages = selectedRecord.sessions.flatMap { it.stages ?: emptyList() }
        val stageMinutes = if (stages.isEmpty()) null else SleepStageMinutes(
            awake = sumDurationsInWholeMinutes(
                stages.filter { it.stage == DataType.SleepType.StageType.AWAKE }
                    .map { Duration.between(it.startTime, it.endTime) }
            ),
            light = sumDurationsInWholeMinutes(
                stages.filter { it.stage == DataType.SleepType.StageType.LIGHT }
                    .map { Duration.between(it.startTime, it.endTime) }
            ),
            deep = sumDurationsInWholeMinutes(
                stages.filter { it.stage == DataType.SleepType.StageType.DEEP }
                    .map { Duration.between(it.startTime, it.endTime) }
            ),
            rem = sumDurationsInWholeMinutes(
                stages.filter { it.stage == DataType.SleepType.StageType.REM }
                    .map { Duration.between(it.startTime, it.endTime) }
            )
        )

        // Samsung Health 的“实际睡眠时间”只包含浅睡、深睡和 REM,不包含清醒阶段。
        // 若 SDK 没有阶段数据,回退到所有子 session 时长之和,避免旧设备完全不显示时长。
        val actualSleepMinutes = sumDurationsInWholeMinutes(
            stages.filter {
                it.stage == DataType.SleepType.StageType.LIGHT ||
                    it.stage == DataType.SleepType.StageType.DEEP ||
                    it.stage == DataType.SleepType.StageType.REM
            }.map { Duration.between(it.startTime, it.endTime) }
        )
        val totalMinutes = actualSleepMinutes
            ?: selectedRecord.sessions.sumOf { it.duration.toMinutes() }

        SleepSessionsResult(
            totalMinutes = totalMinutes,
            startTime = startTime,
            endTime = endTime,
            stageMinutes = stageMinutes,
            score = selectedRecord.score
        )
    }.onFailure { e ->
        Log.w(TAG, "读取睡眠会话失败: ${e.message}")
    }.getOrNull()

    companion object {
        private const val TAG = "SamsungHealthSleep"
    }
}
