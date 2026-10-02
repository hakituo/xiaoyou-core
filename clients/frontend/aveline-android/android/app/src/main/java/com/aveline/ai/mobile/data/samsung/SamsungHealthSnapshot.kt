package com.aveline.ai.mobile.data.samsung

import java.time.Instant
import java.time.LocalTime
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonObjectBuilder
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * 单次饮水记录(来自 Samsung Health 饮水数据)。
 *
 * @property amountMl 饮水量(ml)
 * @property startTime 该条记录的时间
 */
data class WaterIntakeEntry(
    val amountMl: Float,
    val startTime: Instant
)

/**
 * 单次饮食记录快照(来自 Samsung Health 营养数据)。
 *
 * Samsung Health 的 NUTRITION 数据类型每条记录代表一次饮食摄入,
 * 含食物名称(TITLE)、餐次(MEAL_TYPE)、热量及各营养素。
 * 此类只保留 UI 需要的字段, 供 Life 餐食 Tab 展示"今天吃了什么"。
 *
 * @property title 食物名称(如"米饭""鸡蛋"), 可能为空(SDK 未填)
 * @property mealType 餐次类型名称(如 BREAKFAST/LUNCH/DINNER/SNACK), 未知时为原始枚举名或 null
 * @property calories 该条记录的热量(kcal)
 * @property protein 蛋白质(g), 可能为空
 * @property carbs 碳水(g), 可能为空
 * @property fat 脂肪(g), 可能为空
 * @property startTime 该条记录的时间
 */
data class NutritionEntry(
    val title: String?,
    val mealType: String?,
    val calories: Float?,
    val protein: Float?,
    val carbs: Float?,
    val fat: Float?,
    val startTime: Instant,
    // ---- 三星健康 NUTRITION 完整营养素字段(均为可空, 未填则 null) ----
    val saturatedFat: Float? = null,   // 饱和脂肪(g)
    val transFat: Float? = null,       // 反式脂肪(g)
    val monosaturatedFat: Float? = null, // 单不饱和脂肪(g)
    val polysaturatedFat: Float? = null, // 多不饱和脂肪(g)
    val dietaryFiber: Float? = null,   // 膳食纤维(g)
    val sugar: Float? = null,          // 糖(g)
    val cholesterol: Float? = null,    // 胆固醇(mg)
    val sodium: Float? = null,         // 钠(mg)
    val potassium: Float? = null,      // 钾(mg)
    val vitaminA: Float? = null,       // 维生素A
    val vitaminC: Float? = null,       // 维生素C
    val calcium: Float? = null,        // 钙(mg)
    val iron: Float? = null            // 铁(mg)
)

/**
 * 单次运动会话快照。
 *
 * @property startTime 开始时间
 * @property endTime 结束时间
 * @property durationMinutes 持续时长(分钟)
 * @property distanceKm 距离(km),可能为空(如力量训练)
 * @property calories 消耗热量(kcal)
 * @property exerciseTypeName 运动类型名称
 * @property customTitle 用户自定义标题,可能为空
 */
data class ExerciseSnapshot(
    val startTime: Instant,
    val endTime: Instant,
    val durationMinutes: Long,
    val distanceKm: Float?,
    val calories: Float,
    val exerciseTypeName: String,
    val customTitle: String?
)

/**
 * 睡眠各阶段时长(分钟)。
 *
 * 各字段独立可空: 某阶段无记录时为 null。
 * 与 Samsung Health SDK 的 [DataType.SleepType.StageType] 对应。
 *
 * @property awake 清醒阶段时长
 * @property light 浅睡阶段时长
 * @property deep 深睡阶段时长
 * @property rem REM(快速眼动)阶段时长
 */
data class SleepStageMinutes(
    val awake: Long? = null,
    val light: Long? = null,
    val deep: Long? = null,
    val rem: Long? = null
)

