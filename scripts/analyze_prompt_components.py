import asyncio
import sys
import os
import json

# Add project root to path
sys.path.append(os.getcwd())

from core.agents.chat_agent import ChatAgent

async def analyze_prompt_components():
    print("Initializing ChatAgent...")
    agent = ChatAgent()
    await agent.initialize()
    
    # 1. Base Template (from Aveline.json)
    # This is what's in agent.config.system_prompt
    base_template = agent.config.system_prompt
    print(f"\n[1. Base Template (from Aveline.json)] Length: {len(base_template)}")
    print("-" * 20)
    print(base_template)
    print("-" * 20)
    
    # 2. Dynamic Construction
    # We call _get_dynamic_system_prompt manually to see what's added
    # We use empty active_tools to simulate the "optimized" state
    print("\n[2. Constructing Dynamic Prompt (No Tools)]")
    full_prompt = agent._get_dynamic_system_prompt(active_tools=[])
    
    print(f"\n[Total Prompt Length]: {len(full_prompt)}")
    
    # Breakdown by sections (heuristic based on known headers)
    sections = [
        "# Role Definition",
        "# System Architecture",
        "# User Protocol",
        "# Cognitive Constraints",
        "# Emotion Protocol",
        "# Language Style",
        "# Emotional State Logic",
        "# Memory Echoes",  # In prompt it might be just "Memory Echo" or injected
        "dependency_prompt_injection", # Not a header, but check variable
        "defect_prompt_injection",
        "# User Profile",
        "# Available Tools",
        "[SYSTEM REMINDER]"
    ]
    
    # Simple split analysis won't work perfectly because some are formatting, 
    # but we can try to find their indices.
    
    sorted_indices = []
    for sec in sections:
        idx = full_prompt.find(sec)
        if idx != -1:
            sorted_indices.append((idx, sec))
    
    sorted_indices.sort()
    
    print("\n--- Component Breakdown ---")
    for i in range(len(sorted_indices)):
        start_idx, name = sorted_indices[i]
        end_idx = sorted_indices[i+1][0] if i+1 < len(sorted_indices) else len(full_prompt)
        length = end_idx - start_idx
        content_preview = full_prompt[start_idx:start_idx+50].replace('\n', ' ')
        print(f"Section: {name:<30} | Length: {length:<5} | Start: {start_idx}")
        # print(f"  Preview: {content_preview}...")

    # Check for "hidden" text between sections or at start
    if sorted_indices and sorted_indices[0][0] > 0:
        print(f"Header (Pre-Section Text)          | Length: {sorted_indices[0][0]}")

if __name__ == "__main__":
    asyncio.run(analyze_prompt_components())
