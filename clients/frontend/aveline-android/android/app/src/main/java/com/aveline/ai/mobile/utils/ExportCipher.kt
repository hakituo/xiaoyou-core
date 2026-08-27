package com.aveline.ai.mobile.utils

import java.security.SecureRandom
import java.security.spec.KeySpec
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

/**
 * 导出文件加密/解密的纯逻辑实现, 与 Android 框架 / Room 解耦, 便于单元测试。
 *
 * 采用 PBKDF2WithHmacSHA256(随机盐) 派生 256 位密钥 + AES/GCM 认证加密。
 * 文件格式(文本):
 *   AVELINE_EXPORT_V1:<base64( salt | iv | gcm密文 )>
 *
 * 密码错误或内容被篡改时, GCM 认证会失败并抛 [javax.crypto.AEADBadTagException],
 * 由调用方捕获并给出明确错误。
 */
object ExportCipher {
    const val MAGIC = "AVELINE_EXPORT_V1:"

    private const val GCM_TAG_BITS = 128
    private const val SALT_SIZE = 16   // 随机盐字节数
    private const val IV_SIZE = 12     // GCM IV 字节数
    private const val PBKDF2_ITERATIONS = 120000
    private const val TRANSFORMATION = "AES/GCM/NoPadding"

    // java.util.Base64 (minSdk=26 自带), 而非 android.util.Base64, 以便 JVM 单元测试
    private val encoder = Base64.getEncoder()
    private val decoder = Base64.getDecoder()
    private val random = SecureRandom()

    /** 是否加密导出格式(以 [MAGIC] 开头)。 */
    fun isEncrypted(content: String): Boolean = content.startsWith(MAGIC)

    /**
     * 加密 [plain] 为导出文本格式。
     * @throws Exception 加密层异常(通常不会因输入而失败)
     */
    fun encrypt(plain: ByteArray, password: String): String {
        val salt = ByteArray(SALT_SIZE).also(random::nextBytes)
        val iv = ByteArray(IV_SIZE).also(random::nextBytes)
        val key = deriveKey(password, salt)

        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(GCM_TAG_BITS, iv))
        val encrypted = cipher.doFinal(plain)

        val combined = ByteArray(salt.size + iv.size + encrypted.size)
        System.arraycopy(salt, 0, combined, 0, salt.size)
        System.arraycopy(iv, 0, combined, salt.size, iv.size)
        System.arraycopy(encrypted, 0, combined, salt.size + iv.size, encrypted.size)
        return MAGIC + encoder.encodeToString(combined)
    }

    /**
     * 解密 [payload](须以 [MAGIC] 开头)。
     * @throws IllegalArgumentException 非加密格式 / 长度非法时
     * @throws javax.crypto.BadPaddingException 密码错误或数据被篡改时(GCM 认证失败)
     */
    fun decrypt(payload: String, password: String): ByteArray {
        require(payload.startsWith(MAGIC)) { "非加密导出格式" }
        val combined = decoder.decode(payload.substring(MAGIC.length))
        require(combined.size > SALT_SIZE + IV_SIZE) { "加密数据长度非法" }

        val salt = combined.copyOfRange(0, SALT_SIZE)
        val iv = combined.copyOfRange(SALT_SIZE, SALT_SIZE + IV_SIZE)
        val encrypted = combined.copyOfRange(SALT_SIZE + IV_SIZE, combined.size)
        val key = deriveKey(password, salt)

        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(GCM_TAG_BITS, iv))
        return cipher.doFinal(encrypted)
    }

    /** PBKDF2WithHmacSHA256 从口令 + 盐派生 256 位 AES 密钥。 */
    fun deriveKey(password: String, salt: ByteArray): ByteArray {
        val spec: KeySpec = PBEKeySpec(password.toCharArray(), salt, PBKDF2_ITERATIONS, 256)
        return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded
    }
}