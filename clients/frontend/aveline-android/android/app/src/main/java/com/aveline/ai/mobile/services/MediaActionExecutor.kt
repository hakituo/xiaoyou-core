package com.aveline.ai.mobile.services

import android.content.Context
import android.media.AudioManager
import android.view.KeyEvent
import com.aveline.ai.mobile.domain.models.PhoneAction
import com.aveline.ai.mobile.domain.models.PhoneActionResult
import kotlinx.serialization.json.JsonPrimitive

/**
 * 媒体与音量动作执行器
 *
 * 从 PhoneActionExecutor 中提取的媒体控制相关逻辑，负责：
 * - 媒体播放控制（播放/暂停/上一首/下一首/停止）
 * - 系统音量调节（按流类型设置音量）
 *
 * 通过构造函数接收应用上下文，用于获取 AudioManager 等系统服务。
 *
 * @property context 应用上下文
 */
class MediaActionExecutor(
    private val context: Context
) {

    /**
     * 执行媒体控制动作
     *
     * 将媒体指令映射为对应的 KeyEvent，并通过 AudioManager 派发，
     * 模拟物理媒体按键的效果。
     *
     * @param action 媒体控制动作
     * @return 执行结果
     */
    fun mediaControl(action: PhoneAction.MediaControl): PhoneActionResult {
        val keyCode = when (action.command) {
            "play" -> KeyEvent.KEYCODE_MEDIA_PLAY
            "pause" -> KeyEvent.KEYCODE_MEDIA_PAUSE
            "play_pause" -> KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE
            "next" -> KeyEvent.KEYCODE_MEDIA_NEXT
            "previous" -> KeyEvent.KEYCODE_MEDIA_PREVIOUS
            "stop" -> KeyEvent.KEYCODE_MEDIA_STOP
            else -> return PhoneActionResult(
                actionId = action.actionId,
                success = false,
                resultType = "unknown_media_command",
                error = "未知媒体指令: ${action.command}"
            )
        }

        val downEvent = KeyEvent(KeyEvent.ACTION_DOWN, keyCode)
        val upEvent = KeyEvent(KeyEvent.ACTION_UP, keyCode)

        val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        audioManager.dispatchMediaKeyEvent(downEvent)
        audioManager.dispatchMediaKeyEvent(upEvent)

        return PhoneActionResult(
            actionId = action.actionId,
            success = true,
            resultType = "media_command_sent",
            data = mapOf("command" to JsonPrimitive(action.command))
        )
    }

    /**
     * 设置系统音量
     *
     * 根据流类型（音乐/铃声/通知/闹钟等）设置对应音量，
     * 音量值会被限制在该流类型的有效范围内。
     *
     * @param action 音量设置动作
     * @return 执行结果，包含实际设置的音量与最大音量
     */
    fun setVolume(action: PhoneAction.SetVolume): PhoneActionResult {
        val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager

        val streamType = when (action.streamType) {
            "music", "media" -> AudioManager.STREAM_MUSIC
            "ring" -> AudioManager.STREAM_RING
            "notification" -> AudioManager.STREAM_NOTIFICATION
            "alarm" -> AudioManager.STREAM_ALARM
            "system" -> AudioManager.STREAM_SYSTEM
            "voice_call" -> AudioManager.STREAM_VOICE_CALL
            else -> AudioManager.STREAM_MUSIC
        }

        val maxVolume = audioManager.getStreamMaxVolume(streamType)
        val clampedLevel = action.level.coerceIn(0, maxVolume)
        audioManager.setStreamVolume(streamType, clampedLevel, 0)

        return PhoneActionResult(
            actionId = action.actionId,
            success = true,
            resultType = "volume_set",
            data = mapOf(
                "streamType" to JsonPrimitive(action.streamType),
                "level" to JsonPrimitive(clampedLevel),
                "maxLevel" to JsonPrimitive(maxVolume)
            )
        )
    }
}
