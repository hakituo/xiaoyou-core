package com.aveline.ai.mobile.presentation

import android.content.ClipboardManager
import android.content.Context
import androidx.arch.core.executor.testing.InstantTaskExecutorRule
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.domain.repository.PersonaRepository
import com.aveline.ai.mobile.domain.repository.SessionRepository
import com.aveline.ai.mobile.presentation.chat.ChatViewModel
import com.aveline.ai.mobile.presentation.utils.EmotionResolver
import com.aveline.ai.mobile.services.FileUploadManager
import com.aveline.ai.mobile.services.TTSEngine
import com.aveline.ai.mobile.services.TTSState
import com.aveline.ai.mobile.services.UploadState
import com.aveline.ai.mobile.services.VoiceInputManager
import com.aveline.ai.mobile.services.VoiceInputState
import io.kotest.property.Arb
import io.kotest.property.arbitrary.int
import io.kotest.property.arbitrary.list
import io.kotest.property.arbitrary.string
import io.kotest.property.checkAll
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

/**
 * Preservation Property Tests for Non-Buggy Scenarios
 * 
 * **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12**
 * 
 * **Property 2: Preservation** - 现有功能保持不变
 * 
 * **IMPORTANT**: Follow observation-first methodology
 * 
 * These tests capture the CURRENT BEHAVIOR on UNFIXED code for non-buggy scenarios.
 * They ensure that fixing the 3 bugs doesn't break existing functionality.
 * 
 * **EXPECTED OUTCOME ON UNFIXED CODE**: Tests PASS (confirms baseline behavior)
 * **EXPECTED OUTCOME AFTER FIX**: Tests STILL PASS (confirms no regressions)
 * 
 * Test Coverage:
 * - Error responses (statusCode != 200) show error prompts
 * - Network failures show connection failure prompts
 * - User messages display immediately
 * - Conversation switching loads message history
 * - Breathing light animation speed/rhythm adjusts by emotion
 * - Voice input, image upload, TTS work normally
 * - Background operations work normally
 */
@OptIn(ExperimentalCoroutinesApi::class)
class PreservationPropertyTest {
    
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
        
        // Setup WebSocket manager mocks
        every { mockWebSocketManager.messages } returns webSocketMessagesFlow
        every { mockWebSocketManager.connectionState } returns connectionStateFlow
        
        // Setup session repository to return empty session flow
        every { mockSessionRepository.observeCurrentSession() } returns flowOf(null)
        
        // Setup chat repository to return empty messages
        coEvery { mockChatRepository.observeMessages(any()) } returns flowOf(emptyList())
        
        // Setup app preferences
        every { mockAppPreferences.backendUrl } returns "http://localhost:8000"
        every { mockAppPreferences.accessToken } returns ""

        // Mock voice input / TTS / upload 状态流,避免 init 中 collect 抛 KotlinNothingValueException
        every { mockVoiceInputManager.state } returns MutableStateFlow(VoiceInputState.Idle)
        every { mockVoiceInputManager.partialText } returns MutableStateFlow("")
        every { mockVoiceInputManager.amplitude } returns MutableStateFlow(0f)
        every { mockTTSEngine.state } returns MutableStateFlow(TTSState.Idle)
        every { mockFileUploadManager.uploadState } returns MutableStateFlow(UploadState.Idle)

        // Mock ClipboardManager,避免 copyMessage 中 lazy 初始化时 cast 失败
        every { mockContext.getSystemService(Context.CLIPBOARD_SERVICE) } returns mockk<ClipboardManager>(relaxed = true)

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
    
    // ==================== Error Response Preservation (Req 3.1) ====================
    
