"""
睡眠/起床识别准确度测试脚本
测试规则引擎 + BERT 对各种表达方式的识别能力
"""
import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.services.daily.extractor import ActivityExtractor
from core.services.daily.manager import get_daily_manager
from memory.core.discourse import analyze_discourse, infer_state_event


# 测试用例：(输入文本, 期望结果, 说明)
TEST_CASES = [
    # === 起床场景 ===
    ("我醒了", "wakeup", "明确起床"),
    ("起床了", "wakeup", "明确起床"),
    ("刚睡醒", "wakeup", "明确起床"),
    ("早安", "wakeup", "早安=起床"),
    ("早上好", "wakeup", "早上好=起床"),
    ("我起了", "wakeup", "口语化起床"),
    ("自然醒", "wakeup", "自然醒"),
    ("被吵醒了", "wakeup", "被吵醒"),
    ("睡醒了", "wakeup", "睡醒了"),
    ("醒来", "wakeup", "醒来"),
    
    # === 睡觉场景 ===
    ("晚安", "sleep", "晚安=睡觉"),
    ("我睡了", "sleep", "明确睡觉"),
    ("去睡了", "sleep", "去睡觉"),
    ("先睡了", "sleep", "先睡了"),
    ("要睡了", "sleep", "要睡觉"),
    ("困了", "sleep", "困了=要睡"),
    ("准备睡了", "sleep", "准备睡觉"),
    ("睡觉了", "sleep", "睡觉了"),
    ("躺下了", "sleep", "躺下了"),
    
    # === 带时间的起床 ===
    ("八点起床", "wakeup", "中文时间+起床"),
    ("8点起", "wakeup", "数字时间+起"),
    ("九点半醒了", "wakeup", "中文时间+醒了"),
    ("早上七点醒的", "wakeup", "早上+时间+醒"),
    ("10:30起床", "wakeup", "HH:MM格式起床"),
    
    # === 带时间的睡觉 ===
    ("十一点睡", "sleep", "中文时间+睡"),
    ("11点睡觉", "sleep", "数字时间+睡觉"),
    ("凌晨两点睡的", "sleep", "凌晨+时间+睡"),
    ("23:30睡觉", "sleep", "HH:MM格式睡觉"),
    ("晚上十二点睡", "sleep", "晚上+时间+睡"),
    
    # === 容易误识别的场景 ===
    ("八点半吃早饭", "none", "吃饭不是睡觉"),
    ("四点零二分吃了早饭", "none", "吃饭不是睡觉"),
    ("下午三点开会", "none", "开会不是睡觉"),
    ("晚上十点打游戏", "none", "打游戏不是睡觉"),
    ("今天学习了三小时", "none", "学习不是睡觉"),
    ("喝了杯水", "none", "喝水不是睡觉"),
    ("头疼", "none", "健康问题不是睡觉"),
    ("心情不好", "none", "心情不是睡觉"),
    
    # === 复杂场景 ===
    ("昨晚三点才睡，今早十点才醒", "sleep_wakeup", "包含睡和起"),
    ("睡到自然醒", "wakeup", "睡到自然醒=起床"),
    ("昨晚失眠了", "none", "失眠不是正常睡觉"),
    ("没睡好", "none", "没睡好不是记录睡觉"),
    
    # === 边界场景 ===
    ("", "none", "空字符串"),
    ("你好", "none", "普通打招呼"),
    ("今天天气不错", "none", "天气话题"),
]


def test_recognition_logic(text: str) -> str:
    """测试识别逻辑，不实际记录数据"""
    extractor = ActivityExtractor()
    
    # 测试 _looks_like_wakeup
    if extractor._looks_like_wakeup(text):
        return "wakeup"
    
    # 测试 _looks_like_sleep
    if extractor._looks_like_sleep(text):
        return "sleep"
    
    # 测试 discourse 分析
    discourse = analyze_discourse(text)
    state_event = infer_state_event(text, discourse)
    
    if state_event == "WAKEUP_NOW":
        return "wakeup"
    elif state_event == "SLEEP_NOW":
        return "sleep"
    
    # 测试 BERT 意图识别（只分析，不记录）
    try:
        from core.services.data_ops.bert_analyzer import get_bert_analyzer
        analyzer = get_bert_analyzer()
        result = analyzer.analyze(text)
        intent = str((result or {}).get("intent") or "NONE").upper()
        conf = float((result or {}).get("confidence") or 0.0)
        
        if conf >= 0.75:
            if intent == "RECORD_WAKEUP":
                return "wakeup"
            elif intent == "RECORD_SLEEP":
                return "sleep"
    except Exception:
        pass
    
    return "none"


def test_recognition():
    """测试识别准确度"""
    print("=" * 80)
    print("睡眠/起床识别准确度测试（纯逻辑测试，不记录数据）")
    print("=" * 80)
    print()
    
    correct = 0
    total = len(TEST_CASES)
    failed_cases = []
    
    for text, expected, description in TEST_CASES:
        # 测试识别
        actual = test_recognition_logic(text)
        
        # 检查是否正确
        if expected == "sleep_wakeup":
            is_correct = actual in ["sleep", "wakeup"]
        elif expected == "none":
            is_correct = actual == "none"
        else:
            is_correct = actual == expected
        
        if is_correct:
            correct += 1
            status = "✓"
        else:
            status = "✗"
            failed_cases.append((text, expected, actual, description))
        
        # 打印结果
        print(f"{status} [{description}]")
        print(f"   输入: {text}")
        print(f"   期望: {expected}, 实际: {actual}")
        print()
    
    # 打印统计
    print("=" * 80)
    print(f"测试结果: {correct}/{total} 通过 ({correct/total*100:.1f}%)")
    print("=" * 80)
    
    if failed_cases:
        print("\n失败的用例:")
        print("-" * 80)
        for text, expected, actual, description in failed_cases:
            print(f"✗ [{description}]")
            print(f"   输入: {text}")
            print(f"   期望: {expected}, 实际: {actual}")
            print()
    
    return correct, total, failed_cases


if __name__ == "__main__":
    correct, total, failed = test_recognition()
    sys.exit(0 if correct == total else 1)
