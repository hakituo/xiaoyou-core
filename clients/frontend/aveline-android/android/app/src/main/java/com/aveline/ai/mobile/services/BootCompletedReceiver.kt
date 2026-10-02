package com.aveline.ai.mobile.services

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.services.worker.DataSyncManager
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent

class BootCompletedReceiver : BroadcastReceiver() {

    @EntryPoint
    @InstallIn(SingletonComponent::class)
    interface BootReceiverEntryPoint {
        fun appPreferences(): AppPreferences
        fun dataSyncManager(): DataSyncManager
    }

    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        // 只处理 BOOT_COMPLETED。LOCKED_BOOT_COMPLETED 不适合启动同步/网络任务(此时设备仍锁定、
        // 应用私有存储可能是 device-protected, 且启动前台服务限制更严格)。
        if (action != Intent.ACTION_BOOT_COMPLETED) {
            return
        }

        try {
            val entryPoint = EntryPointAccessors.fromApplication(
                context.applicationContext,
                BootReceiverEntryPoint::class.java
            )
            val appPreferences = entryPoint.appPreferences()
            val dataSyncManager = entryPoint.dataSyncManager()

            // 受限启动: Android 15 (targetSdk 35) 限制从 BOOT_COMPLETED 直接启动 dataSync 类型
            // 前台服务。这里不再直接 startForegroundService, 改为用 WorkManager 注册周期同步,
            // 由系统在合规时机执行。前台常驻能力会受影响, 这正是"受限启动"的预期取舍。
            if (appPreferences.residentModeEnabled) {
                dataSyncManager.startPeriodicSync()
            }
        } catch (e: Exception) {
            Log.e("BootCompletedReceiver", "开机自启动失败", e)
        }
    }
}
