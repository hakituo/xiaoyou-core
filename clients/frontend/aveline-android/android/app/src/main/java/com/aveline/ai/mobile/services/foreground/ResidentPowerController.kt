package com.aveline.ai.mobile.services.foreground

import android.content.Context
import android.os.PowerManager

/** 管理常驻模式持有的 PARTIAL_WAKE_LOCK。 */
class ResidentPowerController(private val context: Context) {
    private var wakeLock: PowerManager.WakeLock? = null

    fun acquire() {
        if (wakeLock?.isHeld == true) return
        val powerManager = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = powerManager.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "AvelineApp:ForegroundServiceWakeLock"
        ).apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    fun release() {
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
    }
}
