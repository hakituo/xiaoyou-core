package com.aveline.ai.mobile.presentation.components

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material.icons.automirrored.rounded.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.rounded.KeyboardArrowRight
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.aveline.ai.mobile.presentation.theme.BorderLight
import com.aveline.ai.mobile.presentation.theme.BubbleAI
import com.aveline.ai.mobile.presentation.theme.BubbleSystem
import com.aveline.ai.mobile.presentation.theme.BubbleUser
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import androidx.compose.ui.platform.LocalContext
import android.content.Context
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.presentation.study.NotesMarkdownRenderer
import com.aveline.ai.mobile.presentation.utils.EmotionResolver
import com.aveline.ai.mobile.utils.ImageUrlResolver
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent

// 括号内容(如"(开心)")匹配正则,提取到文件顶层避免每次重组都重新编译
private val RETRACTION_REGEX = Regex("（[\\s\\S]*?）|\\([\\s\\S]*?\\)")

/**
 * 通过 Hilt EntryPoint 在非 ViewModel 的 Composable 中拿到 AppPreferences 单例。
 */
@EntryPoint
@InstallIn(SingletonComponent::class)
interface AppPreferencesEntryPoint {
    fun appPreferences(): AppPreferences
}

private fun Context.avelineAppPreferences(): AppPreferences =
    EntryPointAccessors.fromApplication(this, AppPreferencesEntryPoint::class.java)
        .appPreferences()

/**
 * 把图片地址补全为可加载的绝对地址：
 * - 已是绝对地址（http/https/data/content/file）原样返回；
 * - 后端下发的相对路径（如 /output/image/xxx）拼接后端 baseUrl，
 *   否则 Coil/OkHttp 因缺少 host 无法解析，最终显示破图占位（感叹号图标）。
 */
private fun resolveImageUrl(rawUrl: String, backendBaseUrl: String): String {
    return ImageUrlResolver.resolve(backendBaseUrl, rawUrl)
}

/**
 * 消息类型枚举
 */
enum class MessageType {
    USER,
    AI,
    SYSTEM,
    RETRACTION  // 括号内容如(开心) - 居中淡色显示
}

/**
 * 消息数据类
 */
data class MessageData(
    val id: String,
    val text: String,
    val isUser: Boolean,
    val timestamp: Long,
    val messageType: MessageType = if (isUser) MessageType.USER else MessageType.AI,
    val imageUrl: String? = null,
    val isPlaying: Boolean = false,
    val emotion: String? = null,
    val variantIndex: Int = 0,
    val variantCount: Int = 1
)

/**
 * 消息气泡组件
 * 
 * 显示用户或 AI 消息，支持：
 * - 不同对齐方式（用户右对齐，AI 左对齐）
 * - 时间戳显示
 * - 图片显示
 * - TTS 播放按钮（AI 消息）
 * - 长按上下文菜单
 * 
 * @param message 消息数据
 * @param onPlayTTS TTS 播放回调
 * @param onCopy 复制回调
 * @param onDelete 删除回调
 * @param onImageClick 图片点击回调
 * @param modifier 修饰符
 */
