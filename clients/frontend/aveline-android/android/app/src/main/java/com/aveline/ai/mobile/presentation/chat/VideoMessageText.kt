package com.aveline.ai.mobile.presentation.chat

/**
 * 视频消息的用户侧文本组装（纯函数，便于单元测试）。
 *
 * 后端 chat 通道只接受文本，且当前没有视频理解能力，所以视频不像图片那样
 * 先走视觉识别——直接把地址以 `[视频: url]` 的口径发给模型（与图片识别失败
 * 时的回退格式对称），本地气泡则按 videoUrl 渲染 ExoPlayer 播放器。
 */
object VideoMessageText {

    /**
     * 组装视频消息真正发给后端的文本。
     *
     * @param videoUrl 上传后得到的视频地址（相对路径，如 /output/video/uploads/x.mp4）
     * @param caption 用户附带的文字，可为空
     */
    fun build(videoUrl: String, caption: String): String {
        val body = "[视频: $videoUrl]"
        return if (caption.isBlank()) body else "$body\n$caption"
    }
}
