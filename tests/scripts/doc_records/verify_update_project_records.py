"""验证文档记录脚本能正确更新临时副本。

覆盖：
1. updates entry 按日期写入 `docs/updates/YYYY/MM/YYYY-MM-DD.md`：当天文件不存在则创建、
   已存在则追加到末尾，不覆盖历史记录
2. 重复执行不重复写入（去重），也不需要修订时不动当天文件
3. 索引 `docs/updates/README.md` 与根 `UPDATES.md` 入口随日期文件自动重建
4. 不属于本次日期的日期文件不被改动
5. Question_Reviewer/ 文件夹按类别分文件追加
6. 自动归类（按标题关键词）与显式 category 字段都能正确路由
7. 首次创建分类文件时自动写入标准头部
8. 同 ID 记录允许修订，单个字符串字段不会被逐字拆分
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

from scripts.doc_records.update_project_records import apply_payload  # noqa: E402

SAME_DAY_OLD_BLOCK = "## 2026-06-30（二）\n\n- **旧记录**\n  - **背景**: 用来验证追加顺序\n"
PREV_DAY_BLOCK = "## 2026-06-29（一）\n\n- **前一天记录**\n  - **背景**: 不应被本次写入改动\n"


def _build_payload() -> dict:
    return {
        "updates": [
            {
                "date": "2026-06-30",
                "weekday": "二",
                "title": "文档记录脚本接入",
                "background": "以后不再手工改更新日志和 Question_Reviewer",
                "fixes": [
                    "更新日志改为按日期写入 docs/updates/",
                    "索引与根入口自动重建",
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
        updates_month_dir = temp_root / "docs" / "updates" / "2026" / "06"
        updates_month_dir.mkdir(parents=True)
        same_day_path = updates_month_dir / "2026-06-30.md"
        same_day_path.write_text(SAME_DAY_OLD_BLOCK, encoding="utf-8")
        prev_day_path = updates_month_dir / "2026-06-29.md"
        prev_day_path.write_text(PREV_DAY_BLOCK, encoding="utf-8")
        question_dir = temp_root / "Question_Reviewer"

        payload = _build_payload()

        first_result = apply_payload(payload, temp_root)
        second_result = apply_payload(payload, temp_root)
        same_day_text = same_day_path.read_text(encoding="utf-8")

        # 1. 写入目标：docs/updates/YYYY/MM/YYYY-MM-DD.md
        if not first_result["updates_changed"]:
            print(f"FAIL: 首次执行没有写入更新记录: {json.dumps(first_result, ensure_ascii=False)}")
            return 1
        if not same_day_path.exists():
            print("FAIL: 没有写到 docs/updates/2026/06/2026-06-30.md")
            return 2
        if (temp_root / "UPDATES.md").read_text(encoding="utf-8").count("## 2026-06-30") > 0:
            print("FAIL: 记录仍然写进了根 UPDATES.md（应只保留入口）")
            return 3

        # 2. 当天历史记录保留 + 新记录追加到末尾
        if not same_day_text.startswith(SAME_DAY_OLD_BLOCK.rstrip("\n")):
            print("FAIL: 当天历史记录被覆盖或顺序被打乱")
            return 4
        if same_day_text.index("旧记录") > same_day_text.index("文档记录脚本接入"):
            print("FAIL: 新记录没有追加到当天文件末尾")
            return 5

        # 3. 重复执行去重
        if second_result["updates_changed"]:
            print(f"FAIL: updates 重复执行没有去重: {json.dumps(second_result, ensure_ascii=False)}")
            return 6
        if same_day_path.read_text(encoding="utf-8") != same_day_text:
            print("FAIL: 重复执行改动了当天文件")
            return 7

        # 4. 非本次日期的文件不被改动
        if prev_day_path.read_text(encoding="utf-8") != PREV_DAY_BLOCK:
            print("FAIL: 非本次日期的文件被改动")
            return 8

        # 5. 索引与根入口按现存日期文件重建
        index_path = temp_root / "docs" / "updates" / "README.md"
        if not index_path.exists():
            print("FAIL: 没有生成 docs/updates/README.md 索引")
            return 9
        index_text = index_path.read_text(encoding="utf-8")
        if "[2026-06-30](2026/06/2026-06-30.md)" not in index_text:
            print("FAIL: 索引里缺少 2026-06-30 链接")
            return 10
        if "[2026-06-29](2026/06/2026-06-29.md)" not in index_text:
            print("FAIL: 索引里缺少已存在的 2026-06-29 链接")
            return 11
        entry_text = (temp_root / "UPDATES.md").read_text(encoding="utf-8")
        if "docs/updates/2026/06/2026-06-30.md" not in entry_text:
            print("FAIL: 根入口没有指向最新日期文件")
            return 12

        # 6. Question_Reviewer 按类别路由
        if not first_result["question_reviewer_changed"]:
            print(f"FAIL: 首次执行没有写入 Question_Reviewer: {json.dumps(first_result, ensure_ascii=False)}")
            return 13
        if second_result["question_reviewer_changed"]:
            print(f"FAIL: Question_Reviewer 重复执行没有去重: {json.dumps(second_result, ensure_ascii=False)}")
            return 14

        corrected_payload = _build_payload()
        corrected_payload["question_reviewers"][0]["actual"] = "修订后的实际行为"
        corrected_payload["question_reviewers"][0]["title"] = "Active Care 记录标题也已修订"
        corrected_result = apply_payload(corrected_payload, temp_root)
        if not corrected_result["question_reviewer_changed"]:
            print("FAIL: 同 ID Question_Reviewer 内容变化后没有原位修订")
            return 15

        # 7. 自动归类：Active Care 应写到 01_active_care.md
        active_care_path = question_dir / "01_active_care.md"
        if not active_care_path.exists():
            print(f"FAIL: 自动归类没有生成 01_active_care.md，目录内容: {list(question_dir.glob('*.md'))}")
            return 16
        active_care_text = active_care_path.read_text(encoding="utf-8")
        if "### 11.99 Active Care 记录标题也已修订 (2026-06-30)" not in active_care_text:
            print("FAIL: 自动归类条目没有写入 01_active_care.md")
            return 17
        if "# Active Care 主动关怀" not in active_care_text:
            print("FAIL: 分类文件缺少标准头部")
            return 18
        if active_care_text.count("### 11.99 ") != 1:
            print("FAIL: 同 ID 修订产生重复记录")
            return 19
        if "    1. 修订后的实际行为" not in active_care_text:
            print("FAIL: 单个字符串字段被错误拆分或未完成修订")
            return 20

        # 8. 显式 category：应写到 03_cpp_scheduler.md
        cpp_path = question_dir / "03_cpp_scheduler.md"
        if not cpp_path.exists():
            print(f"FAIL: 显式 category 没有生成 03_cpp_scheduler.md，目录内容: {list(question_dir.glob('*.md'))}")
            return 21
        cpp_text = cpp_path.read_text(encoding="utf-8")
        if "### 11.100 C++ 调度器测试条目（显式 category） (2026-06-30)" not in cpp_text:
            print("FAIL: 显式 category 条目没有写入 03_cpp_scheduler.md")
            return 22

        # 9. 非法 category 应该报错
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
            return 23
        except ValueError as e:
            if "99_not_exist" not in str(e):
                print(f"FAIL: 报错信息缺少类别名: {e}")
                return 24

        # 10. 旧的单文件 Question_Reviewer.md 不应该被创建
        if (temp_root / "Question_Reviewer.md").exists():
            print("FAIL: 仍写到了旧的 Question_Reviewer.md 单文件")
            return 25

        print("OK: 日期文件写入/追加、去重、索引与入口重建、Question_Reviewer 分类路由全部通过")
        print(f"     分类文件: {sorted(p.name for p in question_dir.glob('*.md'))}")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(run_check())
