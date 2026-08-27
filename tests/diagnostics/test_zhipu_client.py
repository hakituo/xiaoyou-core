#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智谱AI客户端集成测试

测试模型：
- glm-4.5-air: 轻量文本模型
- glm-4.6v: 视觉模型
- glm-4.7: 高性能文本模型
- web_search: 联网搜索功能
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from core.llm.openai_compat.zhipu_client import ZhiPuClient


API_KEY = os.getenv("ZHIPU_API_KEY")
IMAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "20260501_0134752.png")


async def test_glm_45_air():
    print("=" * 60)
    print("测试 glm-4.5-air (文本模型 + 思考模式)")
    print("=" * 60)

    client = ZhiPuClient(
        api_key=API_KEY,
        model="glm-4.5-air",
        thinking_enabled=True,
    )
    await client.initialize()

    messages = [
        {"role": "user", "content": "请用三句话介绍一下人工智能的发展历程"}
    ]

    result = await client.chat(messages, temperature=0.6)
    if isinstance(result, dict):
        print(f"回复: {result.get('response', '')[:500]}")
        print(f"finish_reason: {result.get('finish_reason')}")
    else:
        print(f"结果: {str(result)[:500]}")

    await client.shutdown()
    print()


async def test_glm_46v():
    print("=" * 60)
    print("测试 glm-4.6v (视觉模型)")
    print("=" * 60)

    client = ZhiPuClient(
        api_key=API_KEY,
        model="glm-4.6v",
        thinking_enabled=False,
    )
    await client.initialize()

    if os.path.exists(IMAGE_PATH):
        image_msg = ZhiPuClient.build_image_message(IMAGE_PATH, "请详细描述这张图片的内容")
        messages = [image_msg]
    else:
        print(f"图片不存在: {IMAGE_PATH}，使用纯文本测试")
        messages = [{"role": "user", "content": "你好，请介绍一下自己"}]

    result = await client.chat(messages, temperature=0.6, max_tokens=2048)
    if isinstance(result, dict):
        print(f"回复: {result.get('response', '')[:500]}")
        print(f"finish_reason: {result.get('finish_reason')}")
    else:
        print(f"结果: {str(result)[:500]}")

    await client.shutdown()
    print()


async def test_glm_47():
    print("=" * 60)
    print("测试 glm-4.7 (高性能文本模型 + 思考模式)")
    print("=" * 60)

    client = ZhiPuClient(
        api_key=API_KEY,
        model="glm-4.7",
        thinking_enabled=True,
    )
    await client.initialize()

    messages = [
        {"role": "user", "content": "请解释什么是混合专家(MoE)模型架构，以及它的优缺点"}
    ]

    result = await client.chat(messages, temperature=0.6)
    if isinstance(result, dict):
        print(f"回复: {result.get('response', '')[:500]}")
        print(f"finish_reason: {result.get('finish_reason')}")
    else:
        print(f"结果: {str(result)[:500]}")

    await client.shutdown()
    print()


async def test_web_search():
    print("=" * 60)
    print("测试 web_search (联网搜索)")
    print("=" * 60)

    client = ZhiPuClient(
        api_key=API_KEY,
        model="glm-4.5-air",
        thinking_enabled=False,
        web_search_enabled=True,
    )
    await client.initialize()

    messages = [
        {"role": "user", "content": "2025年最新的AI大模型有哪些重要进展？"}
    ]

    result = await client.chat(messages, temperature=0.6)
    if isinstance(result, dict):
        print(f"回复: {result.get('response', '')[:800]}")
        print(f"finish_reason: {result.get('finish_reason')}")
    else:
        print(f"结果: {str(result)[:800]}")

    await client.shutdown()
    print()


async def test_stream_chat():
    print("=" * 60)
    print("测试 glm-4.5-air 流式输出")
    print("=" * 60)

    client = ZhiPuClient(
        api_key=API_KEY,
        model="glm-4.5-air",
        thinking_enabled=True,
    )
    await client.initialize()

    messages = [
        {"role": "user", "content": "写一首关于春天的短诗"}
    ]

    full_content = ""
    async for chunk in client.stream_chat(messages, temperature=0.6):
        if isinstance(chunk, dict):
            if "content" in chunk:
                content = chunk["content"]
                print(content, end="", flush=True)
                full_content += content
            elif "error" in chunk:
                print(f"\n错误: {chunk['error']}")
                break

    print(f"\n\n流式输出完成，总长度: {len(full_content)}")
    await client.shutdown()
    print()


async def main():
    if not API_KEY:
        print("错误: 未找到 ZHIPU_API_KEY 环境变量")
        return

    print(f"API Key: {API_KEY[:8]}...{API_KEY[-4:]}")
    print(f"图片路径: {IMAGE_PATH} (存在: {os.path.exists(IMAGE_PATH)})")
    print()

    tests = [
        ("glm-4.5-air", test_glm_45_air),
        ("glm-4.6v", test_glm_46v),
        ("glm-4.7", test_glm_47),
        ("web_search", test_web_search),
        ("stream", test_stream_chat),
    ]

    print("可用测试:")
    for i, (name, _) in enumerate(tests, 1):
        print(f"  {i}. {name}")
    print(f"  0. 全部运行")
    print()

    try:
        choice = input("请选择测试编号 (默认0): ").strip()
    except EOFError:
        choice = "0"

    if not choice or choice == "0":
        for name, test_fn in tests:
            try:
                await test_fn()
            except Exception as e:
                print(f"测试 {name} 失败: {e}\n")
    else:
        idx = int(choice) - 1
        if 0 <= idx < len(tests):
            name, test_fn = tests[idx]
            try:
                await test_fn()
            except Exception as e:
                print(f"测试 {name} 失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())
