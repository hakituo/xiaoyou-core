package com.aveline.ai.mobile.presentation.utils

import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * EmotionResolver.parseColor 回归测试
 *
 * 重点验证 P0-5 修复:6 位 hex 颜色不应被解析为完全透明(alpha=0)。
 * 修复前 `Color(color)` 把 0x10B981L 当 ARGB,alpha=0x00 完全透明;
 * 修复后 `Color(color or 0xFF000000L)` 补全 alpha=0xFF。
 */
class EmotionResolverParseColorTest {

    @Test
    fun `6 位 hex 颜色不应解析为完全透明`() {
        // 经典绿色 #10B981,修复前 alpha=0 完全透明
        val color = EmotionResolver.parseColor("#10B981")
        assertEquals("6位hex alpha 必须为 1.0(不透明)", 1.0f, color.alpha, 0.001f)
    }

    @Test
    fun `6 位 hex 颜色 RGB 通道应正确解析`() {
        val color = EmotionResolver.parseColor("#10B981")
        // 0x10=16, 0xB9=185, 0x81=129; 转 0-1 浮点
        assertEquals(16f / 255f, color.red, 0.001f)
        assertEquals(185f / 255f, color.green, 0.001f)
        assertEquals(129f / 255f, color.blue, 0.001f)
    }

    @Test
    fun `6 位 hex 不带井号也能解析`() {
        val withHash = EmotionResolver.parseColor("#FF8C00")
        val withoutHash = EmotionResolver.parseColor("FF8C00")
        assertEquals(withHash, withoutHash)
        assertEquals(1.0f, withHash.alpha, 0.001f)
    }

    @Test
    fun `8 位 hex 颜色保持原有 alpha`() {
        // 0x8010B981: alpha=0x80=128, RGB=10B981
        val color = EmotionResolver.parseColor("#8010B981")
        assertEquals(128f / 255f, color.alpha, 0.001f)
        assertEquals(16f / 255f, color.red, 0.001f)
        assertEquals(185f / 255f, color.green, 0.001f)
        assertEquals(129f / 255f, color.blue, 0.001f)
    }

    @Test
    fun `非法长度 hex 回退中性灰`() {
        // 长度 5/7 等非法值回退默认色 0xFF6B7280
        val color = EmotionResolver.parseColor("#12345")
        assertEquals(Color(0xFF6B7280), color)
    }

    @Test
    fun `非法 hex 不抛异常且回退中性灰`() {
        val color = EmotionResolver.parseColor("not-a-color")
        assertEquals(Color(0xFF6B7280), color)
    }

    @Test
    fun `所有 EmotionType 颜色都不透明`() {
        // 间接验证 EmotionType.color 配置本身没问题
        EmotionResolver.EmotionType.values().forEach { type ->
            assertEquals(
                "情绪 $type 颜色应不透明",
                1.0f,
                type.color.alpha,
                0.001f
            )
        }
    }
}
