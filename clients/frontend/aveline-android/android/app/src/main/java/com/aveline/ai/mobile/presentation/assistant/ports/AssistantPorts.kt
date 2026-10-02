package com.aveline.ai.mobile.presentation.assistant.ports

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import javax.inject.Inject

/**
 * 语音助手的对外端口（Ports & Adapters）。
 *
 * 这一层把「助手该做什么」和「谁来做」拆开：**UI 与 ViewModel 只认端口，不认实现**。
 * 目前四个端口全部是本地桩实现，纯前端链路已经能完整跑起来：
 *
 * ```
 * 点胶囊 / 喊唤醒词 → 录音转写 → AssistantBackendPort.reply() → 回复上屏 → AssistantSpeechPort.speak()
 * ```
 *
 * 后端 / 端侧模型就绪后，**只需要把 `stubs` 里的实现类换成真实实现**（改 Hilt 绑定即可），
 * UI、ViewModel、动画一行都不用动。
 *
 * ┌───────────────────────────┬──────────────────────────────────────────────┐
 * │ 端口                       │ 将来对接的实现 / 后端接口                     │
 * ├───────────────────────────┼──────────────────────────────────────────────┤
 * │ AssistantWakeWordPort      │ 端侧关键词检测（KWS）。                       │
 * │                           │ 自定义唤醒词拉取：GET  /api/v1/assistant/wake-words  │
 * │ AssistantBackendPort       │ 对话生成，流式返回。                          │
 * │                           │ 建         议：POST /api/v1/assistant/chat（SSE）   │
 * │                           │ 备选（复用现成）：现有 chat 流式通道 + 独立 session  │
 * │ AssistantSpeechPort        │ 朗读。本地 TTSEngine，                        │
 * │                           │ 或远端：POST /api/v1/media/tts（现有 media 路由）    │
 * │ AssistantActionPort        │ 意图执行（开 App / 打电话 / 设提醒）。         │
 * │                           │ 本机：现有 SystemControlExecutor、PhoneActionExecutor │
 * │                           │ 需大模型决策时：POST /api/v1/assistant/command      │
 * └───────────────────────────┴──────────────────────────────────────────────┘
 *
 * 后端只要在 `routers/v1/` 下按上表的路径实现，再把 `.trae/` 展示链路接上，
 * 这一个 `.kt` 文件之外的所有代码都不需要知道细节。
 */

/** 一次助手对话请求。 */
data class AssistantRequest(
    /** 转写出来的用户原话。 */
    val text: String,
    /** 当前角色 scope / id，为空表示用默认助手人格。 */
    val roleId: String? = null,
    /** 会话 id，为空表示新开一轮短对话。 */
    val sessionId: String? = null
)

/** 后端的流式回复块，语义与现有 chat 流式通道一致（token → done）。 */
sealed class AssistantReply {
    /** 一个增量片段，会直接接在已显示文本后面。 */
    data class Token(val text: String) : AssistantReply()

    /** 生成结束，[fullText] 是完整文本。 */
    data class Done(val fullText: String) : AssistantReply()

    /** 失败（网络、鉴权、限流等）。 */
    data class Failure(val message: String) : AssistantReply()
}

/** 助手可以代执行的设备动作。现阶段只定义壳，由 AssistantActionPort 扩展。 */
sealed class AssistantAction {
    data class OpenApp(val packageName: String) : AssistantAction()
    data class OpenUrl(val url: String) : AssistantAction()
    /** 后端返回了尚不支持的动作，兜底用，别静默丢弃。 */
    data class Unsupported(val raw: String) : AssistantAction()
}

// ─────────────────────────────────────────────────────────────────────────────
// 端口 1：唤醒词
// ─────────────────────────────────────────────────────────────────────────────

/** 唤醒来源，用于埋点与差异化打招呼（喊出来的和点出来的，语气可以不一样）。 */
enum class AssistantWakeReason {
    /** 点击胶囊。 */
    TAP,

    /** 端侧唤醒词命中（"小柚"等）。 */
    WAKE_WORD,

    /** 通知 / 桌面快捷方式 / 耳机按键。 */
    EXTERNAL
}

