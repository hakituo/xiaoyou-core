"""验证学习模式上下文连续性与退出后收束行为。

运行：
    venv_core\\Scripts\\python.exe tests/scripts/study/verify_study_context_continuity.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# 直接以脚本方式运行时 sys.path[0] 是脚本所在目录，需手动挂上项目根；
# core.* 的导入因此推迟到函数内（与 prompt_cache 下的同类脚本一致）。
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def _settings():
    budget = SimpleNamespace(
        cloud_max_history_messages=30,
        cloud_max_history_chars=3000,
        study_active_recent_window=20,
        study_active_cloud_max_history_chars=18000,
    )
    return SimpleNamespace(chat=SimpleNamespace(context_budget=budget))


def main() -> None:
    from core.agents.chat_agent_components.context_budget.budget_apply import (
        apply_cloud_history_budget,
    )
    from core.agents.chat_agent_components.context_budget.history_compression import (
        compress_study_session_messages,
    )

    history = [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"学习链-{i}",
            "category": "learning",
            "timestamp": 100 + i,
        }
        for i in range(30)
    ]

    with patch("config.integrated_config.get_settings", return_value=_settings()):
        cloud_history = apply_cloud_history_budget(history, "B")
    # 时间锚点下学习窗口会回退到锚点块首（本例时间戳全部落在同一个 300 秒
    # 块内，回退到 quantize 上限后取到全部 30 条）；窗口必须是连续尾部，
    # 且最近 20 条工作记忆完整包含在窗内。
    assert 19 <= len(cloud_history) <= 30, (
        f"学习窗口 {len(cloud_history)} 条，超出 [19, 30]"
    )
    assert [m["content"] for m in cloud_history] == [
        m["content"] for m in history[-len(cloud_history):]
    ]
    assert [m["content"] for m in cloud_history[-20:]] == [
        m["content"] for m in history[-20:]
    ]

    finished = compress_study_session_messages(
        [
            {"role": "user", "content": "普通聊天", "timestamp": 90},
            {
                "role": "user",
                "content": "为什么 F=-kx 有负号？",
                "timestamp": 100,
                "category": "learning",
            },
            {
                "role": "assistant",
                "content": "负号表示回复力方向与位移方向相反。" * 5,
                "timestamp": 101,
                "category": "learning",
            },
            {
                "role": "user",
                "content": "所以它总指向平衡位置？",
                "timestamp": 102,
                "category": "learning",
            },
            {"role": "user", "content": "先休息", "timestamp": 110},
        ],
        force=True,
        session_start_ts=100,
        session_end_ts=102,
        max_summary_chars=1200,
    )
    assert finished[0]["content"] == "普通聊天"
    assert finished[-1]["content"] == "先休息"
    assert any("[学习会话摘要]" in m["content"] for m in finished)
    assert any("平衡位置" in m["content"] for m in finished)

    print("OK: 学习进行中保留连续工作窗口（≥最近20条，时间锚点生效），退出后仅压缩已结束学习会话。")


if __name__ == "__main__":
    main()
