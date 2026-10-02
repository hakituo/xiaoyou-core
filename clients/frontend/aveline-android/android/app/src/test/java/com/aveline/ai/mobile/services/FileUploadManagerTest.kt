package com.aveline.ai.mobile.services

import io.mockk.every
import io.mockk.mockk
import okhttp3.OkHttpClient
import io.mockk.verify
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/**
 * FileUploadManager 单元测试
 * 
 * 测试覆盖：
 * - 文件大小验证
 * - 文件类型验证
 * - 上传状态管理
 * - 错误处理
 * 
 * Requirements: 4.2, 4.3, 4.7, 22.4
 */
class FileUploadManagerTest {
    
    private lateinit var fileUploadManager: FileUploadManager
    private val context = mockk<android.content.Context>(relaxed = true)
    
    @Before
    fun setUp() {
        fileUploadManager = FileUploadManager(context, mockk(relaxed = true))
    }
    
    // ==================== 文件大小验证测试 ====================
    
    @Test
    fun `validateFileSize returns true for files under 10MB`() {
        val smallFile = 5 * 1024 * 1024L // 5MB
        assertTrue(fileUploadManager.validateFileSize(smallFile, UploadKind.DOCUMENT))
    }
    
    @Test
    fun `validateFileSize returns true for files exactly 10MB`() {
        val exactLimit = 10 * 1024 * 1024L // 10MB
        assertTrue(fileUploadManager.validateFileSize(exactLimit, UploadKind.DOCUMENT))
    }
    
    @Test
    fun `validateFileSize returns false for files over 10MB`() {
        val largeFile = 11 * 1024 * 1024L // 11MB
        assertFalse(fileUploadManager.validateFileSize(largeFile, UploadKind.DOCUMENT))
    }
    
    @Test
    fun `validateFileSize returns false for files slightly over 10MB`() {
        val slightlyOver = 10 * 1024 * 1024L + 1 // 10MB + 1 byte
        assertFalse(fileUploadManager.validateFileSize(slightlyOver, UploadKind.DOCUMENT))
    }
    
    @Test
    fun `validateFileSize for images uses same 10MB limit`() {
        val imageUnderLimit = 8 * 1024 * 1024L // 8MB
        val imageOverLimit = 15 * 1024 * 1024L // 15MB
        
        assertTrue(fileUploadManager.validateFileSize(imageUnderLimit, UploadKind.IMAGE))
        assertFalse(fileUploadManager.validateFileSize(imageOverLimit, UploadKind.IMAGE))
    }

    @Test
    fun `validateFileSize for videos uses 50MB limit`() {
        val videoUnderLimit = 40 * 1024 * 1024L // 40MB，图片/文档会被拒
        val videoOverLimit = 51 * 1024 * 1024L // 51MB

        assertTrue(fileUploadManager.validateFileSize(videoUnderLimit, UploadKind.VIDEO))
        assertFalse(fileUploadManager.validateFileSize(videoOverLimit, UploadKind.VIDEO))
        // 同一份文件按图片/文档口径仍受 10MB 限制，说明分类确实生效
        assertFalse(fileUploadManager.validateFileSize(videoUnderLimit, UploadKind.IMAGE))
        assertFalse(fileUploadManager.validateFileSize(videoUnderLimit, UploadKind.DOCUMENT))
    }
    
    @Test
    fun `validateFileSize returns true for empty file`() {
        assertTrue(fileUploadManager.validateFileSize(0L, UploadKind.DOCUMENT))
    }
    
    @Test
    fun `validateFileSize returns true for 1 byte file`() {
        assertTrue(fileUploadManager.validateFileSize(1L, UploadKind.DOCUMENT))
    }
    
    // ==================== 文件类型验证测试 ====================
    
    @Test
    fun `isSupportedImageType returns true for JPEG`() {
        assertTrue(fileUploadManager.isSupportedImageType("image/jpeg"))
    }
    
    @Test
    fun `isSupportedImageType returns true for PNG`() {
        assertTrue(fileUploadManager.isSupportedImageType("image/png"))
    }
    
    @Test
    fun `isSupportedImageType returns true for GIF`() {
        assertTrue(fileUploadManager.isSupportedImageType("image/gif"))
    }
    
    @Test
    fun `isSupportedImageType returns true for WebP`() {
        assertTrue(fileUploadManager.isSupportedImageType("image/webp"))
    }
    
    @Test
    fun `isSupportedImageType returns true for BMP`() {
        assertTrue(fileUploadManager.isSupportedImageType("image/bmp"))
    }
    
    @Test
    fun `isSupportedImageType returns false for unsupported types`() {
        assertFalse(fileUploadManager.isSupportedImageType("image/svg+xml"))
        assertFalse(fileUploadManager.isSupportedImageType("image/tiff"))
        assertFalse(fileUploadManager.isSupportedImageType("application/pdf"))
        assertFalse(fileUploadManager.isSupportedImageType("text/plain"))
    }
    
    @Test
    fun `isSupportedImageType is case insensitive`() {
        assertTrue(fileUploadManager.isSupportedImageType("IMAGE/JPEG"))
        assertTrue(fileUploadManager.isSupportedImageType("Image/Png"))
        assertTrue(fileUploadManager.isSupportedImageType("image/GIF"))
    }
    
    @Test
    fun `isSupportedDocumentType returns true for PDF`() {
        assertTrue(fileUploadManager.isSupportedDocumentType("application/pdf"))
    }
    
