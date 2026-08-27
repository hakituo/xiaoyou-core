package com.aveline.ai.mobile.services

import android.Manifest
import android.annotation.SuppressLint
import android.app.ActivityManager
import android.app.AppOpsManager
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.location.Geocoder
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.Process
import android.app.WallpaperManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Base64
import android.util.Log
import com.aveline.ai.mobile.utils.ShizukuShellExecutor
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.util.Locale
import kotlin.coroutines.resume

/**
 * 系统控制执行器
 *
 * 接收后端下发的 device_command 指令, 在手机端执行系统操作, 返回结果。
 *
 * 指令清单:
 * - force_stop_app: 强制停止应用 (Shizuku am force-stop, 降级 killBackgroundProcesses)
 * - list_installed_apps: 列出已安装应用
 * - start_app: 启动应用
 * - get_app_usage_time: 查询应用使用时长 (UsageStatsManager)
 * - capture_screen: 截图手机屏幕 (Shizuku screencap)
 * - get_device_location: 获取地理位置 (原生 LocationManager, 不依赖 Google Play 服务)
 * - list_paired_bluetooth_devices: 列出已配对蓝牙设备 (含连接状态)
 * - scan_bluetooth_devices: 扫描附近蓝牙设备 (异步, 10s)
 * - pair_bluetooth_device: 配对蓝牙设备 (反射 createBond)
 * - unpair_bluetooth_device: 取消配对 (反射 removeBond)
 * - a11y_click_at: 按坐标点击屏幕 (GestureDescription)
 * - a11y_swipe: 滑动屏幕 (GestureDescription)
 * - a11y_go_back: 模拟返回键
 * - a11y_go_home: 模拟桌面键
 * - a11y_find_and_click: 找文字并点击
 * - a11y_dump_visible_text: dump 当前屏幕可见文本树 (供 AI 看屏幕内容)
 * - set_wallpaper: 设置手机壁纸 (base64 → Bitmap → WallpaperManager)
 *
 * 设计: 模仿 PhoneActionExecutor 的 execute → when 模式, 但用 JsonObject 返回复杂结构
 */