@Composable
fun MessageBubble(
    message: MessageData,
    onPlayTTS: ((String) -> Unit)? = null,
    onCopy: ((String) -> Unit)? = null,
    onDelete: ((String) -> Unit)? = null,
    onRegenerate: ((String) -> Unit)? = null,
    onEdit: ((String, String) -> Unit)? = null,
    onPreviousVariant: ((String) -> Unit)? = null,
    onNextVariant: ((String) -> Unit)? = null,
    onImageClick: ((String) -> Unit)? = null,
    modifier: Modifier = Modifier
) {
    val isRetraction = message.messageType == MessageType.RETRACTION || isRetractionText(message.text)
    // 剥离 [MEME]/[IMG]/[BM]/[VOICE] 媒体标签，避免前端显示 "[MEME]" 字样
    // （后端 _send_chunk 已剥离一次，这里兜底防边界情况）
    val rawText = if (isRetraction) unwrapRetractionText(message.text) else message.text
    val cleanedText = stripMediaTags(rawText)
    if (isRetraction) {
        Row(
            modifier = modifier
                .fillMaxWidth()
                .padding(vertical = 8.dp),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .widthIn(min = 48.dp, max = 64.dp)
                    .height(1.dp)
                    .background(
                        Brush.horizontalGradient(
                            colors = listOf(Color.Transparent, Color(0x33FFFFFF), Color.Transparent)
                        )
                    )
            )
            Text(
                text = cleanedText,
                style = MaterialTheme.typography.labelSmall.copy(
                    letterSpacing = 1.2.sp
                ),
                color = TextTertiary,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(horizontal = 12.dp)
            )
            Box(
                modifier = Modifier
                    .widthIn(min = 48.dp, max = 64.dp)
                    .height(1.dp)
                    .background(
                        Brush.horizontalGradient(
                            colors = listOf(Color.Transparent, Color(0x33FFFFFF), Color.Transparent)
                        )
                    )
            )
        }
        return
    }

    val isUser = message.isUser
    // 用 message.id 作为 key,避免 LazyColumn 复用 item 时菜单/交互状态跨消息错乱
    val interactionSource = remember(message.id) { MutableInteractionSource() }
    val isPressed by interactionSource.collectIsPressedAsState()
    var showActions by remember(message.id) { androidx.compose.runtime.mutableStateOf(false) }
    val aiEmotionColor = EmotionResolver.getColorForEmotion(message.emotion ?: "neutral").copy(alpha = 0.15f)
    
    // 按压缩放动画
    val scale by animateFloatAsState(
        targetValue = if (isPressed) 0.98f else 1.0f,
        animationSpec = tween(durationMillis = 100, easing = FastOutSlowInEasing),
        label = "scale"
    )
    
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(
                horizontal = 12.dp,
                vertical = 2.dp
            ),
        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start
    ) {
        // 消息气泡
        Surface(
            modifier = (if (isUser) Modifier.widthIn(max = 300.dp) else Modifier.fillMaxWidth())
                .scale(scale)
                .clip(
                    if (isUser) {
                        RoundedCornerShape(
                            topStart = 18.dp,
                            topEnd = 18.dp,
                            bottomStart = 18.dp,
                            bottomEnd = 6.dp
                        )
                    } else {
                        RoundedCornerShape(0.dp)
                    }
                )
                .clickable(
                    interactionSource = interactionSource,
                    indication = null
                ) {
                    showActions = !showActions
                },
            color = when (message.messageType) {
                MessageType.USER -> Color(0x0CFFFFFF) // bg-white/5
                // AI 正文采用 ChatGPT 式无气泡整行排版，Markdown 块可使用完整宽度。
                MessageType.AI -> Color.Transparent
                MessageType.SYSTEM -> Color(0x33000000)
                MessageType.RETRACTION -> aiEmotionColor
            },
            border = if (isUser || message.messageType == MessageType.SYSTEM) {
                BorderStroke(1.dp, Color(0x1AFFFFFF))
            } else {
                null
            },
            shape = if (isUser) {
                RoundedCornerShape(
                    topStart = 16.dp,
                    topEnd = 16.dp,
                    bottomStart = 16.dp,
                    bottomEnd = 2.dp
                )
            } else {
                RoundedCornerShape(0.dp)
            },
            shadowElevation = 0.dp
        ) {
            Column(
                modifier = Modifier.padding(
                    horizontal = if (isUser) 16.dp else 4.dp,
                    vertical = if (isUser) 12.dp else 8.dp
                )
            ) {
                // 图片显示（如果有）
                message.imageUrl?.let { imageUrl ->
                    MessageImage(
                        imageUrl = imageUrl,
                        isUser = isUser,
                        onImageClick = onImageClick,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(bottom = if (message.text.isNotBlank()) 8.dp else 0.dp)
                    )
                }
                
                // 消息文本 - 对AI消息中的括号内容(如情绪标注)特殊渲染，去除末尾句号
                if (cleanedText.isNotBlank()) {
                    val displayText = if (!isUser) {
                        // AI消息：去除末尾句号并处理括号内容
                        stripTrailingPeriod(cleanedText)
                    } else {
                        cleanedText
                    }
                    if (isUser) {
                        Text(
                            text = AnnotatedString(displayText),
                            style = MaterialTheme.typography.bodyMedium.copy(
                                lineHeight = 22.sp,
                                fontWeight = FontWeight.Normal
                            ),
                            color = TextPrimary,
                            modifier = Modifier.semantics {
                                contentDescription = "用户消息: $cleanedText"
                            }
                        )
                    } else {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .semantics { contentDescription = "AI消息: $cleanedText" }
                        ) {
                            NotesMarkdownRenderer(text = displayText)
                        }
                    }
                }
                
                // 点击消息后显示操作按钮：用户消息可编辑，AI 消息可重新生成。
                androidx.compose.animation.AnimatedVisibility(
                    visible = showActions && (
                        onCopy != null || onDelete != null ||
                            (!isUser && (onPlayTTS != null || onRegenerate != null)) ||
                            (isUser && onEdit != null)
                        )
                ) {
                    Row(
                        modifier = Modifier
                            .padding(top = 8.dp)
                            .align(Alignment.End),
                        horizontalArrangement = Arrangement.spacedBy(4.dp)
                    ) {
                        // TTS 播放按钮
                        if (!isUser && onPlayTTS != null) {
                            IconButton(
                                onClick = { onPlayTTS(message.id) },
                                modifier = Modifier.size(32.dp)
                            ) {
                                Icon(
                                    imageVector = if (message.isPlaying) Icons.Rounded.Stop else Icons.Rounded.PlayArrow,
                                    contentDescription = if (message.isPlaying) "停止播放" else "播放语音",
                                    tint = TextSecondary,
                                    modifier = Modifier.size(18.dp)
                                )
                            }
                        }

                        if (isUser && onEdit != null) {
                            IconButton(
                                onClick = { onEdit(message.id, message.text) },
                                modifier = Modifier.size(32.dp)
                            ) {
                                Icon(
                                    imageVector = Icons.Rounded.Edit,
                                    contentDescription = "编辑请求",
                                    tint = TextSecondary,
                                    modifier = Modifier.size(16.dp)
                                )
                            }
                        }

                        if (!isUser && onRegenerate != null) {
                            IconButton(
                                onClick = { onRegenerate(message.id) },
                                modifier = Modifier.size(32.dp)
                            ) {
                                Icon(
                                    imageVector = Icons.Rounded.Refresh,
                                    contentDescription = "重新生成",
                                    tint = TextSecondary,
                                    modifier = Modifier.size(16.dp)
                                )
                            }
                        }
                        
                        // 复制按钮
                        if (onCopy != null) {
                            IconButton(
                                onClick = { onCopy(message.text) },
                                modifier = Modifier.size(32.dp)
                            ) {
                                Icon(
                                    imageVector = Icons.Rounded.ContentCopy,
                                    contentDescription = "复制",
                                    tint = TextSecondary,
                                    modifier = Modifier.size(16.dp)
                                )
                            }
                        }
                        
                        // 删除按钮
                        if (onDelete != null) {
                            IconButton(
                                onClick = { onDelete(message.id) },
                                modifier = Modifier.size(32.dp)
                            ) {
                                Icon(
                                    imageVector = Icons.Rounded.Delete,
                                    contentDescription = "删除",
                                    tint = TextSecondary,
                                    modifier = Modifier.size(16.dp)
                                )
                            }
                        }
                    }
                }

                if (message.variantCount > 1) {
                    Row(
                        modifier = Modifier
                            .padding(top = 4.dp)
                            .align(Alignment.End),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        IconButton(
                            onClick = { onPreviousVariant?.invoke(message.id) },
                            enabled = message.variantIndex > 0,
                            modifier = Modifier.size(28.dp)
                        ) {
                            Icon(
                                Icons.AutoMirrored.Rounded.KeyboardArrowLeft,
                                contentDescription = "上一个版本",
                                modifier = Modifier.size(17.dp)
                            )
                        }
                        Text(
                            text = "${message.variantIndex + 1} / ${message.variantCount}",
                            style = MaterialTheme.typography.labelSmall,
                            color = TextTertiary
                        )
                        IconButton(
                            onClick = { onNextVariant?.invoke(message.id) },
                            enabled = message.variantIndex < message.variantCount - 1,
                            modifier = Modifier.size(28.dp)
                        ) {
                            Icon(
                                Icons.AutoMirrored.Rounded.KeyboardArrowRight,
                                contentDescription = "下一个版本",
                                modifier = Modifier.size(17.dp)
                            )
                        }
                    }
                }
            }
        }
    }
}

