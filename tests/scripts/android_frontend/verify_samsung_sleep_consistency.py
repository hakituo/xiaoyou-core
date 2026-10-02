# -*- coding: utf-8 -*-
"""验证 Samsung Health 睡眠会话、时长和得分使用一致的数据口径。"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SAMSUNG_DIR = (
    REPO_ROOT
    / "clients"
    / "frontend"
    / "aveline-android"
    / "android"
    / "app"
    / "src"
    / "main"
    / "java"
    / "com"
    / "aveline"
    / "ai"
    / "mobile"
    / "data"
    / "samsung"
)
# 读取门面(负责调用睡眠读取器组装快照)
READER = SAMSUNG_DIR / "SamsungHealthReader.kt"
# 睡眠口径实现(记录选择与阶段合并)
SLEEP_READER = SAMSUNG_DIR / "SamsungHealthSleepReader.kt"
UNIT_TEST = (
    REPO_ROOT
    / "clients"
    / "frontend"
    / "aveline-android"
    / "android"
    / "app"
    / "src"
    / "test"
    / "java"
    / "com"
    / "aveline"
    / "ai"
    / "mobile"
    / "data"
    / "samsung"
    / "SamsungSleepSelectionTest.kt"
)


def main() -> int:
    """执行静态回归检查。"""
    reader = READER.read_text(encoding="utf-8")
    sleep_reader = SLEEP_READER.read_text(encoding="utf-8")
    unit_test = UNIT_TEST.read_text(encoding="utf-8")
    checks = {
        "使用正序比较器配合 max 选择最新结束记录": (
            "compareBy<Int> { windows[it].endTime }" in sleep_reader
            and "compareByDescending<SleepSession>" not in sleep_reader
        ),
        "睡眠得分来自所选睡眠记录": (
            "score = selectedRecord.score" in sleep_reader
            and "sleepScore = sleepSessions?.score" in reader
            and "private suspend fun readSleepScore" not in sleep_reader
        ),
        "同一睡眠记录的全部子 session 被合并": (
            "val stages = selectedRecord.sessions.flatMap" in sleep_reader
            and "startTime = selectedRecord.startTime" in sleep_reader
            and "endTime = selectedRecord.endTime" in sleep_reader
        ),
        "实际睡眠仅累计浅睡深睡和 REM": (
            "val actualSleepMinutes = sumDurationsInWholeMinutes" in sleep_reader
            and "StageType.LIGHT ||" in sleep_reader
            and "StageType.DEEP ||" in sleep_reader
            and "StageType.REM" in sleep_reader
        ),
        "存在多会话和阶段取整回归测试": (
            "多条有效会话应选择结束时间最新的一条" in unit_test
            and "实际睡眠应先合并阶段时长再按整分钟取整" in unit_test
        ),
    }

    failed = []
    for name, passed in checks.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
        if not passed:
            failed.append(name)

    if failed:
        print(f"验证失败，共 {len(failed)} 项")
        return 1
    print("Samsung Health 睡眠一致性验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
