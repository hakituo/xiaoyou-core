package com.aveline.ai.mobile.presentation.assistant

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.presentation.assistant.ports.AssistantBackendPort
import com.aveline.ai.mobile.presentation.assistant.ports.AssistantReply
import com.aveline.ai.mobile.presentation.assistant.ports.AssistantRequest
import com.aveline.ai.mobile.presentation.assistant.ports.AssistantSpeechPort
import com.aveline.ai.mobile.presentation.assistant.ports.AssistantWakeReason
import com.aveline.ai.mobile.services.VoiceInputManager
import com.aveline.ai.mobile.services.VoiceInputState
import com.aveline.ai.mobile.utils.HapticFeedbackManager
import com.aveline.ai.mobile.utils.HapticFeedbackType
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * 悬浮助手胶囊的驱动。
 *
 * 职责边界：**只做编排，不做实现**。识别找 [VoiceInputManager]，说话找后端端口，
 * 发声找朗读端口 —— 这些将来都会被替换掉，替换不影响本类。
 *
 * 位置不在这里管：胶囊挂在系统窗口上，位置是 `WindowManager.LayoutParams.x/y`，
 * 由 AssistantOverlayService 负责（那样才能拖到屏幕任何角落，包括输入法之上）。
 *
 * 关于录音会话的所有权：
 * [VoiceInputManager] 是全局单例，聊天页的输入框也在用它。**同一时刻只能有一路录音**，
 * 因此这里用 [ownsVoiceSession] 标记「这一轮是不是胶囊发起的」，不是自己的会话就完全
 * 不消费它的状态流，避免聊天页一开始录音，悬浮胶囊跟着乱跳。
 */
