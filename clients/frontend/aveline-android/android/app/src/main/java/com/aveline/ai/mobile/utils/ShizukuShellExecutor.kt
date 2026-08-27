package com.aveline.ai.mobile.utils

import android.content.pm.PackageManager
import android.os.IBinder
import android.os.ParcelFileDescriptor
import android.util.Log
import rikka.shizuku.Shizuku

/**
 * Shizuku Shell 执行器
 *
 * 通过 Shizuku (以 shell uid 2000 运行) 执行系统命令,
 * 实现 am force-stop / pm uninstall / settings put 等需要 shell 权限的操作。
 *
 * 用反射调用 IShizukuService.newProcess, 避免 import 不确定的 AIDL 类名
 * (不同 Shizuku 版本 IShizukuService 包名可能变化, 反射更稳健)
 */
object ShizukuShellExecutor {
    private const val TAG = "ShizukuShellExecutor"

    /**
     * 检查 Shizuku 是否可用且已授权
     */
    fun isAvailable(): Boolean {
        return try {
            if (!Shizuku.pingBinder()) {
                Log.d(TAG, "Shizuku binder 未运行")
                return false
            }
            if (Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED) {
                Log.d(TAG, "Shizuku 未授权")
                return false
            }
            true
        } catch (e: Exception) {
            Log.w(TAG, "Shizuku 可用性检查失败: ${e.message}")
            false
        }
    }

    /**
     * 执行 shell 命令, 返回结果
     *
     * @param command 要执行的命令 (会通过 sh -c 包装, 支持管道/重定向)
     * @return ShellResult (success/stdout/stderr/exitCode)
     */
    fun execute(command: String): ShellResult {
        if (!isAvailable()) {
            return ShellResult(
                success = false,
                stdout = "",
                stderr = "Shizuku 不可用或未授权",
                exitCode = -1
            )
        }

        return try {
            val binder = Shizuku.getBinder()
                ?: return ShellResult(false, "", "Shizuku binder 为空", -1)

            // 用反射拿 IShizukuService (避免直接 import moe.shizuku.server.IShizukuService)
            val service = newShizukuService(binder)
                ?: return ShellResult(false, "", "无法获取 IShizukuService", -1)

            // 调用 newProcess(String[] cmd, String[] env, String cwd)
            val process = newProcess(service, arrayOf("sh", "-c", command), null, null)
                ?: return ShellResult(false, "", "newProcess 返回 null", -1)

            // 用反射拿 stdout / stderr / exitCode
            val stdout = readProcessStream(process, "getStdoutFileDescriptor")
            val stderr = readProcessStream(process, "getStderrFileDescriptor")
            val exitCode = waitForProcess(process)

            ShellResult(
                success = exitCode == 0,
                stdout = stdout,
                stderr = stderr,
                exitCode = exitCode
            )
        } catch (e: Exception) {
            Log.e(TAG, "Shizuku 执行命令失败: ${e.message}", e)
            ShellResult(false, "", "Shizuku 执行失败: ${e.message}", -1)
        }
    }

    /**
     * 用反射创建 IShizukuService 代理
     */
    private fun newShizukuService(binder: IBinder): Any? {
        return try {
            // 尝试 moe.shizuku.server.IShizukuService (Shizuku 13.x 标准)
            val serviceClass = try {
                Class.forName("moe.shizuku.server.IShizukuService")
            } catch (e: ClassNotFoundException) {
                // 回退: 某些版本可能在 dev.rikka.shizuku.server 下
                Class.forName("dev.rikka.shizuku.server.IShizukuService")
            }
            val asInterface = serviceClass.getDeclaredMethod("asInterface", IBinder::class.java)
            asInterface.invoke(null, binder)
        } catch (e: Exception) {
            Log.e(TAG, "创建 IShizukuService 失败: ${e.message}")
            null
        }
    }

    /**
     * 用反射调用 service.newProcess(cmd, env, cwd)
     */
    private fun newProcess(
        service: Any,
        cmd: Array<String>,
        env: Array<String>?,
        cwd: String?
    ): Any? {
        return try {
            val serviceClass = service.javaClass
            // newProcess 可能有多个重载, 尝试常见的 (String[], String[], String)
            val method = serviceClass.methods.firstOrNull {
                it.name == "newProcess" && it.parameterTypes.size == 3
            } ?: return null
            method.invoke(service, cmd, env, cwd)
        } catch (e: Exception) {
            Log.e(TAG, "调用 newProcess 失败: ${e.message}")
            null
        }
    }

    /**
     * 用反射读 process 的 stdout/stderr 流
     */
    private fun readProcessStream(process: Any, methodName: String): String {
        return try {
            val processClass = process.javaClass
            val method = processClass.methods.firstOrNull { it.name == methodName }
                ?: return ""
            val pfd = method.invoke(process) as? ParcelFileDescriptor ?: return ""
            ParcelFileDescriptor.AutoCloseInputStream(pfd).bufferedReader().use {
                it.readText()
            }
        } catch (e: Exception) {
            Log.w(TAG, "读 process 流失败 ($methodName): ${e.message}")
            ""
        }
    }

    /**
     * 用反射调 process.waitFor()
     */
    private fun waitForProcess(process: Any): Int {
        return try {
            val method = process.javaClass.methods.firstOrNull { it.name == "waitFor" }
            method?.invoke(process) as? Int ?: -1
        } catch (e: Exception) {
            Log.w(TAG, "waitFor 失败: ${e.message}")
            -1
        }
    }
}

/**
 * Shell 命令执行结果
 */
data class ShellResult(
    val success: Boolean,
    val stdout: String,
    val stderr: String,
    val exitCode: Int
)
