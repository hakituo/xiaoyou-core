"""验证 nightly processor 日志独立 + 日记/计划修复

检查项：
1. nightly 相关模块全部使用 get_module_logger + nightly_processor.log
2. task_runner 的 daily_summary 调用使用 force=True（覆盖凌晨不完整版）
3. task_runner 的计划生成基于 target_date+1（generate_plan_for_date），而非 generate_tomorrow_plan
4. JournalService / JournalPlanService 暴露 generate_plan_for_date 公共方法
5. 实际触发日志写入，确认 nightly_processor.log 文件被创建
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# 项目根目录加入 sys.path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _read_source(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def check_substring(rel_path: str, required: str, forbidden: list[str] | None = None) -> None:
    """检查文件源码包含/不包含指定字符串"""
    src = _read_source(rel_path)
    assert required in src, (
        f"[FAIL] {rel_path} 未找到预期配置: {required}"
    )
    for bad in forbidden or []:
        assert bad not in src, (
            f"[FAIL] {rel_path} 仍包含禁止字符串: {bad}"
        )


def main() -> int:
    # 1. nightly 模块全部使用 get_module_logger + nightly_processor.log
    nightly_files = [
        "memory/nightly_processor.py",
        "memory/nightly/task_runner.py",
        "memory/nightly/analysis_service.py",
        "memory/nightly/config.py",
        "memory/nightly/user_loader.py",
    ]
    for rel in nightly_files:
        check_substring(
            rel,
            required='get_module_logger(__name__, "nightly_processor.log")',
            forbidden=["get_logger(__name__)"],
        )
    print(f"[OK] {len(nightly_files)} 个 nightly 模块 logger 配置正确（nightly_processor.log）")

    # 2. task_runner daily_summary 使用 force=True
    task_src = _read_source("memory/nightly/task_runner.py")
    assert "force=True" in task_src, "[FAIL] task_runner 未使用 force=True 重新生成 daily_summary"
    assert "force=True" in task_src, "[FAIL] task_runner 未使用 force=True"
    # 确认注释说明存在（便于后续维护者理解）
    assert "凌晨睡眠时" in task_src or "不完整版本" in task_src, (
        "[FAIL] task_runner 缺少 force=True 的原因注释"
    )
    print("[OK] task_runner daily_summary 使用 force=True 覆盖不完整版")

    # 3. task_runner 计划基于 target_date+1（generate_plan_for_date），不再用 generate_tomorrow_plan
    assert "generate_plan_for_date" in task_src, (
        "[FAIL] task_runner 未使用 generate_plan_for_date"
    )
    assert "next_day = target_date + datetime.timedelta(days=1)" in task_src, (
        "[FAIL] task_runner 未基于 target_date+1 生成计划"
    )
    # nightly task_runner 里不应再调用 generate_tomorrow_plan（日期会错算成后天）
    # 注：注释中会提及该方法名，故只检查实际调用形式 journal_service.xxx
    assert "journal_service.generate_tomorrow_plan" not in task_src, (
        "[FAIL] task_runner 仍调用 generate_tomorrow_plan（凌晨运行会生成后天计划）"
    )
    assert "journal_service.get_tomorrow_plan" not in task_src, (
        "[FAIL] task_runner 仍调用 get_tomorrow_plan（应基于 target_date+1 检查）"
    )
    print("[OK] task_runner 计划基于 target_date+1（generate_plan_for_date）")

    # 3b. 空计划（0 项）不应跳过重新生成
    assert "existing_plan and existing_plan.items" in task_src, (
        "[FAIL] task_runner 未检查 existing_plan.items，空计划会被跳过"
    )
    assert "force_regenerate = existing_plan is not None" in task_src, (
        "[FAIL] task_runner 未对空计划使用 force=True 覆盖"
    )
    print("[OK] task_runner 空计划（0 项）会触发 force=True 重新生成")

    # 4. JournalService / JournalPlanService 暴露 generate_plan_for_date
    check_substring(
        "core/services/journal/plan_service.py",
        required="async def generate_plan_for_date",
    )
    check_substring(
        "core/services/journal/service.py",
        required="async def generate_plan_for_date",
    )
    print("[OK] JournalPlanService / JournalService 已暴露 generate_plan_for_date")

    # 5. 实际触发日志写入，确认 nightly_processor.log 被创建
    tmp = tempfile.mkdtemp()
    try:
        os.chdir(tmp)
        from core.utils.logger import get_module_logger

        test_logger = get_module_logger("NIGHTLY_TEST", "nightly_processor.log")
        test_logger.info("verify_nightly_log_and_fixes: 测试写入")

        import time
        candidates: list[Path] = []
        for _ in range(20):
            candidates = list(Path(tmp).rglob("nightly_processor.log"))
            if candidates:
                break
            time.sleep(0.3)

        assert candidates, "[FAIL] nightly_processor.log 文件未被创建"
        content = candidates[0].read_text(encoding="utf-8", errors="ignore")
        assert "verify_nightly_log_and_fixes" in content, (
            f"[FAIL] nightly_processor.log 中未找到测试日志: {content}"
        )
        print(f"[OK] nightly_processor.log 文件已创建并写入成功: {candidates[0]}")
    finally:
        try:
            for h in list(test_logger.handlers):
                h.close()
                test_logger.removeHandler(h)
        except Exception:
            pass
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n所有验证通过 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
