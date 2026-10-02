# -*- coding: utf-8 -*-
"""验证 Samsung Health 读取器已按职责解耦且接线完整。

回归背景：SamsungHealthReader.kt 曾达到 1089 行，同时承担权限请求、11 类数据读取、
快照组装和睡眠/体成分算法，任何一处改动都要在千行文件里定位。
现拆为门面 + 6 个领域读取器 + 共享查询辅助。
"""

from __future__ import annotations

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
APP_MODULE = (
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
    / "di"
    / "AppModule.kt"
)
FACADE_NAME = "SamsungHealthReader.kt"
FACADE_MAX_LINES = 300
COLLABORATOR_MAX_LINES = 260
COLLABORATORS = {
    "SamsungHealthPermissions.kt": "class SamsungHealthPermissions",
    "SamsungHealthQuerySupport.kt": "internal suspend fun <T : Any> readLocalTimeAggregate",
    "SamsungHealthVitalsReader.kt": "class SamsungHealthVitalsReader",
    "SamsungHealthBodyReader.kt": "class SamsungHealthBodyReader",
    "SamsungHealthSleepReader.kt": "class SamsungHealthSleepReader",
    "SamsungHealthDietActivityReader.kt": "class SamsungHealthDietActivityReader",
    "SamsungHealthScoreGoalReader.kt": "class SamsungHealthScoreGoalReader",
}

# 门面只做组装，这些实现细节必须留在协作文件里
LEAKED_IMPLEMENTATION = (
    "store.readData(",
    "store.aggregateData(",
    "getGrantedPermissions(",
    "private suspend fun read",
)


def main() -> int:
    """执行结构回归检查。"""
    problems: list[str] = []
    facade = (SAMSUNG_DIR / FACADE_NAME).read_text(encoding="utf-8")
    facade_lines = len(facade.splitlines())
    if facade_lines > FACADE_MAX_LINES:
        problems.append(f"{FACADE_NAME} 有 {facade_lines} 行，超过门面上限 {FACADE_MAX_LINES} 行")

    for filename, marker in COLLABORATORS.items():
        path = SAMSUNG_DIR / filename
        if not path.exists():
            problems.append(f"缺少协作文件: {filename}")
            continue
        source = path.read_text(encoding="utf-8")
        if marker not in source:
            problems.append(f"{filename} 未声明 {marker}")
        lines = len(source.splitlines())
        if lines > COLLABORATOR_MAX_LINES:
            problems.append(f"{filename} 有 {lines} 行，超过单文件上限 {COLLABORATOR_MAX_LINES} 行")

    for marker in LEAKED_IMPLEMENTATION:
        if marker in facade:
            problems.append(f"{FACADE_NAME} 仍残留读取实现: {marker}")

    injected = (
        "private val permissions: SamsungHealthPermissions",
        "private val vitalsReader: SamsungHealthVitalsReader",
        "private val bodyReader: SamsungHealthBodyReader",
        "private val sleepReader: SamsungHealthSleepReader",
        "private val dietActivityReader: SamsungHealthDietActivityReader",
        "private val scoreGoalReader: SamsungHealthScoreGoalReader",
    )
    for marker in injected:
        if marker not in facade:
            problems.append(f"{FACADE_NAME} 未注入协作读取器: {marker}")

    public_api = (
        "suspend fun ensurePermissions(activity: Activity)",
        "suspend fun hasPermissions()",
        "suspend fun readVitals()",
        "suspend fun readBodyComposition()",
        "suspend fun readAll(includeBodyComposition: Boolean = true)",
    )
    for marker in public_api:
        if marker not in facade:
            problems.append(f"{FACADE_NAME} 公共 API 发生变化: {marker}")

    # store 只在 DI 里创建一次，避免每个读取器各建一份
    app_module = APP_MODULE.read_text(encoding="utf-8")
    if "HealthDataService.getStore(" not in app_module:
        problems.append("AppModule 未提供 Samsung Health HealthDataStore 单例")
    for path in SAMSUNG_DIR.glob("*.kt"):
        if "HealthDataService.getStore(" in path.read_text(encoding="utf-8"):
            problems.append(f"{path.name} 自行创建 store，应改为注入 HealthDataStore")

    if problems:
        print("验证失败:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(
        f"结构验证通过: 门面 {facade_lines} 行，"
        f"{len(COLLABORATORS)} 个协作者职责独立，store 由 DI 单例提供。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
