import asyncio
import time
import logging
import sys
import os

# Ensure project root is in path
sys.path.append(os.getcwd())

from core.agents.chat_agent import ChatAgent, AgentConfig

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_timing():
    print("\n[Test] Initializing ChatAgent...")
    config = AgentConfig(
        agent_name="timing_test_agent",
        temperature=0.7
    )
    agent = ChatAgent(config=config)
    await agent.initialize()
    print("[Test] Agent initialized.")

    user_id = "test_user_timing"
    message = "你好，请用一句话证明你还活着。"
    print(f"\n[Test] Sending message: {message}")

    t_start = time.time()
    t_first_token = None
    token_count = 0
    
    print("[Test] Starting stream_chat...")
    try:
        async for chunk in agent.stream_chat(user_id=user_id, message=message):
            now = time.time()
            if t_first_token is None:
                t_first_token = now
                latency = t_first_token - t_start
                print(f"\n[Test] First token received after {latency:.4f}s")
            
            if isinstance(chunk, dict):
                if chunk.get("type") == "token":
                    content = chunk.get("data", "")
                    print(content, end="", flush=True)
                    token_count += 1
                elif chunk.get("error"):
                    print(f"\n[Test] Error in chunk: {chunk['error']}")
            else:
                print(chunk, end="", flush=True)
                token_count += 1
                
        t_end = time.time()
        print(f"\n\n[Test] Stream finished.")
        print(f"[Test] Total duration: {t_end - t_start:.4f}s")
        print(f"[Test] First token latency: {t_first_token - t_start:.4f}s" if t_first_token else "[Test] No tokens received.")
        print(f"[Test] Token count: {token_count}")
        
    except Exception as e:
        print(f"\n[Test] Exception during chat: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_timing())