@HiltViewModel
class AssistantCapsuleViewModel @Inject constructor(
    private val appPreferences: AppPreferences,
    private val voiceInputManager: VoiceInputManager,
    private val backendPort: AssistantBackendPort,
    private val speechPort: AssistantSpeechPort,
    private val haptics: HapticFeedbackManager
) : ViewModel() {

    private val _stage = MutableStateFlow<AssistantCapsuleStage>(
        if (appPreferences.assistantCapsuleEnabled) {
            AssistantCapsuleStage.Idle
        } else {
            AssistantCapsuleStage.Dismissed
        }
    )

    /** 胶囊展示阶段。窗口位置不在这里，见类注释。 */
    val stage: StateFlow<AssistantCapsuleStage> = _stage.asStateFlow()

    /** 本轮录音是否由胶囊发起。 */
    private var ownsVoiceSession = false

    private var returnJob: Job? = null
    private var replyJob: Job? = null

    /** 最近一次唤醒的来源，留作后续差异化打招呼 / 埋点用。 */
    private var lastWakeReason: AssistantWakeReason = AssistantWakeReason.TAP

    /** 对外只读的最近唤醒来源。 */
    val wakeReason: AssistantWakeReason get() = lastWakeReason

    init {
        observeVoiceInput()
    }

    // ── 对外的显隐与唤醒 ──────────────────────────────────────────────────────

    /** 重新显示胶囊（常驻通知点击 / 设置页开关打开 / 唤醒词命中）。 */
    fun show() {
        if (_stage.value is AssistantCapsuleStage.Dismissed) {
            _stage.value = AssistantCapsuleStage.Idle
        }
    }

    /**
     * 收起胶囊。
     *
     * 只把胶囊收起来，**不停服务、不释放麦克风**：手机助手被喊一声就该重新出来，
     * 关服务是设置页开关的事（或系统回收）。
     */
    fun hide() {
        returnJob?.cancel()
        replyJob?.cancel()
        speechPort.stop()
        releaseVoiceSession(cancelRecording = true)
        _stage.value = AssistantCapsuleStage.Dismissed
    }

    /**
     * 唤醒入口。
     *
     * **这就是将来「喊她」要接的那个点**：端侧唤醒词检测命中后，
     * 拿到本 ViewModel 调用 `wake(AssistantWakeReason.WAKE_WORD)`，
     * 之后的流程和现在点胶囊一模一样。
     */
    fun wake(reason: AssistantWakeReason = AssistantWakeReason.TAP) {
        returnJob?.cancel()
        replyJob?.cancel()
        speechPort.stop()

        ownsVoiceSession = true
        lastWakeReason = reason

        // reset 会把上一轮的中间状态清干净（含 sherpa 引擎里残留的 Result），
        // 否则下一次开录会立刻把老文本重放回来
        voiceInputManager.reset()

        _stage.value = AssistantCapsuleStage.Listening(level = 0f, transcript = "")
        haptics.performHapticFeedback(HapticFeedbackType.LIGHT)
        voiceInputManager.startListening()
    }

    /**
     * 轻点胶囊。
     *
     * 待命态点一下**不是**直接开录音，而是展开输入面板：面板里既能打字也能一键转语音。
     * 纯语音在会议、图书馆、旁边有人的场合根本没法用，所以默认落点给"能打字"的那个。
     * 正在听的时候再点一下仍是收声转写（结束这一轮）。
     */
    fun onCapsuleTap() {
        when (_stage.value) {
            is AssistantCapsuleStage.Listening -> voiceInputManager.stopListening()
            // 面板里的点击由输入框和按钮自己处理，胶囊本体不再抢
            is AssistantCapsuleStage.Composing -> Unit
            else -> openComposer()
        }
    }

    /**
     * 长按胶囊。
     *
     * 逐级收起：面板态先收面板，再长按才收起整个胶囊 ——
     * 给用户一个"退一步"的机会，而不是一下把悬浮窗收没了。
     */
    fun onCapsuleLongPress() {
        when (_stage.value) {
            is AssistantCapsuleStage.Composing -> collapseComposer()
            else -> hide()
        }
    }

    /** 展开输入面板。 */
    fun openComposer() {
        returnJob?.cancel()
        replyJob?.cancel()
        speechPort.stop()
        releaseVoiceSession(cancelRecording = true)
        _stage.value = AssistantCapsuleStage.Composing()
        haptics.performHapticFeedback(HapticFeedbackType.LIGHT)
    }

    /** 收起面板回到待命。 */
    fun collapseComposer() {
        if (_stage.value is AssistantCapsuleStage.Composing) {
            _stage.value = AssistantCapsuleStage.Idle
        }
    }

    /** 输入框内容变化。只在面板态下生效，避免别处误写进来。 */
    fun onTextChange(text: String) {
        val current = _stage.value
        if (current is AssistantCapsuleStage.Composing) {
            _stage.value = current.copy(text = text)
        }
    }

    /** 提交输入框里的文字（软键盘「发送」键或点发送按钮）。空内容直接忽略。 */
    fun onSubmitText() {
        val current = _stage.value
        if (current !is AssistantCapsuleStage.Composing) return
        val text = current.text.trim()
        if (text.isEmpty()) return

        haptics.performHapticFeedback(HapticFeedbackType.LIGHT)
        askBackend(text)
    }

    /** 面板里改走语音。 */
    fun onVoiceInput() {
        wake(AssistantWakeReason.TAP)
    }

    // ── VoiceInputManager 状态消费 ────────────────────────────────────────────

    private fun observeVoiceInput() {
        viewModelScope.launch {
            voiceInputManager.state.collect { state ->
                if (!ownsVoiceSession) return@collect
                when (state) {
                    VoiceInputState.Idle -> Unit
                    // Listening 状态已经在 wake() 里置好了，这里覆盖回去会丢掉刚采到的 level
                    VoiceInputState.Recording -> Unit
                    VoiceInputState.Processing -> _stage.value = AssistantCapsuleStage.Thinking
                    is VoiceInputState.Result -> onRecognized(state.text)
                    is VoiceInputState.Error -> fail(state.message)
                }
            }
        }

        viewModelScope.launch {
            voiceInputManager.amplitude.collect { level ->
                val current = _stage.value
                if (current is AssistantCapsuleStage.Listening) {
                    _stage.value = current.copy(level = level.coerceIn(0f, 1f))
                }
            }
        }

        viewModelScope.launch {
            voiceInputManager.partialText.collect { text ->
                val current = _stage.value
                if (current is AssistantCapsuleStage.Listening) {
                    _stage.value = current.copy(transcript = text)
                }
            }
        }
    }

    // ── 内部编排 ──────────────────────────────────────────────────────────────

    private fun onRecognized(text: String) {
        releaseVoiceSession(cancelRecording = false)
        if (text.isBlank()) {
            fail(EMPTY_RECOGNITION_MESSAGE)
            return
        }
        askBackend(text)
    }

    /** 把用户的话交给后端端口拿流式回复。真实实现里这里会跑网络请求（自身负责切线程）。 */
    private fun askBackend(text: String) {
        replyJob?.cancel()
        replyJob = viewModelScope.launch {
            _stage.value = AssistantCapsuleStage.Thinking
            backendPort.reply(AssistantRequest(text = text)).collect { reply ->
                when (reply) {
                    is AssistantReply.Token -> {
                        val previous = _stage.value
                        val merged = if (previous is AssistantCapsuleStage.Replying) {
                            previous.text + reply.text
                        } else {
                            reply.text
                        }
                        _stage.value = AssistantCapsuleStage.Replying(merged)
                    }

                    is AssistantReply.Done -> {
                        _stage.value = AssistantCapsuleStage.Replying(reply.fullText)
                        speechPort.speak(reply.fullText)
                        scheduleReturnToIdle()
                    }

                    is AssistantReply.Failure -> fail(reply.message)
                }
            }
        }
    }

    private fun fail(message: String) {
        replyJob?.cancel()
        speechPort.stop()
        _stage.value = AssistantCapsuleStage.Failed(message)
        haptics.performHapticFeedback(HapticFeedbackType.ERROR)
        scheduleReturnToIdle(delayMillis = FAILURE_HOLD_MS)
    }

    /** 念完 / 报错后自动收回待命态，别让胶囊一直亮着占注意力。 */
    private fun scheduleReturnToIdle(delayMillis: Long = REPLY_HOLD_MS) {
        returnJob?.cancel()
        returnJob = viewModelScope.launch {
            delay(delayMillis)
            when (_stage.value) {
                is AssistantCapsuleStage.Replying,
                is AssistantCapsuleStage.Failed -> _stage.value = AssistantCapsuleStage.Idle
                else -> Unit
            }
        }
    }

    private fun releaseVoiceSession(cancelRecording: Boolean) {
        if (!ownsVoiceSession) return
        ownsVoiceSession = false
        if (cancelRecording) voiceInputManager.cancel()
    }

    override fun onCleared() {
        releaseVoiceSession(cancelRecording = true)
        super.onCleared()
    }

    private companion object {
        const val REPLY_HOLD_MS = 4_000L
        const val FAILURE_HOLD_MS = 2_600L
        const val EMPTY_RECOGNITION_MESSAGE = "没听清，再说一次"
    }
}
