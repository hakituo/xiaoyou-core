from typing import AsyncGenerator, Dict, Any
from domain.interfaces.base_interfaces import LLMInterface, MemoryInterface
from domain.entities.character import CharacterProfile
from shared.di import container

class ChatService:
    def __init__(self, character: CharacterProfile):
        self.character = character
        self.llm = container.resolve(LLMInterface)
        self.memory = container.resolve(MemoryInterface)

    async def process_message(self, user_input: str) -> AsyncGenerator[Dict[str, Any], None]:
        # 1. Check Sensory Triggers
        sensory = self.character.check_sensory_triggers(user_input)
        if sensory:
            yield {"type": "sensory_trigger", "data": sensory.dict()}

        # 2. Check Behavior Chains
        behavior = self.character.check_behavior_chains(user_input)
        if behavior:
            yield {"type": "behavior_chain", "data": behavior.dict()}

        # 3. Save User Message
        await self.memory.add_message("user", user_input)

        # 4. Get History
        history = await self.memory.get_history(limit=10)
        history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])

        # 5. Construct Prompt
        # Inject dynamic state into system prompt (Intimacy, Emotion)
        system_prompt = self._build_system_prompt()
        
        # 6. Stream Response
        full_response = ""
        async for chunk in self.llm.stream_generate(history_text, system_prompt=system_prompt):
            full_response += chunk
            yield {"type": "token", "data": chunk}

        # 7. Save AI Message
        await self.memory.add_message("ai", full_response)

    def _build_system_prompt(self) -> str:
        base = self.character.system_prompt
        state = f"\nCurrent State:\nEmotion: {self.character.current_emotion}\nIntimacy: {self.character.intimacy_level}"
        return f"{base}\n{state}"
