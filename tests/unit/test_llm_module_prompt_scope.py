import asyncio


def test_stream_chat_prompt_scope_regression():
    from core.modules.llm.module import LLMModule

    class _FakeLlama:
        def n_ctx(self):
            return 2048

        def create_chat_completion(self, messages, **kwargs):
            assert isinstance(messages, list)
            assert messages
            yield {"choices": [{"delta": {"content": "OK"}}]}

    llm = LLMModule(config={"text_model_path": "fake.gguf"})
    llm.is_loaded = True
    llm.is_gguf = True
    llm.llama_model = _FakeLlama()
    llm._use_cpp_scheduler_for_llm = False

    async def _runner():
        chunks = []
        async for chunk in llm.stream_chat(
            [{"role": "user", "content": "hi"}],
            max_tokens=8,
            temperature=0.7,
            first_token_timeout=3.0,
        ):
            if "content" in chunk:
                chunks.append(chunk["content"])
            if chunk.get("error"):
                raise AssertionError(chunk["error"])
        return "".join(chunks)

    result = asyncio.run(_runner())
    assert result == "OK"

