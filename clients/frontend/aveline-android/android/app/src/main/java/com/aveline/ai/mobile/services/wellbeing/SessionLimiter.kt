package com.aveline.ai.mobile.services.wellbeing

import android.content.Context
import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.domain.repository.ContextRepository
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.time.LocalDate
import java.time.ZoneId
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 数字健康的会话状态机与限额判定核心。
 *
 * ```
 *                 AppLimitPolicy
 *                       │
 *             ┌─────────┴─────────┐
 *             │                   │
 *        DailyLimit          SessionLimit
 *      今日总额度            单次连续额度
 *             │                   │
 *             └─────────┬─────────┘
 *                       ↓
 *                LimitDecision
 *              ALLOW / BLOCK
 * ```
 *
 * 两条限制**同时生效并取更严格的那个**:
 * - 每日额度耗尽 → 今天都不能用 (次日 00:00 自动重置)
 * - 单次额度耗尽 → 进入冷却, 冷却结束后 **新的一次**又有完整的单次额度, 但每日额度不会重置
 *
 * "一次"的定义由 [AppLimitPolicy.sessionGapMs] 决定:
 * ```
 * 离开 < gap  → 仍是同一次, 回来接着累计
 * 离开 ≥ gap  → 本次结束, 下次打开建立新会话
 * ```
 * 这样"用 9分50秒 → Home → 立刻重开"拿不到新的 10 分钟。
 *
 * 用量口径统一取 UsageStatsManager 的当日前台时长 (见 ContextRepository.getAppUsageSince),
 * 单次用量 = 当日累计 - 会话开始时的基线, 因此切去别的应用不会污染本应用的计数。
 *
 * 调用方与模式:
 * - [noteForeground]: 无障碍服务实时调用 (应用在前台), 完整状态机 + 两类拦截
 * - [enforceFallback]: 15 分钟 Worker 兜底, 只校验每日额度并清理过期会话
 * - [peek]: 只读, 供 UI 展示"本次已用/剩余冷却"
 */
