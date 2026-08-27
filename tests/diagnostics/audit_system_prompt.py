
import os
import sys
import asyncio
from unittest.mock import patch

sys.path.append(r"d:\AI\xiaoyou-core")

from core.agents.chat_agent import ChatAgent
from core.agents.chat_agent_components.persona_system.prompt import build_persona_prompt
from core.character.managers.persona_manager import PersonaManager


def _preview(text: str, limit: int = 120) -> str:
    s = str(text or "").replace("\n", "\\n")
    return s[:limit] + ("..." if len(s) > limit else "")


async def audit_system_prompt() -> None:
    print("--- Auditing System Prompt (QQ Mode, Real Injection Path) ---")

    pm = PersonaManager()
    pm.current_persona_file = "qq/Aveline_QQ_Master.json"
    pm._load_current_persona()

    agent = ChatAgent()
    await agent.initialize()

    user_id = "private_123456"
    user_name = "Master"
    message = "早安，今天天气怎么样？"

    prompt = build_persona_prompt(
        agent=agent,
        user_id=user_id,
        user_name=user_name,
        mode="chat",
        message=message,
    )

    print("\n[Generated System Prompt - Full]:")
    print(f"[Prompt Length]: {len(prompt)} chars")
    print("=" * 80)
    print(prompt)
    print("=" * 80)

    print("\n[Prompt Structure Analysis]:")
    lines = prompt.split("\n")
    print(f"- Total lines: {len(lines)}")
    print(f"- Total chars: {len(prompt)}")
    
    dynamic_markers = ["当前时间", "仿生体状态", "情绪状态", "饮食系统"]
    for marker in dynamic_markers:
        if marker in prompt:
            idx = prompt.find(marker)
            print(f"- Found '{marker}' at position {idx}")


if __name__ == "__main__":
    asyncio.run(audit_system_prompt())