/**
 * 端口 1：常驻唤醒词监听。
 *
 * 这是个**输入侧**端口：现在还没有实现（返回不可用），由胶囊点击代替。
 * 将来做前台 Service + 麦克风常驻检测时，让那个 Service 持有本接口的实现，
 * 命中后回调 [onWake]，之后的流程和「点胶囊」完全一致。
 */
interface AssistantWakeWordPort {

    /** 端侧 KWS 是否可用（模型有没有、权限有没有）。 */
    fun isAvailable(): Boolean

    /**
     * 开始常驻监听。重复调用应当是幂等的。
     *
     * @param onWake 命中回调，reason 恒为 [AssistantWakeReason.WAKE_WORD]
     */
    fun startListening(onWake: (AssistantWakeReason) -> Unit)

    fun stopListening()
}

// ─────────────────────────────────────────────────────────────────────────────
// 端口 2：对话后端
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 端口 2：对话后端。
 *
 * **这是最需要先换新实现的端口**，现桩是「回声」，目的是让纯前端链路自洽。
 * 真实实现拿到 [AssistantRequest] 后走 SSE / WebSocket，把增量 token 转成
 * [AssistantReply.Token] 逐个 emit，最后 emit [AssistantReply.Done]。
 */
interface AssistantBackendPort {
    fun reply(request: AssistantRequest): Flow<AssistantReply>
}

// ─────────────────────────────────────────────────────────────────────────────
// 端口 3：朗读
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 端口 3：把回复念出来。
 *
 * 真实实现可以复用现有的本地 `TTSEngine`，也可以走 `POST /api/v1/media/tts`
 * 拿远端音频，取决于「离线优先」还是「音色优先」，两种都不影响调用方。
 */
interface AssistantSpeechPort {
    fun speak(text: String)

    fun stop()

    /** 当前是否正在朗读，用于 UI 判断要不要显示「停止朗读」入口。 */
    fun isSpeaking(): Boolean
}

// ─────────────────────────────────────────────────────────────────────────────
// 端口 4：设备动作
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 端口 4：代执行的设备动作。
 *
 * 真实实现优先复用现有的 `SystemControlExecutor` / `PhoneActionExecutor`；
 * 需要「理解一句话要做什么」这种决策时再加后端 `POST /api/v1/assistant/command`。
 */
interface AssistantActionPort {
    /**
     * @return true 表示已执行；false 表示当前实现干不了这件事（交给调用方降级成普通对话）
     */
    suspend fun execute(action: AssistantAction): Boolean
}

// ─────────────────────────────────────────────────────────────────────────────
// 桩实现：后端就绪后逐个替换，改动只落在 AssistantPortsModule 的绑定上
// ─────────────────────────────────────────────────────────────────────────────

/** 桩：端侧 KWS 尚未接入，一律返回不可用，避免上层误以为在常驻监听。 */
class StubAssistantWakeWordPort @Inject constructor() : AssistantWakeWordPort {
    override fun isAvailable(): Boolean = false
    override fun startListening(onWake: (AssistantWakeReason) -> Unit) = Unit
    override fun stopListening() = Unit
}

/**
 * 桩：回声后端。
 *
 * 把用户说的原话原样还回去，并在前面标注「后端未接入」，
 * 这样一眼就能区分「这是桩行为」还是「模型真的这么回的」。
 */
class StubAssistantBackendPort @Inject constructor() : AssistantBackendPort {
    override fun reply(request: AssistantRequest): Flow<AssistantReply> = flow {
        val text = "（后端未接入）${request.text}"
        emit(AssistantReply.Token(text))
        emit(AssistantReply.Done(text))
    }
}

/** 桩：不发声，仅记录一句日志所需的空实现。 */
class StubAssistantSpeechPort @Inject constructor() : AssistantSpeechPort {
    private var speaking = false

    override fun speak(text: String) {
        speaking = text.isNotBlank()
    }

    override fun stop() {
        speaking = false
    }

    override fun isSpeaking(): Boolean = speaking
}

/** 桩：所有动作都干不了，返回 false 让调用方降级成普通对话。 */
class StubAssistantActionPort @Inject constructor() : AssistantActionPort {
    override suspend fun execute(action: AssistantAction): Boolean = false
}
