"""验证 Android 客户端保活增强(WakeLock + 电池优化白名单引导)是否正确落地。

检查项:
1. ResidentPowerController 持有并释放 PARTIAL_WAKE_LOCK
2. SettingsUiState 新增 showBatteryOptimizationRequest 字段
3. SettingsViewModel 新增 confirmBatteryOptimization / dismissBatteryOptimization 方法
4. SettingsPrivacyTab 新增 AlertDialog 引导
5. SettingsScreenV2 + NavGraph 完成回调透传

运行方式:
    python tests/scripts/android_keepalive/verify_wakelock_and_battery_whitelist.py
退出码 0 表示全部通过,非 0 表示有未落地的改动点。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 项目根目录(脚本位于 tests/scripts/android_keepalive/ 下)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ANDROID_SRC = PROJECT_ROOT / "clients" / "frontend" / "aveline-android" / "android" / "app" / "src" / "main" / "java" / "com" / "aveline" / "ai"


def _check_file_contains(rel_path: str, needle: str, description: str) -> bool:
    """检查文件是否包含指定字符串。"""
    file_path = ANDROID_SRC / rel_path
    if not file_path.exists():
        print(f"[FAIL] 文件不存在: {rel_path} ({description})")
        return False
    content = file_path.read_text(encoding="utf-8")
    if needle not in content:
        print(f"[FAIL] 未找到: {needle} ({description})")
        return False
    print(f"[OK] {description}")
    return True


def main() -> int:
    checks = [
        # 1. WakeLock — ResidentPowerController
        (
            "mobile/services/foreground/ResidentPowerController.kt",
            "import android.os.PowerManager",
            "WakeLock: import PowerManager",
        ),
        (
            "mobile/services/foreground/ResidentPowerController.kt",
            "private var wakeLock: PowerManager.WakeLock? = null",
            "WakeLock: 字段声明",
        ),
        (
            "mobile/services/foreground/ResidentPowerController.kt",
            "PowerManager.PARTIAL_WAKE_LOCK",
            "WakeLock: 使用 PARTIAL_WAKE_LOCK",
        ),
        (
            "mobile/services/AvelineForegroundServiceV2.kt",
            "powerController.acquire()",
            "WakeLock: acquireWakeLock 调用",
        ),
        (
            "mobile/services/AvelineForegroundServiceV2.kt",
            "powerController.release()",
            "WakeLock: releaseWakeLock 调用",
        ),
        # 2. SettingsUiState 新增字段
        (
            "mobile/presentation/settings/SettingsUiState.kt",
            "showBatteryOptimizationRequest",
            "SettingsUiState: showBatteryOptimizationRequest 字段",
        ),
        # 3. SettingsViewModel 新增方法
        (
            "mobile/presentation/settings/SettingsViewModel.kt",
            "fun confirmBatteryOptimization()",
            "SettingsViewModel: confirmBatteryOptimization 方法",
        ),
        (
            "mobile/presentation/settings/SettingsViewModel.kt",
            "fun dismissBatteryOptimization()",
            "SettingsViewModel: dismissBatteryOptimization 方法",
        ),
        (
            "mobile/presentation/settings/SettingsViewModel.kt",
            "isIgnoringBatteryOptimizations",
            "SettingsViewModel: isIgnoringBatteryOptimizations 检查",
        ),
        (
            "mobile/presentation/settings/SettingsViewModel.kt",
            "ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS",
            "SettingsViewModel: 跳转系统电池优化设置",
        ),
        # 4. SettingsPrivacyTab AlertDialog
        (
            "mobile/presentation/settings/SettingsPrivacyTab.kt",
            "AlertDialog",
            "SettingsPrivacyTab: AlertDialog 引导",
        ),
        (
            "mobile/presentation/settings/SettingsPrivacyTab.kt",
            "onConfirmBatteryOptimization",
            "SettingsPrivacyTab: 确认回调参数",
        ),
        # 5. SettingsScreenV2 透传
        (
            "mobile/presentation/settings/SettingsScreenV2.kt",
            "onConfirmBatteryOptimization",
            "SettingsScreenV2: 透传确认回调",
        ),
        # 6. NavGraph 透传
        (
            "mobile/presentation/navigation/NavGraph.kt",
            "settingsViewModel::confirmBatteryOptimization",
            "NavGraph: 透传 confirmBatteryOptimization",
        ),
        (
            "mobile/presentation/navigation/NavGraph.kt",
            "settingsViewModel::dismissBatteryOptimization",
            "NavGraph: 透传 dismissBatteryOptimization",
        ),
    ]

    all_passed = True
    for rel_path, needle, description in checks:
        if not _check_file_contains(rel_path, needle, description):
            all_passed = False

    print()
    if all_passed:
        print("=== 全部通过:保活增强改动已正确落地 ===")
        return 0
    print("=== 存在未落地的改动点,请检查上方 [FAIL] 项 ===")
    return 1


if __name__ == "__main__":
    sys.exit(main())