@Singleton
class SessionLimiter @Inject constructor(
    @ApplicationContext private val context: Context,
    private val appPreferences: AppPreferences,
    private val contextRepository: ContextRepository,
) {

    /** 判定模式。 */
    private enum class EvalMode {
        /** 应用确实在前台: 允许推进状态机并触发单次/每日拦截。 */
        FOREGROUND,

        /** 兜底校验: 只处理每日额度与过期会话, 不判定单次 (拿不到前台信息)。 */
        FALLBACK,

        /** 只读: 不做任何状态变更。 */
        PEEK,
    }

    /** 拦截原因。 */
    enum class BlockReason {
        /** 今日额度用完。 */
        DAILY,

        /** 单次连续使用超时。 */
        SESSION,

        /** 单次超时后的冷却期。 */
        COOLDOWN,
    }

    /** 限额判定结果。 */
    sealed interface LimitDecision {

        /** 允许继续使用。 */
        data class Allow(
            val dailyUsedMs: Long,
            val dailyLimitMs: Long,
            val sessionUsedMs: Long,
            val sessionLimitMs: Long,
        ) : LimitDecision

        /** 需要拦截。 */
        data class Block(
            val reason: BlockReason,
            /** 用户可见的原因短语 (不含应用名, 由执行方拼接)。 */
            val reasonText: String,
            /** 解禁时刻 (epoch 毫秒); 0 表示到次日 00:00 才解禁。 */
            val blockedUntilMs: Long,
            val dailyUsedMs: Long,
            val dailyLimitMs: Long,
            val sessionUsedMs: Long,
            val sessionLimitMs: Long,
        ) : LimitDecision
    }

    /**
     * 单个应用的会话状态 (跨进程持久化, 进程被回收后仍能恢复)。
     *
     * @property day 状态所属日期, 跨天整体失效
     * @property startMs 本次会话开始时刻; <= 0 表示当前没有进行中的会话
     * @property baselineDailyMs 会话开始时该应用的当日累计用量 (单次用量 = 当前累计 - 基线)
     * @property lastForegroundMs 最近一次确认在前台的时刻, 作为 sessionGap 的计时起点
     * @property blockedUntilMs 冷却截止时刻; 0 表示不在冷却中
     * @property dailyBlockedDay 每日额度耗尽的日期 (yyyy-MM-dd); 跨天自动失效
     */
    private data class SessionState(
        val packageName: String,
        val day: String = "",
        val startMs: Long = 0L,
        val baselineDailyMs: Long = 0L,
        val lastForegroundMs: Long = 0L,
        val blockedUntilMs: Long = 0L,
        val dailyBlockedDay: String = "",
    )

    private val mutex = Mutex()

    @Volatile
    private var cachedPolicies: Map<String, AppLimitPolicy>? = null

    @Volatile
    private var migrationChecked = false

    // ── 策略读写 ──────────────────────────────────────────

    /**
     * 旧版配置一次性迁移。
     *
     * 必须发生在"第一次读取"而不是"第一次写入": 写入会立刻覆盖迁移结果,
     * 迁移的意义是让无障碍服务在 App 升级后、下一次同步之前继续有可用的限额。
     */
    private fun ensureMigrated() {
        if (migrationChecked) return
        migrationChecked = true
        if (appPreferences.migrateLegacyUsageLimits()) {
            Log.i(TAG, "数字健康: 已迁移旧版限额配置到新策略表")
        }
    }

    /** 当前生效的策略表 (包名 -> 策略)。 */
    fun policies(): Map<String, AppLimitPolicy> {
        ensureMigrated()
        cachedPolicies?.let { return it }
        val parsed = AppLimitPolicyCodec.parse(appPreferences.appLimitPolicies)
        cachedPolicies = parsed
        return parsed
    }

    /** 单个应用的策略, 未设限返回 null。 */
    fun policyFor(packageName: String): AppLimitPolicy? = policies()[packageName]

    /**
     * 全量覆盖策略 (后端下发 / 页面保存后调用)。
     *
     * 同步清理已移除策略应用的残留会话状态, 避免旧状态继续拦截或污染 UI。
     */
    suspend fun replacePolicies(policies: Collection<AppLimitPolicy>) = mutex.withLock {
        ensureMigrated()
        appPreferences.appLimitPolicies = AppLimitPolicyCodec.format(policies)
        cachedPolicies = null
        val allowed = policies.map { it.packageName }.toSet()
        val states = loadStates().toMutableMap()
        val removed = states.keys.filter { it !in allowed }
        if (removed.isNotEmpty()) {
            removed.forEach { states.remove(it) }
            saveStates(states)
        }
    }

    // ── 状态机入口 ────────────────────────────────────────

    /**
     * 应用进入前台 (或持续处于前台): 推进会话状态机并给出判定。
     *
     * 由无障碍服务实时调用, 是单次额度的主要执行路径。
     */
    suspend fun noteForeground(
        packageName: String,
        nowMs: Long = System.currentTimeMillis(),
    ): LimitDecision = mutex.withLock {
        evaluateLocked(packageName, nowMs, EvalMode.FOREGROUND)
    }

    /**
     * 应用离开前台: 记录离开时刻, 作为 sessionGap 的计时起点。
     *
     * 不结束会话 —— 是否算"新的一次"由下次进入前台时的间隔决定。
     */
    suspend fun noteBackground(
        packageName: String,
        nowMs: Long = System.currentTimeMillis(),
    ) {
        mutex.withLock {
            val states = loadStates().toMutableMap()
            val state = states[packageName] ?: return@withLock
            states[packageName] = state.copy(lastForegroundMs = nowMs)
            saveStates(states)
        }
    }

    /**
     * 兜底校验 (15 分钟 Worker): 只处理每日额度与过期会话清理。
     *
     * Worker 拿不到前台信息, 且周期远粗于单次额度, 因此不在这里判定单次额度,
     * 避免"打开 1 分钟被 15 分钟前的旧状态误杀"。
     */
    suspend fun enforceFallback(
        packageName: String,
        nowMs: Long = System.currentTimeMillis(),
    ): LimitDecision = mutex.withLock {
        evaluateLocked(packageName, nowMs, EvalMode.FALLBACK)
    }

    /** 只读判定: 不推进状态机, 供 UI 展示使用。 */
    suspend fun peek(
        packageName: String,
        nowMs: Long = System.currentTimeMillis(),
    ): LimitDecision = mutex.withLock {
        evaluateLocked(packageName, nowMs, EvalMode.PEEK)
    }

    /**
     * 清理过期会话与孤儿状态 (Worker 兜底 / 页面刷新时调用)。
     *
     * 长时间离开后如果没有这一步, UI 会一直显示上一次的"本次已用"。
     */
    suspend fun reconcile(nowMs: Long = System.currentTimeMillis()) = mutex.withLock {
        val policies = policies()
        val today = LocalDate.now().toString()
        val states = loadStates().toMutableMap()
        var changed = false
        for ((pkg, state) in states.entries.toList()) {
            val policy = policies[pkg]
            when {
                policy == null || state.day != today -> {
                    states.remove(pkg)
                    changed = true
                }
                state.startMs > 0 && nowMs - state.lastForegroundMs >= policy.sessionGapMs -> {
                    // 本次使用已结束, 下次打开将建立新会话。
                    // 注意不能顺带清掉 blockedUntilMs: 处于冷却期且不在前台时,
                    // lastForegroundMs 早已过期, 清掉冷却会让用户立刻重新进入。
                    states[pkg] = state.copy(startMs = 0L)
                    changed = true
                }
            }
        }
        if (changed) saveStates(states)
    }

    /** 清除单个应用的所有会话状态 (移除限额时调用)。 */
    suspend fun reset(packageName: String) {
        mutex.withLock {
            val states = loadStates().toMutableMap()
            if (states.remove(packageName) != null) saveStates(states)
        }
    }

    // ── 判定核心 ──────────────────────────────────────────

    private suspend fun evaluateLocked(
        packageName: String,
        nowMs: Long,
        mode: EvalMode,
    ): LimitDecision {
        val policy = policies()[packageName]
            ?: return LimitDecision.Allow(0L, 0L, 0L, 0L)

        if (!contextRepository.hasUsageStatsPermission()) {
            // 拿不到用量时不做任何拦截, 否则会把"统计失败"误判成"没超时"
            return LimitDecision.Allow(0L, policy.dailyLimitMs, 0L, policy.sessionLimitMs)
        }

        val today = LocalDate.now().toString()
        val dayStart = todayStartMs()
        val usageMs = contextRepository.getAppUsageSince(dayStart)
            .firstOrNull { it.packageName == packageName }
            ?.usageTimeMs ?: 0L

        val states = loadStates().toMutableMap()
        var state = states[packageName]?.takeIf { it.day == today }
            ?: SessionState(packageName = packageName, day = today)

        // 1) 冷却未过: 单次超时后的休息期内一律拦下, 与本次已用多久无关
        if (state.blockedUntilMs > nowMs) {
            if (mode != EvalMode.PEEK) saveStates(states)
            return LimitDecision.Block(
                reason = BlockReason.COOLDOWN,
                reasonText = "还在休息时间",
                blockedUntilMs = state.blockedUntilMs,
                dailyUsedMs = usageMs,
                dailyLimitMs = policy.dailyLimitMs,
                sessionUsedMs = 0L,
                sessionLimitMs = policy.sessionLimitMs,
            )
        }

        // 2) 今日额度已用完: 次日 00:00 前都不可用
        if (state.dailyBlockedDay == today) {
            if (mode != EvalMode.PEEK) saveStates(states)
            return dailyBlocked(usageMs, policy)
        }

        // 3) 会话判定: 离开超过 sessionGap 才算"新的一次"
        val gapExpired = state.startMs <= 0L ||
            nowMs - state.lastForegroundMs >= policy.sessionGapMs
        if (mode == EvalMode.FOREGROUND && gapExpired) {
            state = state.copy(
                startMs = nowMs,
                baselineDailyMs = usageMs,
                lastForegroundMs = nowMs,
            )
        }
        val sessionUsedMs = if (gapExpired) {
            0L
        } else {
            (usageMs - state.baselineDailyMs).coerceAtLeast(0L)
        }

        // 4) 每日额度: 与单次额度取更严格的那个, 哪怕本次才用了 30 秒
        if (policy.dailyLimitMs > 0 && usageMs >= policy.dailyLimitMs) {
            if (mode != EvalMode.PEEK) {
                states[packageName] = state.copy(
                    dailyBlockedDay = today,
                    startMs = 0L,
                    blockedUntilMs = 0L,
                    lastForegroundMs = nowMs,
                )
                saveStates(states)
            }
            return dailyBlocked(usageMs, policy)
        }

        // 5) 单次额度: 只在确认前台时判定 (Worker 没有前台信息, 不能替用户结束会话)
        if (mode == EvalMode.FOREGROUND &&
            policy.sessionLimitMs > 0 &&
            sessionUsedMs >= policy.sessionLimitMs
        ) {
            val cooldownUntil = nowMs + policy.cooldownMs
            states[packageName] = state.copy(
                startMs = 0L,
                lastForegroundMs = nowMs,
                blockedUntilMs = cooldownUntil,
            )
            saveStates(states)
            return LimitDecision.Block(
                reason = BlockReason.SESSION,
                reasonText = "本次已用满 ${formatDuration(policy.sessionLimitMs)}, 先休息一下",
                blockedUntilMs = cooldownUntil,
                dailyUsedMs = usageMs,
                dailyLimitMs = policy.dailyLimitMs,
                sessionUsedMs = sessionUsedMs,
                sessionLimitMs = policy.sessionLimitMs,
            )
        }

        // 6) 允许: 前台模式下刷新"最近前台时刻", 维持同一次会话
        if (mode == EvalMode.FOREGROUND) {
            states[packageName] = state.copy(
                lastForegroundMs = nowMs,
                blockedUntilMs = 0L,
            )
            saveStates(states)
        }
        return LimitDecision.Allow(
            dailyUsedMs = usageMs,
            dailyLimitMs = policy.dailyLimitMs,
            sessionUsedMs = sessionUsedMs,
            sessionLimitMs = policy.sessionLimitMs,
        )
    }

    private fun dailyBlocked(
        usageMs: Long,
        policy: AppLimitPolicy,
    ) = LimitDecision.Block(
        reason = BlockReason.DAILY,
        reasonText = "今日额度已用完",
        blockedUntilMs = 0L,
        dailyUsedMs = usageMs,
        dailyLimitMs = policy.dailyLimitMs,
        sessionUsedMs = 0L,
        sessionLimitMs = policy.sessionLimitMs,
    )

    // ── 持久化 ────────────────────────────────────────────

    private fun loadStates(): Map<String, SessionState> = buildMap {
        appPreferences.appSessionStates.split(',').forEach { entry ->
            val separator = entry.indexOf('=')
            if (separator <= 0) return@forEach
            val packageName = entry.substring(0, separator).trim()
            val parts = entry.substring(separator + 1).split('|')
            if (packageName.isBlank() || parts.size < STATE_FIELDS) return@forEach
            put(
                packageName,
                SessionState(
                    packageName = packageName,
                    day = parts[0],
                    startMs = parts[1].toLongOrNull() ?: 0L,
                    baselineDailyMs = parts[2].toLongOrNull() ?: 0L,
                    lastForegroundMs = parts[3].toLongOrNull() ?: 0L,
                    blockedUntilMs = parts[4].toLongOrNull() ?: 0L,
                    dailyBlockedDay = parts.getOrNull(5).orEmpty(),
                )
            )
        }
    }

    private fun saveStates(states: Map<String, SessionState>) {
        appPreferences.appSessionStates = states.values
            .filter { it.day.isNotBlank() }
            .joinToString(",") { state ->
                "${state.packageName}=${state.day}|${state.startMs}|${state.baselineDailyMs}" +
                    "|${state.lastForegroundMs}|${state.blockedUntilMs}|${state.dailyBlockedDay}"
            }
    }

    private fun todayStartMs(): Long = LocalDate.now()
        .atStartOfDay(ZoneId.systemDefault())
        .toInstant()
        .toEpochMilli()

    /** 应用展示名 (取不到时退回包名)。 */
    fun appLabel(packageName: String): String = try {
        context.packageManager
            .getApplicationLabel(context.packageManager.getApplicationInfo(packageName, 0))
            .toString()
    } catch (e: Exception) {
        packageName
    }

    companion object {
        private const val TAG = "SessionLimiter"

        /** 会话状态序列化字段数: day|start|baseline|lastFg|blockedUntil|dailyBlockedDay */
        private const val STATE_FIELDS = 6

        /** 毫秒格式化为 "1h20m" / "20m" / "30s", 供提示文案使用。 */
        fun formatDuration(ms: Long): String {
            if (ms <= 0) return "0m"
            if (ms < 60_000) return "${(ms / 1000).coerceAtLeast(1)}s"
            val totalMin = ms / 60_000
            val h = totalMin / 60
            val m = totalMin % 60
            return if (h > 0) "${h}h${if (m > 0) "${m}m" else ""}" else "${m}m"
        }
    }
}
