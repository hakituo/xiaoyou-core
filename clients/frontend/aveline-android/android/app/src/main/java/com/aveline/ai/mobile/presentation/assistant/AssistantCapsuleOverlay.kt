package com.aveline.ai.mobile.presentation.assistant

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.aveline.ai.mobile.presentation.theme.EmotionRed
import com.aveline.ai.mobile.presentation.theme.Primary

/**
 * 悬浮窗里的助手胶囊内容。
 *
 * 这一层只做三件事：把 ViewModel 的状态接到纯展示的 [AssistantCapsule] 上、
 * 决定强调色、把拖动事件交给外部（由 AssistantOverlayService 去改窗口坐标）。
 *
 * 位置**不在这里算**：胶囊挂在系统窗口上，坐标就是 `WindowManager.LayoutParams.x/y`，
 * 拖动直接改窗口坐标，所以能拖到屏幕任何角落（含输入法之上），不受任何容器矩形限制。
 *
 * @param viewModel 由 Service 手工构造后传入 —— Service 里没有 Hilt 的 ViewModelFactory，
 *                  走不了 `hiltViewModel()`，见 AssistantOverlayService 的说明
 * @param onDrag 拖动增量（px），外部据此移动窗口
 * @param onDragEnd 松手，外部据此落盘坐标
 */
@Composable
fun AssistantCapsuleOverlay(
    viewModel: AssistantCapsuleViewModel,
    modifier: Modifier = Modifier,
    accent: Color = Primary,
    onDrag: (deltaXPx: Float, deltaYPx: Float) -> Unit = { _, _ -> },
    onDragEnd: () -> Unit = {}
) {
    val stage by viewModel.stage.collectAsStateWithLifecycle()
    val effectiveAccent = if (stage is AssistantCapsuleStage.Failed) EmotionRed else accent

    // 这里绝对不能用 fillMaxSize：窗口是 WRAP_CONTENT 的，内容一旦去填满父容器，
    // 测量结果会一路顶到整屏，窗口就变成全屏窗口 —— 空白区域开始吃触摸，
    // 用户会发现整个屏幕点不动（悬浮窗最经典的坑）。
    Box(modifier = modifier.wrapContentSize()) {
        AssistantCapsule(
            stage = stage,
            accent = effectiveAccent,
            onTap = viewModel::onCapsuleTap,
            onLongPress = viewModel::onCapsuleLongPress,
            onDrag = onDrag,
            onDragEnd = onDragEnd,
            onTextChange = viewModel::onTextChange,
            onSubmitText = viewModel::onSubmitText,
            onVoiceInput = viewModel::onVoiceInput
        )
    }
}
