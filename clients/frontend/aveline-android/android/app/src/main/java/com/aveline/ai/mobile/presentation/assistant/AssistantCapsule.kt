package com.aveline.ai.mobile.presentation.assistant

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateDpAsState
// InfiniteTransition.animateFloat 是扩展函数，必须单独 import：
// 少了它编译器不是报「找不到 animateFloat」，而是把类型推不出来，
// 连带后面几十行 Float/Double 匹配和 abs/sin 重载全部塌掉，报错位置会离这里很远。
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.theme.CardBorder
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.sin

/**
 * 底部语音助手胶囊。
 *
 * 这是一个**纯展示 + 纯手势**的组件：不引用 ViewModel、不碰 Android  APIs，
 * 所以将来无论是继续挂在 MainActivity 上，还是整块搬到悬浮窗 Service 的
 * ComposeView 里、搬到手表端，都能直接复用。
 *
 * 视觉约定：任何时候都是**一根完整的小圆柱**（圆角 = 高度的一半），
 * - 待命：长度最短、亮度最低，中心光点 + 外扩呼吸涟漪；
 * - 被唤醒：横向舒展开，内部换成声波 / 转写文本 / 思考圆点，并整体提亮。
 *
 * 颜色全部由外部传进来的 [accent] 驱动（默认是情绪色），因此它会跟着
 * App 的呼吸背景一起换色，不会出现「第二个主题」。
 *
 * @param stage 当前展示阶段
 * @param accent 强调色（品牌色 / 情绪色 / 出错时的红色）
 * @param onTap 轻点：待命时唤醒，正在听时收声
 * @param onLongPress 长按：收起胶囊
 * @param onDrag 拖动中，参数是本次拖动的像素增量
 * @param onDragEnd 拖动结束，用于写回位置并吸附
 * @param onTextChange 输入面板里文字变化
 * @param onSubmitText 提交输入框里的内容（软键盘「发送」键或点发送按钮）
 * @param onVoiceInput 在输入面板里改走语音
 */
@Composable
fun AssistantCapsule(
    stage: AssistantCapsuleStage,
    accent: Color,
    modifier: Modifier = Modifier,
    onTap: () -> Unit = {},
    onLongPress: () -> Unit = {},
    onDrag: (deltaXPx: Float, deltaYPx: Float) -> Unit = { _, _ -> },
    onDragEnd: () -> Unit = {},
    onTextChange: (String) -> Unit = {},
    onSubmitText: () -> Unit = {},
    onVoiceInput: () -> Unit = {}
) {
    AnimatedVisibility(
        visible = stage !is AssistantCapsuleStage.Dismissed,
        modifier = modifier.semantics { contentDescription = "语音助手" },
        enter = fadeIn(animationSpec = tween(200)) +
            scaleIn(
                animationSpec = tween(280, easing = FastOutSlowInEasing),
                initialScale = 0.55f,
                transformOrigin = TransformOrigin(0.5f, 1f)
            ) +
            slideInVertically(animationSpec = tween(280, easing = FastOutSlowInEasing)) { it / 3 },
        exit = fadeOut(animationSpec = tween(160)) +
            scaleOut(
                animationSpec = tween(160),
                targetScale = 0.7f,
                transformOrigin = TransformOrigin(0.5f, 1f)
            ) +
            slideOutVertically(animationSpec = tween(160)) { it / 3 }
    ) {
        CapsuleBody(
            stage = stage,
            accent = accent,
            onTap = onTap,
            onLongPress = onLongPress,
            onDrag = onDrag,
            onDragEnd = onDragEnd,
            onTextChange = onTextChange,
            onSubmitText = onSubmitText,
            onVoiceInput = onVoiceInput
        )
    }
}

