#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
情绪检测器测试脚本
"""

import sys
from pathlib import Path

# 确保项目根目录在 path 中
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from core.emotion import get_emotion_detector_smart, get_emotion_manager
from core.emotion.constants import EMOTION_CN_MAP


TEST_CASES = [
    # 积极情绪
    ("今天好开心啊 😄", "happy"),
    ("太高兴了！终于完成了！", "happy"),
    ("好兴奋好期待 🤩", "excited"),
    
    # 消极情绪
    ("好难过啊，好伤心 😭", "sad"),
    ("气死我了！太气人了！", "angry"),
    ("好焦虑好紧张，怎么办啊", "anxious"),
    
    # 其他情绪
    ("好累好困啊，想睡觉 💤", "tired"),
    ("好害羞不好意思 😳", "shy"),
    ("好孤独好寂寞 😔", "lonely"),
    ("好害怕吓死我了 😱", "fear"),
    ("好委屈太冤枉了 🥺", "wronged"),
    ("好嘛好嘛，人家想 👉👈", "coquetry"),
    ("好迷茫不知道怎么办 😕", "lost"),
    
    # 否定词测试
    ("今天不开心", "sad"),
    ("我没生气哦", "neutral"),
    ("别难过了", "neutral"),
    
    # 中性
    ("嗯好的，知道了", "neutral"),
    ("挺好的，还行吧", "neutral"),
]


def test_emotion_detector():
    """测试智能情绪检测器"""
    print("=" * 60)
    print("测试智能情绪检测器")
    print("=" * 60)
    
    try:
        detector = get_emotion_detector_smart()
        print("✅ 检测器加载成功\n")
    except Exception as e:
        print(f"❌ 检测器加载失败: {e}")
        return
    
    correct = 0
    total = len(TEST_CASES)
    
    for text, expected in TEST_CASES:
        state = detector.detect(text)
        primary = state.primary_emotion.value
        confidence = state.confidence
        source = state.source
        
        is_correct = primary == expected or primary in expected
        if is_correct:
            correct += 1
        
        status = "✅" if is_correct else "❌"
        print(f"{status} '{text}'")
        print(f"   预测: {primary} ({confidence:.2%}), 来源: {source}")
        if state.sub_emotions:
            sub_str = ", ".join([f"{k}: {v:.2f}" for k, v in list(state.sub_emotions.items())[:3]])
            print(f"   子情绪: {sub_str}")
        print()
    
    print("-" * 60)
    print(f"准确率: {correct}/{total} = {correct/total*100:.1f}%\n")


def test_emotion_manager():
    """测试情绪管理器（带衰减+持久化"""
    print("\n" + "=" * 60)
    print("测试情绪管理器")
    print("=" * 60)
    
    try:
        manager = get_emotion_manager()
        print("✅ 管理器加载成功\n")
    except Exception as e:
        print(f"❌ 管理器加载失败: {e}")
        return
    
    user_id = "test_user_001"
    
    test_messages = [
        "今天好开心啊 😄",
        "刚才有点难过",
        "现在好累想睡觉 💤",
    ]
    
    for i, text in enumerate(test_messages):
        state = manager.process_text(user_id, text)
        print(f"[{i+1}] 输入: {text}")
        print(f"      情绪: {state.primary_emotion.value} ({state.confidence:.2%})")
        print(f"      强度: {state.intensity:.2f}")
        print()
    
    effective = manager.get_effective_state(user_id)
    print("📊 最终有效状态:")
    print(f"   情绪: {effective.primary_emotion.value}")
    print(f"   强度: {effective.intensity:.2f}")
    print(f"   子情绪: {effective.sub_emotions}")


def test_emotion_manager_fallback():
    """测试回退到 legacy 模式"""
    print("\n" + "=" * 60)
    print("测试 Legacy 模式（LLM 标签提取）")
    print("=" * 60)
    
    from core.emotion import EmotionManager
    
    manager = EmotionManager({"detector_mode": "legacy"})
    test_texts = [
        "[EMO: sad] 好难过",
        "[开心] 今天好开心",
        "没有标签，应该返回 neutral",
    ]
    
    for text in test_texts:
        state = manager.detector.detect(text)
        print(f"输入: {text}")
        print(f"预测: {state.primary_emotion.value} ({state.confidence:.2%})\n")


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # 测试1: 智能检测器
    test_emotion_detector()
    
    # 测试2: 情绪管理器
    test_emotion_manager()
    
    # 测试3: Legacy 模式
    test_emotion_manager_fallback()
    
    print("\n🎉 所有测试完成！")
