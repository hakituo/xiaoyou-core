package com.aveline.ai.mobile.data.samsung

import android.app.Activity
import android.util.Log
import com.samsung.android.sdk.health.data.HealthDataStore
import com.samsung.android.sdk.health.data.permission.AccessType
import com.samsung.android.sdk.health.data.permission.Permission
import com.samsung.android.sdk.health.data.request.DataTypes
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Samsung Health 读取权限管理。
 *
 * 权限请求需要 Activity, 因 SDK 的 [HealthDataStore.requestPermissions] 是 UI 操作;
 * 无 Activity 的场景(后台 Service)只能检查不能请求, 见 [hasPermissions]。
 */
@Singleton
class SamsungHealthPermissions @Inject constructor(
    private val store: HealthDataStore
) {
    /**
     * 所需的读取权限集合。
     * 覆盖 SDK 支持的全部数据类型(原有 6 类 + 新增 17 类)。
     */
    private val requiredPermissions: Set<Permission> = setOf(
        // 原有 6 类
        Permission.of(DataTypes.SLEEP, AccessType.READ),
        Permission.of(DataTypes.BODY_COMPOSITION, AccessType.READ),
        Permission.of(DataTypes.BLOOD_PRESSURE, AccessType.READ),
        Permission.of(DataTypes.BODY_TEMPERATURE, AccessType.READ),
        Permission.of(DataTypes.BLOOD_GLUCOSE, AccessType.READ),
        Permission.of(DataTypes.HEART_RATE, AccessType.READ),
        // 新增 17 类
        Permission.of(DataTypes.SKIN_TEMPERATURE, AccessType.READ),
        Permission.of(DataTypes.BLOOD_OXYGEN, AccessType.READ),
        Permission.of(DataTypes.FLOORS_CLIMBED, AccessType.READ),
        Permission.of(DataTypes.WATER_INTAKE, AccessType.READ),
        Permission.of(DataTypes.NUTRITION, AccessType.READ),
        Permission.of(DataTypes.EXERCISE, AccessType.READ),
        Permission.of(DataTypes.SLEEP_APNEA, AccessType.READ),
        Permission.of(DataTypes.IRREGULAR_HEART_RHYTHM_NOTIFICATION, AccessType.READ),
        Permission.of(DataTypes.ENERGY_SCORE, AccessType.READ),
        Permission.of(DataTypes.STEPS, AccessType.READ),
        Permission.of(DataTypes.ACTIVITY_SUMMARY, AccessType.READ),
        Permission.of(DataTypes.SLEEP_GOAL, AccessType.READ),
        Permission.of(DataTypes.STEPS_GOAL, AccessType.READ),
        Permission.of(DataTypes.ACTIVE_CALORIES_BURNED_GOAL, AccessType.READ),
        Permission.of(DataTypes.ACTIVE_TIME_GOAL, AccessType.READ),
        Permission.of(DataTypes.WATER_INTAKE_GOAL, AccessType.READ),
        Permission.of(DataTypes.NUTRITION_GOAL, AccessType.READ)
    )

    /**
     * 检查并请求 Samsung Health 数据读取权限。
     *
     * 已授权时直接返回 true;未授权时弹出 Samsung Health 权限请求界面。
     * 必须在主线程调用(因涉及 UI),但内部是 suspend,可在协程中调用。
     *
     * @param activity 用于显示权限请求 UI 的 Activity
     * @return true 表示所有权限已授权;false 表示用户拒绝或请求失败
     */
    suspend fun ensurePermissions(activity: Activity): Boolean = withContext(Dispatchers.Main) {
        runCatching {
            val granted = store.getGrantedPermissions(requiredPermissions)
            if (granted.containsAll(requiredPermissions)) {
                return@runCatching true
            }
            val missing = requiredPermissions - granted
            Log.i(TAG, "缺少权限: ${missing.size} 项,请求中...")
            val obtained = store.requestPermissions(missing, activity)
            obtained.containsAll(missing)
        }.onFailure { e ->
            Log.e(TAG, "请求权限失败: ${e.message}", e)
        }.getOrDefault(false)
    }

    /**
     * 检查是否已获得所有 Samsung Health 读取权限。
     *
     * 不请求权限,只检查。供 Service 等无 Activity 场景使用:
     * - true: 权限已授予,可以安全读取数据
     * - false: 权限缺失,需要用户在 Life 页面手动授权
     */
    suspend fun hasPermissions(): Boolean = withContext(Dispatchers.IO) {
        runCatching {
            store.getGrantedPermissions(requiredPermissions).containsAll(requiredPermissions)
        }.getOrDefault(false)
    }

    companion object {
        private const val TAG = "SamsungHealthPermission"
    }
}
