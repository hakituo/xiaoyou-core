
import asyncio
import sys
import os
import time
from unittest.mock import MagicMock, patch

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agents.chat_agent_components.context import build_conversation_history
from memory.weighted_memory_manager import WeightedMemoryManager

async def test_timing():
    print("Starting timing test...")
    
    # Mock Agent
    class DummyAgent:
        def __init__(self):
            self.mm = MagicMock(spec=WeightedMemoryManager)
            self.mm.lock = MagicMock()
            self.mm.__enter__ = MagicMock()
            self.mm.__exit__ = MagicMock()
            
            # Simulate enough memories to trigger RAG (min is 6)
            self.mm.weighted_memories = {str(i): {} for i in range(10)}
            self.mm.short_term_memory = [{"id": str(i)} for i in range(10)]
            
            # Simulate hybrid search
            def mock_hybrid_search(*args, **kwargs):
                time.sleep(0.05) # Simulate 50ms search
                return [{"content": "memory", "scopes": ["local"], "category": "general"}]
            self.mm.hybrid_search = mock_hybrid_search
            
            # Simulate keyword search
            def mock_keyword_search(*args, **kwargs):
                time.sleep(0.01)
                return []
            self.mm._search_by_keyword = mock_keyword_search
            
            # Simulate history
            self.mm.get_history.return_value = [{"role": "user", "content": "hi"}]

            self.vocab_manager = None
            self.llm_module = None
            self.dependency_manager = None
            self.defect_manager = None
            self.config = MagicMock()
            
        def _get_memory_manager(self, user_id):
            return self.mm
            
        def _is_study_mode(self, message, model_hint=None):
            return False
            
        def _determine_mode(self, message):
            return "chat"
            
        def _get_dynamic_system_prompt(self, **kwargs):
            time.sleep(0.02) # Simulate prompt generation
            return "sys prompt"

    agent = DummyAgent()
    
    # Mock settings to enable RAG
    with patch("config.integrated_config.get_settings") as mock_settings:
        s = MagicMock()
        s.chat.rag.enabled = True
        s.chat.rag.min_memory_items_to_rag = 6
        s.chat.rag.enable_query_rewrite = True
        s.chat.rag.query_rewrite_model_path = "mock_model_path" # Trigger rewrite logic
        mock_settings.return_value = s
        
        # Mock rewrite LLM loading/inference to avoid actual model loading
        with patch("core.agents.chat_agent_components.context._rewrite_rag_query", side_effect=lambda **k: asyncio.sleep(0.1) or "rewritten query"):
            
            print("Calling build_conversation_history...")
            start = time.perf_counter()
            await build_conversation_history(
                agent,
                "user1",
                "This is a long enough message to trigger RAG rewrite logic potentially?",
                model_hint="local"
            )
            end = time.perf_counter()
            print(f"Total time: {end - start:.4f}s")

            assert end > start, "结束时间应大于开始时间"
            assert (end - start) < 30.0, f"build_conversation_history 耗时过长: {end - start:.4f}s"

if __name__ == "__main__":
    asyncio.run(test_timing())
