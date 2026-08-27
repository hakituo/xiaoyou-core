"""裁剪已膨胀的 short_term 文件到容量上限

背景:
    三个 bug 叠加导致 short_term 文件膨胀:
    1. load_memory 不 trim → 启动后保持膨胀
    2. backfill 追加 + trim 延迟 30s → 多次启动后指数膨胀
    3. important 消息不占配额 → peer_aveline/peer_ling 100% important 时 trim 无效

    现已修复三个 bug,本脚本用于一次性裁剪已落盘的膨胀文件。
    复用 distillation.py 的新 trim 逻辑(important/普通 各占 50% 配额)。

用法:
    # 先 dry-run 查看会裁剪什么
    python tests/scripts/memory/trim_bloated_short_term.py --dry-run

    # 实际执行裁剪
    python tests/scripts/memory/trim_bloated_short_term.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 复用项目的 trim 逻辑
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from memory.core.distillation import trim_short_term_memory  # noqa: E402

# 与 app.yaml 的 short_term_capacity 保持一致
MAX_SHORT_TERM = 60
COMPANION_DATA = PROJECT_ROOT / "companion_data"


def _noop_detect_topics(_text: str) -> list:
    """trim_short_term_memory 需要 detect_topics_fn 参数,但实际未使用"""
    return []


def find_short_term_files() -> list[Path]:
    """扫描 companion_data 下所有 short_term 目录的 *_short.json 文件"""
    results: list[Path] = []
    if not COMPANION_DATA.exists():
        return results
    for data_dir in COMPANION_DATA.iterdir():
        if not data_dir.is_dir():
            continue
        short_term_dir = data_dir / "memories" / "short_term"
        if not short_term_dir.is_dir():
            continue
        for f in short_term_dir.glob("*_short.json"):
            if f.is_file():
                results.append(f)
    return results


def trim_file(file_path: Path, dry_run: bool) -> tuple[int, int]:
    """裁剪单个 short_term 文件,返回 (原记录数, 裁剪后记录数)"""
    try:
        raw = file_path.read_text(encoding="utf-8")
        records = json.loads(raw)
    except Exception as e:
        print(f"  [跳过] 读取失败: {file_path.name} - {e}")
        return (0, 0)

    if not isinstance(records, list):
        print(f"  [跳过] 格式非数组: {file_path.name}")
        return (0, 0)

    original_count = len(records)
    if original_count <= MAX_SHORT_TERM:
        return (original_count, original_count)

    # 应用新的 trim 逻辑
    trimmed, removed = trim_short_term_memory(
        records,
        MAX_SHORT_TERM,
        _noop_detect_topics,
    )
    cleaned_count = len(trimmed)

    role = file_path.parent.parent.parent.name  # aveline_data / ling_data / dual_role
    removed_count = original_count - cleaned_count
    print(f"  [{role}] {file_path.name}: "
          f"裁剪 {removed_count} 条 (原 {original_count} -> 剩 {cleaned_count})")

    # 统计被裁剪消息的来源
    if removed:
        import collections
        sources = collections.Counter(m.get("source", "?") for m in removed)
        cats = collections.Counter(m.get("category", "?") for m in removed)
        imps = sum(1 for m in removed if m.get("is_important"))
        print(f"    被裁剪: important={imps}, sources={dict(sources)}, cats={dict(cats)}")

    if not dry_run and removed:
        # 原子写入
        tmp_path = file_path.with_suffix(".json.tmp_trim")
        tmp_path.write_text(
            json.dumps(trimmed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(file_path)

    return (original_count, cleaned_count)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="裁剪已膨胀的 short_term 文件到容量上限"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只报告会裁剪什么,不实际修改文件",
    )
    args = parser.parse_args()

    mode = "[DRY-RUN] " if args.dry_run else ""
    print(f"{mode}扫描 short_term 膨胀文件 (容量上限: {MAX_SHORT_TERM} 条)")
    print(f"扫描目录: {COMPANION_DATA}\n")

    short_term_files = find_short_term_files()
    if not short_term_files:
        print("未找到任何 short_term 文件")
        return 0

    print(f"发现 {len(short_term_files)} 个 short_term 文件\n")

    total_original = 0
    total_cleaned = 0
    files_trimmed = 0

    for f in sorted(short_term_files):
        orig, cleaned = trim_file(f, args.dry_run)
        total_original += orig
        total_cleaned += cleaned
        if orig > cleaned:
            files_trimmed += 1

    print(f"\n--- 汇总 ---")
    print(f"扫描文件: {len(short_term_files)}")
    print(f"需裁剪文件: {files_trimmed}")
    print(f"总记录数: {total_original}")
    print(f"裁剪后记录数: {total_cleaned}")
    print(f"删除记录: {total_original - total_cleaned}")
    if args.dry_run:
        print("(DRY-RUN 模式,未实际修改文件)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