/**
 * 消息图片组件
 */
@Composable
private fun MessageImage(
    imageUrl: String,
    @Suppress("UNUSED_PARAMETER") isUser: Boolean,
    onImageClick: ((String) -> Unit)?,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val appPreferences = remember { context.applicationContext.avelineAppPreferences() }
    val resolvedUrl = remember(imageUrl) { resolveImageUrl(imageUrl, appPreferences.backendUrl) }
    AsyncImage(
        model = resolvedUrl,
        contentDescription = "图片消息",
        modifier = modifier
            .clip(RoundedCornerShape(8.dp))
            .clickable(enabled = onImageClick != null) {
                onImageClick?.invoke(resolvedUrl)
            },
        contentScale = ContentScale.FillWidth,
        placeholder = painterResource(android.R.drawable.ic_menu_gallery),
        error = painterResource(android.R.drawable.ic_menu_report_image)
    )
}

private fun isRetractionText(value: String): Boolean {
    val trimmed = value.trim()
    return (trimmed.startsWith("（") && trimmed.endsWith("）")) ||
        (trimmed.startsWith("(") && trimmed.endsWith(")"))
}

private fun unwrapRetractionText(value: String): String {
    val trimmed = value.trim()
    return if (isRetractionText(trimmed)) trimmed.substring(1, trimmed.length - 1).trim() else trimmed
}

