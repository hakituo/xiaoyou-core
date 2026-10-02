#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
情绪检测器误导性测试
测试关键词检测的局限性和 BERT 的语义理解能力
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


TRICKY_TEST_CASES = [
    # === 反讽/讽刺 ===
    ("你可真厉害啊", "neutral", "反讽：表面夸奖，实际讽刺"),
    ("呵呵，真棒", "neutral", "讽刺：呵呵表示不屑"),
    ("行行行，你说的都对", "angry", "敷衍/不耐烦"),
    ("太棒了，我又搞砸了", "sad", "自嘲：表面积极词，实际消极"),
    
    # === 否定词 ===
    ("我不开心", "sad", "否定：不开心 = 难过"),
    ("我没有生气", "neutral", "否定：没生气 = 中性"),
    ("不是很难过", "neutral", "否定：不是难过 = 中性"),
    ("别难过了", "neutral", "劝慰：别难过"),
    
    # === 复杂情绪 ===
    ("好开心但又有点难过", "happy", "混合情绪：开心+难过"),
    ("生气但又委屈", "angry", "混合情绪：生气+委屈"),
    ("又累又困又难过", "tired", "多重消极情绪"),
    
    # === 上下文依赖 ===
    ("今天真是...呵呵", "neutral", "省略号+呵呵：无语/讽刺"),
    ("我没事", "neutral", "口是心非：可能难过，但文字看不出"),
    ("算了", "neutral", "无奈/放弃"),
    ("无所谓了", "neutral", "不在乎"),
    
    # === 程度词 ===
    ("有点难过", "sad", "程度：有点 = 弱"),
    ("超级超级开心", "happy", "程度：超级 = 强"),
    ("稍微有点累", "tired", "程度：稍微 = 很弱"),
    
    # === 网络用语 ===
    ("emo了", "sad", "网络用语：emo = 难过/抑郁"),
    ("破防了", "sad", "网络用语：破防 = 崩溃"),
    ("yyds", "happy", "网络用语：永远的神 = 赞美"),
    ("无语死了", "angry", "网络用语：无语 = 烦躁"),
    ("笑死", "happy", "网络用语：很好笑"),
    
    # === Emoji 组合 ===
    ("😭🙏", "sad", "Emoji：感动/感谢到哭"),
    ("😅", "neutral", "Emoji：尴尬/无奈"),
    ("🥲", "sad", "Emoji：苦笑/感动"),
    
    # === 隐晦表达 ===
    ("今天天气真好", "neutral", "无情绪：纯描述"),
    ("我饿了", "neutral", "生理需求：无情绪"),
    ("...", "neutral", "省略号：无语/沉默"),
    ("好的", "neutral", "简单回复"),
    
    # === 对比测试 ===
    ("开心", "happy", "简单：开心"),
    ("好开心", "happy", "程度词：好开心"),
    ("今天好开心", "happy", "完整句：今天好开心"),
    ("我今天真的好开心啊", "happy", "完整句+程度：真的很开心"),
]


def test_tricky_cases():
    """测试误导性输入"""
    print("=" * 70)
    print("情绪检测器误导性测试")
    print("=" * 70)
    
    try:
        from core.emotion import get_emotion_detector_smart
        detector = get_emotion_detector_smart()
        print("✅ 检测器加载成功\n")
    except Exception as e:
        print(f"❌ 检测器加载失败: {e}")
        return
    
    correct = 0
    total = len(TRICKY_TEST_CASES)
    failed_cases = []
    
    for text, expected, description in TRICKY_TEST_CASES:
        state = detector.detect(text)
        primary = state.primary_emotion.value
        confidence = state.confidence
        source = state.source
        
        is_correct = primary == expected
        if is_correct:
            correct += 1
        else:
            failed_cases.append((text, expected, primary, description))
        
        status = "✅" if is_correct else "❌"
        print(f"{status} '{text}'")
        print(f"   预期: {expected} | 实际: {primary} ({confidence:.2%}) | 来源: {source}")
        print(f"   说明: {description}")
        if state.sub_emotions and len(state.sub_emotions) > 1:
            sub_str = ", ".join([f"{k}: {v:.2f}" for k, v in list(state.sub_emotions.items())[:3]])
            print(f"   子情绪: {sub_str}")
        print()
    
    print("-" * 70)
    print(f"准确率: {correct}/{total} = {correct/total*100:.1f}%")
    print()
    
    if failed_cases:
        print("=" * 70)
        print("❌ 失败案例分析:")
        print("=" * 70)
        for text, expected, actual, desc in failed_cases:
            print(f"输入: '{text}'")
            print(f"预期: {expected} | 实际: {actual}")
            print(f"说明: {desc}")
            print()


