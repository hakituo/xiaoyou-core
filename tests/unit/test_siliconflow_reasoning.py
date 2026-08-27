import sys
import os
import asyncio
from unittest.mock import MagicMock, AsyncMock
import pytest

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.llm.siliconflow_client import SiliconFlowClient

@pytest.mark.asyncio
async def test_siliconflow_reasoning_content():
    print("Testing SiliconFlow reasoning_content support...")
    
    # Mock response content iterator
    chunks = [
        b'data: {"choices": [{"delta": {"reasoning_content": "Deep"}}]}\n\n',
        b'data: {"choices": [{"delta": {"reasoning_content": "Seek"}}]}\n\n',
        b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n',
        b'data: [DONE]\n\n'
    ]
    
    async def iter_content():
        for chunk in chunks:
            yield chunk
            
    mock_response = AsyncMock()
    mock_response.status = 200
    # Assign the async generator directly to content so it can be iterated
    mock_response.content = iter_content()
    
    # Fix mock_session.post
    mock_session = MagicMock() 
    mock_post_ctx = AsyncMock()
    mock_post_ctx.__aenter__.return_value = mock_response
    mock_post_ctx.__aexit__.return_value = None
    mock_session.post.return_value = mock_post_ctx
    
    client = SiliconFlowClient(api_key="fake")
    client._get_session = AsyncMock(return_value=mock_session)
    client.initialized = True
    
    collected_content = []
    print("Starting stream_chat...")
    async for chunk in client.stream_chat([{"role": "user", "content": "hi"}]):
        print(f"Received chunk: {chunk}")
        if "content" in chunk:
            collected_content.append(chunk["content"])
            
    full_text = "".join(collected_content)
    print(f"Full collected text: {full_text}")
    
    # Verification
    assert "> **Thinking Process:**" in full_text
    assert "Deep" in full_text
    assert "Seek" in full_text
    assert "\n\n---\n\n" in full_text
    assert "Hello" in full_text
    
    print("Test Passed: SiliconFlow reasoning content is correctly formatted and merged.")

if __name__ == "__main__":
    asyncio.run(test_siliconflow_reasoning_content())
