"""验证 UPDATES.md 按日期拆分的切割、索引与入口生成逻辑。

覆盖：
1. `parse_blocks` 按 `## YYYY-MM-DD` 切块，日期标题之前的前言单独返回
2. `split_to_daily` 把同一天的历史块反转成「早 → 晚」，写入当天文件
3. `migrate` 在临时仓库里生成 `docs/updates/YYYY/MM/YYYY-MM-DD.md`、索引与根入口
4. 拆分不丢失内容：所有块内容与索引条目数一致
5. `--index` 模式可重建索引与入口，`--check` 在结构一致时通过、被改坏时报错
6. 日期文件路径/文件名/块日期不一致时 `scan_daily_dir` 直接报错
"""

from __future__ import annotations

import contextlib
import io
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.doc_records.split_updates_to_daily import (  # noqa: E402
    check,
    daily_relpath,
    migrate,
    parse_blocks,
    rebuild_index,
    render_entry,
    render_index,
    scan_daily_dir,
    split_to_daily,
)

SOURCE_TEXT = (
    "## 2026-06-30（二）\n"
    "\n"
    "- **第二条（同一天，较新）**\n"
    "  - **背景**: 用于验证天内顺序\n"
    "\n"
    "## 2026-06-30（二）\n"
    "\n"
    "- **第一条（同一天，较早）**\n"
    "  - **背景**: 用于验证天内顺序\n"
    "\n"
    "## 2026-06-29（一）\n"
    "\n"
    "- **更早的一天**\n"
    "  - **背景**: 用于验证跨天排序\n"
)


def _silent(func, *args, **kwargs):
    """静音被测函数的打印，返回 (返回值, 输出文本)。"""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = func(*args, **kwargs)
    return result, buffer.getvalue()


def run_check() -> int:
    # 1. 切块与前言的分离
    preamble, blocks = parse_blocks("前言\n\n" + SOURCE_TEXT)
    if len(blocks) != 3:
        print(f"FAIL: 切块数量不对: {len(blocks)}")
        return 1
    if [date_value for date_value, _ in blocks] != [
        "2026-06-30",
        "2026-06-30",
        "2026-06-29",
    ]:
        print(f"FAIL: 切块日期不对: {[date for date, _ in blocks]}")
        return 2
    if "".join(preamble).strip() != "前言":
        print(f"FAIL: 前言没有单独返回: {preamble!r}")
        return 3

    # 2. 天内顺序反转：原文件「最新在前」→ 当天文件「早到晚」
    daily = split_to_daily(blocks)
    if list(daily) != ["2026-06-30", "2026-06-29"]:
        print(f"FAIL: 日期分组顺序不对: {list(daily)}")
        return 4
    same_day = "".join(daily["2026-06-30"])
    if same_day.index("第一条") > same_day.index("第二条"):
        print("FAIL: 同一天的块没有按「早到晚」排列")
        return 5
    if len(daily["2026-06-29"]) != 1:
        print("FAIL: 06-29 分组数量不对")
        return 6

    # 3. 索引与入口渲染
    index_text = render_index(daily)
    if "[2026-06-30](2026/06/2026-06-30.md)" not in index_text:
        print("FAIL: 索引缺少 06-30 链接")
        return 7
    if "[2026-06-29](2026/06/2026-06-29.md)" not in index_text:
        print("FAIL: 索引缺少 06-29 链接")
        return 8
    if "## 2026-06" not in index_text:
        print("FAIL: 索引缺少月份分组标题")
        return 9
    entry_text = render_entry(daily)
    if "docs/updates/2026/06/2026-06-30.md" not in entry_text:
        print("FAIL: 入口缺少最新日期链接")
        return 10
    if "## 2026-06-30（二）" in entry_text:
        print("FAIL: 入口里不应包含完整记录正文")
        return 11

    # 4. 迁移：临时仓库里真实写盘
    temp_root = pathlib.Path(tempfile.mkdtemp(prefix="updates-split-"))
    try:
        (temp_root / "UPDATES.md").write_text(SOURCE_TEXT, encoding="utf-8")
        written, total_entries = migrate(temp_root)
        if written != 2 or total_entries != 3:
            print(f"FAIL: 迁移统计不对: written={written}, total={total_entries}")
            return 12

        same_day_path = temp_root / "docs" / "updates" / daily_relpath("2026-06-30")
        prev_day_path = temp_root / "docs" / "updates" / daily_relpath("2026-06-29")
        for path in (same_day_path, prev_day_path):
            if not path.exists():
                print(f"FAIL: 没有生成日期文件 {path}")
                return 13

        same_day_file = same_day_path.read_text(encoding="utf-8")
        if same_day_file.index("第一条") > same_day_file.index("第二条"):
            print("FAIL: 当天文件内顺序不是「早到晚」")
            return 14
        if same_day_file.count("## 2026-06-30") != 2:
            print("FAIL: 当天文件丢失了块标题")
            return 15

        scanned = scan_daily_dir(temp_root / "docs" / "updates")
        if scanned != daily:
            print(f"FAIL: 回读结果与原分组不一致: {sorted(scanned)}")
            return 16

        # 5. --index 幂等 + --check 通过
        changed = rebuild_index(temp_root)
        if changed:
            print("FAIL: 刚迁移完再重建索引不应有变化")
            return 17
        code, output = _silent(check, temp_root)
        if code != 0:
            print(f"FAIL: check 未通过: {output.strip()}")
            return 18

        # 6. 索引被改坏时 check 应报错
        index_path = temp_root / "docs" / "updates" / "README.md"
        index_path.write_text(
            index_path.read_text(encoding="utf-8") + "手工追加的一行\n", encoding="utf-8"
        )
        code, output = _silent(check, temp_root)
        if code == 0 or "README.md" not in output:
            print("FAIL: 索引被改坏后 check 没有报错")
            return 19

        # 7. 文件名日期与块日期不一致时直接报错
        bad_path = temp_root / "docs" / "updates" / "2026" / "07" / "2026-07-01.md"
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text("## 2026-06-30（二）\n\n- **日期错位**\n", encoding="utf-8")
        code, output = _silent(check, temp_root)
        if code == 0 or "不一致" not in output:
            print("FAIL: 块日期与文件名不一致时没有报错")
            return 20

        print("OK: 切块、天内排序、迁移写盘、索引/入口生成、--index 幂等、--check 校验全部通过")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(run_check())
