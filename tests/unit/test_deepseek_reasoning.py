import sys
import os
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.llm.openai_compat import OpenAIClient

@pytest.mark.asyncio
async def test_deepseek_reasoning_content():
    print("Testing DeepSeek reasoning_content support...")
    
    # Mock response content iterator
    # DeepSeek typically sends multiple chunks
    chunks = [
        b'data: {"choices": [{"delta": {"reasoning_content": "Thinking..."}}]}\n\n',
        b'data: {"choices": [{"delta": {"reasoning_content": " Still thinking."}}]}\n\n',
        b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n',
        b'data: [DONE]\n\n'
    ]
    
    async def iter_content():
        for chunk in chunks:
            yield chunk
            
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.content.iter_any = MagicMock(return_value=iter_content())
    
    # Fix mock_session.post to support async context manager
    # aiohttp session.post is NOT a coroutine itself, but returns an async context manager
    mock_session = MagicMock() 
    mock_post_ctx = AsyncMock()
    mock_post_ctx.__aenter__.return_value = mock_response
    mock_post_ctx.__aexit__.return_value = None
    mock_session.post.return_value = mock_post_ctx
    
    client = OpenAIClient(api_key="fake", base_url="http://fake")
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
    assert "> **Thinking Process:**" in full_text, "Should contain reasoning header"
    assert "Thinking..." in full_text, "Should capture first reasoning chunk"
    assert "Still thinking." in full_text, "Should capture second reasoning chunk"
    assert "\n\n---\n\n" in full_text, "Should contain separator"
    assert "Hello" in full_text, "Should capture content chunk"
    
    print("Test Passed: Reasoning content is correctly formatted and merged into output.")

if __name__ == "__main__":
    asyncio.run(test_deepseek_reasoning_content())
