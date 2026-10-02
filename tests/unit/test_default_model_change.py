#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""默认云端模型路由回归测试。"""

import asyncio


def test_hybrid_llm_module_accepts_none_model_path_for_cloud_chat_and_stream():
    from core.llm import HybridLLMModule

    class DummyCloudModule:
        async def chat(self, messages, **kwargs):
            return {"content": "ok", "model": kwargs.get("model")}

        async def stream_chat(self, messages, **kwargs):
            yield {"content": f"stream:{kwargs.get('model')}"}

    async def _run():
        module = HybridLLMModule(
            local_module=None,
            cloud_module=DummyCloudModule(),
            preload_local=False,
            default_provider="deepseek",
        )
        module.default_model_name = "deepseek-chat"

        chat_result = await module.chat(
            [{"role": "user", "content": "你好"}],
            model_path=None,
        )
        assert isinstance(chat_result, dict)
        assert chat_result.get("model") == "deepseek-chat"

        chunks = []
        async for chunk in module.stream_chat(
            [{"role": "user", "content": "你好"}],
            model_path=None,
        ):
            chunks.append(chunk)

        assert chunks
        assert chunks[0].get("content") == "stream:deepseek-chat"

    asyncio.run(_run())
