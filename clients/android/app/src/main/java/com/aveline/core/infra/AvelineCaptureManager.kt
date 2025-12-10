package com.aveline.core.infra

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
import android.util.Base64
import com.aveline.core.ui.CapturePermissionActivity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream

object AvelineCaptureManager {
    private var mediaProjection: MediaProjection? = null

    fun onPermissionResult(activity: Activity, resultCode: Int, data: Intent) {
        val mpm = activity.getSystemService(MediaProjectionManager::class.java)
        mediaProjection = mpm.getMediaProjection(resultCode, data)
    }

    suspend fun captureOnce(context: Context): String {
        if (mediaProjection == null) {
            val intent = Intent(context, CapturePermissionActivity::class.java)
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
            return encodePlaceholder()
        }

        return withContext(Dispatchers.IO) {
            var reader: ImageReader? = null
            var vd: VirtualDisplay? = null
            try {
                val metrics = context.resources.displayMetrics
                val w = metrics.widthPixels
                val h = metrics.heightPixels
                val density = metrics.densityDpi

                reader = ImageReader.newInstance(w, h, ImageFormat.RGB_565, 2)
                
                // Create VirtualDisplay on Main thread to be safe
                withContext(Dispatchers.Main) {
                    vd = mediaProjection!!.createVirtualDisplay("aveline", w, h, density, DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, reader.surface, null, null)
                }

                // Wait for image availability (retry mechanism)
                var img: android.media.Image? = null
                for (i in 0..10) {
                    img = reader.acquireLatestImage()
                    if (img != null) break
                    delay(50) 
                }

                if (img == null) {
                    return@withContext encodePlaceholder()
                }

                val plane = img.planes[0]
                val pixelStride = plane.pixelStride
                val rowStride = plane.rowStride
                val rowPadding = rowStride - pixelStride * w
                val bmp = Bitmap.createBitmap(w + rowPadding / pixelStride, h, Bitmap.Config.RGB_565)
                bmp.copyPixelsFromBuffer(plane.buffer)
                
                // Crop padding if necessary
                val outBmp = Bitmap.createBitmap(bmp, 0, 0, w, h)
                
                val baos = ByteArrayOutputStream()
                outBmp.compress(Bitmap.CompressFormat.JPEG, 70, baos)
                val b64 = Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP)
                
                img.close()
                "data:image/jpeg;base64,$b64"
            } catch (e: Exception) {
                e.printStackTrace()
                encodePlaceholder()
            } finally {
                vd?.release()
                reader?.close()
            }
        }
    }

    private fun encodePlaceholder(): String {
        val png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/5+AAgMDAgBz8gvnAAAAAElFTkSuQmCC"
        return "data:image/png;base64," + png
    }
}