/**
 * 剥离 [MEME]/[IMG]/[BM]/[VOICE] 媒体标签（含半角/全角括号、半角/全角冒号）。
 *
 * 后端 _send_chunk 已在每个 chunk 发送前剥离过一次，这里兜底防边界情况
 * （如消息从本地 DB 重新加载时，DB 里存的是含标签的原始文本）。
 */
private val _MEDIA_TAG_REGEX = Regex("""[\[［](?:MEME|IMG|BM|VOICE)(?:[：:][^\]］]*)?[\]］]""", RegexOption.IGNORE_CASE)

private fun stripMediaTags(text: String): String {
    return _MEDIA_TAG_REGEX.replace(text, "").trim()
}

/**
 * 去除文本末尾的中文句号或英文句号
 * 参考PC web前端的逻辑：句号省略不显示
 */
private fun stripTrailingPeriod(text: String): String {
    return text.trimEnd('。', '.')
}

/**
 * 构建带括号内容特殊样式的AnnotatedString
 * 参考PC web前端的smartSegmentText逻辑：
 * - 括号内容(开心)使用斜体+淡色显示
 * - 普通文本正常显示
 */
private fun buildAnnotatedStringWithRetraction(text: String): AnnotatedString {
    return buildAnnotatedString {
        var lastIndex = 0

        for (match in RETRACTION_REGEX.findAll(text)) {
            // 括号前的普通文本
            if (match.range.first > lastIndex) {
                val before = text.substring(lastIndex, match.range.first)
                if (before.isNotEmpty()) {
                    append(before)
                }
            }
            
            // 括号内容 - 去掉括号，使用斜体+淡色样式（参考PC web的retraction样式）
            val innerText = match.value.substring(1, match.value.length - 1).trim()
            if (innerText.isNotEmpty()) {
                withStyle(SpanStyle(
                    color = TextSecondary,
                    fontStyle = FontStyle.Italic,
                    fontSize = 13.sp,
                    letterSpacing = 0.5.sp
                )) {
                    append(innerText)
                }
            }
            
            lastIndex = match.range.last + 1
        }
        
        // 剩余的普通文本
        if (lastIndex < text.length) {
            append(text.substring(lastIndex))
        }
    }
}

/**
 * 系统消息气泡
 */
@Composable
fun SystemMessageBubble(
    text: String,
    modifier: Modifier = Modifier
) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 24.dp, vertical = 8.dp),
        contentAlignment = Alignment.Center
    ) {
        Surface(
            shape = RoundedCornerShape(12.dp),
            color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.2f)
        ) {
            Text(
                text = text,
                style = MaterialTheme.typography.labelMedium,
                color = TextTertiary,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)
            )
        }
    }
}

/**
 * 图片消息气泡
 */
@Composable
fun ImageMessageBubble(
    imageUrl: String,
    isUser: Boolean,
    onImageClick: ((String) -> Unit)? = null,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 4.dp),
        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start
    ) {
        val context = LocalContext.current
        val appPreferences = remember { context.applicationContext.avelineAppPreferences() }
        val resolvedUrl = remember(imageUrl) { resolveImageUrl(imageUrl, appPreferences.backendUrl) }
        Surface(
            modifier = Modifier
                .widthIn(max = 200.dp)
                .clip(RoundedCornerShape(12.dp))
                .clickable(enabled = onImageClick != null) {
                    onImageClick?.invoke(resolvedUrl)
                },
            shape = RoundedCornerShape(12.dp),
            color = Color.Transparent
        ) {
            AsyncImage(
                model = resolvedUrl,
                contentDescription = "图片消息",
                modifier = Modifier.fillMaxWidth(),
                contentScale = ContentScale.FillWidth,
                placeholder = painterResource(android.R.drawable.ic_menu_gallery),
                error = painterResource(android.R.drawable.ic_menu_report_image)
            )
        }
    }
}
