# -*- coding: utf-8 -*-
"""验证 Life 日程页明确区分在床、实际睡眠和夜间清醒。"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET = REPO_ROOT / (
    "clients/frontend/aveline-android/android/app/src/main/java/"
    "com/aveline/ai/mobile/presentation/life/LifeScheduleTab.kt"
)


def main() -> int:
    source = TARGET.read_text(encoding="utf-8")
    checks = {
        "睡眠起止改为无歧义标签": (
            'MetricRow(label = "入睡时间"' in source
            and 'MetricRow(label = "起床时间"' in source
        ),
        "显示在床时长和实际睡眠": (
            'MetricRow(label = "在床时长"' in source
            and 'MetricRow(label = "实际睡眠"' in source
        ),
        "显示或推算夜间清醒": (
            "sleepStageAwakeMinutes" in source
            and "(span - actual).coerceAtLeast(0)" in source
            and 'MetricRow(label = "夜间清醒"' in source
        ),
        "解释实际睡眠的计算口径": (
            'text = "实际睡眠 = 浅睡 + 深睡 + REM，不含夜间清醒"' in source
        ),
        "低打扰关闭时不显示无效原因与结束时间": (
            "if (uiState.reducedModeActive)" in source
            and 'it != "none"' in source
        ),
        "不再用 N/A 表示缺失的睡眠起止": (
            'sleepTime ?: "暂无记录"' in source
            and 'wakeTime ?: "暂无记录"' in source
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    for name, passed in checks.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    if failed:
        print(f"验证失败，共 {len(failed)} 项")
        return 1
    print("Life 睡眠卡片展示验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
