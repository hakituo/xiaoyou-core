#!/usr/bin/env python3
"""
端到端测试：DeepSeek主模型 → WebSearchTool(智谱代理搜索) → DeepSeek生成回答

模拟ChatAgent的完整工具调用流程：
1. DeepSeek判断需要搜索
2. 调用WebSearchTool（通过智谱代理搜索）
3. 搜索结果注入上下文
4. DeepSeek基于搜索结果生成最终回答
"""
import asyncio
import sys
import os
import re
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from core.llm.openai_compat.deepseek_client import DeepSeekClient
from core.tools.implementations import WebSearchTool
from core.tools.registry import ToolRegistry
from core.utils.logger import get_logger

logger = get_logger("test_e2e_search")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")


async def test_step1_tool_registry():
    """测试1: ToolRegistry能否正确生成web_search的OpenAI Function Calling格式"""
    print("=" * 60)
    print("测试1: ToolRegistry - web_search工具注册")
    print("=" * 60)

    registry = ToolRegistry()
    registry.register(WebSearchTool())

    # 获取OpenAI Function Calling格式
    openai_tools = registry.get_openai_tools()
    print(f"注册工具数: {len(openai_tools)}")
    for tool in openai_tools:
        func = tool.get("function", {})
        print(f"  工具名: {func.get('name')}")
        print(f"  描述: {func.get('description')}")
        params = func.get("parameters", {})
        print(f"  参数: {json.dumps(params, ensure_ascii=False, indent=4)}")
    print()


async def test_step2_deepseek_tool_calling():
    """测试2: DeepSeek能否正确发起web_search工具调用"""
    print("=" * 60)
    print("测试2: DeepSeek - 发起web_search工具调用")
    print("=" * 60)

    client = DeepSeekClient(
        api_key=DEEPSEEK_API_KEY,
        model="deepseek-chat",
        thinking_enabled=False,
    )
    await client.initialize()

    registry = ToolRegistry()
    registry.register(WebSearchTool())
    openai_tools = registry.get_openai_tools()

    messages = [
        {"role": "user", "content": "2026年5月有什么重要的AI新闻？请搜索一下。"}
    ]

    print(f"用户问题: {messages[0]['content']}")
    print(f"传递给DeepSeek的工具数: {len(openai_tools)}")
    print()

    # 调用DeepSeek，传入tools参数
    result = await client.chat(
        messages,
        temperature=0.3,
        tools=openai_tools,
        tool_choice="auto",
    )

    if isinstance(result, dict):
        # 检查是否有tool_calls
        response_obj = result.get("raw_response")
        tool_calls = result.get("tool_calls")

        if tool_calls:
            print(f"✅ DeepSeek发起了工具调用!")
            for tc in tool_calls:
                func = tc.get("function", {})
                print(f"  工具名: {func.get('name')}")
                args_str = func.get("arguments", "{}")
                print(f"  参数: {args_str}")
        else:
            # 检查raw_response
            content = result.get("response", "")
            print(f"DeepSeek直接回复 (未调用工具):")
            print(f"  {content[:200]}...")

            # 尝试从文本中提取TOOL_USE标记
            tool_match = re.search(r'\[TOOL_USE:\s*({.*?})\]', content, re.DOTALL)
            if tool_match:
                print(f"\n✅ DeepSeek通过文本标记发起了工具调用!")
                print(f"  {tool_match.group(1)}")
    else:
        print(f"结果: {str(result)[:300]}")

    await client.shutdown()
    print()


async def test_step3_zhipu_search():
    """测试3: WebSearchTool(智谱代理)能否正确搜索"""
    print("=" * 60)
    print("测试3: WebSearchTool - 智谱代理搜索")
    print("=" * 60)

    tool = WebSearchTool()

    # 模拟DeepSeek传来的搜索参数
    query = "2026年5月AI新闻"

    print(f"搜索查询: {query}")
    print(f"搜索provider: {tool._resolve_provider()}")
    print()

    result = await tool._run(query=query, count=3)

    if result and not result.startswith("Error") and not result.startswith("Search"):
        print(f"✅ 搜索成功! 结果({len(result)}字):")
        print(result[:500])
        if len(result) > 500:
            print("...")
    else:
        print(f"❌ 搜索失败: {result}")
    print()


