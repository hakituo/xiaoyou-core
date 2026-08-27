import sys
import os
import asyncio
import json
from unittest.mock import MagicMock

import pytest

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agents.chat_agent import ChatAgent, AgentConfig


def test_chat_agent_stream_error_propagation():
    """
    验证 ChatAgent.stream_chat 在底层 LLM 流返回错误块时，
    是否会按约定向上游抛出包含 error/done 的单一块，并立刻结束。
    """

    async def _run():
        config = AgentConfig()
        agent = ChatAgent(config)

        class DummyLLM:
            async def stream_chat(self, *args, **kwargs):
                # 模拟底层 LLM 在流式返回中直接返回错误字典
                yield {"error": "mock-llm-error"}

        # 跳过真实初始化，直接注入假的 LLM 模块，避免加载大模型
        agent.is_initialized = True
        agent.llm_module = DummyLLM()

        chunks = []
        async for chunk in agent.stream_chat(
            user_id="test_user",
            message="hello",
            save_history=False,
            model_hint=None,
        ):
            chunks.append(chunk)

        # 预期只有一个块，且包含 error 与 done 标记
        assert len(chunks) == 1
        assert chunks[0].get("error") == "mock-llm-error"
        assert chunks[0].get("done") is True

    asyncio.run(_run())

def test_auto_clear_history_on_overflow():
    """
    当本地历史记录字符总数过大时，不应清空记忆（避免破坏体验），而是裁剪上下文
    """

    async def _run():
        config = AgentConfig()
        agent = ChatAgent(config)

        class DummyMemoryManager:
            def __init__(self):
                self.cleared_mode = None
                # 构造一个远大于 10000 字符的历史
                self._history = []
                for i in range(80):
                    self._history.append(
                        {
                            "role": "user" if i % 2 == 0 else "assistant",
                            "content": "x" * 200,
                        }
                    )

            def get_history(self):
                return list(self._history)

            def clear_memory(self, mode: str = "all"):
                self.cleared_mode = mode
                self._history = []

        user_id = "test_user_overflow"
        dummy_mm = DummyMemoryManager()

        # 注入假的 memory_manager
        agent.memory_managers[user_id] = dummy_mm
        agent._get_memory_manager = MagicMock(return_value=dummy_mm)

        messages = await agent._build_conversation_history(
            user_id, "hello", model_hint="local"
        )

        # 断言：不应主动清理记忆，而应在构建上下文阶段做裁剪
        assert dummy_mm.cleared_mode is None

        # 断言：传入 LLM 的历史消息被裁剪到合理规模
        history_messages = [
            m
            for m in messages
            if m.get("role") in ("user", "assistant") and m.get("content") != "hello"
        ]
        total_history_chars = sum(len(m.get("content", "")) for m in history_messages)
        assert total_history_chars > 0

        max_chars = 6000
        try:
            from config.integrated_config import get_settings

            n_ctx = int(getattr(get_settings().model, "n_ctx", 0) or 0)
            if n_ctx > 0:
                max_chars = max(max_chars, min(24000, int(n_ctx * 4)))
        except Exception:
            pass

        assert total_history_chars <= max_chars

    asyncio.run(_run())

def test_build_conversation_history_injects_sensitive_only_for_local():
    async def _run():
        config = AgentConfig()
        agent = ChatAgent(config)

        class DummyMemoryManager:
            def __init__(self):
                self.history_calls = []

            def get_history(self, scope=None):
                self.history_calls.append(scope)
                if scope == "cloud":
                    return [
                        {"role": "assistant", "content": "cloud history", "timestamp": 1}
                    ]
                return [
                    {"role": "assistant", "content": "local history", "timestamp": 1}
                ]

            def get_sensitive_memories(self, limit=5):
                return [
                    {"timestamp": 1700000000, "content": "sensitive-1"},
                    {"timestamp": 1700000600, "content": "sensitive-2"},
                ][:limit]

        user_id = "test_user_privacy"
        dummy_mm = DummyMemoryManager()
        agent.memory_managers[user_id] = dummy_mm
        agent._get_memory_manager = MagicMock(return_value=dummy_mm)

        local_messages = await agent._build_conversation_history(
            user_id, "hello", model_hint="local"
        )
        assert dummy_mm.history_calls[-1] == "local"
        assert any(
            m.get("role") == "system"
            and "Private Memories (Local Only)" in (m.get("content") or "")
            and "sensitive-2" in (m.get("content") or "")
            for m in local_messages
        )

        cloud_messages = await agent._build_conversation_history(
            user_id, "hello", model_hint="cloud:siliconflow:deepseek"
        )
        assert dummy_mm.history_calls[-1] == "cloud"
        assert not any(
            m.get("role") == "system"
            and "Private Memories (Local Only)" in (m.get("content") or "")
            for m in cloud_messages
        )

    asyncio.run(_run())


def test_save_conversation_history_marks_private_as_local_sensitive():
    async def _run():
        from core.agents.chat_agent_components.history import save_conversation_history

        class DummyMemoryManager:
            def __init__(self):
                self.calls = []

            def add_memory(self, **kwargs):
                self.calls.append(kwargs)

        class DummyAgent:
            def __init__(self):
                self.mm = DummyMemoryManager()
                self.llm_module = None

            def _get_memory_manager(self, user_id):
                return self.mm

            def _is_study_mode(self, message, model_hint=None):
                return False

        agent = DummyAgent()
        await save_conversation_history(
            agent=agent,
            user_id="u1",
            user_msg="/sensitive hello",
            assistant_msg="ok",
            message_id="m1",
            model_hint="cloud:siliconflow:deepseek",
        )

        assert len(agent.mm.calls) == 2
        for call in agent.mm.calls:
            assert call.get("category") == "sensitive"
            assert call.get("scopes") == ["local"]

    asyncio.run(_run())


