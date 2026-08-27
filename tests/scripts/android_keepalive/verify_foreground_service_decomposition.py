# -*- coding: utf-8 -*-
"""验证 Android 前台守护 Service 已按职责解耦且行为接线完整。"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SERVICES = (
    ROOT
    / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile/services"
)
FOREGROUND = SERVICES / "foreground"


def main() -> int:
    problems: list[str] = []
    service_path = SERVICES / "AvelineForegroundServiceV2.kt"
    service = service_path.read_text(encoding="utf-8")
    line_count = len(service.splitlines())
    if line_count > 300:
        problems.append(f"AvelineForegroundServiceV2 仍有 {line_count} 行，超过薄壳上限 300 行")

    components = {
        "ForegroundNotificationController.kt": "ForegroundNotificationController",
        "ForegroundServiceContract.kt": "ForegroundServiceContract",
        "ResidentPowerController.kt": "ResidentPowerController",
        "ContextSyncController.kt": "ContextSyncController",
        "SamsungHealthSyncController.kt": "SamsungHealthSyncController",
        "AccessibilityMonitor.kt": "AccessibilityMonitor",
        "WebSocketCommandCoordinator.kt": "WebSocketCommandCoordinator",
    }
    for filename, class_name in components.items():
        path = FOREGROUND / filename
        if not path.exists():
            problems.append(f"缺少前台服务子组件: {filename}")
            continue
        source = path.read_text(encoding="utf-8")
        if class_name not in source:
            problems.append(f"{filename} 未声明 {class_name}")
        if len(source.splitlines()) > 250:
            problems.append(f"{filename} 超过 250 行，出现新的大文件风险")

    wiring_markers = (
        "notifications.createChannels()",
        "startForegroundCompat()",
        "powerController.acquire()",
        "contextSyncController.start()",
        "webSocketCoordinator.startObserving()",
        "samsungHealthSyncController.start()",
        "accessibilityMonitor.start()",
        "webSocketCoordinator.stop()",
        "serviceScope.cancel()",
    )
    for marker in wiring_markers:
        if marker not in service:
            problems.append(f"Service 生命周期接线缺失: {marker}")

    leaked_business_markers = (
        "fun parsePhoneAction",
        "fun startSamsungHealthSync",
        "NotificationCompat.Builder",
        "PowerManager.PARTIAL_WAKE_LOCK",
        "Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES",
    )
    for marker in leaked_business_markers:
        if marker in service:
            problems.append(f"Service 薄壳仍残留子系统实现: {marker}")

    if problems:
        print("验证失败:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"结构验证通过: Service 已从 783 行收敛到 {line_count} 行，7 个子组件职责独立。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
