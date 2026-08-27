"""把 Question_Reviewer.md 按问题类别拆分到 Question_Reviewer/ 文件夹。

拆分后目录结构：
    Question_Reviewer/
        README.md           - 目录说明与分类索引
        01_active_care.md
        02_android_frontend.md
        03_cpp_scheduler.md
        ...

只做一次性拆分，运行后即可删除。后续维护由 update_project_records.py 负责。
分类定义见 `question_categories.py`，新增/调整类别请改那里。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

# 让同目录下的 question_categories 可被导入
sys.path.insert(0, str(Path(__file__).resolve().parent))
from question_categories import CATEGORIES, categorize  # noqa: E402


# 条目标题正则：匹配 `### <ID> <title> (<date>)` 或 `### ISSUE-...` 或 `### Q20260...`
ENTRY_HEADER_RE = re.compile(
    r"^###\s+(?P<id>\S+(?:\s+\S+)*?)\s*\((?P<date>\d{4}-\d{2}-\d{2})\)\s*$"
)
# 也兼容形如 `### 10.141 标题（2026-06-28）` 全角括号
ENTRY_HEADER_RE_FULLWIDTH = re.compile(
    r"^###\s+(?P<id>\S+(?:\s+\S+)*?)\s*（(?P<date>\d{4}-\d{2}-\d{2})）\s*$"
)
# 子问题条目：`### 问题 1: <title>`（无日期，继承所在 section 的日期）
SUB_ISSUE_HEADER_RE = re.compile(r"^###\s+(?P<title>问题\s*\d+\s*[:：].*)$")
# 段落标题：`## 2026-06-17 P0 问题修复记录` 用作子问题日期回退
SECTION_DATE_RE = re.compile(r"^##\s+(?P<date>\d{4}-\d{2}-\d{2})\b")


@dataclass
class Entry:
    """单条 Question_Reviewer 记录。"""

    header: str  # 完整 header 行（含 ###）
    body: str   # header 之后到下一个 ### 之间的内容（含尾部空行）
    title: str  # 不含 ### 与日期的标题部分
    date: str   # YYYY-MM-DD


def parse_entries(content: str) -> list[Entry]:
    """按 `### ` 切分 Question_Reviewer.md。

    支持三种条目格式：
    1. `### <id> <title> (YYYY-MM-DD)` —— 主条目，自带日期
    2. `### <id> <title>（YYYY-MM-DD）` —— 全角括号变体
    3. `### 问题 N: <title>` —— 子问题，继承所在 `## YYYY-MM-DD ...` 段落日期
    """
    lines = content.splitlines()
    entries: list[Entry] = []
    current_header: str | None = None
    current_title: str | None = None
    current_date: str | None = None
    current_body: list[str] = []
    section_date: str | None = None  # 来自最近的 `## YYYY-MM-DD ...`

    def flush() -> None:
        nonlocal current_header, current_title, current_date, current_body
        if current_header is not None:
            # body 末尾的空行保留两条以保证 markdown 渲染
            body_text = "\n".join(current_body).rstrip() + "\n\n"
            entries.append(
                Entry(
                    header=current_header,
                    body=body_text,
                    title=current_title or "",
                    date=current_date or section_date or "",
                )
            )
        current_header = None
        current_title = None
        current_date = None
        current_body = []

    for line in lines:
        # 先识别段落日期（## YYYY-MM-DD ...），用于子问题回退
        section_match = SECTION_DATE_RE.match(line)
        if section_match:
            section_date = section_match.group("date")

        if line.startswith("### "):
            match = (
                ENTRY_HEADER_RE.match(line) or ENTRY_HEADER_RE_FULLWIDTH.match(line)
            )
            if match:
                flush()
                # 提取 title：去掉 ### 与 (date) 部分
                # group "id" 包含了 ID + 完整标题
                title_with_id = match.group("id").strip()
                current_header = line
                current_title = title_with_id
                current_date = match.group("date")
                continue

            # 子问题：`### 问题 N: <title>`
            sub_match = SUB_ISSUE_HEADER_RE.match(line)
            if sub_match:
                flush()
                title = sub_match.group("title").strip()
                # 子问题的 header 重写为带日期的格式，方便后续渲染与去重
                fallback_date = section_date or "unknown-date"
                current_header = f"### {title} ({fallback_date})"
                current_title = title
                current_date = fallback_date
                continue
        if current_header is not None:
            current_body.append(line)
    flush()
    return entries


def split_file(source: Path, target_dir: Path) -> dict[str, int]:
    """把 source 拆分到 target_dir 下若干分类文件。

    source 可以是：
    - 单个 .md 文件（如旧的 Question_Reviewer.md）
    - 一个目录（如已有的 Question_Reviewer/），会合并目录下所有 .md 文件后重新归类
    """
    target_dir.mkdir(parents=True, exist_ok=True)

    # 收集所有源内容
    if source.is_dir():
        # 从已有的分类文件夹读取：合并所有 .md（排除 README.md）
        contents: list[str] = []
        for md_file in sorted(source.glob("*.md")):
            if md_file.name.lower() == "readme.md":
                continue
            contents.append(md_file.read_text(encoding="utf-8"))
        if not contents:
            raise SystemExit(f"目录 {source} 下没有 .md 文件可拆分")
        merged_content = "\n\n".join(contents)
    elif source.is_file():
        merged_content = source.read_text(encoding="utf-8")
    else:
        raise SystemExit(f"找不到源: {source}")

    # 清理旧的分类文件，避免上一次拆分残留
    for old_file in target_dir.glob("*.md"):
        old_file.unlink()

    entries = parse_entries(merged_content)

    buckets: dict[str, list[Entry]] = {file_name: [] for file_name, _, _ in CATEGORIES}

    for entry in entries:
        file_name, _ = categorize(entry.title)
        buckets[file_name].append(entry)

    # 去重：同一 (title, date) 只保留一条
    seen_keys: set[tuple[str, str]] = set()
    for file_name in buckets:
        deduped: list[Entry] = []
        for entry in buckets[file_name]:
            key = (entry.title, entry.date)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(entry)
        buckets[file_name] = deduped

    counts: dict[str, int] = {}
    for file_name, display_name, _ in CATEGORIES:
        entries_in_bucket = buckets[file_name]
        counts[file_name] = len(entries_in_bucket)
        if not entries_in_bucket:
            continue

        lines: list[str] = [
            f"# {display_name}",
            "",
            f"本分类共 {len(entries_in_bucket)} 条记录。按时间倒序（最新在前）排列。",
            "",
            "---",
            "",
        ]
        # 按日期倒序；同日期按 title 排序保持稳定
        sorted_entries = sorted(
            entries_in_bucket, key=lambda e: (e.date, e.title), reverse=True
        )
        for entry in sorted_entries:
            lines.append(entry.header)
            lines.append("")  # header 与 body 之间空行
            lines.append(entry.body.rstrip())
            lines.append("")
        file_path = target_dir / f"{file_name}.md"
        file_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    return counts


def write_readme(target_dir: Path, counts: dict[str, int]) -> None:
    """生成 README.md，列出所有分类与条目数。"""
    lines: list[str] = [
        "# Question_Reviewer 问题回顾索引",
        "",
        "本目录由 `Question_Reviewer.md` 拆分而来，按问题类别归档。",
        "新增记录请通过 `scripts/doc_records/update_project_records.py` 自动写入对应分类文件。",
        "",
        "## 分类目录",
        "",
        "| 文件 | 类别 | 条目数 |",
        "|------|------|--------|",
    ]
    total = 0
    for file_name, display_name, _ in CATEGORIES:
        count = counts.get(file_name, 0)
        total += count
        if count > 0:
            lines.append(f"| [{file_name}.md]({file_name}.md) | {display_name} | {count} |")
    lines.append(f"| **合计** |  | **{total}** |")
    lines.append("")
    lines.append("## 分类规则")
    lines.append("")
    lines.append(
        "新增记录时，`update_project_records.py` 会按 entry 的 `category` 字段路由到对应文件；"
        "若未指定 `category`，则按标题关键词自动归类。"
    )
    lines.append("")
    target_dir.joinpath("README.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    source = project_root / "Question_Reviewer.md"
    target_dir = project_root / "Question_Reviewer"

    if not source.exists():
        raise SystemExit(f"找不到源文件: {source}")

    counts = split_file(source, target_dir)
    write_readme(target_dir, counts)

    print("拆分完成：")
    for file_name, display_name, _ in CATEGORIES:
        count = counts.get(file_name, 0)
        if count > 0:
            print(f"  {file_name}.md  ({display_name}): {count} 条")
    print(f"  输出目录: {target_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