def test_multi_emotion():
    """测试多情绪分布计算"""
    print("\n" + "=" * 70)
    print("多情绪分布计算详解")
    print("=" * 70)
    
    try:
        from core.emotion import get_emotion_detector_smart
        detector = get_emotion_detector_smart()
    except Exception as e:
        print(f"❌ 检测器加载失败: {e}")
        return
    
    test_texts = [
        "好开心但又有点难过",
        "又累又困又难过",
        "生气但又委屈",
        "好焦虑好紧张好害怕",
    ]
    
    for text in test_texts:
        print(f"\n输入: '{text}'")
        print("-" * 50)
        
        # 获取 Fast Path 结果
        fast_scores = detector.detect_fast_path(text)
        if fast_scores:
            print("Fast Path (关键词):")
            sorted_fast = sorted(fast_scores.items(), key=lambda x: -x[1])[:5]
            for emo, score in sorted_fast:
                if score > 0.01:
                    print(f"  {emo}: {score:.2%}")
        
        # 获取 BERT Path 结果
        bert_scores = detector.detect_bert_path(text)
        if bert_scores:
            print("BERT Path (语义):")
            sorted_bert = sorted(bert_scores.items(), key=lambda x: -x[1])[:5]
            for emo, score in sorted_bert:
                if score > 0.01:
                    print(f"  {emo}: {score:.2%}")
        
        # 获取融合结果
        state = detector.detect(text)
        print(f"融合结果 (主导: {state.primary_emotion.value}, 来源: {state.source}):")
        sorted_final = sorted(state.sub_emotions.items(), key=lambda x: -x[1])
        for emo, score in sorted_final:
            if score > 0.01:
                print(f"  {emo}: {score:.2%}")


def test_keyword_limitations():
    """展示关键词检测的局限性"""
    print("\n" + "=" * 70)
    print("关键词检测的局限性演示")
    print("=" * 70)
    
    try:
        from core.emotion import get_emotion_detector_smart
        detector = get_emotion_detector_smart()
    except Exception as e:
        print(f"❌ 检测器加载失败: {e}")
        return
    
    limitations = [
        ("我今天心情不太好", "sad", "关键词匹配不到'不太好'"),
        ("心里有点堵", "sad", "隐喻：'堵'表示难过，但关键词没有"),
        ("感觉空落落的", "lost", "隐喻：'空落落'表示失落"),
        ("想哭", "sad", "简单但关键词可能没有"),
        ("笑不出来", "sad", "否定表达：笑不出来 = 难过"),
        ("烦死了", "angry", "口语：烦 = 生气/烦躁"),
        ("无语", "angry", "口语：无语 = 烦躁"),
    ]
    
    print("\n这些是关键词检测可能失败的情况：\n")
    for text, expected, reason in limitations:
        state = detector.detect(text)
        primary = state.primary_emotion.value
        status = "✅" if primary == expected else "❌"
        print(f"{status} '{text}'")
        print(f"   预期: {expected} | 实际: {primary} | 原因: {reason}")
        print()


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)
    
    # 测试1: 误导性输入
    test_tricky_cases()
    
    # 测试2: 多情绪分布
    test_multi_emotion()
    
    # 测试3: 关键词局限性
    test_keyword_limitations()
    
    print("\n🎉 测试完成！")