/**
 * Samsung Health 读取的健康数据快照。
 *
 * 字段可空: Samsung Health 中可能没有对应数据(用户从未测过),
 * 读取时返回 null 表示该类型无记录。
 *
 * @property steps 今日步数 (聚合值,由手表端 Health Services 实时采集,本类不再读取)
 * @property heartRate 最新心率
 * @property heartRateTimestamp 心率测量时间
 * @property sleepMinutes 昨晚睡眠时长 (分钟)
 * @property sleepStartTime 睡眠开始时间
 * @property sleepEndTime 睡眠结束时间
 * @property sleepStageMinutes 各睡眠阶段时长 (分钟): AWAKE/LIGHT/DEEP/REM, null 表示该阶段无记录
 * @property sleepScore 睡眠得分 (0-100)
 * @property weightKg 体重 (kg)
 * @property heightM 身高 (m, SDK 返回 cm,本类已转换)
 * @property bodyFatPercent 体脂率 (0-1, SDK 返回百分比数值,本类已除 100)
 * @property skeletalMusclePercent 骨骼肌率 (0-1, SDK 返回百分比数值,本类已除 100)
 * @property basalMetabolicRate 基础代谢率 (kcal)
 * @property bmi 体重指数
 * @property muscleMass 肌肉量 (kg)
 * @property bodyFatMass 脂肪量 (kg)
 * @property fatFreeMass 去脂体重 (kg)
 * @property skeletalMuscleMass 骨骼肌量 (kg)
 * @property totalBodyWater 总体水分 (kg)
 * @property systolic 收缩压 (mmHg)
 * @property diastolic 舒张压 (mmHg)
 * @property bodyTemperature 体温 (°C)
 * @property bloodGlucose 血糖 (mmol/L)
 *
 * 新增字段:
 * @property skinTemperature 皮肤温度 (°C)
 * @property skinTemperatureMin 皮肤温度最低值 (°C)
 * @property skinTemperatureMax 皮肤温度最高值 (°C)
 * @property bloodOxygen 血氧饱和度 (0-1)
 * @property bloodOxygenMin 血氧最低值 (0-1)
 * @property bloodOxygenMax 血氧最高值 (0-1)
 * @property floorsClimbed 今日爬楼层数
 * @property waterIntakeMl 今日饮水量 (ml)
 * @property nutritionCalories 今日摄入热量 (kcal)
 * @property nutritionProtein 今日蛋白质摄入 (g)
 * @property nutritionCarbs 今日碳水摄入 (g)
 * @property nutritionFat 今日脂肪摄入 (g)
 * @property exerciseSessions 今日运动会话列表
 * @property sleepApneaSign 睡眠呼吸暂停征兆(枚举字符串)
 * @property irregularHeartRhythmStatus 心律不齐通知状态(枚举字符串)
 * @property energyScore 今日能量评分
 * @property stepsToday 今日总步数 (聚合查询)
 * @property activeCaloriesBurned 今日活动消耗热量 (kcal)
 * @property totalCaloriesBurned 今日总消耗热量 (kcal)
 * @property activeTimeMinutes 今日活动时长 (分钟)
 * @property totalDistanceKm 今日总距离 (km)
 * @property sleepGoalBedTime 睡眠目标就寝时间
 * @property sleepGoalWakeTime 睡眠目标起床时间
 * @property stepsGoal 步数目标
 * @property activeCaloriesGoal 活动热量目标 (kcal)
 * @property activeTimeGoalMinutes 活动时长目标 (分钟)
 * @property waterIntakeGoalMl 饮水目标 (ml)
 * @property nutritionGoalCalories 热量摄入目标 (kcal)
 */
