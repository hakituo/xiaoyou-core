"""
BERT 模型速度测试

测试三个模型的推理速度
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.services.data_ops.bert_analyzer import get_bert_analyzer


def test_inference_speed():
    """测试推理速度"""
    print("=" * 70)
    print("BERT 模型推理速度测试")
    print("=" * 70)
    
    analyzer = get_bert_analyzer()
    
    # 检查模型加载状态
    print(f"\n模型状态:")
    print(f"  基础模型: {'已加载' if analyzer._session else '未加载'}")
    
    test_texts = [
        "切换到少女模式",
        "今天天气不错",
        "老板说这个项目非常重要，必须在周五前上线",
        "画一只猫",
        "查看系统状态",
    ]
    
    num_iterations = 20
    
    print(f"\n测试配置:")
    print(f"  测试文本数: {len(test_texts)}")
    print(f"  每个文本迭代次数: {num_iterations}")
    print(f"  总推理次数: {len(test_texts) * num_iterations}")
    
    # 测试意图识别速度
    print("\n" + "-" * 70)
    print("测试 1: 意图识别 (analyze_intent)")
    print("-" * 70)
    
    latencies = []
    for text in test_texts:
        for _ in range(num_iterations):
            start = time.time()
            analyzer.analyze_intent(text)
            latency = (time.time() - start) * 1000
            latencies.append(latency)
    
    avg = sum(latencies) / len(latencies)
    min_l = min(latencies)
    max_l = max(latencies)
    print(f"  平均延迟: {avg:.2f} ms")
    print(f"  最小延迟: {min_l:.2f} ms")
    print(f"  最大延迟: {max_l:.2f} ms")
    print(f"  QPS: {1000/avg:.1f} 次/秒")
    
    # 测试完整分析速度（包含三个模型）
    print("\n" + "-" * 70)
    print("测试 2: 完整分析 (analyze) - 包含意图+分类+重要性")
    print("-" * 70)
    
    latencies = []
    for text in test_texts:
        for _ in range(num_iterations):
            start = time.time()
            analyzer.analyze(text)
            latency = (time.time() - start) * 1000
            latencies.append(latency)
    
    avg = sum(latencies) / len(latencies)
    min_l = min(latencies)
    max_l = max(latencies)
    print(f"  平均延迟: {avg:.2f} ms")
    print(f"  最小延迟: {min_l:.2f} ms")
    print(f"  最大延迟: {max_l:.2f} ms")
    print(f"  QPS: {1000/avg:.1f} 次/秒")
    
    # 测试单个模型速度
    print("\n" + "-" * 70)
    print("测试 3: 单个模型推理速度")
    print("-" * 70)
    
    # 只测试意图模型
    latencies_intent = []
    for _ in range(num_iterations * 4):
        start = time.time()
        analyzer._run_intent_inference("测试文本")
        latency = (time.time() - start) * 1000
        latencies_intent.append(latency)
    
    avg_intent = sum(latencies_intent) / len(latencies_intent)
    print(f"  意图模型平均延迟: {avg_intent:.2f} ms")
    
    # 只测试分类模型
    latencies_category = []
    for _ in range(num_iterations * 4):
        start = time.time()
        analyzer._run_category_inference("测试文本")
        latency = (time.time() - start) * 1000
        latencies_category.append(latency)
    
    avg_category = sum(latencies_category) / len(latencies_category)
    print(f"  分类模型平均延迟: {avg_category:.2f} ms")
    
    # 只测试重要性模型
    latencies_importance = []
    for _ in range(num_iterations * 4):
        start = time.time()
        analyzer._run_importance_inference("测试文本")
        latency = (time.time() - start) * 1000
        latencies_importance.append(latency)
    
    avg_importance = sum(latencies_importance) / len(latencies_importance)
    print(f"  重要性模型平均延迟: {avg_importance:.2f} ms")
    
    # 汇总
    print("\n" + "=" * 70)
    print("速度测试汇总")
    print("=" * 70)
    print(f"  单个模型平均延迟: {(avg_intent + avg_category + avg_importance)/3:.2f} ms")
    print(f"  三个模型串行总延迟: {avg_intent + avg_category + avg_importance:.2f} ms")
    print(f"  实际完整分析延迟: {avg:.2f} ms")
    print()
    print("结论:")
    if avg < 100:
        print("  ✅ 速度优秀 (< 100ms)，完全可以满足实时需求")
    elif avg < 200:
        print("  ✅ 速度良好 (< 200ms)，可以满足大多数场景")
    else:
        print("  ⚠️ 速度一般，可能需要优化")
    print("=" * 70)


if __name__ == "__main__":
    try:
        test_inference_speed()
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
