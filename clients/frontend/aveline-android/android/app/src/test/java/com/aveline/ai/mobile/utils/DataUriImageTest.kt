package com.aveline.ai.mobile.utils

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

/**
 * 覆盖 data URI 解码：后端表情包以 data URI 下发，Coil 2.x 无法直接加载，
 * 必须解码成 ByteArray 才能显示（否则消息气泡显示破图占位）。
 */
class DataUriImageTest {

    private fun dataUrl(bytes: ByteArray, mime: String = "image/jpeg"): String {
        val b64 = Base64.getEncoder().encodeToString(bytes)
        return "data:$mime;base64,$b64"
    }

    @Test
    fun `标准 data URI 解码出原始字节`() {
        val raw = byteArrayOf(0x11, 0x22, 0x33, 0x44, 0x55)
        assertArrayEquals(raw, DataUriImage.decode(dataUrl(raw)))
    }

    @Test
    fun `png 与其它 mime 同样可解码`() {
        val raw = byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47)
        assertArrayEquals(raw, DataUriImage.decode(dataUrl(raw, "image/png")))
    }

    @Test
    fun `带换行的 base64 仍能解码`() {
        val raw = byteArrayOf(0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08)
        val b64 = Base64.getEncoder().encodeToString(raw)
        val wrapped = "data:image/jpeg;base64,\n${b64.take(4)}\n${b64.drop(4)}\n"
        assertArrayEquals(raw, DataUriImage.decode(wrapped))
    }

    @Test
    fun `普通 http 地址不解码`() {
        assertNull(DataUriImage.decode("http://192.168.1.2:8000/output/image/a.png"))
    }

    @Test
    fun `相对路径不解码`() {
        assertNull(DataUriImage.decode("/output/image/a.png"))
    }

    @Test
    fun `非 base64 的 data URI 返回 null`() {
        assertNull(DataUriImage.decode("data:image/svg+xml,%3Csvg%3E%3C/svg%3E"))
    }

    @Test
    fun `payload 为空返回 null`() {
        assertNull(DataUriImage.decode("data:image/jpeg;base64,"))
    }

    @Test
    fun `非法 base64 返回 null 而不抛异常`() {
        assertNull(DataUriImage.decode("data:image/jpeg;base64,@@@@"))
    }

    @Test
    fun `isDataUri 忽略大小写与前导空白`() {
        assertTrue(DataUriImage.isDataUri("data:image/jpeg;base64,AAA="))
        assertTrue(DataUriImage.isDataUri("DATA:image/jpeg;base64,AAA="))
        assertTrue(DataUriImage.isDataUri("  data:image/jpeg;base64,AAA="))
        assertFalse(DataUriImage.isDataUri("http://example.com/a.png"))
        assertFalse(DataUriImage.isDataUri(""))
    }

    @Test
    fun `解码结果就是后端真实下发的那串 base64`() {
        // 后端 _encode_image_to_data_url: base64.b64encode(...).decode("utf-8")
        val raw = "aveline".toByteArray()
        val url = dataUrl(raw)
        assertEquals("data:image/jpeg;base64,YXZlbGluZQ==", url)
        assertEquals("aveline", String(DataUriImage.decode(url)!!))
    }
}
