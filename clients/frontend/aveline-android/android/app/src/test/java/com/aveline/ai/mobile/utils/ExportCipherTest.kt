package com.aveline.ai.mobile.utils

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * ExportCipher 加解密单元测试。
 *
 * 验证: 加密-解密往返一致性、正确密码校验、错误密码拒绝、密文不可读(不以明文出现)、
 * 同明文多次加密密文不同(随机盐/IV)、格式识别、非法长度与篡改被拒。
 */
class ExportCipherTest {

    private val password = "test-password"

    @Test
    fun `加密后解密往返得到原文`() {
        val original = """{"sessions":[{"id":"s1","messages":[{"content":"你好"}]}]}""".toByteArray()
        val encrypted = ExportCipher.encrypt(original, password)
        val decrypted = ExportCipher.decrypt(encrypted, password)
        assertArrayEquals(original, decrypted)
    }

    @Test
    fun `输出以魔数头开头, 且不含任何明文片段`() {
        val original = "this-is-top-secret-content".toByteArray()
        val encrypted = ExportCipher.encrypt(original, password)
        assertTrue(ExportCipher.isEncrypted(encrypted))
        assertTrue(encrypted.startsWith(ExportCipher.MAGIC))
        // 密文(Base64)里绝不能出现明文关键字
        assertFalse(encrypted.contains("top-secret"))
    }

    @Test
    fun `错误密码解密被拒绝`() {
        val original = "my-private-diary".toByteArray()
        val encrypted = ExportCipher.encrypt(original, password)
        assertThrows(javax.crypto.BadPaddingException::class.java) {
            ExportCipher.decrypt(encrypted, "wrong-password")
        }
        // "wrong-password" 与正确密码不同即可, 再补一个空密码拒绝
        assertThrows(javax.crypto.BadPaddingException::class.java) {
            ExportCipher.decrypt(encrypted, "")
        }
    }

    @Test
    fun `同明文每次加密结果不同(随机盐导致)`() {
        val original = "same-input".toByteArray()
        val a = ExportCipher.encrypt(original, password)
        val b = ExportCipher.encrypt(original, password)
        assertNotEquals(a, b)
    }

    @Test
    fun `非加密内容识别为 false`() {
        assertFalse(ExportCipher.isEncrypted("{\"version\":1}"))
        assertFalse(ExportCipher.isEncrypted(""))
    }

    @Test
    fun `非加密格式解密被拒`() {
        assertThrows(IllegalArgumentException::class.java) {
            ExportCipher.decrypt("not-an-encrypted-export", password)
        }
    }

    @Test
    fun `长度非法的密文被拒`() {
        // 只有魔数头 + 不到 salt+iv 长度的内容
        val tooShort = ExportCipher.MAGIC + "AA=="
        assertThrows(IllegalArgumentException::class.java) {
            ExportCipher.decrypt(tooShort, password)
        }
    }

    @Test
    fun `篡改密文后认证失败被拒`() {
        val original = "do-not-tamper".toByteArray()
        val encrypted = ExportCipher.encrypt(original, password)
        // 翻转最后一字节, GCM 认证应失败
        val tampered = encrypted.substring(0, encrypted.length - 2) +
            if (encrypted.last() == 'A') "B" else "A"
        assertThrows(javax.crypto.BadPaddingException::class.java) {
            ExportCipher.decrypt(tampered, password)
        }
    }
}
