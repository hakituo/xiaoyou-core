#!/usr/bin/env python3
"""
测试智谱模型是否会自动判断是否需要搜索

对比测试：
1. 需要搜索的问题（实时信息）→ 模型应该自动搜索
2. 不需要搜索的问题（常识/推理）→ 模型应该直接回答
3. 模糊问题 → 看模型怎么判断
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from core.llm.openai_compat.zhipu_client import ZhiPuClient

API_KEY = os.getenv("ZHIPU_API_KEY")


async def test_auto_search_decision():
    """测试模型是否自动判断是否需要搜索"""

    test_cases = [
        {
            "name": "需要搜索 - 实时新闻",
            "query": "今天有什么重要新闻？",
            "expect_search": True,
        },
        {
            "name": "需要搜索 - 最新信息",
            "query": "2026年5月最新的AI模型发布有哪些？",
            "expect_search": True,
        },
        {
            "name": "不需要搜索 - 常识问题",
            "query": "地球到月球的距离是多少？",
            "expect_search": False,
        },
        {
            "name": "不需要搜索 - 数学推理",
            "query": "请计算 17 * 23 + 45",
            "expect_search": False,
        },
        {
            "name": "模糊问题 - 可能需要",
            "query": "Python最新版本有什么新特性？",
            "expect_search": None,
        },
    ]

    client = ZhiPuClient(
        api_key=API_KEY,
        model="glm-4.5-air",
        thinking_enabled=False,
        web_search_enabled=True,
    )
    await client.initialize()

    print("=" * 60)
    print("智谱模型 web_search 自动判断测试")
    print("web_search_enabled=True, 模型自行决定是否搜索")
    print("=" * 60)
    print()

    for case in test_cases:
        print(f"--- {case['name']} ---")
        print(f"问题: {case['query']}")

        messages = [{"role": "user", "content": case["query"]}]
        result = await client.chat(messages, temperature=0.6)

        if isinstance(result, dict):
            response = result.get("response", "")
            # 检查是否包含搜索引用（智谱搜索结果通常包含引用标记）
            has_search_marker = "搜索" in response or "来源" in response or "引用" in response or "http" in response.lower()
            print(f"回复 ({len(response)}字): {response[:200]}...")
            print(f"疑似使用搜索: {'是' if has_search_marker else '否'}")
        else:
            print(f"结果: {str(result)[:200]}")
        print()

    await client.shutdown()


async def test_search_vs_no_search():
    """对比测试：同一个问题，开启/关闭搜索的回答差异"""

    print("=" * 60)
    print("对比测试：同一个问题，开启 vs 关闭 web_search")
    print("=" * 60)
    print()

    query = "2026年五一假期有什么热门旅游目的地推荐？"

    # 不开搜索
    client_no_search = ZhiPuClient(
        api_key=API_KEY,
        model="glm-4.5-air",
        thinking_enabled=False,
        web_search_enabled=False,
    )
    await client_no_search.initialize()

    print(f"问题: {query}")
    print("\n[关闭搜索]:")
    result = await client_no_search.chat([{"role": "user", "content": query}], temperature=0.6)
    if isinstance(result, dict):
        print(result.get("response", "")[:300])
    await client_no_search.shutdown()

    # 开搜索
    client_with_search = ZhiPuClient(
        api_key=API_KEY,
        model="glm-4.5-air",
        thinking_enabled=False,
        web_search_enabled=True,
    )
    await client_with_search.initialize()

    print("\n[开启搜索]:")
    result = await client_with_search.chat([{"role": "user", "content": query}], temperature=0.6)
    if isinstance(result, dict):
        print(result.get("response", "")[:300])
    await client_with_search.shutdown()
    print()


async def main():
    if not API_KEY:
        print("错误: 未找到 ZHIPU_API_KEY 环境变量")
        return

    await test_auto_search_decision()
    await test_search_vs_no_search()


if __name__ == "__main__":
    asyncio.run(main())
