package com.aveline.core.service

import android.accessibilityservice.AccessibilityService
import android.view.KeyEvent
import android.view.accessibility.AccessibilityEvent
import com.aveline.core.ui.AvelineOverlay
import com.aveline.core.infra.AvelineCaptureManager
import com.aveline.core.infra.HttpClient
import com.aveline.core.infra.AudioPlayer
import kotlinx.coroutines.*
import kotlin.coroutines.CoroutineContext

class AvelineAccessibilityService : AccessibilityService(), CoroutineScope {
    private val job = Job()
    override val coroutineContext: CoroutineContext
        get() = Dispatchers.Main + job

    private var isAnalyzing = false

    override fun onDestroy() {
        super.onDestroy()
        job.cancel()
        AvelineOverlay.remove()
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        val prefs = getSharedPreferences("config", MODE_PRIVATE)
        val savedIp = prefs.getString("server_ip", "http://10.0.2.2:5000")
        if (savedIp != null) {
            HttpClient.updateBaseUrl(savedIp)
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}

    override fun onKeyEvent(event: KeyEvent): Boolean {
        if (event.keyCode == KeyEvent.KEYCODE_VOLUME_DOWN && event.isLongPress) {
            if (isAnalyzing) return true
            
            launch {
                isAnalyzing = true
                try {
                    AvelineOverlay.ensure(this@AvelineAccessibilityService)
                    AvelineOverlay.setStatus("analyzing")
                    
                    val b64 = AvelineCaptureManager.captureOnce(this@AvelineAccessibilityService)
                    
                    val res = HttpClient.postAnalyze(b64)
                    
                    val label = res["label"] as? String
                    val audio = res["audio_base64"] as? String
                    
                    if (label == "fraud") {
                        AvelineOverlay.setStatus("danger")
                    } else {
                        AvelineOverlay.setStatus("idle")
                    }
                    
                    if (!audio.isNullOrEmpty()) {
                        AudioPlayer.playBase64(this@AvelineAccessibilityService, audio)
                    }
                } catch (e: Exception) {
                    e.printStackTrace()
                    AvelineOverlay.setStatus("idle")
                } finally {
                    isAnalyzing = false
                }
            }
            return true
        }
        return false
    }
}