def test_build_conversation_history_passes_message_to_system_prompt_builder():
    async def _run():
        from core.agents.chat_agent_components.context import build_conversation_history

        class DummyMemoryManager:
            lock = MagicMock()
            short_term_memory = []

            def get_history(self, scope=None):
                return []

        class DummyAgent:
            def __init__(self):
                self.mm = DummyMemoryManager()
                self.vocab_manager = None
                self.llm_module = None
                self.dependency_manager = None
                self.defect_manager = None
                self.called = []

            def _get_memory_manager(self, user_id: str):
                return self.mm

            def _is_study_mode(self, message: str, model_hint=None):
                return False

            def _get_dynamic_system_prompt(self, user_id=None, active_tools=None, mode=None, message=None):
                self.called.append(message)
                return "sys"

        agent = DummyAgent()
        await build_conversation_history(agent, "u1", "hello world", model_hint="local")
        assert agent.called[-1] == "hello world"

    asyncio.run(_run())


def test_dynamic_system_prompt_injects_dialogue_examples_and_gates_sensitive():
    from core.agents.chat_agent_components.persona import get_dynamic_system_prompt

    class DummyLLM:
        def __init__(self, name: str):
            self._name = name

        def get_current_model_name(self):
            return self._name

    class DummyDialogueSearch:
        def __init__(self, docs):
            self._docs = docs

        def query(self, text, top_k=3):
            return list(self._docs)[:top_k]

    class DummyAgent:
        dependency_manager = None
        defect_manager = None

        def __init__(self, model_name: str):
            self.llm_module = DummyLLM(model_name)
            self.config = type("Cfg", (), {"system_prompt": "BASE_SYS"})()
            self.tool_registry = None
            self.dialogue_search_sfw_daily = DummyDialogueSearch(["SFW_EX_1"])
            self.dialogue_search_sfw_study = None
            self.dialogue_search_sfw = None
            self.dialogue_search_sfw_legacy = None
            self.dialogue_search_sensitive = DummyDialogueSearch(["SENSITIVE_EX_1"])

        def _is_study_mode(self, message: str, model_hint=None):
            return False

    local_agent = DummyAgent("models/llm/L3-8B-Stheno-v3.2-Q5_K_M.gguf")
    local_prompt = get_dynamic_system_prompt(local_agent, user_id="u1", mode="chat", message="亲密一点")
    assert "Dynamic Dialogue Examples" in local_prompt
    assert "SFW_EX_1" in local_prompt
    assert "SENSITIVE_EX_1" in local_prompt

    cloud_agent = DummyAgent("cloud:siliconflow:deepseek-ai/DeepSeek-V3.2")
    cloud_prompt = get_dynamic_system_prompt(cloud_agent, user_id="u1", mode="chat", message="亲密一点")
    assert "SFW_EX_1" in cloud_prompt
    assert "SENSITIVE_EX_1" not in cloud_prompt


def test_dynamic_system_prompt_injects_time_context_block_for_cloud_and_local():
    from core.agents.chat_agent_components.persona import get_dynamic_system_prompt

    class DummyLLM:
        def __init__(self, name: str):
            self._name = name

        def get_current_model_name(self):
            return self._name

    class DummyAgent:
        dependency_manager = None
        defect_manager = None

        def __init__(self, model_name: str):
            self.llm_module = DummyLLM(model_name)
            self.config = type("Cfg", (), {"system_prompt": "BASE_SYS"})()
            self.tool_registry = None
            self.dialogue_search_sfw_daily = None
            self.dialogue_search_sfw_study = None
            self.dialogue_search_sfw = None
            self.dialogue_search_sfw_legacy = None
            self.dialogue_search_sensitive = None

        def _is_study_mode(self, message: str, model_hint=None):
            return False

    local_agent = DummyAgent("models/llm/L3-8B-Stheno-v3.2-Q5_K_M.gguf")
    local_prompt = get_dynamic_system_prompt(local_agent, user_id="u1", mode="chat", message="随便聊聊")
    assert "【时间基准】" in local_prompt
    assert "当前时间段" in local_prompt

    cloud_agent = DummyAgent("cloud:siliconflow:deepseek-ai/DeepSeek-V3.2")
    cloud_prompt = get_dynamic_system_prompt(cloud_agent, user_id="u1", mode="chat", message="随便聊聊")
    assert "【时间基准】" in cloud_prompt
    assert "当前时间段" in cloud_prompt


def test_determine_mode_does_not_force_study_for_qwen():
    from core.agents.chat_agent_components.persona import determine_mode

    class DummyLLM:
        def get_current_model_name(self):
            return "models/llm/Qwen2.5-7B-Instruct-Q4_K_M.gguf"

    class DummyAgent:
        def __init__(self):
            self.llm_module = DummyLLM()

        def _is_study_mode(self, message: str, model_hint=None):
            return False

    agent = DummyAgent()
    assert determine_mode(agent, "随便聊聊") == "chat"


