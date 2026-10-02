package com.aveline.ai.mobile.presentation.chat

/**
 * 图片消息的发送文本组装（纯函数，便于单元测试）。
 *
 * `[图片: url]` 现在是 Android → 后端聊天链的图片附件标记：
 * 后端在构建本轮 LLM 消息时会把它还原成标准 OpenAI `image_url` 内容。
 * 因此 Android 不需要、也不应该在发送前先把图片交给独立视觉模型描述一次。
 */
object ImageMessageText {

    /**
     * 旧视觉描述提示词保留给仍使用独立视觉接口的调用方；聊天发送链不再使用它。
     */
    const val VISION_PROMPT =
        "请详细描述这张图片的内容，包括场景、人物、动作、文字以及任何值得注意的细节。"

    /**
     * 组装图片附件标记。
     *
     * @param imageUrl 上传后得到的图片地址（相对路径，如 /output/image/uploads/x.jpg）
     * @param caption 用户附带的文字，可为空
     */
    fun buildAttachment(imageUrl: String, caption: String): String {
        val body = "[图片: ${imageUrl.trim()}]"
        return if (caption.isBlank()) body else "$body\n$caption"
    }

    /**
     * 兼容旧调用：description 为空时走新的附件标记；非空时仍保留旧的“识别结果文本”格式，
     * 避免其它尚未迁移的调用方被突然改变语义。
     */
    fun build(imageUrl: String, caption: String, description: String?): String {
        if (description.isNullOrBlank()) {
            return buildAttachment(imageUrl, caption)
        }
        val body = "[图像识别结果：$description]"
        return if (caption.isBlank()) body else "$body\n$caption"
    }
}
