# -*- coding: utf-8 -*-
"""验证「角色 A 会读到角色 B 日记」的跨角色串读已修复。

背景：
    Aveline 对话时 prompt 里会出现另一个角色（历史上是Ling/ling）的日记总结内容，
    像是被直接注入。根因是日记读取链路存在多处「不指定 scope」的调用，而
    JournalStorage 在 scope 为空时按角色顺序取第一个存在的文件：
    一旦当前角色当天没有 diary_summary.json，就会静默返回别人的总结，
    再被 dynamic_context 包装成「今日总基调（来自昨日日记总结）」注入 prompt。

    角色对不再硬编码：主角色 / 对照角色取注册角色（character_runtime.yaml）。

本脚本验证：
    1. get_daily_summary 不再跨角色回退（默认只读活跃 role 目录）。
    2. 主角色自己当天没有日记时，返回 None，而不是别人的日记。
    3. 显式 scope 依旧各自独立可读。
    4. allow_cross_scope_fallback=True 保留旧的汇总回退能力（仅面向主人视图）。
    5. 源码层面 get_tomorrow_tone / _get_journal_summary 已带 scope 解析。

运行：
    d:\\AI\\xiaoyou-core\\venv_core\\scripts\\python.exe ^
        tests\\scripts\\journal\\verify_diary_scope_isolation.py
"""
from __future__ import annotations

import asyncio
import inspect
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

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


def _make_summary(date_str: str, tone: str, summary: str) -> dict:
    """构造一个最小可用的 DailySummary 载荷（generated_at 是 float 时间戳）。"""
    return {
        "date": date_str,
        "summary": summary,
        "tomorrow_tone": tone,
        "mood_trend": "平稳",
        "keywords": [],
        "generated_at": datetime.now().timestamp(),
    }


def _role_pair() -> tuple[str, str]:
    """主角色 / 对照角色：取注册角色；只有一个注册角色时用 user 作对照。"""
    from core.services.journal.diary_personas import get_diary_persona_ids

    roles = list(get_diary_persona_ids())
    if not roles:
        raise AssertionError("没有注册角色，无法验证隔离")
    primary = roles[0]
    other = roles[1] if len(roles) > 1 else "user"
    return primary, other


async def _test_storage_scope_isolation() -> None:
    """核心：主角色没有日记时不得回退到别的角色。"""
    from core.services.journal.storage import JournalStorage

    primary, other = _role_pair()
    date = datetime(2026, 9, 15)

    with tempfile.TemporaryDirectory() as tmp:
        storage = JournalStorage()
        # 把 scope 根目录重定向到临时目录，避免污染真实数据
        tmp_root = Path(tmp)

        def _fake_scope_base(scope: str) -> Path:
            return tmp_root / f"{scope}_data"

        storage._get_scope_base_dir = _fake_scope_base  # type: ignore[assignment]
        storage._summary_cache.clear()

        # 只给对照角色写日记，主角色故意留空（复现线上场景）
        other_dir = storage.get_daily_dir(date, scope=other)
        other_dir.mkdir(parents=True, exist_ok=True)
        other_tone = "记得追他一句，周末到底哪天来杭州，提前说"
        (other_dir / "diary_summary.json").write_text(
            json.dumps(_make_summary("2026-09-15", other_tone, f"{other} 的日记正文"), ensure_ascii=False),
            encoding="utf-8",
        )

        # 1. 显式 scope=主角色：应读不到（None），绝不能拿到别人的
        got_primary = await storage.get_daily_summary(date, scope=primary)
        _check(
            f"显式 scope={primary} 读不到 {other} 的日记",
            got_primary is None,
            f"got={getattr(got_primary, 'tomorrow_tone', None)!r}",
        )

        # 2. 显式 scope=对照角色：应正常读到它自己的
        got_other = await storage.get_daily_summary(date, scope=other)
        _check(
            f"显式 scope={other} 能读到它自己的日记",
            got_other is not None and got_other.tomorrow_tone == other_tone,
            f"got={getattr(got_other, 'tomorrow_tone', None)!r}",
        )

        # 3. 汇总视图：allow_cross_scope_fallback=True 时保留回退能力
        storage._summary_cache.clear()
        got_fallback = await storage.get_daily_summary(
            date, scope=primary, allow_cross_scope_fallback=True
        )
        _check(
            "allow_cross_scope_fallback=True 保留汇总回退",
            got_fallback is not None and got_fallback.tomorrow_tone == other_tone,
            f"got={getattr(got_fallback, 'tomorrow_tone', None)!r}",
        )

        # 4. 不传 scope 时，应解析为活跃角色（主角色），不得返回别人的
        storage._summary_cache.clear()
        got_default = await storage.get_daily_summary(date)
        _check(
            f"不传 scope 时不跨角色回退到 {other}",
            got_default is None,
            f"got={getattr(got_default, 'tomorrow_tone', None)!r}",
        )