def test_stream_chat_no_system_error_when_injection_disabled():
    async def _run():
        from core.agents.chat_agent_components import streaming as streaming_module

        original_get_life = streaming_module.get_life_simulation_service
        original_sensory = streaming_module.check_aveline_sensory_triggers
        original_behavior = streaming_module.check_aveline_behavior_chains

        class DummyLifeConfig:
            enable_system_error_injection = False
            enable_ignore_injection = False
            system_error_base_probability = 1.0
            ignore_threshold = 100.0
            ignore_probability = 1.0

        class DummyLifeService:
            life_config = DummyLifeConfig()
            life_stats = {
                "mood_score": 0.0,
                "shyness_score": 100.0,
                "is_sick": True,
                "immune_damage": 0.0,
                "level": 1,
            }

            def update_interaction(self, *args, **kwargs):
                return None

            def note_intimacy_context(self):
                return None

        streaming_module.get_life_simulation_service = lambda: DummyLifeService()
        streaming_module.check_aveline_sensory_triggers = lambda _msg: None
        streaming_module.check_aveline_behavior_chains = lambda _msg: None

        try:
            class DummyLLM:
                async def stream_chat(self, *args, **kwargs):
                    yield {"content": "OK"}

            class DummyEmotionManager:
                def process_text(self, *args, **kwargs):
                    return None

            class DummyAgent:
                def __init__(self):
                    self.is_initialized = True
                    self.llm_module = DummyLLM()
                    self.config = type("Cfg", (), {"temperature": 0.1})()
                    self.dependency_manager = None
                    self.defect_manager = None
                    self.tool_registry = None
                    self.emotion_manager = DummyEmotionManager()

                async def initialize(self):
                    self.is_initialized = True

                async def _build_conversation_history(self, user_id, message, model_hint=None, system_prompt=None):
                    return [
                        {"role": "system", "content": system_prompt or "sys"},
                        {"role": "user", "content": message},
                    ]

            out = []
            async for chunk in streaming_module.stream_chat_impl(
                DummyAgent(),
                user_id="u1",
                message="你在干嘛",
                message_id="m1",
                save_history=False,
            ):
                if isinstance(chunk, dict):
                    out.append(str(chunk.get("data") or chunk.get("content") or ""))
                else:
                    out.append(str(chunk))
                if isinstance(chunk, dict) and chunk.get("done") is True:
                    break

            joined = "".join(out)
            assert "SYSTEM ERROR" not in joined
            assert "OK" in joined
        finally:
            streaming_module.get_life_simulation_service = original_get_life
            streaming_module.check_aveline_sensory_triggers = original_sensory
            streaming_module.check_aveline_behavior_chains = original_behavior

    asyncio.run(_run())


def test_stream_postprocess_does_not_emit_standalone_quotes_or_kaomoji():
    async def _run():
        from core.agents.chat_agent_components import streaming as streaming_module

        import config.integrated_config as integrated_config_module

        original_get_settings = getattr(integrated_config_module, "get_settings")
        original_get_life = streaming_module.get_life_simulation_service
        original_sensory = streaming_module.check_aveline_sensory_triggers
        original_behavior = streaming_module.check_aveline_behavior_chains

        class DummyPP:
            enabled = True
            buffer_min_chars = 12
            buffer_hard_chars = 48
            strip_sentence_period = False
            enable_kaomoji = False
            max_kaomoji_per_reply = 1
            base_kaomoji_probability = 0.0

        class DummyChat:
            postprocess = DummyPP()

        class DummySettings:
            chat = DummyChat()

        class DummyLifeConfig:
            enable_system_error_injection = False
            enable_ignore_injection = False

        class DummyLifeService:
            life_config = DummyLifeConfig()
            life_stats = {
                "mood_score": 80.0,
                "shyness_score": 0.0,
                "is_sick": False,
                "immune_damage": 0.0,
                "level": 1,
            }

            def update_interaction(self, *args, **kwargs):
                return None

            def note_intimacy_context(self):
                return None

            def get_state(self):
                return {}

        try:
            integrated_config_module.get_settings = lambda: DummySettings()
            streaming_module.get_life_simulation_service = lambda: DummyLifeService()
            streaming_module.check_aveline_sensory_triggers = lambda _msg: None
            streaming_module.check_aveline_behavior_chains = lambda _msg: None

            class DummyLLM:
                async def stream_chat(self, *args, **kwargs):
                    yield {"content": "你怎么这样？"}
                    yield {"content": "\""}
                    yield {"content": "我只是逗你"}
                    yield {"content": "你是坏蛋？"}
                    yield {"content": "(///ω///)"}
                    yield {"content": "别闹"}

            class DummyEmotionManager:
                def process_text(self, *args, **kwargs):
                    return None

            class DummyAgent:
                def __init__(self):
                    self.is_initialized = True
                    self.llm_module = DummyLLM()
                    self.config = type("Cfg", (), {"temperature": 0.1})()
                    self.dependency_manager = None
                    self.defect_manager = None
                    self.tool_registry = None
                    self.emotion_manager = DummyEmotionManager()

                async def initialize(self):
                    self.is_initialized = True

                async def _build_conversation_history(self, user_id, message, model_hint=None, system_prompt=None):
                    return [
                        {"role": "system", "content": system_prompt or "sys"},
                        {"role": "user", "content": message},
                    ]

                async def _check_daily_routine(self, user_id):
                    return None

                def _get_memory_manager(self, user_id: str):
                    class DummyMM:
                        def get_memories_by_topic(self, *args, **kwargs):
                            return []

                    return DummyMM()

            tokens = []
            async for chunk in streaming_module.stream_chat_impl(
                agent=DummyAgent(),
                user_id="u1",
                message="hello",
                message_id="m1",
                save_history=False,
                model_hint="local",
            ):
                if isinstance(chunk, dict) and chunk.get("type") == "token":
                    tokens.append(str(chunk.get("data") or ""))
                if isinstance(chunk, dict) and chunk.get("done") is True:
                    break

            stripped = [t.strip() for t in tokens if t.strip()]
            assert "\"" not in stripped
            assert "(///ω///)" not in stripped
            joined = "".join(tokens)
            assert "？\"" in joined
            assert "？(///ω///)" in joined
        finally:
            integrated_config_module.get_settings = original_get_settings
            streaming_module.get_life_simulation_service = original_get_life
            streaming_module.check_aveline_sensory_triggers = original_sensory
            streaming_module.check_aveline_behavior_chains = original_behavior

    asyncio.run(_run())


