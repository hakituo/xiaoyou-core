#!/usr/bin/env python3
"""
测试DeepSeek通过智谱代理搜索

模拟场景：DeepSeek作为主模型，需要搜索时调用WebSearchTool，
WebSearchTool通过智谱glm-4.5-air(开启web_search)完成搜索
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from core.tools.implementations import WebSearchTool


async def test_zhipu_proxy_search():
    """测试智谱代理搜索：WebSearchTool调用智谱完成搜索"""
    print("=" * 60)
    print("测试: DeepSeek主模型 → 智谱代理搜索")
    print("=" * 60)

    tool = WebSearchTool()

    queries = [
        "2026年5月最新的AI新闻",
        "Python最新版本有什么新特性",
        "今天的天气怎么样",
    ]

    for query in queries:
        print(f"\n--- 搜索: {query} ---")

        # 直接调用_search_via_zhipu
        result = await tool._search_via_zhipu(query)

        if result and not result.startswith("Error") and not result.startswith("Search"):
            print(f"搜索结果 ({len(result)}字):")
            print(result[:400])
            if len(result) > 400:
                print("...")
        else:
            print(f"搜索失败: {result}")

    print()


async def test_provider_resolution():
    """测试provider解析：DeepSeek应该映射到zhipu代理搜索"""
    print("=" * 60)
    print("测试: Provider解析")
    print("=" * 60)

    tool = WebSearchTool()

    # 模拟不同主模型的provider解析
    test_models = [
        ("cloud:deepseek:deepseek-v4-pro", "DeepSeek"),
        ("cloud:siliconflow:Qwen/Qwen3.5-27B", "SiliconFlow"),
        ("cloud:zhipu:glm-4.5-air", "智谱"),
        ("cloud:ark:doubao-pro", "火山方舟"),
    ]

    for model_path, name in test_models:
        provider = tool._extract_provider_from_model(model_path)
        print(f"  {name} ({model_path}) → provider: {provider}")

        if provider:
            try:
                from config.model_config import get_web_search_provider_for_llm
                ws_provider = get_web_search_provider_for_llm(provider)
                print(f"    → web_search provider: {ws_provider}")
            except Exception as e:
                print(f"    → 解析失败: {e}")

    print()


async def test_full_flow():
    """测试完整流程：WebSearchTool._run() 自动选择搜索方式"""
    print("=" * 60)
    print("测试: WebSearchTool._run() 自动选择搜索方式")
    print("=" * 60)

    tool = WebSearchTool()

    # 不设置运行时上下文，使用默认provider
    provider = tool._resolve_provider()
    print(f"默认搜索provider: {provider}")
    print()

    query = "2025年中国AI大模型最新进展"
    print(f"搜索: {query}")

    result = await tool._run(query)
    if result and not result.startswith("Error") and not result.startswith("Search"):
        print(f"结果 ({len(result)}字):")
        print(result[:500])
    else:
        print(f"搜索失败: {result}")

    print()


async def main():
    await test_provider_resolution()
    await test_zhipu_proxy_search()
    await test_full_flow()


if __name__ == "__main__":
    asyncio.run(main())
