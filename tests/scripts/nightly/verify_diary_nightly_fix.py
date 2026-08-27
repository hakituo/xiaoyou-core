# -*- coding: utf-8 -*-
"""验证"凌晨空日记"与"Ling日记安卓端不可见"两项修复。

背景：
1. 凌晨 5 点兜底触发夜间任务时，get_diary_target_date() 因阈值=5 返回"今天"，
   而今天尚未结束 → 写出 chat_turn_count=0 的"没找我"空日记。
   修复：凌晨归属阈值 5 → 12（中午前都归属前一天）。
2. Ling的每日总结日记条目被记成 source=aveline（用了"当前活跃 persona"），
   且按"任一同类型条目已存在即跳过"去重，导致Ling总结被 Aveline 顶掉，
   安卓端按 source 分组永远看不到Ling的日记。
   修复：source 改用 persona 本身 + 按 persona 作用域去重。
3. 自动总结不得再次进入任一角色的生成上下文；不同角色撞稿时按身份边界重写，
   不再用“缓存命中”解释或提高 temperature 碰运气。

运行：
    d:\\AI\\xiaoyou-core\\venv_core\\scripts\\python.exe ^
        tests\\scripts\\nightly\\verify_diary_nightly_fix.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

# 项目根目录加入 sys.path
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PASSED = []
FAILED = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASSED.append(name)
        print(f"[OK] {name}")
    else:
        FAILED.append(name)
        print(f"[FAIL] {name} {detail}")


def _test_diary_target_date_threshold() -> None:
    """get_diary_target_date 凌晨归属阈值应改为 12。"""
    from core.utils.time.time_utils import get_diary_target_date

    base = datetime(2026, 8, 15, 12, 0, 0)
    # 0~11 点应归属前一天 8/14
    for hour in (0, 4, 5, 11):
        got = get_diary_target_date(base.replace(hour=hour)).date()
        _check(
            f"get_diary_target_date hour={hour} 归属前一天",
            got == datetime(2026, 8, 14).date(),
            f"got={got}",
        )
    # 12 点起应归属当天
    for hour in (12, 13, 23):
        got = get_diary_target_date(base.replace(hour=hour)).date()
        _check(
            f"get_diary_target_date hour={hour} 归属当天",
            got == datetime(2026, 8, 15).date(),
            f"got={got}",
        )
    # 跨年/跨月边界：1/1 凌晨 5 点应归属去年 12/31
    new_year = datetime(2026, 1, 1, 5, 0, 0)
    got = get_diary_target_date(new_year).date()
    _check(
        "get_diary_target_date 跨年边界归属 2025-12-31",
        got == datetime(2025, 12, 31).date(),
        f"got={got}",
    )


def _test_daily_manager_calendar_day() -> None:
    """daily 实时记录默认日期应按自然日（今天），不受凌晨归属阈值影响。"""
    from core.services.daily.manager import DailyActivityManager

    fake_now = datetime(2026, 8, 15, 8, 30, 0)
    with tempfile.TemporaryDirectory() as td:
        with mock.patch("core.utils.time.time_utils.get_current_time", return_value=fake_now), \
             mock.patch(
                 "core.services.daily.manager.get_user_daily_records_dir",
                 return_value=Path(td),
             ):
            mgr = DailyActivityManager()
            got = mgr._normalize_date(None)
            _check(
                "daily 实时记录 8/15 上午默认归属自然日 8/15（非昨天）",
                got == "2026-08-15",
                f"got={got}",
            )
            # 显式日期仍按原样解析
            got2 = mgr._normalize_date("2026-08-14")
            _check("daily 显式日期解析保持原样", got2 == "2026-08-14", f"got={got2}")


def _build_summary_service_fakes() -> tuple:
    """构造 _append_daily_summary_diary_entry 所需的轻量假对象。"""

    class _FakeSettings:
        class _Memory:
            append_auto_daily_summary_to_user_journal = True
        memory = _Memory()

    class _FakeStorage:
        def __init__(self) -> None:
            self.saved: list = []

        async def get_entries(self, dt):  # noqa: ANN001
            return list(self.saved)

        async def save_entry(self, entry, dt):  # noqa: ANN001
            self.saved.append(entry)
            return "fake_path"

        async def replace_entry(self, entry, dt):  # noqa: ANN001
            for index, old in enumerate(self.saved):
                if old.id == entry.id:
                    self.saved[index] = entry
                    return "fake_path"
            self.saved.append(entry)
            return "fake_path"

    class _FakeService:
        async def _append_journal_memory(self, entry) -> None:  # noqa: ANN001
            pass

    from core.services.journal.summary_service import JournalSummaryService

    svc = JournalSummaryService.__new__(JournalSummaryService)
    svc.settings = _FakeSettings()
    svc.storage = _FakeStorage()
    svc.service = _FakeService()
    return svc


def _test_daily_summary_entry_persona() -> None:
    """每日总结条目：source 用 persona；同 persona 重生成时原位更新。"""
    from core.services.journal.models import DailySummary

    svc = _build_summary_service_fakes()
    dt = datetime(2026, 8, 15)

    summary_aveline = DailySummary(
        date="2026-08-15", summary="Aveline 视角的日记正文", stats={"generated": True}
    )
    summary_ling = DailySummary(
        date="2026-08-15", summary="Ling视角的日记正文", stats={"generated": True}
    )
    summary_ling_v2 = DailySummary(
        date="2026-08-15", summary="Ling重新生成后的日记正文", stats={"generated": True}
    )

    export_placeholder = mock.AsyncMock()

    async def run() -> None:
        with mock.patch(
            "core.services.journal.persona_exports.get_persona_journal_export_service",
            return_value=type("_E", (), {"export_after_entry": export_placeholder})(),
        ):
            # 1. 先写 Aveline
            await svc._append_daily_summary_diary_entry(
                dt=dt, summary_obj=summary_aveline, study_stats={}, persona="aveline"
            )
            # 2. 再写Ling——不应被 Aveline 顶掉
            await svc._append_daily_summary_diary_entry(
                dt=dt, summary_obj=summary_ling, study_stats={}, persona="ling"
            )
            # 3. Ling强制重生成应原位更新，不保留旧正文
            await svc._append_daily_summary_diary_entry(
                dt=dt, summary_obj=summary_ling_v2, study_stats={}, persona="ling"
            )

    asyncio.run(run())

    _check(
        "Ling/Aveline 每日总结条目均落盘（未被跨 persona 去重）",
        len(svc.storage.saved) == 2,
        f"saved={len(svc.storage.saved)}",
    )
    sources = [e.source for e in svc.storage.saved]
    _check(
        "条目 source 分别为 aveline 与 ling",
        sources == ["aveline", "ling"],
        f"sources={sources}",
    )
    contents = [e.content for e in svc.storage.saved]
    _check(
        "Ling重生成条目原位更新且未被 Aveline 覆盖",
        "Ling重新生成后的日记正文" in contents and "Ling视角的日记正文" not in contents[-1]
        and "Aveline 视角" not in contents[-1],
        f"contents={contents}",
    )
    _check("Ling条目的 thought 为 auto_generated_daily_summary",
           all(getattr(e, "thought", None) == "auto_generated_daily_summary" for e in svc.storage.saved))


def _test_source_changes_present() -> None:
    """源码级断言：关键修复点已在文件中生效。"""
    import re

    time_src = (ROOT / "core/utils/time/time_utils.py").read_text(encoding="utf-8")
    _check(
        "time_utils 默认阈值改为 12",
        "early_morning_threshold: int = 12" in time_src,
    )

    summary_src = (ROOT / "core/services/journal/summary_service.py").read_text(encoding="utf-8")
    _check(
        "summary_service 按 persona 查找并更新自动总结条目",
        'resolve_data_scope_from_source(' in summary_src and 'replace_entry(entry, dt)' in summary_src,
    )
    _check(
        "summary_service 条目 source 用 persona",
        re.search(r"source\s*=\s*persona", summary_src) is not None,
    )

    global_tasks_src = (ROOT / "memory/nightly/global_tasks.py").read_text(
        encoding="utf-8"
    )
    _check(
        "global_tasks 以 Aveline 正文作为撞稿校验基准",
        "distinct_from=aveline_text" in global_tasks_src
        and "temperature=0.8" not in global_tasks_src,
    )

    helper_src = (ROOT / "core/services/journal/journal_helpers.py").read_text(encoding="utf-8")
    _check(
        "角色日记上下文排除自动总结与其他 persona",
        'entry_type == "daily_summary"' in helper_src
        and 'source not in {"user", persona}' in helper_src,
    )

    template_src = (
        ROOT
        / "core/agents/chat_agent_components/persona_system/prompt/components/templates.py"
    ).read_text(encoding="utf-8")
    _check(
        "两套角色 Prompt 明确不同叙事方式与证据边界",
        "语气克制、敏锐" in template_src
        and "临睡前想到哪写到哪" in template_src
        and "不为缓存强行复用同一骨架" in template_src,
    )

    config_src = (ROOT / "memory/nightly/config.py").read_text(encoding="utf-8")
    _check(
        "nightly 窗口 end_time 扩展至 12:00",
        '"end_time": "12:00"' in config_src,
    )

    orch_src = (ROOT / "core/services/life_simulation/orchestrator.py").read_text(encoding="utf-8")
    _check(
        "life_simulation 凌晨窗口同步改为 12",
        "now_dt.hour >= 12" in orch_src,
    )

    router_src = (ROOT / "routers/v1/diary.py").read_text(encoding="utf-8")
    _check(
        "GET /diary/summary 支持 persona 参数",
        "persona: str = Query(" in router_src and 'aveline / ling / user' in router_src,
    )
    svc_src = (ROOT / "core/services/workspace/service.py").read_text(encoding="utf-8")
    _check(
        "workspace.get_diary_summary 透传 persona",
        "def get_diary_summary(\n        self, date: Optional[str] = None, persona: str = \"aveline\"\n    )" in svc_src,
    )
    journal_svc_src = (ROOT / "core/services/journal/service.py").read_text(encoding="utf-8")
    _check(
        "JournalService.get_daily_summary 支持 persona",
        "persona: str = \"aveline\"" in journal_svc_src and "get_daily_summary(date, persona=persona)" in journal_svc_src,
    )
    summary_svc_src = (ROOT / "core/services/journal/summary_service.py").read_text(encoding="utf-8")
    _check(
        "JournalSummaryService.get_daily_summary 按 scope 读取",
        "scope=persona" in summary_svc_src,
    )


def main() -> int:
    print("=== 验证日记凌晨归属与Ling日记修复 ===\n")
    _test_diary_target_date_threshold()
    _test_daily_manager_calendar_day()
    _test_daily_summary_entry_persona()
    _test_source_changes_present()

    print(f"\n结果: {len(PASSED)} 通过, {len(FAILED)} 失败")
    if FAILED:
        print("失败项:", ", ".join(FAILED))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
