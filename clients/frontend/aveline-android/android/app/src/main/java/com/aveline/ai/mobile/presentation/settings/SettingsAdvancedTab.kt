package com.aveline.ai.mobile.presentation.settings

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.util.Base64
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.tools.ToolsUiState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream

/**
 * 高级 tab:调试工具(从 Tools 提取)。
 *
 * 所有调试工具默认折叠,点击展开:
 * - 图像生成:提示词 + 模型选择 + 生成按钮
 * - 视觉分析:图片输入 + 提示词 + 描述按钮
 * - 系统资源:系统资源/统计展示
 */
@Composable
fun SettingsAdvancedTab(
    toolsUiState: ToolsUiState,
    onLoadImageModels: () -> Unit,
    onGenerateImage: () -> Unit,
    onImagePromptChange: (String) -> Unit,
    onImageModelChange: (String) -> Unit,
    onVisionInputChange: (String) -> Unit,
    onVisionPromptChange: (String) -> Unit,
    onDescribeVision: () -> Unit,
    onLoadSystemResources: () -> Unit,
    onLoadSystemStats: () -> Unit,
    onClearError: () -> Unit,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var visionImageUri by remember { mutableStateOf<Uri?>(null) }

    // 视觉分析图片选择器:选择后压缩并转 base64 存入 visionInput
    // 修复 P0-19:原实现 stream.readBytes() 一次性读取全部字节,大图会 OOM;
    // 且无 try-catch,IO 异常会崩溃。改为先按 1024px 采样压缩,再转 JPEG(质量 80) + Base64。
    val visionImagePicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent()
    ) { uri: Uri? ->
        uri?.let {
            visionImageUri = it
            scope.launch {
                val base64 = withContext(Dispatchers.IO) {
                    try {
                        // 1. 先读图片尺寸,不真正解码像素
                        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                        context.contentResolver.openInputStream(it)?.use { stream ->
                            BitmapFactory.decodeStream(stream, null, bounds)
                        }
                        // 2. 计算 inSampleSize,把图片压缩到 1024x1024 以内
                        val sampleSize = calculateInSampleSize(bounds.outWidth, bounds.outHeight, 1024)
                        val options = BitmapFactory.Options().apply { inSampleSize = sampleSize }
                        // 3. 解码得到压缩后的 bitmap
                        val bitmap = context.contentResolver.openInputStream(it)?.use { stream ->
                            BitmapFactory.decodeStream(stream, null, options)
                        }
                        if (bitmap != null) {
                            val baos = ByteArrayOutputStream()
                            bitmap.compress(Bitmap.CompressFormat.JPEG, 80, baos)
                            bitmap.recycle()
                            "data:image/jpeg;base64," + Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP)
                        } else {
                            null
                        }
                    } catch (e: Exception) {
                        null
                    }
                }
                if (base64 != null) {
                    onVisionInputChange(base64)
                }
            }
        }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Spacer(modifier = Modifier.height(8.dp))

        // 图像生成(默认折叠)
        SectionCard(
            title = "图像生成",
            subtitle = "图像模型与推理参数",
            collapsible = true,
            defaultExpanded = false
        ) {
            OutlinedTextField(
                value = toolsUiState.imagePrompt,
                onValueChange = onImagePromptChange,
                label = { Text("提示词") },
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 56.dp)
            )
            Spacer(modifier = Modifier.height(8.dp))
            OutlinedTextField(
                value = toolsUiState.imageModelId,
                onValueChange = onImageModelChange,
                label = { Text("模型路径/ID") },
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 56.dp)
            )
            Spacer(modifier = Modifier.height(16.dp))
            AdvancedActionRow(
                primaryText = "模型列表",
                primaryAction = onLoadImageModels,
                secondaryText = "生成图片",
                secondaryAction = onGenerateImage,
                loading = toolsUiState.isImageLoading
            )
            if (toolsUiState.imageModelsText.isNotBlank()) {
                Text(
                    text = toolsUiState.imageModelsText,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            // 生成结果预览(URL 或 Base64)
            val imageResult = toolsUiState.imageResultUrl ?: toolsUiState.imageResultBase64
            if (!imageResult.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(8.dp))
                AsyncImage(
                    model = imageResult,
                    contentDescription = "image-result",
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(200.dp)
                )
            }
        }

        // 视觉分析(默认折叠)
        SectionCard(
            title = "视觉分析",
            subtitle = "图片理解与描述",
            collapsible = true,
            defaultExpanded = false
        ) {
            // 图片选择按钮
            Button(
                onClick = { visionImagePicker.launch("image/*") },
                colors = ButtonDefaults.buttonColors(
                    containerColor = Color(0x2A38BDF8),
                    contentColor = Color(0xFFE2E8F0)
                ),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(if (visionImageUri != null) "重新选择图片" else "选择图片")
            }
            // 图片预览
            visionImageUri?.let { uri ->
                Spacer(modifier = Modifier.height(12.dp))
                AsyncImage(
                    model = uri,
                    contentDescription = "vision-preview",
                    modifier = Modifier.fillMaxWidth().height(200.dp)
                )
            }
            Spacer(modifier = Modifier.height(16.dp))
            OutlinedTextField(
                value = toolsUiState.visionPrompt,
                onValueChange = onVisionPromptChange,
                label = { Text("提示词(可选)") },
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 56.dp)
            )
            Spacer(modifier = Modifier.height(16.dp))
            AdvancedActionRow(
                primaryText = "开始分析",
                primaryAction = onDescribeVision,
                secondaryText = null,
                secondaryAction = null,
                loading = toolsUiState.isVisionLoading
            )
            if (!toolsUiState.visionResult.isNullOrBlank()) {
                Text(
                    text = toolsUiState.visionResult.orEmpty(),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }

        // 系统资源(默认折叠)
        SectionCard(
            title = "系统资源",
            subtitle = "调度与运行健康指标",
            collapsible = true,
            defaultExpanded = false
        ) {
            AdvancedActionRow(
                primaryText = "资源信息",
                primaryAction = onLoadSystemResources,
                secondaryText = "运行统计",
                secondaryAction = onLoadSystemStats,
                loading = toolsUiState.isSystemLoading
            )
            JsonPreview(label = "资源", value = toolsUiState.systemResourcesText)
            JsonPreview(label = "统计", value = toolsUiState.systemStatsText)
        }

        // 错误提示
        if (!toolsUiState.error.isNullOrBlank()) {
            SectionCard(title = "错误", subtitle = null) {
                Text(
                    text = toolsUiState.error.orEmpty(),
                    style = MaterialTheme.typography.bodySmall,
                    color = Color(0xFFFFC7CE)
                )
                Spacer(modifier = Modifier.height(8.dp))
                TextButton(onClick = onClearError) { Text("关闭") }
            }
        }

        Spacer(modifier = Modifier.height(16.dp))
    }
}

