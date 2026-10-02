package com.aveline.ai.mobile.data.samsung

import android.util.Log
import com.samsung.android.sdk.health.data.HealthDataStore
import com.samsung.android.sdk.health.data.data.Field
import com.samsung.android.sdk.health.data.data.HealthDataPoint
import com.samsung.android.sdk.health.data.data.entries.ExerciseSession
import com.samsung.android.sdk.health.data.request.DataType
import com.samsung.android.sdk.health.data.request.DataTypes
import com.samsung.android.sdk.health.data.request.LocalTimeFilter
import javax.inject.Inject
import javax.inject.Singleton

/** 营养摄入汇总(今日累计,单位: kcal/g/mg)。 */
internal data class NutritionSummary(
    val calories: Float,
    val protein: Float,
    val carbs: Float,
    val fat: Float,
    val saturatedFat: Float? = null,
    val transFat: Float? = null,
    val dietaryFiber: Float? = null,
    val sugar: Float? = null,
    val cholesterol: Float? = null,
    val sodium: Float? = null,
    val potassium: Float? = null,
    val vitaminA: Float? = null,
    val vitaminC: Float? = null,
    val calcium: Float? = null,
    val iron: Float? = null
)

/**
 * 饮食、饮水与运动会话读取器(今日逐条明细 + 今日累计)。
 *
 * 这些数据只在用户手动记录时变化,由后台中频通道读取, 见 SamsungHealthSyncController。
 *
 * 方法统一为 internal: 对外只通过 [SamsungHealthReader] 门面暴露。
 */
