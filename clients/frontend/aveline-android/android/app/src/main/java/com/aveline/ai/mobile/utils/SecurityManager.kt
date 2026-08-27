package com.aveline.ai.mobile.utils

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyInfo
import android.security.keystore.KeyProperties
import dagger.hilt.android.qualifiers.ApplicationContext
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.inject.Inject
import javax.inject.Singleton
import android.util.Base64

/**
 * 安全管理器
 * 
 * 提供加密、解密和安全存储功能
 * 
 * Requirements: 24.1, 24.2
 */
@Singleton
class SecurityManager @Inject constructor(
    @ApplicationContext private val context: Context
) {
    companion object {
        private const val ANDROID_KEY_STORE = "AndroidKeyStore"
        private const val KEY_ALIAS = "aveline_master_key"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val TAG_LENGTH = 128
    }
    
    private val keyStore: KeyStore by lazy {
        KeyStore.getInstance(ANDROID_KEY_STORE).apply {
            load(null)
        }
    }
    
    /**
     * 获取或创建密钥
     */
    private fun getOrCreateKey(): SecretKey {
        if (!keyStore.containsAlias(KEY_ALIAS)) {
            createKey()
        }
        
        return (keyStore.getEntry(KEY_ALIAS, null) as KeyStore.SecretKeyEntry).secretKey
    }
    
    /**
     * 创建新密钥
     */
    private fun createKey() {
        val keyGenerator = KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES,
            ANDROID_KEY_STORE
        )
        
        val spec = KeyGenParameterSpec.Builder(
            KEY_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .setRandomizedEncryptionRequired(true)
            .build()
        
        keyGenerator.init(spec)
        keyGenerator.generateKey()
    }
    
    /**
     * 加密数据
     * 
     * @param data 要加密的数据
     * @return Base64 编码的加密数据（IV + 密文）
     */
    fun encrypt(data: String): String {
        if (data.isEmpty()) return ""
        
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        
        val encrypted = cipher.doFinal(data.toByteArray(Charsets.UTF_8))
        val iv = cipher.iv
        
        // 将 IV 和密文组合
        val combined = ByteArray(iv.size + encrypted.size)
        System.arraycopy(iv, 0, combined, 0, iv.size)
        System.arraycopy(encrypted, 0, combined, iv.size, encrypted.size)
        
        return Base64.encodeToString(combined, Base64.NO_WRAP)
    }
    
    /**
     * 解密数据
     *
     * 修复 P0-sec-2: 原实现未校验 combined 长度,短于 12 字节(IV 长度)时
     * copyOfRange 会抛 IllegalArgumentException 导致崩溃。改为显式校验。
     *
     * @param encryptedData Base64 编码的加密数据
     * @return 解密后的原始数据
     */
    fun decrypt(encryptedData: String): String {
        if (encryptedData.isEmpty()) return ""

        val combined = Base64.decode(encryptedData, Base64.NO_WRAP)

        // 提取 IV（GCM IV 长度为 12 字节）
        val ivSize = 12
        // 边界检查:密文必须至少包含 IV + 1 字节(GCM tag 16 字节,实际最少 ivSize+16)
        if (combined.size <= ivSize) {
            throw IllegalArgumentException("Invalid encrypted data: too short for IV")
        }
        val iv = combined.copyOfRange(0, ivSize)
        val encrypted = combined.copyOfRange(ivSize, combined.size)

        val cipher = Cipher.getInstance(TRANSFORMATION)
        val spec = GCMParameterSpec(TAG_LENGTH, iv)
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), spec)

        val decrypted = cipher.doFinal(encrypted)
        return String(decrypted, Charsets.UTF_8)
    }
    
    /**
     * 检查密钥是否存在
     */
    fun hasKey(): Boolean {
        return keyStore.containsAlias(KEY_ALIAS)
    }
    
    /**
     * 删除密钥
     */
    fun deleteKey() {
        if (keyStore.containsAlias(KEY_ALIAS)) {
            keyStore.deleteEntry(KEY_ALIAS)
        }
    }
    
    /**
     * 安全地清除敏感数据
     */
    fun clearSensitiveData() {
        deleteKey()
    }
    
    /**
     * 生成随机盐值
     */
    fun generateSalt(): String {
        val salt = ByteArray(16)
        java.security.SecureRandom().nextBytes(salt)
        return Base64.encodeToString(salt, Base64.NO_WRAP)
    }
    
    /**
     * 哈希数据
     */
    fun hash(data: String, salt: String): String {
        val saltBytes = Base64.decode(salt, Base64.NO_WRAP)
        val dataBytes = data.toByteArray(Charsets.UTF_8)
        
        val combined = ByteArray(saltBytes.size + dataBytes.size)
        System.arraycopy(saltBytes, 0, combined, 0, saltBytes.size)
        System.arraycopy(dataBytes, 0, combined, saltBytes.size, dataBytes.size)
        
        val digest = java.security.MessageDigest.getInstance("SHA-256")
        val hash = digest.digest(combined)
        
        return Base64.encodeToString(hash, Base64.NO_WRAP)
    }
    
    /**
     * 验证哈希（使用常量时间比较，防止时序攻击）
     */
    fun verifyHash(data: String, salt: String, expectedHash: String): Boolean {
        val actualHash = hash(data, salt)
        return java.security.MessageDigest.isEqual(
            actualHash.toByteArray(Charsets.UTF_8),
            expectedHash.toByteArray(Charsets.UTF_8)
        )
    }
    
    /**
     * 检查设备是否支持硬件加密。
     *
     * 修复 P0-sec-1: 原实现用 `secretKey.algorithm == "AES"` 判断硬件支持,
     * 但所有 AES 密钥(无论软件/硬件)的 algorithm 都是 "AES",该判断恒为 true,
     * 完全无法区分硬件/软件支持。改为通过 SecretKeyFactory.getKeySpec 获取 KeyInfo,
     * 调用 getSecurityLevel() 判断密钥是否存储在安全硬件(TEE/StrongBox)中。
     *
     * API 35 废弃了 isInsideSecureHardware(),改用 KeyInfo.getSecurityLevel()
     * 与 KeyProperties.SECURITY_LEVEL_SOFTWARE 比较:
     * - != SOFTWARE 即代表密钥在安全硬件(TEE/StrongBox)中
     */
    fun isHardwareBackedKeyStore(): Boolean {
        return try {
            if (!hasKey()) {
                createKey()
            }

            val entry = keyStore.getEntry(KEY_ALIAS, null) as KeyStore.SecretKeyEntry
            val secretKey = entry.secretKey
            val factory = SecretKeyFactory.getInstance(secretKey.algorithm, ANDROID_KEY_STORE)
            val keyInfo = factory.getKeySpec(secretKey, KeyInfo::class.java) as KeyInfo
            keyInfo.getSecurityLevel() != KeyProperties.SECURITY_LEVEL_SOFTWARE
        } catch (e: Exception) {
            false
        }
    }
    
    /**
     * 检查设备是否处于安全状态
     */
    fun isDeviceSecure(): Boolean {
        val keyguardManager = context.getSystemService(Context.KEYGUARD_SERVICE) 
            as android.app.KeyguardManager
        return keyguardManager.isDeviceSecure
    }
    
    /**
     * 检查是否有屏幕锁
     */
    fun hasScreenLock(): Boolean {
        val keyguardManager = context.getSystemService(Context.KEYGUARD_SERVICE) 
            as android.app.KeyguardManager
        return keyguardManager.isKeyguardSecure
    }
}
