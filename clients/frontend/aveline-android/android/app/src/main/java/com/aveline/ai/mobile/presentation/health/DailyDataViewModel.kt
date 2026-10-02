package com.aveline.ai.mobile.presentation.health

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.domain.models.BatteryStatus
import com.aveline.ai.mobile.domain.models.DeviceContext
import com.aveline.ai.mobile.domain.models.HealthData
import com.aveline.ai.mobile.domain.models.NetworkType
import com.aveline.ai.mobile.data.samsung.SamsungHealthReader
import com.aveline.ai.mobile.data.samsung.SamsungHealthSnapshot
import com.aveline.ai.mobile.data.samsung.toSyncJson
import com.aveline.ai.mobile.data.wear.WearDataSource
import com.aveline.ai.mobile.domain.repository.ContextRepository
import com.aveline.ai.mobile.domain.repository.HealthRepository
import android.app.Activity
import dagger.hilt.android.lifecycle.HiltViewModel
import java.time.Instant
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

enum class DailyTab {
    PORTRAIT,
    SCHEDULE,
    FILES,
}

data class DailyRecentFile(
    val path: String,
    val name: String,
    val size: Int?,
    val mtime: Int?,
    val ext: String?,
)

data class DailyStudySession(
    val topic: String,
    val content: String,
    val time: String,
)

data class DailyMeal(
    val type: String,
    val content: String,
    val time: String,
)

data class DailyDataUiState(
    val activeTab: DailyTab = DailyTab.PORTRAIT,
    val isLoading: Boolean = false,
    val error: String? = null,
    val message: String? = null,
    val lastRefreshTime: Long = 0L,
    val portraitDate: String = "",
    val wakeup: String? = null,
    val sleep: String? = null,
    val drinkTotalMl: Int = 0,
    val drinkCount: Int = 0,
    val studyTotalMinutes: Int = 0,
    val studyCount: Int = 0,
    val studySessions: List<DailyStudySession> = emptyList(),
    val meals: List<DailyMeal> = emptyList(),
    val reducedModeActive: Boolean = false,
    val reducedModeReason: String = "",
    val reducedModeExpectedEndTs: Long? = null,
    val weightKg: Double? = null,
    val recentFiles: List<DailyRecentFile> = emptyList(),
    // 健康数据 (由 Samsung Health + 手表实时数据填充)
    val steps: Long? = null,
    val heartRate: Int? = null,
    val heartRateTimestamp: Long? = null,
    val healthWeightKg: Double? = null,
    val heightM: Double? = null,
    val bodyFatPercent: Double? = null,
    val skeletalMusclePercent: Double? = null,
    // 身体成分扩展字段(kg)
    val muscleMass: Double? = null,
    val bodyFatMass: Double? = null,
    val fatFreeMass: Double? = null,
    val skeletalMuscleMass: Double? = null,
    val totalBodyWater: Double? = null,
    val sleepMinutes: Long? = null,
    val sleepStartTime: Long? = null,
    val sleepEndTime: Long? = null,
    // 睡眠阶段时长(分钟), null 表示该阶段无记录
    val sleepStageAwakeMinutes: Long? = null,
    val sleepStageLightMinutes: Long? = null,
    val sleepStageDeepMinutes: Long? = null,
    val sleepStageRemMinutes: Long? = null,
    // 睡眠得分 (0-100)
    val sleepScore: Int? = null,
    val bloodPressureSystolic: Double? = null,
    val bloodPressureDiastolic: Double? = null,
    val bodyTemperature: Double? = null,
    val bloodGlucose: Double? = null,
    // Samsung Health 扩展数据
    val skinTemperature: Double? = null,
    val bloodOxygen: Double? = null,
    val floorsClimbed: Double? = null,
    val waterIntakeMl: Double? = null,
    val nutritionCalories: Double? = null,
    val nutritionProtein: Double? = null,
    val nutritionCarbs: Double? = null,
    val nutritionFat: Double? = null,
    val nutritionSaturatedFat: Double? = null,
    val nutritionTransFat: Double? = null,
    val nutritionDietaryFiber: Double? = null,
    val nutritionSugar: Double? = null,
    val nutritionCholesterol: Double? = null,
    val nutritionSodium: Double? = null,
    val nutritionPotassium: Double? = null,
    val nutritionVitaminA: Double? = null,
    val nutritionVitaminC: Double? = null,
    val nutritionCalcium: Double? = null,
    val nutritionIron: Double? = null,
    val exerciseSessions: List<com.aveline.ai.mobile.data.samsung.ExerciseSnapshot> = emptyList(),
    // 今日逐条饮食记录(来自 Samsung Health 营养数据: 食物名/餐次/热量)
    val nutritionEntries: List<com.aveline.ai.mobile.data.samsung.NutritionEntry> = emptyList(),
    // 今日逐条饮水记录(来自 Samsung Health: 时间+量)
    val waterIntakeEntries: List<com.aveline.ai.mobile.data.samsung.WaterIntakeEntry> = emptyList(),
    val sleepApneaSign: String? = null,
    val irregularHeartRhythmStatus: String? = null,
    val energyScore: Double? = null,
    val stepsToday: Long? = null,
    val activeCaloriesBurned: Double? = null,
    val totalCaloriesBurned: Double? = null,
    val activeTimeMinutes: Long? = null,
    val totalDistanceKm: Double? = null,
    val sleepGoalBedTime: String? = null,
    val sleepGoalWakeTime: String? = null,
    val stepsGoal: Int? = null,
    val activeCaloriesGoal: Int? = null,
    val activeTimeGoalMinutes: Long? = null,
    val waterIntakeGoalMl: Double? = null,
    val nutritionGoalCalories: Double? = null,
    // 设备上下文 (电池/网络/亮度/音量) - 来自 ContextRepository, 不需要特殊权限
    val batteryLevel: Int? = null,
    val isCharging: Boolean = false,
    val batteryStatus: BatteryStatus = BatteryStatus.UNKNOWN,
    val networkType: NetworkType = NetworkType.UNKNOWN,
    val screenBrightness: Int? = null,
    val volumeLevel: Int? = null
)

