package com.aveline.ai.mobile.presentation.chat

import android.content.ClipboardManager
import android.content.Context
import android.content.SharedPreferences
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.local.preferences.ChatDraftStore
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.domain.models.Session
import com.aveline.ai.mobile.domain.repository.ChatMessageWindow
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.domain.repository.PersonaRepository
import com.aveline.ai.mobile.domain.repository.SessionRepository
import com.aveline.ai.mobile.domain.repository.ToolsRepository
import com.aveline.ai.mobile.services.FileUploadManager
import com.aveline.ai.mobile.services.TTSEngine
import com.aveline.ai.mobile.services.TTSState
import com.aveline.ai.mobile.services.UploadState
import com.aveline.ai.mobile.services.VoiceInputManager
import com.aveline.ai.mobile.services.VoiceInputState
import io.mockk.coEvery
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

private const val SESSION_A = "session-a"
private const val SESSION_B = "session-b"

/**
 * 输入框草稿端到端行为（ViewModel 级）。
 *
 * 覆盖：打字 -> 落盘 -> 退出聊天页 -> 重新进入同一会话 -> 内容回到输入框。
 * ViewModel 的草稿流水线跑在 Dispatchers.IO 上并有 400ms debounce，
 * 这里用真实时间的轮询等待（与 PreservationPropertyTest 里后台发送管线的等待方式一致），
 * 不依赖 sleep 的精确时长，超时上限给到 3 秒。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ChatInputDraftTest {

    @get:Rule
    val mainDispatcherRule = com.aveline.ai.mobile.util.MainDispatcherRule(UnconfinedTestDispatcher())

    private lateinit var mockContext: Context
    private lateinit var mockChatRepository: ChatRepository
    private lateinit var mockSessionRepository: SessionRepository
    private lateinit var mockWebSocketManager: WebSocketManager
    private lateinit var mockFileUploadManager: FileUploadManager
    private lateinit var mockTTSEngine: TTSEngine
    private lateinit var mockVoiceInputManager: VoiceInputManager
    private lateinit var mockAppPreferences: AppPreferences
    private lateinit var mockPersonaRepository: PersonaRepository
    private lateinit var mockPersonaLocalMetaRepository: PersonaLocalMetaRepository
    private lateinit var mockToolsRepository: ToolsRepository

    private val webSocketMessagesFlow = MutableSharedFlow<WebSocketMessage>(extraBufferCapacity = 64)
    private val connectionStateFlow = MutableStateFlow(WebSocketManager.ConnectionState.DISCONNECTED)
    private val sessionFlow = MutableStateFlow<Session?>(null)

    /** 全局"当前会话"，切会话用例会改它。 */
    private var currentSessionId: String? = null

    private lateinit var draftStore: ChatDraftStore

    @Before
    fun setUp() {
        mockContext = mockk(relaxed = true)
        mockChatRepository = mockk(relaxed = true)
        mockSessionRepository = mockk(relaxed = true)
        mockWebSocketManager = mockk(relaxed = true)
        mockFileUploadManager = mockk(relaxed = true)
        mockTTSEngine = mockk(relaxed = true)
        mockVoiceInputManager = mockk(relaxed = true)
        mockAppPreferences = mockk(relaxed = true)
        mockPersonaRepository = mockk(relaxed = true)
        mockPersonaLocalMetaRepository = mockk(relaxed = true)
        mockToolsRepository = mockk(relaxed = true)

        every { mockWebSocketManager.messages } returns webSocketMessagesFlow
        every { mockWebSocketManager.connectionState } returns connectionStateFlow
        every { mockSessionRepository.observeCurrentSession() } returns sessionFlow
        every { mockPersonaRepository.observeActivePersona() } returns flowOf(null)

        coEvery { mockChatRepository.observeMessages(any()) } returns flowOf(emptyList())
        coEvery { mockChatRepository.observeMessageWindow(any(), any()) } returns flowOf(
            ChatMessageWindow(emptyList(), hasOlder = false)
        )
        coEvery { mockChatRepository.loadHistoryFromApi(any()) } returns Result.success(emptyList())
        coEvery { mockPersonaLocalMetaRepository.observeAll() } returns flowOf(emptyList())

        every { mockAppPreferences.effectiveBackendUrl } returns "http://localhost:8000"
        every { mockAppPreferences.accessToken } returns ""
        every { mockAppPreferences.currentSessionId } answers { currentSessionId }

        every { mockVoiceInputManager.state } returns MutableStateFlow(VoiceInputState.Idle)
        every { mockVoiceInputManager.partialText } returns MutableStateFlow("")
        every { mockVoiceInputManager.amplitude } returns MutableStateFlow(0f)
        every { mockTTSEngine.state } returns MutableStateFlow(TTSState.Idle)
        every { mockFileUploadManager.uploadState } returns MutableStateFlow(UploadState.Idle)
        every { mockContext.getSystemService(Context.CLIPBOARD_SERVICE) } returns
            mockk<ClipboardManager>(relaxed = true)

        draftStore = buildDraftStore()
    }

    private fun buildDraftStore(): ChatDraftStore {
        val values = mutableMapOf<String, Any?>()
        val editor = mockk<SharedPreferences.Editor>(relaxed = true)
        val prefs = mockk<SharedPreferences>()
        val context = mockk<Context>()
        every { context.getSharedPreferences(any(), any()) } returns prefs
        every { prefs.edit() } returns editor
        every { prefs.all } answers { values.toMap() }
        every { prefs.getString(any(), any()) } answers {
            values[firstArg<String>()] as? String ?: secondArg<String?>()
        }
        every { prefs.getLong(any(), any()) } answers {
            values[firstArg<String>()] as? Long ?: secondArg<Long>()
        }
        every { editor.putString(any(), any()) } answers {
            values[firstArg()] = secondArg<String>()
            editor
        }
        every { editor.putLong(any(), any()) } answers {
            values[firstArg()] = secondArg<Long>()
            editor
        }
        every { editor.remove(any()) } answers {
            values.remove(firstArg<String>())
            editor
        }
        return ChatDraftStore(context)
    }

    private fun buildViewModel(): ChatViewModel = ChatViewModel(
        context = mockContext,
        chatRepository = mockChatRepository,
        sessionRepository = mockSessionRepository,
        webSocketManager = mockWebSocketManager,
        fileUploadManager = mockFileUploadManager,
        ttsEngine = mockTTSEngine,
        voiceInputManager = mockVoiceInputManager,
        appPreferences = mockAppPreferences,
        personaRepository = mockPersonaRepository,
        personaLocalMetaRepository = mockPersonaLocalMetaRepository,
        toolsRepository = mockToolsRepository,
        draftStore = draftStore
    )

    private fun session(id: String) = Session(
        id = id,
        title = id,
        createdAt = 0L,
        updatedAt = 0L
    )

    /** 轮询等待：草稿流水线跑在真实 IO 线程上，不能用虚拟时间推进。 */
    private fun awaitUntil(timeoutMs: Long = 3000L, condition: () -> Boolean): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (condition()) return true
            Thread.sleep(20)
        }
        return condition()
    }

    /**
     * 建 ViewModel 并等它认领会话（把该会话已有的草稿读进输入框）。
     *
     * 必须先等这一步：草稿归属（ViewModel 里的 draftSessionId）是在会话 flow 首帧才建立的，
     * 在此之前敲的字无处安放。用一条哨兵草稿把"认领完成"显式暴露出来，
     * 避免测试和用户抢那几十毫秒。
     */
    private fun buildViewModelWithSession(id: String, sentinelDraft: String = ""): ChatViewModel {
        currentSessionId = id
        sessionFlow.value = session(id)
        draftStore.writeDraft(id, sentinelDraft)
        val viewModel = buildViewModel()
        assertTrue(
            "会话就绪后应把它已有的草稿读回输入框，实际是 '${viewModel.uiState.value.inputText}'",
            awaitUntil { viewModel.uiState.value.inputText == sentinelDraft }
        )
        return viewModel
    }

    @Test
    fun `退出聊天页再回来，输入框里没发出去的字还在`() {
        val lastDraft = "半句没说完的话"
        val viewModel = buildViewModelWithSession(SESSION_A, sentinelDraft = lastDraft)

        val edited = "$lastDraft，补上后半句"
        viewModel.updateInputText(edited)
        assertTrue(
            "打字停顿后草稿应该落盘",
            awaitUntil { draftStore.readDraft(SESSION_A) == edited }
        )

        // 聊天页 dispose + ViewModel.onCleared 都会走这一步，这里模拟"返回会话列表"。
        viewModel.flushInputDraft()

        // 返回列表后 ViewModel 被清掉，再进来是一个全新的实例。
        val reentered = buildViewModel()
        assertTrue(
            "重新进入同一会话应把草稿填回输入框，实际是 '${reentered.uiState.value.inputText}'",
            awaitUntil { reentered.uiState.value.inputText == edited }
        )
    }

    @Test
    fun `发送后输入框被清空时草稿同步删除`() {
        val viewModel = buildViewModelWithSession(SESSION_A, sentinelDraft = "这句已经被发出去了")

        // 发送流水线就是把 inputText 置 ""（见 ChatSendController.prepareSend）。
        viewModel.updateInputText("")

        assertTrue(
            "发出去的内容不能留在草稿里",
            awaitUntil { draftStore.readDraft(SESSION_A).isEmpty() }
        )

        val reentered = buildViewModelWithSession(SESSION_A)
        assertEquals("重进聊天不该再看到已发出的内容", "", reentered.uiState.value.inputText)
    }

    @Test
    fun `切换会话时草稿按会话归档，互不串台`() {
        val viewModel = buildViewModelWithSession(SESSION_A, sentinelDraft = "给 A 的话")

        viewModel.updateInputText("给 A 的补充")
        awaitUntil { draftStore.readDraft(SESSION_A) == "给 A 的补充" }

        // 切到 B：A 还没说完的话留在 A 的草稿里，输入框换成 B 的草稿（此时是空的）。
        currentSessionId = SESSION_B
        sessionFlow.value = session(SESSION_B)
        assertTrue(
            "切到别的会话时输入框应让位给该会话自己的草稿",
            awaitUntil { viewModel.uiState.value.inputText.isEmpty() }
        )

        viewModel.updateInputText("给 B 的话")
        awaitUntil { draftStore.readDraft(SESSION_B) == "给 B 的话" }
        assertEquals("A 的草稿不能被 B 覆盖", "给 A 的补充", draftStore.readDraft(SESSION_A))

        // 切回 A，草稿要跟着换回来。
        currentSessionId = SESSION_A
        sessionFlow.value = session(SESSION_A)
        assertTrue(
            "切回 A 应恢复 A 的草稿，实际是 '${viewModel.uiState.value.inputText}'",
            awaitUntil { viewModel.uiState.value.inputText == "给 A 的补充" }
        )
        assertEquals("B 的话应留在 B 自己的草稿里", "给 B 的话", draftStore.readDraft(SESSION_B))
    }
}