@Singleton
class SamsungHealthDietActivityReader @Inject constructor(
    private val store: HealthDataStore
) {
    /**
     * 读取今日饮水量(ml,所有记录求和)。
     */
    internal suspend fun readWaterIntakeToday(): Float? = runCatching {
        val (start, end) = todayLocalTimeRange()
        val request = DataTypes.WATER_INTAKE.readDataRequestBuilder
            .setLocalTimeFilter(LocalTimeFilter.of(start, end))
            .build()
        val response = store.readData(request)
        val sum = response.dataList.mapNotNull { it.getValue<Float>(DataType.WaterIntakeType.AMOUNT) }.sum()
        sum.takeIf { it > 0f }
    }.onFailure { e ->
        Log.w(TAG, "读取饮水量失败: ${e.message}")
    }.getOrNull()

    /**
     * 读取今日逐条饮水记录(时间+量), 转换为 WaterIntakeEntry 列表。
     *
     * Samsung Health 的 WATER_INTAKE 数据类型每条记录代表一次饮水,
     * 含 AMOUNT(量, ml) 和 startTime。供 UI 展示"几点喝了多少水"。
     */
    internal suspend fun readWaterIntakeEntries(): List<WaterIntakeEntry> = runCatching {
        val (start, end) = todayLocalTimeRange()
        val request = DataTypes.WATER_INTAKE.readDataRequestBuilder
            .setLocalTimeFilter(LocalTimeFilter.of(start, end))
            .build()
        val response = store.readData(request)
        response.dataList.map { dp ->
            WaterIntakeEntry(
                amountMl = dp.getValue<Float>(DataType.WaterIntakeType.AMOUNT) ?: 0f,
                startTime = dp.startTime
            )
        }
    }.onFailure { e ->
        Log.w(TAG, "读取饮水记录失败: ${e.message}")
    }.getOrDefault(emptyList())

    /**
     * 读取今日营养摄入(热量/蛋白质/碳水/脂肪,分别对所有记录求和)。
     */
    internal suspend fun readNutritionToday(): NutritionSummary? = runCatching {
        val (start, end) = todayLocalTimeRange()
        val request = DataTypes.NUTRITION.readDataRequestBuilder
            .setLocalTimeFilter(LocalTimeFilter.of(start, end))
            .build()
        val response = store.readData(request)
        val list = response.dataList
        if (list.isEmpty()) null
        else NutritionSummary(
            calories = list.mapNotNull { it.getValue<Float>(DataType.NutritionType.CALORIES) }.sum(),
            protein = list.mapNotNull { it.getValue<Float>(DataType.NutritionType.PROTEIN) }.sum(),
            carbs = list.mapNotNull { it.getValue<Float>(DataType.NutritionType.CARBOHYDRATE) }.sum(),
            fat = list.mapNotNull { it.getValue<Float>(DataType.NutritionType.TOTAL_FAT) }.sum(),
            saturatedFat = sumNotNull(list, DataType.NutritionType.SATURATED_FAT),
            transFat = sumNotNull(list, DataType.NutritionType.TRANS_FAT),
            dietaryFiber = sumNotNull(list, DataType.NutritionType.DIETARY_FIBER),
            sugar = sumNotNull(list, DataType.NutritionType.SUGAR),
            cholesterol = sumNotNull(list, DataType.NutritionType.CHOLESTEROL),
            sodium = sumNotNull(list, DataType.NutritionType.SODIUM),
            potassium = sumNotNull(list, DataType.NutritionType.POTASSIUM),
            vitaminA = sumNotNull(list, DataType.NutritionType.VITAMIN_A),
            vitaminC = sumNotNull(list, DataType.NutritionType.VITAMIN_C),
            calcium = sumNotNull(list, DataType.NutritionType.CALCIUM),
            iron = sumNotNull(list, DataType.NutritionType.IRON)
        )
    }.onFailure { e ->
        Log.w(TAG, "读取营养摄入失败: ${e.message}")
    }.getOrNull()

    /** 对营养数据点列表的某个字段求和; 全为 null 则返回 null(不展示)。 */
    private fun sumNotNull(
        list: List<HealthDataPoint>,
        field: Field<Float>
    ): Float? {
        val values = list.mapNotNull { it.getValue<Float>(field) }
        return if (values.isEmpty()) null else values.sum()
    }

    /**
     * 读取今日逐条饮食记录(食物名/餐次/热量), 转换为 NutritionEntry 列表。
     *
     * Samsung Health 的 NUTRITION 数据类型每条记录代表一次饮食摄入,
     * 含 TITLE(食物名)、MEAL_TYPE(餐次枚举)、CALORIES 等。
     * 此方法保留逐条信息, 供 UI 展示"今天吃了什么"。
     *
     * 同一次 readData 既出总量也出逐条, 避免重复查询。
     */
    internal suspend fun readNutritionEntries(): List<NutritionEntry> = runCatching {
        val (start, end) = todayLocalTimeRange()
        val request = DataTypes.NUTRITION.readDataRequestBuilder
            .setLocalTimeFilter(LocalTimeFilter.of(start, end))
            .build()
        val response = store.readData(request)
        response.dataList.map { dp ->
            NutritionEntry(
                title = dp.getValue<String>(DataType.NutritionType.TITLE),
                mealType = dp.getValue<DataType.NutritionType.MealType>(DataType.NutritionType.MEAL_TYPE)?.name,
                calories = dp.getValue<Float>(DataType.NutritionType.CALORIES),
                protein = dp.getValue<Float>(DataType.NutritionType.PROTEIN),
                carbs = dp.getValue<Float>(DataType.NutritionType.CARBOHYDRATE),
                fat = dp.getValue<Float>(DataType.NutritionType.TOTAL_FAT),
                startTime = dp.startTime,
                saturatedFat = dp.getValue<Float>(DataType.NutritionType.SATURATED_FAT),
                transFat = dp.getValue<Float>(DataType.NutritionType.TRANS_FAT),
                monosaturatedFat = dp.getValue<Float>(DataType.NutritionType.MONOSATURATED_FAT),
                polysaturatedFat = dp.getValue<Float>(DataType.NutritionType.POLYSATURATED_FAT),
                dietaryFiber = dp.getValue<Float>(DataType.NutritionType.DIETARY_FIBER),
                sugar = dp.getValue<Float>(DataType.NutritionType.SUGAR),
                cholesterol = dp.getValue<Float>(DataType.NutritionType.CHOLESTEROL),
                sodium = dp.getValue<Float>(DataType.NutritionType.SODIUM),
                potassium = dp.getValue<Float>(DataType.NutritionType.POTASSIUM),
                vitaminA = dp.getValue<Float>(DataType.NutritionType.VITAMIN_A),
                vitaminC = dp.getValue<Float>(DataType.NutritionType.VITAMIN_C),
                calcium = dp.getValue<Float>(DataType.NutritionType.CALCIUM),
                iron = dp.getValue<Float>(DataType.NutritionType.IRON)
            )
        }
    }.onFailure { e ->
        Log.w(TAG, "读取饮食记录失败: ${e.message}")
    }.getOrDefault(emptyList())

    /**
     * 读取今日所有运动会话,转换为 ExerciseSnapshot 列表。
     */
    internal suspend fun readExerciseSessionsToday(): List<ExerciseSnapshot> = runCatching {
        val (start, end) = todayLocalTimeRange()
        val request = DataTypes.EXERCISE.readDataRequestBuilder
            .setLocalTimeFilter(LocalTimeFilter.of(start, end))
            .build()
        val response = store.readData(request)
        val sessions = response.dataList.flatMap { dp ->
            dp.getValue<List<ExerciseSession>>(DataType.ExerciseType.SESSIONS) ?: emptyList()
        }
        sessions.map { it.toSnapshot() }
    }.onFailure { e ->
        Log.w(TAG, "读取运动会话失败: ${e.message}")
    }.getOrDefault(emptyList())

    /**
     * ExerciseSession 转 ExerciseSnapshot。
     * distance 单位由米转 km(若 SDK 返回为空则保持 null)。
     */
    private fun ExerciseSession.toSnapshot(): ExerciseSnapshot = ExerciseSnapshot(
        startTime = startTime,
        endTime = endTime,
        durationMinutes = duration.toMinutes(),
        distanceKm = distance?.let { it / 1000f },
        calories = calories,
        exerciseTypeName = exerciseType.name,
        customTitle = customTitle
    )

    companion object {
        private const val TAG = "SamsungHealthDiet"
    }
}
