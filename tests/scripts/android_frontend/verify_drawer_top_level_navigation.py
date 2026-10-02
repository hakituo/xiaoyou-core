"""验证 Android 侧边栏所有顶层栏目共用同一返回栈导航策略。"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ANDROID_PRESENTATION = (
    PROJECT_ROOT
    / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile/presentation"
)


def read(relative_path: str) -> str:
    return (ANDROID_PRESENTATION / relative_path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    activity = read("MainActivity.kt")
    drawer = read("components/DrawerContent.kt")

    require("onSettingsClick" not in activity + drawer, "设置仍保留独立导航入口")
    require(
        "onClick = { onNavigate(item.route) }" in drawer,
        "侧边栏栏目没有统一交给顶层导航回调",
    )
    require(
        "popUpTo(startDestId)" in activity,
        "顶层导航没有在切换栏目时整理返回栈",
    )
    require(
        "restoreState = !isStartDestination" in activity,
        "顶层导航没有按目的地恢复已保存状态",
    )
    require(
        "navController.navigate(Routes.SETTINGS)" not in activity,
        "设置仍绕过统一顶层导航策略",
    )

    print("Android 侧边栏顶层路由验证通过：设置与其他栏目共用同一返回栈策略。")


if __name__ == "__main__":
    main()
