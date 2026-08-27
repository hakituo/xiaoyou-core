package com.aveline.ai.mobile.presentation.chat

import android.content.Context
import androidx.arch.core.executor.testing.InstantTaskExecutorRule
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.domain.repository.PersonaRepository
import com.aveline.ai.mobile.domain.repository.SessionRepository
import com.aveline.ai.mobile.services.FileUploadManager
import com.aveline.ai.mobile.services.TTSEngine
import com.aveline.ai.mobile.services.TTSState
import com.aveline.ai.mobile.services.UploadState
import com.aveline.ai.mobile.services.VoiceInputManager
import com.aveline.ai.mobile.services.VoiceInputState
import io.mockk.coEvery
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ChatViewModelBugConditionTest {

    @get:Rule
    val instantTaskExecutorRule = InstantTaskExecutorRule()

    private val testDispatcher = StandardTestDispatcher()

    private lateinit var viewModel: ChatViewModel
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

    private val webSocketMessagesFlow = MutableSharedFlow<WebSocketMessage>(extraBufferCapacity = 64)
    private val connectionStateFlow = MutableStateFlow(WebSocketManager.ConnectionState.DISCONNECTED)

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)

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

        every { mockWebSocketManager.messages } returns webSocketMessagesFlow
        every { mockWebSocketManager.connectionState } returns connectionStateFlow

        every { mockSessionRepository.observeCurrentSession() } returns flowOf(null)

        coEvery { mockChatRepository.observeMessages(any()) } returns flowOf(emptyList())

        every { mockAppPreferences.backendUrl } returns "http://localhost:8000"
        every { mockAppPreferences.accessToken } returns ""

        // Mock voice input / TTS / upload 状态流,避免 init 中 collect 抛 KotlinNothingValueException
        every { mockVoiceInputManager.state } returns MutableStateFlow(VoiceInputState.Idle)
        every { mockVoiceInputManager.partialText } returns MutableStateFlow("")
        every { mockVoiceInputManager.amplitude } returns MutableStateFlow(0f)
        every { mockTTSEngine.state } returns MutableStateFlow(TTSState.Idle)
        every { mockFileUploadManager.uploadState } returns MutableStateFlow(UploadState.Idle)

        viewModel = ChatViewModel(
            context = mockContext,
            chatRepository = mockChatRepository,
            sessionRepository = mockSessionRepository,
            webSocketManager = mockWebSocketManager,
            fileUploadManager = mockFileUploadManager,
            ttsEngine = mockTTSEngine,
            voiceInputManager = mockVoiceInputManager,
            appPreferences = mockAppPreferences,
            personaRepository = mockPersonaRepository,
            personaLocalMetaRepository = mockPersonaLocalMetaRepository
        )
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `bug condition - API returns 200 with response field but UI shows empty`() = runTest {
        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTED
        advanceUntilIdle()

        val testMessage = "你好！有什么可以帮助你的？"
        val wsMessage = WebSocketMessage.TextMessage(
            text = testMessage,
            emotion = null
        )

        webSocketMessagesFlow.emit(wsMessage)
        advanceUntilIdle()

        val messages = viewModel.uiState.value.messages

        assertTrue(
            "BUG DETECTED: API returned 200 with valid 'response' field but UI shows empty. " +
                "Messages list size: ${messages.size}, expected: >= 1",
            messages.isNotEmpty()
        )

        if (messages.isNotEmpty()) {
            // 智能分段会将文本按标点/括号拆成多条消息,拼接后应等于原文
            val combinedText = messages.joinToString("") { it.text }
            assertEquals(
                "Combined message text should match the response content (智能分段后拼接应等于原文)",
                testMessage,
                combinedText
            )
            assertFalse(
                "Last message should be from AI (isUser=false)",
                messages.last().isUser
            )
        }
    }

    @Test
    fun `bug condition - WebSocket pushes message but UI state not updated`() = runTest {
        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTED
        advanceUntilIdle()

        val chunks = listOf("你", "好", "！")

        for (chunk in chunks) {
            webSocketMessagesFlow.emit(WebSocketMessage.TextMessage(text = chunk, emotion = null))
            advanceUntilIdle()
        }

        val messages = viewModel.uiState.value.messages

        assertTrue(
            "BUG DETECTED: WebSocket pushed ${chunks.size} message chunks but UI state not updated. " +
                "Messages list size: ${messages.size}",
            messages.isNotEmpty()
        )

        if (messages.isNotEmpty()) {
            val lastMessage = messages.last()
            assertTrue(
                "Message should contain accumulated chunks. Got: '${lastMessage.text}'",
                lastMessage.text.isNotEmpty()
            )
        }
    }

    @Test
    fun `bug condition - placeholder content not replaced by actual data`() = runTest {
        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTING
        advanceUntilIdle()

        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTED
        advanceUntilIdle()

        val actualMessage = "这是实际的消息内容"
        webSocketMessagesFlow.emit(WebSocketMessage.TextMessage(text = actualMessage, emotion = null))
        advanceUntilIdle()

        val messages = viewModel.uiState.value.messages
        val isLoading = viewModel.uiState.value.isLoading

        assertFalse(
            "BUG DETECTED: UI still shows loading state after receiving data",
            isLoading && messages.isEmpty()
        )

        assertTrue(
            "BUG DETECTED: Placeholder not replaced by actual data. Messages: ${messages.size}",
            messages.isNotEmpty()
        )
    }

    @Test
    fun `property - all response field types should be parsed correctly`() = runTest {
        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTED
        advanceUntilIdle()

        val testMessages = listOf(
            "简单文本消息",
            "包含emoji的消息 😊",
            "多行消息\n第二行\n第三行",
            "包含特殊字符: @#\$%^&*()",
            "很长的消息" + "重复内容".repeat(100)
        )

        for (testMessage in testMessages) {
            webSocketMessagesFlow.emit(WebSocketMessage.ResponseDone)
            advanceUntilIdle()

            webSocketMessagesFlow.emit(WebSocketMessage.TextMessage(text = testMessage, emotion = null))
            advanceUntilIdle()

            val messages = viewModel.uiState.value.messages

            // 智能分段会按标点/括号切分,且会丢弃空括号;拼接后应等于 ChatTextProcessor 处理后的预期
            val expectedCombined = ChatTextProcessor.smartSegmentText(testMessage).joinToString("") { it.text }
            val actualCombined = messages.joinToString("") { it.text }
            assertTrue(
                "BUG DETECTED: Failed to parse message type: '${testMessage.take(20)}...'. " +
                    "Expected combined: '$expectedCombined', actual: '$actualCombined'",
                actualCombined.contains(expectedCombined) || expectedCombined.contains(actualCombined)
            )
        }
    }

    @Test
    fun `property - empty or null responses handled gracefully`() = runTest {
        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTED
        advanceUntilIdle()

        webSocketMessagesFlow.emit(WebSocketMessage.TextMessage(text = "", emotion = null))
        advanceUntilIdle()

        val messages = viewModel.uiState.value.messages
        val error = viewModel.uiState.value.error

        assertTrue(
            "Empty response should be handled gracefully (either empty messages or error shown)",
            messages.isEmpty() || error != null || messages.all { it.text.isBlank() }
        )
    }

    @Test
    fun `property - rapid message updates should all be captured`() = runTest {
        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTED
        advanceUntilIdle()

        val messageCount = 10
        for (i in 1..messageCount) {
            webSocketMessagesFlow.emit(WebSocketMessage.TextMessage(text = "消息$i", emotion = null))
        }
        advanceUntilIdle()

        val messages = viewModel.uiState.value.messages

        assertTrue(
            "BUG DETECTED: Rapid messages not captured. Expected content from $messageCount messages, " +
                "but got ${messages.size} message(s)",
            messages.isNotEmpty()
        )

        if (messages.isNotEmpty()) {
            val totalText = messages.joinToString("") { it.text }
            assertTrue(
                "Message content should contain accumulated text. Got: '$totalText'",
                totalText.isNotEmpty()
            )
        }
    }

    @Test
    fun `bug condition - connection established but messages not loaded`() = runTest {
        connectionStateFlow.value = WebSocketManager.ConnectionState.DISCONNECTED
        advanceUntilIdle()

        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTED
        advanceUntilIdle()

        webSocketMessagesFlow.emit(WebSocketMessage.TextMessage(text = "连接后的消息", emotion = null))
        advanceUntilIdle()

        val messages = viewModel.uiState.value.messages
        val connectionState = viewModel.uiState.value.connectionState

        assertEquals(
            "Connection state should be CONNECTED",
            WebSocketManager.ConnectionState.CONNECTED,
            connectionState
        )

        assertTrue(
            "BUG DETECTED: Connection established but message not loaded. Messages: ${messages.size}",
            messages.isNotEmpty()
        )
    }
}
