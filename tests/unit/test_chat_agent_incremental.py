import sys
import os
import asyncio
import logging
import time
from unittest.mock import MagicMock, AsyncMock
import pytest


pytestmark = [pytest.mark.integration, pytest.mark.slow]


if os.getenv("XIAOYOU_RUN_INTEGRATION_TESTS") != "1":
    pytest.skip(
        "需要设置 XIAOYOU_RUN_INTEGRATION_TESTS=1 才运行集成测试",
        allow_module_level=True,
    )


# Add current directory to path
sys.path.append(os.getcwd())

from core.agents.chat_agent import ChatAgent, AgentConfig
from core.llm import get_llm_module, LLMConfig, create_instance

# Configure logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s] %(message)s')
logger = logging.getLogger("TEST_INCREMENTAL")

async def test_scenario_1_pure_llm():
    print("\n" + "="*50)
    print("SCENARIO 1: Pure LLM (No Memory, No Emotion, No Tools)")
    print("="*50)
    
    # Initialize Agent
    config = AgentConfig(agent_name="test_agent_pure")
    agent = ChatAgent(config)
    
    # 1. Disable extraneous initializations in __init__ (too late for that, but we can mock them before initialize())
    # Actually, ChatAgent.__init__ creates empty registries.
    # The heavy lifting is in initialize().
    
    # Mock methods to disable features
    agent._build_conversation_history = AsyncMock(side_effect=lambda uid, msg, hint: [{"role": "user", "content": msg}])
    agent._save_conversation_history = AsyncMock()
    agent._check_daily_routine = AsyncMock(return_value=None)
    agent.emotion_manager = MagicMock()
    agent.emotion_manager.process_text = MagicMock(return_value=None)
    
    # Mock Aveline triggers (imported in streaming.py, but we can't easily mock module-level imports here without patching)
    # However, stream_chat_impl calls them. We can patch `core.agents.chat_agent_components.streaming` functions if needed.
    # Or, simpler: we let them run. They are usually fast regex checks.
    # The main blockers are Memory (DB access) and Emotion (Model access).
    
    # Initialize only LLM
    print("Initializing LLM only...")
    agent.llm_module = get_llm_module()
    await agent.llm_module.initialize()
    
    # Ensure LLM instance exists
    llm_status = agent.llm_module.get_status()
    if llm_status.get("llm_status", {}).get("instances_count", 0) == 0:
        print("Creating default LLM instance...")
        llm_config = LLMConfig(
            model_name="default",
            device="auto",
            max_context_length=4096,
            temperature=0.7
        )
        create_instance("default_llm", llm_config)
    
    agent.is_initialized = True # Skip full initialize()
    
    # Run Stream Chat
    print("Running stream_chat...")
    start_time = time.time()
    first_token_time = None
    response_text = ""
    
    try:
        async for chunk in agent.stream_chat(user_id="test_user_pure", message="Hello, who are you?"):
            if "error" in chunk:
                print(f"Error received: {chunk['error']}")
            if chunk.get("type") == "token":
                content = chunk.get("content", "")
                if not first_token_time:
                    first_token_time = time.time()
                    print(f"First token received in {first_token_time - start_time:.4f}s")
                print(content, end="", flush=True)
                response_text += content
    except Exception as e:
        print(f"\nException: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n\nTotal time: {time.time() - start_time:.4f}s")
    return agent