data class SamsungHealthSnapshot(
    val steps: Long? = null,
    val heartRate: Int? = null,
    val heartRateTimestamp: Instant? = null,
    val sleepMinutes: Long? = null,
    val sleepStartTime: Instant? = null,
    val sleepEndTime: Instant? = null,
    // 新增: 睡眠阶段时长 (分钟), null 表示该阶段无记录
    val sleepStageMinutes: SleepStageMinutes? = null,
    // 新增: 睡眠得分 (0-100, SDK 原始字段 SLEEP_SCORE)
    val sleepScore: Int? = null,
    val weightKg: Float? = null,
    val heightM: Float? = null,
    val bodyFatPercent: Float? = null,
    val skeletalMusclePercent: Float? = null,
    val basalMetabolicRate: Int? = null,
    val bmi: Float? = null,
    // 新增: 身体成分扩展字段(SDK 原始值,未做单位转换)
    val muscleMass: Float? = null,
    val bodyFatMass: Float? = null,
    val fatFreeMass: Float? = null,
    val skeletalMuscleMass: Float? = null,
    val totalBodyWater: Float? = null,
    val systolic: Float? = null,
    val diastolic: Float? = null,
    val bodyTemperature: Float? = null,
    val bloodGlucose: Float? = null,
    // 新增: 皮肤温度
    val skinTemperature: Float? = null,
    val skinTemperatureMin: Float? = null,
    val skinTemperatureMax: Float? = null,
    // 新增: 血氧
    val bloodOxygen: Float? = null,
    val bloodOxygenMin: Float? = null,
    val bloodOxygenMax: Float? = null,
    // 新增: 爬楼/饮水/营养
    val floorsClimbed: Float? = null,
    val waterIntakeMl: Float? = null,
    val nutritionCalories: Float? = null,
    val nutritionProtein: Float? = null,
    val nutritionCarbs: Float? = null,
    val nutritionFat: Float? = null,
    // 新增: 微量营养素总量(有值才上报)
    val nutritionSaturatedFat: Float? = null,
    val nutritionTransFat: Float? = null,
    val nutritionDietaryFiber: Float? = null,
    val nutritionSugar: Float? = null,
    val nutritionCholesterol: Float? = null,
    val nutritionSodium: Float? = null,
    val nutritionPotassium: Float? = null,
    val nutritionVitaminA: Float? = null,
    val nutritionVitaminC: Float? = null,
    val nutritionCalcium: Float? = null,
    val nutritionIron: Float? = null,
    // 新增: 运动会话
    val exerciseSessions: List<ExerciseSnapshot> = emptyList(),
    // 新增: 今日逐条饮食记录(食物名/餐次/热量), 来自 Samsung Health NUTRITION 的 TITLE+MEAL_TYPE
    val nutritionEntries: List<NutritionEntry> = emptyList(),
    // 新增: 今日逐条饮水记录(时间+量), 来自 Samsung Health WATER_INTAKE
    val waterIntakeEntries: List<WaterIntakeEntry> = emptyList(),
    // 新增: 睡眠呼吸暂停 / 心律不齐
    val sleepApneaSign: String? = null,
    val irregularHeartRhythmStatus: String? = null,
    // 新增: 能量评分
    val energyScore: Float? = null,
    // 新增: 今日活动聚合
    val stepsToday: Long? = null,
    val activeCaloriesBurned: Float? = null,
    val totalCaloriesBurned: Float? = null,
    val activeTimeMinutes: Long? = null,
    val totalDistanceKm: Float? = null,
    // 新增: 各类目标
    val sleepGoalBedTime: LocalTime? = null,
    val sleepGoalWakeTime: LocalTime? = null,
    val stepsGoal: Int? = null,
    val activeCaloriesGoal: Int? = null,
    val activeTimeGoalMinutes: Long? = null,
    val waterIntakeGoalMl: Float? = null,
    val nutritionGoalCalories: Float? = null,
    val collectedAt: Instant = Instant.now()
)

/**
 * 将健康数据快照转为后端同步用的 JSON。
 *
 * 仅包含非 null 字段,避免后端接收大量 null 覆盖已有数据。
 * ViewModel 和 Service 共用此函数,确保字段一致。
 */
