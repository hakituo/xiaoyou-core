package com.aveline.ai.mobile.utils

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 分享工具类
 * 
 * 提供消息和图片分享功能
 * 
 * Requirements: 19.4, 19.5, 19.6
 */
@Singleton
class ShareUtils @Inject constructor(
    @ApplicationContext private val context: Context
) {
    /**
     * 分享文本消息
     * 
     * @param text 要分享的文本
     * @param title 分享对话框标题
     */
    fun shareText(
        text: String,
        title: String = "分享消息"
    ) {
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, text)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        
        val chooserIntent = Intent.createChooser(intent, title).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        
        context.startActivity(chooserIntent)
    }
    
    /**
     * 分享图片
     *
     * 修复 P0-32:原实现非 suspend 同步写 FileOutputStream(imageBytes)到磁盘,若从
     * Composable 的 onClick(Main 线程)调用会阻塞 UI。改为 suspend + 写文件在 IO 线程,
     * 构建 Intent/startActivity 在调用方调度器上运行(startActivity 可接受非主线程,只要
     * 使用 ApplicationContext + NEW_TASK)。
     *
     * @param imageBytes 图片字节数据
     * @param fileName 文件名
     * @param title 分享对话框标题
     */
    suspend fun shareImage(
        imageBytes: ByteArray,
        fileName: String = "shared_image.png",
        title: String = "分享图片"
    ) {
        // 写入文件放到 IO 线程
        val (imageFile, imageUri) = withContext(Dispatchers.IO) {
            val cachePath = File(context.cacheDir, "images")
            cachePath.mkdirs()
            val imageFile = File(cachePath, fileName)
            FileOutputStream(imageFile).use { output ->
                output.write(imageBytes)
            }
            imageFile to FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                imageFile
            )
        }

        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "image/png"
            putExtra(Intent.EXTRA_STREAM, imageUri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        val chooserIntent = Intent.createChooser(intent, title).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        context.startActivity(chooserIntent)
    }

    /**
     * 分享文本和图片
     *
     * 说明:同样将文件写入下沉到 IO 线程,避免主线程阻塞。
     */
    suspend fun shareTextAndImage(
        text: String,
        imageBytes: ByteArray,
        fileName: String = "shared_image.png",
        title: String = "分享内容"
    ) {
        val imageUri = withContext(Dispatchers.IO) {
            val cachePath = File(context.cacheDir, "images")
            cachePath.mkdirs()
            val imageFile = File(cachePath, fileName)
            FileOutputStream(imageFile).use { output ->
                output.write(imageBytes)
            }
            FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                imageFile
            )
        }

        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "image/png"
            putExtra(Intent.EXTRA_TEXT, text)
            putExtra(Intent.EXTRA_STREAM, imageUri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        val chooserIntent = Intent.createChooser(intent, title).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        context.startActivity(chooserIntent)
    }
    
    /**
     * 清理分享缓存
     */
    fun clearShareCache() {
        val cachePath = File(context.cacheDir, "images")
        if (cachePath.exists() && cachePath.isDirectory) {
            cachePath.listFiles()?.forEach { it.delete() }
        }
    }
}
