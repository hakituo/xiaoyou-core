package com.aveline.ai.mobile.services

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import okhttp3.MediaType
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import okio.BufferedSink
import okio.source
import java.io.IOException
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 文件上传状态
 */
sealed class UploadState {
    data object Idle : UploadState()
    data class Uploading(
        val fileName: String,
        val progress: Float,
        val bytesUploaded: Long,
        val totalBytes: Long
    ) : UploadState()
    data class Success(
        val fileName: String,
        val fileUrl: String,
        val fileId: String
    ) : UploadState()
    data class Error(
        val fileName: String,
        val message: String
    ) : UploadState()
}

/**
 * 上传文件的用途分类。
 *
 * 三类的体积上限与 MIME 白名单都不同（图片 10MB、视频 50MB、其余按普通文件 10MB），
 * 用枚举而不是多个 Boolean 参数，避免出现 `isImage && isVideo` 这种无意义组合。
 */
enum class UploadKind {
    /** 普通文件（文档等） */
    DOCUMENT,

    /** 图片 */
    IMAGE,

    /** 视频 / 动图 */
    VIDEO,
}

/**
 * 文件上传结果
 */
data class UploadResult(
    val success: Boolean,
    val fileUrl: String? = null,
    val fileId: String? = null,
    val fileName: String? = null,
    val error: String? = null
)

/**
 * 文件上传管理器
 * 
 * 功能：
 * - 文件大小验证（最大 10MB）
 * - 上传进度跟踪
 * - 多文件类型支持
 * - 错误处理
 * 
 * Requirements: 4.2, 4.3, 4.7, 22.4
 */
