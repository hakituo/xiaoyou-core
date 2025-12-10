package com.aveline.core.ui

import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.os.Build
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import com.aveline.core.R

object AvelineOverlay {
    private var view: View? = null
    private var wm: WindowManager? = null

    fun ensure(context: Context) {
        if (view != null) return
        val appContext = context.applicationContext
        wm = appContext.getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val lp = WindowManager.LayoutParams()
        lp.width = WindowManager.LayoutParams.WRAP_CONTENT
        lp.height = WindowManager.LayoutParams.WRAP_CONTENT
        lp.gravity = Gravity.TOP or Gravity.END
        lp.format = PixelFormat.TRANSLUCENT
        lp.flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            lp.type = WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            lp.type = WindowManager.LayoutParams.TYPE_PHONE
        }
        val inflater = LayoutInflater.from(appContext)
        view = inflater.inflate(R.layout.overlay_view, null)
        wm?.addView(view, lp)
        setStatus("idle")
    }

    fun remove() {
        if (view != null && wm != null) {
            wm?.removeView(view)
            view = null
            wm = null
        }
    }

    fun setStatus(s: String) {
        val tv = view?.findViewById<TextView>(R.id.tvStatus)
        when (s) {
            "idle" -> {
                view?.setBackgroundColor(Color.argb(150, 0, 0, 0))
                tv?.text = "Idle"
            }
            "analyzing" -> {
                view?.setBackgroundColor(Color.argb(200, 255, 165, 0))
                tv?.text = "Analyzing"
            }
            "danger" -> {
                view?.setBackgroundColor(Color.argb(200, 255, 0, 0))
                tv?.text = "Danger"
            }
        }
    }
}
