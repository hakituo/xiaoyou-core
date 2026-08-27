"""测试strip_emojis_from_text方法"""

import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.services.active_care.core.history_processor import HistoryProcessor


def main():
    processor = HistoryProcessor()

    # 测试中文内容
    test_cases = [
        "我刚洗完澡",
        "洗完澡清爽多了吧",
        "嗯嗯",
        "蚊子包涂花露水了没？",
        "早~ 在忙啥呀？",
        "Hello World",
        "你好👋",
    ]

    print("=" * 60)
    print("测试 strip_emojis_from_text 方法")
    print("=" * 60)

    for text in test_cases:
        result = processor.strip_emojis_from_text(text)
        print(f"原文: {text}")
        print(f"结果: {result}")
        print(f"是否为空: {not result}")
        print("-" * 40)


if __name__ == "__main__":
    main()
