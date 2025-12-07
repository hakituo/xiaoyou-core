import asyncio
import sys
import os

# Ensure project root is in path
sys.path.append(os.getcwd())

from core.llm_connector import query_model
from memory.memory_manager import MemoryManager
import logging

# Configure logging to see what's happening
logging.basicConfig(level=logging.INFO)

async def test_integration():
    print("Testing Main Program Integration...")
    
    # 1. Initialize Memory
    memory = MemoryManager(user_id="test_user")
    
    # 2. Test Image Generation Query
    query = "帮我画一张猫的图片"
    print(f"Query: {query}")
    
    response = await query_model(query, memory)
    
    print(f"Response: {response}")
    
    if "已为您生成图片" in response and "文件保存于" in response:
        print("SUCCESS: Image generation triggered and completed via main program logic!")
    else:
        print("FAILURE: Image generation did not complete as expected.")

if __name__ == "__main__":
    asyncio.run(test_integration())
