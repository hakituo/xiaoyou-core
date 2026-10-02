#!/usr/bin/env python3
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from core.tools.implementations import WebSearchTool


async def test_full_preprocess():
    """测试完整的预处理流程：规则过滤 + LLM精炼 + 输出清理"""
    print("=" * 60)
    print("测试: WebSearchTool 完整预处理流程")
    print("=" * 60)

    tool = WebSearchTool()

    raw_search_results = """Title: 2025年中国AI大模型最新进展汇总 - 科技日报
Snippet: 2025年，中国AI大模型领域迎来爆发式增长。DeepSeek推出V3模型，在多项基准测试中超越GPT-4o；智谱AI发布GLM-5系列，支持原生工具调用和深度推理；月之暗面推出Kimi-K2，在代码生成领域表现突出。此外，百度文心大模型4.5 Turbo版本发布，阿里通义千问Qwen3系列全面开源。
URL: https://tech.example.com/ai-progress-2025

Title: 【广告】AI培训课程限时优惠！零基础学大模型开发 - 某培训机构
Snippet: 零基础入门AI大模型开发，原价9999元，限时优惠3999元！包含DeepSeek、GLM、Qwen等主流模型实战教程，赠送GPU算力时长。报名即送面试辅导和就业推荐！名额有限，先到先得！
URL: https://ad.example.com/ai-course

Title: DeepSeek V3技术报告解读 - 知乎专栏
Snippet: DeepSeek V3采用MoE架构，总参数671B，激活参数37B。在MMLU、HumanEval等基准上达到SOTA水平。训练成本仅557万美元，远低于GPT-4的1亿美元。该模型完全开源，支持商业使用。
URL: https://zhuanlan.zhihu.com/deepseek-v3

Title: 2025年最值得买的手机推荐 - 消费导购
Snippet: 2025年手机选购指南：iPhone 17 Pro Max、华为Mate 70 Pro+、小米15 Ultra等旗舰手机对比评测。AI拍照、卫星通信、折叠屏等新功能全面解析。
URL: https://shop.example.com/phone-guide

Title: 智谱AI GLM-5发布：原生Agent能力 - 机器之心
Snippet: 智谱AI发布GLM-5系列模型，首次在单个模型中实现推理、编码和Agent能力原生融合。GLM-5总参数3550亿，激活参数320亿，支持128K上下文。在SWE-Bench、TAU-Bench等Agent评测中表现优异，可作为Claude Code的替代方案。
URL: https://www.jiqizhixin.com/glm-5-launch"""

    query = "2025年中国AI大模型有哪些重要进展？"

    print(f"--- 原始搜索结果 ({len(raw_search_results)}字, 5条) ---")
    print(raw_search_results[:300] + "...\n")

    # 第一步：规则过滤
    filtered = tool._rule_based_filter(raw_search_results)
    print(f"--- 规则过滤后 ({len(filtered)}字) ---")
    print(filtered[:300] + "...\n")

    # 第二步：LLM精炼 + 输出清理
    preprocessed = await tool._call_preprocess_llm(query, filtered)
    if preprocessed:
        print(f"--- LLM精炼后 ({len(preprocessed)}字) ---")
        print(preprocessed)
        print(f"\n总压缩比: {len(raw_search_results)}字 -> {len(preprocessed)}字 ({len(preprocessed)/len(raw_search_results)*100:.1f}%)")
    else:
        print("LLM精炼失败，使用规则过滤结果")
        print(filtered)


async def main():
    await test_full_preprocess()


if __name__ == "__main__":
    asyncio.run(main())
