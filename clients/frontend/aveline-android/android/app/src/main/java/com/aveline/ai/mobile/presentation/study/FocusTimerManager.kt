package com.aveline.ai.mobile.presentation.study

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * 番茄钟计时管理器（纯逻辑，与 Android/Compose 无关，可单测）。
 *
 * 负责：
 * - 计时循环（每秒递减 remainingSeconds）
 * - 阶段推进（WORK → BREAK/LONG_BREAK → WORK）
 * - 一个 WORK 阶段自然完成时通知调用方
 * - 阶段变化时通知调用方，由 ViewModel 负责同步后端 FocusSession 生命周期
 *
 * 所有副作用通过回调交给调用方，本类只维护本地 UI 计时状态。
 */
class FocusTimerManager(
    private val scope: CoroutineScope,
    val state: MutableStateFlow<StudyFocusState>,
    private val onWorkCompleted: (StudyFocusState) -> Unit,
    private val onPhaseChanged: (FocusPhase, FocusPhase, StudyFocusState) -> Unit = { _, _, _ -> }
) {
    private var timerJob: Job? = null

    /** 开始 / 暂停计时。后端生命周期由 ViewModel 在调用本方法前后协调。 */
    fun toggle() {
        state.update { it.copy(isRunning = !it.isRunning) }
        if (state.value.isRunning) startLoop() else timerJob?.cancel()
    }

    /** 只暂停本地计时，不切换阶段。 */
    fun pause() {
        timerJob?.cancel()
        state.update { it.copy(isRunning = false) }
    }

    /** 重置当前阶段到初始倒计时（停止计时）。 */
    fun reset() {
        timerJob?.cancel()
        state.update { fs ->
            fs.copy(
                isRunning = false,
                remainingSeconds = phaseSeconds(fs.phase, fs)
            )
        }
    }

    /** 跳过当前阶段。手动跳过 WORK 不计为完成一个番茄，也不触发长休息。 */
    fun skipPhase() {
        transitionPhase(naturalWorkCompleted = false)
    }

    private fun startLoop() {
        timerJob?.cancel()
        timerJob = scope.launch {
            while (isActive) {
                delay(1000)
                val current = state.value
                if (!current.isRunning) continue
                val next = current.remainingSeconds - 1
                if (next > 0) {
                    state.update { it.copy(remainingSeconds = next) }
                } else {
                    transitionPhase(naturalWorkCompleted = current.phase == FocusPhase.WORK)
                }
            }
        }
    }

    /**
     * 推进到下一阶段。
     *
     * 只有 WORK 自然倒计时结束才增加 todayTomatoes/completedCycles；手动跳过不算完成。
     * 阶段剩余时间必须按“新阶段”计算，避免 WORK→BREAK 后仍显示工作时长。
     */
    private fun transitionPhase(naturalWorkCompleted: Boolean) {
        val before = state.value
        val from = before.phase
        val to = nextPhase(from, before, naturalWorkCompleted)

        state.update { current ->
            val completed = if (naturalWorkCompleted && from == FocusPhase.WORK) {
                current.completedCycles + 1
            } else {
                current.completedCycles
            }
            val tomatoes = if (naturalWorkCompleted && from == FocusPhase.WORK) {
                current.todayTomatoes + 1
            } else {
                current.todayTomatoes
            }
            current.copy(
                phase = to,
                remainingSeconds = phaseSeconds(to, current),
                todayTomatoes = tomatoes,
                completedCycles = completed
            )
        }

        if (naturalWorkCompleted && from == FocusPhase.WORK) {
            onWorkCompleted(before)
        }
        onPhaseChanged(from, to, state.value)
    }

    /** WORK 仅在自然完成时按“完成后的周期数”判断是否进入长休息。 */
    private fun nextPhase(
        phase: FocusPhase,
        stateBefore: StudyFocusState,
        naturalWorkCompleted: Boolean
    ): FocusPhase = when (phase) {
        FocusPhase.WORK -> {
            if (!naturalWorkCompleted) {
                FocusPhase.BREAK
            } else {
                val completedAfterThisWork = stateBefore.completedCycles + 1
                if (completedAfterThisWork % stateBefore.cyclesBeforeLongBreak == 0) {
                    FocusPhase.LONG_BREAK
                } else {
                    FocusPhase.BREAK
                }
            }
        }
        FocusPhase.BREAK, FocusPhase.LONG_BREAK -> FocusPhase.WORK
    }

    private fun phaseSeconds(phase: FocusPhase, stateValue: StudyFocusState): Int = when (phase) {
        FocusPhase.WORK -> stateValue.workMinutes * 60
        FocusPhase.BREAK -> stateValue.breakMinutes * 60
        FocusPhase.LONG_BREAK -> stateValue.longBreakMinutes * 60
    }

    fun clear() {
        timerJob?.cancel()
    }
}
