package com.aveline.ai.mobile.presentation.health

import com.aveline.ai.mobile.data.samsung.SamsungHealthReader
import com.aveline.ai.mobile.data.wear.WearDataSource
import com.aveline.ai.mobile.domain.repository.ContextRepository
import com.aveline.ai.mobile.domain.repository.HealthRepository
import com.aveline.ai.mobile.util.MainDispatcherRule
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test

/**
 * DailyDataViewModel.recordDrink 回归测试
 *
 * 重点验证 P0-9 修复:recordDrink 应直接传 amount_ml(毫升)给后端,
 * 而不是 units(250ml/单位)。
 *
 * 修复前: UI 传 200/300/500ml,NavGraph 做 ml/250 转 units,
 *   200ml→0→coerceAtLeast(1)=1→后端记 250ml(多记 50ml),
 *   300ml→1→后端记 250ml(少记 50ml)。
 * 修复后: 直接传 amount_ml,200ml→200ml,精确无误。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class DailyDataViewModelDrinkTest {

    @get:Rule
    val mainDispatcherRule = MainDispatcherRule()

    @Test
    fun `recordDrink 传 amount_ml 而非 units`() = runTest {
        val mockRepo = mockk<HealthRepository>(relaxed = true)
        val payloadSlot = slot<JsonObject>()
        coEvery { mockRepo.recordDailyDrink(capture(payloadSlot)) } returns Result.success(
            buildJsonObject { put("message", "ok") }
        )
        // relaxed=true 会让 refreshData 内部调用返回默认值,无需额外配置

        val viewModel = DailyDataViewModel(
            mockRepo,
            contextRepository = mockk<ContextRepository>(relaxed = true),
            wearDataSource = mockk<WearDataSource>(relaxed = true),
            samsungHealthReader = mockk<SamsungHealthReader>(relaxed = true)
        )
        advanceUntilIdle()

        viewModel.recordDrink(amountMl = 300)
        advanceUntilIdle()

        val payload = payloadSlot.captured
        // 修复后应包含 amount_ml=300,而非 units
        assertEquals(300, payload["amount_ml"]!!.jsonPrimitive.intOrNull)
        // 不应再传 units
        assertNull(payload["units"])
    }

    @Test
    fun `recordDrink 200ml 精确传递不被放大`() = runTest {
        val mockRepo = mockk<HealthRepository>(relaxed = true)
        val payloadSlot = slot<JsonObject>()
        coEvery { mockRepo.recordDailyDrink(capture(payloadSlot)) } returns Result.success(
            buildJsonObject { put("message", "ok") }
        )

        val viewModel = DailyDataViewModel(
            mockRepo,
            contextRepository = mockk<ContextRepository>(relaxed = true),
            wearDataSource = mockk<WearDataSource>(relaxed = true),
            samsungHealthReader = mockk<SamsungHealthReader>(relaxed = true)
        )
        advanceUntilIdle()

        // 修复前:200/250=0→coerceAtLeast(1)=1→后端 units=1→记 250ml(多50ml)
        // 修复后:直接传 amount_ml=200
        viewModel.recordDrink(amountMl = 200)
        advanceUntilIdle()

        assertEquals(200, payloadSlot.captured["amount_ml"]!!.jsonPrimitive.intOrNull)
    }

    @Test
    fun `recordDrink 默认 250ml`() = runTest {
        val mockRepo = mockk<HealthRepository>(relaxed = true)
        val payloadSlot = slot<JsonObject>()
        coEvery { mockRepo.recordDailyDrink(capture(payloadSlot)) } returns Result.success(
            buildJsonObject { put("message", "ok") }
        )

        val viewModel = DailyDataViewModel(
            mockRepo,
            contextRepository = mockk<ContextRepository>(relaxed = true),
            wearDataSource = mockk<WearDataSource>(relaxed = true),
            samsungHealthReader = mockk<SamsungHealthReader>(relaxed = true)
        )
        advanceUntilIdle()

        viewModel.recordDrink()
        advanceUntilIdle()

        assertEquals(250, payloadSlot.captured["amount_ml"]!!.jsonPrimitive.intOrNull)
    }

    @Test
    fun `recordDrink 成功时刷新数据`() = runTest {
        val mockRepo = mockk<HealthRepository>(relaxed = true)
        coEvery { mockRepo.recordDailyDrink(any()) } returns Result.success(
            buildJsonObject { put("message", "已记录喝水 300ml") }
        )

        val viewModel = DailyDataViewModel(
            mockRepo,
            contextRepository = mockk<ContextRepository>(relaxed = true),
            wearDataSource = mockk<WearDataSource>(relaxed = true),
            samsungHealthReader = mockk<SamsungHealthReader>(relaxed = true)
        )
        advanceUntilIdle()

        viewModel.recordDrink(amountMl = 300)
        advanceUntilIdle()

        // 验证 message 被设置
        assertEquals("已记录喝水 300ml", viewModel.uiState.value.message)
        // 验证 recordDailyDrink 被调用
        coVerify(atLeast = 1) { mockRepo.recordDailyDrink(any()) }
    }

    @Test
    fun `recordDrink 失败时设置 error`() = runTest {
        val mockRepo = mockk<HealthRepository>(relaxed = true)
        coEvery { mockRepo.recordDailyDrink(any()) } returns Result.failure(
            RuntimeException("网络错误")
        )

        val viewModel = DailyDataViewModel(
            mockRepo,
            contextRepository = mockk<ContextRepository>(relaxed = true),
            wearDataSource = mockk<WearDataSource>(relaxed = true),
            samsungHealthReader = mockk<SamsungHealthReader>(relaxed = true)
        )
        advanceUntilIdle()

        viewModel.recordDrink(amountMl = 300)
        advanceUntilIdle()

        assertEquals("网络错误", viewModel.uiState.value.error)
    }
}