/**
 * 调试工具操作行:主按钮 + 可选次按钮 + 加载指示。
 *
 * 按钮改为垂直堆叠,每个按钮独占一行,彻底解决小屏幕上水平按钮文字挤压/重合问题。
 */
@Composable
private fun AdvancedActionRow(
    primaryText: String,
    primaryAction: () -> Unit,
    secondaryText: String?,
    secondaryAction: (() -> Unit)?,
    loading: Boolean
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Button(
            onClick = primaryAction,
            enabled = !loading,
            modifier = Modifier
                .fillMaxWidth()
                .height(48.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = Color(0x2A38BDF8),
                contentColor = Color(0xFFE2E8F0)
            )
        ) {
            if (loading) {
                CircularProgressIndicator(
                    modifier = Modifier.size(18.dp),
                    strokeWidth = 2.dp,
                    color = Color(0xFFE2E8F0)
                )
            } else {
                Text(text = primaryText, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        if (!secondaryText.isNullOrBlank() && secondaryAction != null) {
            Button(
                onClick = secondaryAction,
                enabled = !loading,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(48.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = Color(0x1A000000),
                    contentColor = Color(0xFFE2E8F0)
                )
            ) { Text(text = secondaryText, maxLines = 1, overflow = TextOverflow.Ellipsis) }
        }
    }
}

/**
 * JSON 预览:仅当值非空时展示。
 */
@Composable
private fun JsonPreview(label: String, value: String?) {
    if (!value.isNullOrBlank()) {
        Text(
            text = "$label: $value",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 4.dp)
        )
    }
}

/**
 * 计算 BitmapFactory 的 inSampleSize,使解码后的图片长边不超过 [maxSize]。
 *
 * 标准的 2 的幂次采样,Android 文档推荐实现。
 */
private fun calculateInSampleSize(width: Int, height: Int, maxSize: Int): Int {
    if (width <= 0 || height <= 0) return 1
    var sampleSize = 1
    while (width / sampleSize > maxSize || height / sampleSize > maxSize) {
        sampleSize *= 2
    }
    return sampleSize
}
