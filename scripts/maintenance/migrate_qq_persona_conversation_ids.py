"""把 QQ 专属人设的聊天历史归档迁移到核心人设的 conversation_id。

背景
----
Aveline / Ling 不再维护 QQ 专属人设（``qq/Aveline_QQ_Master.json``、
``qq/Ling_QQ_Master.json`` 已删除），multi_qq_config.json 改为直接指向
``core_aveline.json`` / ``core_ling.json``。conversation_id 由 persona 文件名派生，
因此 QQ 会话的 cid 会从 ``__persona__aveline_qq_master`` 变成
``__persona__core_aveline``（Ling同理）。

chat_history 归档是按**精确 cid**分文件存储的，不迁移的话 QQ 会话历史会被切断
（新的归档写到新 cid，旧的留在旧 cid）。

注意：记忆（memories/ 下 short_term / weighted）不受影响——它们经
``resolve_memory_user_id`` 归一到 ``<base>__scope__<scope>``，同一角色的所有人设
本来就共享同一份记忆，本脚本不碰记忆目录。

用法::

    venv_core\\Scripts\\python.exe scripts\\maintenance\\migrate_qq_persona_conversation_ids.py            # 预演
    venv_core\\Scripts\\python.exe scripts\\maintenance\\migrate_qq_persona_conversation_ids.py --apply     # 执行

默认只预演，传入 ``--apply`` 才会原子写入。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPANION_DATA = PROJECT_ROOT / "companion_data"

# 旧 persona token -> 新 persona token（与 core_aveline.json / core_ling.json 的 slug 一致）
TOKEN_MIGRATIONS: Tuple[Tuple[str, str], ...] = (
    ("aveline_qq_master", "core_aveline"),
    ("ling_qq_master", "core_ling"),
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.atomic_io import safe_json_dump, safe_json_load, safe_write_text  # noqa: E402


def migrate_token(text: str) -> Tuple[str, bool]:
    """把文本里的旧 persona token 换成新 token，返回 (新文本, 是否发生替换)。"""
    result = str(text or "")
    changed = False
    for old, new in TOKEN_MIGRATIONS:
        if old in result:
            result = result.replace(old, new)
            changed = True
    return result, changed


def iter_chat_history_roots() -> List[Path]:
    """列出 companion_data 下所有 chat_history 目录。"""
    if not COMPANION_DATA.exists():
        return []
    return sorted(path for path in COMPANION_DATA.glob("*/chat_history") if path.is_dir())


def load_events(path: Path) -> List[Dict[str, Any]]:
    """读取 jsonl 事件；坏行原样丢弃（与 chat_history_store 的读法一致）。"""
    events: List[Dict[str, Any]] = []
    if not path.exists():
        return events
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                import json

                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                events.append(payload)
    return events


def event_sort_key(event: Dict[str, Any]) -> float:
    try:
        return float(event.get("timestamp") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def dedupe_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 event_id 去重（无 event_id 时退回 role+content+timestamp），并按时间排序。"""
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for event in sorted(events, key=event_sort_key):
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            event_id = "|".join(
                [
                    str(event.get("role") or ""),
                    str(event.get("content") or ""),
                    str(event.get("timestamp") or ""),
                ]
            )
        if event_id not in merged:
            order.append(event_id)
            merged[event_id] = event
    return [merged[key] for key in order]


def write_events(path: Path, events: List[Dict[str, Any]]) -> None:
    """原子写入 jsonl（事件顺序即写入顺序）。"""
    lines = []
    for event in events:
        import json

        lines.append(json.dumps(event, ensure_ascii=False))
    text = "\n".join(lines)
    if text:
        text += "\n"
    safe_write_text(text, str(path), use_fsync=True)


