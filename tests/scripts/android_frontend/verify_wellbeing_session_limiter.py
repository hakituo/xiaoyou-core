"""验证数字健康「每日额度 + 真实单次会话」重构是否完整落地。

覆盖三层:
1. Android 侧: 策略模型 / 会话状态机 / 无障碍实时执行 / Worker 兜底 / 持久化 / UI
2. 后端侧: DigitalWellbeingService 策略归一化 (含旧字段兼容) 与默认值补齐
3. 关键语义: 会话间隔与冷却必须存在, 否则"退出再打开"能绕过单次额度

用法:
    venv_core\\Scripts\\python.exe tests\\scripts\\android_frontend\\verify_wellbeing_session_limiter.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

ANDROID_SOURCE = (
    PROJECT_ROOT
    / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"
)
WELLBEING = ANDROID_SOURCE / "services/wellbeing"


def read(relative_path: str) -> str:
    return (ANDROID_SOURCE / relative_path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


# ── 1. 策略模型与会话状态机 ──────────────────────────────────


def verify_policy_model() -> None:
    policy = (WELLBEING / "AppLimitPolicy.kt").read_text(encoding="utf-8")
    require("data class AppLimitPolicy" in policy, "缺少 AppLimitPolicy 策略模型")
    for field in ("dailyLimitMs", "sessionLimitMs", "sessionGapMs", "cooldownMs"):
        require(f"val {field}" in policy, f"策略缺少字段 {field}")
    require("DEFAULT_SESSION_GAP_MS" in policy, "缺少默认会话间隔")
    require("DEFAULT_COOLDOWN_MS" in policy, "缺少默认冷却时长")
    # 间隔为 0 必须回落默认值, 否则每次切后台都能白拿一份新的单次额度
    require(
        "sessionGapMs.takeIf { it > 0 } ?: DEFAULT_SESSION_GAP_MS" in policy,
        "会话间隔没有做缺省保护, 0 间隔会让单次限制形同虚设",
    )
    require(
        "fun fromLegacy(" in policy,
        "缺少旧版 (app_limits + session_caps) 兼容转换",
    )


def verify_session_limiter() -> None:
    limiter = (WELLBEING / "SessionLimiter.kt").read_text(encoding="utf-8")
    # 四类判定都要有
    require("BlockReason.DAILY" in limiter, "缺少每日额度拦截")
    require("BlockReason.SESSION" in limiter, "缺少单次额度拦截")
    require("BlockReason.COOLDOWN" in limiter, "缺少冷却期拦截")
    # "一次"的语义由 sessionGap 界定, 且会话基线按当日用量快照
    require(
        "nowMs - state.lastForegroundMs >= policy.sessionGapMs" in limiter,
        "缺少会话间隔判定 (离开多久算新的一次)",
    )
    require(
        "baselineDailyMs" in limiter,
        "缺少会话基线, 无法计算本次已用",
    )
    require(
        "(usageMs - state.baselineDailyMs)" in limiter,
        "本次用量没有用 (当日累计 - 会话基线) 计算",
    )
    # 单次超限后必须设置冷却, 否则用户可立刻重开
    require(
        "blockedUntilMs = cooldownUntil" in limiter and "nowMs + policy.cooldownMs" in limiter,
        "单次超限后没有进入冷却",
    )
    # 每日额度耗尽标记当天, 次日自动失效
    require(
        "dailyBlockedDay = today" in limiter,
        "每日额度耗尽没有记录日期, 无法次日自动恢复",
    )
    # 三种调用模式: 实时 / 兜底 / 只读
    for mode in ("noteForeground", "enforceFallback", "peek", "reconcile"):
        require(f"fun {mode}" in limiter, f"SessionLimiter 缺少 {mode}")
    require(
        "EvalMode.FOREGROUND &&" in limiter,
        "单次额度必须只在确认前台时判定 (Worker 无前台信息)",
    )
    require(
        "appPreferences.appSessionStates" in limiter,
        "会话状态没有跨进程持久化, 进程回收后冷却/会话会丢失",
    )
    require("Mutex" in limiter, "状态机没有加锁, 存在并发写坏风险")


# ── 2. 执行器与两条执行路径 ──────────────────────────────────


def verify_enforcer() -> None:
    enforcer = (WELLBEING / "UsageLimitEnforcer.kt").read_text(encoding="utf-8")
    require("goHome()" in enforcer, "拦截时没有先退回桌面")
    require(
        "forceStopApp(" in enforcer and "acceptBackgroundFallback = true" in enforcer,
        "拦截时没有尝试强退目标应用",
    )
    require("SelfPackageGuard.isSelf" in enforcer, "拦截器缺少自身保护")


def verify_accessibility_realtime() -> None:
    svc = read("services/AvelineAccessibilityService.kt")
    require("currentForegroundPackage" in svc, "无障碍服务没有跟踪前台应用")
    require(
        "sessionLimiter.noteBackground(previous)" in svc,
        "离开前台没有记录时刻, sessionGap 计时不会启动",
    )
    require("startForegroundTicker()" in svc, "缺少前台限额轮询 (单次额度主执行路径)")
    require("sessionLimiter.noteForeground(packageName)" in svc, "前台轮询没有调用状态机")
    # 快到单次上限时把轮询间隔压到剩余时间, 让拦截精确到秒而不是等 10s
    require(
        "remaining.coerceIn(TICK_MIN_MS" in svc,
        "临近单次上限时没有缩短轮询间隔",
    )
    require(
        "usageLimitEnforcer.block(packageName, decision)" in svc,
        "实时路径没有接拦截执行器",
    )
    # 轮询协程取消时不能被兜底 catch 吞掉
    require(
        "catch (e: CancellationException)" in svc,
        "轮询循环缺少取消传播, 服务销毁后协程会残留",
    )


def verify_worker_fallback_only() -> None:
    worker = read("services/worker/UsageLimitMonitor.kt")
    require("sessionLimiter.enforceFallback" in worker, "Worker 没有走兜底判定")
    require(
        "noteForeground" not in worker,
        "Worker 不应判定前台 (15 分钟周期对单次额度不够精确)",
    )
    require("sessionLimiter.reconcile()" in worker, "Worker 缺少过期会话清理")
    require(
        "兜底" in worker,
        "Worker 注释应说明它是兜底执行器, 不是主执行器",
    )


# ── 3. 数据层与 UI ──────────────────────────────────────────


def verify_data_layer() -> None:
    prefs = read("data/local/preferences/AppPreferences.kt")
    require("appLimitPolicies" in prefs, "缺少策略表持久化键")
    require("appSessionStates" in prefs, "缺少会话状态持久化键")
    require(
        "migrateLegacyUsageLimits" in prefs,
        "缺少旧配置一次性迁移, 升级后会出现限额真空期",
    )
    require("KEY_SESSION_CAP_STARTS" not in prefs, "旧版会话起点键未清理")

    sync = read("data/remote/dto/ContextSyncRequest.kt")
    require("data class AppLimitPolicyDto" in sync, "缺少策略下发 DTO")
    for field in ("daily_limit_ms", "session_limit_ms", "session_gap_ms", "cooldown_ms"):
        require(f'"{field}"' in sync, f"策略 DTO 缺少 {field}")
    require("appPolicies" in sync, "同步响应没有接收 app_policies")

    dto = read("data/remote/dto/AppLimitDto.kt")
    for field in ("session_limit_ms", "session_gap_ms", "cooldown_ms"):
        require(f'"{field}"' in dto, f"AppLimitDto 缺少 {field}")
    require(
        "fun effectiveSessionLimitMs" in dto,
        "AppLimitDto 缺少旧字段兼容读取",
    )

    ds = read("services/worker/DataSyncWorker.kt")
    require("applyAppPolicies" in ds, "DataSyncWorker 没有落地新策略")
    require(
        "AppLimitPolicyCodec.fromLegacy" in ds,
        "DataSyncWorker 缺少老后端回退 (只有 app_limits/session_caps 时)",
    )
    require("sessionLimiter.replacePolicies" in ds, "策略没有写入 SessionLimiter")

    vm = read("presentation/wellbeing/WellbeingViewModel.kt")
    for param in ("dailyLimitMs", "sessionLimitMs", "cooldownMs"):
        require(f"{param}: Long" in vm, f"ViewModel 保存限额缺少参数 {param}")
    require(
        "sessionLimiter.peek" in vm,
        "页面没有从会话状态机读取本次已用",
    )


def verify_ui() -> None:
    screen = read("presentation/wellbeing/WellbeingScreen.kt")
    for concept in ("今日使用", "单次使用", "超时休息", "每日限额", "单次限额"):
        require(concept in screen, f"数字健康卡片缺少用户概念「{concept}」")
    require(
        "一次性会话限额" not in screen,
        "卡片仍保留旧的一次性 cap 文案",
    )

    dialog = read("presentation/wellbeing/AppLimitDialog.kt")
    require("PRESET_SESSION_LIMITS" in dialog, "对话框缺少单次限额预设")
    require("PRESET_COOLDOWNS" in dialog, "对话框缺少超时休息预设")
    require(
        "离开超过 2 分钟" in dialog,
        "对话框没有解释\"新的一次\"的判定规则",
    )


# ── 4. 后端 ────────────────────────────────────────────────


def verify_backend_service() -> None:
    from core.services.digital_wellbeing.service import (  # noqa: E402
        DEFAULT_COOLDOWN_MS,
        DEFAULT_SESSION_GAP_MS,
        DigitalWellbeingService,
    )

    require(DEFAULT_SESSION_GAP_MS > 0, "默认会话间隔必须大于 0")
    require(DEFAULT_COOLDOWN_MS > 0, "默认冷却必须大于 0")

    with tempfile.TemporaryDirectory() as tmp:
        svc = DigitalWellbeingService(base_dir=Path(tmp))

        # 每日 + 单次 + 自定义间隔/冷却 全部落盘
        svc.set_single_limit(
            package_name="com.douyin",
            limit_ms=3_600_000,
            app_name="抖音",
            target_date="2099-01-01",
            session_limit_ms=600_000,
            session_gap_ms=120_000,
            cooldown_ms=300_000,
        )
        cfg = svc.get_limits("2099-01-01")["limits"]["com.douyin"]
        require(cfg["limit_ms"] == 3_600_000, "每日额度未落盘")
        require(cfg["session_limit_ms"] == 600_000, "单次额度未落盘")
        require(cfg["session_gap_ms"] == 120_000, "自定义会话间隔未落盘")
        require(cfg["cooldown_ms"] == 300_000, "自定义冷却未落盘")

        # 只改每日额度不能把单次额度抹掉
        svc.set_single_limit(
            package_name="com.douyin",
            limit_ms=1_800_000,
            target_date="2099-01-01",
        )
        cfg = svc.get_limits("2099-01-01")["limits"]["com.douyin"]
        require(cfg["limit_ms"] == 1_800_000, "每日额度更新失败")
        require(cfg["session_limit_ms"] == 600_000, "只改每日额度时单次额度被抹掉")

        # 不传间隔/冷却时补默认值; 且只有配置了单次额度才需要冷却
        svc.set_single_limit(
            package_name="com.bilibili",
            limit_ms=1_800_000,
            app_name="哔哩哔哩",
            target_date="2099-01-01",
            session_limit_ms=900_000,
        )
        cfg = svc.get_limits("2099-01-01")["limits"]["com.bilibili"]
        require(cfg["session_gap_ms"] == DEFAULT_SESSION_GAP_MS, "会话间隔没有补默认值")
        require(cfg["cooldown_ms"] == DEFAULT_COOLDOWN_MS, "冷却没有补默认值")

        svc.set_single_limit(
            package_name="com.wechat",
            limit_ms=900_000,
            target_date="2099-01-01",
        )
        cfg = svc.get_limits("2099-01-01")["limits"]["com.wechat"]
        require(cfg.get("session_limit_ms", 0) == 0, "未设单次额度却出现了单次字段")
        require("cooldown_ms" not in cfg, "未设单次额度却出现了冷却")

        # 旧字段 session_cap_ms 兼容读取
        svc.save_limits(
            {
                "com.legacy": {
                    "limit_ms": 600_000,
                    "app_name": "旧字段应用",
                    "session_cap_ms": 300_000,
                }
            },
            target_date="2099-01-02",
        )
        cfg = svc.get_limits("2099-01-02")["limits"]["com.legacy"]
        require(cfg.get("session_limit_ms") == 300_000, "旧字段 session_cap_ms 未迁移")
        require(cfg.get("session_gap_ms") == DEFAULT_SESSION_GAP_MS, "旧数据没有补会话间隔")

        # 两条额度同时为 0 = 整条移除
        svc.set_single_limit(
            package_name="com.wechat",
            limit_ms=0,
            target_date="2099-01-01",
            session_limit_ms=0,
        )
        require(
            "com.wechat" not in svc.get_limits("2099-01-01")["limits"],
            "每日与单次同时清零时没有移除整条配置",
        )


def verify_backend_router_and_tool() -> None:
    router = (PROJECT_ROOT / "routers/v1/context_device.py").read_text(encoding="utf-8")
    require('"app_policies"' in router, "sync_context 没有下发 app_policies")
    require(
        "session_limit_ms" in router and "session_gap_ms" in router,
        "REST 请求/响应模型没有携带单次额度与会话间隔",
    )
    require(
        router.count('"app_limits"') >= 1 and '"session_caps"' in router,
        "旧字段被移除, 未升级的客户端会拿不到限额",
    )

    tool = (PROJECT_ROOT / "core/tools/device/set_app_limit.py").read_text(encoding="utf-8")
    for field in ("session_limit", "session_gap", "cooldown"):
        require(f"{field}: Optional[str]" in tool, f"set_app_limit 工具缺少 {field} 参数")
    require("session_cap" in tool, "set_app_limit 工具丢了旧参数 session_cap 兼容")
    require(
        "离开超过 2 分钟" in tool or "_format_ms(gap_ms)" in tool,
        "工具返回文案没有解释\"新的一次\"判定",
    )


# ── 5. 端到端语义: 绕过路径必须被堵住 ────────────────────────


def verify_bypass_protection() -> None:
    """静态确认三条绕过路径都有关卡。"""
    limiter = (WELLBEING / "SessionLimiter.kt").read_text(encoding="utf-8")
    policy = (WELLBEING / "AppLimitPolicy.kt").read_text(encoding="utf-8")

    # 1) Home 立刻重开: gap 未到 -> 仍是同一次 (基线不变, 用量继续累计)
    require(
        "nowMs - state.lastForegroundMs >= policy.sessionGapMs" in limiter,
        "快速重开未被判为同一次会话",
    )
    # 2) 冷却期内重开: 直接拦
    require("state.blockedUntilMs > nowMs" in limiter, "冷却期内重开没有被拦下")
    # 3) 后端下发 0 间隔/0 冷却: 归一化补默认值
    require(
        "sessionGapMs.takeIf { it > 0 } ?: DEFAULT_SESSION_GAP_MS" in policy,
        "0 间隔未做归一化保护",
    )
    require(
        "cooldownMs.takeIf { it > 0 } ?: DEFAULT_COOLDOWN_MS" in policy,
        "0 冷却未做归一化保护",
    )
    # 4) 每日额度不受单次重置影响: 单次超限只清 startMs, 不清 dailyBlockedDay
    require(
        limiter.index("dailyBlockedDay = today") < limiter.index("blockedUntilMs = cooldownUntil"),
        "判定顺序错误: 应先判每日额度再判单次额度",
    )


def main() -> None:
    checks = [
        ("策略模型", verify_policy_model),
        ("会话状态机", verify_session_limiter),
        ("拦截执行器", verify_enforcer),
        ("无障碍实时执行", verify_accessibility_realtime),
        ("Worker 兜底", verify_worker_fallback_only),
        ("数据层", verify_data_layer),
        ("UI", verify_ui),
        ("后端服务", verify_backend_service),
        ("后端路由与工具", verify_backend_router_and_tool),
        ("绕过路径防护", verify_bypass_protection),
    ]
    for name, fn in checks:
        fn()
        print(f"[PASS] {name}")
    print(f"\n全部 {len(checks)} 项检查通过: 每日额度 + 真实单次会话 (gap/cooldown) 重构完成。")


if __name__ == "__main__":
    main()
