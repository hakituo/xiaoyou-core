import sys
import os
import asyncio
import time
import logging
import pytest


pytestmark = [pytest.mark.integration, pytest.mark.slow]


# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TestLLMModule")

if os.getenv("XIAOYOU_RUN_INTEGRATION_TESTS") != "1":
    pytest.skip("需要设置 XIAOYOU_RUN_INTEGRATION_TESTS=1 才运行集成测试", allow_module_level=True)

async def test_module():
    sys.path.append(os.getcwd())
    from core.modules.llm.module import LLMModule
    from config.integrated_config import get_settings
    print("Initializing LLMModule...")
    
    # Mock settings if needed, or rely on app.yaml
    settings = get_settings()
    print(f"Model path from settings: {settings.model.text_path}")
    
    # Initialize module
    llm_module = LLMModule()
    
    print("Loading model...")
    start_load = time.time()
    success = await llm_module._load_model()
    print(f"Model load result: {success}, took {time.time() - start_load:.2f}s")
    
    if not success:
        print("Failed to load model")
        return

    print("\nStarting stream_chat test...")
    prompt = "你好"
    
    start_gen = time.time()
    first_token_received = False
    
    try:
        # Use a short timeout to test our change
        async for chunk in llm_module.stream_chat(prompt, first_token_timeout=15.0):
            if not first_token_received:
                print(f"\n[First token received in {time.time() - start_gen:.2f} seconds]")
                first_token_received = True
            
            if "content" in chunk:
                print(chunk["content"], end="", flush=True)
            elif "error" in chunk:
                print(f"\nError received: {chunk['error']}")
            
        print(f"\n\nTotal generation time: {time.time() - start_gen:.2f} seconds")
        
    except Exception as e:
        print(f"\nException during stream_chat: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_module())
