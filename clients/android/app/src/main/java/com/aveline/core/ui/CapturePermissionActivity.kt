package com.aveline.core.ui

import android.app.Activity
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.aveline.core.infra.AvelineCaptureManager

class CapturePermissionActivity : AppCompatActivity() {
    private val captureLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            AvelineCaptureManager.onPermissionResult(this, result.resultCode, result.data!!)
        }
        finish()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val mpm = getSystemService(MediaProjectionManager::class.java)
        val intent = mpm.createScreenCaptureIntent()
        captureLauncher.launch(intent)
    }
}
