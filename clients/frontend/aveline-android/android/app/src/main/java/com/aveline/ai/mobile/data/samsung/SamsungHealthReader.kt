package com.aveline.ai.mobile.data.samsung

import android.app.Activity
import android.util.Log
import com.samsung.android.sdk.health.data.request.DataType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Samsung Health 数据读取门面。
 *
 * 国行设备 Health Connect 系统服务被裁剪,无法读取睡眠/体脂/体重等历史数据。
 * Samsung Health Data SDK 直接读取 Samsung Health 应用的数据存储,
 * 不依赖 Google 系统服务,是国行设备的可行方案。
 *
 * 数据流: Galaxy Watch → Samsung Health (手机应用) → 本读取器 → 后端
 *
 * 三档同步口径(调度见 SamsungHealthSyncController):
 * - [readVitals] 高频: 心率/步数/活动汇总/爬楼/皮温/血氧
 * - [readBodyComposition] 低频(24 小时): 身体成分与血压/体温/血糖
 * - [readAll] 中频全量: 一次组装全部数据
 *
 * 本类只做组装; 各数据类型的读取实现在同包的领域读取器中:
 * - [SamsungHealthPermissions] 读取权限请求与检查
 * - [SamsungHealthVitalsReader] 高频生命体征
 * - [SamsungHealthBodyReader] 身体成分/血压/体温/血糖
 * - [SamsungHealthSleepReader] 睡眠记录选择与子会话合并
 * - [SamsungHealthDietActivityReader] 饮食/饮水/运动会话
 * - [SamsungHealthScoreGoalReader] 能量评分/健康预警/各类目标
 *
 * 权限请求需要 Activity,因 SDK 的 HealthDataStore.requestPermissions 是 UI 操作。
 * 调用方需在 UI 层获取 Activity 引用后传入 [ensurePermissions]。
 */
