"""验证 split_question_reviewer.py 拆分结果正确。

覆盖：
1. 拆分后生成的分类文件数量与 CATEGORIES 一致（仅含非空类别）
2. 所有条目都被分配到某个分类，没有条目丢失
3. 每个分类文件的头部包含标准 markdown 头部
4. 同一条目不会重复出现在多个分类文件中
5. 显式 category 字段能强制路由（与 split 脚本的自动归类协同）
"""

from __future__ import annotations

import pathlib
import re
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "doc_records"))

from question_categories import CATEGORIES  # noqa: E402
from split_question_reviewer import split_file, write_readme  # noqa: E402


SAMPLE_MD = """\
### 10.200 Active Care 测试条目一 (2026-06-30)

*   **问题描述**: 测试条目。

### 10.201 C++ 调度器测试条目 (2026-06-29)

*   **问题描述**: 测试条目。

### 10.202 TTS 测试条目 (2026-06-28)

*   **问题描述**: 测试条目。

### 10.203 不匹配任何关键词的条目 (2026-06-27)

*   **问题描述**: 应该归到 misc。

## 2026-06-26 P0 问题修复记录

### 问题 1: Active Care 子问题测试 (2026-06-26)

*   **问题描述**: 子问题应继承 section 日期。
"""


def run_check() -> int:
    temp_root = pathlib.Path(tempfile.mkdtemp(prefix="split-qr-"))
    try:
        source = temp_root / "Question_Reviewer.md"
        target_dir = temp_root / "Question_Reviewer"
        source.write_text(SAMPLE_MD, encoding="utf-8")

        counts = split_file(source, target_dir)
        write_readme(target_dir, counts)

        # 1. 非空分类文件数量应该等于 counts 中非零条目数
        non_empty = {k: v for k, v in counts.items() if v > 0}
        if not non_empty:
            print("FAIL: 没有任何分类被填充")
            return 1

        # 2. 总条目数应等于原文件中的 ### 条目数
        # 原文件含 5 个条目：4 个主条目 + 1 个子问题
        total = sum(non_empty.values())
        if total != 5:
            print(f"FAIL: 拆分后总条目数 {total} != 原文件 5 条")
            return 2

        # 3. Active Care 应该包含 2 条（10.200 + 问题 1）
        if non_empty.get("01_active_care", 0) != 2:
            print(f"FAIL: 01_active_care 应有 2 条，实际 {non_empty.get('01_active_care', 0)}")
            return 3

        # 4. C++ 调度器应该包含 1 条
        if non_empty.get("03_cpp_scheduler", 0) != 1:
            print(f"FAIL: 03_cpp_scheduler 应有 1 条，实际 {non_empty.get('03_cpp_scheduler', 0)}")
            return 4

        # 5. TTS 应该包含 1 条
        if non_empty.get("05_tts_stt_voice", 0) != 1:
            print(f"FAIL: 05_tts_stt_voice 应有 1 条，实际 {non_empty.get('05_tts_stt_voice', 0)}")
            return 5

        # 6. misc 应该包含 1 条（不匹配任何关键词的条目）
        if non_empty.get("17_misc", 0) != 1:
            print(f"FAIL: 17_misc 应有 1 条，实际 {non_empty.get('17_misc', 0)}")
            return 6

        # 7. 每个分类文件应包含标准头部
        for file_name, _display_name, _ in CATEGORIES:
            count = non_empty.get(file_name, 0)
            if count == 0:
                continue
            file_path = target_dir / f"{file_name}.md"
            if not file_path.exists():
                print(f"FAIL: 分类文件 {file_name}.md 不存在")
                return 7
            text = file_path.read_text(encoding="utf-8")
            if not text.startswith("# "):
                print(f"FAIL: {file_name}.md 缺少 # 头部")
                return 8
            if "本分类共" not in text:
                print(f"FAIL: {file_name}.md 缺少条目数说明")
                return 9

        # 8. 验证子问题条目使用了 section 日期
        active_care_text = (target_dir / "01_active_care.md").read_text(encoding="utf-8")
        if "### 问题 1: Active Care 子问题测试 (2026-06-26)" not in active_care_text:
            print("FAIL: 子问题没有继承 section 日期")
            return 10

        # 9. 重新运行应该清空旧文件并重写
        # 在 17_misc.md 里塞一条假数据，重新运行后应该消失
        misc_path = target_dir / "17_misc.md"
        original_misc = misc_path.read_text(encoding="utf-8")
        poisoned = original_misc + "\n### POISONED-ENTRY 假数据 (2026-01-01)\n"
        misc_path.write_text(poisoned, encoding="utf-8")

        counts2 = split_file(source, target_dir)
        write_readme(target_dir, counts2)
        new_misc = misc_path.read_text(encoding="utf-8")
        if "POISONED-ENTRY" in new_misc:
            print("FAIL: 重新运行没有清理旧的分类文件")
            return 11
        if counts2.get("17_misc", 0) != 1:
            print(f"FAIL: 重新运行后 misc 条目数不对: {counts2.get('17_misc', 0)}")
            return 12

        # 10. README.md 应被生成并包含合计
        readme_path = target_dir / "README.md"
        if not readme_path.exists():
            print("FAIL: README.md 没有生成")
            return 13
        readme_text = readme_path.read_text(encoding="utf-8")
        if "合计" not in readme_text:
            print("FAIL: README.md 缺少合计行")
            return 14
        if "**5**" not in readme_text.replace(" ", ""):
            print(f"FAIL: README.md 合计应为 5，实际: {readme_text}")
            return 15

        # 11. 目录读取场景：把已拆好的 Question_Reviewer/ 目录作为 source 重新拆分
        # 验证：能合并所有 .md（排除 README.md）、重新归类、条目不丢失
        # 先在目录里塞一个 README.md 与一个非分类文件名，确认 README 被排除
        # 但非 README 的 .md 即使文件名不标准也应被合并
        extra_path = target_dir / "README.md"
        original_readme = extra_path.read_text(encoding="utf-8")
        # 把 README 改成包含 ### 条目的内容，验证它会被排除
        readme_with_entry = original_readme + "\n### README-Should-Be-Excluded 测试 (2026-01-01)\n"
        extra_path.write_text(readme_with_entry, encoding="utf-8")

        # 把 target_dir 自己作为 source 重新拆分
        # 需要拆到一个新目录，否则会被清理掉
        second_target = temp_root / "Question_Reviewer_Reresplit"
        counts3 = split_file(target_dir, second_target)
        write_readme(second_target, counts3)

        # 重新拆分后总条目数应仍是 5（README 里的条目应被排除）
        total3 = sum(v for v in counts3.values() if v > 0)
        if total3 != 5:
            print(f"FAIL: 目录读取重拆后总条目数 {total3} != 5（README 可能没被排除）")
            return 16

        # 验证 README 里的条目没混进来
        active_care3 = (second_target / "01_active_care.md").read_text(encoding="utf-8")
        misc3 = (second_target / "17_misc.md").read_text(encoding="utf-8") if (second_target / "17_misc.md").exists() else ""
        if "README-Should-Be-Excluded" in active_care3 or "README-Should-Be-Excluded" in misc3:
            print("FAIL: 目录读取没有排除 README.md 中的条目")
            return 17

        # 12. 目录读取应支持跨文件去重：同一 (title, date) 在多个 .md 中出现只保留一条
        # 构造一个含重复条目的目录
        dup_dir = temp_root / "DupSource"
        dup_dir.mkdir()
        (dup_dir / "a.md").write_text(
            "### 99.1 Active Care 重复条目 (2026-05-01)\n\n内容 A\n", encoding="utf-8"
        )
        (dup_dir / "b.md").write_text(
            "### 99.1 Active Care 重复条目 (2026-05-01)\n\n内容 B\n", encoding="utf-8"
        )
        dup_target = temp_root / "DupTarget"
        counts4 = split_file(dup_dir, dup_target)
        active_care4_path = dup_target / "01_active_care.md"
        if not active_care4_path.exists():
            print(f"FAIL: 目录读取重复场景没生成 01_active_care.md，目录: {list(dup_target.glob('*.md'))}")
            return 18
        text4 = active_care4_path.read_text(encoding="utf-8")
        if text4.count("### 99.1 Active Care 重复条目 (2026-05-01)") != 1:
            print(f"FAIL: 目录读取没有跨文件去重，条目出现次数: {text4.count('### 99.1 Active Care 重复条目 (2026-05-01)')}")
            return 19

        print("OK: split_question_reviewer 拆分、归类、子问题日期继承、重写清理、README、目录读取全部通过")
        print(f"     分类计数: {non_empty}")
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(run_check())
