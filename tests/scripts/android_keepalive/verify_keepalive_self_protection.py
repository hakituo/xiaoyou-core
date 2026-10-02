# -*- coding: utf-8 -*-
"""验证 Android 端"无障碍开关自己关闭"的两个保活 P0 缺陷已修复。

覆盖两条链路：
1. 自身 force-stop 自杀链：SystemControlExecutor 最底层拒绝 force-stop Aveline 自身，
   且数字健康限额的写入端/执行端（WellbeingViewModel、DataSyncWorker、UsageLimitMonitor）
   全部过滤自身包名。
2. 常驻前台服务 dataSync 6 小时配额雷：前台类型改为 specialUse 优先 + Android 15
   onTimeout 优雅降级 + 配额冷却重挂，不再让系统抛 RemoteServiceException 崩掉宿主进程。

本脚本只做静态检查，不运行 Gradle，避免与 Android Studio 争用缓存锁。

用法：
    .\\venv_core\\Scripts\\python.exe tests\\scripts\\android_keepalive\\verify_keepalive_self_protection.py
"""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "clients/frontend/aveline-android/android/app/src/main"
SERVICES = APP / "java/com/aveline/ai/mobile/services"
UTILS = APP / "java/com/aveline/ai/mobile/utils"
WELLBEING = APP / "java/com/aveline/ai/mobile/presentation/wellbeing"
MANIFEST = APP / "AndroidManifest.xml"


def require(source: str, marker: str, problem: str, problems: list[str]) -> None:
    """要求源码包含关键结构。"""
    if marker not in source:
        problems.append(problem)


def require_re(source: str, pattern: str, problem: str, problems: list[str]) -> None:
    """要求源码匹配正则。用于「写法可能变（全限定名 / 变量名 / 换行）」的结构断言。"""
    if not re.search(pattern, source):
        problems.append(problem)


def forbid(source: str, marker: str, problem: str, problems: list[str]) -> None:
    """要求源码不再包含危险结构。"""
    if marker in source:
        problems.append(problem)