async def test_step4_full_flow():
    """测试4: 完整流程 - DeepSeek搜索+生成"""
    print("=" * 60)
    print("测试4: 完整流程 - DeepSeek调用搜索→基于结果生成回答")
    print("=" * 60)

    client = DeepSeekClient(
        api_key=DEEPSEEK_API_KEY,
        model="deepseek-chat",
        thinking_enabled=False,
    )
    await client.initialize()

    registry = ToolRegistry()
    registry.register(WebSearchTool())
    openai_tools = registry.get_openai_tools()

    user_query = "2026年5月有什么重要的AI新闻？"
    messages = [{"role": "user", "content": user_query}]

    print(f"用户问题: {user_query}\n")

    # 第一步：DeepSeek判断是否需要搜索
    print("[步骤1] DeepSeek判断是否需要搜索...")
    result = await client.chat(
        messages,
        temperature=0.3,
        tools=openai_tools,
        tool_choice="auto",
    )

    tool_call_info = None
    if isinstance(result, dict):
        tool_calls = result.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                func = tc.get("function", {})
                if func.get("name") == "web_search":
                    tool_call_info = func
                    break

        # 也检查文本标记
        if not tool_call_info:
            content = result.get("response", "")
            tool_match = re.search(r'\[TOOL_USE:\s*({.*?})\]', content, re.DOTALL)
            if tool_match:
                tool_call_info = json.loads(tool_match.group(1))

    if not tool_call_info:
        print("DeepSeek没有调用搜索工具，直接回复了")
        if isinstance(result, dict):
            print(f"回复: {result.get('response', '')[:300]}")
        await client.shutdown()
        return

    print(f"✅ DeepSeek调用了web_search!")
    args_str = tool_call_info.get("arguments", "{}")
    if isinstance(args_str, str):
        args = json.loads(args_str)
    else:
        args = args_str
    search_query = args.get("query", user_query)
    print(f"  搜索查询: {search_query}")

    # 第二步：执行搜索（通过智谱代理）
    print("\n[步骤2] 通过智谱代理执行搜索...")
    tool = WebSearchTool()
    search_result = await tool._run(query=search_query, count=3)

    if search_result.startswith("Error") or search_result.startswith("Search"):
        print(f"❌ 搜索失败: {search_result}")
        await client.shutdown()
        return

    print(f"✅ 搜索成功! ({len(search_result)}字)")
    print(f"  摘要: {search_result[:150]}...")

    # 第三步：搜索结果注入上下文，DeepSeek生成最终回答
    print("\n[步骤3] DeepSeek基于搜索结果生成回答...")
    messages.append({
        "role": "assistant",
        "content": f"我来搜索一下相关信息。[TOOL_USE: {json.dumps({'name': 'web_search', 'arguments': args}, ensure_ascii=False)}]"
    })
    messages.append({
        "role": "system",
        "content": f'工具"web_search"输出：\n{search_result}\n\n请基于该信息继续对话。'
    })

    final_result = await client.chat(messages, temperature=0.6)

    if isinstance(final_result, dict):
        final_response = final_result.get("response", "")
        print(f"✅ DeepSeek最终回答:")
        print(f"{final_response[:500]}")
        if len(final_response) > 500:
            print("...")
    else:
        print(f"结果: {str(final_result)[:300]}")

    await client.shutdown()
    print()


async def main():
    if not DEEPSEEK_API_KEY:
        print("错误: 未找到 DEEPSEEK_API_KEY")
        return

    if not os.getenv("ZHIPU_API_KEY"):
        print("错误: 未找到 ZHIPU_API_KEY")
        return

    await test_step1_tool_registry()
    await test_step2_deepseek_tool_calling()
    await test_step3_zhipu_search()
    await test_step4_full_flow()


if __name__ == "__main__":
    asyncio.run(main())
