package com.aveline.core

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.ImageFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.util.Base64
import java.io.ByteArrayOutputStream

object AvelineCaptureManager {
    private var mediaProjection: MediaProjection? = null
    private var vd: VirtualDisplay? = null
    private var reader: ImageReader? = null
    fun onPermissionResult(activity: Activity, resultCode: Int, data: Intent) {
        val mpm = activity.getSystemService(MediaProjectionManager::class.java)
        mediaProjection = mpm.getMediaProjection(resultCode, data)
    }
    fun captureOnce(context: Context, cb: (String) -> Unit) {
        val metrics = context.resources.displayMetrics
        val w = metrics.widthPixels
        val h = metrics.heightPixels
        val density = metrics.densityDpi
        if (mediaProjection == null) {
            val intent = Intent(context, CapturePermissionActivity::class.java)
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
            cb(encodePlaceholder())
            return
        }
        reader = ImageReader.newInstance(w, h, ImageFormat.RGB_565, 2)
        vd = mediaProjection!!.createVirtualDisplay("aveline", w, h, density, DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, reader!!.surface, null, null)
        val img = reader!!.acquireLatestImage()
        if (img == null) {
            cb(encodePlaceholder())
            release()
            return
        }
        val plane = img.planes[0]
        val pixelStride = plane.pixelStride
        val rowStride = plane.rowStride
        val rowPadding = rowStride - pixelStride * w
        val bmp = Bitmap.createBitmap(w + rowPadding / pixelStride, h, Bitmap.Config.RGB_565)
        bmp.copyPixelsFromBuffer(plane.buffer)
        val outBmp = Bitmap.createBitmap(bmp, 0, 0, w, h)
        val baos = ByteArrayOutputStream()
        outBmp.compress(Bitmap.CompressFormat.JPEG, 70, baos)
        val b64 = Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP)
        cb("data:image/jpeg;base64," + b64)
        img.close()
        release()
    }
    private fun release() {
        vd?.release()
        reader?.close()
    }
    private fun encodePlaceholder(): String {
        val png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/5+AAgMDAgBz8gvnAAAAAElFTkSuQmCC"
        return "data:image/png;base64," + png
    }
}
