package com.aveline.ai.mobile.utils

import android.content.Context

/**
 * Aveline 自身包名保护。
 *
 * 背景: AOSP 的 AccessibilityManagerService 会在某个包被 force-stop 时, 把该包拥有的
 * 已启用无障碍服务从 Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES 里删除并持久化。
 * 也就是说 Aveline 一旦对自己执行 am force-stop, 系统的无障碍开关会真的被关闭,
 * 表现就是"无障碍自己没了"。
 *
 * 因此所有"按包名操作应用"的入口 (force-stop / 应用限额 / 限额缓存 / 应用列表) 都必须
 * 先过这里, 排除 Aveline 自身。包名一律用运行时的 context.packageName 判断, 不硬编码,
 * 以同时覆盖 com.aveline.ai 与 com.aveline.ai.debug 两个变体。
 */
object SelfPackageGuard {

    /**
     * Aveline 应用族包名前缀。
     * 除了运行时包名, 同前缀的其它变体 (如正式包与 debug 包共存时) 也一并保护,
     * 避免 A 变体把 B 变体的无障碍授权顺手关掉。
     */
    private const val SELF_PACKAGE_PREFIX = "com.aveline.ai"

    /**
     * 判断包名是否属于 Aveline 自身。
     *
     * @param context 任意 Context, 实际只用 packageName
     * @param packageName 待判断的目标包名
     */
    fun isSelf(context: Context, packageName: String): Boolean {
        if (packageName.isBlank()) return false
        return packageName == context.packageName || packageName.startsWith(SELF_PACKAGE_PREFIX)
    }

    /**
     * 过滤掉其中属于 Aveline 自身的条目, 用于"包名 -> 限额毫秒"这类映射。
     */
    fun filterOutSelf(context: Context, source: Map<String, Long>): Map<String, Long> =
        source.filterKeys { !isSelf(context, it) }
}