def test_stream_postprocess_strips_role_prefix_and_think_store():
    async def _run():
        from core.agents.chat_agent_components import streaming as streaming_module

        import config.integrated_config as integrated_config_module

        original_get_settings = getattr(integrated_config_module, "get_settings")
        original_get_life = streaming_module.get_life_simulation_service
        original_sensory = streaming_module.check_aveline_sensory_triggers
        original_behavior = streaming_module.check_aveline_behavior_chains

        class DummyPP:
            enabled = True
            buffer_min_chars = 6
            buffer_hard_chars = 48
            buffer_max_delay_ms = 10
            strip_sentence_period = False
            enable_kaomoji = False
            max_kaomoji_per_reply = 0
            base_kaomoji_probability = 0.0
            emit_backchannel_on_slow_ttft = False

        class DummyChat:
            postprocess = DummyPP()

        class DummySettings:
            chat = DummyChat()

        class DummyLifeConfig:
            enable_system_error_injection = False
            enable_ignore_injection = False

        class DummyLifeService:
            life_config = DummyLifeConfig()
            life_stats = {
                "mood_score": 80.0,
                "shyness_score": 0.0,
                "is_sick": False,
                "immune_damage": 0.0,
                "level": 1,
            }

            def update_interaction(self, *args, **kwargs):
                return None

            def note_intimacy_context(self):
                return None

            def get_state(self):
                return {}

        try:
            integrated_config_module.get_settings = lambda: DummySettings()
            streaming_module.get_life_simulation_service = lambda: DummyLifeService()
            streaming_module.check_aveline_sensory_triggers = lambda _msg: None
            streaming_module.check_aveline_behavior_chains = lambda _msg: None

            class DummyLLM:
                async def stream_chat(self, *args, **kwargs):
                    yield {"content": "assistant: 你好\nuser: 你在吗"}
                    yield {"content": "[THINK_STORE: 内部想法]"}
                    yield {"content": "在的，怎么啦"}

            class DummyEmotionManager:
                def process_text(self, *args, **kwargs):
                    return None

            class DummyAgent:
                def __init__(self):
                    self.is_initialized = True
                    self.llm_module = DummyLLM()
                    self.config = type("Cfg", (), {"temperature": 0.1})()
                    self.dependency_manager = None
                    self.defect_manager = None
                    self.tool_registry = None
                    self.emotion_manager = DummyEmotionManager()

                async def initialize(self):
                    self.is_initialized = True

                async def _build_conversation_history(self, user_id, message, model_hint=None, system_prompt=None):
                    return [
                        {"role": "system", "content": system_prompt or "sys"},
                        {"role": "user", "content": message},
                    ]

                async def _check_daily_routine(self, user_id):
                    return None

                def _get_memory_manager(self, user_id: str):
                    class DummyMM:
                        def get_memories_by_topic(self, *args, **kwargs):
                            return []

                    return DummyMM()

            tokens = []
            async for chunk in streaming_module.stream_chat_impl(
                agent=DummyAgent(),
                user_id="u1",
                message="hello",
                message_id="m1",
                save_history=False,
                model_hint="local",
            ):
                if isinstance(chunk, dict) and chunk.get("type") == "token":
                    tokens.append(str(chunk.get("data") or ""))
                if isinstance(chunk, dict) and chunk.get("done") is True:
                    break

            joined = "".join(tokens)
            assert "assistant:" not in joined
            assert "user:" not in joined
            assert "THINK_STORE" not in joined
            assert "你好" in joined
            assert "在的，怎么啦" in joined
        finally:
            integrated_config_module.get_settings = original_get_settings
            streaming_module.get_life_simulation_service = original_get_life
            streaming_module.check_aveline_sensory_triggers = original_sensory
            streaming_module.check_aveline_behavior_chains = original_behavior

    asyncio.run(_run())


def test_stream_postprocess_strips_punct_before_tilde_at_end():
    async def _run():
        from core.agents.chat_agent_components import streaming as streaming_module

        import config.integrated_config as integrated_config_module

        original_get_settings = getattr(integrated_config_module, "get_settings")
        original_get_life = streaming_module.get_life_simulation_service
        original_sensory = streaming_module.check_aveline_sensory_triggers
        original_behavior = streaming_module.check_aveline_behavior_chains

        class DummyPP:
            enabled = True
            buffer_min_chars = 12
            buffer_hard_chars = 48
            buffer_max_delay_ms = 10
            strip_sentence_period = False
            enable_kaomoji = False
            max_kaomoji_per_reply = 0
            base_kaomoji_probability = 0.0
            emit_backchannel_on_slow_ttft = False

        class DummyChat:
            postprocess = DummyPP()

        class DummySettings:
            chat = DummyChat()

        class DummyLifeConfig:
            enable_system_error_injection = False
            enable_ignore_injection = False

        class DummyLifeService:
            life_config = DummyLifeConfig()
            life_stats = {
                "mood_score": 80.0,
                "shyness_score": 0.0,
                "is_sick": False,
                "immune_damage": 0.0,
                "level": 1,
            }

            def update_interaction(self, *args, **kwargs):
                return None

            def note_intimacy_context(self):
                return None

            def get_state(self):
                return {}

        try:
            integrated_config_module.get_settings = lambda: DummySettings()
            streaming_module.get_life_simulation_service = lambda: DummyLifeService()
            streaming_module.check_aveline_sensory_triggers = lambda _msg: None
            streaming_module.check_aveline_behavior_chains = lambda _msg: None

            long_sentence = "你别这样啦我真的会害羞的啦" * 4 + "。"

            class DummyLLM:
                async def stream_chat(self, *args, **kwargs):
                    yield {"content": "好。"}
                    yield {"content": "~"}
                    yield {"content": "你怎么这样？"}
                    yield {"content": "~"}
                    yield {"content": "哼！"}
                    yield {"content": "~"}
                    yield {"content": long_sentence}
                    yield {"content": "~"}

            class DummyEmotionManager:
                def process_text(self, *args, **kwargs):
                    return None

            class DummyAgent:
                def __init__(self):
                    self.is_initialized = True
                    self.llm_module = DummyLLM()
                    self.config = type("Cfg", (), {"temperature": 0.1})()
                    self.dependency_manager = None
                    self.defect_manager = None
                    self.tool_registry = None
                    self.emotion_manager = DummyEmotionManager()

                async def initialize(self):
                    self.is_initialized = True

                async def _build_conversation_history(
                    self, user_id, message, model_hint=None, system_prompt=None
                ):
                    return [
                        {"role": "system", "content": system_prompt or "sys"},
                        {"role": "user", "content": message},
                    ]

                async def _check_daily_routine(self, user_id):
                    return None

                def _get_memory_manager(self, user_id: str):
                    class DummyMM:
                        def get_memories_by_topic(self, *args, **kwargs):
                            return []

                    return DummyMM()

            tokens = []
            async for chunk in streaming_module.stream_chat_impl(
                agent=DummyAgent(),
                user_id="u1",
                message="hello",
                message_id="m1",
                save_history=False,
                model_hint="local",
            ):
                if isinstance(chunk, dict) and chunk.get("type") == "token":
                    tokens.append(str(chunk.get("data") or ""))
                if isinstance(chunk, dict) and chunk.get("done") is True:
                    break

            joined = "".join(tokens)
            assert "。~" not in joined
            assert "？~" not in joined
            assert "！~" not in joined
            assert "好~" in joined
            assert "你怎么这样~" in joined
            assert "哼~" in joined
            assert long_sentence.replace("。", "") + "~" in joined
        finally:
            integrated_config_module.get_settings = original_get_settings
            streaming_module.get_life_simulation_service = original_get_life
            streaming_module.check_aveline_sensory_triggers = original_sensory
            streaming_module.check_aveline_behavior_chains = original_behavior

    asyncio.run(_run())