fun SamsungHealthSnapshot.toSyncJson(): JsonObject = buildJsonObject {
    put("source", "samsung_health")
    putNotNull("heart_rate", heartRate)
    putNotNull("heart_rate_timestamp", heartRateTimestamp?.toString())
    putNotNull("weight_kg", weightKg)
    putNotNull("height_m", heightM)
    putNotNull("body_fat_percent", bodyFatPercent)
    putNotNull("skeletal_muscle_percent", skeletalMusclePercent)
    putNotNull("basal_metabolic_rate", basalMetabolicRate)
    putNotNull("sleep_minutes", sleepMinutes)
    putNotNull("sleep_start_time", sleepStartTime?.toString())
    putNotNull("sleep_end_time", sleepEndTime?.toString())
    putNotNull("sleep_stage_awake_minutes", sleepStageMinutes?.awake)
    putNotNull("sleep_stage_light_minutes", sleepStageMinutes?.light)
    putNotNull("sleep_stage_deep_minutes", sleepStageMinutes?.deep)
    putNotNull("sleep_stage_rem_minutes", sleepStageMinutes?.rem)
    putNotNull("sleep_score", sleepScore)
    putNotNull("blood_pressure_systolic", systolic)
    putNotNull("blood_pressure_diastolic", diastolic)
    putNotNull("body_temperature", bodyTemperature)
    putNotNull("blood_glucose", bloodGlucose)
    putNotNull("muscle_mass", muscleMass)
    putNotNull("body_fat_mass", bodyFatMass)
    putNotNull("fat_free_mass", fatFreeMass)
    putNotNull("skeletal_muscle_mass", skeletalMuscleMass)
    putNotNull("total_body_water", totalBodyWater)
    putNotNull("skin_temperature", skinTemperature)
    putNotNull("blood_oxygen", bloodOxygen)
    putNotNull("floors_climbed", floorsClimbed)
    putNotNull("water_intake_ml", waterIntakeMl)
    putNotNull("nutrition_calories", nutritionCalories)
    putNotNull("nutrition_protein", nutritionProtein)
    putNotNull("nutrition_carbs", nutritionCarbs)
    putNotNull("nutrition_fat", nutritionFat)
    putNotNull("nutrition_saturated_fat", nutritionSaturatedFat)
    putNotNull("nutrition_trans_fat", nutritionTransFat)
    putNotNull("nutrition_dietary_fiber", nutritionDietaryFiber)
    putNotNull("nutrition_sugar", nutritionSugar)
    putNotNull("nutrition_cholesterol", nutritionCholesterol)
    putNotNull("nutrition_sodium", nutritionSodium)
    putNotNull("nutrition_potassium", nutritionPotassium)
    putNotNull("nutrition_vitamin_a", nutritionVitaminA)
    putNotNull("nutrition_vitamin_c", nutritionVitaminC)
    putNotNull("nutrition_calcium", nutritionCalcium)
    putNotNull("nutrition_iron", nutritionIron)
    putNotNull("sleep_apnea_sign", sleepApneaSign)
    putNotNull("irregular_heart_rhythm", irregularHeartRhythmStatus)
    putNotNull("energy_score", energyScore)
    putNotNull("steps_today", stepsToday)
    putNotNull("active_calories_burned", activeCaloriesBurned)
    putNotNull("total_calories_burned", totalCaloriesBurned)
    putNotNull("active_time_minutes", activeTimeMinutes)
    putNotNull("total_distance_km", totalDistanceKm)
    putNotNull("sleep_goal_bed_time", sleepGoalBedTime?.toString())
    putNotNull("sleep_goal_wake_time", sleepGoalWakeTime?.toString())
    putNotNull("steps_goal", stepsGoal)
    putNotNull("active_calories_goal", activeCaloriesGoal)
    putNotNull("active_time_goal_minutes", activeTimeGoalMinutes)
    putNotNull("water_intake_goal_ml", waterIntakeGoalMl)
    putNotNull("nutrition_goal_calories", nutritionGoalCalories)
    // 逐条饮食记录(食物名/餐次/热量/时间), 供后端 AI 查询"今天吃了什么"
    if (nutritionEntries.isNotEmpty()) {
        put("nutrition_entries", buildJsonArray {
            nutritionEntries.forEach { e ->
                add(buildJsonObject {
                    put("title", e.title)
                    put("meal_type", e.mealType)
                    put("calories", e.calories)
                    put("protein", e.protein)
                    put("carbs", e.carbs)
                    put("fat", e.fat)
                    put("time", e.startTime.toString())
                    // 完整营养素字段, 仅放非空值
                    putNotNull("saturated_fat", e.saturatedFat)
                    putNotNull("trans_fat", e.transFat)
                    putNotNull("monosaturated_fat", e.monosaturatedFat)
                    putNotNull("polysaturated_fat", e.polysaturatedFat)
                    putNotNull("dietary_fiber", e.dietaryFiber)
                    putNotNull("sugar", e.sugar)
                    putNotNull("cholesterol", e.cholesterol)
                    putNotNull("sodium", e.sodium)
                    putNotNull("potassium", e.potassium)
                    putNotNull("vitamin_a", e.vitaminA)
                    putNotNull("vitamin_c", e.vitaminC)
                    putNotNull("calcium", e.calcium)
                    putNotNull("iron", e.iron)
                })
            }
        })
    }
    // 逐条饮水记录(时间+量), 供后端 AI 查询"今天几点喝了多少水"
    if (waterIntakeEntries.isNotEmpty()) {
        put("water_intake_entries", buildJsonArray {
            waterIntakeEntries.forEach { e ->
                add(buildJsonObject {
                    put("amount_ml", e.amountMl)
                    put("time", e.startTime.toString())
                })
            }
        })
    }
    put("collected_at", Instant.now().toString())
}

/** JsonObject Builder 扩展: 仅当 value 非 null 时 put */
private fun kotlinx.serialization.json.JsonObjectBuilder.putNotNull(
    key: String,
    value: Any?
) {
    if (value == null) return
    when (value) {
        is Number -> put(key, value)
        is Boolean -> put(key, value)
        is String -> put(key, value)
        else -> put(key, value.toString())
    }
}
