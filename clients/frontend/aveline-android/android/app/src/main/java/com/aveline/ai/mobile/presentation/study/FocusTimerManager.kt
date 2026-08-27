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
 * - 一个 WORK 阶段自然完成时，回调 [onWorkCompleted]（由调用方负责上报后端）
 *
 * 状态以 [MutableStateFlow] 形式暴露，调用方可直接 collect 给 UI。
 * 所有副作用（上报后端）通过构造时传入的回调处理，保持本类纯粹。
 *
 * @property scope 协程作用域，通常传 ViewModel 的 viewModelScope
 * @property state 番茄钟状态流（共享同一实例给 UI）
 * @property onWorkCompleted 一个工作阶段自然完成时触发（参数为完成那一刻的状态）
 */
class FocusTimerManager(
    private val scope: CoroutineScope,
    val state: MutableStateFlow<StudyFocusState>,
    private val onWorkCompleted: (StudyFocusState) -> Unit
) {
    private var timerJob: Job? = null

    /** 开始 / 暂停计时 */
    fun toggle() {
        state.update { it.copy(isRunning = !it.isRunning) }
        if (state.value.isRunning) startLoop() else timerJob?.cancel()
    }

    /** 重置当前阶段到初始倒计时（停止计时） */
    fun reset() {
        timerJob?.cancel()
        state.update { fs ->
            val seconds = when (fs.phase) {
                FocusPhase.WORK -> fs.workMinutes * 60
                FocusPhase.BREAK -> fs.breakMinutes * 60
                FocusPhase.LONG_BREAK -> fs.longBreakMinutes * 60
            }
            fs.copy(isRunning = false, remainingSeconds = seconds)
        }
    }

    /** 跳过当前阶段，进入下一阶段（不触发上报） */
    fun skipPhase() {
        state.update { it.copy(phase = advancePhase(it.phase)) }
        resetPhaseRemaining(state.value.phase)
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
                    val wasWork = current.phase == FocusPhase.WORK
                    state.update { it.copy(phase = advancePhase(it.phase), remainingSeconds = phaseSeconds(it.phase)) }
                    if (wasWork) onWorkCompleted(current)
                }
            }
        }
    }

    /** WORK 完成时推进到休息（每 cyclesBeforeLongBreak 个进入长休息），休息结束回到 WORK */
    private fun advancePhase(phase: FocusPhase): FocusPhase = when (phase) {
        FocusPhase.WORK -> {
            val s = state.value
            val completed = s.completedCycles + 1
            if (completed % s.cyclesBeforeLongBreak == 0) FocusPhase.LONG_BREAK else FocusPhase.BREAK
        }
        FocusPhase.BREAK, FocusPhase.LONG_BREAK -> FocusPhase.WORK
    }

    /** 新阶段初始秒数（WORK 完成时同步累积计数） */
    private fun phaseSeconds(phase: FocusPhase): Int {
        val s = state.value
        return when (phase) {
            FocusPhase.WORK -> s.workMinutes * 60
            FocusPhase.BREAK -> s.breakMinutes * 60
            FocusPhase.LONG_BREAK -> s.longBreakMinutes * 60
        }
    }

    /** 进入新阶段时设置倒计时，并同步 todayTomatoes/completedCycles（仅 WORK→休息路径需要计数） */
    private fun resetPhaseRemaining(phase: FocusPhase) {
        state.update { s ->
            val (tomatoes, completed) = if (phase == FocusPhase.BREAK || phase == FocusPhase.LONG_BREAK) {
                s.todayTomatoes + 1 to s.completedCycles + 1
            } else {
                s.todayTomatoes to s.completedCycles
            }
            s.copy(
                remainingSeconds = when (phase) {
                    FocusPhase.WORK -> s.workMinutes * 60
                    FocusPhase.BREAK -> s.breakMinutes * 60
                    FocusPhase.LONG_BREAK -> s.longBreakMinutes * 60
                },
                todayTomatoes = tomatoes,
                completedCycles = completed
            )
        }
    }

    fun clear() {
        timerJob?.cancel()
    }
}