def test_stream_slow_ttft_backchannel_does_not_cancel_generation():
    async def _run():
        from core.agents.chat_agent_components import streaming as streaming_module

        import config.integrated_config as integrated_config_module

        original_get_settings = getattr(integrated_config_module, "get_settings")
        original_get_life = streaming_module.get_life_simulation_service
        original_sensory = streaming_module.check_aveline_sensory_triggers
        original_behavior = streaming_module.check_aveline_behavior_chains

        class DummyPP:
            enabled = True
            buffer_min_chars = 12
            buffer_hard_chars = 48
            buffer_max_delay_ms = 10
            strip_sentence_period = False
            enable_kaomoji = False
            max_kaomoji_per_reply = 0
            base_kaomoji_probability = 0.0
            emit_backchannel_on_slow_ttft = True  # 强制开启以测试逻辑
            slow_ttft_backchannel_delay_ms = 10
            slow_ttft_backchannel_text = "嗯…"

        class DummyChat:
            postprocess = DummyPP()

        class DummySettings:
            chat = DummyChat()

        class DummyLifeConfig:
            enable_system_error_injection = False
            enable_ignore_injection = False

        class DummyLifeService:
            life_config = DummyLifeConfig()
            life_stats = {
                "mood_score": 80.0,
                "shyness_score": 0.0,
                "is_sick": False,
                "immune_damage": 0.0,
                "level": 1,
            }

            def update_interaction(self, *args, **kwargs):
                return None

            def note_intimacy_context(self):
                return None

            def get_state(self):
                return {}

        try:
            integrated_config_module.get_settings = lambda: DummySettings()
            streaming_module.get_life_simulation_service = lambda: DummyLifeService()
            streaming_module.check_aveline_sensory_triggers = lambda _msg: None
            streaming_module.check_aveline_behavior_chains = lambda _msg: None

            class DummyLLM:
                async def stream_chat(self, *args, **kwargs):
                    await asyncio.sleep(0.05)
                    yield {"content": "别急，我在想。"}
                    yield {"content": "现在好了"}

            class DummyEmotionManager:
                def process_text(self, *args, **kwargs):
                    return None

            class DummyAgent:
                def __init__(self):
                    self.is_initialized = True
                    self.llm_module = DummyLLM()
                    self.config = type("Cfg", (), {"temperature": 0.1})()
                    self.dependency_manager = None
                    self.defect_manager = None
                    self.tool_registry = None
                    self.emotion_manager = DummyEmotionManager()

                async def initialize(self):
                    self.is_initialized = True

                async def _build_conversation_history(self, user_id, message, model_hint=None, system_prompt=None):
                    return [
                        {"role": "system", "content": system_prompt or "sys"},
                        {"role": "user", "content": message},
                    ]

                async def _check_daily_routine(self, user_id):
                    return None

                def _get_memory_manager(self, user_id: str):
                    class DummyMM:
                        def get_memories_by_topic(self, *args, **kwargs):
                            return []

                    return DummyMM()

            tokens = []
            done_seen = False
            async for chunk in streaming_module.stream_chat_impl(
                agent=DummyAgent(),
                user_id="u1",
                message="你好",
                message_id="m1",
                save_history=False,
                model_hint="local",
            ):
                if isinstance(chunk, dict) and chunk.get("type") == "token":
                    tokens.append(str(chunk.get("data") or ""))
                if isinstance(chunk, dict) and chunk.get("done") is True:
                    done_seen = True
                    break

            joined = "".join(tokens)
            assert done_seen is True
            assert "嗯" in joined
            assert "现在好了" in joined
        finally:
            integrated_config_module.get_settings = original_get_settings
            streaming_module.get_life_simulation_service = original_get_life
            streaming_module.check_aveline_sensory_triggers = original_sensory
            streaming_module.check_aveline_behavior_chains = original_behavior

    asyncio.run(_run())


def test_vector_search_load_dependencies_sets_module_on_subsequent_instances():
    import threading

    import core.vector_search as vector_search_module

    original_loaded = vector_search_module._chromadb_loaded
    original_module = getattr(vector_search_module, "_chromadb_module", None)
    try:
        vector_search_module._chromadb_loaded = True
        sentinel = object()
        vector_search_module._chromadb_module = sentinel

        vs = vector_search_module.VectorSearch.__new__(vector_search_module.VectorSearch)
        vs._lock = threading.RLock()
        vs._chromadb_module = None

        vector_search_module.VectorSearch._load_dependencies(vs)
        assert vs._chromadb_module is sentinel
    finally:
        vector_search_module._chromadb_loaded = original_loaded
        vector_search_module._chromadb_module = original_module