async def _test_tomorrow_tone_isolated() -> None:
    """get_tomorrow_tone 必须按角色隔离，主角色不得拿到别人的基调。"""
    from core.services.journal import summary_service as ss

    primary, other = _role_pair()
    fake_tone_other = f"{other} 专属基调：追他周末来杭州"
    captured = {}

    class _FakeStorage:
        async def get_daily_summary(self, date, scope=None, **kwargs):
            captured["scope"] = scope
            from core.services.journal.models import DailySummary

            return DailySummary.model_validate(
                _make_summary("2026-09-15", fake_tone_other, f"{other} 日记")
            )

    class _FakeService:
        @staticmethod
        def _parse_date(date):
            return datetime(2026, 9, 15)

    svc = object.__new__(ss.JournalSummaryService)
    svc.storage = _FakeStorage()
    svc.service = _FakeService()

    tone = await svc.get_tomorrow_tone(persona=primary)
    _check(
        f"get_tomorrow_tone(persona={primary}) 传递 scope={primary}",
        captured.get("scope") == primary,
        f"captured={captured!r}",
    )
    _check(
        f"get_tomorrow_tone(persona={other}) 传递 scope={other}",
        (await svc.get_tomorrow_tone(persona=other)) is not None
        and captured.get("scope") == other,
        f"captured={captured!r}",
    )
    _ = tone


def _test_source_uses_scope() -> None:
    """源码层面确认关键调用点都已带 scope，防止回归。"""
    import core.services.journal.summary_service as ss
    import core.services.self_improvement.core_memory as cm
    import core.services.aveline_life.service as als

    tone_src = inspect.getsource(ss.JournalSummaryService.get_tomorrow_tone)
    _check(
        "get_tomorrow_tone 源码带 scope 参数",
        "scope=" in tone_src and "persona" in tone_src,
        "未发现 scope 传递",
    )

    collect_src = inspect.getsource(ss.JournalSummaryService._collect_daily_summaries)
    _check(
        "_collect_daily_summaries 源码带 scope",
        "scope=" in collect_src,
        "未发现 scope 传递",
    )

    mem_src = inspect.getsource(cm.CoreMemory._get_journal_summary)
    _check(
        "_get_journal_summary 源码按活跃 scope 读取",
        "scope=" in mem_src,
        "未发现 scope 传递",
    )

    life_src = inspect.getsource(als.AvelineLifeRhythmService._get_diary_summary)
    _check(
        "AvelineLife._get_diary_summary 锁死 persona=aveline",
        'persona="aveline"' in life_src,
        "未锁死 persona",
    )


def main() -> int:
    print("=" * 68)
    print("验证：日记读取按角色隔离（当前角色不应读到别的角色的日记）")
    print("=" * 68)

    asyncio.run(_test_storage_scope_isolation())
    asyncio.run(_test_tomorrow_tone_isolated())
    _test_source_uses_scope()

    print("-" * 68)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        for name in FAILED:
            print(f"  [FAIL] {name}")
        return 1
    print("全部通过：角色不再跨角色读到别人的日记总结。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
