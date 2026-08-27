"""查看Active Care实际生成的prompt"""

import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.services.active_care.prompt.prompt_builder import build_active_care_prompt
from core.services.active_care.core.history_processor import HistoryProcessor


def main():
    # 模拟一个典型的聊天历史
    history_msgs = [
        {"role": "user", "content": "我刚洗完澡", "timestamp": 1781900000},
        {"role": "assistant", "content": "洗完澡清爽多了吧", "timestamp": 1781900010},  # 主程序回复
        {"role": "user", "content": "嗯嗯", "timestamp": 1781900030},
        {"role": "assistant", "content": "蚊子包涂花露水了没？", "timestamp": 1781900040},  # 主程序回复
    ]

    processor = HistoryProcessor()
    recent_history_text, last_user_message = processor.build_recent_history_text(
        history_msgs, now_ts=1781900200
    )

    print("=" * 60)
    print("Active Care 看到的历史记录:")
    print("=" * 60)
    print(recent_history_text)
    print("=" * 60)

    # 构建prompt
    result = build_active_care_prompt(
        sys_prompt_type="checking",
        user_input_mock="[ACTIVE_CARE_TRIGGER]",
        reminder_msg=None,
        thought="用户刚洗完澡，可以关心一下",
        tod="evening",
        now=1781900200,
        user_display_name="主人",
        persona_prompt="你是Aveline，一个傲娇的AI助手。",
        recent_history_text=recent_history_text,
        preferred_language="zh",
        elapsed_seconds=600,  # 10分钟
    )

    print("\n" + "=" * 60)
    print("Active Care 的 System Prompt (静态部分):")
    print("=" * 60)
    print(result.static_prompt[:2000])
    print("\n" + "=" * 60)
    print("Active Care 的 User Prompt (动态部分):")
    print("=" * 60)
    print(result.dynamic_prompt[:2000])


if __name__ == "__main__":
    main()