def main() -> int:
    guard = (UTILS / "SelfPackageGuard.kt").read_text(encoding="utf-8")
    executor = (SERVICES / "SystemControlExecutor.kt").read_text(encoding="utf-8")
    limit_monitor = (SERVICES / "worker/UsageLimitMonitor.kt").read_text(encoding="utf-8")
    sync_worker = (SERVICES / "worker/DataSyncWorker.kt").read_text(encoding="utf-8")
    wellbeing_vm = (WELLBEING / "WellbeingViewModel.kt").read_text(encoding="utf-8")
    fg_service = (SERVICES / "AvelineForegroundServiceV2.kt").read_text(encoding="utf-8")
    # 挂前台 / 超时降级 / 配额冷却在 2026-09-24 拆到 ForegroundStartCoordinator.kt，检查点跟着搬家
    fg_start = (
        SERVICES / "foreground/ForegroundStartCoordinator.kt"
    ).read_text(encoding="utf-8")
    type_policy = (
        SERVICES / "foreground/ForegroundServiceTypePolicy.kt"
    ).read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")
    problems: list[str] = []

    # ── 1. 自身包名统一保护 ──────────────────────────────
    checks = (
        (
            guard,
            "packageName == context.packageName",
            "SelfPackageGuard 未使用运行时 context.packageName 判断自身",
        ),
        (guard, "SELF_PACKAGE_PREFIX", "SelfPackageGuard 缺少同族变体前缀保护 (debug/正式包)"),
        (guard, "fun filterOutSelf", "SelfPackageGuard 缺少 Map 过滤能力"),
        (
            executor,
            "拒绝强制停止 Aveline 自身",
            "SystemControlExecutor 未拒绝 force-stop Aveline 自身",
        ),
    )
    for source, marker, problem in checks:
        require(source, marker, problem, problems)

    # 两个入口（本地调用 + device_command 远程指令）都要有硬保护
    if executor.count("SelfPackageGuard.isSelf") < 2:
        problems.append("SystemControlExecutor 的两个 forceStopApp 入口未全部接入自身保护")

    # ── 2. 数字健康限额链路过滤自身 ─────────────────────
    # 2026-09-25 重新对准：限额链路在 ba06949d 重构为 AppLimitPolicy + SessionLimiter
    # 抽象，原先「UsageLimitMonitor 自己解析原始 prefs、用
    # filterOutSelf(context, parsePairs(limitsRaw/sessionCapsRaw)) 过滤」的写法已随
    # 解析职责搬走而消失（旧标记因此长期误报，本脚本未接入 CI 所以没人发现）。
    # 现按新架构断言**端到端**保证：策略表只有两个写入点，且都写入已剔除自身的集合。
    limit_checks = (
        (
            wellbeing_vm,
            "!SelfPackageGuard.isSelf(context, it.packageName)",
            "WellbeingViewModel 缓存后端限额时未剔除自身",
        ),
        (
            wellbeing_vm,
            "sessionLimiter.replacePolicies(selfExcluded)",
            "WellbeingViewModel 写入策略表时未使用已剔除自身的集合",
        ),
        (
            sync_worker,
            "SelfPackageGuard.isSelf(context, it.packageName)",
            "DataSyncWorker 写入策略表前未剔除自身",
        ),
        (
            sync_worker,
            "sessionLimiter.replacePolicies(safe)",
            "DataSyncWorker 写入策略表时未使用已剔除自身的集合",
        ),
        (
            wellbeing_vm,
            "!SelfPackageGuard.isSelf(context, ai.packageName)",
            "WellbeingViewModel 应用候选列表未排除 Aveline 自身",
        ),
    )
    for source, marker, problem in limit_checks:
        require(source, marker, problem, problems)

    # 执行端兜底：UsageLimitMonitor 逐策略跳过自身。
    # 用正则而非精确串，容忍「全限定名 vs import 短名」「变量名 pkg vs packageName」的写法差异。
    require_re(
        limit_monitor,
        r"SelfPackageGuard\.isSelf\(context,\s*packageName\)\)\s*\{\s*continue",
        "UsageLimitMonitor 遍历策略时缺少自身包名兜底跳过",
        problems,
    )

    # ── 3. 前台服务类型与超时降级 ───────────────────────
    fgs_checks = (
        (
            type_policy,
            "FOREGROUND_SERVICE_TYPE_SPECIAL_USE",
            "前台服务类型策略未使用不受配额限制的 specialUse",
        ),
        (
            type_policy,
            "Build.VERSION_CODES.VANILLA_ICE_CREAM",
            "前台服务类型策略未识别 Android 15 的 dataSync 配额",
        ),
        (
            fg_service,
            "override fun onTimeout(startId: Int)",
            "前台服务未实现 Android 15 onTimeout(startId)",
        ),
        (
            fg_service,
            "override fun onTimeout(startId: Int, fgsType: Int)",
            "前台服务未实现 Android 15 onTimeout(startId, fgsType)",
        ),
        (
            fg_start,
            "service.stopForeground(Service.STOP_FOREGROUND_DETACH)",
            "前台服务超时后未保留常驻通知仅解除前台状态",
        ),
        (
            fg_start,
            "ForegroundServiceTypePolicy.candidates()",
            "前台服务仍硬编码单一前台类型",
        ),
        (
            fg_start,
            "appPreferences.fgsQuotaResumeAtMs",
            "前台服务缺少配额冷却记录, 会陷入超时-重启死循环",
        ),
        (
            manifest,
            'android:foregroundServiceType="specialUse|dataSync"',
            "Manifest 未声明 specialUse 前台服务类型",
        ),
        (
            manifest,
            "android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE",
            "Manifest 缺少 specialUse 必需的 subtype 属性",
        ),
        (
            manifest,
            "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
            "Manifest 缺少 FOREGROUND_SERVICE_SPECIAL_USE 权限",
        ),
    )
    for source, marker, problem in fgs_checks:
        require(source, marker, problem, problems)

    forbid(
        fg_service,
        "ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC",
        "前台服务仍在直接使用 dataSync 类型常量, 未走类型策略",
        problems,
    )

    if problems:
        print("验证失败:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("静态验证通过: 自身 force-stop 已堵死, 数字健康链路过滤自身, 前台服务配额雷已拆除。")
    print("真机复验:")
    print("  1) 数字健康给 Aveline 自己设一个 1 分钟限额, 超时后无障碍开关应保持开启;")
    print("  2) adb shell 观察连续运行 > 6 小时不再出现 RemoteServiceException;")
    print("  3) adb logcat -s A11yDiag 检查 FgSvc 的 startForeground type=specialUse。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