@Composable
private fun CapsuleBody(
    stage: AssistantCapsuleStage,
    accent: Color,
    onTap: () -> Unit,
    onLongPress: () -> Unit,
    onDrag: (Float, Float) -> Unit,
    onDragEnd: () -> Unit,
    onTextChange: (String) -> Unit,
    onSubmitText: () -> Unit,
    onVoiceInput: () -> Unit
) {
    val active = stage !is AssistantCapsuleStage.Idle && stage !is AssistantCapsuleStage.Dismissed

    val capsuleWidth by animateDpAsState(
        targetValue = CapsuleGeometry.widthFor(stage),
        animationSpec = tween(durationMillis = 300, easing = FastOutSlowInEasing),
        label = "capsule_width"
    )

    val breatheTransition = rememberInfiniteTransition(label = "capsule_breathe")
    val breatheScale by breatheTransition.animateFloat(
        initialValue = 1f,
        targetValue = 1.035f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1800, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "breathe_scale"
    )
    val breatheGlow by breatheTransition.animateFloat(
        initialValue = 0.18f,
        targetValue = 0.34f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1800, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "breathe_glow"
    )

    val shape = RoundedCornerShape(percent = 50)

    Box(contentAlignment = Alignment.Center) {
        // 外光晕：比本体大一圈的径向渐变，纯装饰，不参与手势
        Box(
            modifier = Modifier
                .size(
                    width = capsuleWidth + CapsuleGeometry.glowBleed * 2,
                    height = CapsuleGeometry.height + CapsuleGeometry.glowBleed * 2
                )
                .clip(shape)
                .background(
                    brush = Brush.radialGradient(
                        colors = listOf(accent.copy(alpha = 0.5f), Color.Transparent)
                    )
                )
                // 待命时光晕跟着呼吸慢慢明灭；被唤醒后固定提亮，把注意力拉过来
                .then(if (active) Modifier.alpha(0.85f) else Modifier.alpha(breatheGlow))
        )

        Row(
            modifier = Modifier
                .size(width = capsuleWidth, height = CapsuleGeometry.height)
                .graphicsLayer {
                    scaleX = if (active) 1f else breatheScale
                    scaleY = if (active) 1f else breatheScale
                }
                .clip(shape)
                .background(
                    brush = Brush.horizontalGradient(
                        listOf(accent.copy(alpha = 0.34f), accent.copy(alpha = 0.12f))
                    ),
                    shape = shape
                )
                .border(width = 1.dp, color = CardBorder, shape = shape)
                // 手势必须挂在 padding 之前：放在 padding 之后会把可点-hotspot 缩到内容区，
                // 胶囊两侧的圆角边缘点不到。
                .pointerInput(Unit) {
                    detectTapGestures(
                        onTap = { onTap() },
                        onLongPress = { onLongPress() }
                    )
                }
                .pointerInput(Unit) {
                    detectDragGestures(
                        onDragEnd = { onDragEnd() },
                        onDragCancel = { onDragEnd() }
                    ) { _, dragAmount ->
                        onDrag(dragAmount.x, dragAmount.y)
                    }
                }
                .padding(horizontal = CapsuleGeometry.horizontalPadding),
            verticalAlignment = Alignment.CenterVertically
        ) {
            CapsuleCore(
                accent = accent,
                level = levelFor(stage),
                active = active
            )
            CapsuleContent(
                stage = stage,
                accent = accent,
                onTextChange = onTextChange,
                onSubmitText = onSubmitText,
                onVoiceInput = onVoiceInput
            )
        }
    }
}

/** 各阶段驱动核心光点的音量：说话/复述时给一个固定幅度，让它看起来在输出声音。 */
private fun levelFor(stage: AssistantCapsuleStage): Float = when (stage) {
    is AssistantCapsuleStage.Listening -> stage.level.coerceIn(0f, 1f)
    is AssistantCapsuleStage.Replying -> 0.45f
    else -> 0f
}

/** 胶囊左端恒定存在的「核心光点」，是所有阶段共用的视觉锚点。 */
@Composable
private fun CapsuleCore(
    accent: Color,
    level: Float,
    active: Boolean,
    modifier: Modifier = Modifier
) {
    val ripple by rememberInfiniteTransition(label = "capsule_core").animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 2200, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "core_ripple"
    )

    Canvas(modifier = modifier.size(CapsuleGeometry.coreSize)) {
        val unit = size.minDimension / 2f

        if (active) {
            drawCircle(
                color = accent.copy(alpha = 0.3f),
                radius = unit * (0.4f + level * 0.7f),
                center = center
            )
        } else {
            // 待命时两圈错相位的呼吸涟漪：手机助手就该有个「还活着」的暗示
            repeat(2) { index ->
                val phase = (ripple + index * 0.5f) % 1f
                drawCircle(
                    color = accent.copy(alpha = (1f - phase) * 0.3f),
                    radius = unit * (0.35f + phase * 0.7f),
                    center = center
                )
            }
        }

        drawCircle(
            color = accent.copy(alpha = if (active) 1f else 0.8f),
            radius = unit * (0.2f + level * 0.06f),
            center = center
        )
    }
}

