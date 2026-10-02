package com.aveline.ai.mobile.presentation.chat

import android.util.Log
import com.aveline.ai.mobile.data.remote.api.StreamEvent
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.domain.repository.ChatBranchContext
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.services.foreground.RoleReplyNotifier
import com.aveline.ai.mobile.utils.AppForegroundTracker
import com.aveline.ai.mobile.utils.text.TextSegmenter
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 负责"发消息"的核心流程（HTTP SSE 流式回复）。
 *
 * 当前 role 的手选模型在真正生成前解析为 route，并作为本次请求的 model 显式下发；
 * 不再通过全局 /models/switch 恢复模型，因此角色之间和并发请求之间不会互相踩状态。
 *
 * 生成事务不能绑定聊天页 ViewModel 生命周期：用户发完消息返回会话列表时，
 * ChatViewModel 会被销毁。如果 persona/session 准备、SSE collect 或最终 Room 写入仍运行在
 * viewModelScope，页面一退出就可能主动取消请求，后端即使生成完成，本地也永远只有用户消息。
 * 因此发送准备 + 真正生成 + 持久化统一使用进程级后台作用域；UI/TTS 更新仍受 [scope]
 * 生命周期约束，页面销毁后只继续网络和存储，不再碰旧 UI。
 */
class ChatSendController(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val chatRepository: ChatRepository,
    private val personaLocalMetaRepository: PersonaLocalMetaRepository,
    private val sessionController: ChatSessionController,
    private val ttsController: ChatTtsController,
    private val flushManager: ChatFlushManager,
    private val mapEmotion: (String) -> Emotion?,
    private val resolveRoleModelRoute: () -> String? = { null },
    /**
     * 后台回复通知发布器。
     *
     * 用户主动发消息走 HTTP SSE，回复完成时 WebSocket 侧被抑制（见 ChatFlushManager），
     * 因此 SSE 收尾必须自己弹通知，否则「切出去等回复」永远收不到提示。
     * 可空 + 默认值：单测直接构造时不传。
     */
    private val replyNotifier: RoleReplyNotifier? = null
) {
    companion object {
        private const val TAG = "ChatSendController"

        /**
         * 请求体里携带的历史窗口上限（条数）。
         *
         * 这个窗口会原样作为 `history_override` 上传，所以它直接决定请求体大小：
         * 实测最近 200 条的文本量是 44-95KB。内网直连无所谓，但走 Cloudflare Tunnel 时
         * 这段上传要 0.75s 以上（实测 100KB body 比 1KB body 的首字节多 0.75s），
         * 叠加 TLS 握手就是用户感知的「点发送卡 2-3 秒」。
         */
        private const val HISTORY_WINDOW_MESSAGES = 200

        /**
         * 真正上传的历史字符预算。
         *
         * 后端 context_budget 实际只会用到 24000 字符（本地 max_total_chars_cap）
         * 或 18 条 / 6000 字符（云端 cloud_max_history_*），超出部分会被直接截断。
         * 所以按预算把窗口收下来，砍掉的全是白传的字节，对模型看到的上下文没有影响。
         */
        private const val HISTORY_BUDGET_CHARS = 20_000

        /** 至少保留的条数：消息很长时不至于把窗口削得过薄。 */
        private const val HISTORY_MIN_MESSAGES = 12

        /**
         * 后台生成协程未捕获异常的最后一道网。
         *
         * SupervisorJob 只保证"一条生成失败不取消其它并发生成"，它**不**负责兜住异常：
         * launch 里抛出的未捕获异常会一路交到线程默认异常处理器，被 `CrashHandler`
         * 记档后直接杀掉进程 —— 用户看到的就是"聊天页突然闪退"。
         * 回复生成失败应该是"这一轮报错"，不该赔上整个 App，所以这里兜一层并记日志。
         * 业务侧更细的处理见 `runAssistantGeneration` 里的 catch（会同时关掉打字指示器）。
         */
        private val backgroundExceptionHandler = CoroutineExceptionHandler { _, e ->
            Log.e(TAG, "后台生成协程未捕获异常（已拦截，不再导致进程闪退）", e)
        }

        /**
         * 聊天生成属于 App 进程，而不是某个 Compose 页面。
         * SupervisorJob 保证一条生成失败不会取消其它并发生成；进程被系统回收时自然结束。
         */
        private val backgroundGenerationScope =
            CoroutineScope(SupervisorJob() + Dispatchers.IO + backgroundExceptionHandler)

        /** 后台并发生成统一使用线程安全 ID，避免竞争 ViewModel 内的普通计数器。 */
        private val backgroundMessageIdCounter = AtomicLong(0L)

        /**
         * HTTP SSE 活跃数也必须是进程级：旧 ChatViewModel 销毁后重新进入聊天，
         * 新 ChatFlushManager 仍要知道此时应抑制 WebSocket response_chunk/done，避免双通道重复回复。
         */
        private val backgroundHttpStreamCount = AtomicLong(0L)
        private val _backgroundHttpStreamingActive = MutableStateFlow(false)
        val backgroundHttpStreamingActive: StateFlow<Boolean> =
            _backgroundHttpStreamingActive.asStateFlow()

        /** 拿不到会话 ID 时的占位去重键（此时发送本来就会走「记录尚未加载」分支）。 */
        private const val DEFAULT_SEND_KEY = "(no-session)"

        /**
         * 正在「发送预检」中的会话集合。
         *
         * 点下发送到请求真正发出之间有一段预检（persona 切换、历史窗口组装、写库），
         * 这段窗口里界面本来不会变（输入框还没清、气泡还没上屏、`isTyping` 还是 false），
         * 用户很容易以为没点上而重复点击。旧行为下每次点击都会各起一个协程，
         * 预检一结束 N 个 POST 几乎同时发出（实测间隔 3~7ms），后端只能把前 N-1 个
         * cancel 掉（`stream_orchestrator: cancelling prev_task`）——白白多跑几轮
         * prompt 组装，回复也可能闪一下又重来。
         *
         * 这里只锁**预检窗口**，不锁生成过程：生成期间用户主动再发一条是允许的
         * （后端会 cancel 上一条），只是「同一次点击被重复触发」没有意义。
         */
        private val inFlightPreflight: MutableSet<String> = ConcurrentHashMap.newKeySet()

        /**
         * 正在生成回复的后台任务，按会话 ID 索引，供「停止生成」取消。
         *
         * 为什么按会话索引而不是只存一个：生成跑在进程级的 [backgroundGenerationScope] 上，
         * 用户在 A 角色发完消息、切到 B 角色再发，两个生成会同时在跑；
         * 停止按钮只能停**当前这个会话**那一轮，不能顺手把另一个会话的生成一起掐掉。
         *
         * 为什么放 companion（进程级）而不是实例字段：生成不随聊天页销毁而停止，
         * 用户退出再进来（新 ChatViewModel / 新 controller）时，那一轮生成可能还在跑，
         * 此时仍然要能把它停掉。
         */
        private val activeGenerationJobs = ConcurrentHashMap<String, Job>()

        private fun generateBackgroundMessageId(): String =
            "${System.currentTimeMillis()}-bg-${backgroundMessageIdCounter.incrementAndGet()}"

        /**
         * 记一轮 HTTP SSE 开始/结束。
         *
         * 计数器是"当前有几轮 HTTP 流在跑"，[backgroundHttpStreamingActive] 由它派生；
         * 调用方必须用返回的布尔值去同步 flushManager，**不要**自己写死 true/false：
         * 同一会话可能有一轮正在收尾、下一轮已经在跑（同一会话发新请求时后端会 cancel
         * 上一轮，客户端也会提前取消），旧轮收尾时无脑 `setHttpStreamingActive(false)`
         * 会把新轮的 WS 抑制一起放开，两个通道同时上屏就重复了。
         * 注意 StateFlow 同值不重发，ViewModel 那边的 collector 救不回来这种自相矛盾。
         */
        private fun markHttpStreamStarted(): Boolean {
            if (backgroundHttpStreamCount.incrementAndGet() == 1L) {
                _backgroundHttpStreamingActive.value = true
            }
            return backgroundHttpStreamingActive.value
        }

        /** @return 收尾后是否仍有 HTTP 流在跑（即 WS 是否还要继续被抑制）。 */
        private fun markHttpStreamFinished(): Boolean {
            val remaining = backgroundHttpStreamCount.decrementAndGet()
            if (remaining <= 0L) {
                backgroundHttpStreamCount.set(0L)
                _backgroundHttpStreamingActive.value = false
            }
            return backgroundHttpStreamingActive.value
        }
    }

    fun sendMessage(
        text: String,
        model: String = "default",
        imageUrl: String? = null,
        videoUrl: String? = null,
        displayText: String? = null
    ) {
        if (text.isBlank()) return
        // 预检去重：key 取点击瞬间的会话。预检内部换 persona 不会换 role session，
        // 所以这个 key 在整个预检窗口内都稳定。
        val entrySessionId = sessionController.conversationSessionId
        val sendKey = entrySessionId ?: DEFAULT_SEND_KEY
        if (!inFlightPreflight.add(sendKey)) return

        launchGeneration(entrySessionId) {
            // 兜底原文：图片/视频路径传的是 caption，文本路径就是正文本身。
            val fallbackText = displayText ?: text
            // 用户气泡是否已经落库。决定取消时要不要把原文还回输入框：
            // 已经发出去的消息不该再在输入框里留一份（用户会以为根本没发出去）。
            var userMessageInserted = false
            try {
                val prepared = (try {
                    prepareSend(entrySessionId, fallbackText, imageUrl, videoUrl)
                } finally {
                    // 无论成功、失败还是抛异常都要放开去重锁，否则这个会话会永久发不出消息。
                    // 生成过程不占锁：生成期间用户主动再发一条仍然允许（后端会 cancel 上一条）。
                    inFlightPreflight.remove(sendKey)
                }) ?: return@launchGeneration

                userMessageInserted = true
                startAssistantGeneration(
                    userMessage = prepared.userMessage,
                    prefixHistory = prepared.prefixHistory,
                    model = model,
                    assistantVariantIndex = 0,
                    personaFilename = prepared.personaFilename,
                    sendText = text
                )
            } catch (e: CancellationException) {
                // 预检阶段就被取消：用户点「停止」、离开页面，或同一会话起了新一轮。
                // 这时 runAssistantGeneration 的取消收尾还没接手（它只覆盖 SSE 开始之后的
                // 窗口），界面会停在中间态，这里补一次兜底。
                //
                // selfJob 必须在 withContext 外面取：里面是 NonCancellable，
                // `currentCoroutineContext()[Job]` 拿到的是 NonCancellable 而不是本轮任务，
                // 传给收尾就永远判不出"是否已被顶替"。
                val selfJob = currentCoroutineContext()[Job]
                withContext(NonCancellable) {
                    rescueCancelledSend(
                        sessionId = entrySessionId,
                        selfJob = selfJob,
                        originalText = fallbackText,
                        restoreText = !userMessageInserted
                    )
                }
                throw e
            }
        }
    }

    /**
     * 停止当前会话正在进行的生成（生成期间输入栏按钮会切成「停止」）。
     *
     * 取消的是这一轮生成所在的后台 Job：`sendMessageStreaming` 的 collect 随之抛出
     * CancellationException → callbackFlow 被取消 → OkHttp 关闭连接 → 后端 FastAPI 侧
     * 收到客户端断开，ASGI 取消生成器。也就是说这一轮推理是真的停了，不是只在客户端
     * 假装停了。
     *
     * 已经流出来的正文不会丢：runAssistantGeneration 的 CancellationException 分支会在
     * NonCancellable 里把已收到的部分落库、再关掉打字指示器（只是不发"回复完成"通知）。
     *
     * 只停当前会话：其它角色/会话并发的生成不受影响（见 [activeGenerationJobs]）。
     * 没有可停的任务时是安全空操作 —— 例如 WebSocket 推来的主动关怀也在置 isTyping，
     * 但那种回复没有本地任务；UI 侧已经用 `generatingSessionId` 把它挡掉了。
     */
    fun stopGeneration() {
        val sessionId = sessionController.conversationSessionId ?: return
        val job = activeGenerationJobs[sessionId] ?: return
        // 只 cancel，**不**在这里把表项摘掉：摘除统一由 launchGeneration 的 finally 做。
        // 提前摘会让这一轮的收尾（rescueCancelledSend）把自己误判成"已被新一轮顶替"
        // 而整段跳过 —— 那正是"点了停止界面还卡在正在输入"的来源。
        job.cancel(CancellationException("用户停止了生成"))
    }

    /**
     * 在进程级作用域里跑一轮「发送 / 重生成」，并把这一轮的 Job 登记到 [activeGenerationJobs]。
     *
     * 登记点放在**协程体最开头**（预检之前），而不是等 SSE 真正开始：
     * 图片/视频发送路径在进入 sendMessage 之前就把 isTyping 置成了 true，
     * 那一刻输入栏按钮已经切成「停止」。若等 runAssistantGeneration 才登记，
     * 用户在预检窗口里点停止会打空（表里还没有可停的任务）。
     *
     * @param sessionId 这一轮归属的会话，用作停止按钮的索引键；为 null 时只跑不登记
     *   （此时本来也定位不到会话，停止按钮不会亮）。
     */
    private fun launchGeneration(sessionId: String?, block: suspend () -> Unit) {
        backgroundGenerationScope.launch {
            val selfJob = currentCoroutineContext()[Job]
            if (sessionId != null && selfJob != null) {
                // 同一会话又起了一轮：先把上一轮停掉。
                //
                // 后端本来就只允许每个会话一轮在跑（stream_orchestrator 收到同一 cid 的
                // 新请求会 `prev_task.cancel()`），所以上一轮注定拿不到完整回复。
                // 客户端提前取消有两个好处：旧 SSE 立刻断开（不用等后端反应过来）；
                // 旧轮以"被取代"收尾 —— 走 CancellationException 分支、notify=false，
                // 不会为一段被截断的正文弹「回复完成」通知，也不会给会话列表白记一个未读。
                //
                // 用 put 的返回值拿旧值：替换与读取是一步原子操作，不会漏掉并发替换。
                val previous = activeGenerationJobs.put(sessionId, selfJob)
                if (previous != null && previous !== selfJob) {
                    previous.cancel(CancellationException("同一会话发起了新一轮生成"))
                }
                markGenerating(sessionId, active = true)
            }
            try {
                block()
            } catch (e: CancellationException) {
                // 取消发生在 SSE 开始之前时，runAssistantGeneration 的收尾根本没机会执行；
                // 见 rescueCancelledSend 的说明。正常收尾跑过之后这里再收一次是无害的。
                withContext(NonCancellable) {
                    rescueCancelledSend(sessionId, selfJob, null, restoreText = false)
                }
                throw e
            } finally {
                if (sessionId != null && selfJob != null) {
                    // 顺序不能反：markGenerating 靠"表里已经空了"来判断该不该清标志位，
                    // 先清标志再 remove 会把同会话新一轮生成的「停止」按钮一起关掉。
                    activeGenerationJobs.remove(sessionId, selfJob)
                    markGenerating(sessionId, active = false)
                }
            }
        }
    }

    /**
     * 标记/清除"当前有本地生成在跑"，驱动输入栏的「发送 ↔ 停止」双态。
     *
     * 直接改 uiState 而不走 [withUiIfActive]：这里只改一个标志位，没有挂起点，
     * 而调用它的 finally 很可能处在已取消的协程里 —— withUiIfActive 内部的
     * `withContext` 在取消态下会立刻抛 CancellationException，收尾会半途而废。
     *
     * 清除时有两个前置条件，缺一个都会让停止按钮在该在的时候消失：
     * - 字段确实指向自己这一轮（用户在别的会话发起过生成时字段已经被改写）；
     * - [activeGenerationJobs] 里这一会话已经空了（用户生成期间又发了一条时，
     *   旧任务先结束不能把新任务的标志位清掉）。所以调用方必须**先 remove 再清标志**。
     */
    private fun markGenerating(sessionId: String, active: Boolean) {
        uiState.update { state ->
            when {
                active -> state.copy(generatingSessionId = sessionId)
                state.generatingSessionId == sessionId && activeGenerationJobs[sessionId] == null ->
                    state.copy(generatingSessionId = null)
                else -> state
            }
        }
    }

    /**
     * 取消发生得太早（预检阶段）时的兜底收尾。
     *
     * 只做**幂等**的两件事：
     * 1. 关掉打字指示器 —— 图片/视频路径在进 sendMessage 前就置了 isTyping = true，
     *    预检被取消时没人再把它关掉，界面会永远卡在「正在输入」。
     * 2. 输入框仍为空且消息尚未落库时把原文还回去 —— 预检第一步就清了输入框，
     *    取消后用户打的字会凭空消失。已经落库就不还：那条消息是用户真实发出去的，
     *    再在输入框留一份会让人以为没发成功。
     *
     * 刻意不碰消息树：取消点不同，用户气泡可能已插入也可能没有，无法可靠判断该不该
     * 撤回。那条消息是用户真实发过的内容，留在会话里比猜着删掉更安全 ——
     * 用户可以直接再点一次发送或重新生成。
     *
     * @param selfJob 本轮自己的 Job。收尾前要拿它和 [activeGenerationJobs] 对一下：
     *   若表里已经不是自己，说明同一会话起了新一轮，界面状态现在归那一轮管 ——
     *   这时再关打字指示器会把新一轮的「正在输入」抹掉（用户看到"发了没反应"）。
     *   注意这个判断依赖"停止时不提前摘表"（见 [stopGeneration]），否则用户自己点停止
     *   也会被误判成被顶替。
     */
    private suspend fun rescueCancelledSend(
        sessionId: String?,
        selfJob: Job?,
        originalText: String?,
        restoreText: Boolean
    ) {
        withUiIfActive(sessionId) {
            uiState.update { state ->
                // 在 CAS 里再判一次：从进入这个函数到真正提交之间，新一轮可能刚好登记完。
                if (sessionId != null && selfJob != null &&
                    activeGenerationJobs[sessionId] !== selfJob
                ) {
                    return@update state
                }
                state.copy(
                    isTyping = false,
                    showTypingIndicator = false,
                    inputText = if (restoreText && originalText != null && state.inputText.isBlank()) {
                        originalText
                    } else {
                        state.inputText
                    }
                )
            }
        }
    }

    /** 预检产物：已落库的用户消息、它之前的正文窗口、本次请求冻结的 persona。 */
    private data class PreparedSend(
        val userMessage: Message,
        val prefixHistory: List<Message>,
        val personaFilename: String?
    )

    /**
     * 发送预检：清空输入框 -> persona 切换 -> 组装正文窗口 -> 用户消息落库。
     *
     * 失败时把正文写回输入框并置 error，返回 null；调用方只在拿到非 null 时才进入生成。
     * 入口先把输入框清空（立刻给用户「发出去了」的反馈），所以这里的每个失败分支
     * 都必须把原文还回去，不能吞掉用户打的字。
     */
    private suspend fun prepareSend(
        entrySessionId: String?,
        pendingText: String,
        imageUrl: String?,
        videoUrl: String?
    ): PreparedSend? {
        // 立刻清空输入框：用户点完发送就该看到「已经发出去了」的反馈。
        // 必须放在整条链路最前面 —— 下面的预检（persona 切换、历史窗口组装）在界面上
        // 本来什么都不会变，把清输入拖到它之后就是「点了没反应」，用户会一直补点。
        withUiIfActive(entrySessionId) {
            uiState.update { it.copy(inputText = "", error = null) }
        }
        try {
            sessionController.consumePendingSwitchIfNeeded()
        } catch (e: Exception) {
            restoreInputOnFailure(pendingText, "切换人设失败: ${e.message}")
            return null
        }

        val sessionId = sessionController.conversationSessionId
        if (sessionId.isNullOrBlank()) {
            restoreInputOnFailure(pendingText, "聊天记录尚未加载，请稍后重试")
            return null
        }
        val personaFilename = sessionController.conversationPersonaFilename
            ?: sessionController.personaFilenameForSession(sessionId)
        // 正文窗口与上下文独立；上滑、缩小页面窗口不能改变下一轮的上下文来源。
        val prefixHistory = try {
            chatRepository.loadHistoryFromApi(sessionId).getOrThrow()
            trimHistoryForRequest(
                chatRepository.observeMessageWindow(sessionId, HISTORY_WINDOW_MESSAGES).first().messages
            )
        } catch (e: Exception) {
            restoreInputOnFailure(pendingText, "读取聊天记录失败: ${e.message}", sessionId)
            return null
        }
        val userMessage = Message(
            id = generateBackgroundMessageId(),
            text = pendingText,
            isUser = true,
            timestamp = System.currentTimeMillis(),
            messageType = when {
                !videoUrl.isNullOrBlank() -> "video"
                !imageUrl.isNullOrBlank() -> "image"
                else -> "text"
            },
            imageUrl = imageUrl,
            videoUrl = videoUrl,
            sessionId = sessionId,
            parentId = prefixHistory.lastOrNull()?.id
        )
        // 乐观上屏：气泡先插进 uiState，不等 Room 回流。
        // uiState.messages 由消息 Flow 整体覆盖（ChatSessionObserver.observeMessages），
        // 长会话下那次回流要重算整棵消息树，等它才上屏就是「点发送卡一下」的体感。
        // Room 只在事务提交后通知，下一次回流必然包含这条消息，不会重复也不会丢。
        withUiIfActive(sessionId) {
            uiState.update { state -> state.copy(messages = state.messages + userMessage) }
        }
        val insertResult = chatRepository.insertMessageVariant(userMessage)
        if (insertResult.isFailure) {
            // 写库失败就把乐观插入撤回，避免界面上留一条实际不存在的消息
            withUiIfActive(sessionId) {
                uiState.update { state ->
                    state.copy(messages = state.messages.filterNot { it.id == userMessage.id })
                }
            }
            restoreInputOnFailure(
                pendingText,
                "消息保存失败: ${insertResult.exceptionOrNull()?.message}",
                sessionId
            )
            return null
        }
        persistConversationPreview(userMessage, personaFilename)
        return PreparedSend(userMessage, prefixHistory, personaFilename)
    }

    /**
     * 把要上传的历史裁到后端上下文预算之内。
     *
     * 从最新往回累积，直到接近 [HISTORY_BUDGET_CHARS] 为止；至少保留
     * [HISTORY_MIN_MESSAGES] 条。保留的是最新的若干条（而不是最早的），
     * 与后端预算逻辑一致 —— 它同样只保留最近的内容，多传的部分会被截断。
     *
     * 结果直接决定 `history_override` 的体积，也就决定了走隧道时点发送的等待时间。
     */
    private fun trimHistoryForRequest(history: List<Message>): List<Message> {
        if (history.isEmpty()) return history

        var chars = 0
        var taken = 0
        for (message in history.asReversed()) {
            val next = chars + message.text.length
            if (taken >= HISTORY_MIN_MESSAGES && next > HISTORY_BUDGET_CHARS) break
            chars = next
            taken++
        }
        return history.takeLast(taken)
    }

    /** 编辑某个用户请求会创建同级新版本，旧请求及其后续分支不会删除。 */
    fun editUserMessage(messageId: String, newText: String, model: String = "default") {
        if (newText.isBlank()) return
        launchGeneration(sessionController.conversationSessionId) {
            val currentPath = sessionController.conversationSessionId?.let {
                chatRepository.observeMessages(it).first()
            } ?: return@launchGeneration
            val originalIndex = currentPath.indexOfFirst { it.id == messageId && it.isUser }
            if (originalIndex < 0) return@launchGeneration
            val original = currentPath[originalIndex]
            val prefixHistory = currentPath.take(originalIndex)
            val edited = original.copy(
                id = generateBackgroundMessageId(),
                text = newText.trim(),
                timestamp = System.currentTimeMillis(),
                variantIndex = original.variantCount,
                variantCount = original.variantCount + 1,
                isActiveVariant = true
            )
            chatRepository.insertMessageVariant(edited)
            startAssistantGeneration(
                userMessage = edited,
                prefixHistory = prefixHistory,
                model = model,
                assistantVariantIndex = 0,
                personaFilename = sessionController.conversationPersonaFilename
                    ?: sessionController.personaFilenameForSession(edited.sessionId),
                userVariantOfId = original.id
            )
        }
    }

    /** 对指定 AI 回复重新生成，生成结果作为同一用户请求下的新回复版本。 */
    fun regenerateMessage(messageId: String, model: String = "default") {
        launchGeneration(sessionController.conversationSessionId) {
            val currentPath = sessionController.conversationSessionId?.let {
                chatRepository.observeMessages(it).first()
            } ?: return@launchGeneration
            val aiIndex = currentPath.indexOfFirst { it.id == messageId && !it.isUser }
            if (aiIndex < 1) return@launchGeneration
            // 一条回复可能被表情包/断句切成多条气泡（正文1 -> 图 -> 正文2）。
            // 点其中任意一条都应该重新生成**整轮**，所以往回找到本轮的第一条 AI 气泡 ——
            // 它才是挂在用户消息下、承载版本号的那个节点；直接拿被点的那条当"原回复"
            // 会在第二条气泡上退化成"前一条是图，不是用户消息"从而静默失败。
            var turnStart = aiIndex
            while (turnStart - 1 >= 1 && !currentPath[turnStart - 1].isUser) {
                turnStart--
            }
            val userMessage = currentPath[turnStart - 1]
            if (!userMessage.isUser) return@launchGeneration
            val original = currentPath[turnStart]
            startAssistantGeneration(
                userMessage = userMessage,
                prefixHistory = currentPath.take(turnStart - 1),
                model = model,
                assistantVariantIndex = original.variantCount,
                personaFilename = sessionController.conversationPersonaFilename
                    ?: sessionController.personaFilenameForSession(userMessage.sessionId),
                assistantVariantOfId = original.id
            )
        }
    }

    fun selectVariant(messageId: String, offset: Int) {
        val message = uiState.value.messages.firstOrNull { it.id == messageId } ?: return
        val target = message.variantIndex + offset
        if (target !in 0 until message.variantCount) return
        scope.launch {
            chatRepository.selectSiblingVariant(message, target).onFailure { e ->
                uiState.update { it.copy(error = "切换消息版本失败: ${e.message}") }
            }
        }
    }

    /**
     * 当前调用已经位于进程级后台作用域；这里仅冻结本次请求的模型和消息 ID，
     * 后续不再读取可变的当前 persona/model，避免用户退出后切到其它角色导致串路由。
     */
    private suspend fun startAssistantGeneration(
        userMessage: Message,
        prefixHistory: List<Message>,
        model: String,
        assistantVariantIndex: Int,
        personaFilename: String?,
        sendText: String? = null,
        userVariantOfId: String? = null,
        assistantVariantOfId: String? = null
    ) {
        val requestModel = resolveRoleModelRoute()?.takeIf { it.isNotBlank() } ?: model
        runAssistantGeneration(
            userMessage = userMessage,
            prefixHistory = prefixHistory,
            requestModel = requestModel,
            personaFilename = personaFilename,
            assistantVariantIndex = assistantVariantIndex,
            aiMessageId = generateBackgroundMessageId(),
            sendText = sendText,
            userVariantOfId = userVariantOfId,
            assistantVariantOfId = assistantVariantOfId
        )
    }

    private suspend fun runAssistantGeneration(
        userMessage: Message,
        prefixHistory: List<Message>,
        requestModel: String,
        personaFilename: String?,
        assistantVariantIndex: Int,
        aiMessageId: String,
        sendText: String? = null,
        userVariantOfId: String? = null,
        assistantVariantOfId: String? = null
    ) {
        val sessionId = userMessage.sessionId
        val aiMessageStart = System.currentTimeMillis()
        val aiPlaceholder = Message(
            id = aiMessageId,
            text = "",
            isUser = false,
            timestamp = aiMessageStart,
            messageType = "text",
            sessionId = sessionId,
            parentId = userMessage.id,
            variantIndex = assistantVariantIndex,
            variantCount = (assistantVariantIndex + 1).coerceAtLeast(1)
        )
        // 与用户气泡同理：占位消息先上屏，「对方正在输入」立刻出现，
        // 后面的 SSE 首字节等待（走公网时是几百毫秒到数秒）才不会被误读成"卡住了"。
        withUiIfActive(sessionId) {
            uiState.update {
                it.copy(
                    messages = it.messages + aiPlaceholder,
                    isTyping = true,
                    showTypingIndicator = true,
                    inputText = "",
                    error = null
                )
            }
            ttsController.startStreamingIfEnabled(aiMessageId)
        }
        chatRepository.insertMessageVariant(aiPlaceholder)

        // 本轮生成的任务登记/摘除由外层 launchGeneration 统一负责：它从预检之前就开始
        // 覆盖，而这里只能覆盖"占位气泡上屏之后"的一段，登记晚一步就会出现
        // "按钮已经能按、表里却还没得可停"的空窗。
        val fullText = StringBuilder()
        // 本轮回复的全部正文（跨多条气泡）。只用于后台通知的正文，不影响落库结构。
        val replyText = StringBuilder()
        var finalEmotion: String? = null
        // 是否产出过图片/视频：这类回复正文可以是空的（AI 只丢一张表情包），
        // 此时空占位消息要保留 —— 图片消息的 parentId 挂在它下面，删了就成孤儿。
        var hasMedia = false
        // 为什么媒体不能都挂在 aiMessageId 下：消息树把「同一个父节点 + 同为
        // 用户/AI」的节点当作**互为版本**（见 selectActiveConversationPath 的
        // variantCount = siblings.size）。连着发 3 张表情包时三条都是 aiMessageId
        // 的子节点，于是被折叠成一个槽位，界面只显示第 1 张、右侧多出一个
        // 「1/3 切换键」，要手动点才能看到剩下两张 —— 而 QQ/微信 是三条气泡竖着
        // 排下来。串成一条链后每张的兄弟数都是 1，variantCount = 1，不再出现切换键。
        //
        // 链尾直接复用下面的 textMessageId，不要再单独维护一个"媒体链尾"变量：
        // 媒体挂在"当前正文气泡"下，封口时又在媒体下面新开一条正文气泡，于是天然串成
        //   正文1 -> 图1 -> 空占位 -> 图2 -> 空占位 -> 图3 -> 正文2
        // （空占位渲染成"什么都不显示"，只当链上的连接点）。
        // 若改成"下一张图挂上一张图"，第二张图就会与那段的空占位互为兄弟，被挤出
        // 活跃路径（selectActiveMessageEntities 每层只跟一个激活子节点）—— 表现为
        // 连发多张时只剩第一张可见。
        // 当前正在累积正文的气泡：收到媒体事件时它会"封口"，后续文字落到新气泡里。
        // 后端现在按 [MEME] 标签的位置下发图片（图紧跟标签所在那句话），所以"收到图"
        // 就等于"这句话说完了、下面的话属于另一条气泡"。
        var textMessageId = aiMessageId
        var textParentId: String? = userMessage.id
        var textVariantIndex = assistantVariantIndex
        var textBubbleTimestamp = aiMessageStart

        /**
         * 把当前正文气泡封口，并为后续文字开一条挂在 [nextParentId] 下的新气泡。
         *
         * 封口 = 把已累积的正文落库（原先只在整轮结束时写一次，有了气泡切分后
         * 每条被封的气泡都得自己写），然后清空缓冲、把"当前气泡"指向新节点。
         * 正文为空时不写库：那条空气泡留在树上当链接（渲染成空气泡，看不见），
         * 保证"回复以表情包开头/结尾"时消息链不断。
         */
        suspend fun sealTextBubbleAndStartNext(nextParentId: String) {
            val sealedText = TextSegmenter.clean(fullText.toString())
            if (sealedText.isNotBlank()) {
                chatRepository.insertMessage(
                    Message(
                        id = textMessageId,
                        text = sealedText,
                        isUser = false,
                        timestamp = textBubbleTimestamp,
                        messageType = "text",
                        sessionId = sessionId,
                        parentId = textParentId,
                        variantIndex = textVariantIndex
                    )
                ).onFailure { e -> Log.e(TAG, "写入分段正文失败", e) }
                withUiIfActive(sessionId) {
                    uiState.update { state ->
                        state.copy(
                            messages = state.messages.map {
                                if (it.id == textMessageId) it.copy(text = sealedText) else it
                            }
                        )
                    }
                }
            }
            fullText.clear()

            val nextPlaceholder = Message(
                id = generateBackgroundMessageId(),
                text = "",
                isUser = false,
                timestamp = System.currentTimeMillis(),
                messageType = "text",
                sessionId = sessionId,
                parentId = nextParentId
            )
            // 上屏必须排在落库**之前**，与上面图片/视频消息的顺序保持一致。
            //
            // 反过来（先落库、再上屏）会踩一个偶发闪退：insertMessage 返回后，Room 的
            // Flow 随时可能发射，把 messages 整体替换成"已经包含这条占位"的活跃路径。
            // 若这次发射恰好挤在"落库"和"上屏"之间，紧接着的 append 就把同一条消息
            // 加了第二次，LazyColumn 的 key 重复 →
            // IllegalArgumentException: Key "..." was already used，整个进程闪退。
            // 表现为"角色发图时偶尔崩"，且只发生在有表情包/图片的那一轮。
            //
            // 先上屏、后落库时，随后的 Flow 发射是**整体替换**，天然去重。
            // append 本身再做一层幂等（先按 id 摘掉再追加），双保险。
            withUiIfActive(sessionId) {
                uiState.update { state ->
                    state.copy(
                        messages = state.messages.filterNot { it.id == nextPlaceholder.id } +
                            nextPlaceholder
                    )
                }
            }
            // 用 insertMessage 而不是 insertMessageVariant：这是正文链上的下一环，
            // 不是同一节点的另一个版本，不能去动兄弟节点的 isActiveVariant
            chatRepository.insertMessage(nextPlaceholder)
                .onFailure { e -> Log.e(TAG, "写入分段占位消息失败", e) }
            textMessageId = nextPlaceholder.id
            textParentId = nextParentId
            textVariantIndex = 0
            textBubbleTimestamp = nextPlaceholder.timestamp
        }

        // 用计数器派生出的值同步 WS 抑制，而不是写死 true：同一会话上一轮可能还没收完。
        flushManager.setHttpStreamingActive(markHttpStreamStarted())
        try {
            // 图片消息的用户气泡 text 存的是「用户文案（caption）」，真正要发给后端的是
            // 识别结果文本（含 [图像识别结果：...] + caption）。sendText 只在图片发送路径
            // 显式传入，其余路径回退到 userMessage.text 保持原行为。
            val effectiveSendText = sendText ?: userMessage.text
            chatRepository.sendMessageStreaming(
                effectiveSendText,
                sessionId,
                requestModel,
                personaFilename,
                prefixHistory,
                ChatBranchContext(
                    userMessage = userMessage,
                    assistantMessage = aiPlaceholder,
                    userVariantOfId = userVariantOfId,
                    assistantVariantOfId = assistantVariantOfId
                )
            ).collect { event ->
                when (event) {
                    is StreamEvent.Chunk -> {
                        fullText.append(event.content)
                        replyText.append(event.content)
                        withUiIfActive(sessionId) {
                            ttsController.appendStreamingChunk(event.content)
                            uiState.update { state ->
                                val updatedMessages = state.messages.map {
                                    if (it.id == textMessageId) {
                                        it.copy(text = fullText.toString())
                                    } else {
                                        it
                                    }
                                }
                                state.copy(messages = updatedMessages)
                            }
                        }
                    }
                    is StreamEvent.Done -> {
                        finalEmotion = event.emotion
                        withUiIfActive(sessionId) {
                            ttsController.finishStreamingIfEnabled()
                        }
                    }
                    is StreamEvent.Error -> {
                        withUiIfActive(sessionId) {
                            ttsController.stopIfEnabled()
                            uiState.update {
                                it.copy(
                                    error = "生成失败: ${event.message}",
                                    isTyping = false,
                                    showTypingIndicator = false
                                )
                            }
                        }
                    }
                    is StreamEvent.Reset -> {
                        // 只清当前这条气泡：AI 开始调用工具，正在生成的临时消息作废。
                        // 已经被表情包"封口"的前几条气泡保持不动（正文确实已经发出去了）。
                        fullText.clear()
                        withUiIfActive(sessionId) {
                            ttsController.finishStreamingIfEnabled()
                            uiState.update { state ->
                                val updatedMessages = state.messages.map {
                                    if (it.id == textMessageId) it.copy(text = "") else it
                                }
                                state.copy(
                                    messages = updatedMessages,
                                    isTyping = true,
                                    showTypingIndicator = true
                                )
                            }
                        }
                    }
                    is StreamEvent.ImageResult -> {
                        hasMedia = true
                        // 图挂在"当前正文气泡"后面；封口后会在图下面新开一条正文气泡，
                        // 下一张图再挂到那条新气泡下，连发多张时自然串成一条链。
                        val imageMessage = Message(
                            id = generateBackgroundMessageId(),
                            text = "",
                            isUser = false,
                            timestamp = System.currentTimeMillis(),
                            messageType = "image",
                            imageUrl = event.imageUrl,
                            sessionId = sessionId,
                            parentId = textMessageId
                        )
                        withUiIfActive(sessionId) {
                            uiState.update { state ->
                                state.copy(messages = state.messages + imageMessage)
                            }
                        }
                        val result = chatRepository.insertMessage(imageMessage)
                        result.onFailure { e -> Log.e(TAG, "写入图片消息失败", e) }
                        if (result.isSuccess) {
                            persistConversationPreview(imageMessage, personaFilename)
                        }
                        // 再把刚发完的那句话封口，后续文字开一条挂在图下面的新气泡：
                        // 最终链路是 正文1 -> 图 -> 正文2 -> 图 -> 正文3
                        sealTextBubbleAndStartNext(imageMessage.id)
                    }
                    is StreamEvent.VideoResult -> {
                        hasMedia = true
                        // 与图片同理：视频也接在"当前正文气泡"后面，由封口逻辑串成链
                        val videoMessage = Message(
                            id = generateBackgroundMessageId(),
                            text = "",
                            isUser = false,
                            timestamp = System.currentTimeMillis(),
                            messageType = "video",
                            videoUrl = event.videoUrl,
                            sessionId = sessionId,
                            parentId = textMessageId
                        )
                        withUiIfActive(sessionId) {
                            uiState.update { state ->
                                state.copy(messages = state.messages + videoMessage)
                            }
                        }
                        val result = chatRepository.insertMessage(videoMessage)
                        result.onFailure { e -> Log.e(TAG, "写入视频消息失败", e) }
                        if (result.isSuccess) {
                            persistConversationPreview(videoMessage, personaFilename)
                        }
                        sealTextBubbleAndStartNext(videoMessage.id)
                    }
                }
            }
        } catch (e: CancellationException) {
            // 协程被取消：用户点了「停止生成」、用户离开页面，或后端 cancel 了上一轮。
            // 取消信号必须原样上抛（吞掉会让上层误以为这一轮"正常跑完了"），
            // 但**收尾不能跟着一起跳过** —— 直接上抛的话 isTyping 会永远停在 true、
            // 已经流出来的正文也不会落库，界面就卡在"正在输入"、气泡停在半截。
            // 所以先在 NonCancellable 里走一遍收尾（只是不发"回复完成"通知），再上抛。
            //
            // 必须 NonCancellable：此刻协程已是取消态，收尾里的每个挂起点（落库、
            // 清空占位、关打字指示器）都会立刻再抛 CancellationException，收尾会半途而废。
            withContext(NonCancellable) {
                finalizeAssistantBubble(
                    sessionId = sessionId,
                    textMessageId = textMessageId,
                    fullText = fullText.toString(),
                    replyText = replyText.toString(),
                    hasMedia = hasMedia,
                    textParentId = textParentId,
                    textVariantIndex = textVariantIndex,
                    textBubbleTimestamp = textBubbleTimestamp,
                    finalEmotion = finalEmotion,
                    personaFilename = personaFilename,
                    notify = false
                )
            }
            throw e
        } catch (e: Exception) {
            // 兜底：流式过程中任何未预期异常都只让"这一轮"失败，不再冒泡到线程默认
            // 异常处理器把整个进程带走 —— 那正是"角色发图时偶尔闪退"当初的表现形式。
            // 失败必须落成用户可见的 error 并关掉打字指示器，否则界面会一直卡在"正在输入"。
            Log.e(TAG, "生成回复过程中发生未预期异常", e)
            withUiIfActive(sessionId) {
                uiState.update {
                    it.copy(
                        error = "生成失败: ${e.message ?: e.javaClass.simpleName}",
                        isTyping = false,
                        showTypingIndicator = false
                    )
                }
            }
        } finally {
            // 生成任务的登记/摘除由外层 launchGeneration 负责（见那里对登记时机的说明），
            // 这里只做流式通道状态收尾。
            // 先摘计数器再同步抑制开关：本轮可能是"旧轮"，此时新一轮还在跑，
            // 计数不会归零，返回值仍是 true，WS 抑制不会被提前放开。
            flushManager.setHttpStreamingActive(markHttpStreamFinished())
        }

        // 正常结束：收尾统一走 finalizeAssistantBubble（与「停止生成」共用同一套落库口径）。
        finalizeAssistantBubble(
            sessionId = sessionId,
            textMessageId = textMessageId,
            fullText = fullText.toString(),
            replyText = replyText.toString(),
            hasMedia = hasMedia,
            textParentId = textParentId,
            textVariantIndex = textVariantIndex,
            textBubbleTimestamp = textBubbleTimestamp,
            finalEmotion = finalEmotion,
            personaFilename = personaFilename,
            notify = true
        )
    }

    /**
     * 本轮生成的收尾：空占位清理 / 正文落库 / 完成通知。
     *
     * 抽成独立函数是因为它有**两个调用方**——正常结束、以及被取消（用户点「停止生成」，
     * 或后端 cancel 了上一轮）。落库口径只能有一处，否则以后改了正常路径必然漏掉取消路径。
     * 注意 `catch (e: Exception)` 那条失败分支**不走**这里：异常时这一轮正文不落库，
     * 只报错并关掉打字指示器。
     *
     * @param notify 是否发「回复完成」通知。用户主动停止时传 false：
     *   那是用户自己的动作，不该在他切到别的 App 时弹一条"她回你了"把人叫回来。
     */
    private suspend fun finalizeAssistantBubble(
        // 可空：来源是 Message.sessionId（本身是 String?）。落库、withUiIfActive 都接受 null，
        // 这里跟着用 String? 就行，不要为了"看起来更严格"收成非空 —— 那会在调用处报类型不符。
        sessionId: String?,
        textMessageId: String,
        fullText: String,
        replyText: String,
        hasMedia: Boolean,
        textParentId: String?,
        textVariantIndex: Int,
        textBubbleTimestamp: Long,
        finalEmotion: String?,
        personaFilename: String?,
        notify: Boolean
    ) {
        // 一条内容都没收到时（生成失败、后端返回错误、流静默结束、用户立刻点了停止），
        // 开头插的空占位消息会变成一条空白气泡永久留在会话里：UI 只在
        // showTypingIndicator=true 时把它当 typing 占位渲染（ChatMessageList 的
        // isBlankAssistantPlaceholder），生成一结束 typing 关掉，它就显形成空气泡，
        // 用户看到的就是「AI 回了一条空的」甚至以为卡住了。这里直接把它清掉。
        val finalText = TextSegmenter.clean(fullText)
        if (finalText.isBlank() && !hasMedia) {
            withUiIfActive(sessionId) { ttsController.stopIfEnabled() }
            chatRepository.deleteMessage(textMessageId).onFailure { e ->
                Log.w(TAG, "清理空白占位消息失败: ${e.message}")
            }
            withUiIfActive(sessionId) {
                uiState.update { state ->
                    state.copy(
                        messages = state.messages.filterNot { it.id == textMessageId },
                        isTyping = false,
                        showTypingIndicator = false
                    )
                }
            }
            return
        }

        val finalMessage = Message(
            id = textMessageId,
            text = finalText,
            isUser = false,
            timestamp = textBubbleTimestamp,
            messageType = "text",
            sessionId = sessionId,
            parentId = textParentId,
            variantIndex = textVariantIndex,
            emotion = finalEmotion
        )

        withUiIfActive(sessionId) {
            uiState.update { state ->
                val updatedMessages = state.messages.map {
                    if (it.id == textMessageId) {
                        it.copy(text = finalText, emotion = finalEmotion)
                    } else {
                        it
                    }
                }
                state.copy(
                    messages = updatedMessages,
                    isTyping = false,
                    showTypingIndicator = false,
                    currentEmotion = finalEmotion?.let { emo -> mapEmotion(emo) }
                        ?: state.currentEmotion
                )
            }
        }

        // 关键：最终落库必须跟随后台生成作用域，绝不能再切回 viewModelScope。
        // 页面即使已经销毁，这一步仍会完成；重新进入聊天后 Room Flow 会直接恢复完整回复。
        val result = chatRepository.insertMessage(finalMessage)
        result.onFailure { e -> Log.e(TAG, "消息版本写库失败", e) }
        if (result.isSuccess && finalMessage.text.isNotBlank()) {
            persistConversationPreview(finalMessage, personaFilename)
        }
        // 落库成功后才提醒：用户发完消息切到别的 App，AI 回完这一刻要弹窗把人叫回来。
        // 必须放在这里（而非 withUiIfActive 内）：用户已经离开聊天页时 UI 分支会整段跳过，
        // 而通知恰恰只在离开时才有意义。
        //
        // 通知正文用整轮回复（replyText）而不是最后一条气泡：回复被表情包切成多段后，
        // 末段可能是空气泡（"……[MEME]"结尾），拿它当正文会弹出一条空通知。
        if (result.isSuccess && notify) {
            notifyReplyAndBumpUnread(
                message = finalMessage.copy(text = TextSegmenter.clean(replyText)),
                personaFilename = personaFilename
            )
        }
    }

    /**
     * 后台回复完成后的未读标记与通知。
     *
     * 与主动关怀（WebSocket proactive_message）表现对齐：
     * - 会话列表未读 +1，用户切回来能看到红点；
     * - App 在后台时弹一条 QQ/微信式通知（角色头像 + 昵称作标题 + 正文）。
     *
     * 前台时只加未读不弹通知（回复已经直接上屏，再弹横幅属于重复打扰），
     * 是否弹由 [RoleReplyNotifier.notifyReplyIfBackground] 内部判定。
     */
    private suspend fun notifyReplyAndBumpUnread(
        message: Message,
        personaFilename: String?
    ) {
        val filename = personaFilename?.takeIf { it.isNotBlank() } ?: return
        if (AppForegroundTracker.isForeground) return
        runCatching {
            personaLocalMetaRepository.incrementUnread(filename)
        }.onFailure { e ->
            Log.w(TAG, "后台回复未读计数失败: ${e.message}", e)
        }
        val notifier = replyNotifier ?: return
        runCatching {
            notifier.notifyReplyIfBackground(
                RoleReplyNotifier.ReplyNotification(
                    role = RoleReplyNotifier.roleIdFromPersonaFilename(filename),
                    personaFilename = filename,
                    fallbackTitle = null,
                    body = TextSegmenter.clean(message.text)
                )
            )
        }.onFailure { e ->
            Log.w(TAG, "后台回复通知发布失败: ${e.message}", e)
        }
    }

    /**
     * 会话列表预览使用 PersonaLocalMeta，不是直接观察 Room。
     * 因此后台生成完成后必须同步更新 meta，否则消息虽已持久化，列表仍会停在“我：上一条消息”。
     */
    private suspend fun persistConversationPreview(message: Message, personaFilename: String?) {
        val filename = personaFilename?.takeIf { it.isNotBlank() } ?: return
        runCatching {
            personaLocalMetaRepository.updateLastMessage(
                personaFilename = filename,
                preview = ChatPreviewBuilder.buildPreviewText(
                    text = message.text,
                    isUser = message.isUser,
                    messageType = message.messageType,
                    imageUrl = message.imageUrl,
                    videoUrl = message.videoUrl
                ),
                timestamp = message.timestamp
            )
        }.onFailure { e ->
            Log.w(TAG, "更新后台消息会话预览失败: ${e.message}")
        }
    }

    /**
     * 预检失败时把正文写回输入框。
     *
     * 发送入口会先把输入框清空（好让用户立刻看到「已经发出去了」），所以任何
     * 「消息还没落库就退出」的分支都必须把原文还回去，否则用户打的字凭空消失。
     * 只在输入框仍为空时回填：预检期间用户可能已经重新开始输入，不能覆盖新的内容。
     */
    private suspend fun restoreInputOnFailure(text: String, error: String, sessionId: String? = null) {
        withUiIfActive(sessionId) {
            uiState.update {
                it.copy(inputText = if (it.inputText.isBlank()) text else it.inputText, error = error)
            }
        }
    }

    /** 页面销毁后后台生成继续，但旧 UI 和 TTS 不再接收更新。 */
    private fun isUiScopeActive(): Boolean =
        scope.coroutineContext[Job]?.isActive == true

    private suspend inline fun withUiIfActive(sessionId: String? = null, crossinline block: () -> Unit) {
        if (!isUiScopeActive()) return
        withContext(Dispatchers.Main.immediate) {
            if (isUiScopeActive() && (sessionId == null ||
                    (sessionController.conversationSessionId == sessionId &&
                        uiState.value.currentSession?.id == sessionId))) block()
        }
    }
}