async def test_scenario_2_add_memory(agent):
    print("\n" + "="*50)
    print("SCENARIO 2: Adding Memory")
    print("="*50)
    
    # Restore _build_conversation_history
    # We need to import the real function and bind it, or just call the real logic.
    # Since we can't easily un-mock to the original method on the instance, we'll create a new agent or reload.
    # But to save time/resources, let's just create a new agent and reuse the LLM module (it's a singleton anyway).
    
    config = AgentConfig(agent_name="test_agent_memory")
    agent_mem = ChatAgent(config)
    agent_mem.llm_module = agent.llm_module # Reuse initialized LLM
    agent_mem.is_initialized = True
    
    # Mock Emotion only
    agent_mem.emotion_manager = MagicMock()
    agent_mem.emotion_manager.process_text = MagicMock(return_value=None)
    
    # Allow Memory (default behavior of ChatAgent is to use WeightedMemoryManager)
    # But we need to make sure VectorSearch doesn't block or fail if not set up.
    # ChatAgent.__init__ tries to init VectorSearch. If it fails, it logs warning.
    
    print("Running stream_chat with Memory...")
    start_time = time.time()
    first_token_time = None
    
    try:
        # First message
        print("\n[Turn 1] User: My name is TestUser.")
        async for chunk in agent_mem.stream_chat(user_id="test_user_mem", message="My name is TestUser."):
            if chunk.get("type") == "token":
                if not first_token_time:
                    first_token_time = time.time()
                    print(f"First token: {first_token_time - start_time:.4f}s")
                print(chunk.get("content", ""), end="", flush=True)
        
        # Second message (test recall)
        print("\n\n[Turn 2] User: What is my name?")
        start_time = time.time()
        first_token_time = None
        async for chunk in agent_mem.stream_chat(user_id="test_user_mem", message="What is my name?"):
             if chunk.get("type") == "token":
                if not first_token_time:
                    first_token_time = time.time()
                    print(f"First token: {first_token_time - start_time:.4f}s")
                print(chunk.get("content", ""), end="", flush=True)

    except Exception as e:
        print(f"\nException: {e}")
        import traceback
        traceback.print_exc()

async def test_scenario_3_add_emotion(agent):
    print("\n" + "="*50)
    print("SCENARIO 3: Adding Emotion")
    print("="*50)
    
    # Create new agent with memory + emotion
    config = AgentConfig(agent_name="test_agent_emotion")
    agent_emo = ChatAgent(config)
    agent_emo.llm_module = agent.llm_module # Reuse initialized LLM
    agent_emo.is_initialized = True
    
    # We need to initialize EmotionManager properly.
    # ChatAgent.__init__ calls get_emotion_manager(), which might return a lazy proxy or the real thing.
    # But initialize() usually ensures models are loaded.
    # ChatAgent.initialize() does:
    # try:
    #    # ... initialization of emotion responder ...
    # except ...
    
    # But stream_chat_impl calls:
    # emo_state = agent.emotion_manager.process_text(user_id, current_response_content)
    
    # So we need to make sure agent_emo.emotion_manager is the real deal.
    from core.emotion import get_emotion_manager
    agent_emo.emotion_manager = get_emotion_manager()
    
    # Initialize Emotion Manager (if it has an initialize method)
    if hasattr(agent_emo.emotion_manager, "initialize"):
        print("Initializing EmotionManager...")
        t0 = time.time()
        await agent_emo.emotion_manager.initialize()
        print(f"EmotionManager initialized in {time.time() - t0:.4f}s")
        
    print("Running stream_chat with Memory + Emotion...")
    start_time = time.time()
    first_token_time = None
    
    try:
        # We need a message that might trigger emotion
        msg = "I am feeling very happy today! I love you."
        print(f"\n[Turn 1] User: {msg}")
        
        async for chunk in agent_emo.stream_chat(user_id="test_user_emo", message=msg):
            if chunk.get("type") == "token":
                if not first_token_time:
                    first_token_time = time.time()
                    print(f"First token: {first_token_time - start_time:.4f}s")
                print(chunk.get("content", ""), end="", flush=True)
            elif chunk.get("type") == "emotion_update":
                print(f"\n[Emotion Update] {chunk.get('data')}")

    except Exception as e:
        print(f"\nException: {e}")
        import traceback
        traceback.print_exc()

async def main():
    agent = await test_scenario_1_pure_llm()
    await test_scenario_2_add_memory(agent)
    await test_scenario_3_add_emotion(agent)

if __name__ == "__main__":
    asyncio.run(main())
