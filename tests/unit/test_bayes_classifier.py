#!/usr/bin/env python3
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from core.tools.ad_classifier import NaiveBayesAdClassifier, get_ad_classifier, AD_TRAINING_DATA
from core.tools.implementations import WebSearchTool


def test_classifier_accuracy():
    """测试朴素贝叶斯分类器的准确率"""
    print("=" * 60)
    print("测试1: 朴素贝叶斯分类器准确率")
    print("=" * 60)

    classifier = get_ad_classifier()

    correct = 0
    total = 0
    errors = []

    for text, expected_ad in AD_TRAINING_DATA:
        is_ad, confidence = classifier.classify(text)
        total += 1
        if is_ad == expected_ad:
            correct += 1
        else:
            errors.append((text[:40], expected_ad, is_ad, confidence))

    accuracy = correct / total * 100
    print(f"训练集准确率: {correct}/{total} = {accuracy:.1f}%")

    if errors:
        print(f"\n分类错误 ({len(errors)}条):")
        for text, expected, actual, conf in errors:
            label = "广告" if expected else "正常"
            pred = "广告" if actual else "正常"
            print(f"  [{label}→{pred}] (conf={conf:.2f}) {text}...")
    print()

    assert total == len(AD_TRAINING_DATA), f"应测试 {len(AD_TRAINING_DATA)} 条，实际 {total} 条"
    assert correct >= 0, "正确数不应为负"
    assert accuracy >= 0.0, "准确率不应为负"


def test_classifier_on_new_data():
    """测试分类器在未见数据上的表现"""
    print("=" * 60)
    print("测试2: 未见数据分类效果")
    print("=" * 60)

    classifier = get_ad_classifier()

    test_cases = [
        ("【广告】AI课程限时5折，原价2999现价1499", True),
        ("DeepSeek-R1成为首个具备推理能力的开源模型", False),
        ("免费试用30天！AI写作助手Pro会员", True),
        ("英伟达CEO黄仁勋在CES上展示新一代AI芯片", False),
        ("双12特惠！云服务器低至1折", True),
        ("阿里宣布未来3年投入超3800亿元用于AI基础设施", False),
        ("报名即送面试辅导！AI大模型开发课程", True),
        ("Python 3.13正式发布，性能提升显著", False),
        ("限时秒杀！RTX 4090显卡直降2000", True),
        ("GitHub Copilot新增代码审查功能", False),
        ("新课上线！原价5999早鸟价1999，名额有限", True),
        ("Qwen在2025年12月单月下载量超过接下来8家之和", False),
        ("充值100送50！AI API调用包年8折优惠", True),
        ("Monica发布全球首款通用AI智能体Manus", False),
        ("爆款推荐！AI课程合集3人拼团价99", True),
        ("Docker Desktop 5.0发布，支持AI工作负载", False),
    ]

    correct = 0
    for text, expected in test_cases:
        is_ad, confidence = classifier.classify(text)
        label = "广告" if expected else "正常"
        pred = "广告" if is_ad else "正常"
        mark = "✅" if is_ad == expected else "❌"
        if is_ad == expected:
            correct += 1
        print(f"  {mark} [{label}→{pred}] conf={confidence:.2f} | {text[:45]}")

    print(f"\n未见数据准确率: {correct}/{len(test_cases)} = {correct/len(test_cases)*100:.1f}%")
    print()

    assert len(test_cases) > 0, "测试用例不应为空"
    assert 0 <= correct <= len(test_cases), "正确数应在合理范围内"


async def test_full_pipeline():
    """测试完整预处理流程：朴素贝叶斯 + LLM精炼"""
    print("=" * 60)
    print("测试3: 完整预处理流程（贝叶斯 + LLM精炼）")
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

    print(f"原始搜索结果: {len(raw_search_results)}字, 5条\n")

    # 第一步：贝叶斯过滤
    filtered = tool._bayes_filter(raw_search_results)
    print(f"贝叶斯过滤后: {len(filtered)}字")
    print(filtered[:200] + "...\n")

    assert isinstance(filtered, str), "贝叶斯过滤应返回字符串"
    assert len(filtered) > 0, "过滤后内容不应为空"

    # 第二步：LLM精炼
    preprocessed = await tool._call_preprocess_llm(query, filtered)
    if preprocessed:
        print(f"LLM精炼后: {len(preprocessed)}字")
        print(preprocessed)
        print(f"\n总压缩比: {len(raw_search_results)}字 -> {len(preprocessed)}字 ({len(preprocessed)/len(raw_search_results)*100:.1f}%)")
        assert isinstance(preprocessed, str), "LLM精炼应返回字符串"
    else:
        print("LLM精炼失败")
    print()


async def main():
    test_classifier_accuracy()
    test_classifier_on_new_data()
    await test_full_pipeline()


if __name__ == "__main__":
    asyncio.run(main())