@Singleton
class FileUploadManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val okHttpClient: OkHttpClient
) {
    companion object {
        const val MAX_FILE_SIZE = 10 * 1024 * 1024L // 10MB
        const val MAX_IMAGE_SIZE = 10 * 1024 * 1024L // 10MB for images
        // 视频体积天然比图片大一个量级，10MB 会让大部分手机录制的短视频直接被拒，放宽到 50MB
        const val MAX_VIDEO_SIZE = 50 * 1024 * 1024L // 50MB for videos
        
        private val SUPPORTED_IMAGE_TYPES = setOf(
            "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"
        )

        private val SUPPORTED_VIDEO_TYPES = setOf(
            "video/mp4", "video/webm", "video/3gpp", "video/3gpp2",
            "video/quicktime", "video/x-matroska", "video/x-msvideo"
        )
        
        private val SUPPORTED_DOCUMENT_TYPES = setOf(
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/plain",
            "text/csv"
        )
    }
    
    private val uploadClient = okHttpClient.newBuilder()
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()
    
    private val _uploadState = MutableStateFlow<UploadState>(UploadState.Idle)
    val uploadState: StateFlow<UploadState> = _uploadState.asStateFlow()
    
    private var backendUrl: String = ""
    private var accessToken: String = ""
    
    /**
     * 设置后端 URL
     */
    fun setBackendUrl(url: String) {
        backendUrl = url.trimEnd('/')
    }
    
    /**
     * 设置访问令牌
     */
    fun setAccessToken(token: String) {
        accessToken = token
    }
    
    /**
     * 获取文件信息
     *
     * 修复 P0-31:原实现是非 suspend 的同步方法,内部 contentResolver.query 是阻塞式 IO
     * (涉及 MediaStore 数据库查询),ChatUploadHelper 在 viewModelScope(Main)内直接调用
     * 导致选文件上传时主线程被阻塞。改为 suspend + withContext(IO),保证运行在 IO 线程。
     */
    suspend fun getFileInfo(uri: Uri): FileInfo? = withContext(Dispatchers.IO) {
        try {
            val cursor = context.contentResolver.query(uri, null, null, null, null)
            cursor?.use {
                val nameIndex = it.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeIndex = it.getColumnIndex(OpenableColumns.SIZE)

                if (it.moveToFirst()) {
                    val name = if (nameIndex >= 0) it.getString(nameIndex) else "unknown"
                    val size = if (sizeIndex >= 0) it.getLong(sizeIndex) else 0L
                    val mimeType = context.contentResolver.getType(uri) ?: "application/octet-stream"

                    FileInfo(
                        uri = uri,
                        name = name,
                        size = size,
                        mimeType = mimeType
                    )
                } else null
            }
        } catch (e: Exception) {
            null
        }
    }
    
    /**
     * 验证文件大小
     *
     * @param kind 上传用途，决定按哪个上限校验
     */
    fun validateFileSize(size: Long, kind: UploadKind): Boolean {
        val maxSize = when (kind) {
            UploadKind.IMAGE -> MAX_IMAGE_SIZE
            UploadKind.VIDEO -> MAX_VIDEO_SIZE
            UploadKind.DOCUMENT -> MAX_FILE_SIZE
        }
        return size <= maxSize
    }
    
    /**
     * 检查是否为支持的图片类型
     */
    fun isSupportedImageType(mimeType: String): Boolean {
        return SUPPORTED_IMAGE_TYPES.contains(mimeType.lowercase())
    }

    /**
     * 检查是否为支持的视频类型
     *
     * 覆盖手机相册/拍摄常见的 mp4、webm 动图、3gp、mov、mkv、avi。
     */
    fun isSupportedVideoType(mimeType: String): Boolean {
        return SUPPORTED_VIDEO_TYPES.contains(mimeType.lowercase())
    }
    
    /**
     * 检查是否为支持的文档类型
     */
    fun isSupportedDocumentType(mimeType: String): Boolean {
        return SUPPORTED_DOCUMENT_TYPES.contains(mimeType.lowercase()) || 
               mimeType.startsWith("text/")
    }
    
    /**
     * 上传文件
     *
     * 修复 P0-oom: 原实现 [readFileBytes] 把整个文件读入 ByteArrayOutputStream 再 toByteArray,
     * 10MB 文件占用 ~20MB 堆内存(buffer + copy)。改为流式上传,直接从 ContentResolver
     * 输入流写入网络,不在内存中持有完整文件。
     *
     * @param uri 文件 URI
     * @param kind 上传用途（决定体积上限与 MIME 白名单）
     * @return 上传结果
     */
    suspend fun uploadFile(uri: Uri, kind: UploadKind): UploadResult = withContext(Dispatchers.IO) {
        val fileInfo = getFileInfo(uri)

        if (fileInfo == null) {
            return@withContext UploadResult(
                success = false,
                error = "无法读取文件信息"
            )
        }

        // 验证文件大小
        if (!validateFileSize(fileInfo.size, kind)) {
            val maxSizeMB = when (kind) {
                UploadKind.IMAGE -> MAX_IMAGE_SIZE / (1024 * 1024)
                UploadKind.VIDEO -> MAX_VIDEO_SIZE / (1024 * 1024)
                UploadKind.DOCUMENT -> MAX_FILE_SIZE / (1024 * 1024)
            }
            return@withContext UploadResult(
                success = false,
                fileName = fileInfo.name,
                error = "文件大小超过限制 (${maxSizeMB}MB)"
            )
        }

        // 验证文件类型
        if (kind == UploadKind.IMAGE && !isSupportedImageType(fileInfo.mimeType)) {
            return@withContext UploadResult(
                success = false,
                fileName = fileInfo.name,
                error = "不支持的图片格式"
            )
        }
        if (kind == UploadKind.VIDEO && !isSupportedVideoType(fileInfo.mimeType)) {
            return@withContext UploadResult(
                success = false,
                fileName = fileInfo.name,
                error = "不支持的视频格式"
            )
        }

        // 检查后端 URL
        if (backendUrl.isEmpty()) {
            return@withContext UploadResult(
                success = false,
                fileName = fileInfo.name,
                error = "未配置后端地址"
            )
        }

        // 更新上传状态(用 fileInfo.size 而非 bytes.size,因为不再读取完整文件到内存)
        _uploadState.value = UploadState.Uploading(
            fileName = fileInfo.name,
            progress = 0f,
            bytesUploaded = 0,
            totalBytes = fileInfo.size
        )

        // 执行流式上传
        return@withContext try {
            performUpload(fileInfo)
        } catch (e: Exception) {
            _uploadState.value = UploadState.Error(fileInfo.name, e.message ?: "上传失败")
            UploadResult(
                success = false,
                fileName = fileInfo.name,
                error = "上传失败: ${e.message}"
            )
        }
    }

    /**
     * 执行上传请求(流式)
     *
     * 使用自定义 [RequestBody],在 [writeTo] 中直接从 ContentResolver 输入流读取并写入网络,
     * 不把整个文件加载到内存。OkHttp 负责分块传输。
     */
    private suspend fun performUpload(fileInfo: FileInfo): UploadResult = withContext(Dispatchers.IO) {
        try {
            // 图片先在本地压一道再传：后端 optimize_image 也会压，但那是「先传原图再压」，
            // 带宽已经花掉了。非图片 / GIF / 解码失败 / 压完反而更大时返回 null，回退传原文件。
            val compressed = UploadImageCompressor.compress(
                context = context,
                uri = fileInfo.uri,
                mimeType = fileInfo.mimeType,
                originalSize = fileInfo.size
            )

            val uploadSize = compressed?.bytes?.size?.toLong() ?: fileInfo.size

            // 修复 P0-36: 原实现在常量字符串 fallback 上也用 toMediaTypeOrNull()!!,
            // 虽然对 "application/octet-stream" 来说实际不会为空,但 !! 是代码臭味。
            // fallback 分支改用非空的 toMediaType() 直接构造,从签名上保证永不失败。
            val mediaType = (compressed?.mimeType ?: fileInfo.mimeType).toMediaTypeOrNull()
                ?: "application/octet-stream".toMediaType()

            // 压缩后的字节直接发；未压缩时仍走流式 RequestBody，不把整个文件加载到内存。
            val requestBody: RequestBody = if (compressed != null) {
                compressed.bytes.toRequestBody(mediaType)
            } else {
                object : RequestBody() {
                    override fun contentType(): MediaType? = mediaType

                    // 必须返回 -1（长度未知），不能返回 fileInfo.size。
                    //
                    // fileInfo.size 取自 OpenableColumns.SIZE，是 ContentProvider 的元数据，
                    // 可能与真实字节数不符（媒体库行过期、云相册给出的是缩略图大小、部分
                    // provider 直接给 0）。元数据偏小时 MultipartBody 会算出偏小的
                    // Content-Length；走隧道时 OkHttp 用 HTTP/2，帧层不再按长度校验，
                    // 多出的字节照发，而 Cloudflare / uvicorn 只按声明长度收 —— multipart
                    // 被截断，FastAPI 拿不到 file 字段，直接回 422 Field required。
                    //
                    // 返回 -1 让 OkHttp 改用 chunked，长度由分块界定，不可能截断。
                    override fun contentLength(): Long = -1L

                    override fun writeTo(sink: BufferedSink) {
                        context.contentResolver.openInputStream(fileInfo.uri)?.use { input ->
                            val source = input.source()
                            sink.writeAll(source)
                        } ?: throw IOException("无法打开文件输入流")
                    }
                }
            }

            val multipartBody = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("file", fileInfo.name, requestBody)
                .build()

            val requestBuilder = Request.Builder()
                // 上传端点在媒体业务域下：/api/v1/media/upload（不是 /api/v1/upload）。
                // 旧路径已不存在，请求会落到前端的 catch-all 静态挂载，只允许 GET/HEAD，
                // 于是返回 405 Method Not Allowed。
                .url("$backendUrl/api/v1/media/upload")
                .post(multipartBody)

            // 添加认证头
            if (accessToken.isNotEmpty()) {
                requestBuilder.addHeader("Authorization", "Bearer $accessToken")
            }

            _uploadState.value = UploadState.Uploading(
                fileName = fileInfo.name,
                progress = 0.5f,
                bytesUploaded = uploadSize / 2,
                totalBytes = uploadSize
            )

            val response = uploadClient.newCall(requestBuilder.build()).execute()

            if (!response.isSuccessful) {
                // 后端 4xx 的原因在响应体 detail 里（FastAPI 的校验明细），Cloudflare 5xx
                // 的说明也在 body 里。只留状态码的话用户和日志都只能看到一个没有上下文的数字。
                val detail = response.body?.string().orEmpty().trim().take(300)
                throw IOException(
                    if (detail.isEmpty()) "HTTP ${response.code}: ${response.message}"
                    else "HTTP ${response.code}: $detail"
                )
            }

            val responseBody = response.body?.string() ?: throw IOException("空响应")
            val json = JSONObject(responseBody)

            // 解析响应
            val data = json.optJSONObject("data") ?: json
            val fileUrl = data.optString("file_url", data.optString("url", ""))
            val fileId = data.optString("file_id", data.optString("id", ""))

            _uploadState.value = UploadState.Success(
                fileName = fileInfo.name,
                fileUrl = fileUrl,
                fileId = fileId
            )

            UploadResult(
                success = true,
                fileUrl = fileUrl,
                fileId = fileId,
                fileName = fileInfo.name
            )
        } catch (e: Exception) {
            throw e
        }
    }
    
    /**
     * 重置上传状态
     */
    fun resetState() {
        _uploadState.value = UploadState.Idle
    }
}

/**
 * 文件信息数据类
 */
data class FileInfo(
    val uri: Uri,
    val name: String,
    val size: Long,
    val mimeType: String
)
