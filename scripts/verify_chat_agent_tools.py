import os
import sys
import asyncio

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agents.chat_agent import ChatAgent
from core.tools.registry import ToolRegistry

async def verify_tools():
    print("Initializing ChatAgent...")
    try:
        agent = ChatAgent()
        print("ChatAgent initialized.")
        
        tools = agent.tool_registry.list_tools()
        print(f"Registered tools ({len(tools)}):")
        for tool in tools:
            print(f" - {tool.name}: {tool.description}")
            
        expected_tools = ["generate_math_plot", "create_file", "text_to_speech"]
        missing_tools = []
        tool_names = [t.name for t in tools]
        
        for et in expected_tools:
            if et not in tool_names:
                missing_tools.append(et)
        
        if missing_tools:
            print(f"\n[FAIL] Missing expected tools: {missing_tools}")
        else:
            print("\n[SUCCESS] All expected tools are registered.")
            
    except Exception as e:
        print(f"\n[ERROR] Failed to initialize ChatAgent: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify_tools())
