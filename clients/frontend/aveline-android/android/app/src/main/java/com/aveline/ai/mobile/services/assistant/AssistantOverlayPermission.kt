package com.aveline.ai.mobile.services.assistant

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import android.util.Log

/**
 * 「允许显示在其他应用上层」这个特殊权限的读写。
 *
 * 它和录音、通知那类运行时权限不一样：**没有可以在应用内弹出的申请弹窗**，
 * 只能跳系统设置页让用户手动打开，所以必须自己判断 + 自己引导。
 */
object AssistantOverlayPermission {

    private const val TAG = "AssistantOverlayPerm"

    /**
     * 当前是否已授权。
     *
     * 注意 `Settings.canDrawOverlays` 在 API 23 以下恒为 true、23 及以上才反映真实开关；
     * 本工程 minSdk = 26，所以直接用它即可。
     */
    fun canDrawOverlays(context: Context): Boolean = Settings.canDrawOverlays(context)

    /**
     * 跳系统设置页去开「显示在其他应用上层」。
     *
     * 带 package uri 会直接定位到本应用的授权开关，比落在一堆应用列表里强。
     * 个别 ROM 不认这个 action，回退到应用详情页，至少让用户能自己找到权限入口。
     */
    fun openOverlaySettings(context: Context) {
        val overlayIntent = Intent(
            Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
            Uri.parse("package:${context.packageName}")
        ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

        runCatching { context.startActivity(overlayIntent) }
            .onFailure { error ->
                Log.w(TAG, "跳转悬浮窗授权页失败，回退应用详情页: ${error.message}")
                runCatching {
                    context.startActivity(
                        Intent(
                            Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                            Uri.parse("package:${context.packageName}")
                        ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    )
                }.onFailure { fallbackError ->
                    Log.e(TAG, "应用详情页也打不开: ${fallbackError.message}")
                }
            }
    }
}
