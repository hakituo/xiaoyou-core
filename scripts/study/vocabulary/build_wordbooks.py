"""重建 ECDICT 分级词书。

默认只生成并打印统计；显式传入 ``--write`` 才会覆盖 Words 目录成品。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.study.vocabulary.wordbook_builder import (  # noqa: E402
    DEFAULT_ECDICT_PATH,
    DEFAULT_OVERRIDES_PATH,
    DEFAULT_PROGRESS_PATH,
    DEFAULT_SENTENCE_DIR,
    DEFAULT_WORDS_DIR,
    build_wordbooks,
    write_wordbooks,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="基于 ECDICT 重建分级英语词书")
    parser.add_argument("--ecdict", type=Path, default=DEFAULT_ECDICT_PATH)
    parser.add_argument("--words-dir", type=Path, default=DEFAULT_WORDS_DIR)
    parser.add_argument("--sentence-dir", type=Path, default=DEFAULT_SENTENCE_DIR)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES_PATH)
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS_PATH)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="输出目录；默认与 words-dir 相同",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="确认写入成品；未指定时仅生成并打印统计",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="写入前备份现有词书；仅与 --write 一起生效",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    books, report = build_wordbooks(
        ecdict_path=args.ecdict,
        words_dir=args.words_dir,
        sentence_dir=args.sentence_dir,
        overrides_path=args.overrides,
        progress_path=args.progress,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.write:
        print("未指定 --write，未修改词书文件。")
        return 0

    output_dir = args.output_dir or args.words_dir
    backup_dir = args.backup_dir
    if backup_dir is None and output_dir.resolve() == args.words_dir.resolve():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = output_dir / "backups" / f"before_sense_cleanup_{stamp}"
    write_wordbooks(books, output_dir, backup_dir)
    print(f"已写入: {output_dir}")
    if backup_dir is not None:
        print(f"原词书备份: {backup_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