@javax.inject.Singleton
class SystemControlExecutor @javax.inject.Inject constructor(
    @ApplicationContext private val context: Context
) {
    companion object {
        private const val TAG = "SystemControlExecutor"

        // Android 组件名包名/类名合法字符: 字母、数字、下划线、点
        // 纯白名单校验, 拒绝一切 shell 元字符 (`;|&$(){}[]<>'"\ \n` 等), 用于防命令注入
        private val COMPONENT_NAME_REGEX = Regex("^[a-zA-Z0-9_.]+$")
    }

    /**
     * 校验包名/组件名是否只含合法字符, 防止远程传入的字符串进入 shell 造成命令注入。
     * 包名不能为空字符串片段, 校验失败返回描述性错误。
     */
    private fun validateComponentName(value: String, field: String): String? {
        if (value.isEmpty()) return "缺少 $field 参数"
        if (!COMPONENT_NAME_REGEX.matches(value)) {
            Log.w(TAG, "非法 $field: $value 含 shell 特殊字符, 已拒绝")
            return "$field 包含非法字符, 已拒绝执行"
        }
        return null
    }

    /**
     * 执行设备指令, 返回结果 JsonObject
     *
     * @return JsonObject: {status: "success|error", result: {...}, error: "..."}
     */
    suspend fun execute(command: String, args: JsonObject): JsonObject = try {
        Log.i(TAG, "执行设备指令: $command, args=$args")
        val result = when (command) {
            "force_stop_app" -> forceStopApp(args)
            "list_installed_apps" -> listInstalledApps(args)
            "start_app" -> startApp(args)
            "get_app_usage_time" -> getAppUsageTime(args)
            "capture_screen" -> captureScreen(args)
            "get_device_location" -> getDeviceLocation(args)
            "list_paired_bluetooth_devices" -> listPairedBluetoothDevices(args)
            "scan_bluetooth_devices" -> scanBluetoothDevices(args)
            "pair_bluetooth_device" -> pairBluetoothDevice(args)
            "unpair_bluetooth_device" -> unpairBluetoothDevice(args)
            "a11y_click_at" -> a11yClickAt(args)
            "a11y_swipe" -> a11ySwipe(args)
            "a11y_go_back" -> a11yGoBack(args)
            "a11y_go_home" -> a11yGoHome(args)
            "a11y_find_and_click" -> a11yFindAndClick(args)
            "a11y_dump_visible_text" -> a11yDumpVisibleText(args)
            "set_wallpaper" -> setWallpaper(args)
            else -> errorResult("未知指令: $command")
        }
        result
    } catch (e: Exception) {
        Log.e(TAG, "执行设备指令失败: $command", e)
        errorResult(e.message ?: "未知错误")
    }

    // ── 强制停止应用 ──────────────────────────────────────

    /**
     * 公开封装: 直接按包名强制停止应用 (供 UsageLimitMonitor 等本地监控调用,
     * 无需走 device_command JSON 通道)。返回是否成功强停。
     */
    suspend fun forceStopApp(
        packageName: String,
        acceptBackgroundFallback: Boolean = false
    ): Boolean {
        if (packageName.isBlank()) return false
        val result = forceStopApp(buildJsonObject { put("package_name", packageName) })
        if (result["status"]?.toString()?.trim('"') != "success") return false
        val resultObject = result["result"] as? JsonObject ?: return false
        val channel = resultObject["channel"]?.toString()?.trim('"')
        // killBackgroundProcesses 不能关闭仍在前台的应用，不能再向周期监控谎报“强退成功”。
        // 无障碍执行器会先返回桌面，再显式允许把这个后台降级视为成功。
        return channel == "shizuku" ||
            (acceptBackgroundFallback && channel == "kill_background")
    }

    private suspend fun forceStopApp(args: JsonObject): JsonObject = withContext(Dispatchers.IO) {
        val packageName = args["package_name"]?.toString()?.trim('"') ?: ""
        validateComponentName(packageName, "package_name")?.let {
            return@withContext errorResult(it)
        }

        // 优先用 Shizuku 执行 am force-stop (真正强停, 能停前台)
        if (ShizukuShellExecutor.isAvailable()) {
            val result = ShizukuShellExecutor.execute("am force-stop $packageName")
            if (result.success) {
                return@withContext successResult(
                    buildJsonObject {
                        put("package_name", packageName)
                        put("channel", "shizuku")
                        put("summary", "已通过 Shizuku (am force-stop) 强制停止 $packageName")
                    }
                )
            }
            Log.w(TAG, "Shizuku force-stop 失败, 降级 killBackgroundProcesses: ${result.stderr}")
        }

        // 降级: killBackgroundProcesses (停不了前台, 应用可能立即重启)
        if (!hasPermission(Manifest.permission.KILL_BACKGROUND_PROCESSES)) {
            return@withContext errorResult("Shizuku 不可用且缺少 KILL_BACKGROUND_PROCESSES 权限")
        }
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        am.killBackgroundProcesses(packageName)
        successResult(
            buildJsonObject {
                put("package_name", packageName)
                put("channel", "kill_background")
                put("summary", "已通过 killBackgroundProcesses 停止 $packageName (降级模式, 前台应用可能未被停止)")
            }
        )
    }

    // ── 列出已安装应用 ────────────────────────────────────

    private suspend fun listInstalledApps(args: JsonObject): JsonObject =
        withContext(Dispatchers.IO) {
            val includeSystem = args["include_system_apps"]?.toString()?.toBooleanStrictOrNull() ?: false
            val limit = args["limit"]?.toString()?.toIntOrNull() ?: 100
            val safeLimit = maxOf(1, minOf(limit, 500))

            val pm = context.packageManager
            val flags = PackageManager.GET_META_DATA
            val allApps = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                pm.getInstalledApplications(PackageManager.ApplicationInfoFlags.of(flags.toLong()))
            } else {
                @Suppress("DEPRECATION")
                pm.getInstalledApplications(flags)
            }

            val filtered = allApps
                .filter { includeSystem || (it.flags and ApplicationInfo.FLAG_SYSTEM) == 0 }
                .sortedBy { pm.getApplicationLabel(it).toString().lowercase() }
                .take(safeLimit)
                .map {
                    buildJsonObject {
                        put("name", pm.getApplicationLabel(it).toString())
                        put("package_name", it.packageName)
                        put("is_system", (it.flags and ApplicationInfo.FLAG_SYSTEM) != 0)
                    }
                }

            successResult(
                buildJsonObject {
                    put("apps", kotlinx.serialization.json.JsonArray(filtered))
                    put("total", filtered.size)
                }
            )
        }

    // ── 启动应用 ──────────────────────────────────────────

    private suspend fun startApp(args: JsonObject): JsonObject = withContext(Dispatchers.IO) {
        val packageName = args["package_name"]?.toString()?.trim('"') ?: ""
        validateComponentName(packageName, "package_name")?.let {
            return@withContext errorResult(it)
        }
        val activity = args["activity"]?.toString()?.trim('"')
        if (activity != null) {
            validateComponentName(activity, "activity")?.let {
                return@withContext errorResult(it)
            }
        }

        // 优先用 Shizuku 执行 am start (可以指定 activity)
        if (activity != null && ShizukuShellExecutor.isAvailable()) {
            val result = ShizukuShellExecutor.execute("am start -n $packageName/$activity")
            if (result.success) {
                return@withContext successResult(
                    buildJsonObject {
                        put("package_name", packageName)
                        put("activity", activity)
                    }
                )
            }
        }

        // 普通方式: getLaunchIntentForPackage
        val launchIntent = context.packageManager.getLaunchIntentForPackage(packageName)
        if (launchIntent != null) {
            launchIntent.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(launchIntent)
            successResult(
                buildJsonObject {
                    put("package_name", packageName)
                    put("activity", activity ?: "default")
                }
            )
        } else {
            errorResult("未找到应用 $packageName 的启动器")
        }
    }

    // ── 查询应用使用时长 ──────────────────────────────────

    private suspend fun getAppUsageTime(args: JsonObject): JsonObject = withContext(Dispatchers.IO) {
        if (!hasUsageStatsAccess()) {
            return@withContext errorResult("未授权使用情况访问 (Usage Access), 请到系统设置 > 安全 > 使用情况访问 开启 ${context.packageName}")
        }

        val packageName = args["package_name"]?.toString()?.trim('"')
        val sinceHours = args["since_hours"]?.toString()?.toIntOrNull() ?: 24
        val limit = args["limit"]?.toString()?.toIntOrNull() ?: 10
        val includeSystem = args["include_system_apps"]?.toString()?.toBooleanStrictOrNull() ?: false
        val safeHours = maxOf(1, minOf(sinceHours, 24 * 30))
        val safeLimit = maxOf(1, minOf(limit, 50))

        val endTime = System.currentTimeMillis()
        val startTime = endTime - safeHours * 60L * 60L * 1000L

        val usageStatsManager = context.getSystemService(Context.USAGE_STATS_SERVICE)
            as android.app.usage.UsageStatsManager
        val rawStats = usageStatsManager.queryUsageStats(
            android.app.usage.UsageStatsManager.INTERVAL_DAILY,
            startTime,
            endTime
        ) ?: emptyList()

        // 按 packageName 聚合
        val aggregated = rawStats.groupBy { it.packageName }.map { (pkg, stats) ->
            val totalMs = stats.sumOf { it.totalTimeInForeground }
            val lastUsed = stats.maxOfOrNull { it.lastTimeUsed } ?: 0L
            Triple(pkg, totalMs, lastUsed)
        }.filter { (_, totalMs, _) -> totalMs > 0 }
            .filter { (pkg, _, _) ->
                if (includeSystem) true else !isSystemApp(pkg)
            }
            .filter { (pkg, _, _) ->
                packageName.isNullOrEmpty() || pkg == packageName
            }
            .sortedByDescending { (_, totalMs, _) -> totalMs }
            .take(if (packageName.isNullOrEmpty()) safeLimit else 1)

        val entries = aggregated.map { (pkg, totalMs, lastUsed) ->
            buildJsonObject {
                put("package_name", pkg)
                put("app_name", getAppName(pkg))
                put("total_foreground_time_ms", totalMs)
                put("last_time_used", lastUsed)
                put("is_system_app", isSystemApp(pkg))
            }
        }

        successResult(
            buildJsonObject {
                put("entries", kotlinx.serialization.json.JsonArray(entries))
                put("since_hours", safeHours)
                put("requested_package_name", packageName ?: "")
                put("includes_system_apps", includeSystem)
            }
        )
    }

    // ── 截图手机屏幕 ──────────────────────────────────────

    private suspend fun captureScreen(args: JsonObject): JsonObject = withContext(Dispatchers.IO) {
        // Shizuku 可用: 用 screencap 命令截图
        if (ShizukuShellExecutor.isAvailable()) {
            val tmpPath = "${context.cacheDir.absolutePath}/aveline_screenshot.png"
            val result = ShizukuShellExecutor.execute("screencap -p $tmpPath")
            if (result.success) {
                val file = java.io.File(tmpPath)
                if (file.exists()) {
                    val bytes = file.readBytes()
                    file.delete()
                    val base64 = Base64.encodeToString(bytes, Base64.NO_WRAP)
                    return@withContext successResult(
                        buildJsonObject {
                            put("image_base64", base64)
                            put("format", "png")
                        }
                    )
                }
            }
            Log.w(TAG, "Shizuku screencap 失败: ${result.stderr}")
        }

        // Shizuku 不可用: 尝试用 ImageReader + Display (前台服务无 Activity, 限制较大)
        // MVP 阶段直接返回错误, 后续可加 MediaProjection 降级
        errorResult("截图失败: 需要 Shizuku 执行 screencap (MediaProjection 降级待实现)")
    }

    // ── 获取设备地理位置 (原生 LocationManager) ───────────

    /**
     * 获取手机地理位置, 使用 Android 原生 LocationManager, 不依赖 Google Play 服务。
     *
     * 策略:
     * 1. 先取所有 provider 的 getLastKnownLocation, 选精度最高的快返
     * 2. high_accuracy=True 且 lastKnown 太旧时, 注册一次性 listener 等待新定位
     * 3. Geocoder 反地理 (在 IO 线程, 失败不阻断)
     *
     * 与 PhoneActionExecutor.GetLocation 的区别:
     * - 用 LocationManager 而非 FusedLocationProviderClient
     * - 不依赖 Google Play 服务 (GMS), 兼容华为/小米国行等无 GMS 设备
     * - 走 device_command 通道, 返回复杂结构 (含 provider/address)
     */
    @SuppressLint("MissingPermission")
    private suspend fun getDeviceLocation(args: JsonObject): JsonObject = withContext(Dispatchers.IO) {
        val highAccuracy = args["high_accuracy"]?.toString()?.toBooleanStrictOrNull() ?: true
        val timeoutSec = args["timeout_seconds"]?.toString()?.toIntOrNull() ?: 15
        val safeTimeoutSec = maxOf(5, minOf(timeoutSec, 60))

        // 权限检查: 至少要有 ACCESS_COARSE_LOCATION
        val hasFine = hasPermission(Manifest.permission.ACCESS_FINE_LOCATION)
        val hasCoarse = hasPermission(Manifest.permission.ACCESS_COARSE_LOCATION)
        if (!hasFine && !hasCoarse) {
            return@withContext errorResult("未授予位置权限, 请到系统设置开启 ${context.packageName} 的位置权限")
        }

        val lm = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager

        // 列出可用 provider ( GPS / NETWORK / PASSIVE )
        val allProviders = lm.allProviders
        val gpsEnabled = allProviders.contains(LocationManager.GPS_PROVIDER) &&
            lm.isProviderEnabled(LocationManager.GPS_PROVIDER)
        val networkEnabled = allProviders.contains(LocationManager.NETWORK_PROVIDER) &&
            lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
        val passiveEnabled = allProviders.contains(LocationManager.PASSIVE_PROVIDER) &&
            lm.isProviderEnabled(LocationManager.PASSIVE_PROVIDER)

        if (!gpsEnabled && !networkEnabled && !passiveEnabled) {
            return@withContext errorResult("所有位置 provider 都未开启, 请到系统设置开启位置服务")
        }

        // Step 1: 取所有可用 provider 的 lastKnownLocation, 选精度最高的
        val candidates = mutableListOf<Location>()
        if (hasFine && gpsEnabled) {
            lm.getLastKnownLocation(LocationManager.GPS_PROVIDER)?.let { candidates.add(it) }
        }
        if (networkEnabled) {
            // NETWORK_PROVIDER 只需 coarse 权限
            lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)?.let { candidates.add(it) }
        }
        if (passiveEnabled) {
            // PASSIVE_PROVIDER 读取其他应用触发的位置更新
            lm.getLastKnownLocation(LocationManager.PASSIVE_PROVIDER)?.let { candidates.add(it) }
        }

        var best: Location? = candidates.minByOrNull { it.accuracy }
        val nowMs = System.currentTimeMillis()

        // Step 2: high_accuracy 且 best 太旧 (>5min) → 注册一次性 listener 等新定位
        val shouldRefresh = highAccuracy && best != null &&
            (nowMs - best.time > 5 * 60 * 1000L)
        val noCache = best == null

        if ((shouldRefresh || noCache) && (gpsEnabled || networkEnabled)) {
            val fresh = withTimeoutOrNull(safeTimeoutSec * 1000L) {
                requestSingleLocationUpdate(lm, highAccuracy && hasFine && gpsEnabled)
            }
            if (fresh != null) {
                // 新位置优先 (即使精度稍差, 也是实时的)
                best = if (best == null) fresh else {
                    // 取 fresher 的, 但如果 fresh.accuracy 比 best 差很多 (>100m) 且 best 不算太旧, 保留 best
                    if (fresh.accuracy < best!!.accuracy + 50 || best!!.time < nowMs - 10 * 60 * 1000L) {
                        fresh
                    } else {
                        best
                    }
                }
            }
        }

        if (best == null) {
            return@withContext errorResult("无法获取位置: 所有 provider 均无 lastKnownLocation 且 ${safeTimeoutSec}s 内未收到新定位")
        }

        val loc = best!!
        val address = reverseGeocode(loc.latitude, loc.longitude)

        successResult(
            buildJsonObject {
                put("latitude", loc.latitude)
                put("longitude", loc.longitude)
                put("accuracy_meters", loc.accuracy)
                put("altitude", if (loc.hasAltitude()) loc.altitude else 0.0)
                put("speed_mps", if (loc.hasSpeed()) loc.speed.toDouble() else 0.0)
                put("bearing_deg", if (loc.hasBearing()) loc.bearing.toDouble() else 0.0)
                put("provider", loc.provider ?: "unknown")
                put("timestamp_ms", loc.time)
                if (address != null) put("address", address)
                put("is_from_cache", nowMs - loc.time > 60 * 1000L)
            }
        )
    }

    /**
     * 注册一次性 LocationListener, 拿到第一个位置后立即取消。
     * 优先用 GPS_PROVIDER (高精度), 不可用或不需要高精度时用 NETWORK_PROVIDER。
     * 失败时回退到 getLastKnownLocation, 若仍无则返回 null。
     */
    @SuppressLint("MissingPermission")
    private suspend fun requestSingleLocationUpdate(
        lm: LocationManager,
        preferGps: Boolean
    ): Location? = suspendCancellableCoroutine { cont ->
        val provider = if (preferGps && lm.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
            LocationManager.GPS_PROVIDER
        } else {
            LocationManager.NETWORK_PROVIDER
        }

        val listener = object : LocationListener {
            override fun onLocationChanged(location: Location) {
                lm.removeUpdates(this)
                if (cont.isActive) cont.resume(location)
            }
            override fun onProviderDisabled(provider: String) {}
            override fun onProviderEnabled(provider: String) {}
            @Suppress("DEPRECATION")
            override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
        }

        // 拿到结果后立即取消注册, 防止泄漏
        cont.invokeOnCancellation {
            try {
                lm.removeUpdates(listener)
            } catch (e: SecurityException) {
                Log.w(TAG, "removeUpdates 失败: ${e.message}")
            }
        }

        try {
            // minTimeMs=0, minDistanceM=0 → 立即返回最新位置
            lm.requestLocationUpdates(provider, 0L, 0f, listener)
        } catch (e: SecurityException) {
            if (cont.isActive) cont.resume(getLastKnownFallback(lm, preferGps))
        } catch (e: IllegalArgumentException) {
            // provider 不存在
            if (cont.isActive) cont.resume(getLastKnownFallback(lm, preferGps))
        }
    }

    @SuppressLint("MissingPermission")
    private fun getLastKnownFallback(lm: LocationManager, preferGps: Boolean): Location? {
        return if (preferGps) {
            lm.getLastKnownLocation(LocationManager.GPS_PROVIDER)
                ?: lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)
                ?: lm.getLastKnownLocation(LocationManager.PASSIVE_PROVIDER)
        } else {
            lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)
                ?: lm.getLastKnownLocation(LocationManager.GPS_PROVIDER)
                ?: lm.getLastKnownLocation(LocationManager.PASSIVE_PROVIDER)
        }
    }

    /**
     * 反地理编码: 经纬度 → 可读地址。在 IO 线程同步调用 (Geocoder 是阻塞的)。
     * 失败返回 null, 不影响主流程。
     *
     * 注: Android 13+ 推荐 Geocoder.getFromLocation(lat, lon, maxResults, GeocodeListener) 异步版本,
     * 但同步版本仍可用 (deprecated)。为保证兼容旧设备, 这里继续用同步版本。
     */
    private suspend fun reverseGeocode(lat: Double, lon: Double): String? =
        withContext(Dispatchers.IO) {
            try {
                val geocoder = Geocoder(context, Locale.getDefault())
                // 同步 API 在新旧版本都返回 List<Address>?, TIRAMISU+ 标记为 deprecated 但仍可用
                @Suppress("DEPRECATION")
                val addresses = geocoder.getFromLocation(lat, lon, 1)
                addresses?.firstOrNull()?.let { addr ->
                    val parts = listOfNotNull(
                        addr.adminArea,      // 省
                        addr.locality,       // 市
                        addr.subLocality,    // 区
                        addr.thoroughfare,   // 路
                        addr.subThoroughfare // 号
                    ).filter { it.isNotBlank() }
                    if (parts.isNotEmpty()) parts.joinToString("") else null
                }
            } catch (e: Exception) {
                Log.w(TAG, "反地理编码失败: ${e.message}")
                null
            }
        }

    // ── 蓝牙设备管理 ─────────────────────────────────────

    /**
     * 列出已配对蓝牙设备及连接状态。
     *
     * 连接状态查询用 BluetoothManager.getConnectedDevices(profile) 拿到 A2DP (音频流) + HEADSET (耳机) profile
     * 的已连接设备列表, 再用 MAC 比对判断每个 bonded 设备是否已连接。
     */
    @SuppressLint("MissingPermission")
    private suspend fun listPairedBluetoothDevices(args: JsonObject): JsonObject =
        withContext(Dispatchers.IO) {
            val includeConnectionState = args["include_connection_state"]
                ?.toString()?.toBooleanStrictOrNull() ?: true

            val bm = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
            val adapter = bm?.adapter
            if (adapter == null) {
                return@withContext errorResult("设备不支持蓝牙")
            }
            if (!hasBluetoothConnectPermission()) {
                return@withContext errorResult("未授予 BLUETOOTH_CONNECT 权限")
            }
            if (!adapter.isEnabled) {
                return@withContext errorResult("蓝牙未开启, 请先打开蓝牙")
            }

            // 已连接设备集合 (用于查询 connection_state)
            val connectedMacs = mutableSetOf<String>()
            if (includeConnectionState) {
                try {
                    for (profile in intArrayOf(BluetoothProfile.A2DP, BluetoothProfile.HEADSET)) {
                        val connected = bm.getConnectedDevices(profile)
                        connected.forEach { connectedMacs.add(it.address) }
                    }
                } catch (e: SecurityException) {
                    Log.w(TAG, "查询连接设备失败: ${e.message}")
                }
            }

            val bonded = adapter.bondedDevices ?: emptySet()
            val devices = bonded.map { device ->
                val state = if (includeConnectionState) {
                    if (connectedMacs.contains(device.address)) "connected" else "disconnected"
                } else "unknown"
                buildJsonObject {
                    put("name", device.name ?: "未知名称")
                    put("address", device.address)
                    put("bond_state", bondStateName(device.bondState))
                    if (includeConnectionState) put("connection_state", state)
                    put("major_class", bluetoothMajorClassName(device.bluetoothClass?.majorDeviceClass ?: 0))
                    put("type", deviceTypeName(device.type))
                }
            }

            successResult(
                buildJsonObject {
                    put("devices", kotlinx.serialization.json.JsonArray(devices))
                    put("total", devices.size)
                    put("bluetooth_enabled", true)
                }
            )
        }

    /**
     * 扫描附近蓝牙设备。
     *
     * 启动 BluetoothAdapter.startDiscovery, 注册 ACTION_FOUND receiver 收集设备,
     * 等待 duration 秒后取消 discovery (它本身最多跑 12s 左右)。
     *
     * 注: discovery 期间已连接的蓝牙设备可能短暂断开。
     */
    @SuppressLint("MissingPermission")
    private suspend fun scanBluetoothDevices(args: JsonObject): JsonObject =
        withContext(Dispatchers.IO) {
            val durationSec = args["duration_seconds"]?.toString()?.toIntOrNull() ?: 10
            val includePaired = args["include_paired"]?.toString()?.toBooleanStrictOrNull() ?: false
            val safeDuration = maxOf(3, minOf(durationSec, 30))

            val bm = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
            val adapter = bm?.adapter
            if (adapter == null) {
                return@withContext errorResult("设备不支持蓝牙")
            }
            if (!hasBluetoothConnectPermission()) {
                return@withContext errorResult("未授予 BLUETOOTH_CONNECT 权限 (Android 12+)")
            }
            if (!adapter.isEnabled) {
                return@withContext errorResult("蓝牙未开启")
            }

            // 已配对的 MAC 集合, 用于标记 already_paired
            val pairedMacs = (adapter.bondedDevices ?: emptySet()).map { it.address }.toHashSet()

            val found = mutableSetOf<BluetoothDevice>()
            val foundLock = Any()

            val receiver = object : BroadcastReceiver() {
                override fun onReceive(ctx: Context?, intent: Intent?) {
                    if (intent?.action == BluetoothDevice.ACTION_FOUND) {
                        val device = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                            intent.getParcelableExtra(
                                BluetoothDevice.EXTRA_DEVICE,
                                BluetoothDevice::class.java
                            )
                        } else {
                            @Suppress("DEPRECATION")
                            intent.getParcelableExtra<BluetoothDevice>(BluetoothDevice.EXTRA_DEVICE)
                        }
                        val rssi = intent.getShortExtra(BluetoothDevice.EXTRA_RSSI, Short.MIN_VALUE).toInt()
                        if (device != null) {
                            synchronized(foundLock) {
                                // 把 RSSI 临时存到 map 里, 后面取用
                                deviceRssiMap[device.address] = rssi
                                found.add(device)
                            }
                        }
                    } else if (intent?.action == BluetoothAdapter.ACTION_DISCOVERY_FINISHED) {
                        // discovery 主动结束
                    }
                }
            }

            // 注册 receiver (要带 RECEIVER_NOT_EXPORTED, 因为蓝牙广播是系统发的)
            val filter = IntentFilter().apply {
                addAction(BluetoothDevice.ACTION_FOUND)
                addAction(BluetoothAdapter.ACTION_DISCOVERY_FINISHED)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                context.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
            } else {
                @Suppress("UnspecifiedRegisterReceiverFlag")
                context.registerReceiver(receiver, filter)
            }

            try {
                // 取消正在进行中的 discovery, 再启动新的
                adapter.cancelDiscovery()
                // 等一下确保取消生效
                delay(200)
                if (!adapter.startDiscovery()) {
                    return@withContext errorResult("启动蓝牙扫描失败 (startDiscovery 返回 false)")
                }

                // 等待 duration 秒
                delay(safeDuration * 1000L)

                // 主动取消 discovery (它会持续到自动结束, 但我们截断)
                adapter.cancelDiscovery()
                // 等收尾
                delay(200)
            } finally {
                try {
                    context.unregisterReceiver(receiver)
                } catch (e: IllegalArgumentException) {
                    Log.w(TAG, "unregisterReceiver 失败: ${e.message}")
                }
            }

            val devices = synchronized(foundLock) {
                found
                    .filter { includePaired || !pairedMacs.contains(it.address) }
                    .map { device ->
                        buildJsonObject {
                            put("name", device.name ?: "未知名称")
                            put("address", device.address)
                            val rssi = deviceRssiMap[device.address]
                            if (rssi != null) put("rssi", rssi)
                            put("already_paired", pairedMacs.contains(device.address))
                            put("type", deviceTypeName(device.type))
                        }
                    }
            }

            // 清理临时 rssi map
            deviceRssiMap.clear()

            successResult(
                buildJsonObject {
                    put("devices", kotlinx.serialization.json.JsonArray(devices))
                    put("total", devices.size)
                    put("duration_seconds", safeDuration)
                }
            )
        }

    /**
     * 配对蓝牙设备 (反射调用 BluetoothDevice.createBond)。
     *
     * createBond 是 hide API (public SDK 标记 @hide), 但可通过反射调用。
     * 系统会弹出配对确认框 (如果设备需要配对码), 配对成功后通常自动连接。
     */
    @SuppressLint("MissingPermission")
    private suspend fun pairBluetoothDevice(args: JsonObject): JsonObject =
        withContext(Dispatchers.IO) {
            val address = args["address"]?.toString()?.trim('"') ?: ""
            if (address.isEmpty()) {
                return@withContext errorResult("缺少 address 参数")
            }

            val bm = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
            val adapter = bm?.adapter
            if (adapter == null || !adapter.isEnabled) {
                return@withContext errorResult("蓝牙不可用或未开启")
            }
            if (!hasBluetoothConnectPermission()) {
                return@withContext errorResult("未授予 BLUETOOTH_CONNECT 权限")
            }

            val device = try {
                adapter.getRemoteDevice(address)
            } catch (e: Exception) {
                return@withContext errorResult("无效的 MAC 地址: $address")
            }

            // 已配对就直接返回
            if (device.bondState == BluetoothDevice.BOND_BONDED) {
                return@withContext successResult(
                    buildJsonObject {
                        put("address", address)
                        put("name", device.name ?: "未知名称")
                        put("bond_state", "bonded")
                    }
                )
            }

            // 反射调用 createBond()
            val ok = try {
                val method = BluetoothDevice::class.java.getMethod("createBond")
                method.invoke(device) as? Boolean ?: false
            } catch (e: NoSuchMethodException) {
                // Android 19+ 有 createBond() public 方法, 直接调用
                try {
                    device.createBond()
                } catch (e2: SecurityException) {
                    false
                }
            } catch (e: Exception) {
                Log.w(TAG, "createBond 反射失败: ${e.message}")
                false
            }

            if (!ok) {
                return@withContext errorResult("调用 createBond 失败 (可能设备未发现/不在范围内)")
            }

            // createBond 是异步的, 等几秒再检查 bondState
            delay(2000)
            val newState = device.bondState
            successResult(
                buildJsonObject {
                    put("address", address)
                    put("name", device.name ?: "未知名称")
                    put("bond_state", bondStateName(newState))
                }
            )
        }

    /**
     * 取消配对 (反射调用 BluetoothDevice.removeBond)。
     *
     * removeBond 是 hide API, 必须用反射调用。取消配对会自动断开连接。
     */
    @SuppressLint("MissingPermission")
    private suspend fun unpairBluetoothDevice(args: JsonObject): JsonObject =
        withContext(Dispatchers.IO) {
            val address = args["address"]?.toString()?.trim('"') ?: ""
            if (address.isEmpty()) {
                return@withContext errorResult("缺少 address 参数")
            }

            val bm = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
            val adapter = bm?.adapter
            if (adapter == null || !adapter.isEnabled) {
                return@withContext errorResult("蓝牙不可用或未开启")
            }
            if (!hasBluetoothConnectPermission()) {
                return@withContext errorResult("未授予 BLUETOOTH_CONNECT 权限")
            }

            val device = try {
                adapter.getRemoteDevice(address)
            } catch (e: Exception) {
                return@withContext errorResult("无效的 MAC 地址: $address")
            }

            if (device.bondState != BluetoothDevice.BOND_BONDED) {
                return@withContext successResult(
                    buildJsonObject {
                        put("address", address)
                        put("removed", false)
                        put("reason", "未配对, 无需取消")
                    }
                )
            }

            // 反射调用 removeBond()
            val ok = try {
                val method = BluetoothDevice::class.java.getMethod("removeBond")
                method.invoke(device) as? Boolean ?: false
            } catch (e: Exception) {
                Log.w(TAG, "removeBond 反射失败: ${e.message}")
                false
            }

            if (!ok) {
                return@withContext errorResult("调用 removeBond 失败")
            }

            // removeBond 异步, 等几秒检查
            delay(1500)
            val removed = device.bondState == BluetoothDevice.BOND_NONE
            successResult(
                buildJsonObject {
                    put("address", address)
                    put("removed", removed)
                }
            )
        }

    // 蓝牙扫描用的临时 RSSI 缓存 (action found 时存, 最后渲染时取)
    private val deviceRssiMap = mutableMapOf<String, Int>()

    private fun hasBluetoothConnectPermission(): Boolean {
        // Android 12+ 需要 BLUETOOTH_CONNECT 运行时权限
        // 低版本蓝牙权限是普通权限, 自动授予
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            hasPermission(Manifest.permission.BLUETOOTH_CONNECT)
        } else {
            true
        }
    }

    private fun bondStateName(state: Int): String = when (state) {
        BluetoothDevice.BOND_NONE -> "none"
        BluetoothDevice.BOND_BONDING -> "bonding"
        BluetoothDevice.BOND_BONDED -> "bonded"
        else -> "unknown"
    }

    private fun deviceTypeName(type: Int): String = when (type) {
        BluetoothDevice.DEVICE_TYPE_CLASSIC -> "classic"
        BluetoothDevice.DEVICE_TYPE_LE -> "le"
        BluetoothDevice.DEVICE_TYPE_DUAL -> "dual"
        else -> "unknown"
    }

    private fun bluetoothMajorClassName(major: Int): String = when (major) {
        0x0100 -> "computer"
        0x0400 -> "audio_video" // 耳机/音箱/电视
        0x0500 -> "peripheral"   // 鼠标/键盘/手柄
        0x0600 -> "imaging"      // 相机/打印机
        0x0700 -> "wearable"     // 手表/手环/眼镜
        0x0800 -> "toy"
        0x1F00 -> "health"       // 血压计/体温计
        0x0000 -> "misc"
        else -> "unknown(0x${major.toString(16)})"
    }

    // ── 无障碍 UI 自动化 ───────────────────────────────

    /**
     * 无障碍指令的统一前置检查: 服务必须已连接。
     * 调用方拿到 instance 或返回 errorResult。
     */
    private fun requireA11y(): AvelineAccessibilityService? {
        val svc = AvelineAccessibilityService.instance
        if (svc == null) {
            Log.w(TAG, "无障碍服务未连接, 请到系统设置 > 无障碍 开启 Aveline")
        }
        return svc
    }

    /** 按坐标点击屏幕 */
    private suspend fun a11yClickAt(args: JsonObject): JsonObject = withContext(Dispatchers.IO) {
        val svc = requireA11y() ?: return@withContext errorResult(
            "无障碍服务未开启, 请到系统设置 > 无障碍 中开启 Aveline 服务"
        )
        val x = args["x"]?.toString()?.toFloatOrNull()
        val y = args["y"]?.toString()?.toFloatOrNull()
        if (x == null || y == null) {
            return@withContext errorResult("缺少 x/y 参数 (坐标)")
        }

        val ok = svc.click(x, y)
        successResult(
            buildJsonObject {
                put("x", x.toDouble())
                put("y", y.toDouble())
                put("clicked", ok)
            }
        )
    }

    /** 滑动屏幕 */
    private suspend fun a11ySwipe(args: JsonObject): JsonObject = withContext(Dispatchers.IO) {
        val svc = requireA11y() ?: return@withContext errorResult(
            "无障碍服务未开启, 请到系统设置 > 无障碍 中开启 Aveline 服务"
        )
        val startX = args["start_x"]?.toString()?.toFloatOrNull()
        val startY = args["start_y"]?.toString()?.toFloatOrNull()
        val endX = args["end_x"]?.toString()?.toFloatOrNull()
        val endY = args["end_y"]?.toString()?.toFloatOrNull()
        val durationMs = args["duration_ms"]?.toString()?.toLongOrNull() ?: 300L
        if (startX == null || startY == null || endX == null || endY == null) {
            return@withContext errorResult("缺少 start_x/start_y/end_x/end_y 参数")
        }
        val safeDuration = maxOf(50L, minOf(durationMs, 3000L))

        val ok = svc.swipe(startX, startY, endX, endY, safeDuration)
        successResult(
            buildJsonObject {
                put("start_x", startX.toDouble())
                put("start_y", startY.toDouble())
                put("end_x", endX.toDouble())
                put("end_y", endY.toDouble())
                put("duration_ms", safeDuration)
                put("swiped", ok)
            }
        )
    }

    /** 模拟返回键 */
    private suspend fun a11yGoBack(args: JsonObject): JsonObject = withContext(Dispatchers.IO) {
        val svc = requireA11y() ?: return@withContext errorResult(
            "无障碍服务未开启, 请到系统设置 > 无障碍 中开启 Aveline 服务"
        )
        val ok = svc.goBack()
        successResult(buildJsonObject { put("performed", ok) })
    }

    /** 模拟桌面键 */
    private suspend fun a11yGoHome(args: JsonObject): JsonObject = withContext(Dispatchers.IO) {
        val svc = requireA11y() ?: return@withContext errorResult(
            "无障碍服务未开启, 请到系统设置 > 无障碍 中开启 Aveline 服务"
        )
        val ok = svc.goHome()
        successResult(buildJsonObject { put("performed", ok) })
    }

    /**
     * 找文字并点击。
     *
     * args:
     * - text: 要查找的精确文字 (如 "蓝牙"、"连接")
     * - click_parent: 节点本身不可点击时是否点击父节点 (默认 true)
     */
    private suspend fun a11yFindAndClick(args: JsonObject): JsonObject = withContext(Dispatchers.IO) {
        val svc = requireA11y() ?: return@withContext errorResult(
            "无障碍服务未开启, 请到系统设置 > 无障碍 中开启 Aveline 服务"
        )
        val text = args["text"]?.toString()?.trim('"') ?: ""
        val clickParent = args["click_parent"]?.toString()?.toBooleanStrictOrNull() ?: true
        if (text.isEmpty()) {
            return@withContext errorResult("缺少 text 参数 (要查找的文字)")
        }

        val ok = svc.findAndClickByText(text, clickParent)
        successResult(
            buildJsonObject {
                put("text", text)
                put("found_and_clicked", ok)
            }
        )
    }

    /**
     * Dump 当前屏幕可见文本树 (供 AI 看屏幕内容)。
     *
     * 与截图+视觉模型互补: 截图直观但慢且贵, dump 快且准确 (有文字 ID 等)。
     */
    private suspend fun a11yDumpVisibleText(args: JsonObject): JsonObject = withContext(Dispatchers.IO) {
        val svc = requireA11y() ?: return@withContext errorResult(
            "无障碍服务未开启, 请到系统设置 > 无障碍 中开启 Aveline 服务"
        )
        val maxLen = args["max_length"]?.toString()?.toIntOrNull() ?: 8000
        val safeMaxLen = maxOf(500, minOf(maxLen, 30000))

        val raw = svc.dumpVisibleText()
        val truncated = if (raw.length > safeMaxLen) {
            raw.substring(0, safeMaxLen) + "\n... (已截断)"
        } else raw

        successResult(
            buildJsonObject {
                put("text", truncated)
                put("length", truncated.length)
                put("truncated", raw.length > safeMaxLen)
            }
        )
    }

    // ── 辅助方法 ──────────────────────────────────────────

    private fun hasPermission(permission: String): Boolean {
        return context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
    }

    private fun hasUsageStatsAccess(): Boolean {
        val appOpsManager = context.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val mode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            appOpsManager.unsafeCheckOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                Process.myUid(),
                context.packageName
            )
        } else {
            @Suppress("DEPRECATION")
            appOpsManager.checkOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                Process.myUid(),
                context.packageName
            )
        }
        return mode == AppOpsManager.MODE_ALLOWED
    }

    private fun isSystemApp(packageName: String): Boolean {
        return try {
            val info = context.packageManager.getApplicationInfo(packageName, 0)
            (info.flags and ApplicationInfo.FLAG_SYSTEM) != 0
        } catch (e: PackageManager.NameNotFoundException) {
            false
        }
    }

    private fun getAppName(packageName: String): String {
        return try {
            val info = context.packageManager.getApplicationInfo(packageName, 0)
            context.packageManager.getApplicationLabel(info).toString()
        } catch (e: PackageManager.NameNotFoundException) {
            packageName.substringAfterLast(".")
        }
    }

    // ── 更换壁纸 ──────────────────────────────────────────

    @SuppressLint("ServiceCast")
    private suspend fun setWallpaper(args: JsonObject): JsonObject = withContext(Dispatchers.IO) {
        val b64 = args["image_base64"]?.toString()?.trim('"') ?: ""
        if (b64.isEmpty()) {
            return@withContext errorResult("缺少 image_base64 参数")
        }

        try {
            val data = Base64.decode(b64, Base64.DEFAULT)
            val bitmap = BitmapFactory.decodeByteArray(data, 0, data.size)
                ?: return@withContext errorResult("base64 解码为 Bitmap 失败")

            val wm = WallpaperManager.getInstance(context)
            wm.setBitmap(bitmap)
            Log.i(TAG, "壁纸已更换: ${bitmap.width}x${bitmap.height}")

            successResult(
                buildJsonObject {
                    put("summary", "壁纸已更换")
                    put("width", bitmap.width)
                    put("height", bitmap.height)
                }
            )
        } catch (e: SecurityException) {
            Log.e(TAG, "壁纸权限不足", e)
            errorResult("壁纸设置失败: 缺少 SET_WALLPAPER 权限")
        } catch (e: Exception) {
            Log.e(TAG, "壁纸设置失败", e)
            errorResult("壁纸设置失败: ${e.message}")
        }
    }

    private fun successResult(result: JsonObject): JsonObject {
        return buildJsonObject {
            put("status", "success")
            put("result", result)
        }
    }

    private fun errorResult(error: String): JsonObject {
        return buildJsonObject {
            put("status", "error")
            put("error", error)
        }
    }
}
