package com.aveline.ai.mobile.utils

import org.junit.Assert.assertEquals
import org.junit.Test

class ImageUrlResolverTest {

    @Test
    fun `data uri 保持原样`() {
        val url = "data:image/jpeg;base64,/9j/4AAQ..."
        assertEquals(url, ImageUrlResolver.resolve("http://192.168.1.2:8000", url))
    }

    @Test
    fun `http 绝对地址保持原样`() {
        val url = "http://example.com/output/image/a.png"
        assertEquals(url, ImageUrlResolver.resolve("http://192.168.1.2:8000", url))
    }

    @Test
    fun `https 绝对地址保持原样`() {
        val url = "https://example.com/output/image/a.png"
        assertEquals(url, ImageUrlResolver.resolve("http://192.168.1.2:8000", url))
    }

    @Test
    fun `斜杠开头的相对路径拼接后端地址`() {
        assertEquals(
            "http://192.168.1.2:8000/output/image/a.png",
            ImageUrlResolver.resolve("192.168.1.2:8000", "/output/image/a.png")
        )
    }

    @Test
    fun `无斜杠开头的相对路径自动补斜杠`() {
        assertEquals(
            "http://192.168.1.2:8000/output/image/a.png",
            ImageUrlResolver.resolve("192.168.1.2:8000", "output/image/a.png")
        )
    }

    @Test
    fun `后端地址已带协议时不重复添加`() {
        assertEquals(
            "http://192.168.1.2:8000/output/image/a.png",
            ImageUrlResolver.resolve("http://192.168.1.2:8000", "/output/image/a.png")
        )
    }

    @Test
    fun `后端地址为空时原样返回相对路径`() {
        assertEquals(
            "/output/image/a.png",
            ImageUrlResolver.resolve("", "/output/image/a.png")
        )
    }

    @Test
    fun `去除图片地址首尾空白`() {
        assertEquals(
            "http://192.168.1.2:8000/output/image/a.png",
            ImageUrlResolver.resolve("192.168.1.2:8000", "  /output/image/a.png  ")
        )
    }
}
