"""验证文档记录脚本能正确更新临时副本。

覆盖：
1. UPDATES.md 仍按原样写到根目录开头
2. Question_Reviewer/ 文件夹按类别分文件追加
3. 自动归类（按标题关键词）与显式 category 字段都能正确路由
4. 首次创建分类文件时自动写入标准头部
5. 重复执行不应重复写入（去重）
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.doc_records.update_project_records import apply_payload


def _build_payload() -> dict:
    return {
        "updates": [
            {
                "date": "2026-06-30",
                "weekday": "二",
                "title": "文档记录脚本接入",
                "background": "以后不再手工改 UPDATES 和 Question_Reviewer",
                "fixes": [
                    "新增自动更新脚本",
                    "支持去重插入与追加",
                ],
                "verification": [
                    "venv_core\\Scripts\\python.exe tests\\scripts\\doc_records\\verify_update_project_records.py",
                ],
            }
        ],
        "question_reviewers": [
            # 1. 自动归类：标题含 "Active Care" → 01_active_care
            {
                "id": "11.99",
                "title": "Active Care 手工更新记录容易插错位置",
                "date": "2026-06-30",
                "problem": "手工维护两个文档时经常插错位置或重复追加",
                "steps": ["手工编辑记录文件", "多次追加后容易错位"],
                "expected": ["自动插到正确位置", "重复执行不应重复写入"],
                "actual": ["人工编辑容易混乱"],
                "root_causes": ["缺少统一维护脚本"],
                "fixes": ["新增 update_project_records.py"],
                "verification": [
                    "venv_core\\Scripts\\python.exe tests\\scripts\\doc_records\\verify_update_project_records.py",
                ],
            },
            # 2. 显式 category：直接指定写到 03_cpp_scheduler
            {
                "id": "11.100",
                "title": "C++ 调度器测试条目（显式 category）",
                "date": "2026-06-30",
                "problem": "验证 category 字段能直接路由到指定文件",
                "category": "03_cpp_scheduler",
                "fixes": ["通过 category 字段显式指定分类文件名"],
                "verification": [
                    "venv_core\\Scripts\\python.exe tests\\scripts\\doc_records\\verify_update_project_records.py",
                ],
            },
        ],
    }


def run_check() -> int:
    temp_root = pathlib.Path(tempfile.mkdtemp(prefix="doc-records-"))
    try:
        updates_path = temp_root / "UPDATES.md"
        question_dir = temp_root / "Question_Reviewer"
        updates_path.write_text(
            "## 2026-06-29（一）\n\n- **旧记录**\n  - **背景**: 用来验证插入顺序\n",
            encoding="utf-8",
        )
        # 不再预先创建 Question_Reviewer.md；脚本应当自动创建 Question_Reviewer/ 文件夹

        payload = _build_payload()

        first_result = apply_payload(payload, temp_root)
        second_result = apply_payload(payload, temp_root)
        updates_text = updates_path.read_text(encoding="utf-8")

        # 1. UPDATES 写入与去重
        if not first_result["updates_changed"]:
            print(f"FAIL: 首次执行没有写入 UPDATES: {json.dumps(first_result, ensure_ascii=False)}")
            return 1
        if second_result["updates_changed"]:
            print(f"FAIL: UPDATES 重复执行没有去重: {json.dumps(second_result, ensure_ascii=False)}")
            return 2
        if not updates_text.startswith("## 2026-06-30（二）"):
            print("FAIL: 新的 UPDATES 记录没有插到文件开头")
            return 3

        # 2. Question_Reviewer 按类别路由
        if not first_result["question_reviewer_changed"]:
            print(f"FAIL: 首次执行没有写入 Question_Reviewer: {json.dumps(first_result, ensure_ascii=False)}")
            return 4
        if second_result["question_reviewer_changed"]:
            print(f"FAIL: Question_Reviewer 重复执行没有去重: {json.dumps(second_result, ensure_ascii=False)}")
            return 5

        # 3. 自动归类：Active Care 应写到 01_active_care.md
        active_care_path = question_dir / "01_active_care.md"
        if not active_care_path.exists():
            print(f"FAIL: 自动归类没有生成 01_active_care.md，目录内容: {list(question_dir.glob('*.md'))}")
            return 6
        active_care_text = active_care_path.read_text(encoding="utf-8")
        if "### 11.99 Active Care 手工更新记录容易插错位置 (2026-06-30)" not in active_care_text:
            print("FAIL: 自动归类条目没有写入 01_active_care.md")
            return 7
        if "# Active Care 主动关怀" not in active_care_text:
            print("FAIL: 分类文件缺少标准头部")
            return 8

        # 4. 显式 category：应写到 03_cpp_scheduler.md
        cpp_path = question_dir / "03_cpp_scheduler.md"
        if not cpp_path.exists():
            print(f"FAIL: 显式 category 没有生成 03_cpp_scheduler.md，目录内容: {list(question_dir.glob('*.md'))}")
            return 9
        cpp_text = cpp_path.read_text(encoding="utf-8")
        if "### 11.100 C++ 调度器测试条目（显式 category） (2026-06-30)" not in cpp_text:
            print("FAIL: 显式 category 条目没有写入 03_cpp_scheduler.md")
            return 10

        # 5. 非法 category 应该报错
        try:
            apply_payload(
                {
                    "question_reviewers": [
                        {
                            "id": "X",
                            "title": "test",
                            "date": "2026-06-30",
                            "problem": "test",
                            "category": "99_not_exist",
                        }
                    ]
                },
                temp_root,
            )
            print("FAIL: 非法 category 没有报错")
            return 11
        except ValueError as e:
            if "99_not_exist" not in str(e):
                print(f"FAIL: 报错信息缺少类别名: {e}")
                return 12

        # 6. 旧的单文件 Question_Reviewer.md 不应该被创建
        if (temp_root / "Question_Reviewer.md").exists():
            print("FAIL: 仍写到了旧的 Question_Reviewer.md 单文件")
            return 13

        print("OK: UPDATES 开头插入、Question_Reviewer 分类路由、自动/显式归类、去重、错误处理全部通过")
        print(f"     分类文件: {sorted(p.name for p in question_dir.glob('*.md'))}")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(run_check())
