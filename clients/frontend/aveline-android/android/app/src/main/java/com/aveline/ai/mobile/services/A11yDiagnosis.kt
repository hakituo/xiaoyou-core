package com.aveline.ai.mobile.services

import android.content.Context
import android.os.Process
import android.util.Log
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 无障碍服务保活诊断工具。
 *
 * 把关键生命周期事件 (连接/解绑/销毁) 同时输出到两处, 用于确定"无障碍服务断掉"的根因:
 * 1. Logcat: tag 固定 "A11yDiag" (adb logcat -s A11yDiag 即可实时查看, 不依赖文件/MTP)
 * 2. 应用私有目录文件: Context.getFilesDir()/a11y_diagnosis.log
 *
 * 诊断文件路径: Context.getFilesDir()/a11y_diagnosis.log
 * 用户断线后把该文件内容或 Logcat 发给开发者即可定位。
 */
object A11yDiagnosis {

    private const val FILE_NAME = "a11y_diagnosis.log"
    private const val MAX_LINES = 200
    private const val LOG_TAG = "A11yDiag"

    private val timeFmt = SimpleDateFormat("MM-dd HH:mm:ss.SSS", Locale.getDefault())

    fun log(context: Context?, tag: String, message: String) {
        val ts = timeFmt.format(Date())
        val pid = Process.myPid()
        val lineText = "[$ts][pid=$pid][$tag] $message"
        // 1) 始终输出到 Logcat (最可靠, 不依赖文件系统/MTP)
        Log.i(LOG_TAG, lineText)
        // 2) 尝试写入文件 (失败也不影响)
        try {
            val dir = context?.filesDir ?: return
            val file = File(dir, FILE_NAME)
            val line = "$lineText\n"
            val existing = if (file.exists()) file.readLines() else emptyList()
            val trimmed = if (existing.size >= MAX_LINES) {
                existing.takeLast(MAX_LINES - 1)
            } else {
                existing
            }
            file.writeText((trimmed + line).joinToString(""))
        } catch (_: Exception) {
            // 诊断失败不应影响主流程
        }
    }

    fun read(context: Context?): String {
        return try {
            val dir = context?.filesDir ?: return "无诊断文件"
            val file = File(dir, FILE_NAME)
            if (!file.exists()) return "诊断文件不存在 (服务尚未记录任何事件)"
            file.readText()
        } catch (e: Exception) {
            "读取诊断失败: ${e.message}"
        }
    }
}
