#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 WebSocket 流式消息
验证后端是否正确发送 response_chunk
"""
import asyncio
import json
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm import get_llm_module


async def test_streaming():
    """测试流式生成并打印每个 chunk"""
    print("=" * 60)
    print("测试 WebSocket 流式消息")
    print("=" * 60)
    
    llm_module = get_llm_module()
    
    messages = [
        {"role": "user", "content": "你好"}
    ]
    
    print("\n开始流式生成...")
    print("-" * 60)
    
    chunk_count = 0
    start_time = time.time()
    
    try:
        # 使用流式接口
        async for chunk in llm_module.stream_chat(messages, max_tokens=30, temperature=0.7):
            chunk_count += 1
            chunk_time = time.time() - start_time
            
            if isinstance(chunk, dict):
                content = chunk.get("content", "")
                error = chunk.get("error", "")
                
                if content:
                    print(f"[{chunk_time:.3f}s] Chunk {chunk_count}: '{content}'")
                elif error:
                    print(f"[{chunk_time:.3f}s] Error: {error}")
            else:
                print(f"[{chunk_time:.3f}s] Chunk {chunk_count}: '{chunk}'")
    
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return
    
    elapsed = time.time() - start_time
    print("-" * 60)
    print(f"\n统计:")
    print(f"  总 chunk 数: {chunk_count}")
    print(f"  总耗时: {elapsed:.3f}s")
    
    if chunk_count > 1:
        print(f"\n✅ 流式工作正常: 收到了 {chunk_count} 个 chunk")
    else:
        print(f"\n⚠️ 流式可能有问题: 只收到 {chunk_count} 个 chunk")


if __name__ == "__main__":
    asyncio.run(test_streaming())