@Singleton
class SamsungHealthReader @Inject constructor(
    private val permissions: SamsungHealthPermissions,
    private val vitalsReader: SamsungHealthVitalsReader,
    private val bodyReader: SamsungHealthBodyReader,
    private val sleepReader: SamsungHealthSleepReader,
    private val dietActivityReader: SamsungHealthDietActivityReader,
    private val scoreGoalReader: SamsungHealthScoreGoalReader
) {
    /**
     * 检查并请求 Samsung Health 数据读取权限。
     *
     * 已授权时直接返回 true;未授权时弹出 Samsung Health 权限请求界面。
     * 必须在主线程调用(因涉及 UI),但内部是 suspend,可在协程中调用。
     *
     * @param activity 用于显示权限请求 UI 的 Activity
     * @return true 表示所有权限已授权;false 表示用户拒绝或请求失败
     */
    suspend fun ensurePermissions(activity: Activity): Boolean =
        permissions.ensurePermissions(activity)

    /**
     * 检查是否已获得所有 Samsung Health 读取权限。
     *
     * 不请求权限,只检查。供 Service 等无 Activity 场景使用:
     * - true: 权限已授予,可以安全读取数据
     * - false: 权限缺失,需要用户在 Life 页面手动授权
     */
    suspend fun hasPermissions(): Boolean = permissions.hasPermissions()

    /**
     * 高频读取生命体征数据(心率/步数/血氧/皮肤温度/活动汇总)。
     *
     * 专为后台定时同步设计:只读变化频率高的数据,减少 SDK 调用开销。
     * 低频数据(体重/身高/体脂/睡眠/营养等)用 [readAll] 读取。
     *
     * 返回的 snapshot 只填充高频字段,其余为 null。
     */
    suspend fun readVitals(): SamsungHealthSnapshot = withContext(Dispatchers.IO) {
        val now = Instant.now()
        val todayStart = LocalDate.now().atStartOfDay()
        val todayEnd = LocalDateTime.now()

        // 三元组类(一次查询多字段)
        val skinTemp = vitalsReader.readSkinTemperatureData(now)
        val bloodOxygenRaw = vitalsReader.readBloodOxygenData(now)
        val bloodOxygen = bloodOxygenRaw?.copy(
            current = bloodOxygenRaw.current?.let { it / 100f },
            min = bloodOxygenRaw.min?.let { it / 100f },
            max = bloodOxygenRaw.max?.let { it / 100f }
        )
        val activitySummary = vitalsReader.readActivitySummary(todayStart, todayEnd)

        SamsungHealthSnapshot(
            heartRate = vitalsReader.readHeartRate(now),
            heartRateTimestamp = vitalsReader.readHeartRateTimestamp(now),
            // 今日活动聚合(步数/热量/时长/距离)
            stepsToday = vitalsReader.readStepsToday(todayStart, todayEnd),
            activeCaloriesBurned = activitySummary?.activeCalories,
            totalCaloriesBurned = activitySummary?.totalCalories,
            activeTimeMinutes = activitySummary?.activeTime?.toMinutes(),
            totalDistanceKm = activitySummary?.totalDistance?.let { it / 1000f },
            floorsClimbed = vitalsReader.readFloorsClimbedToday(),
            // 血氧
            bloodOxygen = bloodOxygen?.current,
            bloodOxygenMin = bloodOxygen?.min,
            bloodOxygenMax = bloodOxygen?.max,
            // 皮肤温度
            skinTemperature = skinTemp?.current,
            skinTemperatureMin = skinTemp?.min,
            skinTemperatureMax = skinTemp?.max
        )
    }

    /**
     * 低频读取身体成分(体重/身高/体脂/骨骼肌/基础代谢等)。
     *
     * 这类数据只有站上体脂秤才会变,后台 24 小时读一次即可。
     * 高频数据用 [readVitals],中频全量用 [readAll]。
     *
     * 返回的 snapshot 只填充身体成分字段,其余为 null。
     */
    suspend fun readBodyComposition(): SamsungHealthSnapshot = withContext(Dispatchers.IO) {
        val points = bodyReader.readBodyCompositionPoints(Instant.now())
        val snapshot = SamsungHealthSnapshot(
            weightKg = latestBodyCompositionValue(points, DataType.BodyCompositionType.WEIGHT),
            heightM = latestBodyCompositionValue(points, DataType.BodyCompositionType.HEIGHT)?.let { it / 100f },
            bodyFatPercent = latestBodyCompositionValue(points, DataType.BodyCompositionType.BODY_FAT)?.let { it / 100f },
            skeletalMusclePercent = latestBodyCompositionValue(points, DataType.BodyCompositionType.SKELETAL_MUSCLE)?.let { it / 100f },
            basalMetabolicRate = latestBodyCompositionValue(points, DataType.BodyCompositionType.BASAL_METABOLIC_RATE),
            bmi = latestBodyCompositionValue(points, DataType.BodyCompositionType.BODY_MASS_INDEX),
            muscleMass = latestBodyCompositionValue(points, DataType.BodyCompositionType.MUSCLE_MASS),
            bodyFatMass = latestBodyCompositionValue(points, DataType.BodyCompositionType.BODY_FAT_MASS),
            fatFreeMass = latestBodyCompositionValue(points, DataType.BodyCompositionType.FAT_FREE_MASS),
            skeletalMuscleMass = latestBodyCompositionValue(points, DataType.BodyCompositionType.SKELETAL_MUSCLE_MASS),
            totalBodyWater = latestBodyCompositionValue(points, DataType.BodyCompositionType.TOTAL_BODY_WATER)
        )
        // 体成分是"全 N/A"故障的重灾区, 把逐字段取值打进日志,
        // 便于区分"三星健康里没数据"和"读到了但字段没解析出来"。
        Log.d(
            TAG,
            "体成分取值: 体重=${snapshot.weightKg}, 身高=${snapshot.heightM}, 体脂率=${snapshot.bodyFatPercent}, " +
                "骨骼肌率=${snapshot.skeletalMusclePercent}, 脂肪量=${snapshot.bodyFatMass}, " +
                "去脂体重=${snapshot.fatFreeMass}, 骨骼肌量=${snapshot.skeletalMuscleMass}, " +
                "总体水分=${snapshot.totalBodyWater}, 基础代谢=${snapshot.basalMetabolicRate}"
        )
        snapshot
    }

    /**
     * 读取所有健康数据,返回全量快照。
     *
     * 各数据类型独立读取,互不影响:某类读取失败时该字段为 null,不影响其他数据。
     * 在 IO 线程执行,避免阻塞主线程。
     *
     * 注意: EnergyScore 和各类 Goal 使用 LocalDateFilter.since 而非 LocalDateFilter.of,
     * 因为 of(today, today) 在 SDK 内部被判定 "Time Range is invalid"(start==end)。
     * since(today) 表示 [today, +∞) 开放区间,能正确查到今日数据。
     */
    suspend fun readAll(includeBodyComposition: Boolean = true): SamsungHealthSnapshot = withContext(Dispatchers.IO) {
        val now = Instant.now()
        val today = LocalDate.now()
        val todayStart = today.atStartOfDay()
        val todayEnd = LocalDateTime.now()

        // 三元组类(一次查询多字段)
        val skinTemp = vitalsReader.readSkinTemperatureData(now)
        // SDK 返回百分比数值(如 95.0 表示 95%),转 0-1
        val bloodOxygenRaw = vitalsReader.readBloodOxygenData(now)
        val bloodOxygen = bloodOxygenRaw?.copy(
            current = bloodOxygenRaw.current?.let { it / 100f },
            min = bloodOxygenRaw.min?.let { it / 100f },
            max = bloodOxygenRaw.max?.let { it / 100f }
        )
        // 今日累计类
        val nutrition = dietActivityReader.readNutritionToday()
        // 今日逐条饮食记录(食物名/餐次/热量), 与 nutrition 总量同源但不互相依赖
        val nutritionEntries = dietActivityReader.readNutritionEntries()
        // 今日逐条饮水记录(时间+量)
        val waterIntakeEntries = dietActivityReader.readWaterIntakeEntries()
        val activitySummary = vitalsReader.readActivitySummary(todayStart, todayEnd)
        // 今日运动会话
        val exerciseSessions = dietActivityReader.readExerciseSessionsToday()
        // 睡眠会话(含阶段信息)
        val sleepSessions = sleepReader.readSleepSessions(now)
        // 体成分: 一次查询取回窗口内全部记录, 各字段再取"最近一次非空值"。
        // 低频通道传 false 时整体跳过(体成分由 readBodyComposition 每 24 小时单独读一次)。
        val bodyComposition = if (includeBodyComposition) {
            bodyReader.readBodyCompositionPoints(now)
        } else {
            emptyList()
        }

        SamsungHealthSnapshot(
            steps = null, // 步数由手表端 Health Services 实时采集,这里不重复读
            heartRate = vitalsReader.readHeartRate(now),
            heartRateTimestamp = vitalsReader.readHeartRateTimestamp(now),
            sleepMinutes = sleepSessions?.totalMinutes,
            sleepStartTime = sleepSessions?.startTime,
            sleepEndTime = sleepSessions?.endTime,
            sleepStageMinutes = sleepSessions?.stageMinutes,
            sleepScore = sleepSessions?.score,
            // 体成分: 体重/身高/体脂这类几乎不变,后台低频通道传 false 跳过整个查询。
            weightKg = latestBodyCompositionValue(bodyComposition, DataType.BodyCompositionType.WEIGHT),
            heightM = latestBodyCompositionValue(bodyComposition, DataType.BodyCompositionType.HEIGHT)?.let { it / 100f },
            bodyFatPercent = latestBodyCompositionValue(bodyComposition, DataType.BodyCompositionType.BODY_FAT)?.let { it / 100f },
            skeletalMusclePercent = latestBodyCompositionValue(bodyComposition, DataType.BodyCompositionType.SKELETAL_MUSCLE)?.let { it / 100f },
            basalMetabolicRate = latestBodyCompositionValue(bodyComposition, DataType.BodyCompositionType.BASAL_METABOLIC_RATE),
            bmi = latestBodyCompositionValue(bodyComposition, DataType.BodyCompositionType.BODY_MASS_INDEX),
            muscleMass = latestBodyCompositionValue(bodyComposition, DataType.BodyCompositionType.MUSCLE_MASS),
            bodyFatMass = latestBodyCompositionValue(bodyComposition, DataType.BodyCompositionType.BODY_FAT_MASS),
            fatFreeMass = latestBodyCompositionValue(bodyComposition, DataType.BodyCompositionType.FAT_FREE_MASS),
            skeletalMuscleMass = latestBodyCompositionValue(bodyComposition, DataType.BodyCompositionType.SKELETAL_MUSCLE_MASS),
            totalBodyWater = latestBodyCompositionValue(bodyComposition, DataType.BodyCompositionType.TOTAL_BODY_WATER),
            systolic = bodyReader.readBloodPressureField(DataType.BloodPressureType.SYSTOLIC, now),
            diastolic = bodyReader.readBloodPressureField(DataType.BloodPressureType.DIASTOLIC, now),
            bodyTemperature = bodyReader.readBodyTemperature(now),
            bloodGlucose = bodyReader.readBloodGlucose(now),
            // 新增: 皮肤温度
            skinTemperature = skinTemp?.current,
            skinTemperatureMin = skinTemp?.min,
            skinTemperatureMax = skinTemp?.max,
            // 新增: 血氧
            bloodOxygen = bloodOxygen?.current,
            bloodOxygenMin = bloodOxygen?.min,
            bloodOxygenMax = bloodOxygen?.max,
            // 新增: 爬楼/饮水/营养
            floorsClimbed = vitalsReader.readFloorsClimbedToday(),
            waterIntakeMl = dietActivityReader.readWaterIntakeToday(),
            nutritionCalories = nutrition?.calories,
            nutritionProtein = nutrition?.protein,
            nutritionCarbs = nutrition?.carbs,
            nutritionFat = nutrition?.fat,
            // 新增: 微量营养素总量
            nutritionSaturatedFat = nutrition?.saturatedFat,
            nutritionTransFat = nutrition?.transFat,
            nutritionDietaryFiber = nutrition?.dietaryFiber,
            nutritionSugar = nutrition?.sugar,
            nutritionCholesterol = nutrition?.cholesterol,
            nutritionSodium = nutrition?.sodium,
            nutritionPotassium = nutrition?.potassium,
            nutritionVitaminA = nutrition?.vitaminA,
            nutritionVitaminC = nutrition?.vitaminC,
            nutritionCalcium = nutrition?.calcium,
            nutritionIron = nutrition?.iron,
            // 新增: 运动会话
            exerciseSessions = exerciseSessions,
            nutritionEntries = nutritionEntries,
            waterIntakeEntries = waterIntakeEntries,
            // 新增: 睡眠呼吸暂停 / 心律不齐
            sleepApneaSign = scoreGoalReader.readSleepApneaSign(now),
            irregularHeartRhythmStatus = scoreGoalReader.readIrregularHeartRhythmStatus(now),
            // 新增: 能量评分
            energyScore = scoreGoalReader.readEnergyScore(today),
            // 新增: 今日活动聚合
            stepsToday = vitalsReader.readStepsToday(todayStart, todayEnd),
            activeCaloriesBurned = activitySummary?.activeCalories,
            totalCaloriesBurned = activitySummary?.totalCalories,
            activeTimeMinutes = activitySummary?.activeTime?.toMinutes(),
            totalDistanceKm = activitySummary?.totalDistance?.let { it / 1000f },
            // 新增: 各类目标
            sleepGoalBedTime = scoreGoalReader.readSleepGoalBedTime(today),
            sleepGoalWakeTime = scoreGoalReader.readSleepGoalWakeTime(today),
            stepsGoal = scoreGoalReader.readStepsGoal(today),
            activeCaloriesGoal = scoreGoalReader.readActiveCaloriesGoal(today),
            activeTimeGoalMinutes = scoreGoalReader.readActiveTimeGoal(today)?.toMinutes(),
            waterIntakeGoalMl = scoreGoalReader.readWaterIntakeGoal(today),
            nutritionGoalCalories = scoreGoalReader.readNutritionGoal(today)
        )
    }

    companion object {
        private const val TAG = "SamsungHealthReader"
    }
}