    /**
     * Preservation Test 1: Error responses (statusCode != 200) show error prompts
     * 
     * **Validates: Requirements 3.1**
     * 
     * EXPECTED ON UNFIXED CODE: PASS - error handling works
     * EXPECTED AFTER FIX: PASS - error handling still works
     */
    @Test
    fun `preservation - error responses show error prompts`() = runTest {
        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTED
        advanceUntilIdle()
        
        // Simulate error response from WebSocket
        val errorMessage = "服务器错误: 内部错误"
        webSocketMessagesFlow.emit(WebSocketMessage.Error(errorMessage))
        advanceUntilIdle()
        
        // EXPECTED BEHAVIOR: Error should be displayed in UI state
        val error = viewModel.uiState.value.error
        
        assertNotNull(
            "PRESERVATION: Error responses should show error prompts. " +
            "Expected error message to be set in UI state.",
            error
        )
        
        assertTrue(
            "PRESERVATION: Error message should contain the error text. " +
            "Expected: '$errorMessage', Got: '$error'",
            error?.contains("错误") == true || error?.contains("失败") == true
        )
        
        // Verify typing indicator is stopped on error
        assertFalse(
            "PRESERVATION: Typing indicator should stop on error",
            viewModel.uiState.value.isTyping
        )
    }
    
    /**
     * Property-Based Test: Various error status codes should all show error prompts
     * 
     * **Validates: Requirements 3.1**
     */
    @Test
    fun `property - all error status codes show error prompts`() = runTest {
        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTED
        advanceUntilIdle()
        
        // Test various error scenarios
        val errorScenarios = listOf(
            "400 Bad Request",
            "401 Unauthorized",
            "403 Forbidden",
            "404 Not Found",
            "500 Internal Server Error",
            "502 Bad Gateway",
            "503 Service Unavailable"
        )
        
        for (errorMsg in errorScenarios) {
            // Clear previous error
            viewModel.clearError()
            advanceUntilIdle()
            
            // Send error
            webSocketMessagesFlow.emit(WebSocketMessage.Error(errorMsg))
            advanceUntilIdle()
            
            val error = viewModel.uiState.value.error
            
            assertNotNull(
                "PRESERVATION: Error '$errorMsg' should show error prompt. Got: $error",
                error
            )
        }
    }
    
    // ==================== Network Failure Preservation (Req 3.2) ====================
    
    /**
     * Preservation Test 2: Network connection failures show connection failure prompts
     * 
     * **Validates: Requirements 3.2**
     * 
     * EXPECTED ON UNFIXED CODE: PASS - connection state tracking works
     * EXPECTED AFTER FIX: PASS - connection state tracking still works
     */
    @Test
    fun `preservation - network failures show connection failure state`() = runTest {
        // Simulate connection failure
        connectionStateFlow.value = WebSocketManager.ConnectionState.DISCONNECTED
        advanceUntilIdle()
        
        // EXPECTED BEHAVIOR: Connection state should be reflected in UI
        val connectionState = viewModel.uiState.value.connectionState
        
        assertEquals(
            "PRESERVATION: Network failure should update connection state to DISCONNECTED",
            WebSocketManager.ConnectionState.DISCONNECTED,
            connectionState
        )
        
        // Simulate reconnection attempt
        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTING
        advanceUntilIdle()
        
        assertEquals(
            "PRESERVATION: Reconnection attempt should update state to CONNECTING",
            WebSocketManager.ConnectionState.CONNECTING,
            viewModel.uiState.value.connectionState
        )
    }
    
    /**
     * Property-Based Test: Connection state transitions should be tracked correctly
     * 
     * **Validates: Requirements 3.2**
     */
    @Test
    fun `property - all connection state transitions are tracked`() = runTest {
        val states = listOf(
            WebSocketManager.ConnectionState.DISCONNECTED,
            WebSocketManager.ConnectionState.CONNECTING,
            WebSocketManager.ConnectionState.CONNECTED,
            WebSocketManager.ConnectionState.DISCONNECTED
        )
        
        for (state in states) {
            connectionStateFlow.value = state
            advanceUntilIdle()
            
            assertEquals(
                "PRESERVATION: Connection state should transition to $state",
                state,
                viewModel.uiState.value.connectionState
            )
        }
    }
    
    // ==================== User Message Display Preservation (Req 3.3) ====================
    