def update_day_index(index_path: Path, apply: bool) -> int:
    """把日期级 index.json 里的旧 cid/路径改写为新 cid/路径，返回改动条目数。"""
    payload = safe_json_load(str(index_path), default=None)
    if not isinstance(payload, dict):
        return 0
    files = payload.get("files")
    if not isinstance(files, list):
        return 0

    changed = 0
    seen: set = set()
    new_files: List[Dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict):
            new_files.append(item)
            continue
        new_item = dict(item)
        item_changed = False
        for key in ("relative_path", "name", "conversation_id"):
            raw = str(new_item.get(key) or "")
            migrated, hit = migrate_token(raw)
            if hit:
                new_item[key] = migrated
                item_changed = True
        if item_changed:
            changed += 1
        dedupe_key = (
            str(new_item.get("relative_path") or ""),
            str(new_item.get("conversation_id") or ""),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        new_files.append(new_item)

    if changed and apply:
        payload["files"] = new_files
        safe_json_dump(payload, str(index_path), use_fsync=True)
    return changed


def find_day_index(src: Path, root: Path) -> Path | None:
    """从源文件所在目录向上找日期级 index.json（位于 chat_history 根之下）。

    归档结构是 ``chat_history/YYYY/MM/DD/<分类>/<cid>.jsonl``，
    而 index.json 在日期目录里，不在分类目录，所以要向上找。
    """
    for parent in src.parents:
        if parent == root or root not in parent.parents:
            break
        candidate = parent / "index.json"
        if candidate.is_file():
            return candidate
    return None


def collect_migration_plan() -> List[Tuple[Path, Path, Path | None, int]]:
    """返回 [(源文件, 目标文件, 日期 index.json, 事件数)]，已过滤掉无需迁移的文件。"""
    plan: List[Tuple[Path, Path, Path | None, int]] = []
    for root in iter_chat_history_roots():
        for src in sorted(root.rglob("*.jsonl")):
            new_name, hit = migrate_token(src.name)
            if not hit:
                continue
            dst = src.with_name(new_name)
            plan.append((src, dst, find_day_index(src, root), len(load_events(src))))
    return plan


def run(apply: bool) -> int:
    plan = collect_migration_plan()
    if not plan:
        print("没有需要迁移的 chat_history 文件。")
        return 0

    total_events = sum(count for *_, count in plan)
    mode = "执行" if apply else "预演"
    print(f"[{mode}] 待迁移文件 {len(plan)} 个，事件 {total_events} 条")

    migrated_files = 0
    merged_files = 0
    migrated_events = 0
    touched_indexes: Dict[Path, int] = {}

    for src, dst, index_path, _ in plan:
        events = load_events(src)
        for event in events:
            cid = str(event.get("conversation_id") or "")
            new_cid, hit = migrate_token(cid)
            if hit:
                event["conversation_id"] = new_cid

        if dst.exists():
            existing = load_events(dst)
            for event in existing:
                cid = str(event.get("conversation_id") or "")
                new_cid, hit = migrate_token(cid)
                if hit:
                    event["conversation_id"] = new_cid
            events = dedupe_events(existing + events)
            merged_files += 1

        if apply:
            write_events(dst, events)
            src.unlink()
        migrated_files += 1
        migrated_events += len(events)

        # 同步日期级 index.json
        if index_path is not None and index_path.exists():
            changed = update_day_index(index_path, apply=apply)
            if changed:
                touched_indexes[index_path] = touched_indexes.get(index_path, 0) + changed

    print(
        f"[{mode}] 完成：文件 {migrated_files} 个（其中合并 {merged_files} 个），"
        f"事件 {migrated_events} 条，index.json {len(touched_indexes)} 个"
    )
    for path, changed in sorted(touched_indexes.items()):
        print(f"  index: {path.relative_to(COMPANION_DATA)} 改动 {changed} 条")
    if not apply:
        print("\n这是预演，未写入任何文件。确认无误后加 --apply 执行。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正执行迁移（默认只预演）",
    )
    args = parser.parse_args()
    return run(bool(args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
