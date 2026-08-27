#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 DeepSeek 流式输出
直接在终端查看是否逐字弹出
"""
import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.integrated_config import get_settings


async def test_deepseek_streaming():
    """测试 DeepSeek 流式输出"""
    print("=" * 60)
    print("测试 DeepSeek 流式输出")
    print("=" * 60)
    
    settings = get_settings()
    
    # 检查配置
    provider = settings.model.llm.provider
    model = settings.model.llm.model
    api_key = settings.model.llm.api_key
    
    # 如果配置中没有，尝试从环境变量读取
    if not api_key:
        import os
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
    
    print(f"\n当前配置:")
    print(f"  Provider: {provider}")
    print(f"  Model: {model}")
    print(f"  API Key: {'已配置' if api_key else '未配置'}")
    
    if not api_key:
        print("\n❌ 错误: API Key 未配置，无法测试")
        return
    
    # 导入 OpenAI Client
    from core.llm.openai_compat import DeepSeekClient

    print(f"\n正在初始化 DeepSeek Client...")

    client = DeepSeekClient(
        api_key=api_key,
        model=model
    )
    
    await client.initialize()
    
    print("\n" + "=" * 60)
    print("开始流式生成测试")
    print("=" * 60)
    print("提示词: 你好，请用一句话介绍自己\n")
    print("输出 (观察是否逐字显示):")
    print("-" * 60)
    
    messages = [
        {"role": "user", "content": "你好，请用一句话介绍自己"}
    ]
    
    chunk_count = 0
    total_chars = 0
    import time
    start_time = time.time()
    first_chunk_time = None
    
    try:
        async for chunk in client.stream_chat(messages, max_tokens=50, temperature=0.7):
            if chunk_count == 0:
                first_chunk_time = time.time() - start_time
            
            chunk_count += 1
            
            if isinstance(chunk, dict):
                content = chunk.get("content", "")
                if content:
                    total_chars += len(content)
                    # 直接打印，不换行， flush 确保立即显示
                    print(content, end="", flush=True)
            else:
                content = str(chunk)
                total_chars += len(content)
                print(content, end="", flush=True)
        
        print()  # 最后换行
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        return
    
    elapsed = time.time() - start_time
    
    print("-" * 60)
    print(f"\n统计:")
    print(f"  首 token 延迟: {first_chunk_time:.3f}s" if first_chunk_time else "  首 token 延迟: N/A")
    print(f"  总 chunk 数: {chunk_count}")
    print(f"  总字符数: {total_chars}")
    print(f"  总耗时: {elapsed:.3f}s")
    print(f"  平均每个 chunk 字符数: {total_chars/chunk_count:.2f}" if chunk_count > 0 else "  N/A")
    
    if chunk_count > 0 and total_chars > 0:
        avg_chars_per_chunk = total_chars / chunk_count
        if avg_chars_per_chunk < 5:
            print(f"\n✅ 流式效果良好: 平均每个 chunk 只有 {avg_chars_per_chunk:.2f} 个字符")
            print("   说明是真正的逐 token 流式")
        else:
            print(f"\n⚠️ 流式效果一般: 平均每个 chunk 有 {avg_chars_per_chunk:.2f} 个字符")
            print("   可能是 buffered stream（缓冲流式）")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(test_deepseek_streaming())