/** 胶囊右半段的内容区，随阶段切换。 */
@Composable
private fun RowScope.CapsuleContent(
    stage: AssistantCapsuleStage,
    accent: Color,
    onTextChange: (String) -> Unit,
    onSubmitText: () -> Unit,
    onVoiceInput: () -> Unit
) {
    Box(
        modifier = Modifier.weight(1f),
        contentAlignment = Alignment.CenterStart
    ) {
        when (stage) {
            AssistantCapsuleStage.Dismissed,
            AssistantCapsuleStage.Idle -> Unit

            is AssistantCapsuleStage.Composing -> {
                Row(
                    modifier = Modifier.fillMaxSize(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    AssistantTextField(
                        value = stage.text,
                        onValueChange = onTextChange,
                        onSubmit = onSubmitText,
                        accent = accent,
                        modifier = Modifier.weight(1f)
                    )
                    CapsuleIconButton(
                        icon = Icons.Filled.Mic,
                        label = "改用语音",
                        onClick = onVoiceInput,
                        tint = accent
                    )
                    CapsuleIconButton(
                        icon = Icons.AutoMirrored.Filled.Send,
                        label = "发送",
                        onClick = onSubmitText,
                        enabled = stage.text.isNotBlank(),
                        tint = accent
                    )
                }
            }

            is AssistantCapsuleStage.Listening -> {
                if (stage.transcript.isBlank()) {
                    CapsuleWaveform(
                        modifier = Modifier.fillMaxSize(),
                        accent = accent,
                        level = stage.level,
                        barCount = 9
                    )
                } else {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        CapsuleWaveform(
                            modifier = Modifier.width(48.dp).height(24.dp),
                            accent = accent,
                            level = stage.level,
                            barCount = 5
                        )
                        Text(
                            text = stage.transcript,
                            modifier = Modifier.weight(1f),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            style = MaterialTheme.typography.labelLarge,
                            color = TextPrimary
                        )
                    }
                }
            }

            AssistantCapsuleStage.Thinking -> {
                ThinkingDots(
                    modifier = Modifier.fillMaxSize(),
                    accent = accent
                )
            }

            is AssistantCapsuleStage.Replying -> {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    CapsuleWaveform(
                        modifier = Modifier.width(40.dp).height(24.dp),
                        accent = accent,
                        level = 0.45f,
                        barCount = 5
                    )
                    Text(
                        text = stage.text,
                        modifier = Modifier.weight(1f),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        style = MaterialTheme.typography.labelLarge,
                        color = TextPrimary
                    )
                }
            }

            is AssistantCapsuleStage.Failed -> {
                Text(
                    text = stage.message,
                    modifier = Modifier.fillMaxWidth(),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.labelMedium,
                    color = accent
                )
            }
        }
    }
}

/**
 * 声波条。
 *
 * 每根条的高度 = 音量 × 位置系数（中间高两端低）× 行进的正弦相位，
 * 三者相乘保证「不出声时也有轻微起伏、出声时立刻窜起来」。
 */
@Composable
private fun CapsuleWaveform(
    accent: Color,
    level: Float,
    barCount: Int,
    modifier: Modifier = Modifier
) {
    val phase by rememberInfiniteTransition(label = "capsule_waveform").animateFloat(
        initialValue = 0f,
        // 写成 2f * PI.toFloat() 而不是 (2 * PI).toFloat()：
        // 后者中间量是 Double，一旦 sine 那边被推成 Double，后面 float 的计算就一路类型不匹配。
        targetValue = 2f * PI.toFloat(),
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1500, easing = LinearEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "waveform_phase"
    )

    Canvas(modifier = modifier) {
        // 展开动画途中宽度可能为 0，此时直接跳过绘制，避免算出负间距
        if (size.width <= 0f || size.height <= 0f) return@Canvas

        val barWidth = 3.dp.toPx()
        val gap = (size.width - barCount * barWidth) / (barCount - 1)
        val amp = level.coerceIn(0f, 1f)
        val middle = (barCount - 1) / 2f

        val brush = Brush.verticalGradient(
            colors = listOf(accent, accent.copy(alpha = 0.45f)),
            startY = 0f,
            endY = size.height
        )

        for (index in 0 until barCount) {
            val wave = sin(phase + index * 0.7f)
            val centerFactor = 1f - abs(index - middle) / middle.coerceAtLeast(1f)
            val factor = (0.18f + amp * 0.82f) *
                (0.45f + 0.55f * centerFactor) *
                (0.35f + 0.65f * (wave * 0.5f + 0.5f))
            val barHeight = size.height * factor.coerceIn(0.08f, 1f)

            drawRoundRect(
                brush = brush,
                topLeft = Offset(x = index * (barWidth + gap), y = (size.height - barHeight) / 2f),
                size = Size(barWidth, barHeight),
                cornerRadius = CornerRadius(barWidth / 2f, barWidth / 2f)
            )
        }
    }
}

