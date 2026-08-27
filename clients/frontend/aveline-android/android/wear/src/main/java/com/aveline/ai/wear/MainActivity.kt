package com.aveline.ai.wear

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import android.widget.Button
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.WeightRecord
import androidx.health.connect.client.records.HeightRecord
import androidx.health.connect.client.records.BodyFatRecord
import androidx.health.connect.client.records.BloodPressureRecord
import androidx.health.connect.client.records.BodyTemperatureRecord
import androidx.health.connect.client.records.BloodGlucoseRecord
import androidx.lifecycle.lifecycleScope
import com.aveline.ai.wear.data.HealthConnectReader
import com.aveline.ai.wear.data.WearDataSender
import com.aveline.ai.wear.service.HealthCollectService
import com.aveline.ai.wear.service.HealthState
import kotlinx.coroutines.launch

private const val TAG = "WearMainActivity"

/**
 * Wear OS 主界面。
 *
 * 两个功能:
 * 1. 开始/停止采集 — 启动 HealthCollectService 被动监听步数和心率(实时)
 * 2. 读取健康数据 — 通过 Health Connect 读取睡眠/体重/体脂等历史数据(IO)
 *
 * 数据通过 WearableDataLayer 发送到手机端。
 */
class MainActivity : ComponentActivity() {

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val allGranted = permissions.entries.all { it.value }
        if (allGranted) {
            startCollecting()
        }
    }

    /**
     * Health Connect 权限页返回回调。
     *
     * 不用 PermissionController.createRequestPermissionResultContract(),
     * 因为 Wear OS 上该 contract 启动的权限窗口会立即关闭。
     * 改为直接跳 Health Connect 系统设置页让用户手动授权,返回后直接尝试读取。
     */
    private val hcSettingsLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        // 用户从 Health Connect 设置页返回,直接尝试读取
        doReadAndSendHealthData()
    }

    private lateinit var tvStatus: TextView
    private lateinit var tvSteps: TextView
    private lateinit var tvHeartRate: TextView
    private lateinit var tvDiag: TextView
    private lateinit var btnToggle: Button
    private lateinit var btnReadHealth: Button

    private var isCollecting = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        tvStatus = findViewById(R.id.tvStatus)
        tvSteps = findViewById(R.id.tvSteps)
        tvHeartRate = findViewById(R.id.tvHeartRate)
        tvDiag = findViewById(R.id.tvDiag)
        btnToggle = findViewById(R.id.btnToggle)
        btnReadHealth = findViewById(R.id.btnReadHealth)

        btnToggle.setOnClickListener {
            toggleCollection()
        }

        btnReadHealth.setOnClickListener {
            readAndSendHealthData()
        }

        // 监听 Service 的健康数据,实时更新 UI
        lifecycleScope.launch {
            HealthCollectService.healthState.collect { state ->
                updateHealthDisplay(state)
            }
        }

        updateUi(isCollecting = false)
    }

    private fun toggleCollection() {
        if (isCollecting) {
            HealthCollectService.stop(this)
            isCollecting = false
            updateUi(isCollecting = false)
        } else {
            requestPermissionsAndStart()
        }
    }

    private fun requestPermissionsAndStart() {
        val permissions = arrayOf(
            Manifest.permission.BODY_SENSORS,
            Manifest.permission.ACTIVITY_RECOGNITION
        )
        val needsRequest = permissions.any {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (needsRequest) {
            permissionLauncher.launch(permissions)
        } else {
            startCollecting()
        }
    }

    private fun startCollecting() {
        HealthCollectService.start(this)
        isCollecting = true
        updateUi(isCollecting = true)
    }

    /**
     * 通过 Health Connect 读取所有历史数据并发送到手机。
     *
     * 先尝试直接读取,如果抛 SecurityException(没权限),
     * 则跳转到 Health Connect 系统设置页让用户手动授权。
     * Wear OS 上 PermissionController.createRequestPermissionResultContract() 不稳定,
     * 权限窗口会立即关闭,所以改用直接跳系统设置页的方案。
     */
    private fun readAndSendHealthData() {
        if (!HealthConnectReader.isAvailable(this)) {
            tvDiag.text = "Health Connect 不可用\n(Wear OS 5+ 内置,需三星健康同步数据)"
            return
        }
        doReadAndSendHealthData()
    }

    /** 实际读取,先检查 Health Connect 是否真的可用,再检查权限。 */
    private fun doReadAndSendHealthData() {
        tvDiag.text = "检查 Health Connect…"
        lifecycleScope.launch {
            try {
                // 先验证 Health Connect 系统服务是否真的可用(国行可能裁剪)
                if (!HealthConnectReader.isAvailable(this@MainActivity)) {
                    tvDiag.text = "Health Connect 不可用\n国行手表可能裁剪了该服务\n请用三星健康读取数据"
                    Log.w(TAG, "Health Connect 系统服务不可用")
                    return@launch
                }

                tvDiag.text = "检查权限…"
                // 检查权限
                val client = androidx.health.connect.client.HealthConnectClient.getOrCreate(this@MainActivity)
                val granted = client.permissionController.getGrantedPermissions()
                val missing = REQUIRED_HC_PERMISSIONS - granted
                if (missing.isNotEmpty()) {
                    Log.w(TAG, "缺少 Health Connect 权限: $missing")
                    tvDiag.text = "缺少权限,跳转 Health Connect 设置页…"
                    openHealthConnectSettings()
                    return@launch
                }

                tvDiag.text = "正在读取…"
                val reader = HealthConnectReader(this@MainActivity)
                val sender = WearDataSender(this@MainActivity)

                val snapshot = reader.readAll()

                // 获取当前实时数据(如果 Service 在运行)
                val currentState = HealthCollectService.healthState.value

                // 发送完整数据到手机
                sender.sendFullHealthData(
                    steps = currentState.steps,
                    heartRate = currentState.heartRate,
                    heartRateTimestamp = currentState.heartRateTimestamp,
                    snapshot = snapshot
                )

                // 更新 UI
                val sb = StringBuilder()
                sb.append("睡眠: ").append(snapshot.sleep?.let { "${it.durationMinutes / 60}h ${it.durationMinutes % 60}m" } ?: "无数据")
                sb.append("\n体重: ").append(snapshot.weightKg?.let { "%.1f kg".format(it) } ?: "无数据")
                sb.append("\n体脂: ").append(snapshot.bodyFatPercent?.let { "%.1f%%".format(it) } ?: "无数据")
                sb.append("\n身高: ").append(snapshot.heightM?.let { "%.2f m".format(it) } ?: "无数据")
                snapshot.systolic?.let { sb.append("\n血压: $it/${snapshot.diastolic} mmHg") }
                snapshot.bodyTempCelsius?.let { sb.append("\n体温: %.1f C".format(it)) }
                snapshot.bloodGlucoseMmolL?.let { sb.append("\n血糖: %.1f mmol/L".format(it)) }
                sb.append("\n已发送到手机")

                tvDiag.text = sb.toString()
                Log.i(TAG, "健康数据快照: $snapshot")
            } catch (e: Exception) {
                Log.e(TAG, "读取健康数据失败: ${e.message}", e)
                tvDiag.text = "读取失败: ${e.message}"
            }
        }
    }

    /**
     * 跳转到 Health Connect 权限设置页。
     *
     * Wear OS 5 上 Health Connect 内置在系统设置里,
     * 用 ACTION_MANAGE_HEALTH_PERMISSIONS 打开权限管理页。
     */
    private fun openHealthConnectSettings() {
        try {
            // Android 14+ (API 34) 的 Settings.ACTION_MANAGE_HEALTH_PERMISSIONS
            // 用字符串常量避免 SDK 版本差异导致的编译问题
            val intent = Intent("android.settings.MANAGE_HEALTH_PERMISSIONS").apply {
                putExtra(Intent.EXTRA_PACKAGE_NAME, packageName)
            }
            hcSettingsLauncher.launch(intent)
        } catch (e: Exception) {
            Log.w(TAG, "MANAGE_HEALTH_PERMISSIONS 不可用, fallback 到应用详情页: ${e.message}")
            // fallback: 跳到应用详情页让用户手动找权限
            try {
                val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                    data = Uri.fromParts("package", packageName, null)
                }
                hcSettingsLauncher.launch(intent)
            } catch (e2: Exception) {
                Log.e(TAG, "跳转设置页失败: ${e2.message}", e2)
                tvDiag.text = "无法跳转设置页,请手动到设置里授权"
            }
        }
    }

    private fun updateUi(isCollecting: Boolean) {
        tvStatus.text = getString(
            if (isCollecting) R.string.status_collecting else R.string.status_idle
        )
        btnToggle.text = getString(
            if (isCollecting) R.string.stop_collect else R.string.start_collect
        )
        if (!isCollecting) {
            tvSteps.text = getString(R.string.steps_label)
            tvHeartRate.text = getString(R.string.heart_rate_label)
            tvDiag.text = ""
        }
    }

    private fun updateHealthDisplay(state: HealthState) {
        tvSteps.text = "${getString(R.string.steps_label)}: ${state.steps}"
        tvHeartRate.text = "${getString(R.string.heart_rate_label)}: ${state.heartRate ?: "--"} bpm"
        if (state.statusMessage.isNotBlank()) {
            tvDiag.text = state.statusMessage
        }
    }

    companion object {
        /** Health Connect 需要的所有读取权限 (睡眠/体重/身高/体脂/血压/体温/血糖) */
        private val REQUIRED_HC_PERMISSIONS = setOf(
            HealthPermission.getReadPermission(SleepSessionRecord::class),
            HealthPermission.getReadPermission(WeightRecord::class),
            HealthPermission.getReadPermission(HeightRecord::class),
            HealthPermission.getReadPermission(BodyFatRecord::class),
            HealthPermission.getReadPermission(BloodPressureRecord::class),
            HealthPermission.getReadPermission(BodyTemperatureRecord::class),
            HealthPermission.getReadPermission(BloodGlucoseRecord::class),
        )
    }
}