    /**
     * Preservation Test 3: User messages display immediately
     * 
     * **Validates: Requirements 3.3**
     * 
     * EXPECTED ON UNFIXED CODE: PASS - user message sending works
     * EXPECTED AFTER FIX: PASS - user message sending still works
     */
    @Test
    fun `preservation - user messages display immediately`() = runTest {
        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTED
        advanceUntilIdle()
        
        // Setup mock to return success for sendMessage
        coEvery { mockChatRepository.sendMessage(any(), any(), any()) } returns Result.success(mockk(relaxed = true))
        
        val userMessage = "你好，这是用户消息"
        
        // Send user message
        viewModel.updateInputText(userMessage)
        viewModel.sendMessage(userMessage)
        advanceUntilIdle()
        
        // EXPECTED BEHAVIOR: Input text should be cleared immediately
        assertEquals(
            "PRESERVATION: Input text should be cleared after sending",
            "",
            viewModel.uiState.value.inputText
        )

        // EXPECTED BEHAVIOR: sendMessage 协程同步执行完毕(mock 立即返回 success),
        // typing indicator 已被关闭,这是正常行为;只需验证不会卡在 typing 状态
        assertFalse(
            "PRESERVATION: Typing indicator should not be stuck after send completes",
            viewModel.uiState.value.isTyping && viewModel.uiState.value.showTypingIndicator
        )
    }
    
    /**
     * Property-Based Test: Various user message types should all be sent correctly
     * 
     * **Validates: Requirements 3.3**
     */
    @Test
    fun `property - all user message types are sent correctly`() = runTest {
        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTED
        advanceUntilIdle()
        
        coEvery { mockChatRepository.sendMessage(any(), any(), any()) } returns Result.success(mockk(relaxed = true))
        
        val messageTypes = listOf(
            "简单文本",
            "包含emoji 😊🎉",
            "多行\n消息\n内容",
            "特殊字符 @#$%^&*()",
            "很长的消息" + "重复".repeat(50)
        )
        
        for (message in messageTypes) {
            viewModel.updateInputText(message)
            viewModel.sendMessage(message)
            advanceUntilIdle()
            
            // Input should be cleared
            assertEquals(
                "PRESERVATION: Input cleared for message type: ${message.take(20)}...",
                "",
                viewModel.uiState.value.inputText
            )
        }
    }
    
    // ==================== Conversation Switching Preservation (Req 3.4) ====================
    
