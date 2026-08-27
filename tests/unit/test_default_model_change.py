#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试默认模型已从 DeepSeek 切换到 Qwen 3.5 Plus
"""

import asyncio
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_default_provider():
    """测试默认提供商已切换到 DashScope"""
    from config.integrated_config import get_settings
    
    settings = get_settings()
    
    print("=" * 60)
    print("测试默认模型配置")
    print("=" * 60)
    
    # 检查默认 provider
    provider = settings.model.llm.provider
    model = settings.model.llm.model
    
    print(f"默认 LLM Provider: {provider}")
    print(f"默认 LLM Model: {model}")
    
    # 验证
    assert provider == "dashscope", f"默认 provider 应该是 dashscope，实际是 {provider}"
    assert model == "qwen3.5-plus", f"默认 model 应该是 qwen3.5-plus，实际是 {model}"
    
    print("✅ 默认 Provider 已正确设置为 DashScope")
    print("✅ 默认 Model 已正确设置为 Qwen 3.5 Plus")
    print("=" * 60)
    
    return True


def test_dashscope_client_fixed_model():
    """测试 DashScopeClient 固定使用 qwen3.5-plus"""
    from core.llm.dashscope_client import DashScopeClient
    
    print("\n测试 DashScopeClient 固定模型行为")
    print("=" * 60)
    
    # 尝试传入不同的模型名称
    client = DashScopeClient(api_key="test_key", model="qwen3-max-2025-09-23")
    
    print("传入 model 参数：qwen3-max-2025-09-23")
    print(f"实际 default_model: {client.default_model}")
    
    # 验证固定使用 qwen3.5-plus
    assert client.default_model == "qwen3.5-plus", \
        f"DashScopeClient 应该固定使用 qwen3.5-plus，实际是 {client.default_model}"
    
    print("✅ DashScopeClient 正确固定使用 qwen3.5-plus")
    print("=" * 60)
    
    return True


def test_env_example_updated():
    """测试 .env.example 文件已更新"""
    print("\n测试 .env.example 文件配置")
    print("=" * 60)
    
    env_example_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".env.example"
    )
    
    with open(env_example_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查 DashScope 是否在 DeepSeek 前面
    dashscope_pos = content.find("DASHSCOPE_API_KEY")
    deepseek_pos = content.find("DEEPSEEK_API_KEY")
    
    print(f"DashScope 配置位置：{dashscope_pos}")
    print(f"DeepSeek 配置位置：{deepseek_pos}")
    
    assert dashscope_pos < deepseek_pos, "DashScope 配置应该在 DeepSeek 配置前面"
    
    # 检查是否有说明 DashScope 是默认启用的
    assert "默认启用" in content or "default" in content.lower(), \
        "应该说明 DashScope 是默认启用的"
    
    print("✅ .env.example 已正确更新，DashScope 在 DeepSeek 前面")
    print("=" * 60)
    
    return True


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


if __name__ == "__main__":
    try:
        # 运行所有测试
        test_default_provider()
        test_dashscope_client_fixed_model()
        test_env_example_updated()
        
        print("\n" + "🎉" * 30)
        print("所有测试通过！默认模型已成功从 DeepSeek 切换到 Qwen 3.5 Plus")
        print("🎉" * 30)
        
    except AssertionError as e:
        print(f"\n❌ 测试失败：{e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试出错：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