def test_stream_daily_summary_only_cloud_and_not_private():
    async def _run(model_hint: str, message: str, expected_called: bool):
        from core.agents.chat_agent_components.streaming import stream_chat_impl

        import core.core_engine.model_manager as model_manager_module

        class DummyModelManager:
            _models = {}

        original_get_model_manager = getattr(model_manager_module, "get_model_manager")
        model_manager_module.get_model_manager = lambda: DummyModelManager()
        try:
            class DummyLLM:
                async def stream_chat(self, *args, **kwargs):
                    yield {"content": "hi"}

            class DummyEmotionManager:
                def process_text(self, *args, **kwargs):
                    return None

            class DummyAgent:
                def __init__(self):
                    self.is_initialized = True
                    self.llm_module = DummyLLM()
                    self.config = type("Cfg", (), {"temperature": 0.1})()
                    self.dependency_manager = None
                    self.defect_manager = None
                    self.tool_registry = type("TR", (), {"get_tool": lambda *_args, **_kwargs: None})()
                    self.emotion_manager = DummyEmotionManager()
                    self.daily_called = 0

                async def initialize(self):
                    self.is_initialized = True

                async def _build_conversation_history(self, user_id, message, model_hint=None):
                    return [
                        {"role": "system", "content": "sys"},
                        {"role": "user", "content": message},
                    ]

                async def _check_daily_routine(self, user_id):
                    self.daily_called += 1
                    return "DAILY"

                async def _save_conversation_history(self, *args, **kwargs):
                    return None

            agent = DummyAgent()

            chunks = []
            async for chunk in stream_chat_impl(
                agent=agent,
                user_id="u1",
                message=message,
                message_id="m1",
                save_history=False,
                model_hint=model_hint,
            ):
                chunks.append(chunk)
                if chunk.get("done") is True:
                    break

            assert (agent.daily_called > 0) is expected_called
            assert any(c.get("done") is True for c in chunks)
        finally:
            model_manager_module.get_model_manager = original_get_model_manager

    asyncio.run(_run("cloud:siliconflow:deepseek", "hello", True))
    asyncio.run(_run("local", "hello", False))
    asyncio.run(_run("cloud:siliconflow:deepseek", "/sensitive hello", False))


def test_memory_clear_endpoints_forward_mode():
    async def _run():
        import importlib

        api = importlib.import_module("routers.v1.memories")
        import core.agents.chat_agent as chat_agent_module

        class DummyAgent:
            def __init__(self):
                self.calls = []

            async def clear_history(self, user_id: str, mode: str = "all"):
                self.calls.append((user_id, mode))

        dummy_agent = DummyAgent()

        original_get_default = getattr(chat_agent_module, "get_default_chat_agent")
        chat_agent_module.get_default_chat_agent = lambda: dummy_agent
        try:
            # POST /clear — 新统一接口，payload 为 dict
            resp_post = await api.clear_session_history(
                {"user_id": "u1", "mode": "short_term"}
            )
            assert resp_post["status"] == "success"
            assert dummy_agent.calls[-1] == ("u1", "short")

            # POST /clear — mode=all
            resp_delete = await api.clear_session_history(
                {"user_id": "u2", "mode": "all"}
            )
            assert resp_delete["status"] == "success"
            assert dummy_agent.calls[-1] == ("u2", "all")
        finally:
            chat_agent_module.get_default_chat_agent = original_get_default

    asyncio.run(_run())

async def _run_context_truncation():
    config = AgentConfig()
    agent = ChatAgent(config)
    
    user_id = "test_user"
    mock_memory_manager = MagicMock()
    
    long_history = []
    for i in range(50):
        long_history.append({
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"This is message {i}. " + "x" * 180
        })
    
    mock_memory_manager.get_history.return_value = long_history
    
    agent.memory_managers[user_id] = mock_memory_manager
    agent._get_memory_manager = MagicMock(return_value=mock_memory_manager)
    
    messages = await agent._build_conversation_history(user_id, "Hello", model_hint="local")

    history_messages = [
        m
        for m in messages
        if m.get("role") in ("user", "assistant") and m.get("content") != "Hello"
    ]

    total_history_chars = sum(len(m.get("content", "")) for m in history_messages)
    max_chars = 6000
    try:
        from config.integrated_config import get_settings

        n_ctx = int(getattr(get_settings().model, "n_ctx", 0) or 0)
        if n_ctx > 0:
            max_chars = max(max_chars, min(24000, int(n_ctx * 4)))
    except Exception:
        pass

    assert total_history_chars <= max_chars

    if history_messages:
        last_msg = history_messages[-1].get("content", "")
        assert "message 49" in last_msg

def test_context_truncation():
    asyncio.run(_run_context_truncation())


def test_context_truncation_injects_compressed_summary():
    async def _run():
        config = AgentConfig()
        agent = ChatAgent(config)

        user_id = "test_user_compress"
        mock_memory_manager = MagicMock()

        long_history = []
        for i in range(70):
            long_history.append(
                {
                    "role": "user" if i % 2 == 0 else "assistant",
                    "content": f"This is message {i}. " + "x" * 220,
                }
            )

        mock_memory_manager.get_history.return_value = long_history
        agent.memory_managers[user_id] = mock_memory_manager
        agent._get_memory_manager = MagicMock(return_value=mock_memory_manager)

        messages = await agent._build_conversation_history(
            user_id, "Hello", model_hint="local"
        )

        assert any(
            m.get("role") == "system" and "【更早对话压缩】" in (m.get("content") or "")
            for m in messages
        )

    asyncio.run(_run())


