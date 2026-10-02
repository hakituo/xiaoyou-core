package com.aveline.ai.mobile.data.remote.api

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * 流式事件类型
 */
sealed class StreamEvent {
    /** 文本增量 */
    data class Chunk(val content: String) : StreamEvent()

    /** 流结束 */
    data class Done(val emotion: String? = null, val messageId: String? = null) : StreamEvent()

    /** 错误 */
    data class Error(val message: String) : StreamEvent()

    /** 重置：AI 开始调用工具时下发，通知前端清空当前正在生成的临时消息（不影响历史） */
    object Reset : StreamEvent()

    /** 图片消息：AI 输出 [MEME] 标签时后端推送的表情包/图片 */
    data class ImageResult(
        val imageUrl: String,
        val success: Boolean = true,
        val source: String? = null,
    ) : StreamEvent()

    /** 视频/动图消息：后端推送的 video_result 事件 */
    data class VideoResult(
        val videoUrl: String,
        val success: Boolean = true,
        val source: String? = null,
    ) : StreamEvent()
}

/**
 * SSE 解析器: 从 SSE 行解析出 StreamEvent
 *
 * 后端格式:
 * - data: {"type":"message","subtype":"response_chunk","content":"...",...}
 * - data: {"type":"message","subtype":"response_done","emotion":"...",...}
 * - data: {"type":"error","message":"..."}
 * - data: [DONE]
 * - 裸 JSON（非 SSE）：见 [parse]，后端部分错误分支直接返回普通 JSON，
 *   需要兜底识别，否则会被整段静默丢弃。
 */
object SseParser {
    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
    }

    /**
     * 解析一行 SSE, 返回 StreamEvent 或 null (非 data 行或忽略的事件)
     */
    fun parse(line: String): StreamEvent? {
        val trimmed = line.trim()
        if (trimmed.isEmpty()) return null

        // 裸 JSON 错误响应兜底（见 parseBareJsonError 的说明）
        if (!trimmed.startsWith("data: ")) {
            return if (trimmed.startsWith("{")) parseBareJsonError(trimmed) else null
        }

        val dataStr = trimmed.removePrefix("data: ").trim()
        if (dataStr.isEmpty()) return null

        // [DONE] 终止标记
        if (dataStr == "[DONE]") {
            return StreamEvent.Done()
        }

        return try {
            val obj = json.parseToJsonElement(dataStr).jsonObject
            parseEvent(obj)
        } catch (e: Exception) {
            // 非 JSON 的 data 行, 忽略
            null
        }
    }

    /**
     * 识别「不是 SSE 的 JSON 错误响应」。
     *
     * 历史 bug：`routers/v1/chat.py` 有一部分错误分支走的是 `return resp`
     * 直接返回普通 JSON（HTTP 状态码仍是 200），而不是 SSE 流，例如：
     * - content 为空 → EMPTY_CONTENT（发图不带文案时就会命中）
     * - content 超过 10000 字 → CONTENT_TOO_LARGE
     * - 消息格式非法 → INVALID_MESSAGE_FORMAT
     *
     * 这些响应的每一行都不带 `data: ` 前缀，旧实现要求必须 `startsWith("data: ")`，
     * 于是整段 JSON 被静默丢掉：一个 StreamEvent 都不会发出，UI 一直停在
     * 「正在输入」，也**不弹任何错误**。用户在安卓端看到的就是「AI 完全不回复」，
     * 且日志里没有任何线索 —— 排查时极易被误导成流式通道本身的问题。
     *
     * 这里把这类响应兜底成 [StreamEvent.Error]，让错误至少能显示出来。
     * 带上 error_code 是为了拿到后端具体的失败原因，不用再猜。
     */
    private fun parseBareJsonError(payload: String): StreamEvent? {
        // 整段都包起来：FastAPI 的 422 里 detail 是数组，取 jsonPrimitive 会抛，
        // 兜底解析失败就该安静忽略，绝不能把异常抛回流读取循环。
        return try {
            parseBareJsonErrorUnsafe(payload)
        } catch (e: Exception) {
            null
        }
    }

    private fun parseBareJsonErrorUnsafe(payload: String): StreamEvent? {
        val obj = json.parseToJsonElement(payload).jsonObject
        val status = obj["status"]?.jsonPrimitive?.contentOrNull
        val hasErrorSignal = status == "error" ||
            obj["error_code"] != null ||
            obj["error"] != null ||
            obj["detail"] != null
        if (!hasErrorSignal) return null

        val message = obj["message"]?.jsonPrimitive?.contentOrNull
            ?: obj["error"]?.jsonPrimitive?.contentOrNull
            ?: obj["detail"]?.jsonPrimitive?.contentOrNull
            ?: "未知错误"
        val code = obj["error_code"]?.jsonPrimitive?.contentOrNull
        val text = if (code.isNullOrBlank()) message else "[$code] $message"
        return StreamEvent.Error(text)
    }

    private fun parseEvent(obj: JsonObject): StreamEvent? {
        val type = obj["type"]?.jsonPrimitive?.contentOrNull ?: return null

        when (type) {
            "message" -> {
                val subtype = obj["subtype"]?.jsonPrimitive?.contentOrNull
                when (subtype) {
                    "response_chunk" -> {
                        val content = obj["content"]?.jsonPrimitive?.contentOrNull ?: ""
                        return if (content.isNotEmpty()) StreamEvent.Chunk(content) else null
                    }
                    "response_done", "done" -> {
                        val emotion = obj["emotion"]?.jsonPrimitive?.contentOrNull
                        val messageId = obj["message_id"]?.jsonPrimitive?.contentOrNull
                        return StreamEvent.Done(emotion = emotion, messageId = messageId)
                    }
                    "error" -> {
                        val msg = obj["message"]?.jsonPrimitive?.contentOrNull
                            ?: obj["error"]?.jsonPrimitive?.contentOrNull
                            ?: "未知错误"
                        return StreamEvent.Error(msg)
                    }
                    else -> return null
                }
            }
            "error" -> {
                val msg = obj["message"]?.jsonPrimitive?.contentOrNull
                    ?: obj["error"]?.jsonPrimitive?.contentOrNull
                    ?: "未知错误"
                return StreamEvent.Error(msg)
            }
            "response_reset" -> {
                // AI 开始调用工具，前端应清空当前正在生成的临时消息
                return StreamEvent.Reset
            }
            "image_result" -> {
                // AI 输出 [MEME] 标签时后端推送的表情包/图片
                val data = obj["data"]?.jsonObject
                val imageUrl = data?.get("image_url")?.jsonPrimitive?.contentOrNull
                val success = data?.get("success")?.jsonPrimitive?.contentOrNull
                    ?.toBooleanStrictOrNull() ?: true
                val source = data?.get("source")?.jsonPrimitive?.contentOrNull
                if (!imageUrl.isNullOrEmpty()) {
                    return StreamEvent.ImageResult(
                        imageUrl = imageUrl,
                        success = success,
                        source = source,
                    )
                }
                return null
            }
            "video_result" -> {
                val data = obj["data"]?.jsonObject
                val videoUrl = data?.get("video_url")?.jsonPrimitive?.contentOrNull
                val success = data?.get("success")?.jsonPrimitive?.contentOrNull
                    ?.toBooleanStrictOrNull() ?: true
                val source = data?.get("source")?.jsonPrimitive?.contentOrNull
                if (!videoUrl.isNullOrEmpty()) {
                    return StreamEvent.VideoResult(
                        videoUrl = videoUrl,
                        success = success,
                        source = source,
                    )
                }
                return null
            }
            else -> return null
        }
    }
}
