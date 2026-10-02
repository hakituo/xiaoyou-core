# -*- coding: utf-8 -*-
"""验证 Samsung Health 体成分读取口径：长窗口 + 每字段最近一次非空值。

回归背景：旧实现只查询最近 30 天、且只用最新一条记录取全部字段，
用户几个月前的体成分（三星健康里仍可见）会被整片过滤掉，
表现为 App 里"身体成分全是 N/A"。
"""

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
READER = SAMSUNG_DIR / "SamsungHealthReader.kt"
BODY_READER = SAMSUNG_DIR / "SamsungHealthBodyReader.kt"


def main() -> int:
    """执行静态回归检查。"""
    reader = READER.read_text(encoding="utf-8")
    body_reader = BODY_READER.read_text(encoding="utf-8")
    checks = {
        "体成分回溯窗口放宽到一年": (
            "BODY_COMPOSITION_LOOKBACK_DAYS = 365L" in body_reader
            and "now.minus(BODY_COMPOSITION_LOOKBACK_DAYS, ChronoUnit.DAYS)" in body_reader
        ),
        "体成分不再使用 30 天窗口": (
            "now.minus(30, ChronoUnit.DAYS)" not in body_reader.split("readBloodPressureField")[0]
        ),
        "每个字段取最近一次非空值": (
            "internal fun <T : Any> latestBodyCompositionValue(" in body_reader
            and "firstNotNullOfOrNull { it.getValue(field) }" in body_reader
            and "sortedByDescending { it.endTime }" in body_reader
        ),
        "体成分一次查询取回多条记录": (
            "setLimit(BODY_COMPOSITION_MAX_RECORDS)" in body_reader
            and "BODY_COMPOSITION_MAX_RECORDS = 200" in body_reader
        ),
        "门面两条读取路径共用同一取值口径": (
            "readBodyCompositionPoints(Instant.now())" in reader
            and "bodyReader.readBodyCompositionPoints(now)" in reader
            and reader.count("latestBodyCompositionValue(") >= 22
            and "readBodyCompositionField" not in reader
        ),
        "低频通道仍整体跳过体成分查询": (
            "val bodyComposition = if (includeBodyComposition) {" in reader
            and "} else {\n            emptyList()" in reader
        ),
        "读取失败留下可排查日志": (
            'Log.w(TAG, "读取身体成分失败: ${e.message}", e)' in body_reader
            and "体成分记录 ${points.size} 条" in body_reader
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
    print("Samsung Health 体成分读取口径验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
