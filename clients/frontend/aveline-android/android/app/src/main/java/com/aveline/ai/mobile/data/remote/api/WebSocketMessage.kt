package com.aveline.ai.mobile.data.remote.api

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

/**
 * Sealed class representing different types of WebSocket messages.
 * 
 * All WebSocket messages are JSON-based and discriminated by a "type" field.
 */
@Serializable
sealed class WebSocketMessage {
    
    /**
     * Text message from AI assistant.
     * 
     * @property text Message text content
     * @property emotion Optional emotion state
     */
    @Serializable
    data class TextMessage(
        val text: String,
        val emotion: String? = null
    ) : WebSocketMessage()

    @Serializable
    data object ResponseDone : WebSocketMessage()

    /**
     * AI 开始调用工具时下发的重置信号，前端应清空当前正在生成（临时）的消息，
     * 不影响历史消息；工具完成后最终回答会重新逐块流式发送。
     */
    @Serializable
    data object ResponseReset : WebSocketMessage()

    /**
     * Notification message for user alerts.
     * 
     * @property title Notification title
     * @property body Notification body text
     */
    @Serializable
    data class Notification(
        val title: String,
        val body: String,
        /**
         * 点击通知后的深链目标, 由后端下发以精确跳转到对应页面。可选值:
         * "chat"(默认, 与角色聊天页, 可配合 sessionId), "study"(背单词页),
         * "life"(日常生活页), "settings"(设置页), "status"(伴侣页), "conversations"(主页)。
         * 缺省为 null 时由前端按内容启发式判断(背单词类消息跳 study, 其余跳 chat)。
         */
        val target: String? = null,
        /** 跳转到聊天时指定的会话/角色 ID, 点击通知直接进入该角色的聊天页。 */
        val sessionId: String? = null
    ) : WebSocketMessage()

    /**
     * 角色主动消息（Active Care 主动关怀、角色自发开口）。
     *
     * 后端在 core/services/aveline/proactive_messaging.py 的 dispatch_proactive_message 里以
     * `{"type":"proactive_message","subtype":"active_care",...}` 广播。此前 Android 没有该 type
     * 的解析分支，消息会落到 [Unknown] 被静默丢弃——既不通知也不上屏，
     * 这正是「active care 收不到通知」的根因。
     *
     * @property content 角色说的话
     * @property conversationId 目标会话 id（形如 shared__persona__xxx），用于点击通知直达对应角色
     * @property messageType 消息形态（text / image 等），当前按文本处理
     * @property messageId 后端生成的消息 id，用于通知去重（重连重放时避免重复提醒）
     * @property isPeerScript 是否为双角色剧本消息（这类消息不按"角色回我"提醒）
     * @property peerSpeaker 双角色剧本里的说话者
     * @property personaFilename 说话角色的人设文件名（如 core_aveline.json）。
     *   App 本地会话按 persona 隔离（sessionId = web_{persona_filename}），归档主动消息
     *   必须用它；conversation_id 是后端/QQ 侧的会话 id，与本地 sessionId 不是一个命名空间。
     * @property roleName 说话角色的中文名（如"Aveline"），用作通知标题。
     *   本地自定义昵称优先于它，两者都没有时回退 conversation_id 解析的 role。
     */
    @Serializable
    data class ProactiveMessage(
        val content: String,
        val conversationId: String? = null,
        val messageType: String = "text",
        val messageId: String? = null,
        val isPeerScript: Boolean = false,
        val peerSpeaker: String? = null,
        val personaFilename: String? = null,
        val roleName: String? = null
    ) : WebSocketMessage()
    
    /**
     * Error message from backend.
     * 
     * @property message Error message text
     */
    @Serializable
    data class Error(
        val message: String
    ) : WebSocketMessage()
    
    /**
     * Image generation result.
     * 
     * @property imageUrl URL of the generated image
     */
    @Serializable
    data class ImageResult(
        val imageUrl: String
    ) : WebSocketMessage()

    /**
     * 视频/动图生成结果（AI 生成的短视频、webm 动图等）。
     *
     * 是否静音/是否给控制条不下发，由客户端按消息角色决定（AI 静音循环、
     * 用户自己发的保留原声），保证"实时收到"与"从本地库重新加载"表现一致。
     *
     * @property videoUrl 视频地址（后端相对路径或绝对 URL）
     */
    @Serializable
    data class VideoResult(
        val videoUrl: String
    ) : WebSocketMessage()
    
    /**
     * Ping message for connection health check.
     * 
     * @property timestamp Ping timestamp in milliseconds
     */
    @Serializable
    data class Ping(
        val timestamp: Long
    ) : WebSocketMessage()
    
    /**
     * Pong response to ping message.
     * 
     * @property timestamp Original ping timestamp
     */
    @Serializable
    data class Pong(
        val timestamp: Long
    ) : WebSocketMessage()
    
    /**
     * Model switch notification.
     * 
     * @property model New model identifier
     */
    @Serializable
    data class ModelSwitch(
        val model: String
    ) : WebSocketMessage()
    
    /**
     * Settings update notification.
     * 
     * @property settings Map of setting key-value pairs
     */
    @Serializable
    data class SettingsUpdate(
        val settings: Map<String, JsonElement>
    ) : WebSocketMessage()
    
    /**
     * Emotion update message from backend.
     * 
     * @property primary Primary emotion type
     * @property intensity Emotion intensity (0.0 - 1.0)
     * @property colors List of emotion colors
     * @property emotionMix Map of emotion types to percentages
     */
    @Serializable
    data class EmotionUpdate(
        val primary: String,
        val intensity: Float = 0.5f,
        val colors: List<String> = emptyList(),
        val emotionMix: Map<String, Float> = emptyMap()
    ) : WebSocketMessage()

