#!/usr/bin/env python3
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from core.tools.implementations import WebSearchTool


async def test_bocha_search():
    print("=== Bocha 客户端搜索测试 ===")
    tool = WebSearchTool()
    result = await tool._run("2025年AI大模型最新进展", count=3)
    print(f"搜索结果:\n{result[:800]}")
    print()


async def test_provider_resolution():
    print("=== Provider 解析测试 ===")
    tool = WebSearchTool()

    # 测试无上下文时的默认provider
    provider = tool._resolve_provider()
    print(f"默认provider: {provider}")

    # 测试从模型路径提取provider
    provider = tool._extract_provider_from_model("cloud:deepseek:deepseek-v4-pro")
    print(f"cloud:deepseek:deepseek-v4-pro -> {provider}")

    provider = tool._extract_provider_from_model("cloud:zhipu:glm-4.5-air")
    print(f"cloud:zhipu:glm-4.5-air -> {provider}")

    provider = tool._extract_provider_from_model("local-model.gguf")
    print(f"local-model.gguf -> {provider}")
    print()


async def main():
    await test_provider_resolution()
    await test_bocha_search()


if __name__ == "__main__":
    asyncio.run(main())