def test_multiturn_memory_and_dialogue_style_smoke():
    async def _run():
        class DummyLLM:
            def __init__(self):
                self.calls = []

            def get_current_model_name(self):
                return "mock-local"

            async def stream_chat(self, messages, **kwargs):
                self.calls.append(list(messages))

                user_texts = [
                    (m.get("content") or "")
                    for m in messages
                    if m.get("role") == "user"
                ]
                current = (user_texts[-1] if user_texts else "").strip()

                if current == "我叫什么":
                    reply = "作为AI助手 你叫小明"
                else:
                    reply = "作为AI助手 记住了"

                for i in range(0, len(reply), 4):
                    yield {"content": reply[i : i + 4]}

        class DummyEmotionManager:
            def process_text(self, *args, **kwargs):
                return None

        user_id = "mem_style_smoke_user"
        agent = ChatAgent(AgentConfig(agent_name="mem_style_smoke"))
        agent.is_initialized = True
        agent.llm_module = DummyLLM()
        agent.emotion_manager = DummyEmotionManager()

        mm = agent._get_memory_manager(user_id)
        mm.clear_memory(mode="all")

        async def _turn(text: str) -> str:
            out = []
            async for chunk in agent.stream_chat(
                user_id=user_id,
                message=text,
                save_history=True,
                model_hint="local",
            ):
                if isinstance(chunk, dict) and chunk.get("type") == "token":
                    out.append(chunk.get("content") or "")
                if isinstance(chunk, dict) and chunk.get("done") is True:
                    break
            return "".join(out).strip()

        r1 = await _turn("我叫小明")
        r2 = await _turn("我叫什么")

        assert "小明" in r2
        assert not r2.startswith("作为AI")

        assert agent.llm_module.calls
        sys_prompt = (agent.llm_module.calls[0][0].get("content") or "")
        assert "避免客服腔与模板化道歉" in sys_prompt
        assert "不要一味顺从与讨好" in sys_prompt
        assert "默认短句" in sys_prompt

        msgs_2 = agent.llm_module.calls[-1]
        assert any(
            m.get("role") == "user" and "我叫小明" in (m.get("content") or "")
            for m in msgs_2
        )

        print("U1: 我叫小明")
        print(f"A1: {r1}")
        print("U2: 我叫什么")
        print(f"A2: {r2}")

    asyncio.run(_run())


def test_weighted_memory_manager_trim_preserves_recent_messages():
    from memory.weighted_memory_manager import WeightedMemoryManager

    mm = WeightedMemoryManager(
        user_id="test_trim_preserve_recent",
        max_short_term=6,
        max_long_term=10,
        auto_save_interval=0,
        skip_auto_reclassify=True,
    )
    try:
        mm.clear_memory(mode="all")

        for i in range(12):
            role = "user" if i % 2 == 0 else "assistant"
            mm.add_memory(
                content=f"{role}-{i}",
                source=role,
                topics=["chat"],
                scopes=["local", "cloud"],
                category="chat",
            )

        mm._trim_short_term_memory()
        with mm.lock:
            contents = [m.get("content") for m in mm.short_term_memory]

        assert contents == [
            "user-6",
            "assistant-7",
            "user-8",
            "assistant-9",
            "user-10",
            "assistant-11",
        ]
    finally:
        mm.shutdown()


@pytest.mark.integration
def test_dialogue_persists_weighted_categories_to_directories():
    async def _run():
        from core.agents.chat_agent_components import streaming as streaming_module
        from memory.weighted_memory_manager import HISTORY_DIR

        class _DummyLifeConfig:
            enable_ignore_injection = False
            enable_system_error_injection = False

        class _DummyLifeService:
            life_config = _DummyLifeConfig()
            life_stats = {
                "mood_score": 80.0,
                "shyness_score": 0.0,
                "is_sick": False,
                "immune_damage": 0.0,
                "level": 1,
            }

            def update_interaction(self, xp_gain: int = 0):
                return None

            def note_intimacy_context(self):
                return None

        class _DummyEmotionManager:
            def process_text(self, *args, **kwargs):
                return None

            def get_response_strategy(self, *args, **kwargs):
                return None

        def _reply_for(user_text: str) -> str:
            t = (user_text or "").strip()
            tl = t.lower()

            if any(k in t for k in ["今天", "早上", "晚上", "吃", "天气", "心情"]):
                return "听起来你今天状态不错。火锅这种东西真的很容易把人拉回现实一点。你是和谁一起吃的？"
            if any(k in tl for k in ["learn", "study", "python", "algorithm", "code"]) or any(
                k in t for k in ["学习", "算法", "代码", "刷题"]
            ):
                return "你已经在认真啃了。你现在是卡在概念（比如复杂度/思路），还是卡在实现细节（边界、下标、写不出来）？把题目或你写到哪儿发我，我跟你一起顺着理。"
            if any(k in tl for k in ["job", "meeting", "project", "deadline", "email"]) or any(
                k in t for k in ["工作", "会议", "项目", "截止", "邮件", "加班"]
            ):
                return "这听起来挺耗人的，尤其是开会拖到很晚还压着 deadline。你明天最硬的那个交付是什么？我们先把它拆到“今晚能推进的一小步”。"
            if any(k in tl for k in ["festival", "holiday", "christmas", "new year", "birthday"]) or any(
                k in t for k in ["节日", "假期", "圣诞", "新年", "生日", "春节", "中秋"]
            ):
                return "要过节了呀。你是更期待回家那种热闹，还是其实也有点“要应付”的感觉？你打算回去待几天？"

            return "我在。你现在更想先把事讲清楚，还是我直接给你一个能立刻执行的方案？"

        class _DummyLLM:
            def get_current_model_name(self):
                return "mock-local"

            async def chat(self, messages: list, **kwargs):
                return "测试会话"

            async def stream_chat(self, messages, **kwargs):
                user_text = ""
                for m in reversed(messages):
                    if m.get("role") == "user":
                        user_text = (m.get("content") or "").strip()
                        break

                reply = _reply_for(user_text)
                chunk_size = 6
                for i in range(0, len(reply), chunk_size):
                    yield {"content": reply[i : i + chunk_size]}

        original_get_life = streaming_module.get_life_simulation_service
        original_sensory = streaming_module.check_aveline_sensory_triggers
        original_behavior = streaming_module.check_aveline_behavior_chains

        streaming_module.get_life_simulation_service = lambda: _DummyLifeService()
        streaming_module.check_aveline_sensory_triggers = lambda _msg: None
        streaming_module.check_aveline_behavior_chains = lambda _msg: None

        try:
            user_id = "dialogue_mem_smoke_user"
            agent = ChatAgent(AgentConfig(agent_name="dialogue_mem_smoke"))
            agent.is_initialized = True
            agent.llm_module = _DummyLLM()
            agent.emotion_manager = _DummyEmotionManager()

            mm = agent._get_memory_manager(user_id)
            mm.clear_memory(mode="all")

            turns = [
                "今天我吃了火锅，心情不错。",
                "我最近在学习 Python 算法，有点卡住。",
                "工作项目开会到很晚，明天还有 deadline。",
                "过两天是春节，我要回家。",
            ]

            for msg in turns:
                out = []
                async for chunk in agent.stream_chat(
                    user_id=user_id, message=msg, save_history=True
                ):
                    if isinstance(chunk, dict) and chunk.get("type") == "token":
                        out.append(chunk.get("content") or "")
                    if isinstance(chunk, dict) and chunk.get("done") is True:
                        break
                reply_text = "".join(out).strip()
                assert reply_text
                print(f"U: {msg}")
                print(f"A: {reply_text}")
                print("---")

            mm = agent._get_memory_manager(user_id)
            mm.sync_save_memory()

            history_dir = str(HISTORY_DIR)
            weighted_dir = os.path.join(history_dir, "weighted")
            assert os.path.isdir(weighted_dir)

            expected = ["daily", "learning", "work", "festival"]
            for cat in expected:
                cat_dir = os.path.join(weighted_dir, cat)
                assert os.path.isdir(cat_dir)

                cat_file = os.path.join(cat_dir, f"{user_id}_weighted.json")
                assert os.path.isfile(cat_file)

                with open(cat_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                assert isinstance(data.get("weighted_memories"), list)
                assert data.get("weighted_memories")

        finally:
            streaming_module.get_life_simulation_service = original_get_life
            streaming_module.check_aveline_sensory_triggers = original_sensory
            streaming_module.check_aveline_behavior_chains = original_behavior

    asyncio.run(_run())


def test_style_retriever_uses_best_jsonl_and_manual_selected_txt(tmp_path):
    from core.utils.style_retriever import StyleRetriever

    memory_path = tmp_path / "ling.best.jsonl"
    static_path = tmp_path / "ling_manual_selected.txt"

    memory_rows = [
        {
            "chain": {
                "turns": [
                    {"speaker": "user", "content": "你下班了吗"},
                    {"speaker": "ling", "content": "没呢"},
                    {"speaker": "ling", "content": "还在忙"},
                ],
                "chain_text": "用户：你下班了吗\nLing：没呢\nLing：还在忙",
            }
        }
    ]
    memory_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in memory_rows),
        encoding="utf-8",
    )
    static_path.write_text(
        "Ling: 我继续忙啦过会见\n用户: 嗯嗯\n----------------------------------------\nLing：mua\n用户：mua",
        encoding="utf-8",
    )

    retriever = StyleRetriever(str(memory_path), str(static_path))

    assert len(retriever.conversations) == 1
    assert retriever.conversations[0]["user"] == "你下班了吗"
    assert "没呢" in retriever.conversations[0]["ling"]
    assert len(retriever.static_examples) == 2
    assert retriever.static_examples[0]["text"].startswith("Ling：我继续忙啦过会见")

    results = retriever.retrieve("你下班了吗", k=2, threshold=0.0)
    formatted = retriever.format_for_prompt(results, user_label="用户", ai_label="Ling")

    assert "用户" in formatted
    assert "Ling" in formatted


