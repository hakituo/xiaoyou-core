package com.aveline.core

import android.view.KeyEvent
import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent

class AvelineAccessibilityService : AccessibilityService() {
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}
    override fun onKeyEvent(event: KeyEvent): Boolean {
        if (event.keyCode == KeyEvent.KEYCODE_VOLUME_DOWN && event.isLongPress) {
            AvelineOverlay.ensure(this)
            AvelineOverlay.setStatus("analyzing")
            AvelineCaptureManager.captureOnce(this) { b64 ->
                HttpClient.postAnalyze(this, b64) { res ->
                    val label = res["label"] as? String
                    val audio = res["audio_base64"] as? String
                    if (label == "fraud") AvelineOverlay.setStatus("danger") else AvelineOverlay.setStatus("idle")
                    if (!audio.isNullOrEmpty()) AudioPlayer.playBase64(this, audio)
                }
            }
            return true
        }
        return false
    }
}
