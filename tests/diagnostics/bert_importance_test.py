"""
BERT 重要性分类测试脚本

测试重要性分类模型的效果，并展示其在记忆管理中的作用。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.services.data_ops.bert_analyzer import get_bert_analyzer


def test_importance_classification():
    """测试重要性分类效果"""
    print("=" * 70)
    print("BERT 重要性分类测试")
    print("=" * 70)
    print()
    print("重要性分类用于记忆权重管理：")
    print("  - IMPORTANT: weight_delta > 0，重要记忆保留更久")
    print("  - CASUAL: weight_delta < 0，闲聊内容更快遗忘")
    print()
    
    analyzer = get_bert_analyzer()
    
    # 测试用例：涵盖各种场景
    test_cases = [
        # 工作相关的重要事项
        ("老板说这个项目非常重要，必须在周五前上线", "IMPORTANT", "工作截止日期"),
        ("这件事很紧急，马上处理一下", "IMPORTANT", "紧急任务"),
        ("别忘了交报告，这很关键", "IMPORTANT", "关键提醒"),
        ("明天上午10点有个重要的面试，千万别迟到", "IMPORTANT", "重要约会"),
        ("客户要求今天下班前给出方案", "IMPORTANT", "客户需求"),
        ("这个bug很严重，需要立即修复", "IMPORTANT", "紧急问题"),
        ("记得给妈妈打电话，今天是她的生日", "IMPORTANT", "重要日期"),
        ("周五前必须完成这个功能开发", "IMPORTANT", "截止日期"),
        ("这个决定会影响整个项目的走向", "IMPORTANT", "重要决策"),
        ("明天要签合同，千万别忘了", "IMPORTANT", "重要事件"),
        
        # 健康相关的重要事项
        ("一定要记得吃药，医生说很重要", "IMPORTANT", "健康提醒"),
        ("明天要去医院复查，这个很重要", "IMPORTANT", "医疗预约"),
        
        # 财务相关的重要事项
        ("重要提醒：明天要交房租", "IMPORTANT", "财务提醒"),
        ("务必在今晚12点前提交申请", "IMPORTANT", "截止提醒"),
        
        # 日常闲聊
        ("今天天气不错，想去散步", "CASUAL", "日常闲聊"),
        ("随便聊聊吧", "CASUAL", "闲聊"),
        ("哈哈", "CASUAL", "简单回应"),
        ("晚安", "CASUAL", "问候"),
        ("早上好", "CASUAL", "问候"),
        ("今天心情还行", "CASUAL", "日常状态"),
        ("随便看看", "CASUAL", "闲逛"),
        ("嗯嗯", "CASUAL", "简单回应"),
        ("好的好的", "CASUAL", "简单回应"),
        ("没什么特别的", "CASUAL", "日常描述"),
        ("今天吃了顿好吃的", "CASUAL", "日常分享"),
        ("周末打算睡个懒觉", "CASUAL", "日常计划"),
        ("最近在追一部剧", "CASUAL", "娱乐分享"),
        ("今天有点无聊", "CASUAL", "情绪表达"),
        ("随便逛逛", "CASUAL", "闲逛"),
        ("今天天气一般", "CASUAL", "日常描述"),
        ("没什么事做", "CASUAL", "日常状态"),
        
        # 边缘案例 - 需要仔细判断
        ("今天要去买点生活用品", "CASUAL", "日常购物"),
        ("刚剪了头发，感觉清爽多了", "CASUAL", "日常分享"),
        ("晚上打算看个电影放松一下", "CASUAL", "娱乐计划"),
        ("最近在养绿植，希望不要养死", "CASUAL", "日常爱好"),
        
        # 看起来像重要但实际是闲聊
        ("今天被夸了，心里美滋滋的", "CASUAL", "情绪分享"),
        ("最近很满足，生活挺顺的", "CASUAL", "状态分享"),
    ]
    
    correct = 0
    total = len(test_cases)
    
    print("-" * 70)
    print(f"{'输入':<35} {'期望':<12} {'预测':<12} {'weight':<8} {'结果'}")
    print("-" * 70)
    
    for text, expected, description in test_cases:
        result = analyzer.analyze(text)
        weight_delta = result.get("weight_delta", 0.0)
        confidence = result.get("confidence", 0.0)
        
        # 根据 weight_delta 判断重要性
        predicted = "IMPORTANT" if weight_delta > 0.2 else "CASUAL"
        
        is_correct = predicted == expected
        if is_correct:
            correct += 1
        
        status = "✅" if is_correct else "❌"
        print(f"{text:<35} {expected:<12} {predicted:<12} {weight_delta:+.2f}   {status}")
    
    accuracy = correct / total * 100
    print("-" * 70)
    print(f"准确率: {correct}/{total} = {accuracy:.1f}%")
    
    return accuracy


def test_weight_delta_effect():
    """测试 weight_delta 对记忆权重的影响"""
    print("\n" + "=" * 70)
    print("weight_delta 对记忆权重的影响演示")
    print("=" * 70)
    print()
    
    analyzer = get_bert_analyzer()
    
    # 模拟记忆权重计算
    base_weight = 1.0
    decay_rate = 0.1  # 每次访问衰减
    
    test_memories = [
        ("老板说这个项目非常重要，必须在周五前上线", "IMPORTANT"),
        ("今天天气不错，想去散步", "CASUAL"),
        ("别忘了交报告，这很关键", "IMPORTANT"),
        ("哈哈", "CASUAL"),
        ("明天上午10点有个重要的面试", "IMPORTANT"),
        ("晚安", "CASUAL"),
    ]
    
    print("模拟记忆权重变化（初始权重 = 1.0）：")
    print("-" * 70)
    print(f"{'记忆内容':<35} {'类型':<12} {'weight_delta':<12} {'最终权重'}")
    print("-" * 70)
    
    for text, expected_type in test_memories:
        result = analyzer.analyze(text)
        weight_delta = result.get("weight_delta", 0.0)
        
        # 计算最终权重
        final_weight = base_weight + weight_delta
        final_weight = max(0.1, min(2.0, final_weight))  # 限制范围
        
        print(f"{text:<35} {expected_type:<12} {weight_delta:+.2f}        {final_weight:.2f}")
    
    print("-" * 70)
    print()
    print("说明：")
    print("  - IMPORTANT 记忆：weight_delta ≈ +0.90，权重增加，保留更久")
    print("  - CASUAL 记忆：weight_delta ≈ -0.40，权重减少，更快遗忘")
    print("  - 权重范围：0.1 ~ 2.0")


def test_real_world_scenarios():
    """测试真实场景"""
    print("\n" + "=" * 70)
    print("真实场景测试")
    print("=" * 70)
    print()
    
    analyzer = get_bert_analyzer()
    
    scenarios = [
        {
            "name": "工作场景",
            "messages": [
                "明天下午3点有个部门例会，记得准备材料",
                "项目截止日期是下周五，需要加班赶进度",
                "刚开完会，老板对方案不太满意",
                "今天要写周报，汇总一下本周工作",
            ]
        },
        {
            "name": "日常闲聊",
            "messages": [
                "今天天气不错",
                "晚上打算早点睡",
                "最近在追一部剧",
                "哈哈笑死我了",
            ]
        },
        {
            "name": "健康提醒",
            "messages": [
                "一定要记得吃药，医生说很重要",
                "明天要去医院复查",
                "最近睡眠不太好",
                "今天去健身房了",
            ]
        },
        {
            "name": "边缘案例",
            "messages": [
                "今天心情不错",  # 看起来像闲聊
                "这个决定很重要",  # 明确说重要
                "随便说说而已",  # 明确说不重要
                "记得提醒我明天开会",  # 有提醒需求
            ]
        }
    ]
    
    for scenario in scenarios:
        print(f"\n【{scenario['name']}】")
        print("-" * 50)
        
        for msg in scenario["messages"]:
            result = analyzer.analyze(msg)
            weight_delta = result.get("weight_delta", 0.0)
            predicted = "IMPORTANT" if weight_delta > 0.2 else "CASUAL"
            
            print(f"  {msg:<30} → {predicted:<10} (weight: {weight_delta:+.2f})")


def main():
    print("\n" + "=" * 70)
    print("BERT 重要性分类完整测试")
    print("=" * 70)
    print()
    
    # 检查模型状态
    analyzer = get_bert_analyzer()
    print(f"模型状态:")
    print(f"  基础模型: {'已加载' if analyzer._session else '未加载'}")
    print()
    
    # 运行测试
    results = {}
    
    try:
        results["准确性测试"] = test_importance_classification()
    except Exception as e:
        print(f"\n❌ 准确性测试失败: {e}")
        import traceback
        traceback.print_exc()
        results["准确性测试"] = 0
    
    try:
        test_weight_delta_effect()
    except Exception as e:
        print(f"\n❌ 权重影响测试失败: {e}")
    
    try:
        test_real_world_scenarios()
    except Exception as e:
        print(f"\n❌ 真实场景测试失败: {e}")
    
    # 汇总
    print("\n" + "=" * 70)
    print("测试结果汇总")
    print("=" * 70)
    print(f"  准确性测试: {results.get('准确性测试', 0):.1f}%")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