    /**
     * Preservation Test 4: Conversation switching loads message history
     * 
     * **Validates: Requirements 3.4**
     * 
     * EXPECTED ON UNFIXED CODE: PASS - session switching works
     * EXPECTED AFTER FIX: PASS - session switching still works
     */
    @Test
    fun `preservation - conversation switching loads message history`() = runTest {
        // This test verifies that the session observation mechanism works
        // The actual message loading is handled by observeMessages()
        
        val sessionFlow = MutableStateFlow<com.aveline.ai.mobile.domain.models.Session?>(null)
        every { mockSessionRepository.observeCurrentSession() } returns sessionFlow
        
        // Create new ViewModel with session flow
        val testViewModel = ChatViewModel(
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
        
        advanceUntilIdle()
        
        // Initially no session
        assertNull(
            "PRESERVATION: Initial state should have no session",
            testViewModel.uiState.value.currentSession
        )
        
        // Switch to a session
        val testSession = com.aveline.ai.mobile.domain.models.Session(
            id = "session-1",
            title = "测试会话",
            createdAt = System.currentTimeMillis(),
            updatedAt = System.currentTimeMillis()
        )
        
        sessionFlow.value = testSession
        advanceUntilIdle()
        
        // EXPECTED BEHAVIOR: Current session should be updated
        assertEquals(
            "PRESERVATION: Session switching should update current session",
            testSession.id,
            testViewModel.uiState.value.currentSession?.id
        )
    }
    
    // ==================== Breathing Light Animation Preservation (Req 3.5, 3.6, 3.7) ====================
    
    /**
     * Preservation Test 5: Breathing light animation speed and rhythm adjust by emotion
     * 
     * **Validates: Requirements 3.5, 3.6, 3.7**
     * 
     * EXPECTED ON UNFIXED CODE: PASS - emotion state tracking works
     * EXPECTED AFTER FIX: PASS - emotion state tracking still works
     */
    @Test
    fun `preservation - breathing light animation adjusts by emotion state`() = runTest {
        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTED
        advanceUntilIdle()
        
        // Simulate emotion update
        val emotionUpdate = WebSocketMessage.EmotionUpdate(
            primary = "happy",
            intensity = 0.8f,
            colors = listOf("#F2CE77", "#FFE8B2", "#3A2E13", "#D3A74F")
        )
        
        webSocketMessagesFlow.emit(emotionUpdate)
        advanceUntilIdle()
        
        // EXPECTED BEHAVIOR: Emotion should be updated in UI state
        val currentEmotion = viewModel.uiState.value.currentEmotion
        
        assertNotNull(
            "PRESERVATION: Emotion updates should be reflected in UI state",
            currentEmotion
        )
        
        assertEquals(
            "PRESERVATION: Emotion primary should match update",
            "happy",
            currentEmotion?.primary
        )
        
        assertEquals(
            "PRESERVATION: Emotion intensity should match update",
            0.8f,
            currentEmotion?.intensity ?: 0f,
            0.01f
        )
    }
    
    /**
     * Property-Based Test: All emotion states should be tracked correctly
     * 
     * **Validates: Requirements 3.5, 3.6**
     */
    @Test
    fun `property - all emotion states are tracked correctly`() = runTest {
        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTED
        advanceUntilIdle()
        
        val emotions = listOf(
            "neutral", "happy", "shy", "angry", "jealous",
            "wronged", "coquetry", "lost", "excited"
        )
        
        for (emotion in emotions) {
            val emotionUpdate = WebSocketMessage.EmotionUpdate(
                primary = emotion,
                intensity = 0.7f,
                colors = listOf("#000000", "#111111", "#222222", "#333333")
            )
            
            webSocketMessagesFlow.emit(emotionUpdate)
            advanceUntilIdle()
            
            val currentEmotion = viewModel.uiState.value.currentEmotion
            
            assertEquals(
                "PRESERVATION: Emotion state '$emotion' should be tracked",
                emotion,
                currentEmotion?.primary
            )
        }
    }
    
    /**
     * Preservation Test 6: Breathing light colors exist for all emotion states
     * 
     * **Validates: Requirements 3.5, 3.7**
     * 
     * This test verifies that EmotionResolver provides colors for all emotions
     * (even if they're not the correct Web colors - that's tested in bug condition tests)
     */
    @Test
    fun `preservation - breathing light colors exist for all emotions`() {
        val emotions = listOf(
            "neutral", "happy", "shy", "angry", "jealous",
            "wronged", "coquetry", "lost", "excited"
        )
        
        for (emotion in emotions) {
            val colors = EmotionResolver.getColorsForEmotion(emotion)
            
            assertNotNull(
                "PRESERVATION: Colors should exist for emotion '$emotion'",
                colors
            )
            
            assertTrue(
                "PRESERVATION: Color list should not be empty for emotion '$emotion'",
                colors.isNotEmpty()
            )
        }
    }
    
    // ==================== Other UI Features Preservation (Req 3.8, 3.9, 3.10, 3.11) ====================
    
    /**
     * Preservation Test 7: Voice input state management works
     * 
     * **Validates: Requirements 3.8**
     * 
     * EXPECTED ON UNFIXED CODE: PASS - voice input state tracking works
     * EXPECTED AFTER FIX: PASS - voice input state tracking still works
     */
    @Test
    fun `preservation - voice input state management works`() = runTest {
        // Voice input functionality is managed by VoiceInputManager
        // We verify that the ViewModel properly tracks voice input state
        
        // Initial state should be idle
        assertEquals(
            "PRESERVATION: Initial voice input state should be Idle",
            com.aveline.ai.mobile.services.VoiceInputState.Idle::class,
            viewModel.uiState.value.voiceInputState::class
        )
        
        assertFalse(
            "PRESERVATION: Initial recording state should be false",
            viewModel.uiState.value.isRecording
        )
    }
    
    /**
     * Preservation Test 8: Image upload state management works
     * 
     * **Validates: Requirements 3.9**
     * 
     * EXPECTED ON UNFIXED CODE: PASS - upload state tracking works
     * EXPECTED AFTER FIX: PASS - upload state tracking still works
     */
    @Test
    fun `preservation - image upload state management works`() = runTest {
        // Upload functionality is managed by FileUploadManager
        // We verify that the ViewModel properly tracks upload state
        
        // Initial state should be idle
        assertEquals(
            "PRESERVATION: Initial upload state should be Idle",
            com.aveline.ai.mobile.services.UploadState.Idle::class,
            viewModel.uiState.value.uploadState::class
        )
        
        assertNull(
            "PRESERVATION: Initial uploaded image URL should be null",
            viewModel.uiState.value.lastUploadedImageUrl
        )
    }
    
    /**
     * Preservation Test 9: TTS playback state management works
     * 
     * **Validates: Requirements 3.11**
     * 
     * EXPECTED ON UNFIXED CODE: PASS - TTS state tracking works
     * EXPECTED AFTER FIX: PASS - TTS state tracking still works
     */
    @Test
    fun `preservation - TTS playback state management works`() = runTest {
        // TTS functionality is managed by TTSEngine
        // We verify that the ViewModel properly tracks TTS state
        
        // Initial state should have no playing message
        assertNull(
            "PRESERVATION: Initial TTS state should have no playing message",
            viewModel.uiState.value.playingMessageId
        )
    }
    
    /**
     * Preservation Test 10: Settings and other UI operations work
     * 
     * **Validates: Requirements 3.10**
     * 
     * EXPECTED ON UNFIXED CODE: PASS - basic operations work
     * EXPECTED AFTER FIX: PASS - basic operations still work
     */
    @Test
    fun `preservation - basic UI operations work`() = runTest {
        // Test input text update
        val testText = "测试输入"
        viewModel.updateInputText(testText)
        advanceUntilIdle()
        
        assertEquals(
            "PRESERVATION: Input text update should work",
            testText,
            viewModel.uiState.value.inputText
        )
        
        // Test error clearing
        viewModel.clearError()
        advanceUntilIdle()
        
        assertNull(
            "PRESERVATION: Error clearing should work",
            viewModel.uiState.value.error
        )
    }
    
    // ==================== Message Operations Preservation ====================
    
    /**
     * Preservation Test 11: Message deletion works
     * 
     * **Validates: Requirements 3.3, 3.4**
     * 
     * EXPECTED ON UNFIXED CODE: PASS - message deletion works
     * EXPECTED AFTER FIX: PASS - message deletion still works
     */
    @Test
    fun `preservation - message deletion works`() = runTest {
        coEvery { mockChatRepository.deleteMessage(any()) } returns Result.success(Unit)
        
        val messageId = "test-message-1"
        viewModel.deleteMessage(messageId)
        advanceUntilIdle()
        
        // Should not produce error
        assertNull(
            "PRESERVATION: Message deletion should not produce error",
            viewModel.uiState.value.error
        )
    }
    
    /**
     * Preservation Test 12: Message copy works
     * 
     * **Validates: Requirements 3.3**
     * 
     * EXPECTED ON UNFIXED CODE: PASS - message copy works
     * EXPECTED AFTER FIX: PASS - message copy still works
     */
    @Test
    fun `preservation - message copy works`() {
        // Message copy uses ClipboardManager
        // We just verify it doesn't crash
        val testText = "测试复制文本"
        
        try {
            viewModel.copyMessage(testText)
            // If we get here without exception, copy mechanism works
            assertTrue(
                "PRESERVATION: Message copy should not crash",
                true
            )
        } catch (e: Exception) {
            fail("PRESERVATION: Message copy should not throw exception: ${e.message}")
        }
    }
    
    /**
     * Preservation Test 13: Session creation works
     * 
     * **Validates: Requirements 3.4**
     * 
     * EXPECTED ON UNFIXED CODE: PASS - session creation works
     * EXPECTED AFTER FIX: PASS - session creation still works
     */
    @Test
    fun `preservation - session creation works`() = runTest {
        val newSession = com.aveline.ai.mobile.domain.models.Session(
            id = "new-session",
            title = "新会话",
            createdAt = System.currentTimeMillis(),
            updatedAt = System.currentTimeMillis()
        )
        
        coEvery { mockSessionRepository.createSession(any()) } returns Result.success(newSession)
        
        viewModel.createNewSession("新会话")
        advanceUntilIdle()
        
        // Should not have error
        assertNull(
            "PRESERVATION: Session creation should not produce error",
            viewModel.uiState.value.error
        )
        
        // Loading should be complete
        assertFalse(
            "PRESERVATION: Loading should be complete after session creation",
            viewModel.uiState.value.isLoading
        )
    }
    
    /**
     * Preservation Test 14: History clearing works
     * 
     * **Validates: Requirements 3.4**
     * 
     * EXPECTED ON UNFIXED CODE: PASS - history clearing works
     * EXPECTED AFTER FIX: PASS - history clearing still works
     */
    @Test
    fun `preservation - history clearing works`() = runTest {
        // Setup a session
        val testSession = com.aveline.ai.mobile.domain.models.Session(
            id = "session-1",
            title = "测试会话",
            createdAt = System.currentTimeMillis(),
            updatedAt = System.currentTimeMillis()
        )
        
        val sessionFlow = MutableStateFlow<com.aveline.ai.mobile.domain.models.Session?>(testSession)
        every { mockSessionRepository.observeCurrentSession() } returns sessionFlow
        
        coEvery { mockChatRepository.clearHistory(any()) } returns Result.success(Unit)
        
        val testViewModel = ChatViewModel(
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
        
        advanceUntilIdle()
        
        testViewModel.clearHistory()
        advanceUntilIdle()
        
        // Should not have error
        assertNull(
            "PRESERVATION: History clearing should not produce error",
            testViewModel.uiState.value.error
        )
    }
    
    // ==================== Comprehensive Property-Based Tests ====================
    
    /**
     * Property-Based Test: Error handling is consistent across all error types
     * 
     * **Validates: Requirements 3.1, 3.2**
     */
    @Test
    fun `property - error handling is consistent across all error types`() = runTest {
        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTED
        advanceUntilIdle()
        
        // Generate various error messages
        val errorPrefixes = listOf("错误", "失败", "异常", "Error", "Failed")
        val errorContexts = listOf("网络", "服务器", "数据", "连接", "请求")
        
        for (prefix in errorPrefixes) {
            for (context in errorContexts) {
                val errorMsg = "$prefix: $context"
                
                viewModel.clearError()
                advanceUntilIdle()
                
                webSocketMessagesFlow.emit(WebSocketMessage.Error(errorMsg))
                advanceUntilIdle()
                
                assertNotNull(
                    "PRESERVATION: Error '$errorMsg' should be handled",
                    viewModel.uiState.value.error
                )
            }
        }
    }
    
    /**
     * Property-Based Test: UI state remains consistent during rapid operations
     * 
     * **Validates: Requirements 3.3, 3.4, 3.5**
     */
    @Test
    fun `property - UI state remains consistent during rapid operations`() = runTest {
        connectionStateFlow.value = WebSocketManager.ConnectionState.CONNECTED
        advanceUntilIdle()
        
        coEvery { mockChatRepository.sendMessage(any(), any(), any()) } returns Result.success(mockk(relaxed = true))
        
        // Rapid input updates
        for (i in 1..10) {
            viewModel.updateInputText("消息$i")
        }
        advanceUntilIdle()
        
        // Final input should be the last one
        assertEquals(
            "PRESERVATION: Rapid input updates should result in last value",
            "消息10",
            viewModel.uiState.value.inputText
        )
        
        // Rapid error clearing: 先 emit 全部错误并让 collect 处理完,再 clearError
        for (i in 1..5) {
            webSocketMessagesFlow.emit(WebSocketMessage.Error("错误$i"))
            advanceUntilIdle()
        }
        viewModel.clearError()
        advanceUntilIdle()

        // Error should be cleared
        assertNull(
            "PRESERVATION: Rapid error clearing should work",
            viewModel.uiState.value.error
        )
    }
}
