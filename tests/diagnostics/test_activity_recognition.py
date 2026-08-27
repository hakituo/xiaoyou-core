"""
活动识别准确度测试脚本
测试规则引擎 + BERT 对各种生活场景的识别能力
包括：睡眠、起床、饮食、学习、活动、健康、心情
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.services.daily.extractor import ActivityExtractor
from memory.core.discourse import analyze_discourse, infer_state_event


# 测试用例：(输入文本, 期望结果, 说明)
TEST_CASES = [
    # ========== 睡眠场景 ==========
    ("晚安", "sleep", "晚安=睡觉"),
    ("我睡了", "sleep", "明确睡觉"),
    ("十一点睡", "sleep", "中文时间+睡"),
    ("23:30睡觉", "sleep", "HH:MM格式睡觉"),
    ("躺下了", "sleep", "躺下了"),
    ("困了", "sleep", "困了=要睡"),
    
    # ========== 起床场景 ==========
    ("我醒了", "wakeup", "明确起床"),
    ("早安", "wakeup", "早安=起床"),
    ("八点起床", "wakeup", "中文时间+起床"),
    ("10:30起床", "wakeup", "HH:MM格式起床"),
    ("自然醒", "wakeup", "自然醒"),
    ("被吵醒了", "wakeup", "被吵醒"),
    
    # ========== 饮食场景 ==========
    ("吃了早餐", "meal_breakfast", "吃了早餐"),
    ("吃早饭了", "meal_breakfast", "吃早饭了"),
    ("吃过早餐", "meal_breakfast", "吃过早餐"),
    ("吃了午饭", "meal_lunch", "吃了午饭"),
    ("吃午饭了", "meal_lunch", "吃午饭了"),
    ("吃了晚餐", "meal_dinner", "吃了晚餐"),
    ("吃晚饭了", "meal_dinner", "吃晚饭了"),
    ("吃了饭", "meal", "吃了饭（通用）"),
    ("刚吃完", "meal", "刚吃完"),
    ("正在吃饭", "meal", "正在吃饭"),
    ("喝了杯水", "drink", "喝了水"),
    ("喝水了", "drink", "喝水了"),
    
    # ========== 学习场景 ==========
    ("学习了", "study", "学习了"),
    ("复习了", "study", "复习了"),
    ("背了单词", "study", "背了单词"),
    ("看了书", "study", "看了书"),
    ("做了作业", "study", "做了作业"),
    ("写代码", "study", "写代码"),
    ("学了英语", "study", "学了英语"),
    ("刷题了", "study", "刷题了"),
    
    # ========== 活动场景 ==========
    ("出门了", "activity", "出门了"),
    ("去玩了", "activity", "去玩了"),
    ("打游戏", "activity", "打游戏"),
    ("看了电影", "activity", "看了电影"),
    ("运动了", "activity", "运动了"),
    ("健身了", "activity", "健身了"),
    ("逛街了", "activity", "逛街了"),
    
    # ========== 健康场景 ==========
    ("头疼", "health", "头疼"),
    ("发烧了", "health", "发烧了"),
    ("肚子痛", "health", "肚子痛"),
    ("感冒了", "health", "感冒了"),
    ("不舒服", "health", "不舒服"),
    ("咳嗽了", "health", "咳嗽了"),
    ("胃疼", "health", "胃疼"),
    
    # ========== 心情场景 ==========
    ("心情好", "mood", "心情好"),
    ("心情不好", "mood", "心情不好"),
    ("开心", "mood", "开心"),
    ("难过", "mood", "难过"),
    ("焦虑", "mood", "焦虑"),
    ("生气", "mood", "生气"),
    ("郁闷", "mood", "郁闷"),
    
    # ========== 误识别防护 ==========
    ("八点半吃早饭", "meal_breakfast", "八点半吃早饭"),
    ("下午三点开会", "none", "开会不是活动记录"),
    ("今天天气不错", "none", "天气话题"),
    ("你好", "none", "普通打招呼"),
    ("", "none", "空字符串"),
]


def test_recognition_logic(text: str) -> str:
    """测试识别逻辑，不实际记录数据"""
    extractor = ActivityExtractor()
    
    # 测试睡眠/起床（不需要 self_report 检查）
    if extractor._looks_like_wakeup(text):
        return "wakeup"
    if extractor._looks_like_sleep(text):
        return "sleep"
    
    # 检查是否是 self_report（模拟 _apply_fast_record 的逻辑）
    if not extractor._is_self_report(text):
        return "none"
    
    # 测试 discourse 分析
    discourse = analyze_discourse(text)
    state_event = infer_state_event(text, discourse)
    
    if state_event == "WAKEUP_NOW":
        return "wakeup"
    elif state_event == "SLEEP_NOW":
        return "sleep"
    elif state_event == "DRINK_NOW":
        return "drink"
    elif state_event == "MEAL_NOW":
        # 进一步判断餐食类型
        raw = text.lower()
        if "早餐" in text or "早饭" in text:
            return "meal_breakfast"
        elif "午餐" in text or "午饭" in text:
            return "meal_lunch"
        elif "晚餐" in text or "晚饭" in text:
            return "meal_dinner"
        return "meal"
    elif state_event == "STUDY_NOW":
        return "study"
    elif state_event == "ACTIVITY_NOW":
        return "activity"
    elif state_event == "HEALTH_NOW":
        return "health"
    elif state_event == "MOOD_NOW":
        return "mood"
    
    # 测试 BERT 意图识别
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
            elif intent == "RECORD_MEAL":
                raw = text.lower()
                if "早餐" in text or "早饭" in text:
                    return "meal_breakfast"
                elif "午餐" in text or "午饭" in text:
                    return "meal_lunch"
                elif "晚餐" in text or "晚饭" in text:
                    return "meal_dinner"
                elif "喝" in text:
                    return "drink"
                return "meal"
            elif intent == "RECORD_STUDY":
                return "study"
            elif intent == "RECORD_ACTIVITY":
                return "activity"
            elif intent == "RECORD_HEALTH":
                return "health"
            elif intent == "RECORD_MOOD":
                return "mood"
    except Exception:
        pass
    
    return "none"


def test_recognition():
    """测试识别准确度"""
    print("=" * 80)
    print("活动识别准确度测试（纯逻辑测试，不记录数据）")
    print("=" * 80)
    print()
    
    correct = 0
    total = len(TEST_CASES)
    failed_cases = []
    category_stats = {}
    
    for text, expected, description in TEST_CASES:
        # 测试识别
        actual = test_recognition_logic(text)
        
        # 统计分类
        category = expected.split("_")[0] if "_" in expected else expected
        if category not in category_stats:
            category_stats[category] = {"total": 0, "correct": 0}
        category_stats[category]["total"] += 1
        
        # 检查是否正确
        if expected == "none":
            is_correct = actual == "none"
        elif "_" in expected:
            # 精确匹配（如 meal_breakfast）
            is_correct = actual == expected
        else:
            # 模糊匹配（如 meal 匹配 meal_breakfast）
            is_correct = actual == expected or actual.startswith(expected)
        
        if is_correct:
            correct += 1
            category_stats[category]["correct"] += 1
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
    
    print("\n分类统计:")
    print("-" * 40)
    for category, stats in sorted(category_stats.items()):
        rate = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
        print(f"  {category}: {stats['correct']}/{stats['total']} ({rate:.0f}%)")
    
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
