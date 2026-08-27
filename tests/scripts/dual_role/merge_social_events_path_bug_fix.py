"""一次性脚本：合并 social_events 路径 bug 导致的数据分裂

背景：
- core/services/dual_role/social_events.py 历史路径少算一级，
  把新事件写入了 core/companion_data/dual_role/social_events/default.json
- 历史数据仍在项目根的 companion_data/dual_role/social_events/default.json
- 现已修复代码改用 get_dual_role_data_dir()，本脚本负责把两份数据按 ts
  去重合并回正确路径，并删除 core/companion_data 脏目录。

使用方法：
    venv_core\\Scripts\\python.exe tests\\scripts\\dual_role\\merge_social_events_path_bug_fix.py
"""
import json
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

CORRECT = PROJECT_ROOT / "companion_data" / "dual_role" / "social_events" / "default.json"
DIRTY = PROJECT_ROOT / "core" / "companion_data" / "dual_role" / "social_events" / "default.json"
BACKUP_DIR = PROJECT_ROOT / "companion_data" / "dual_role" / "social_events" / "_backup_before_path_bug_fix_20260801"
DIRTY_ROOT = PROJECT_ROOT / "core" / "companion_data"


def load_events(path: Path) -> list:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    events = payload.get("events") if isinstance(payload, dict) else []
    return [ev for ev in events if isinstance(ev, dict)]


def main() -> None:
    if not CORRECT.exists():
        raise SystemExit(f"正确路径文件不存在: {CORRECT}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CORRECT, BACKUP_DIR / "default.json")
    if DIRTY.exists():
        shutil.copy2(DIRTY, BACKUP_DIR / "default_dirty.json")
    print(f"[1/4] 备份完成: {BACKUP_DIR}")

    correct_events = load_events(CORRECT)
    dirty_events = load_events(DIRTY)
    print(f"[2/4] 正确路径 {len(correct_events)} 条，错误路径 {len(dirty_events)} 条")

    merged = []
    seen_ts = set()
    for ev in correct_events + dirty_events:
        ts = ev.get("ts")
        if ts is None or ts in seen_ts:
            continue
        seen_ts.add(ts)
        merged.append(ev)
    merged.sort(key=lambda x: float(x.get("ts", 0)))
    recent = merged[-24:]

    CORRECT.write_text(
        json.dumps(
            {"conversation_id": "default", "events": recent},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[3/4] 合并去重后共 {len(merged)} 条，写入最近 {len(recent)} 条到 {CORRECT}")

    if DIRTY_ROOT.exists():
        shutil.rmtree(DIRTY_ROOT)
        print(f"[4/4] 已删除脏目录: {DIRTY_ROOT}")
    else:
        print("[4/4] 脏目录已不存在，跳过")


if __name__ == "__main__":
    main()
