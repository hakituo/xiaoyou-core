package com.aveline.ai.mobile.utils

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Environment
import android.os.Process
import android.util.Log
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 崩溃处理器
 * 
 * 捕获未处理异常并记录崩溃日志
 * 
 * Requirements: 22.5, 22.6
 */
@Singleton
class CrashHandler @Inject constructor(
    @ApplicationContext private val context: Context
) : Thread.UncaughtExceptionHandler {
    
    private val dateFormat = SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", Locale.getDefault())
    
    // 系统默认异常处理器
    private var defaultHandler: Thread.UncaughtExceptionHandler? = null
    
    // 崩溃日志目录
    private val crashLogDir: File by lazy {
        File(context.filesDir, "crash_logs").apply {
            if (!exists()) mkdirs()
        }
    }
    
    /**
     * 初始化崩溃处理器
     */
    fun init() {
        defaultHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler(this)
    }
    
    override fun uncaughtException(thread: Thread, throwable: Throwable) {
        // 保存崩溃日志
        saveCrashLog(throwable)
        
        // 调用系统默认处理器
        defaultHandler?.uncaughtException(thread, throwable) ?: run {
            Process.killProcess(Process.myPid())
            System.exit(1)
        }
    }
    
    /**
     * 保存崩溃日志
     *
     * 优化:先用 StringBuilder 在内存构建完整日志内容,再一次性写入文件,
     * 减少崩溃线程上的 IO 开销(原实现多次 println 每次都触发 IO)。
     * catch 块用 Log.e 输出,避免静默吞异常导致日志丢失无任何痕迹。
     */
    private fun saveCrashLog(throwable: Throwable) {
        try {
            val timestamp = dateFormat.format(Date())
            val fileName = "crash_$timestamp.log"
            val logFile = File(crashLogDir, fileName)

            // 先在内存构建完整内容,减少文件 IO 次数
            val sb = StringBuilder()
            sb.appendLine("=== Aveline Crash Log ===")
            sb.appendLine("Time: ${Date()}")
            sb.appendLine()
            appendDeviceInfo(sb)
            appendAppInfo(sb)
            sb.appendLine("=== Crash Stack Trace ===")
            val sw = StringWriter()
            throwable.printStackTrace(PrintWriter(sw))
            sb.append(sw.toString())
            var cause = throwable.cause
            while (cause != null) {
                sb.appendLine()
                sb.appendLine("=== Caused by: ${cause.javaClass.name} ===")
                val csw = StringWriter()
                cause.printStackTrace(PrintWriter(csw))
                sb.append(csw.toString())
                cause = cause.cause
            }
            sb.appendLine()
            sb.appendLine("=== End of Crash Log ===")

            // 一次性写入文件
            logFile.writeText(sb.toString())
        } catch (e: Exception) {
            // 不再静默吞异常,至少用 Log.e 留下痕迹,便于排查日志丢失问题
            Log.e("CrashHandler", "保存崩溃日志失败", e)
        }
    }
    
    /**
     * 追加设备信息到 StringBuilder
     */
    private fun appendDeviceInfo(sb: StringBuilder) {
        sb.appendLine("=== Device Info ===")
        sb.appendLine("Brand: ${Build.BRAND}")
        sb.appendLine("Device: ${Build.DEVICE}")
        sb.appendLine("Model: ${Build.MODEL}")
        sb.appendLine("Product: ${Build.PRODUCT}")
        sb.appendLine("Manufacturer: ${Build.MANUFACTURER}")
        sb.appendLine("Android Version: ${Build.VERSION.RELEASE}")
        sb.appendLine("SDK Version: ${Build.VERSION.SDK_INT}")
        sb.appendLine("Build ID: ${Build.ID}")
        sb.appendLine()
    }

    /**
     * 追加应用信息到 StringBuilder
     */
    private fun appendAppInfo(sb: StringBuilder) {
        try {
            val packageInfo = context.packageManager.getPackageInfo(
                context.packageName,
                PackageManager.GET_ACTIVITIES
            )
            sb.appendLine("=== App Info ===")
            sb.appendLine("Package: ${context.packageName}")
            sb.appendLine("Version Name: ${packageInfo.versionName}")
            // longVersionCode 是 API 28+ 字段, 兼容 Android 8.0/8.1 (API 26/27) 用 versionCode
            val versionCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                packageInfo.longVersionCode
            } else {
                @Suppress("DEPRECATION")
                packageInfo.versionCode.toLong()
            }
            sb.appendLine("Version Code: $versionCode")
            sb.appendLine("Target SDK: ${context.applicationInfo.targetSdkVersion}")
            sb.appendLine()
        } catch (e: PackageManager.NameNotFoundException) {
            sb.appendLine("=== App Info ===")
            sb.appendLine("Unable to get app info: ${e.message}")
            sb.appendLine()
        }
    }
    
    /**
     * 获取崩溃日志列表
     */
    fun getCrashLogs(): List<File> {
        return crashLogDir.listFiles()
            ?.filter { it.name.startsWith("crash_") && it.name.endsWith(".log") }
            ?.sortedByDescending { it.lastModified() }
            ?: emptyList()
    }
    
    /**
     * 获取最新崩溃日志
     */
    fun getLatestCrashLog(): File? {
        return getCrashLogs().firstOrNull()
    }
    
    /**
     * 读取崩溃日志内容
     */
    fun readCrashLog(file: File): String {
        return try {
            file.readText()
        } catch (e: Exception) {
            "Unable to read crash log: ${e.message}"
        }
    }
    
    /**
     * 清除所有崩溃日志
     */
    fun clearCrashLogs() {
        getCrashLogs().forEach { it.delete() }
    }
    
    /**
     * 导出崩溃日志到外部存储
     */
    fun exportCrashLog(file: File, destDir: File): Boolean {
        return try {
            val destFile = File(destDir, file.name)
            file.copyTo(destFile, overwrite = true)
            true
        } catch (e: Exception) {
            false
        }
    }
    
    /**
     * 获取崩溃日志数量
     */
    fun getCrashLogCount(): Int {
        return getCrashLogs().size
    }
    
    /**
     * 检查是否有崩溃日志
     */
    fun hasCrashLogs(): Boolean {
        return getCrashLogs().isNotEmpty()
    }
}
