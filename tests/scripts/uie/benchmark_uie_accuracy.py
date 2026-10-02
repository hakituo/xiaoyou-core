"""按期望文本评估UIE-mini各字段的实际抽取准确率。"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass


PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@dataclass(frozen=True)
class AccuracyCase:
    """单个字段抽取准确率样本。"""

    category: str
    field: str
    text: str
    expected: tuple[str, ...]


CASES = [
    AccuracyCase("起床时间", "起床时间", "我今天早上7点起的", ("早上7点",)),
    AccuracyCase("起床时间", "起床时间", "今天六点半就醒了", ("六点半",)),
    AccuracyCase("起床时间", "起床时间", "睡到上午9点才起来", ("上午9点",)),
    AccuracyCase(
        "起床时间",
        "起床时间",
        "晚上10点睡的，早上6点起的",
        ("早上6点",),
    ),
    AccuracyCase("睡觉时间", "睡觉时间", "昨晚11点半睡的", ("昨晚11点半",)),
    AccuracyCase("睡觉时间", "睡觉时间", "准备凌晨1点睡", ("凌晨1点",)),
    AccuracyCase("睡觉时间", "睡觉时间", "晚上十点就上床睡觉了", ("晚上十点",)),
    AccuracyCase(
        "睡觉时间",
        "睡觉时间",
        "晚上10点睡的，早上6点起的",
        ("晚上10点",),
    ),
    AccuracyCase("食物", "吃的食物", "刚吃了一碗面条", ("一碗面条", "面条")),
    AccuracyCase("食物", "吃的食物", "午饭吃了番茄炒蛋", ("番茄炒蛋",)),
    AccuracyCase("食物", "吃的食物", "下午啃了个苹果", ("苹果",)),
    AccuracyCase("食物", "吃的食物", "晚餐是牛肉盖饭", ("牛肉盖饭",)),
    AccuracyCase("餐次", "餐次", "早餐吃了面包", ("早餐",)),
    AccuracyCase("餐次", "餐次", "午饭吃了番茄炒蛋", ("午饭",)),
    AccuracyCase("餐次", "餐次", "晚餐是牛肉盖饭", ("晚餐",)),
    AccuracyCase("餐次", "餐次", "刚吃完夜宵", ("夜宵",)),
    AccuracyCase("学习内容", "学习内容", "刚复习了高数第三章", ("高数第三章",)),
    AccuracyCase("学习内容", "学习内容", "晚上背了二十个英语单词", ("英语单词",)),
    AccuracyCase(
        "学习内容",
        "学习内容",
        "看完了操作系统的进程调度",
        ("操作系统的进程调度", "进程调度"),
    ),
    AccuracyCase("学习内容", "学习内容", "练习了一套物理卷子", ("物理卷子",)),
    AccuracyCase("活动内容", "活动内容", "出门打了一场篮球", ("打了一场篮球", "篮球")),
    AccuracyCase(
        "活动内容",
        "活动内容",
        "傍晚沿着江边跑了五公里",
        ("沿着江边跑了五公里", "跑了五公里"),
    ),
    AccuracyCase("活动内容", "活动内容", "刚洗完澡", ("洗澡",)),
    AccuracyCase(
        "活动内容",
        "活动内容",
        "下午去超市买东西了",
        ("去超市买东西", "超市买东西"),
    ),
    AccuracyCase("健康症状", "健康症状", "今天有点头疼", ("头疼",)),
    AccuracyCase("健康症状", "健康症状", "胃有点不舒服", ("胃不舒服", "不舒服")),
    AccuracyCase("健康症状", "健康症状", "今天一直咳嗽", ("咳嗽",)),
    AccuracyCase(
        "健康症状",
        "健康症状",
        "太阳穴一跳一跳地疼",
        ("太阳穴一跳一跳地疼", "太阳穴疼"),
    ),
    AccuracyCase("情绪", "情绪", "心情有点郁闷", ("郁闷",)),
    AccuracyCase("情绪", "情绪", "今天特别开心", ("开心",)),
    AccuracyCase("情绪", "情绪", "想到明天考试有些焦虑", ("焦虑",)),
    AccuracyCase("情绪", "情绪", "整个人有点提不起劲", ("提不起劲",)),
]


def _canonical(text: str) -> str:
    """移除不影响字段语义的空白和标点。"""
    return re.sub(r"[\s，。！？、；：,.!?;:]", "", str(text or "")).lower()


def _is_expected(actual: str, expected_values: tuple[str, ...]) -> bool:
    """允许模型返回带时间修饰词或限定词的更长span。"""
    normalized_actual = _canonical(actual)
    return any(
        _canonical(expected) in normalized_actual
        for expected in expected_values
        if _canonical(expected)
    )


def main() -> int:
    """运行固定样本集并打印总体与分字段准确率。"""
    from core.services.data_ops.uie_extractor import get_uie_extractor

    extractor = get_uie_extractor()
    if not extractor._backend:
        print("[FAIL] UIE后端不可用")
        return 1

    stats: dict[str, list[int]] = {}
    correct = 0
    for index, case in enumerate(CASES, start=1):
        result = extractor.extract(case.text, [case.field])
        spans = result.get(case.field) or []
        actual_values = [str(span.get("text") or "") for span in spans]
        # 生产路径的 _uie_first_text 只使用第一个span，基准必须按相同语义计分。
        passed = bool(actual_values) and _is_expected(actual_values[0], case.expected)
        status = "PASS" if passed else ("WRONG" if actual_values else "MISS")
        stats.setdefault(case.category, [0, 0])
        stats[case.category][1] += 1
        if passed:
            correct += 1
            stats[case.category][0] += 1
        print(
            f"[{status}] {index:02d} {case.category} | {case.text} | "
            f"expected={case.expected} actual={actual_values}"
        )

    print("\n按字段统计:")
    for category, (category_correct, category_total) in stats.items():
        accuracy = category_correct / category_total * 100
        print(f"  {category}: {category_correct}/{category_total} ({accuracy:.1f}%)")

    overall_accuracy = correct / len(CASES) * 100
    print(f"\n总体准确率: {correct}/{len(CASES)} ({overall_accuracy:.1f}%)")
    print(f"backend={extractor._backend}")
    print(f"model_path={extractor._backend_model_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
