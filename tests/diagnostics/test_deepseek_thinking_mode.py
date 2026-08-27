#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 DeepSeek 思考模式功能

验证思考模式是否正确启用，reasoning_content 是否正确处理
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.integrated_config import get_settings


async def test_deepseek_thinking_mode():
    """测试 DeepSeek 思考模式"""
    print("=" * 70)
    print("DeepSeek 思考模式测试")
    print("=" * 70)
    
    settings = get_settings()
    
    # 检查配置
    provider = settings.model.llm.provider
    model = settings.model.llm.model
    api_key = settings.model.llm.api_key
    thinking_enabled = getattr(settings.model.llm, 'thinking_enabled', False)
    reasoning_effort = getattr(settings.model.llm, 'reasoning_effort', 'high')
    
    # 如果配置中没有，尝试从环境变量读取
    if not api_key:
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
    
    print(f"\n当前配置:")
    print(f"  Provider: {provider}")
    print(f"  Model: {model}")
    print(f"  API Key: {'已配置' if api_key else '未配置'}")
    print(f"  Thinking Enabled: {thinking_enabled}")
    print(f"  Reasoning Effort: {reasoning_effort}")
    
    if not api_key:
        print("\n❌ 错误：API Key 未配置，无法测试")
        return False
    
    # 导入 DeepSeek Client
    from core.llm.openai_compat import DeepSeekClient

    print(f"\n正在初始化 DeepSeek Client...")
    client = DeepSeekClient(
        api_key=api_key,
        model=model,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
    )
    
    await client.initialize()
    
    print("\n" + "=" * 70)
    print("测试问题：9.11 和 9.8，哪个更大？为什么？")
    print("=" * 70)
    print("\n开始流式生成（观察思考过程）：\n")
    print("-" * 70)
    
    messages = [
        {"role": "user", "content": "9.11 和 9.8，哪个更大？为什么？请详细解释。"}
    ]
    
    full_content = ""
    has_reasoning = False
    
    try:
        async for chunk in client.stream_chat(messages):
            if "error" in chunk:
                print(f"\n❌ 错误：{chunk['error']}")
                return False
            
            if "content" in chunk:
                content = chunk["content"]
                print(content, end="", flush=True)
                full_content += content
                
                if "Thinking Process" in content or "thinking" in content.lower():
                    has_reasoning = True
        
        print("\n" + "-" * 70)
        print("\n测试完成！")
        print(f"  总输出字符数：{len(full_content)}")
        print(f"  是否包含思考过程：{'是' if has_reasoning else '否'}")
        
        # 验证
        if thinking_enabled and not has_reasoning:
            print("\n⚠️  警告：思考模式已启用，但未检测到思考过程输出")
            print("   可能原因：")
            print("   1. 模型返回格式有变化")
            print("   2. reasoning_content 字段名称不同")
            print("   3. 流式解析逻辑需要调整")
        elif thinking_enabled and has_reasoning:
            print("\n✅ 成功：思考模式正常工作！")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败：{e}")
        import traceback
        traceback.print_exc()
        return False


async def test_non_thinking_mode():
    """测试关闭思考模式"""
    print("\n" + "=" * 70)
    print("DeepSeek 思考模式关闭测试")
    print("=" * 70)
    
    settings = get_settings()
    api_key = settings.model.llm.api_key or os.getenv("DEEPSEEK_API_KEY", "")
    model = settings.model.llm.model
    
    if not api_key:
        print("\n❌ 错误：API Key 未配置，无法测试")
        return False
    
    from core.llm.openai_compat import DeepSeekClient

    print(f"\n正在初始化 DeepSeek Client（关闭思考模式）...")
    client = DeepSeekClient(
        api_key=api_key,
        model=model,
        thinking_enabled=False,  # 关闭思考模式
        reasoning_effort="high",
    )
    
    await client.initialize()
    
    print("\n" + "=" * 70)
    print("测试问题：用一句话介绍你自己")
    print("=" * 70)
    print("\n开始流式生成：\n")
    print("-" * 70)
    
    messages = [
        {"role": "user", "content": "用一句话介绍你自己"}
    ]
    
    full_content = ""
    
    try:
        async for chunk in client.stream_chat(messages):
            if "error" in chunk:
                print(f"\n❌ 错误：{chunk['error']}")
                return False
            
            if "content" in chunk:
                content = chunk["content"]
                print(content, end="", flush=True)
                full_content += content
        
        print("\n" + "-" * 70)
        print("\n测试完成！")
        print(f"  总输出字符数：{len(full_content)}")
        
        if "Thinking Process" in full_content:
            print("\n⚠️  警告：思考模式已关闭，但仍检测到思考过程输出")
        else:
            print("\n✅ 成功：思考模式已正确关闭！")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败：{e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主测试函数"""
    print("\n" + "🚀" * 35 + "\n")
    
    # 测试 1：启用思考模式
    result1 = await test_deepseek_thinking_mode()
    
    # 等待一下
    print("\n\n等待 3 秒后继续下一个测试...\n")
    await asyncio.sleep(3)
    
    # 测试 2：关闭思考模式
    result2 = await test_non_thinking_mode()
    
    # 总结
    print("\n" + "=" * 70)
    print("测试总结")
    print("=" * 70)
    print(f"  思考模式启用测试：{'✅ 通过' if result1 else '❌ 失败'}")
    print(f"  思考模式关闭测试：{'✅ 通过' if result2 else '❌ 失败'}")
    print("=" * 70)
    
    return result1 and result2


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