    /**
     * Connection established message from backend (sent to mobile clients on connect).
     * 
     * @property heartbeatInterval Heartbeat interval in seconds
     * @property reconnectSupported Whether server supports reconnect messages
     * @property platform Client platform detected by server
     */
    @Serializable
    data class ConnectionEstablished(
        val heartbeatInterval: Int = 30,
        val reconnectSupported: Boolean = true,
        val platform: String = ""
    ) : WebSocketMessage()

    /**
     * Reconnect sync message from backend (sent in response to reconnect).
     * 
     * @property currentModel Current active model
     * @property emotionState Current emotion state
     * @property lifeStatus Current life simulation status
     */
    @Serializable
    data class ReconnectSync(
        val currentModel: String? = null,
        val emotionState: Map<String, kotlinx.serialization.json.JsonElement>? = null,
        val lifeStatus: Map<String, Float>? = null
    ) : WebSocketMessage()

    /**
     * 生命模拟状态推送（后端每秒广播）
     *
     * @property life 生命属性（health, hunger, happiness, energy等）
     * @property bio 生物统计（dopamine, serotonin等）
     * @property mood 当前心情
     * @property activity 当前活动状态
     * @property timestamp 时间戳
     */
    @Serializable
    data class LifeStatusUpdate(
        val life: Map<String, Float> = emptyMap(),
        val bio: Map<String, Float> = emptyMap(),
        val mood: String = "calm",
        val activity: String = "idle",
        val timestamp: Long = System.currentTimeMillis()
    ) : WebSocketMessage()

    /**
     * 仪式事件推送
     *
     * @property id 事件ID
     * @property content 事件内容
     * @property timestamp 时间戳
     */
    @Serializable
    data class RitualEvent(
        val id: String = "",
        val content: String = "",
        val timestamp: Long = System.currentTimeMillis(),
        /** 触发仪式的角色人设文件名（后端 persona_filename），用于点击通知直达该角色 */
        val personaFilename: String? = null,
        /** 角色显示名，用作通知标题；为空时客户端回退默认标题 */
        val roleName: String? = null
    ) : WebSocketMessage()

    /**
     * 自发反应推送
     *
     * @property id 反应ID
     * @property content 反应内容
     * @property timestamp 时间戳
     * @property personaFilename 触发反应的角色人设文件名，用于点击通知直达该角色
     * @property roleName 角色显示名，用作通知标题；为空时客户端回退默认标题
     */
    @Serializable
    data class SpontaneousReaction(
        val id: String = "",
        val content: String = "",
        val timestamp: Long = System.currentTimeMillis(),
        val personaFilename: String? = null,
        val roleName: String? = null
    ) : WebSocketMessage()

    @Serializable
    data class PhoneActionCommand(
        val actionId: String,
        val actionType: String,
        val params: kotlinx.serialization.json.JsonObject = kotlinx.serialization.json.JsonObject(emptyMap())
    ) : WebSocketMessage()

    /**
     * 设备控制指令 (后端下发到手机前端执行)
     *
     * 与 PhoneActionCommand 区别: device_command 专门承载系统控制类
     * (强制停止/应用列表/使用统计/截图等), 结果用 JsonObject (支持复杂结构),
     * 通过 device_command_result 消息回传
     *
     * @property requestId 请求 ID, 用于后端配对 future
     * @property command 指令名 (如 "force_stop_app")
     * @property args 指令参数 (JsonObject, 支持嵌套)
     * @property timeout 超时秒数
     */
    @Serializable
    data class DeviceCommand(
        val requestId: String,
        val command: String,
        val args: kotlinx.serialization.json.JsonObject = kotlinx.serialization.json.JsonObject(emptyMap()),
        val timeout: Int = 30
    ) : WebSocketMessage()

    @Serializable
    data class ResponseChunk(
        val content: String,
        val chunkIndex: Int = 0,
        val emotion: String? = null
    ) : WebSocketMessage()

    /**
     * 双角色对话消息
     *
     * @property scriptId 剧本ID
     * @property role 角色名称（aveline/ling）
     * @property roleName 角色显示名称
     * @property text 对话内容
     * @property emotion 情绪状态
     * @property roundIndex 轮次索引
     * @property timestamp 时间戳
     */
    @Serializable
    data class PeerChatMessage(
        val scriptId: String = "",
        val role: String = "",
        val roleName: String = "",
        val text: String = "",
        val emotion: String? = null,
        val roundIndex: Int = 0,
        val timestamp: Long = System.currentTimeMillis()
    ) : WebSocketMessage()

    /**
     * 双角色对话剧本开始
     *
     * @property scriptId 剧本ID
     * @property topic 话题
     * @property participants 参与者列表
     * @property totalRounds 总轮次
     */
    @Serializable
    data class PeerChatScriptStart(
        val scriptId: String = "",
        val topic: String = "",
        val participants: List<String> = emptyList(),
        val totalRounds: Int = 0
    ) : WebSocketMessage()

    /**
     * 双角色对话剧本结束
     *
     * @property scriptId 剧本ID
     * @property summary 对话摘要
     * @property mentionedUser 是否提及用户
     */
    @Serializable
    data class PeerChatScriptEnd(
        val scriptId: String = "",
        val summary: String = "",
        val mentionedUser: Boolean = false
    ) : WebSocketMessage()

    @Serializable
    data class Unknown(
        val rawJson: String
    ) : WebSocketMessage()
}

/**
 * Raw WebSocket message wrapper for JSON parsing.
 * 
 * @property type Message type discriminator
 * @property data Message data payload
 */
@Serializable
data class RawWebSocketMessage(
    val type: String,
    val data: JsonElement? = null
)