@HiltViewModel
class DailyDataViewModel @Inject constructor(
    private val healthRepository: HealthRepository,
    private val contextRepository: ContextRepository,
    private val wearDataSource: WearDataSource,
    private val samsungHealthReader: SamsungHealthReader
) : ViewModel() {
    private val _uiState = MutableStateFlow(DailyDataUiState())
    val uiState: StateFlow<DailyDataUiState> = _uiState.asStateFlow()

    // Samsung Health 同步防重入标志(独立于 isLoading)。
    // 不能用 _uiState.isLoading 做守卫: refreshData() 也会置 isLoading=true,
    // 会导致 ON_RESUME/进页时 Samsung 同步被误判为"正在加载"而跳过, 健康数据不刷新。
    private var isSyncingSamsungHealth = false

    init {
        collectWearHealthData()
        refreshData()
    }

    /**
     * 持续监听手表通过 Wearable Data Layer 发送的健康数据。
     *
     * 收到数据后更新 UI 状态,并尝试同步到后端。与 Health Connect 数据独立,
     * 后续可再合并优先级策略。
     */
    private fun collectWearHealthData() {
        viewModelScope.launch {
            runCatching {
                wearDataSource.observeHealthData().collect { data ->
                    _uiState.update {
                        it.copy(
                            steps = data.steps.takeIf { s -> s > 0 } ?: it.steps,
                            heartRate = data.heartRate ?: it.heartRate,
                            heartRateTimestamp = data.heartRateTimestamp?.toEpochMilli()
                                ?: it.heartRateTimestamp,
                            healthWeightKg = data.weight ?: it.healthWeightKg,
                            heightM = data.height ?: it.heightM,
                            bodyFatPercent = data.bodyFat ?: it.bodyFatPercent,
                            sleepMinutes = data.sleepMinutes ?: it.sleepMinutes,
                            sleepStartTime = data.sleepStartTime?.toEpochMilli()
                                ?: it.sleepStartTime,
                            sleepEndTime = data.sleepEndTime?.toEpochMilli()
                                ?: it.sleepEndTime,
                            bloodPressureSystolic = data.bloodPressureSystolic
                                ?: it.bloodPressureSystolic,
                            bloodPressureDiastolic = data.bloodPressureDiastolic
                                ?: it.bloodPressureDiastolic,
                            bodyTemperature = data.bodyTemperature ?: it.bodyTemperature,
                            bloodGlucose = data.bloodGlucose ?: it.bloodGlucose,
                            lastRefreshTime = System.currentTimeMillis()
                        )
                    }
                    syncWearHealthDataToBackend(data)
                }
            }.onFailure { e ->
                // Wearable API 不可用或其他异常,不崩溃 app,只记录日志
                android.util.Log.w("DailyDataViewModel", "手表数据监听失败: ${e.message}")
            }
        }
    }

    private fun syncWearHealthDataToBackend(data: HealthData) {
        viewModelScope.launch {
            runCatching {
                healthRepository.syncHealthData(
                    buildJsonObject {
                        put("source", "wear_os")
                        // 实时数据 (Health Services)
                        put("steps", data.steps.takeIf { it > 0 })
                        put("heart_rate", data.heartRate)
                        put("heart_rate_timestamp", data.heartRateTimestamp?.toString())
                        // 历史数据 (Health Connect, 纯 IO 读取)
                        put("weight_kg", data.weight)
                        put("weight_timestamp", data.weightTimestamp?.toString())
                        put("height_m", data.height)
                        put("height_timestamp", data.heightTimestamp?.toString())
                        put("body_fat_percent", data.bodyFat)
                        put("sleep_minutes", data.sleepMinutes)
                        put("sleep_start_time", data.sleepStartTime?.toString())
                        put("sleep_end_time", data.sleepEndTime?.toString())
                        put("blood_pressure_systolic", data.bloodPressureSystolic)
                        put("blood_pressure_diastolic", data.bloodPressureDiastolic)
                        put("body_temperature", data.bodyTemperature)
                        put("blood_glucose", data.bloodGlucose)
                        put("collected_at", Instant.now().toString())
                    }
                )
            }
        }
    }

    /**
     * 从 Samsung Health 读取健康数据并同步到后端。
     *
     * 国行设备 Health Connect 不可用,改用 Samsung Health Data SDK 直接读取
     * Samsung Health 应用的数据存储。需要 Activity 来请求权限。
     *
     * 数据流: Samsung Health (手机应用) → SamsungHealthReader → UI + 后端
     *
     * @param activity 用于显示 Samsung Health 权限请求 UI 的 Activity
     */
    fun syncFromSamsungHealth(activity: Activity) {
        // 防重入: 正在同步时跳过(定时器可能在同步进行中触发)。
        // 用独立标志而非 isLoading, 避免与 refreshData() 互相阻塞。
        if (isSyncingSamsungHealth) return
        isSyncingSamsungHealth = true
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isLoading = true,
                    message = "正在同步三星健康数据...",
                    error = null
                )
            }

            // 步骤 1: 请求权限
            val granted = runCatching {
                samsungHealthReader.ensurePermissions(activity)
            }.getOrDefault(false)

            if (!granted) {
                isSyncingSamsungHealth = false
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        message = "需要授权才能读取三星健康数据,请在 Samsung Health 中开启权限"
                    )
                }
                return@launch
            }

            // 步骤 2: 读取数据
            val snapshot = runCatching {
                samsungHealthReader.readAll()
            }.getOrElse { e ->
                isSyncingSamsungHealth = false
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        error = "读取数据失败: ${e.message}"
                    )
                }
                return@launch
            }

            // 步骤 3: 更新 UI 状态
            _uiState.update {
                it.copy(
                    // 步数优先用 Samsung Health 聚合值(与"今日活动"区块一致),
                    // 聚合值为空时回退到手表实时值
                    steps = snapshot.stepsToday?.takeIf { it > 0 } ?: it.steps,
                    heartRate = snapshot.heartRate ?: it.heartRate,
                    heartRateTimestamp = snapshot.heartRateTimestamp?.toEpochMilli()
                        ?: it.heartRateTimestamp,
                    sleepMinutes = snapshot.sleepMinutes ?: it.sleepMinutes,
                    sleepStartTime = snapshot.sleepStartTime?.toEpochMilli()
                        ?: it.sleepStartTime,
                    sleepEndTime = snapshot.sleepEndTime?.toEpochMilli()
                        ?: it.sleepEndTime,
                    // 睡眠阶段时长
                    sleepStageAwakeMinutes = snapshot.sleepStageMinutes?.awake ?: it.sleepStageAwakeMinutes,
                    sleepStageLightMinutes = snapshot.sleepStageMinutes?.light ?: it.sleepStageLightMinutes,
                    sleepStageDeepMinutes = snapshot.sleepStageMinutes?.deep ?: it.sleepStageDeepMinutes,
                    sleepStageRemMinutes = snapshot.sleepStageMinutes?.rem ?: it.sleepStageRemMinutes,
                    // 睡眠得分
                    sleepScore = snapshot.sleepScore ?: it.sleepScore,
                    healthWeightKg = snapshot.weightKg?.toDouble() ?: it.healthWeightKg,
                    heightM = snapshot.heightM?.toDouble() ?: it.heightM,
                    bodyFatPercent = snapshot.bodyFatPercent?.toDouble() ?: it.bodyFatPercent,
                    skeletalMusclePercent = snapshot.skeletalMusclePercent?.toDouble() ?: it.skeletalMusclePercent,
                    // 身体成分扩展字段
                    muscleMass = snapshot.muscleMass?.toDouble() ?: it.muscleMass,
                    bodyFatMass = snapshot.bodyFatMass?.toDouble() ?: it.bodyFatMass,
                    fatFreeMass = snapshot.fatFreeMass?.toDouble() ?: it.fatFreeMass,
                    skeletalMuscleMass = snapshot.skeletalMuscleMass?.toDouble() ?: it.skeletalMuscleMass,
                    totalBodyWater = snapshot.totalBodyWater?.toDouble() ?: it.totalBodyWater,
                    bloodPressureSystolic = snapshot.systolic?.toDouble()
                        ?: it.bloodPressureSystolic,
                    bloodPressureDiastolic = snapshot.diastolic?.toDouble()
                        ?: it.bloodPressureDiastolic,
                    bodyTemperature = snapshot.bodyTemperature?.toDouble()
                        ?: it.bodyTemperature,
                    bloodGlucose = snapshot.bloodGlucose?.toDouble() ?: it.bloodGlucose,
                    // 扩展字段
                    skinTemperature = snapshot.skinTemperature?.toDouble() ?: it.skinTemperature,
                    bloodOxygen = snapshot.bloodOxygen?.toDouble() ?: it.bloodOxygen,
                    floorsClimbed = snapshot.floorsClimbed?.toDouble() ?: it.floorsClimbed,
                    waterIntakeMl = snapshot.waterIntakeMl?.toDouble() ?: it.waterIntakeMl,
                    nutritionCalories = snapshot.nutritionCalories?.toDouble() ?: it.nutritionCalories,
                    nutritionProtein = snapshot.nutritionProtein?.toDouble() ?: it.nutritionProtein,
                    nutritionCarbs = snapshot.nutritionCarbs?.toDouble() ?: it.nutritionCarbs,
                    nutritionFat = snapshot.nutritionFat?.toDouble() ?: it.nutritionFat,
                    nutritionSaturatedFat = snapshot.nutritionSaturatedFat?.toDouble() ?: it.nutritionSaturatedFat,
                    nutritionTransFat = snapshot.nutritionTransFat?.toDouble() ?: it.nutritionTransFat,
                    nutritionDietaryFiber = snapshot.nutritionDietaryFiber?.toDouble() ?: it.nutritionDietaryFiber,
                    nutritionSugar = snapshot.nutritionSugar?.toDouble() ?: it.nutritionSugar,
                    nutritionCholesterol = snapshot.nutritionCholesterol?.toDouble() ?: it.nutritionCholesterol,
                    nutritionSodium = snapshot.nutritionSodium?.toDouble() ?: it.nutritionSodium,
                    nutritionPotassium = snapshot.nutritionPotassium?.toDouble() ?: it.nutritionPotassium,
                    nutritionVitaminA = snapshot.nutritionVitaminA?.toDouble() ?: it.nutritionVitaminA,
                    nutritionVitaminC = snapshot.nutritionVitaminC?.toDouble() ?: it.nutritionVitaminC,
                    nutritionCalcium = snapshot.nutritionCalcium?.toDouble() ?: it.nutritionCalcium,
                    nutritionIron = snapshot.nutritionIron?.toDouble() ?: it.nutritionIron,
                    exerciseSessions = snapshot.exerciseSessions,
                    nutritionEntries = snapshot.nutritionEntries,
                    waterIntakeEntries = snapshot.waterIntakeEntries,
                    sleepApneaSign = snapshot.sleepApneaSign ?: it.sleepApneaSign,
                    irregularHeartRhythmStatus = snapshot.irregularHeartRhythmStatus
                        ?: it.irregularHeartRhythmStatus,
                    energyScore = snapshot.energyScore?.toDouble() ?: it.energyScore,
                    stepsToday = snapshot.stepsToday ?: it.stepsToday,
                    activeCaloriesBurned = snapshot.activeCaloriesBurned?.toDouble()
                        ?: it.activeCaloriesBurned,
                    totalCaloriesBurned = snapshot.totalCaloriesBurned?.toDouble()
                        ?: it.totalCaloriesBurned,
                    activeTimeMinutes = snapshot.activeTimeMinutes ?: it.activeTimeMinutes,
                    totalDistanceKm = snapshot.totalDistanceKm?.toDouble() ?: it.totalDistanceKm,
                    sleepGoalBedTime = snapshot.sleepGoalBedTime?.toString() ?: it.sleepGoalBedTime,
                    sleepGoalWakeTime = snapshot.sleepGoalWakeTime?.toString() ?: it.sleepGoalWakeTime,
                    stepsGoal = snapshot.stepsGoal ?: it.stepsGoal,
                    activeCaloriesGoal = snapshot.activeCaloriesGoal ?: it.activeCaloriesGoal,
                    activeTimeGoalMinutes = snapshot.activeTimeGoalMinutes ?: it.activeTimeGoalMinutes,
                    waterIntakeGoalMl = snapshot.waterIntakeGoalMl?.toDouble() ?: it.waterIntakeGoalMl,
                    nutritionGoalCalories = snapshot.nutritionGoalCalories?.toDouble()
                        ?: it.nutritionGoalCalories,
                    isLoading = false,
                    message = "三星健康数据已同步",
                    lastRefreshTime = System.currentTimeMillis()
                )
            }

            // 步骤 4: 同步到后端
            syncSamsungHealthToBackend(snapshot)
            isSyncingSamsungHealth = false
        }
    }

    /**
     * 将 Samsung Health 快照同步到后端。
     */
    private fun syncSamsungHealthToBackend(snapshot: SamsungHealthSnapshot) {
        viewModelScope.launch {
            runCatching {
                healthRepository.syncHealthData(snapshot.toSyncJson())
            }
        }
    }

    fun setActiveTab(tab: DailyTab) {
        _uiState.update { it.copy(activeTab = tab) }
    }

    fun refreshData() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }

            runCatching {
                val portrait = healthRepository.getDailyPortraitToday().getOrThrow()
                val recent = healthRepository.getDailyRecent(limit = 12).getOrThrow()
                val portraitData = portrait["portrait"]?.jsonObject ?: JsonObject(emptyMap())
                val schedule = portraitData["schedule"]?.jsonObject
                val drink = portraitData["drink"]?.jsonObject
                val study = portraitData["study"]?.jsonObject
                val mode = portraitData["mode"]?.jsonObject
                val bodyMetrics = portraitData["body_metrics"]?.jsonObject
                val sessions = study?.get("sessions")?.jsonArray.orEmptyArray().map { item ->
                    val obj = item.jsonObject
                    DailyStudySession(
                        topic = obj.string("topic"),
                        content = obj.string("content"),
                        time = obj.string("time")
                    )
                }
                val meals = portraitData["meals"]?.jsonArray.orEmptyArray().map { item ->
                    val obj = item.jsonObject
                    DailyMeal(
                        type = obj.string("type"),
                        content = obj.string("content"),
                        time = obj.string("time")
                    )
                }
                val files = recent["items"]?.jsonArray.orEmptyArray().map { item ->
                    val obj = item.jsonObject
                    DailyRecentFile(
                        path = obj.string("path"),
                        name = obj.string("name"),
                        size = obj.int("size"),
                        mtime = obj.int("mtime"),
                        ext = obj.string("ext").ifBlank { null }
                    )
                }

                // 设备上下文: 电池/网络/亮度/音量 (本地系统 API, 不需要 HC 权限)
                // 单独 try, 失败不阻断主流程 (设备上下文是次要信息)
                val deviceCtx = runCatching { contextRepository.getDeviceContext() }.getOrNull()

                _uiState.update {
                    it.copy(
                        isLoading = false,
                        portraitDate = portrait.string("date"),
                        wakeup = schedule?.string("wakeup")?.ifBlank { null },
                        sleep = schedule?.string("sleep")?.ifBlank { null },
                        drinkTotalMl = drink?.int("total_ml") ?: 0,
                        drinkCount = drink?.int("count") ?: 0,
                        studyTotalMinutes = study?.int("total_minutes") ?: 0,
                        studyCount = study?.int("count") ?: 0,
                        studySessions = sessions,
                        meals = meals,
                        reducedModeActive = mode?.bool("reduced_mode_active") ?: false,
                        reducedModeReason = mode?.string("reduced_mode_reason") ?: "",
                        reducedModeExpectedEndTs = mode?.long("reduced_mode_expected_end_ts"),
                        weightKg = bodyMetrics?.double("weight_kg"),
                        recentFiles = files,
                        batteryLevel = deviceCtx?.batteryLevel,
                        isCharging = deviceCtx?.isCharging ?: false,
                        batteryStatus = deviceCtx?.batteryStatus ?: BatteryStatus.UNKNOWN,
                        networkType = deviceCtx?.networkType ?: NetworkType.UNKNOWN,
                        screenBrightness = deviceCtx?.screenBrightness,
                        volumeLevel = deviceCtx?.volumeLevel,
                        // 健康指标(心率/睡眠/体脂/身高/BMI 等)不再由 refreshData 触碰,
                        // 全部由 syncFromSamsungHealth 填充并保留, 避免 HC 的 null 覆盖。
                        lastRefreshTime = System.currentTimeMillis(),
                        error = null
                    )
                }
            }.onFailure { error ->
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        error = error.message ?: "加载 Daily Data 失败"
                    )
                }
            }
        }
    }

    /**
     * 记录喝水。
     *
     * 修复 P0-9: 原实现按 units(250ml/单位) 上报,UI 的 200/300/500ml 按钮做 ml/250 转换时
     * 200ml→0→coerceAtLeast(1)=1→后端记 250ml(多记 50ml),300ml→1→后端记 250ml(少记 50ml)。
     * 后端 /v1/context/drink 实际支持 amount_ml 字段(优先于 units),改为直接传毫升数,
     * 200ml→200ml, 300ml→300ml, 500ml→500ml,精确无误。
     *
     * @param amountMl 实际喝水量(毫升),后端会 clamp 到 [50, 5000]
     */
    fun recordDrink(amountMl: Int = 250) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, message = null, error = null) }
            healthRepository.recordDailyDrink(
                buildJsonObject {
                    put("amount_ml", amountMl)
                }
            ).onSuccess { response ->
                _uiState.update {
                    it.copy(message = response.string("message").ifBlank { "已记录喝水" })
                }
                refreshData()
            }.onFailure { error ->
                _uiState.update {
                    it.copy(isLoading = false, error = error.message ?: "记录喝水失败")
                }
            }
        }
    }

    fun startStudy(subject: String, durationMinutes: Int, note: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, message = null, error = null) }
            healthRepository.recordDailyStudy(
                buildJsonObject {
                    put("subject", subject)
                    put("duration_minutes", durationMinutes)
                    if (note.isNotBlank()) {
                        put("note", note)
                    }
                    put("enter_low_disturbance", true)
                    put("switch_mode_to_study", true)
                }
            ).onSuccess { response ->
                _uiState.update {
                    it.copy(message = response.string("message").ifBlank { "学习会话已开始" })
                }
                refreshData()
            }.onFailure { error ->
                _uiState.update {
                    it.copy(isLoading = false, error = error.message ?: "开始学习失败")
                }
            }
        }
    }

    fun finishStudy() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, message = null, error = null) }
            healthRepository.finishDailyStudy().onSuccess { response ->
                _uiState.update {
                    it.copy(message = response.string("message").ifBlank { "学习会话已结束" })
                }
                refreshData()
            }.onFailure { error ->
                _uiState.update {
                    it.copy(isLoading = false, error = error.message ?: "结束学习失败")
                }
            }
        }
    }

    /**
     * 手动更新今日作息(睡觉/起床时间)。
     *
     * 用于用户修正不准确的自动记录, 更新成功后自动刷新 Daily Data。
     *
     * @param sleep 睡觉时间 HH:MM, 为空表示不修改
     * @param wakeup 起床时间 HH:MM, 为空表示不修改
     */
    fun updateSchedule(sleep: String?, wakeup: String?) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, message = null, error = null) }
            healthRepository.recordDailySchedule(
                buildJsonObject {
                    if (!sleep.isNullOrBlank()) put("sleep", sleep)
                    if (!wakeup.isNullOrBlank()) put("wakeup", wakeup)
                }
            ).onSuccess { response ->
                _uiState.update {
                    it.copy(message = response.string("message").ifBlank { "作息已更新" })
                }
                refreshData()
            }.onFailure { error ->
                _uiState.update {
                    it.copy(isLoading = false, error = error.message ?: "更新作息失败")
                }
            }
        }
    }

    fun clearError() {
        _uiState.update { it.copy(error = null, message = null) }
    }
}

private fun JsonObject.string(key: String): String {
    return this[key]?.jsonPrimitive?.contentOrNull.orEmpty()
}

private fun JsonObject.int(key: String): Int? {
    return this[key]?.jsonPrimitive?.intOrNull
}

private fun JsonObject.long(key: String): Long? {
    return this[key]?.jsonPrimitive?.contentOrNull?.toLongOrNull()
}

private fun JsonObject.double(key: String): Double? {
    return this[key]?.jsonPrimitive?.doubleOrNull
}

private fun JsonObject.bool(key: String): Boolean? {
    return this[key]?.jsonPrimitive?.booleanOrNull
}

private fun JsonArray?.orEmptyArray(): JsonArray {
    return this ?: JsonArray(emptyList())
}

// putNotNull 辅助函数已移至 SamsungHealthSnapshot.kt(toSyncJson 使用)
