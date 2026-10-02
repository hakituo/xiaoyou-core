package com.aveline.ai.mobile.presentation.assistant

import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * 语音助手胶囊的展示阶段。
 *
 * 这是一层「纯前端」的展示状态机：不关心内容是怎么来的（点击、唤醒词、通知、深链都行），
 * 只负责描述这一刻底部那根小圆柱应该长什么样。
 *
 * 后续接真实唤醒时，只需由外部（唤醒词服务 / 前台服务 / 深链）调用
 * [com.aveline.ai.mobile.presentation.assistant.AssistantCapsuleViewModel.wake]，
 * 把胶囊推进到 Listening 即可，本文件不用改。
 */
sealed class AssistantCapsuleStage {

    /** 完全隐藏：不占布局、不响应手势。 */
    data object Dismissed : AssistantCapsuleStage()

    /**
     * 待命：屏幕底部一根低亮度的小圆柱，随时可以被点击或唤醒。
     */
    data object Idle : AssistantCapsuleStage()

    /**
     * 展开成输入面板：能打字，也能一键切回语音。
     *
     * 这是「点一下胶囊」的默认落点。纯语音在安静的场合完全没法用
     * （会议、图书馆、旁边有人），所以输入框属于**前端自己就该有**的能力，
     * 跟后端接没接好无关 —— 后端只决定发出去之后有没有人回答。
     *
     * 处在这个阶段时，悬浮窗需要临时变成可聚焦窗口（否则输入法弹不出来），
     * 由 AssistantOverlayService 监听阶段变化去切换窗口 flag。
     *
     * @param text 输入框里的当前内容
     */
    data class Composing(val text: String = "") : AssistantCapsuleStage()

    /**
     * 正在听。
     *
     * @param level 归一化音量 0f~1f，驱动声波条起伏
     * @param transcript 已识别出的流式文本，为空表示还没吐字
     */
    data class Listening(
        val level: Float = 0f,
        val transcript: String = ""
    ) : AssistantCapsuleStage()

    /** 听完了，正在等结果（ASR 收尾 / 后续就是对端思考）。 */
    data object Thinking : AssistantCapsuleStage()

    /**
     * 有结果要念给用户看。
     *
     * @param text 要展示的文本（现阶段就是 ASR 转写结果，将来换成助手回复）
     */
    data class Replying(val text: String) : AssistantCapsuleStage()

    /** 出错：录音权限缺失、引擎不可用、没听清等。 */
    data class Failed(val message: String) : AssistantCapsuleStage()
}

/**
 * 胶囊在不同阶段下的几何尺寸。
 *
 * Idle 收得很短（真·小圆柱），一旦开始听就横向舒展开容纳声波和转写文本，
 * 宽度变化走 tween 动画，观感上是「被唤醒后亮起来」而不是模式切换。
 */
internal object CapsuleGeometry {
    val height: Dp = 44.dp

    /** 内容区里那个恒定存在的核心光点直径，也是左右内边距的基准。 */
    val coreSize: Dp = 32.dp

    val horizontalPadding: Dp = 12.dp

    val glowBleed: Dp = 22.dp

    fun widthFor(stage: AssistantCapsuleStage): Dp = when (stage) {
        // Dismissed 时不参与组合，但宽度必须给非 0 值：AnimatedVisibility 展开的那一帧
        // 拿 0 宽度去测量会让 Canvas 的 DrawScope 拿到 0 尺寸，进而跳过绘制闪一下。
        AssistantCapsuleStage.Dismissed -> 76.dp
        AssistantCapsuleStage.Idle -> 76.dp
        AssistantCapsuleStage.Thinking -> 136.dp
        is AssistantCapsuleStage.Failed -> 216.dp
        is AssistantCapsuleStage.Replying -> 240.dp
        is AssistantCapsuleStage.Listening -> 240.dp
        // 输入面板要比纯展示态更宽：里面要塞下输入框 + 麦克风 + 发送三个东西
        is AssistantCapsuleStage.Composing -> 316.dp
    }
}
