"""统一维护 UPDATES.md 与 Question_Reviewer/ 分类文件夹的记录脚本。

UPDATES.md 仍按原样写到项目根目录。
Question_Reviewer 已从单文件迁移为分类文件夹 `Question_Reviewer/`，
本脚本按 entry 的 `category` 字段（或标题自动归类）路由到对应分类文件。

question_reviewer entry 可选字段：
    category: 指定分类文件名（如 `01_active_care`），缺省时按标题自动归类
              合法值见 `question_categories.py` 的 CATEGORIES
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 让同目录下的 question_categories 可被导入
sys.path.insert(0, str(Path(__file__).resolve().parent))
from question_categories import CATEGORIES, resolve_category  # noqa: E402


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_text(file_path: Path) -> str:
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8")


def _write_text(file_path: Path, content: str) -> None:
    normalized = content.replace("\r\n", "\n").rstrip() + "\n"
    file_path.write_text(normalized, encoding="utf-8")


def _normalize_lines(items: list[str] | None) -> list[str]:
    return [str(item).strip() for item in (items or []) if str(item).strip()]


def _require_text(entry: dict[str, Any], field_name: str) -> str:
    value = str(entry.get(field_name, "")).strip()
    if not value:
        raise ValueError(f"字段 `{field_name}` 不能为空")
    return value


def render_updates_entry(entry: dict[str, Any]) -> tuple[str, str]:
    """渲染一条 UPDATES 记录，并返回去重 key。"""
    date_value = _require_text(entry, "date")
    weekday = _require_text(entry, "weekday")
    title = _require_text(entry, "title")
    background = _require_text(entry, "background")
    root_causes = _normalize_lines(entry.get("root_causes"))
    fixes = _normalize_lines(entry.get("fixes"))
    verification = _normalize_lines(entry.get("verification"))
    notes = _normalize_lines(entry.get("notes"))

    lines = [
        f"## {date_value}（{weekday}）",
        "",
        f"- **{title}**",
        f"  - **背景**: {background}",
    ]
    if root_causes:
        lines.append("  - **根因**:")
        lines.extend(f"    - {item}" for item in root_causes)
    if fixes:
        lines.append("  - **修复**:")
        lines.extend(f"    - {item}" for item in fixes)
    if verification:
        lines.append("  - **验证**:")
        lines.extend(f"    - `{item}`" for item in verification)
    if notes:
        lines.append("  - **备注**:")
        lines.extend(f"    - {item}" for item in notes)

    block = "\n".join(lines).rstrip() + "\n\n"
    dedupe_key = f"## {date_value}（{weekday}）\n\n- **{title}**"
    return block, dedupe_key


def render_question_entry(entry: dict[str, Any]) -> tuple[str, str, str]:
    """渲染一条 Question_Reviewer 记录。

    返回 (block, dedupe_key, category_file_name)。
    category_file_name 由 entry["category"] 或标题自动归类决定。
    """
    issue_id = _require_text(entry, "id")
    title = _require_text(entry, "title")
    date_value = _require_text(entry, "date")
    problem = _require_text(entry, "problem")
    steps = _normalize_lines(entry.get("steps"))
    expected = _normalize_lines(entry.get("expected"))
    actual = _normalize_lines(entry.get("actual"))
    root_causes = _normalize_lines(entry.get("root_causes"))
    fixes = _normalize_lines(entry.get("fixes"))
    verification = _normalize_lines(entry.get("verification"))

    # 渲染时把 issue_id 与 title 合在一起作为 header 的标题部分
    full_title = f"{issue_id} {title}"
    category_file_name, _ = resolve_category(
        title=f"{issue_id} {title}",  # 自动归类时把 ID 也带上以提高命中率
        explicit=entry.get("category"),
    )

    lines = [
        f"### {full_title} ({date_value})",
        f"*   **问题描述**: {problem}",
    ]
    if steps:
        lines.append("*   **复现步骤**:")
        lines.extend(f"    {index}. {item}" for index, item in enumerate(steps, start=1))
    if expected:
        lines.append("*   **预期行为**:")
        lines.extend(
            f"    {index}. {item}" for index, item in enumerate(expected, start=1)
        )
    if actual:
        lines.append("*   **实际行为**:")
        lines.extend(
            f"    {index}. {item}" for index, item in enumerate(actual, start=1)
        )
    if root_causes:
        lines.append("*   **根因**:")
        lines.extend(
            f"    {index}. {item}" for index, item in enumerate(root_causes, start=1)
        )
    if fixes:
        lines.append("*   **修复方案**:")
        lines.extend(
            f"    {index}. {item}" for index, item in enumerate(fixes, start=1)
        )
    if verification:
        lines.append("*   **验证**:")
        lines.extend(
            f"    {index}. `{item}`" for index, item in enumerate(verification, start=1)
        )

    block = "\n".join(lines).rstrip() + "\n\n"
    dedupe_key = f"### {full_title} ({date_value})"
    return block, dedupe_key, category_file_name


def prepend_unique_blocks(file_path: Path, blocks: list[tuple[str, str]]) -> bool:
    """把新块插到文件开头，已存在则跳过。"""
    existing = _read_text(file_path)
    new_parts: list[str] = []
    for block, dedupe_key in blocks:
        if dedupe_key in existing or dedupe_key in "".join(new_parts):
            continue
        new_parts.append(block)

    if not new_parts:
        return False

    new_content = "".join(new_parts) + existing.lstrip("\ufeff")
    _write_text(file_path, new_content)
    return True


def append_unique_blocks(file_path: Path, blocks: list[tuple[str, str]]) -> bool:
    """把新块追加到文件末尾，已存在则跳过。"""
    existing = _read_text(file_path)
    new_parts: list[str] = []
    for block, dedupe_key in blocks:
        if dedupe_key in existing or dedupe_key in "".join(new_parts):
            continue
        new_parts.append(block)

    if not new_parts:
        return False

    suffix = existing
    if suffix and not suffix.endswith("\n"):
        suffix += "\n"
    if suffix and not suffix.endswith("\n\n"):
        suffix += "\n"
    new_content = suffix + "".join(new_parts)
    _write_text(file_path, new_content)
    return True


def _ensure_category_file_header(
    file_path: Path, category_file_name: str, display_name: str
) -> None:
    """确保分类文件存在并带有标准头部。"""
    if file_path.exists():
        return
    header = (
        f"# {display_name}\n\n"
        f"本分类由 `update_project_records.py` 自动维护，新记录追加到末尾。\n"
        f"如需时间倒序查看，请运行 `scripts/doc_records/split_question_reviewer.py` 重新整理。\n\n"
        "---\n\n"
    )
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(header, encoding="utf-8")


def _category_display_name(category_file_name: str) -> str:
    """根据分类文件名反查中文显示名。"""
    for file_name, display_name, _ in CATEGORIES:
        if file_name == category_file_name:
            return display_name
    return "其他"


def apply_payload(
    payload: dict[str, Any], project_root: Path | None = None
) -> dict[str, Any]:
    """根据 payload 更新项目记录文件。"""
    effective_root = project_root or _default_project_root()
    updates_path = effective_root / "UPDATES.md"
    question_dir = effective_root / "Question_Reviewer"

    # 1. UPDATES.md 仍按原样写到根目录开头
    update_blocks = [
        render_updates_entry(entry) for entry in payload.get("updates", []) or []
    ]
    changed_updates = prepend_unique_blocks(updates_path, update_blocks)

    # 2. Question_Reviewer 按类别分文件追加
    # 每个 entry 多返回一个 category_file_name，按类别分组
    buckets: dict[str, list[tuple[str, str]]] = {}
    changed_categories: set[str] = set()
    for entry in payload.get("question_reviewers", []) or []:
        block, dedupe_key, category_file_name = render_question_entry(entry)
        buckets.setdefault(category_file_name, []).append((block, dedupe_key))

    for category_file_name, blocks in buckets.items():
        target_path = question_dir / f"{category_file_name}.md"
        display_name = _category_display_name(category_file_name)
        _ensure_category_file_header(target_path, category_file_name, display_name)
        if append_unique_blocks(target_path, blocks):
            changed_categories.add(category_file_name)

    return {
        "updates_changed": changed_updates,
        "question_reviewer_changed": bool(changed_categories),
        "question_reviewer_categories_changed": sorted(changed_categories),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="统一维护 UPDATES.md 与 Question_Reviewer/ 分类文件夹",
    )
    parser.add_argument(
        "--payload-file",
        required=True,
        help="JSON 载荷文件路径",
    )
    parser.add_argument(
        "--project-root",
        default=str(_default_project_root()),
        help="项目根目录，默认自动定位当前仓库根目录",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    payload_path = Path(args.payload_file).resolve()
    if not payload_path.exists():
        parser.error(f"找不到 payload 文件: {payload_path}")

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    result = apply_payload(payload, Path(args.project_root).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
