import asyncio
import os
import sys
import logging
import pytest


pytestmark = pytest.mark.integration


if os.getenv("XIAOYOU_RUN_INTEGRATION_TESTS") != "1":
    pytest.skip(
        "需要设置 XIAOYOU_RUN_INTEGRATION_TESTS=1 才运行集成测试",
        allow_module_level=True,
    )

# Add current directory to path
sys.path.append(os.getcwd())

from core.agents.chat_agent import ChatAgent, AgentConfig
from core.utils.logger import get_logger

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = get_logger("TEST_CHAT_AGENT")

async def test_agent():
    print("Initializing ChatAgent...")
    
    # Use default config
    config = AgentConfig(
        agent_name="test_agent",
        temperature=0.7
    )
    
    try:
        agent = ChatAgent(config=config)
        await agent.initialize()
        print("ChatAgent initialized.")
        
        user_id = "test_user"
        message = "Hello, who are you?"
        print(f"User: {message}")
        
        print("Starting stream_chat...")
        start_time = asyncio.get_event_loop().time()
        
        # Determine mode to ensure system prompt is set
        agent._determine_mode(message)
        
        async for chunk in agent.stream_chat(user_id=user_id, message=message):
            if isinstance(chunk, dict):
                if chunk.get("type") == "token":
                    print(chunk["data"], end="", flush=True)
                elif chunk.get("error"):
                    print(f"\nError: {chunk['error']}")
            else:
                print(chunk, end="", flush=True)
                
        print(f"\n\nGeneration finished in {asyncio.get_event_loop().time() - start_time:.2f} seconds.")
        
    except Exception as e:
        print(f"\nException occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_agent())
