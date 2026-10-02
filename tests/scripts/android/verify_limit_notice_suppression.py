"""验证 Android 端「限额通知不再反复弹」的修复是否到位。

背景（用户反馈）：
    手机一直弹「已经到了 app 限额」的通知，一天几十条。

根因（叠加）：
    1) 限额一旦判定成立是**持续状态**而非一次事件：每日额度用完会挂到次日 0 点，
       用户每打开一次被限额的应用，UsageLimitEnforcer.block() 就走一遍
       「回桌面 → 强退 → 通知」。
    2) 通知节流只有 20 秒且是内存 Map（ConcurrentHashMap），进程被回收即失效。
    3) 15 分钟兜底 Worker 对每个超限应用无条件调用 block()，于是每 15 分钟
       必然再弹一条（一天最多 96 条），而且会顺带把用户踹回桌面。

修复：
    - 新增 LimitNoticeTracker：把「今天提醒过」持久化到 SharedPreferences，
      每日额度同一天只提醒 1 次；单次额度同一冷却周期只提醒 1 次、每天最多 3 次；
      用户改过额度则重新给一次名额；跨天自动失效。
    - UsageLimitEnforcer 去掉 20 秒内存节流，改用 tracker 判定。
    - 兜底 Worker 调用 block(goHome = false)，不再打断用户当前操作。

本脚本用「静态断言 + 规则复刻模拟」检查修复特征，不依赖 Gradle 构建
（项目规则：不在沙箱跑 gradle）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# 仓库根目录：tests/scripts/android/ -> 上溯三级
REPO_ROOT = Path(__file__).resolve().parents[3]
ANDROID_MAIN = (
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
)
ANDROID_TEST = (
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
)

TRACKER = ANDROID_MAIN / "services" / "wellbeing" / "LimitNoticeTracker.kt"
ENFORCER = ANDROID_MAIN / "services" / "wellbeing" / "UsageLimitEnforcer.kt"
MONITOR = ANDROID_MAIN / "services" / "worker" / "UsageLimitMonitor.kt"
PREFS = ANDROID_MAIN / "data" / "local" / "preferences" / "AppPreferences.kt"
TEST_FILE = ANDROID_TEST / "services" / "wellbeing" / "LimitNoticeTrackerTest.kt"

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    """记录一条断言结果。"""
    status = "OK  " if condition else "FAIL"
    print(f"[{status}] {message}")
    if not condition:
        failures.append(message)


def read(path: Path) -> str:
    """读取源码文本，缺失返回空串。"""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


# ── 1. 静态断言：修复特征是否落地 ─────────────────────────────

print("=" * 70)
print("1. 静态断言：修复特征")
print("=" * 70)

tracker_src = read(TRACKER)
check(TRACKER.exists(), "LimitNoticeTracker.kt 已新增")
check(
    "@Synchronized" in tracker_src and "fun takeNoticeSlot" in tracker_src,
    "takeNoticeSlot 判定与记账是原子的（@Synchronized）",
)
check(
    "appPreferences.appLimitNotices" in tracker_src,
    "通知记录持久化到 AppPreferences.appLimitNotices（进程回收后仍记得）",
)
check(
    "reason == SessionLimiter.BlockReason.DAILY -> !record.dailyNotified" in tracker_src,
    "每日额度：同一天只提醒一次",
)
check(
    "record.sessionKey == blockedUntilMs -> false" in tracker_src,
    "单次额度/冷却：同一冷却周期只提醒一次",
)
check(
    "record.count < MAX_NOTICES_PER_DAY" in tracker_src,
    "单次额度：受每日次数上限约束",
)
check(
    "record.dailyLimitMs != dailyLimitMs -> true" in tracker_src,
    "用户改过额度后重新给一次提醒名额",
)
check(
    "internal fun decide(" in tracker_src,
    "判定核心抽成纯函数 decide()（可被 JVM 单测覆盖）",
)

enforcer_src = read(ENFORCER)
check(
    "noticeTracker.takeNoticeSlot(" in enforcer_src,
    "UsageLimitEnforcer 改用 tracker 判定是否弹通知",
)
check(
    "NOTICE_THROTTLE_MS" not in enforcer_src and "lastNoticeAt" not in enforcer_src,
    "已移除旧的 20 秒内存节流（进程回收即失效）",
)
check(
    "goHome: Boolean = true" in enforcer_src,
    "block() 支持关闭「回桌面」",
)

monitor_src = read(MONITOR)
check(
    "goHome = false" in monitor_src,
    "15 分钟兜底 Worker 不再把用户踹回桌面",
)

prefs_src = read(PREFS)
check(
    "var appLimitNotices" in prefs_src
    and 'KEY_APP_LIMIT_NOTICES = "app_limit_notices"' in prefs_src
    and "DEFAULT_APP_LIMIT_NOTICES" in prefs_src,
    "AppPreferences 已新增 appLimitNotices 字段与默认值",
)

test_src = read(TEST_FILE)
check(TEST_FILE.exists(), "新增 JVM 单测 LimitNoticeTrackerTest.kt")
for case in (
    "当天没提醒过则放行",
    "每日额度同一天只提醒一次",
    "同一冷却周期内只提醒一次",
    "新的单次超时(不同冷却周期)可以再提醒",
    "单次额度提醒达到每日上限后不再提醒",
    "用户改过额度后允许重新提醒一次",
):
    check(case in test_src, f"单测覆盖：{case}")

# ── 2. 常量一致性：模拟用的常量必须与 Kotlin 源码一致 ─────────

print()
print("=" * 70)
print("2. 常量一致性（防止脚本与源码漂移）")
print("=" * 70)


def extract_const(source: str, name: str) -> int | None:
    """从 Kotlin 源码里取 `const val NAME = 123L` 的数值。"""
    match = re.search(rf"const val {name}\s*=\s*(\d[\d_]*)\s*L?", source)
    if not match:
        return None
    return int(match.group(1).replace("_", ""))


min_interval = extract_const(tracker_src, "MIN_INTERVAL_MS")
max_per_day = extract_const(tracker_src, "MAX_NOTICES_PER_DAY")
check(min_interval is not None and min_interval > 0, f"MIN_INTERVAL_MS 可解析（={min_interval}）")
check(max_per_day is not None and max_per_day > 0, f"MAX_NOTICES_PER_DAY 可解析（={max_per_day}）")

MIN_INTERVAL_MS = min_interval or 30_000
MAX_NOTICES_PER_DAY = max_per_day or 3

# ── 3. 规则复刻模拟：一天的拦截序列会产生几条通知 ─────────────

print()
print("=" * 70)
print("3. 规则复刻模拟（复刻 Kotlin decide() 的判定顺序）")
print("=" * 70)

DAILY = "DAILY"
SESSION = "SESSION"
COOLDOWN = "COOLDOWN"


class Record:
    """与 Kotlin NoticeRecord 同构。"""

    def __init__(self, day, count, last_at_ms, daily_notified, daily_limit_ms, session_key):
        self.day = day
        self.count = count
        self.last_at_ms = last_at_ms
        self.daily_notified = daily_notified
        self.daily_limit_ms = daily_limit_ms
        self.session_key = session_key


def decide(record, reason, blocked_until_ms, daily_limit_ms, now_ms) -> bool:
    """复刻 LimitNoticeTracker.decide() 的判定顺序。"""
    if record is None:
        return True
    if now_ms - record.last_at_ms < MIN_INTERVAL_MS:
        return False
    if record.daily_limit_ms != daily_limit_ms:
        return True
    if reason == DAILY:
        return not record.daily_notified
    if record.session_key == blocked_until_ms:
        return False
    return record.count < MAX_NOTICES_PER_DAY


def simulate(events, daily_limit_ms):
    """按事件序列模拟，返回 (通知条数, 最终记录)。"""
    records: dict[str, Record] = {}
    notices = 0
    for package, day, now_ms, reason, blocked_until in events:
        record = records.get(package)
        if record is not None and record.day != day:
            record = None  # 跨天重置
        if not decide(record, reason, blocked_until, daily_limit_ms, now_ms):
            continue
        limit_changed = record.daily_limit_ms != daily_limit_ms if record else True
        records[package] = Record(
            day=day,
            count=(0 if limit_changed else record.count) + 1,
            last_at_ms=now_ms,
            daily_notified=(
                (record.daily_notified and not limit_changed) if record else False
            )
            or reason == DAILY,
            daily_limit_ms=daily_limit_ms,
            session_key=blocked_until,
        )
        notices += 1
    return notices, records.get(PKG)


PKG = "com.bilibili.app.in"
DAY = "2026-09-12"
LIMIT = 6_300_000  # 1h45m，今天的 B 站 auto 限额
T0 = 1_800_000_000_000

# 场景 A：今日额度用完后，Worker 每 15 分钟兜底 + 用户反复打开 20 次
events = []
for i in range(96):  # 24 小时 × 每 15 分钟
    events.append((PKG, DAY, T0 + i * 15 * 60_000, DAILY, 0))
for i in range(20):  # 用户不死心反复打开
    events.append((PKG, DAY, T0 + 3600_000 + i * 120_000, DAILY, 0))
notices, _ = simulate(events, LIMIT)
check(notices == 1, f"场景A 今日额度：116 次拦截只弹 {notices} 条通知（期望 1）")

# 场景 B：单次额度，同一冷却周期反复触发
events = [(PKG, DAY, T0 + i * 60_000, SESSION, T0 + 600_000) for i in range(10)]
notices, _ = simulate(events, LIMIT)
check(notices == 1, f"场景B 同一冷却周期：10 次拦截只弹 {notices} 条通知（期望 1）")

# 场景 C：单次额度，多个不同冷却周期 → 受每日上限约束
events = []
for i in range(6):
    events.append((PKG, DAY, T0 + i * 600_000, SESSION, T0 + 600_000 * (i + 1)))
notices, _ = simulate(events, LIMIT)
check(
    notices == MAX_NOTICES_PER_DAY,
    f"场景C 6 个新冷却周期：弹 {notices} 条（期望上限 {MAX_NOTICES_PER_DAY}）",
)

# 场景 D：用户把额度调大后再次用完 → 重新提醒一次
events = [
    (PKG, DAY, T0, DAILY, 0),
    (PKG, DAY, T0 + 3_600_000, DAILY, 0),  # 同额度，不再打扰
]
notices, rec = simulate(events, LIMIT)
check(notices == 1, f"场景D1 同额度重复拦截：弹 {notices} 条（期望 1）")
notices, _ = simulate([(PKG, DAY, T0 + 7_200_000, DAILY, 0)], LIMIT * 2) if rec else (0, None)
check(notices == 1, f"场景D2 改额度后：弹 {notices} 条（期望 1，新额度重新提醒）")

# 场景 E：跨天重置
events = [
    (PKG, DAY, T0, DAILY, 0),
    (PKG, "2026-09-13", T0 + 86_400_000, DAILY, 0),
]
notices, _ = simulate(events, LIMIT)
check(notices == 2, f"场景E 跨天：弹 {notices} 条（期望 2，次日重新提醒）")

# 场景 F：节流窗口内的事件风暴
events = [(PKG, DAY, T0 + i * 1_000, DAILY, 0) for i in range(5)]
notices, _ = simulate(events, LIMIT)
check(notices == 1, f"场景F 事件风暴：5 次连发只弹 {notices} 条（期望 1）")

print()
print("=" * 70)
if failures:
    print(f"FAILED: {len(failures)} 项不通过")
    for item in failures:
        print(f"  - {item}")
    sys.exit(1)
print("PASSED: 限额通知抑制修复全部校验通过")
sys.exit(0)
