package com.aveline.ai.mobile.services.wellbeing

/**
 * 单个应用的数字健康策略。
 *
 * 与 Codex 那种"5 小时 / 周额度窗口"不同, 手机 App 的使用习惯是
 * **"每天总量 + 每次连续时长"**, 因此这里只有两类硬限制, 二者同时生效并取更严格的那个:
 *
 * - [dailyLimitMs]   每天总共允许多久 (从当天 00:00 起算, 到次日 00:00 重置)
 * - [sessionLimitMs] 一次连续使用最多多久 ("连续"由 [sessionGapMs] 界定)
 *
 * 另外两个参数专门用来堵"退出再打开"绕过单次限制:
 * - [sessionGapMs] 离开多久才算本次使用结束; 小于该值的离开视为同一次, 回来继续累计
 * - [cooldownMs]  单次超限后多久才能重新打开; 冷却期内进入前台立即再次拦截
 *
 * 典型配置:
 * ```
 * 抖音  每日 60 分钟 / 单次 10 分钟 / 离开 2 分钟算结束 / 超时休息 5 分钟
 * ```
 * 效果是"今天最多刷 1 小时, 但不能一口气刷完, 每 10 分钟必须停一下"。
 */
data class AppLimitPolicy(
    val packageName: String,
    val dailyLimitMs: Long = 0L,
    val sessionLimitMs: Long = 0L,
    val sessionGapMs: Long = DEFAULT_SESSION_GAP_MS,
    val cooldownMs: Long = DEFAULT_COOLDOWN_MS,
) {

    /** 两条限制都没配 = 该应用不设限。 */
    val isEmpty: Boolean
        get() = dailyLimitMs <= 0 && sessionLimitMs <= 0

    companion object {
        /** 默认"离开 2 分钟算作本次使用结束"。 */
        const val DEFAULT_SESSION_GAP_MS = 2 * 60_000L

        /** 默认"单次超时后休息 5 分钟"。 */
        const val DEFAULT_COOLDOWN_MS = 5 * 60_000L

        /**
         * 归一化构造: 补齐缺省值, 保证"退出再打开"不能绕过单次限制。
         *
         * - sessionGapMs <= 0 时回落到 [DEFAULT_SESSION_GAP_MS]: 间隔为 0 意味着
         *   每次切后台都能白拿一份新的单次额度, 单次限制形同虚设。
         * - 只有配了 [sessionLimitMs] 时冷却才有意义; 未配时回落到 [DEFAULT_COOLDOWN_MS],
         *   否则超时后可以立刻重开, 同样等于没有限制。
         */
        fun of(
            packageName: String,
            dailyLimitMs: Long,
            sessionLimitMs: Long,
            sessionGapMs: Long = 0L,
            cooldownMs: Long = 0L,
        ): AppLimitPolicy = AppLimitPolicy(
            packageName = packageName,
            dailyLimitMs = dailyLimitMs.coerceAtLeast(0L),
            sessionLimitMs = sessionLimitMs.coerceAtLeast(0L),
            sessionGapMs = sessionGapMs.takeIf { it > 0 } ?: DEFAULT_SESSION_GAP_MS,
            cooldownMs = if (sessionLimitMs > 0) {
                cooldownMs.takeIf { it > 0 } ?: DEFAULT_COOLDOWN_MS
            } else {
                0L
            },
        )
    }
}

/**
 * 策略的本地序列化/反序列化。
 *
 * 存储格式: `"pkg1=每日:单次:间隔:冷却,pkg2=..."`, 例:
 * ```
 * com.ss.android.ugc.aweme=3600000:600000:120000:300000
 * ```
 * 包名不含 `=` `:` `,` , 直接按这三个字符切分是安全的。
 */
object AppLimitPolicyCodec {

    /** 序列化为 SharedPreferences 字符串 (自动剔除空策略)。 */
    fun format(policies: Collection<AppLimitPolicy>): String =
        policies
            .filter { it.packageName.isNotBlank() && !it.isEmpty }
            .joinToString(",") { policy ->
                "${policy.packageName}=${policy.dailyLimitMs}:${policy.sessionLimitMs}" +
                    ":${policy.sessionGapMs}:${policy.cooldownMs}"
            }

    /** 反序列化为 "包名 -> 策略"。 */
    fun parse(raw: String): Map<String, AppLimitPolicy> = buildMap {
        raw.split(',').forEach { entry ->
            val separator = entry.indexOf('=')
            if (separator <= 0) return@forEach
            val packageName = entry.substring(0, separator).trim()
            if (packageName.isBlank()) return@forEach
            val parts = entry.substring(separator + 1).split(':')
            val policy = AppLimitPolicy.of(
                packageName = packageName,
                dailyLimitMs = parts.getOrNull(0)?.trim()?.toLongOrNull() ?: 0L,
                sessionLimitMs = parts.getOrNull(1)?.trim()?.toLongOrNull() ?: 0L,
                sessionGapMs = parts.getOrNull(2)?.trim()?.toLongOrNull() ?: 0L,
                cooldownMs = parts.getOrNull(3)?.trim()?.toLongOrNull() ?: 0L,
            )
            if (!policy.isEmpty) put(packageName, policy)
        }
    }

    /**
     * 兼容旧后端: 老版本只下发 `app_limits`(每日) 与 `session_caps`(一次性 cap),
     * 没有间隔/冷却概念。这里用默认值补齐成完整策略。
     */
    fun fromLegacy(
        dailyLimits: Map<String, Long>,
        sessionCaps: Map<String, Long>,
    ): List<AppLimitPolicy> = (dailyLimits.keys + sessionCaps.keys)
        .filter { it.isNotBlank() }
        .distinct()
        .map { pkg ->
            AppLimitPolicy.of(
                packageName = pkg,
                dailyLimitMs = dailyLimits[pkg] ?: 0L,
                sessionLimitMs = sessionCaps[pkg] ?: 0L,
            )
        }
        .filter { !it.isEmpty }
}
