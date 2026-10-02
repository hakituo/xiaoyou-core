package com.aveline.ai.mobile.data.local.storage

import android.content.Context
import android.net.Uri
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Persona 头像本地存储：把用户选的图片复制到 internal storage，避免依赖外部 Uri 权限。
 *
 * 存储位置：[context.filesDir]/avatars/&lt;personaFilename&gt;.&lt;ext&gt;
 * 同 persona 重复设置时旧文件被覆盖（保持单文件，避免堆积）。
 */
@Singleton
class PersonaAvatarStorage @Inject constructor(
    @ApplicationContext private val context: Context
) {

    private val avatarsDir: File
        get() = File(context.filesDir, "avatars").apply { mkdirs() }

    /**
     * 把用户从相册选的图片复制到 internal storage。
     *
     * @param personaFilename 目标 persona 的 filename
     * @param sourceUri 相册返回的 content:// Uri
     * @return 保存后的文件名（相对 avatars/），失败返回 null
     */
    suspend fun saveAvatar(personaFilename: String, sourceUri: Uri): String? = withContext(Dispatchers.IO) {
        runCatching {
            // 取扩展名（默认 jpg）
            val ext = context.contentResolver.getType(sourceUri)
                ?.substringAfterLast("/")
                ?.takeIf { it in listOf("jpg", "jpeg", "png", "webp", "gif") }
                ?: "jpg"
            val fileName = "${sanitize(personaFilename)}.$ext"
            val target = File(avatarsDir, fileName)

            context.contentResolver.openInputStream(sourceUri)?.use { input ->
                target.outputStream().use { output ->
                    input.copyTo(output)
                }
            } ?: return@runCatching null

            fileName
        }.getOrNull()
    }

    /**
     * 拿头像的本地 File，未设置或文件不存在返回 null。
     */
    fun getAvatarFile(avatarPath: String?): File? {
        if (avatarPath.isNullOrBlank()) return null
        val f = File(avatarsDir, avatarPath)
        return if (f.exists()) f else null
    }

    /**
     * 删除指定 persona 的头像文件。
     */
    suspend fun deleteAvatar(avatarPath: String?): Boolean = withContext(Dispatchers.IO) {
        if (avatarPath.isNullOrBlank()) return@withContext false
        File(avatarsDir, avatarPath).delete()
    }

    /**
     * 生成唯一的本地文件名前缀。
     *
     * 注意：persona 的 filename 是相对路径且常含中文（如 "sensitive/Mian.json"、
     * "sensitive/Frost.json"）。若只做字符替换，所有非 [A-Za-z0-9_-] 字符都会变成 "_"，
     * 同长度的中文名会产生完全相同的结果（两者都变成 "sensitive_____json"），
     * 导致不同 persona 的头像文件互相覆盖。
     * 这里追加原始 filename 的稳定哈希，确保一一对应。
     */
    private fun sanitize(name: String): String {
        val readable = name.replace(Regex("[^A-Za-z0-9_\\-]"), "_")
            .replace(Regex("_+"), "_")
            .trim('_')
            .take(32)
        val hash = md5Hex(name).take(12)
        return if (readable.isEmpty()) hash else "${readable}_$hash"
    }

    private fun md5Hex(input: String): String = runCatching {
        java.security.MessageDigest.getInstance("MD5")
            .digest(input.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
    }.getOrElse { Integer.toHexString(input.hashCode()) }
}