/** 思考中的三连点。 */
@Composable
private fun ThinkingDots(
    accent: Color,
    modifier: Modifier = Modifier
) {
    val transition = rememberInfiniteTransition(label = "capsule_thinking")
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(5.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically
    ) {
        repeat(3) { index ->
            val alpha by transition.animateFloat(
                initialValue = 0.25f,
                targetValue = 1f,
                animationSpec = infiniteRepeatable(
                    animation = tween(
                        durationMillis = 380,
                        delayMillis = index * 140,
                        easing = FastOutSlowInEasing
                    ),
                    repeatMode = RepeatMode.Reverse
                ),
                label = "thinking_dot_$index"
            )
            Box(
                modifier = Modifier
                    .size(6.dp)
                    .clip(CircleShape)
                    .background(accent.copy(alpha = alpha))
            )
        }
    }
}

/**
 * 胶囊里的单行输入框。
 *
 * 用 [BasicTextField] 而不是 Material 的 `TextField`：后者自带一圈描边和 56dp 最小高度，
 * 塞进 44dp 高的圆柱里会直接把形状顶破；这里只取一个裸输入区，外观由胶囊自己负责。
 */
@OptIn(ExperimentalComposeUiApi::class)
@Composable
private fun AssistantTextField(
    value: String,
    onValueChange: (String) -> Unit,
    onSubmit: () -> Unit,
    accent: Color,
    modifier: Modifier = Modifier
) {
    val focusRequester = remember { FocusRequester() }
    val keyboard = LocalSoftwareKeyboardController.current

    // 一进面板就抢焦点并弹键盘：用户点胶囊的意图就是"我要跟它说话/打字"，
    // 还要再点一下输入框才弹出键盘会显得迟钝。
    //
    // 键盘能不能弹出来取决于悬浮窗是否可聚焦 —— 那部分由 AssistantOverlayService
    // 监听阶段变化去切窗口 flag（默认窗口是 FLAG_NOT_FOCUSABLE，压根不会弹键盘）。
    LaunchedEffect(Unit) {
        focusRequester.requestFocus()
        keyboard?.show()
    }

    BasicTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier.focusRequester(focusRequester),
        singleLine = true,
        textStyle = MaterialTheme.typography.bodyMedium.copy(color = TextPrimary),
        cursorBrush = SolidColor(accent),
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
        keyboardActions = KeyboardActions(onSend = { onSubmit() }),
        decorationBox = { innerTextField ->
            Box(contentAlignment = Alignment.CenterStart) {
                if (value.isEmpty()) {
                    Text(
                        text = "说点什么…",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextTertiary,
                        maxLines = 1
                    )
                }
                innerTextField()
            }
        }
    )
}

/** 胶囊内部的圆形小图标按钮（改用语音 / 发送）。 */
@Composable
private fun CapsuleIconButton(
    icon: ImageVector,
    label: String,
    onClick: () -> Unit,
    tint: Color,
    enabled: Boolean = true,
    modifier: Modifier = Modifier
) {
    Box(
        modifier = modifier
            .size(28.dp)
            .clip(CircleShape)
            .clickable(enabled = enabled, onClick = onClick)
            .semantics { contentDescription = label },
        contentAlignment = Alignment.Center
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = if (enabled) tint else tint.copy(alpha = 0.35f),
            modifier = Modifier.size(16.dp)
        )
    }
}
