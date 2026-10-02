"""验证「学习 → 更多」二级板块的手势归属与返回层级。

背景（本次要修的两个问题）：
1. 关掉外层 pager 手势后，二级板块里的横滑一路冒泡到顶层
   PullableNavigationDrawer，变成"呼出侧边栏"；正确归属是：计划 / 日记用它翻
   前一天 / 后一天，其余二级板块至少不能冒泡到侧边栏。
2. 二级板块里按系统返回键直接退出到聊天页，应该先退回「更多」入口。

安卓端按项目规则不在沙箱内跑 Gradle，因此这里做静态契约校验 + 括号配平，
真机/编译验证仍需在 Android Studio 完成。

运行：
    venv_core\\Scripts\\python.exe ^
        tests\\scripts\\android_frontend\\verify_study_more_subsection_gestures.py
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ANDROID_PRESENTATION = (
    PROJECT_ROOT
    / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile/presentation"
)

STUDY = "study"

PASSED: list[str] = []
FAILED: list[str] = []


def read(relative_path: str) -> str:
    return (ANDROID_PRESENTATION / relative_path).read_text(encoding="utf-8")


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"[OK] {name}")
    else:
        FAILED.append(name)
        print(f"[FAIL] {name} {detail}")


def strip_noise(text: str) -> str:
    """去掉注释与字符串字面量，便于括号配平统计。"""
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        nxt = text[index + 1] if index + 1 < length else ""
        if char == "/" and nxt == "/":
            while index < length and text[index] != "\n":
                index += 1
            continue
        if char == "/" and nxt == "*":
            index += 2
            while index + 1 < length and not (text[index] == "*" and text[index + 1] == "/"):
                index += 1
            index += 2
            continue
        if char == '"':
            index += 1
            while index < length and text[index] != '"':
                if text[index] == "\\":
                    index += 1
                index += 1
            index += 1
            continue
        if char == "'":
            index += 1
            while index < length and text[index] != "'":
                if text[index] == "\\":
                    index += 1
                index += 1
            index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def check_balance(relative_path: str) -> None:
    code = strip_noise(read(relative_path))
    for open_char, close_char, label in (("(", ")", "圆括号"), ("{", "}", "花括号")):
        check(
            f"{relative_path} {label}配平",
            code.count(open_char) == code.count(close_char),
            f"open={code.count(open_char)} close={code.count(close_char)}",
        )


def main() -> int:
    gestures = read(f"{STUDY}/StudySwipeGestures.kt")
    screen = read(f"{STUDY}/StudyScreenV2.kt")
    more = read(f"{STUDY}/StudyMoreTab.kt")
    plan = read(f"{STUDY}/StudyPlanTab.kt")
    diary = read(f"{STUDY}/StudyDiaryTab.kt")

    # 1. 手势归属：二级板块自己的横向手势
    check(
        "提供 horizontalPagingSwipe（右滑上一个 / 左滑下一个）",
        "fun Modifier.horizontalPagingSwipe(" in gestures,
    )
    check(
        "提供 consumeHorizontalSwipe（无翻页概念的板块吞掉横滑）",
        "fun Modifier.consumeHorizontalSwipe(" in gestures,
    )
    check(
        "横滑手势消费触摸事件，避免冒泡到顶层抽屉",
        "detectHorizontalDragGestures(" in gestures and "change.consume()" in gestures,
    )
    check(
        "同时用 nestedScroll 吃掉子层没消费完的横向位移（抽屉的第二条通路）",
        "onPostScroll(" in gestures and "Offset(available.x, 0f)" in gestures,
    )

    # 2. 计划 / 日记：横滑翻前一天 / 后一天
    for name, source in (("计划", plan), ("日记", diary)):
        check(
            f"{name}板块接了横滑翻页",
            "horizontalPagingSwipe(" in source,
        )
        check(
            f"{name}板块的横滑与箭头共用 shiftDateString",
            "shiftDateString(selectedDate, -1)" in source
            and "shiftDateString(selectedDate, 1)" in source,
        )
    check(
        "日期偏移助手只保留一份实现",
        "fun shiftDateString(" in plan,
    )
    check(
        "其余二级板块统一吞掉横滑（不冒泡到侧边栏）",
        "consumeHorizontalSwipe()" in more,
    )

    # 3. 返回层级：二级板块 → 更多
    check(
        "二级板块注册了返回键处理",
        "BackHandler(enabled = moreSection != StudyMoreSection.HUB)" in screen,
    )
    check(
        "返回键退回「更多」入口而不是直接退出 Study",
        "moreSection = StudyMoreSection.HUB" in screen,
    )
    check(
        "外层 pager 手势仍按二级板块状态关闭（不重复冒犯 Tab 翻页）",
        "userScrollEnabled = pagerGestureEnabled" in screen,
    )

    for relative in (
        f"{STUDY}/StudySwipeGestures.kt",
        f"{STUDY}/StudyScreenV2.kt",
        f"{STUDY}/StudyMoreTab.kt",
        f"{STUDY}/StudyPlanTab.kt",
        f"{STUDY}/StudyDiaryTab.kt",
    ):
        check_balance(relative)

    print("-" * 60)
    print(f"通过 {len(PASSED)}，失败 {len(FAILED)}")
    if FAILED:
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("提示：手势与返回层级需在 Android Studio 编译 + 真机复现确认。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
