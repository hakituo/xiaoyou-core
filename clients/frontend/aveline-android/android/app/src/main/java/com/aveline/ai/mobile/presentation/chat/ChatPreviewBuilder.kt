package com.aveline.ai.mobile.presentation.chat

/**
 * 会话列表预览文本构造器（单一真源）。
 *
 * 预览副标题的规则：
 * - 文本消息：直接取 text，超长截断
 * - 图片消息：显示 "[图片]"
 * - 用户消息：前缀 "我: "
 *
 * 历史聊天里 DB 存的是含 [MEME]/[IMG]/[BM]/[VOICE] 媒体标签的原始文本，
 * 预览前需要剥离这些标签。
 *
 * 同时被两处复用，避免逻辑分叉：
 * - [ChatIncomingMessageHandler]：进入聊天、收到新消息时实时写预览
 * - [com.aveline.ai.mobile.presentation.conversations.ConversationListViewModel]：
 *   冷启动从本地聊天历史重建全部预览
 */
object ChatPreviewBuilder {
    /** 预览文本最大长度（超出截断，加省略号） */
    const val PREVIEW_MAX_LEN = 60

    private val mediaTagRegex = Regex(
        """[\[［](?:MEME|IMG|BM|VOICE)(?:[：:][^\]］]*)?[\]］]""",
        RegexOption.IGNORE_CASE
    )

    /**
     * 由消息字段构造列表预览文本。
     *
     * @param text 原始消息文本（可能含媒体标签）
     * @param isUser 是否为用户消息（决定 "我: " 前缀）
     * @param messageType 消息类型（"image" 视为图片）
     * @param imageUrl 图片地址（非空视为图片）
     */
    fun buildPreviewText(
        text: String,
        isUser: Boolean,
        messageType: String,
        imageUrl: String?
    ): String {
        // 剥离媒体标签（DB 存的是含标签的原始文本）
        val cleanedText = mediaTagRegex.replace(text, "").replace("\n", " ").trim()
        val raw = when {
            messageType == "image" || !imageUrl.isNullOrBlank() -> "[图片]"
            cleanedText.isNotEmpty() -> cleanedText
            else -> ""
        }
        val withPrefix = if (isUser && raw.isNotEmpty()) "我: $raw" else raw
        return if (withPrefix.length > PREVIEW_MAX_LEN) {
            withPrefix.take(PREVIEW_MAX_LEN - 1) + "…"
        } else {
            withPrefix
        }
    }
}