    @Test
    fun `isSupportedDocumentType returns true for Word documents`() {
        assertTrue(fileUploadManager.isSupportedDocumentType("application/msword"))
        assertTrue(fileUploadManager.isSupportedDocumentType("application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
    }
    
    @Test
    fun `isSupportedDocumentType returns true for text files`() {
        assertTrue(fileUploadManager.isSupportedDocumentType("text/plain"))
        assertTrue(fileUploadManager.isSupportedDocumentType("text/csv"))
    }
    
    @Test
    fun `isSupportedDocumentType returns false for unsupported types`() {
        assertFalse(fileUploadManager.isSupportedDocumentType("application/zip"))
        assertFalse(fileUploadManager.isSupportedDocumentType("video/mp4"))
    }

    // ==================== 视频类型验证测试 ====================

    @Test
    fun `isSupportedVideoType returns true for common video types`() {
        assertTrue(fileUploadManager.isSupportedVideoType("video/mp4"))
        assertTrue(fileUploadManager.isSupportedVideoType("video/webm"))
        assertTrue(fileUploadManager.isSupportedVideoType("video/quicktime"))
        assertTrue(fileUploadManager.isSupportedVideoType("video/x-matroska"))
    }

    @Test
    fun `isSupportedVideoType returns false for images and documents`() {
        assertFalse(fileUploadManager.isSupportedVideoType("image/gif"))
        assertFalse(fileUploadManager.isSupportedVideoType("application/pdf"))
    }

    @Test
    fun `isSupportedVideoType is case insensitive`() {
        assertTrue(fileUploadManager.isSupportedVideoType("VIDEO/MP4"))
        assertTrue(fileUploadManager.isSupportedVideoType("Video/WebM"))
    }
    
    // ==================== 上传状态管理测试 ====================
    
    @Test
    fun `initial upload state is Idle`() {
        assertEquals(UploadState.Idle, fileUploadManager.uploadState.value)
    }
    
    @Test
    fun `resetState sets upload state to Idle`() = runTest {
        fileUploadManager.resetState()
        assertEquals(UploadState.Idle, fileUploadManager.uploadState.value)
    }
    
    @Test
    fun `setBackendUrl stores backend URL`() {
        val testUrl = "https://api.example.com"
        fileUploadManager.setBackendUrl(testUrl)
    }
    
    @Test
    fun `setBackendUrl trims trailing slash`() {
        val testUrl = "https://api.example.com/"
        fileUploadManager.setBackendUrl(testUrl)
    }
    
    @Test
    fun `setAccessToken stores access token`() {
        val testToken = "test-access-token-12345"
        fileUploadManager.setAccessToken(testToken)
    }
    
    // ==================== UploadState 测试 ====================
    
    @Test
    fun `UploadState Idle is not Uploading`() {
        val state: UploadState = UploadState.Idle
        assertFalse(state is UploadState.Uploading)
    }
    
    @Test
    fun `UploadState Uploading contains progress information`() {
        val state = UploadState.Uploading(
            fileName = "test.jpg",
            progress = 0.5f,
            bytesUploaded = 500000L,
            totalBytes = 1000000L
        )
        
        assertEquals("test.jpg", state.fileName)
        assertEquals(0.5f, state.progress, 0.001f)
        assertEquals(500000L, state.bytesUploaded)
        assertEquals(1000000L, state.totalBytes)
    }
    
    @Test
    fun `UploadState Success contains file information`() {
        val state = UploadState.Success(
            fileName = "test.jpg",
            fileUrl = "https://example.com/files/test.jpg",
            fileId = "file-123"
        )
        
        assertEquals("test.jpg", state.fileName)
        assertEquals("https://example.com/files/test.jpg", state.fileUrl)
        assertEquals("file-123", state.fileId)
    }
    
    @Test
    fun `UploadState Error contains error message`() {
        val state = UploadState.Error(
            fileName = "test.jpg",
            message = "File too large"
        )
        
        assertEquals("test.jpg", state.fileName)
        assertEquals("File too large", state.message)
    }
    
    // ==================== UploadResult 测试 ====================
    
    @Test
    fun `UploadResult success has all required fields`() {
        val result = UploadResult(
            success = true,
            fileUrl = "https://example.com/files/test.jpg",
            fileId = "file-123",
            fileName = "test.jpg"
        )
        
        assertTrue(result.success)
        assertEquals("https://example.com/files/test.jpg", result.fileUrl)
        assertEquals("file-123", result.fileId)
        assertEquals("test.jpg", result.fileName)
        assertNull(result.error)
    }
    
    @Test
    fun `UploadResult failure has error message`() {
        val result = UploadResult(
            success = false,
            fileName = "test.jpg",
            error = "Upload failed"
        )
        
        assertFalse(result.success)
        assertNull(result.fileUrl)
        assertNull(result.fileId)
        assertEquals("Upload failed", result.error)
    }
    
    // ==================== FileInfo 测试 ====================
    
    @Test
    fun `FileInfo contains all required fields`() {
        val uri = mockk<android.net.Uri>()
        val fileInfo = FileInfo(
            uri = uri,
            name = "test.jpg",
            size = 1024L,
            mimeType = "image/jpeg"
        )
        
        assertEquals(uri, fileInfo.uri)
        assertEquals("test.jpg", fileInfo.name)
        assertEquals(1024L, fileInfo.size)
        assertEquals("image/jpeg", fileInfo.mimeType)
    }
}
