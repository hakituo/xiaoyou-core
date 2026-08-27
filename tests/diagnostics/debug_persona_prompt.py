
import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.agents.chat_agent import ChatAgent
from core.agents.chat_agent_components.persona import get_dynamic_system_prompt
from core.character.managers.persona_manager import get_persona_manager

async def main():
    print("Initializing ChatAgent...")
    agent = ChatAgent()
    await agent.initialize()
    
    user_id = "test_user"
    message = "我今天有点累，你能安慰我吗？"
    
    print(f"\nTesting prompt for message: '{message}'")
    
    # Check chat prompt
    prompt_chat = get_dynamic_system_prompt(agent, user_id=user_id, mode="chat", message=message)
    print("\n[Chat Mode Prompt]")
    
    if "# Dynamic Dialogue Examples" in prompt_chat:
        print("FOUND: Dynamic Dialogue Examples section")
        # Extract the examples section
        import re
        match = re.search(r"# Dynamic Dialogue Examples.*?(\n\n|$)", prompt_chat, re.DOTALL)
        if match:
            print("--- Examples Content ---")
            print(match.group(0))
            print("------------------------")
    else:
        print("MISSING: Dynamic Dialogue Examples section")
    
    print("\n--- Full Prompt Preview (First 1000 chars) ---")
    print(prompt_chat[:1000])
    print("...")

if __name__ == "__main__":
    asyncio.run(main())
