package com.aveline.ai.mobile.presentation.components

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
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
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.graphics.ColorFilter
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
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil.compose.AsyncImagePainter
import coil.compose.SubcomposeAsyncImage
import coil.compose.SubcomposeAsyncImageContent
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
import com.aveline.ai.mobile.utils.CoilImageModel
import com.aveline.ai.mobile.utils.ImageUrlResolver
import com.aveline.ai.mobile.utils.text.TextSegmenter
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
    /** 视频/动图地址，非空时气泡内渲染 ExoPlayer 播放器而不是图片。 */
    val videoUrl: String? = null,
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
 * - 点击气泡回调（由外层决定是否展开操作栏）
 *
 * 操作按钮不在这里渲染：统一由 `ChatMessageActionBar` 承担，
 * 本组件只负责把点击事件透出去，避免两套操作行实现并存。
 *
 * @param message 消息数据
 * @param onToggleActions 点击气泡回调，用于切换操作栏显隐
 * @param onImageClick 图片点击回调
 * @param modifier 修饰符
 */
@Composable
fun MessageBubble(
    message: MessageData,
    /** 点击气泡时回调，用于切换该条消息的操作栏（复制 / 重新生成 / 更多…）显隐。 */
    onToggleActions: (() -> Unit)? = null,
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
                    onToggleActions?.invoke()
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
                // 注意：后端偶发会下发空白地址，空白时不要渲染图片气泡，
                // 否则 Coil 加载空地址失败会显示破图占位（三角感叹号）
                message.imageUrl?.takeIf { it.isNotBlank() }?.let { imageUrl ->
                    MessageImage(
                        imageUrl = imageUrl,
                        isUser = isUser,
                        onImageClick = onImageClick,
                        modifier = Modifier.padding(
                            bottom = if (message.text.isNotBlank()) 8.dp else 0.dp
                        )
                    )
                }

                // 视频/动图显示（如果有）。
                // 用户自己发出的视频保留原声和控制条；AI 侧推送的短视频静音循环播放。
                message.videoUrl?.takeIf { it.isNotBlank() }?.let { videoUrl ->
                    VideoMessageBubble(
                        videoUrl = videoUrl,
                        muted = !isUser,
                        showController = isUser,
                        modifier = Modifier.padding(
                            bottom = if (message.text.isNotBlank()) 8.dp else 0.dp
                        )
                    )
                }
                
                // 消息文本 - AI 消息按 QQ 同一套断句规则拆成多个"气泡"，
                // 并过滤模型学去的时间戳与句末多余标点（见 utils/text/TextSegmenter.kt）
                if (cleanedText.isNotBlank()) {
                    if (isUser) {
                        Text(
                            text = AnnotatedString(cleanedText),
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
                        val displaySegments = TextSegmenter.splitForDisplay(cleanedText)
                            .ifEmpty { listOf(cleanedText) }
                        displaySegments.forEachIndexed { index, segment ->
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .semantics { contentDescription = "AI消息: $cleanedText" }
                                    .padding(
                                        bottom = if (index == displaySegments.lastIndex) 0.dp else 6.dp
                                    )
                            ) {
                                NotesMarkdownRenderer(text = segment)
                            }
                        }
                    }
                }
            }
        }
    }
}

/**
 * 消息图片组件。
 *
 * 显示策略与 QQ 类即时通讯接近，而不是把图片拉满整行：
 * - 按图片自身宽高比等比缩放显示，只缩不放，小贴纸不会被拉糊；
 * - 图片消息（照片/AI 生成图）限宽 260dp/高 320dp；表情包
 *   （/output/image/memes/ 下的贴纸）限 150dp 见方；
 * - 不做圆角裁剪：PNG 透明区域、GIF/WebP 都能原样显示。
 *
 * 用 SubcomposeAsyncImage 是为了在组合作用域里读到图片解码后的固有尺寸，
 * 外层盒子随图片实际显示大小收缩，而不是撑满整行。
 */
