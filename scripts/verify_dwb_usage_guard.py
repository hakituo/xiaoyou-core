"""验证数字健康用量护栏: 用真实 app_usage.jsonl 模拟 read_today_app_usage 的过滤,
确认被 24h 窗口污染的 bilibili 不再误判超限。"""
import json
from datetime import datetime, timezone

JSONL = r"d:\AI\xiaoyou-core\companion_data\user_data\daily\2026\08\23\app_usage.jsonl"
LIMITS = r"d:\AI\xiaoyou-core\companion_data\user_data\digital_wellbeing\limits_2026-08-23.json"


def _parse_dt(s):
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _is_plausible_today_usage(rec):
    usage_ms = int(rec.get("usage_time_ms", 0) or 0)
    if usage_ms <= 0:
        return True
    last_used = _parse_dt(rec.get("last_used_time"))
    st = _parse_dt(rec.get("server_timestamp"))
    if last_used is None or st is None:
        return True
    today_midnight_utc = st.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    if last_used < today_midnight_utc and usage_ms > 5 * 60 * 1000:
        return False
    return True


def read_today_app_usage(path):
    latest = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            pkg = rec.get("package_name")
            if not pkg or not _is_plausible_today_usage(rec):
                continue
            st = rec.get("server_timestamp", "")
            if pkg not in latest or st > latest[pkg].get("server_timestamp", ""):
                latest[pkg] = rec
    return latest


def main():
    usage = read_today_app_usage(JSONL)
    with open(LIMITS, encoding="utf-8") as f:
        limits = json.load(f).get("limits", {})

    print("=== 过滤后各应用今日用量(最新一条) ===")
    for pkg, rec in sorted(usage.items()):
        print(f"  {pkg:20s} usage={int(rec.get('usage_time_ms',0))/60000:6.1f}m  "
              f"last_used={rec.get('last_used_time')}")

    print("\n=== 超限判定(护栏后) ===")
    exceeded = []
    for pkg, rec in usage.items():
        lim = int(limits.get(pkg, {}).get("limit_ms", 0) or 0)
        u = int(rec.get("usage_time_ms", 0) or 0)
        if lim > 0 and u > lim:
            exceeded.append((pkg, u, lim))
            print(f"  [超限] {pkg}: {u/60000:.1f}m > {lim/60000:.1f}m")
    if not exceeded:
        print("  无应用超限 (bilibili 不再误报)")
    print("\nbilibili 是否在超限列表:", "bilibili" in [p for p, _, _ in exceeded])


if __name__ == "__main__":
    main()
