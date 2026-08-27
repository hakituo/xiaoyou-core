#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 DashScope API 修复
"""

import os
import sys
import asyncio

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_dashscope_api():
    """测试 DashScope API 调用"""
    from core.llm.dashscope_client import DashScopeClient
    
    print("=" * 70)
    print("测试 DashScope API 修复")
    print("=" * 70)
    
    # 创建客户端
    client = DashScopeClient()
    
    print(f"\n客户端配置:")
    print(f"  base_url: {client.base_url}")
    print(f"  default_model: {client.default_model}")
    print(f"  api_key 已配置：{bool(client.api_key)}")
    
    # 测试简单对话
    print("\n测试对话...")
    messages = [
        {"role": "user", "content": "你好，请用一句话介绍你自己"}
    ]
    
    try:
        result = await client.chat(messages)
        print(f"\n✅ 成功!")
        print(f"响应：{result[:100]}...")
        return True
    except Exception as e:
        print(f"\n❌ 失败：{e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # 清理资源
        await client.shutdown()


if __name__ == "__main__":
    try:
        success = asyncio.run(test_dashscope_api())
        if not success:
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试出错：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
