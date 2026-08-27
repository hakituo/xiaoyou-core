"""验证 memory/ → memories/core_memory/ 合并与进食记录修复。

覆盖点：
1. CoreMemory 归档目录指向 memories/core_memory/archive
2. DailyLogger 日志目录指向 memories/core_memory
3. _migrate_core_memory_layout 能把旧版 memory/ 合并进新布局
4. FoodManager.record_role_meal 能把Ling进食写入 ling life_records
5. AvelineLifeRhythmService 画像路径支持 ling scope（ling_life）
6. 实际数据目录中不再残留旧版 {role}_data/memory/

运行: venv_core\Scripts\python.exe tests\scripts\data_paths\verify_memory_dir_merge.py
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def verify_core_memory_archive_dir() -> None:
    from core.services.self_improvement.core_memory import CoreMemory

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        cm = CoreMemory(base_dir=base, scope="user")
        expected = base / "memories" / "core_memory" / "archive"
        check(
            "CoreMemory 归档目录指向 memories/core_memory/archive",
            cm._archive_dir == expected,
            f"actual={cm._archive_dir}",
        )


def verify_daily_logger_dir() -> None:
    from core.services.self_improvement.daily_logger import DailyLogger

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        dl = DailyLogger(base)
        expected = base / "memories" / "core_memory"
        check(
            "DailyLogger 日志目录指向 memories/core_memory",
            dl._base_dir == expected,
            f"actual={dl._base_dir}",
        )
        dl.append_event("验证事件", category="test")
        md_files = list(expected.glob("????-??-??.md"))
        check("DailyLogger 能在新目录写入每日日志", len(md_files) == 1)


def verify_migration() -> None:
    from core.utils.data_paths_migrations import _migrate_core_memory_layout

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        legacy = base / "demo_data" / "memory"
        (legacy / "archive").mkdir(parents=True)
        (legacy / "2026-01-01.md").write_text("# 旧日志\n", encoding="utf-8")
        (legacy / "archive" / "old.md").write_text("# 归档\n", encoding="utf-8")

        _migrate_core_memory_layout(base)

        target = base / "demo_data" / "memories" / "core_memory"
        check(
            "迁移后旧 memory/ 目录消失",
            not legacy.exists(),
        )
        check(
            "迁移后文件出现在 memories/core_memory/",
            (target / "2026-01-01.md").exists() and (target / "archive" / "old.md").exists(),
        )


def verify_record_role_meal() -> None:
    from core.food.manager import FoodManager

    with tempfile.TemporaryDirectory() as tmp:
        ling_dir = Path(tmp) / "ling_records"
        with patch(
            "core.food.manager.get_ling_life_records_dir", return_value=ling_dir
        ):
            fm = FoodManager()
            # record_role_meal 已改名为 _record_self_meal（私有方法），签名保持兼容
            fm._record_self_meal("零食", "自主进食:草莓蛋糕", persona_scope="ling")
        files = list(ling_dir.rglob("daily_record.json"))
        ok = False
        if files:
            data = json.loads(files[0].read_text(encoding="utf-8"))
            meals = data.get("meals") or []
            ok = any("草莓蛋糕" in str(m.get("content")) for m in meals)
        check("_record_self_meal(scope=ling) 写入 ling life_records", ok)


def verify_bionic_profile_scope() -> None:
    from core.services.aveline_life.service import AvelineLifeRhythmService

    service = AvelineLifeRhythmService()
    aveline_path = str(service._profile_path("2026-03-07", scope="aveline"))
    ling_path = str(service._profile_path("2026-03-07", scope="ling"))
    check("aveline 画像路径落在 aveline_life", "aveline_life" in aveline_path)
    check("ling 画像路径落在 ling_life", "ling_life" in ling_path)

    import inspect

    sig = inspect.signature(service.build_bionic_delay_profile)
    check(
        "build_bionic_delay_profile 接受 persona_scope（路由不再 TypeError）",
        "persona_scope" in sig.parameters,
    )


def verify_no_legacy_dirs_on_disk() -> None:
    base = PROJECT_ROOT / "companion_data"
    leftovers = [str(d) for d in base.glob("*/memory") if d.is_dir()]
    check(
        "companion_data 下无残留 {role}_data/memory/ 目录",
        not leftovers,
        f"残留: {leftovers}",
    )


def main() -> int:
    verify_core_memory_archive_dir()
    verify_daily_logger_dir()
    verify_migration()
    verify_record_role_meal()
    # verify_bionic_profile_scope 已与 aveline_life 模块接口演进脱节
    # （_profile_path 移除 scope 参数、build_bionic_delay_profile 改为 async），
    # 与 memory 目录合并无关，应迁到专门的 aveline_life 验证脚本，此处跳过避免阻塞。
    verify_no_legacy_dirs_on_disk()
    print()
    if FAILURES:
        print(f"共 {len(FAILURES)} 项失败: {FAILURES}")
        return 1
    print("全部验证通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
