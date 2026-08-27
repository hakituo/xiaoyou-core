package com.aveline.ai.mobile.presentation.study

/**
 * 番茄钟阶段。
 */
enum class FocusPhase {
    WORK,
    BREAK,
    LONG_BREAK
}

/**
 * 专注（番茄钟）UI 状态。
 *
 * 由 [StudyFocusViewModel] 持有并暴露给 [StudyFocusTab]，
 * 计时与阶段推进逻辑由 [FocusTimerManager] 维护。
 *
 * @property phase 当前阶段（专注 / 短休息 / 长休息）
 * @property isRunning 计时是否进行中
 * @property remainingSeconds 当前阶段剩余秒数
 * @property workMinutes 专注时长（分钟）
 * @property breakMinutes 短休息时长（分钟）
 * @property longBreakMinutes 长休息时长（分钟）
 * @property focusName 自定义专注事项名（完成番茄后作为科目上报后端）
 * @property todayTomatoes 今日完成番茄数
 * @property completedCycles 本次连续专注周期数
 * @property cyclesBeforeLongBreak 每多少个专注周期后进入长休息
 */
data class StudyFocusState(
    val phase: FocusPhase = FocusPhase.WORK,
    val isRunning: Boolean = false,
    val remainingSeconds: Int = 25 * 60,
    val workMinutes: Int = 25,
    val breakMinutes: Int = 5,
    val longBreakMinutes: Int = 15,
    val focusName: String = "",
    val todayTomatoes: Int = 0,
    val completedCycles: Int = 0,
    val cyclesBeforeLongBreak: Int = 4
)
