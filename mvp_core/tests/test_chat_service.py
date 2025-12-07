import pytest
from unittest.mock import AsyncMock, MagicMock
from mvp_core.domain.services.chat_service import ChatService
from mvp_core.domain.entities.character import CharacterProfile
from mvp_core.domain.interfaces.base_interfaces import LLMInterface, MemoryInterface
from mvp_core.shared.di import container

@pytest.mark.asyncio
async def test_chat_service_process_message():
    # Setup Mocks
    mock_llm = MagicMock(spec=LLMInterface)
    mock_llm.stream_generate = AsyncMock(return_value=iter(["Hello", " ", "World"]))
    # Fix: AsyncGenerator mock is tricky, simpler to return a list for iteration if not strictly checking async gen
    # But process_message expects async generator.
    
    async def async_gen(text, **kwargs):
        yield "Hello"
        yield " "
        yield "World"
    mock_llm.stream_generate = async_gen

    mock_memory = MagicMock(spec=MemoryInterface)
    mock_memory.add_message = AsyncMock()
    mock_memory.get_history = AsyncMock(return_value=[])

    # Register Mocks
    container.register(LLMInterface, mock_llm)
    container.register(MemoryInterface, mock_memory)

    # Setup Character
    character = CharacterProfile(
        name="TestBot",
        system_prompt="You are a test bot."
    )

    # Init Service
    service = ChatService(character)

    # Execute
    responses = []
    async for chunk in service.process_message("Hi"):
        responses.append(chunk)

    # Verify
    # 1. Check Sensory Trigger (None)
    assert not any(r["type"] == "sensory_trigger" for r in responses)
    
    # 2. Check LLM Token Stream
    tokens = [r["data"] for r in responses if r["type"] == "token"]
    assert "".join(tokens) == "Hello World"

    # 3. Check Memory Calls
    mock_memory.add_message.assert_any_call("user", "Hi")
    mock_memory.add_message.assert_any_call("ai", "Hello World")
