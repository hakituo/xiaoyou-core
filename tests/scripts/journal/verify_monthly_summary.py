"""验证月度总结生成与质量

用途：
1. 手动触发指定月份的月度总结生成（绕过月末夜间任务触发条件）
2. 检查生成结果是否落盘、字段是否完整
3. 打印生成内容供人工评估质量

运行：
    d:\\AI\\xiaoyou-core\\venv_core\\scripts\\python.exe ^
        tests\\scripts\\journal\\verify_monthly_summary.py 2026-06-30

参数：
    位置参数 1：目标日期 YYYY-MM-DD（默认昨天）
    位置参数 2：--force 强制重新生成（默认只读已有文件）
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# 让脚本能在不安装包的情况下导入项目模块
# 脚本位于 tests/scripts/journal/，parents[3] 才是项目根
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.services.journal.service import get_journal_service  # noqa: E402
from core.services.journal.storage import JournalStorage  # noqa: E402
from core.utils.data_paths import _resolve_scope_from_active_persona  # noqa: E402
from core.utils.logger import get_logger  # noqa: E402

logger = get_logger("verify_monthly_summary")


def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def _inspect_artifact(date_str: str) -> None:
    """检查落盘文件是否存在并打印路径"""
    from datetime import datetime

    dt = datetime.strptime(date_str, "%Y-%m-%d")
    storage = JournalStorage()
    scope = _resolve_scope_from_active_persona()
    monthly_dir = storage._get_monthly_dir(dt, scope=scope)
    summary_file = monthly_dir / "summary.json"
    _print_section("落盘文件检查")
    print(f"scope          : {scope}")
    print(f"monthly_dir    : {monthly_dir}")
    print(f"summary.json   : {'存在' if summary_file.exists() else '不存在'}")
    if summary_file.exists():
        print(f"文件大小        : {summary_file.stat().st_size} bytes")
        try:
            data = json.loads(summary_file.read_text(encoding="utf-8"))
            print(f"month          : {data.get('month')}")
            print(f"summary 长度   : {len(data.get('summary', ''))} 字符")
            print(f"key_events 数量 : {len(data.get('key_events', []))}")
            print(f"mood_trend     : {data.get('mood_trend')}")
            print(f"stats          : {data.get('stats')}")
            print(f"persona_evolution: {data.get('persona_evolution')}")
        except Exception as exc:
            print(f"读取/解析失败: {exc}")


async def main(date_str: str, force: bool) -> int:
    _print_section(f"生成月度总结 date={date_str} force={force}")
    svc = get_journal_service()

    # 先看下当前已有的每日总结数量
    from datetime import datetime
    from core.services.journal.summary_service import JournalSummaryService

    dt = datetime.strptime(date_str, "%Y-%m-%d")
    summary_svc = getattr(svc, "_summary_service", None)
    if summary_svc is None:
        # 兜底：直接构造一个，避免旧版接口差异
        summary_svc = JournalSummaryService(svc)
    daily_summaries = await summary_svc._collect_daily_summaries(dt)
    print(f"已收集每日总结数量: {len(daily_summaries)}")
    if daily_summaries:
        dates = [s.date for s in daily_summaries]
        print(f"日期范围: {dates[0]} ~ {dates[-1]}")

    print("\n开始调用 generate_monthly_summary ...")
    result = await svc.generate_monthly_summary(date_str, force=force)

    _print_section("生成结果（内存对象）")
    print(f"month           : {result.month}")
    print(f"mood_trend      : {result.mood_trend}")
    print(f"key_events      : {result.key_events}")
    print(f"stats           : {result.stats}")
    print(f"persona_evolution: {result.persona_evolution}")
    print("\n--- summary ---")
    print(result.summary)

    _inspect_artifact(date_str)
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        from datetime import timedelta
        from core.utils.time_utils import get_diary_target_date
        target = (get_diary_target_date() - timedelta(days=1)).strftime("%Y-%m-%d")
        date_arg = target
    else:
        date_arg = args[0]
    force_flag = "--force" in args
    raise SystemExit(asyncio.run(main(date_arg, force_flag)))
