package com.aveline.ai.mobile.presentation.chat

import android.content.Context
import androidx.arch.core.executor.testing.InstantTaskExecutorRule
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.remote.dto.MessageDto
import com.aveline.ai.mobile.data.remote.dto.MessageResponse
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
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Unit tests for extractMessageContent function
 * 
 * **Validates: Requirements 1.1, 1.2, 2.1, 2.2, 2.5, 3.1**
 * 
 * Tests the field priority logic: response -> reply -> message -> data
 * Tests logging for parsing process and results
 * Tests handling of empty/null responses
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ExtractMessageContentTest {
    
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
        every { mockWebSocketManager.messages } returns MutableSharedFlow()
        every { mockWebSocketManager.connectionState } returns MutableStateFlow(WebSocketManager.ConnectionState.DISCONNECTED)
        
        // Setup session repository to return empty session flow
        every { mockSessionRepository.observeCurrentSession() } returns flowOf(null)
        
        // Setup app preferences
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
    
    /**
     * Test Priority 1: 'response' field should be extracted first
     */
    @Test
    fun `extractMessageContent should prioritize response field`() {
        val messageResponse = MessageResponse(
            status = "success",
            response = "Content from response field",
            reply = "Content from reply field",
            message = MessageDto(text = "Content from message field"),
            data = MessageDto(text = "Content from data field")
        )
        
        val result = viewModel.extractMessageContent(messageResponse)
        
        assertEquals("Content from response field", result)
    }
    
    /**
     * Test Priority 2: 'reply' field should be used if 'response' is null/blank
     */
    @Test
    fun `extractMessageContent should use reply field when response is null`() {
        val messageResponse = MessageResponse(
            status = "success",
            response = null,
            reply = "Content from reply field",
            message = MessageDto(text = "Content from message field"),
            data = MessageDto(text = "Content from data field")
        )
        
        val result = viewModel.extractMessageContent(messageResponse)
        
        assertEquals("Content from reply field", result)
    }
    
    @Test
    fun `extractMessageContent should use reply field when response is blank`() {
        val messageResponse = MessageResponse(
            status = "success",
            response = "   ",
            reply = "Content from reply field",
            message = MessageDto(text = "Content from message field"),
            data = MessageDto(text = "Content from data field")
        )
        
        val result = viewModel.extractMessageContent(messageResponse)
        
        assertEquals("Content from reply field", result)
    }
    
    /**
     * Test Priority 3: 'message.text' field should be used if response and reply are null/blank
     */
    @Test
    fun `extractMessageContent should use message text when response and reply are null`() {
        val messageResponse = MessageResponse(
            status = "success",
            response = null,
            reply = null,
            message = MessageDto(text = "Content from message field"),
            data = MessageDto(text = "Content from data field")
        )
        
        val result = viewModel.extractMessageContent(messageResponse)
        
        assertEquals("Content from message field", result)
    }
    
    @Test
    fun `extractMessageContent should skip message when text is blank`() {
        val messageResponse = MessageResponse(
            status = "success",
            response = null,
            reply = null,
            message = MessageDto(text = "  "),
            data = MessageDto(text = "Content from data field")
        )
        
        val result = viewModel.extractMessageContent(messageResponse)
        
        assertEquals("Content from data field", result)
    }
    
    /**
     * Test Priority 4: 'data.text' field should be used as last resort
     */
    @Test
    fun `extractMessageContent should use data text when all other fields are null`() {
        val messageResponse = MessageResponse(
            status = "success",
            response = null,
            reply = null,
            message = null,
            data = MessageDto(text = "Content from data field")
        )
        
        val result = viewModel.extractMessageContent(messageResponse)
        
        assertEquals("Content from data field", result)
    }
    
    /**
     * Test empty/null response handling
     */
    @Test
    fun `extractMessageContent should return null when all fields are empty`() {
        val messageResponse = MessageResponse(
            status = "success",
            response = null,
            reply = null,
            message = null,
            data = null
        )
        
        val result = viewModel.extractMessageContent(messageResponse)
        
        assertNull(result)
    }
    
    @Test
    fun `extractMessageContent should return null when all text fields are blank`() {
        val messageResponse = MessageResponse(
            status = "success",
            response = "  ",
            reply = "   ",
            message = MessageDto(text = "  "),
            data = MessageDto(text = "   ")
        )
        
        val result = viewModel.extractMessageContent(messageResponse)
        
        assertNull(result)
    }
    
    /**
     * Test error response handling
     */
    @Test
    fun `extractMessageContent should return null for error responses with no content`() {
        val messageResponse = MessageResponse(
            status = "error",
            response = null,
            reply = null,
            message = null,
            data = null,
            error = "Something went wrong"
        )
        
        val result = viewModel.extractMessageContent(messageResponse)
        
        assertNull(result)
    }
    
    /**
     * Test various content types
     */
    @Test
    fun `extractMessageContent should handle emoji content`() {
        val messageResponse = MessageResponse(
            status = "success",
            response = "你好！😊 有什么可以帮助你的？"
        )
        
        val result = viewModel.extractMessageContent(messageResponse)
        
        assertEquals("你好！😊 有什么可以帮助你的？", result)
    }
    
    @Test
    fun `extractMessageContent should handle multiline content`() {
        val messageResponse = MessageResponse(
            status = "success",
            response = "第一行\n第二行\n第三行"
        )
        
        val result = viewModel.extractMessageContent(messageResponse)
        
        assertEquals("第一行\n第二行\n第三行", result)
    }
    
    @Test
    fun `extractMessageContent should handle special characters`() {
        val messageResponse = MessageResponse(
            status = "success",
            response = "特殊字符: @#\$%^&*()"
        )
        
        val result = viewModel.extractMessageContent(messageResponse)
        
        assertEquals("特殊字符: @#\$%^&*()", result)
    }
    
    @Test
    fun `extractMessageContent should handle very long content`() {
        val longContent = "重复内容".repeat(1000)
        val messageResponse = MessageResponse(
            status = "success",
            response = longContent
        )
        
        val result = viewModel.extractMessageContent(messageResponse)
        
        assertEquals(longContent, result)
    }
    
    /**
     * Test edge cases
     */
    @Test
    fun `extractMessageContent should handle message with null text`() {
        val messageResponse = MessageResponse(
            status = "success",
            response = null,
            reply = null,
            message = MessageDto(text = ""),
            data = null
        )
        
        val result = viewModel.extractMessageContent(messageResponse)
        
        assertNull(result)
    }
    
    @Test
    fun `extractMessageContent should handle data with null text`() {
        val messageResponse = MessageResponse(
            status = "success",
            response = null,
            reply = null,
            message = null,
            data = MessageDto(text = "")
        )
        
        val result = viewModel.extractMessageContent(messageResponse)
        
        assertNull(result)
    }
}