def test_manual_selected_is_fully_injected_in_stable_order(tmp_path):
    import core.agents.chat_agent_components.persona_system.dialogue_examples as de

    persona_name = "Ling"
    static_rel_path = "data/character/test/manual_selected.txt"
    static_file = tmp_path / "data" / "character" / "test" / "manual_selected.txt"
    static_file.parent.mkdir(parents=True, exist_ok=True)
    static_file.write_text(
        "Ling：第一段开头\n用户：第一段用户\n----------------------------------------\nLing：第二段开头\n用户：第二段用户",
        encoding="utf-8",
    )

    old_paths = dict(de._PERSONA_STATIC_TOPIC_PATHS)
    old_chat_paths = dict(de._PERSONA_CHAT_PATHS)
    old_cache = de._STATIC_TOPIC_CACHE
    old_real_cache = de._REAL_CHAT_CACHE
    old_root = de.get_project_root
    try:
        de._PERSONA_STATIC_TOPIC_PATHS = {**old_paths, persona_name: static_rel_path}
        de._PERSONA_CHAT_PATHS = {**old_chat_paths, persona_name: "missing.jsonl"}
        de._STATIC_TOPIC_CACHE = {"mtimes": {}, "by_persona": {}}
        de._REAL_CHAT_CACHE = {"mtimes": {}, "by_persona": {}}
        de.get_project_root = lambda: str(tmp_path)

        all_examples = de.get_all_static_topic_examples(persona_name)
        assert all_examples == [
            "我：第一段开头\n用户：第一段用户",
            "我：第二段开头\n用户：第二段用户",
        ]

        injected_1 = de.get_dialogue_examples(
            agent=None,
            message="随便聊聊",
            mode="chat",
            is_sensitive_mode=False,
            is_local_gguf=False,
            allow_sensitive_dialogue_examples=False,
            persona_name=persona_name,
        )
        injected_2 = de.get_dialogue_examples(
            agent=None,
            message="换个话题",
            mode="chat",
            is_sensitive_mode=False,
            is_local_gguf=False,
            allow_sensitive_dialogue_examples=False,
            persona_name=persona_name,
        )

        expected = "我：第一段开头\n用户：第一段用户\n我：第二段开头\n用户：第二段用户\n"
        assert injected_1 == expected
        assert injected_2 == expected
    finally:
        de._PERSONA_STATIC_TOPIC_PATHS = old_paths
        de._PERSONA_CHAT_PATHS = old_chat_paths
        de._STATIC_TOPIC_CACHE = old_cache
        de._REAL_CHAT_CACHE = old_real_cache
        de.get_project_root = old_root

if __name__ == "__main__":
    asyncio.run(_run_context_truncation())
