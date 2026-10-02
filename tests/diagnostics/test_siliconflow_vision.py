#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试SiliconFlow视觉模型功能
验证Qwen3-VL-235B-A22B-Thinking模型处理图片的两阶段流程
"""

import asyncio
import sys
import os
import base64
from io import BytesIO
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm.siliconflow_client import SiliconFlowClient


def create_test_image(width=100, height=100, color=(128, 128, 128)):
    """创建一个测试图片"""
    img = Image.new('RGB', (width, height), color)
    buffer = BytesIO()
    img.save(buffer, format='JPEG')
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


async def test_vision_model():
    """测试视觉模型功能"""
    print("=" * 60)
    print("SiliconFlow 视觉模型测试")
    print("=" * 60)

    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        print("错误: 请设置 SILICONFLOW_API_KEY 环境变量")
        return False

    client = SiliconFlowClient(api_key=api_key)
    await client.initialize()

    print(f"\n视觉模型: {client.VISION_MODEL}")
    print(f"默认LLM模型: {client.default_model}")

    test_base64_image = create_test_image(100, 100, (128, 128, 128))

    print("\n" + "-" * 40)
    print("测试1: 检测图片内容")
    print("-" * 40)

    messages_with_image = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "请描述这张图片"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{test_base64_image}"}}
            ]
        }
    ]

    has_image = client._has_image_content(messages_with_image)
    print(f"检测到图片内容: {has_image}")

    messages_without_image = [
        {"role": "user", "content": "你好，介绍一下你自己"}
    ]

    has_image2 = client._has_image_content(messages_without_image)
    print(f"无图片消息检测结果: {has_image2}")

    print("\n" + "-" * 40)
    print("测试2: 提取文本prompt")
    print("-" * 40)

    text_prompt = client._extract_text_prompt(messages_with_image)
    print(f"提取的文本prompt: {text_prompt}")

    print("\n" + "-" * 40)
    print("测试3: 两阶段视觉模型调用")
    print("-" * 40)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "这张图片里有什么？"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{test_base64_image}"}}
            ]
        }
    ]

    try:
        result = await client.chat(messages, max_tokens=500)
        print(f"\nchat返回结果:\n{result}")
    except Exception as e:
        print(f"测试过程中出现错误: {e}")

    print("\n" + "-" * 40)
    print("测试4: 普通文本chat（无图片）")
    print("-" * 40)

    text_messages = [
        {"role": "user", "content": "你好"}
    ]

    try:
        result = await client.chat(text_messages, max_tokens=100)
        print(f"普通chat返回: {result[:100]}...")
    except Exception as e:
        print(f"测试过程中出现错误: {e}")

    await client.shutdown()

    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)


async def test_stream_vision():
    """测试流式视觉模型"""
    print("\n" + "=" * 60)
    print("流式视觉模型测试")
    print("=" * 60)

    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        print("错误: 请设置 SILICONFLOW_API_KEY 环境变量")
        return

    client = SiliconFlowClient(api_key=api_key)
    await client.initialize()

    test_base64_image = create_test_image(100, 100, (200, 100, 50))

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "这张图片里有什么？"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{test_base64_image}"}}
            ]
        }
    ]

    print("\n开始流式输出:")
    print("-" * 40)

    async for chunk in client.stream_chat(messages, max_tokens=500):
        if "content" in chunk:
            print(chunk["content"], end="", flush=True)
        elif "error" in chunk:
            print(f"\n错误: {chunk['error']}")

    print("\n" + "-" * 40)

    await client.shutdown()


if __name__ == "__main__":
    asyncio.run(test_vision_model())
    asyncio.run(test_stream_vision())