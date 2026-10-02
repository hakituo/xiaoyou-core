"""验证「写日记的角色 = 注册角色」：日记链路不再硬编码 aveline / ling。

运行：
    d:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe ^
        tests\\scripts\\journal\\verify_diary_personas_from_registry.py
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PASSED: list[str] = []
FAILED: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASSED.append(name)
        print(f"[OK] {name}")
    else:
        FAILED.append(name)
        print(f"[FAIL] {name} {detail}")


def _verify_registry_source() -> None:
    """注册角色与日记角色一致；换注册配置时日记角色跟着变。"""
    from core.character.runtime_roles import get_autonomous_role_ids
    from core.services.journal.diary_personas import get_diary_persona_ids

    registered = set(get_autonomous_role_ids())
    diary = set(get_diary_persona_ids())
    _check(
        "日记角色集合 == 注册角色集合",
        diary == registered,
        f"registered={sorted(registered)} diary={sorted(diary)}",
    )

    with mock.patch(
        "core.character.runtime_roles.get_autonomous_role_ids",
        return_value=frozenset({"aveline", "ling"}),
    ):
        _check(
            "改注册配置后日记角色同步变化",
            set(get_diary_persona_ids()) == {"aveline", "ling"},
        )


def _verify_prompt_routing() -> None:
    """每个注册角色都有自己的日记 prompt，且不会串到别的角色语气上。"""
    from core.services.journal.diary_personas import get_diary_persona_ids
    from core.services.journal.journal_helpers import build_daily_summary_messages

    kwargs = dict(
        date_str="2026-09-22",
        diary_context="手记",
        chat_context="聊天",
        active_care_context="主动行为",
        user_status_summary="状态",
        study_context="学习",
        daily_context="生活",
        user_diary_context="主人日记",
        character_daily_context="节奏",
    )
    systems: dict[str, str] = {}
    for role_id in get_diary_persona_ids():
        systems[role_id] = build_daily_summary_messages(**kwargs, persona=role_id)[0][
            "content"
        ]
    _check("每个注册角色都拿到 system prompt", bool(systems))

    names = {role_id: text for role_id, text in systems.items()}
    _check(
        "不同角色的日记 prompt 互不相同",
        len(set(names.values())) == len(names),
        f"roles={list(names)}",
    )
    for role_id, text in systems.items():
        _check(
            f"{role_id} 的 prompt 认领自己的身份",
            _self_name_of(role_id) in text,
            f"missing={_self_name_of(role_id)}",
        )


def _self_name_of(role_id: str) -> str:
    from core.services.dual_role.personas import get_persona

    profile = get_persona(role_id)
    return profile.cn_name if profile else role_id


def _verify_nightly_loops_registered_roles() -> None:
    """nightly 全局任务按注册角色逐个生成，不再写死 ling。"""
    import datetime

    from memory.nightly.global_tasks import NightlyGlobalTaskService

    source = inspect.getsource(NightlyGlobalTaskService._run_journal_plan_and_wellbeing)
    _check("nightly 从注册角色取日记角色", "get_diary_persona_ids" in source)
    _check("nightly 不再硬编码 persona=\"ling\"", 'persona="ling"' not in source)

    calls: list[str] = []
    results: dict = {}

    class _FakeSummary:
        summary = "角色日记正文"
        stats: dict = {}

    class _FakeJournal:
        async def generate_daily_summary(
            self, _date, force=False, persona="aveline", distinct_from=None
        ):
            calls.append(persona)
            return _FakeSummary()

    async def run() -> None:
        service = NightlyGlobalTaskService()
        with mock.patch(
            "core.services.journal.service.get_journal_service",
            return_value=_FakeJournal(),
        ), mock.patch(
            "memory.nightly.global_tasks.is_valid_daily_summary_obj", return_value=True
        ), mock.patch.object(
            NightlyGlobalTaskService, "_ensure_diary_file", staticmethod(lambda _d: None)
        ), mock.patch.object(
            NightlyGlobalTaskService,
            "_mark_roles_nightly_done",
            staticmethod(lambda _d, _r: None),
        ), mock.patch.object(
            NightlyGlobalTaskService,
            "_review_digital_wellbeing",
            staticmethod(lambda *_a: None),
        ), mock.patch.object(
            NightlyGlobalTaskService,
            "_generate_next_day_plan",
            new=mock.AsyncMock(return_value=None),
        ):
            await service._run_journal_plan_and_wellbeing(
                datetime.date(2026, 9, 22), results
            )

    import asyncio

    asyncio.run(run())
    _check(
        "nightly 只为注册角色生成日记",
        calls == list(get_registered_ids()),
        f"calls={calls}",
    )
    _check(
        "结果里带每个角色的生成状态",
        all(f"{role}_daily_summary" in results for role in get_registered_ids()),
        f"results={results}",
    )


def get_registered_ids() -> tuple:
    from core.services.journal.diary_personas import get_diary_persona_ids

    return get_diary_persona_ids()


def _verify_backfill_uses_single_dispatch() -> None:
    """生活模拟只上报信号，角色名单与 force 策略都在统一调度入口。"""
    from core.services.life_simulation.orchestration import minute_tick
    from memory.nightly import sleep_hooks

    source = inspect.getsource(minute_tick)
    _check("生活模拟不再自己生成每日总结", "generate_daily_summary" not in source)
    _check("生活模拟把补写交给统一入口", "schedule_backfill_after_sleep" in source)
    _check("生活模拟不含角色字面量", '("aveline", "ling")' not in source)

    hooks_source = inspect.getsource(sleep_hooks)
    _check("nightly 睡眠标记读注册角色", "get_autonomous_role_ids" in hooks_source)
    _check("nightly 睡眠标记不再写死角色", '("aveline", "ling")' not in hooks_source)


def _verify_storage_scopes() -> None:
    """读取日记条目/总结的 scope 列表也来自注册角色。"""
    from core.services.journal.diary_personas import (
        get_diary_entry_scopes,
        get_diary_persona_ids,
    )
    from core.services.journal.storage import JournalStorage

    source = inspect.getsource(JournalStorage.get_entries)
    _check("storage.get_entries 不再写死角色列表", '("user", "aveline", "ling")' not in source)
    _check(
        "扫描 scope = 主人 + 注册角色",
        set(get_diary_entry_scopes()) == {"user", *get_diary_persona_ids()},
    )


def _verify_model_route_avoids_moderation() -> None:
    """日记 / 蒸馏模型不能是会审核拒绝题材的 Minimax，否则日记直接写不出来。"""
    from config.model_config import load_model_config, get_journal_model

    journal_model = get_journal_model()
    distill_model = (load_model_config().get("memory_models") or {}).get("distillation")
    _check(
        "日记模型已切到 deepseek（不再被 MiniMax 422 拒绝）",
        "deepseek" in journal_model and "minimax" not in journal_model.lower(),
        f"journal_model={journal_model}",
    )
    _check(
        "记忆蒸馏 / 人物档案提取同样走 deepseek",
        distill_model and "deepseek" in distill_model,
        f"distillation={distill_model}",
    )


def _verify_sensitive_prefix_injection() -> None:
    """敏感人设（Ye）的日记 system prompt 复用聊天侧分级前缀；非敏感人设不注入。"""
    from core.agents.chat_agent_components.persona_system.prompt.sensitive_prefix import (
        get_sensitive_prefix,
    )
    from core.services.journal.journal_helpers import build_daily_summary_messages
    from core.services.dual_role.personas import get_persona

    kwargs = dict(
        date_str="2026-09-22",
        diary_context="手记",
        chat_context="聊天",
        active_care_context="主动行为",
        user_status_summary="状态",
        study_context="学习",
        daily_context="生活",
    )
    ye_system = build_daily_summary_messages(**kwargs, persona="ye")[0]["content"]
    aveline_system = build_daily_summary_messages(**kwargs, persona="aveline")[0]["content"]

    prefix_body = get_sensitive_prefix().strip()
    if not prefix_body:
        _check("本机敏感前缀为空（跳过注入断言）", True)
        return
    _check(
        "Ye（敏感人设）日记 prompt 首位带敏感前缀",
        ye_system.startswith(prefix_body[:40]),
        f"head={ye_system[:30]!r}",
    )
    _check(
        "Aveline（非敏感人设）日记 prompt 不注入敏感前缀",
        not aveline_system.startswith(prefix_body[:40]),
        f"head={aveline_system[:30]!r}",
    )
    _ = get_persona


def main() -> int:
    print("=== 验证日记角色跟随注册角色 ===\n")
    _verify_registry_source()
    _verify_prompt_routing()
    _verify_nightly_loops_registered_roles()
    _verify_backfill_uses_single_dispatch()
    _verify_storage_scopes()
    _verify_model_route_avoids_moderation()
    _verify_sensitive_prefix_injection()

    print(f"\n结果: {len(PASSED)} 通过, {len(FAILED)} 失败")
    if FAILED:
        print("失败项:", ", ".join(FAILED))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
