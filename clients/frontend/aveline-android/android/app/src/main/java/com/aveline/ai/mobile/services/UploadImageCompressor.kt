package com.aveline.ai.mobile.services

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import android.net.Uri
import java.io.ByteArrayOutputStream

/**
 * 上传前的本地图片压缩。
 *
 * 后端 `optimize_image` 也会压一次，但那是「先把原图传上去再压」—— 带宽已经花掉了。
 * 这里在本地先压一道，只把压缩后的字节发出去。
 *
 * 参数与后端 `core/image/image_utils.py` 对齐：长边 [MAX_LONG_SIDE]、JPEG 质量 [JPEG_QUALITY]；
 * 源图是 PNG 或含透明通道时保持 PNG，避免把透明压没（表情包、贴纸会变黑底）。
 */
object UploadImageCompressor {

    /** 与后端 DEFAULT_MAX_SIZE 保持一致。 */
    const val MAX_LONG_SIDE = 1600

    /** 与后端 DEFAULT_JPEG_QUALITY 保持一致。 */
    const val JPEG_QUALITY = 85

    /** 压缩结果：字节 + 实际 MIME（PNG 与 JPEG 二选一，必须跟内容一致）。 */
    class Result(val bytes: ByteArray, val mimeType: String)

    /**
     * 压缩用于上传的图片。
     *
     * 返回 null 表示「不要用压缩结果」，调用方应回退成上传原文件。以下情况返回 null：
     * - 不是图片，或者是 GIF（重编码会丢掉动图）；
     * - 解码失败（例如设备不支持该编码格式）；
     * - 压完反而更大（小图、已经优化过的图）。
     *
     * @param originalSize 原文件字节数，用于判断压缩是否真的更小；未知时传 0。
     */
    fun compress(context: Context, uri: Uri, mimeType: String?, originalSize: Long): Result? {
        if (!isCompressibleImage(mimeType)) return null

        val source = decodeDownsampled(context, uri) ?: return null
        var scaled: Bitmap? = null
        return try {
            scaled = scaleToMaxLongSide(source)
            val format = if (isPng(mimeType) || scaled.hasAlpha()) {
                Bitmap.CompressFormat.PNG
            } else {
                Bitmap.CompressFormat.JPEG
            }
            val out = ByteArrayOutputStream()
            // PNG 会忽略 quality（无损），JPEG 走 85。
            scaled.compress(format, JPEG_QUALITY, out)
            val bytes = out.toByteArray()

            if (originalSize > 0 && bytes.size >= originalSize) {
                null
            } else {
                Result(
                    bytes = bytes,
                    mimeType = if (format == Bitmap.CompressFormat.PNG) "image/png" else "image/jpeg"
                )
            }
        } catch (e: Exception) {
            null
        } finally {
            if (scaled != null && scaled !== source) scaled.recycle()
            source.recycle()
        }
    }

    private fun isCompressibleImage(mimeType: String?): Boolean {
        val type = mimeType?.lowercase() ?: return false
        // GIF 是动图，重编码成单帧等于把动画弄丢，直接传原图。
        return type.startsWith("image/") && type != "image/gif"
    }

    private fun isPng(mimeType: String?): Boolean = mimeType?.lowercase() == "image/png"

    /**
     * 按采样率解码，避免整张大图进内存。
     *
     * 先只读边界算采样率，再正式解码；采样率取 2 的幂，
     * 让解码结果的长边刚好不小于 [MAX_LONG_SIDE]，剩下的交给精确缩放。
     */
    private fun decodeDownsampled(context: Context, uri: Uri): Bitmap? {
        val resolver = context.contentResolver

        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null

        val options = BitmapFactory.Options().apply {
            inSampleSize = calculateInSampleSize(bounds.outWidth, bounds.outHeight)
            inPreferredConfig = Bitmap.Config.ARGB_8888
        }
        val decoded = resolver.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(it, null, options)
        } ?: return null

        return applyExifOrientation(context, uri, decoded)
    }

    private fun calculateInSampleSize(width: Int, height: Int): Int {
        var sample = 1
        var longSide = maxOf(width, height)
        while (longSide / 2 >= MAX_LONG_SIDE) {
            longSide /= 2
            sample *= 2
        }
        return sample
    }

    /**
     * 手动应用 EXIF 方向。
     *
     * `ImageDecoder` 会自动处理方向但要 API 28+，本项目 minSdk 26，所以走 BitmapFactory +
     * 手动旋转。不做这一步的话，手机竖拍照片上传后会显示成躺倒的。
     */
    private fun applyExifOrientation(context: Context, uri: Uri, bitmap: Bitmap): Bitmap {
        val orientation = try {
            context.contentResolver.openFileDescriptor(uri, "r")?.use { pfd ->
                ExifInterface(pfd.fileDescriptor).getAttributeInt(
                    ExifInterface.TAG_ORIENTATION,
                    ExifInterface.ORIENTATION_NORMAL
                )
            } ?: ExifInterface.ORIENTATION_NORMAL
        } catch (e: Exception) {
            ExifInterface.ORIENTATION_NORMAL
        }

        val matrix = Matrix()
        when (orientation) {
            ExifInterface.ORIENTATION_ROTATE_90 -> matrix.postRotate(90f)
            ExifInterface.ORIENTATION_ROTATE_180 -> matrix.postRotate(180f)
            ExifInterface.ORIENTATION_ROTATE_270 -> matrix.postRotate(270f)
            ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.postScale(-1f, 1f)
            ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.postScale(1f, -1f)
            ExifInterface.ORIENTATION_TRANSPOSE -> {
                matrix.postRotate(90f)
                matrix.postScale(-1f, 1f)
            }
            ExifInterface.ORIENTATION_TRANSVERSE -> {
                matrix.postRotate(270f)
                matrix.postScale(-1f, 1f)
            }
            else -> return bitmap
        }

        return try {
            val rotated = Bitmap.createBitmap(
                bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true
            )
            if (rotated !== bitmap) bitmap.recycle()
            rotated
        } catch (e: Exception) {
            bitmap
        }
    }

    private fun scaleToMaxLongSide(bitmap: Bitmap): Bitmap {
        val longSide = maxOf(bitmap.width, bitmap.height)
        if (longSide <= MAX_LONG_SIDE) return bitmap

        val ratio = MAX_LONG_SIDE.toFloat() / longSide
        val width = (bitmap.width * ratio).toInt().coerceAtLeast(1)
        val height = (bitmap.height * ratio).toInt().coerceAtLeast(1)
        return Bitmap.createScaledBitmap(bitmap, width, height, true)
    }
}
