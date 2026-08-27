"""检查 BERT 模型实际内存占用和推理速度"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.services.data_ops.bert_analyzer import get_bert_analyzer

def main():
    analyzer = get_bert_analyzer()
    
    print("=== 模型加载状态 ===")
    print(f"基础 embedding session: {'已加载' if analyzer._session else '未加载'}")
    
    # 推理速度测试
    print("\n=== 推理速度测试 ===")
    test_text = "我今天学习了Python编程，感觉收获很大"
    
    # 意图识别
    times = []
    for _ in range(10):
        t0 = time.time()
        analyzer.analyze_intent(test_text)
        times.append((time.time() - t0) * 1000)
    print(f"意图识别: {sum(times)/len(times):.1f}ms (avg)")
    
    # 完整分析
    times = []
    for _ in range(10):
        t0 = time.time()
        analyzer.analyze(test_text)
        times.append((time.time() - t0) * 1000)
    print(f"完整分析 (analyze): {sum(times)/len(times):.1f}ms (avg)")

if __name__ == "__main__":
    main()
