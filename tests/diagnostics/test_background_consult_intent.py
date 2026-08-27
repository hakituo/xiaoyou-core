#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试后台商量意图检测功能
验证当角色说"去找Ling商量一下"时，系统是否真的会触发后台协商
"""

import asyncio
import sys
import os

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

from core.services.data_ops.bert_analyzer import get_bert_analyzer


def test_background_consult_intent_detection():
    """测试BERT意图检测是否能识别'后台商量'意图"""
    print("=" * 60)
    print("测试1: BERT意图检测 - '后台商量'意图识别")
    print("=" * 60)
    
    bert_analyzer = get_bert_analyzer()
    
    test_cases = [
        ("去找Ling商量一下", True),
        ("问问Ling这个怎么办", True),
        ("我和Ling讨论讨论", True),
        ("让后台看看这个问题", True),
        ("我去问问Ling的意见", True),
        ("今天天气不错", False),
        ("随便聊聊", False),
        ("你好", False),
    ]
    
    passed = 0
    failed = 0
    
    for text, should_detect in test_cases:
        result = bert_analyzer.analyze_intent(
            text,
            candidates=["BACKGROUND_CONSULT", "NONE"]
        )
        intent = result.get("intent", "NONE")
        confidence = result.get("confidence", 0.0)
        
        detected = (intent == "BACKGROUND_CONSULT")
        is_correct = (detected == should_detect)
        
        status = "✓ PASS" if is_correct else "✗ FAIL"
        print(f"\n{status} | 输入: '{text}'")
        print(f"  意图: {intent} (置信度: {confidence:.2f})")
        print(f"  预期: {'应检测到' if should_detect else '不应检测到'}")
        print(f"  实际: {'检测到' if detected else '未检测到'}")
        
        if is_correct:
            passed += 1
        else:
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
    
    return failed == 0


def test_intent_examples():
    """测试所有定义的意图示例"""
    print("\n" + "=" * 60)
    print("测试2: 意图示例覆盖测试")
    print("=" * 60)
    
    bert_analyzer = get_bert_analyzer()
    
    examples = [
        "去找Ling商量一下",
        "问问Ling",
        "和Ling讨论一下",
        "找Ling问问",
        "让Ling看看",
        "我去问问Ling",
        "找后台商量一下",
        "问问后台",
    ]
    
    print("\n测试意图示例:")
    for example in examples:
        result = bert_analyzer.analyze_intent(
            example,
            candidates=["BACKGROUND_CONSULT", "NONE"]
        )
        intent = result.get("intent", "NONE")
        confidence = result.get("confidence", 0.0)
        
        status = "✓" if intent == "BACKGROUND_CONSULT" else "✗"
        print(f"  {status} '{example}' -> {intent} ({confidence:.2f})")


def test_confidence_threshold():
    """测试置信度阈值"""
    print("\n" + "=" * 60)
    print("测试3: 置信度阈值测试")
    print("=" * 60)
    
    bert_analyzer = get_bert_analyzer()
    
    threshold = 0.55
    
    test_texts = [
        "去找Ling商量一下",
        "问问Ling",
        "今天天气不错",
    ]
    
    print(f"\n当前阈值: {threshold}")
    print("\n测试结果:")
    for text in test_texts:
        result = bert_analyzer.analyze_intent(
            text,
            candidates=["BACKGROUND_CONSULT", "NONE"]
        )
        intent = result.get("intent", "NONE")
        confidence = result.get("confidence", 0.0)
        
        would_trigger = (intent == "BACKGROUND_CONSULT" and confidence >= threshold)
        
        print(f"\n  输入: '{text}'")
        print(f"  意图: {intent}")
        print(f"  置信度: {confidence:.2f}")
        print(f"  会触发后台协商: {'是' if would_trigger else '否'}")


def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("后台商量意图检测功能测试")
    print("=" * 60)
    
    all_passed = True
    
    all_passed &= test_background_consult_intent_detection()
    test_intent_examples()
    test_confidence_threshold()
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ 所有测试通过！")
    else:
        print("✗ 部分测试失败")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())
