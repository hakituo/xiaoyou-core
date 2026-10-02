package com.aveline.ai.mobile.presentation.chat

import org.junit.Assert.assertEquals
import org.junit.Test

class ImageMessageTextTest {

    @Test
    fun `识别成功时把描述发给后端`() {
        assertEquals(
            "[图像识别结果：一只猫]",
            ImageMessageText.build("/output/image/uploads/a.jpg", "", "一只猫")
        )
    }

    @Test
    fun `识别成功且带文案时描述在前文案在后`() {
        assertEquals(
            "[图像识别结果：一只猫]\n帮我配个文案",
            ImageMessageText.build("/output/image/uploads/a.jpg", "帮我配个文案", "一只猫")
        )
    }

    @Test
    fun `识别失败时回退成图片地址`() {
        assertEquals(
            "[图片: /output/image/uploads/a.jpg]",
            ImageMessageText.build("/output/image/uploads/a.jpg", "", null)
        )
    }

    @Test
    fun `识别失败且带文案时回退地址在前文案在后`() {
        assertEquals(
            "[图片: /output/image/uploads/a.jpg]\n看看这张",
            ImageMessageText.build("/output/image/uploads/a.jpg", "看看这张", "   ")
        )
    }

    @Test
    fun `视觉提示词非空`() {
        org.junit.Assert.assertTrue(ImageMessageText.VISION_PROMPT.isNotBlank())
    }
}