@OptIn(coil.annotation.ExperimentalCoilApi::class)
@Composable
private fun MessageImage(
    imageUrl: String,
    @Suppress("UNUSED_PARAMETER") isUser: Boolean,
    onImageClick: ((String) -> Unit)?,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val appPreferences = remember { context.applicationContext.avelineAppPreferences() }
    // 生效地址必须作为重组依赖：局域网/公网切换后要重新解析，否则图片会一直去连旧通道的
    // 地址（那个地址此刻已不通或绕远路）。SharedPreferences 不可观察，所以观察 Flow
    // 而不是直接读 effectiveBackendUrl —— 后者读到的值变化不会触发重组。
    val activeBackend by appPreferences.effectiveBackendUrlFlow.collectAsStateWithLifecycle()
    val resolvedUrl = remember(imageUrl, activeBackend) {
        resolveImageUrl(imageUrl, activeBackend)
    }
    val imageModel = remember(resolvedUrl) { CoilImageModel.build(context, resolvedUrl) }

    val isMeme = isMemeImageUrl(resolvedUrl)
    val maxWidth = if (isMeme) MemeMaxWidth else ImageMaxWidth
    val maxHeight = if (isMeme) MemeMaxHeight else ImageMaxHeight

    SubcomposeAsyncImage(
        model = imageModel,
        contentDescription = null,
        contentScale = ContentScale.Fit,
        modifier = modifier.clickable(enabled = onImageClick != null) {
            onImageClick?.invoke(resolvedUrl)
        }
    ) {
        when (val state = painter.state) {
            is AsyncImagePainter.State.Loading -> ImageLoadingPlaceholder()
            is AsyncImagePainter.State.Error -> {
                // 保留破图提示方便排查，但只占提示图标区域，不再占整行
                Box(
                    modifier = Modifier.size(PlaceholderImageWidth, PlaceholderImageHeight),
                    contentAlignment = Alignment.Center
                ) {
                    Image(
                        painter = painterResource(android.R.drawable.ic_menu_report_image),
                        contentDescription = "图片加载失败",
                        colorFilter = ColorFilter.tint(TextTertiary)
                    )
                }
            }
            is AsyncImagePainter.State.Success -> {
                val drawable = state.result.drawable
                val (width, height) = scaledImageDisplaySize(
                    drawable.intrinsicWidth,
                    drawable.intrinsicHeight,
                    maxWidth,
                    maxHeight
                )
                // 直接把等比后的尺寸施加给内容，外层盒子随之收缩到图片实际大小；
                // 不能包 Box（Box 的 receiver 不是 SubcomposeAsyncImageScope）
                SubcomposeAsyncImageContent(modifier = Modifier.size(width, height))
            }
            else -> {
                // 无状态（空 model 等）：占位即可
                ImageLoadingPlaceholder()
            }
        }
    }
}

/** 加载中占位：常见 4:3 区域 + 小转圈，避免图片出现前后消息高度突变。 */
@OptIn(coil.annotation.ExperimentalCoilApi::class)
@Composable
private fun ImageLoadingPlaceholder() {
    Box(
        modifier = Modifier.size(PlaceholderImageWidth, PlaceholderImageHeight),
        contentAlignment = Alignment.Center
    ) {
        CircularProgressIndicator(
            modifier = Modifier.size(20.dp),
            strokeWidth = 2.dp
        )
    }
}

/** 普通图片消息最大显示尺寸（dp），等比缩放、超出才缩小。 */
private val ImageMaxWidth = 260.dp
private val ImageMaxHeight = 320.dp

/** 表情包（贴纸）最大显示尺寸（dp）。 */
private val MemeMaxWidth = 150.dp
private val MemeMaxHeight = 150.dp

/** 加载中的占位区域尺寸（4:3，避免消息高度突变）。 */
private val PlaceholderImageWidth = 180.dp
private val PlaceholderImageHeight = 135.dp

/** 后端表情包静态资源统一落在 /output/image/memes/ 下，用它区分小表情与大图。 */
private fun isMemeImageUrl(url: String): Boolean =
    url.contains("/memes/", ignoreCase = true)

/**
 * 按图片固有尺寸等比计算显示尺寸：
 * - 等比缩放到 max 框内；
 * - 原始尺寸小于 max 时不放大（小贴纸不会被拉糊）。
 */
internal fun scaledImageDisplaySize(
    intrinsicWidth: Int,
    intrinsicHeight: Int,
    maxWidth: Dp,
    maxHeight: Dp
): Pair<Dp, Dp> {
    if (intrinsicWidth <= 0 || intrinsicHeight <= 0) {
        return maxWidth to maxHeight
    }
    val scale = minOf(
        1f,
        maxWidth.value / intrinsicWidth,
        maxHeight.value / intrinsicHeight
    )
    return (intrinsicWidth * scale).dp to (intrinsicHeight * scale).dp
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
 * 剥离 [MEME]/[IMG]/[BM]/[VOICE]/[VIDEO] 媒体标签（含半角/全角括号、半角/全角冒号）。
 *
 * 后端 _send_chunk 已在每个 chunk 发送前剥离过一次，这里兜底防边界情况
 * （如消息从本地 DB 重新加载时，DB 里存的是含标签的原始文本）。
 *
 * VIDEO 必须包含：早期后端正则漏了这个标签，Web/Android 通道会把 "[VIDEO]"
 * 当正文原样下发给前端，气泡上就会出现裸标签。
 */
private val _MEDIA_TAG_REGEX = Regex("""[\[［](?:MEME|IMG|BM|VOICE|VIDEO)(?:[：:][^\]］]*)?[\]］]""", RegexOption.IGNORE_CASE)

private fun stripMediaTags(text: String): String {
    return _MEDIA_TAG_REGEX.replace(text, "").trim()
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

