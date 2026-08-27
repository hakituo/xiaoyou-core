"""把 persona 中文别名目录安全合并到 ``meta.scope`` 目录。

默认仅预览；确认后加 ``--write`` 执行。遇到非 sessions.json 的同名不同内容
文件会保留源文件并报告冲突，不会静默覆盖。
"""

from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.scope_registry import list_dynamic_scopes, refresh_scope_registry  # noqa: E402


@dataclass
class MigrationReport:
    moved: list[tuple[Path, Path]] = field(default_factory=list)
    deduplicated: list[Path] = field(default_factory=list)
    merged_sessions: list[tuple[Path, Path]] = field(default_factory=list)
    conflicts: list[tuple[Path, Path]] = field(default_factory=list)


def _canonical_relative_path(relative: Path, alias: str, scope: str) -> Path:
    old_marker = f"__scope__{alias}"
    new_marker = f"__scope__{scope}"
    return Path(*(part.replace(old_marker, new_marker) for part in relative.parts))


def _merge_session_payload(source: Path, target: Path) -> list[dict] | None:
    try:
        source_rows = json.loads(source.read_text(encoding="utf-8"))
        target_rows = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(source_rows, list) or not isinstance(target_rows, list):
        return None

    merged: dict[str, dict] = {}
    anonymous: list[dict] = []
    for row in [*target_rows, *source_rows]:
        if not isinstance(row, dict):
            continue
        session_id = str(row.get("id") or "").strip()
        if not session_id:
            anonymous.append(row)
            continue
        previous = merged.get(session_id)
        if previous is None or float(row.get("updated_at") or 0) >= float(
            previous.get("updated_at") or 0
        ):
            merged[session_id] = row
    return [*merged.values(), *anonymous]


def _move_file(
    source: Path,
    target: Path,
    *,
    write: bool,
    report: MigrationReport,
) -> None:
    if not target.exists():
        report.moved.append((source, target))
        if write:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        return

    if filecmp.cmp(source, target, shallow=False):
        report.deduplicated.append(source)
        if write:
            source.unlink()
        return

    if source.name == "sessions.json" and target.name == "sessions.json":
        merged = _merge_session_payload(source, target)
        if merged is not None:
            report.merged_sessions.append((source, target))
            if write:
                target.write_text(
                    json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                source.unlink()
            return

    report.conflicts.append((source, target))


def _prune_empty_dirs(source_dir: Path) -> None:
    for directory in sorted(
        (path for path in source_dir.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        source_dir.rmdir()
    except OSError:
        pass


def merge_registered_scope_dirs(
    base_dir: Path,
    *,
    write: bool = False,
    registry: dict[str, dict] | None = None,
) -> MigrationReport:
    """合并已注册 scope 的别名目录；可注入 registry 供验证脚本使用。"""
    report = MigrationReport()
    scopes = registry if registry is not None else list_dynamic_scopes()
    base_dir = Path(base_dir).resolve()

    for scope, info in scopes.items():
        target_dir = base_dir / f"{scope}_data"
        for alias in info.get("slugs", []):
            alias = str(alias).strip()
            if not alias or alias == scope:
                continue
            source_dir = base_dir / f"{alias}_data"
            if not source_dir.exists():
                continue
            for source in sorted(path for path in source_dir.rglob("*") if path.is_file()):
                relative = source.relative_to(source_dir)
                canonical_relative = _canonical_relative_path(relative, alias, scope)
                _move_file(
                    source,
                    target_dir / canonical_relative,
                    write=write,
                    report=report,
                )
            if write:
                _prune_empty_dirs(source_dir)
    return report


def _print_report(report: MigrationReport, *, write: bool) -> None:
    prefix = "已执行" if write else "预览"
    for source, target in report.moved:
        print(f"[{prefix}] 移动: {source} -> {target}")
    for source in report.deduplicated:
        print(f"[{prefix}] 删除完全重复文件: {source}")
    for source, target in report.merged_sessions:
        print(f"[{prefix}] 合并会话索引: {source} -> {target}")
    for source, target in report.conflicts:
        print(f"[冲突保留] {source} != {target}")
    print(
        "汇总: "
        f"移动 {len(report.moved)}, 去重 {len(report.deduplicated)}, "
        f"会话合并 {len(report.merged_sessions)}, 冲突 {len(report.conflicts)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="合并 persona 别名数据目录")
    parser.add_argument("--write", action="store_true", help="实际执行；默认仅预览")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=PROJECT_ROOT / "companion_data",
        help="数据根目录",
    )
    args = parser.parse_args()

    refresh_scope_registry()
    report = merge_registered_scope_dirs(args.base_dir, write=args.write)
    _print_report(report, write=args.write)
    return 2 if report.conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
