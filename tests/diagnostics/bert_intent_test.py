"""
BERT 意图识别测试脚本

用于验证项目中 BERT 模型是否能正常工作
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.services.data_ops.bert_analyzer import get_bert_analyzer
from core.services.intent.service import classify_intent


async def test_bert_analyzer():
    """测试 BertAnalyzer 类"""
    print("=" * 60)
    print("测试 1: BertAnalyzer 基础功能")
    print("=" * 60)
    
    analyzer = get_bert_analyzer()
    
    if not analyzer._session:
        print("❌ BERT 模型未加载！")
        print(f"   模型路径：{analyzer.model_path}")
        print(f"   模型文件存在：{os.path.exists(analyzer.model_path)}")
        return False
    
    print("✅ BERT 模型已加载")
    
    # 测试用例
    test_cases = [
        ("切换到少女模式", "SWITCH_PERSONA"),
        ("查看系统状态", "SHOW_STATUS"),
        ("忘掉刚才的内容", "CLEAR_MEMORY"),
        ("帮我画一张图片", "IMAGE_GEN"),
        ("有哪些可用的模型", "LIST_MODELS"),
        ("今天天气不错", "NONE"),  # 闲聊，无明确意图
    ]
    
    print("\n测试意图识别:")
    print("-" * 60)
    
    all_passed = True
    for text, expected_intent in test_cases:
        result = analyzer.analyze_intent(text)
        detected = result.get("intent", "NONE")
        confidence = result.get("confidence", 0.0)
        reason = result.get("reason", "")
        
        # 判断是否匹配
        match = "✅" if detected == expected_intent else "⚠️"
        if detected != expected_intent and expected_intent == "NONE":
            # 对于闲聊，只要不是误识别为其他意图就行
            match = "✅" if detected == "NONE" else "❌"
        
        print(f"{match} 输入：{text}")
        print(f"   预期：{expected_intent}, 检测：{detected} (置信度：{confidence:.2f})")
        print(f"   原因：{reason}")
        
        if detected != expected_intent and expected_intent != "NONE":
            all_passed = False
    
    return all_passed


async def test_intent_service():
    """测试完整的意图识别服务（包含规则+BERT）"""
    print("\n" + "=" * 60)
    print("测试 2: 完整意图识别服务")
    print("=" * 60)
    
    # 测试用例
    test_cases = [
        ("切换到猫娘模式", "SWITCH_PERSONA"),
        ("显示系统负载", "SHOW_STATUS"),
        ("清空记忆", "CLEAR_MEMORY"),
        ("画一只猫", "IMAGE_GEN"),
        ("列出所有模型", "LIST_MODELS"),
        ("你好啊", "NONE"),  # 闲聊
        ("今天心情怎么样", "NONE"),  # 闲聊
    ]
    
    print("\n测试完整服务:")
    print("-" * 60)
    
    all_passed = True
    for text, expected_intent in test_cases:
        result = await classify_intent(text)
        detected = result.get("intent", "NONE")
        confidence = result.get("confidence", 0.0)
        raw = result.get("raw", "")
        
        match = "✅" if detected == expected_intent else "⚠️"
        
        print(f"{match} 输入：{text}")
        print(f"   预期：{expected_intent}, 检测：{detected} (置信度：{confidence:.2f})")
        print(f"   来源：{raw}")
        
        if detected != expected_intent and expected_intent != "NONE":
            all_passed = False
    
    return all_passed


async def test_performance():
    """测试 BERT 推理性能"""
    print("\n" + "=" * 60)
    print("测试 3: 性能测试")
    print("=" * 60)
    
    analyzer = get_bert_analyzer()
    
    if not analyzer._session:
        print("❌ BERT 模型未加载，跳过性能测试")
        return True
    
    import time
    
    test_text = "切换到少女模式"
    num_iterations = 10
    
    print(f"\n运行 {num_iterations} 次推理测试...")
    
    latencies = []
    for i in range(num_iterations):
        start = time.time()
        analyzer.analyze_intent(test_text)
        latency = (time.time() - start) * 1000  # 转换为毫秒
        latencies.append(latency)
    
    avg_latency = sum(latencies) / len(latencies)
    min_latency = min(latencies)
    max_latency = max(latencies)
    
    print(f"\n性能指标:")
    print(f"   平均延迟：{avg_latency:.2f} ms")
    print(f"   最小延迟：{min_latency:.2f} ms")
    print(f"   最大延迟：{max_latency:.2f} ms")
    
    # 评估性能
    if avg_latency < 50:
        print(f"✅ 性能优秀 (< 50ms)")
    elif avg_latency < 100:
        print(f"✅ 性能良好 (< 100ms)")
    elif avg_latency < 200:
        print(f"⚠️  性能可接受 (< 200ms)")
    else:
        print(f"❌ 性能较差 (> 200ms)，建议优化")
    
    return True


async def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("BERT 意图识别系统测试")
    print("=" * 60)
    print()
    
    # 检查模型文件
    model_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "models", "BERT", "bge-small-zh-v1.5", "onnx", "model.onnx"
    )
    
    print(f"检查模型文件:")
    print(f"   路径：{model_path}")
    print(f"   存在：{os.path.exists(model_path)}")
    
    if not os.path.exists(model_path):
        print("\n❌ 错误：BERT 模型文件不存在！")
        print("   请先下载模型或运行模型转换脚本")
        print("   模型下载地址：https://huggingface.co/BAAI/bge-small-zh-v1.5")
        return
    
    print("\n✅ 模型文件存在\n")
    
    # 运行测试
    results = []
    
    try:
        result1 = await test_bert_analyzer()
        results.append(("BertAnalyzer 基础功能", result1))
    except Exception as e:
        print(f"\n❌ BertAnalyzer 测试失败：{e}")
        results.append(("BertAnalyzer 基础功能", False))
    
    try:
        result2 = await test_intent_service()
        results.append(("完整意图识别服务", result2))
    except Exception as e:
        print(f"\n❌ 完整服务测试失败：{e}")
        results.append(("完整意图识别服务", False))
    
    try:
        result3 = await test_performance()
        results.append(("性能测试", result3))
    except Exception as e:
        print(f"\n❌ 性能测试失败：{e}")
        results.append(("性能测试", False))
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{status}: {test_name}")
    
    all_passed = all(result[1] for result in results)
    
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 所有测试通过！BERT 系统运行正常")
    else:
        print("⚠️  部分测试失败，请检查日志")
    print("=" * 60)
    
    return all_passed


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
