# -*- coding: utf-8 -*-
"""验证 Android 前台守护通知被移除后可立即自恢复。

本脚本只做静态检查，不运行 Gradle，避免与 Android Studio 争用缓存锁。

用法：
    .\venv_core\Scripts\python.exe tests\scripts\android_keepalive\verify_notification_self_restore.py
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SERVICES = (
    ROOT
    / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile/services"
)


def require(source: str, marker: str, problem: str, problems: list[str]) -> None:
    """要求源码包含关键结构。"""
    if marker not in source:
        problems.append(problem)


def main() -> int:
    foreground_dir = SERVICES / "foreground"
    notification = (foreground_dir / "ForegroundNotificationController.kt").read_text(
        encoding="utf-8"
    )
    contract = (foreground_dir / "ForegroundServiceContract.kt").read_text(
        encoding="utf-8"
    )
    listener = (SERVICES / "AvelineNotificationService.kt").read_text(encoding="utf-8")
    problems: list[str] = []

    checks = (
        (
            notification,
            "import com.aveline.ai.mobile.services.AvelineNotificationManager.Companion.CHANNEL_MESSAGES",
            "无障碍断线提醒使用的 CHANNEL_MESSAGES 导入缺失",
        ),
        (contract, "ACTION_RESTORE_NOTIFICATION", "缺少通知恢复 Action"),
        (notification, "PendingIntent.getForegroundService", "Android 8+ 未使用前台服务恢复 PendingIntent"),
        (notification, ".setDeleteIntent(restorePendingIntent)", "守护通知没有绑定划除恢复动作"),
        (notification, ".setOngoing(true)", "守护通知没有保持 ongoing 标记"),
        (notification, ".setOnlyAlertOnce(true)", "恢复通知可能反复提示"),
        (notification, ".setSilent(true)", "恢复通知可能反复发声"),
        (contract, "AvelineAccessibilityService.isEnabledInSystem(appContext)", "恢复前未检查无障碍是否仍启用"),
        (contract, "AppPreferences(appContext).residentModeEnabled", "恢复前未检查常驻模式"),
        (listener, "override fun onNotificationRemoved", "通知监听服务缺少移除兜底"),
        (listener, "isKeepAliveNotification(sbn.id)", "通知监听服务没有精确匹配守护通知 ID"),
        (listener, "restoreKeepAliveNotification", "通知监听服务没有触发恢复"),
    )
    for source, marker, problem in checks:
        require(source, marker, problem, problems)

    if problems:
        print("验证失败:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("静态验证通过: ongoing + deleteIntent 主恢复 + NotificationListener 兜底均已接通。")
    print("真机复验: 保持无障碍开启，划掉 Aveline 守护通知，通知应立即重新出现且不重复响铃。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
