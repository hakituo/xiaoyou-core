"""验证 nightly 分阶段编排、断点续跑、目标日期和模型缓存结构。"""

from __future__ import annotations

import asyncio
import datetime
import inspect
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def verify_once_and_persistent_skip(temp_dir: Path) -> None:
    """多个 scope 只各跑一次，全局阶段只跑一次，重建实例仍会跳过。"""
    from memory.nightly.run_state import NightlyRunStateStore
    from memory.nightly_processor import NightlyProcessor

    target_date = datetime.date(2026, 8, 24)
    state_path = temp_dir / "once.json"
    scopes = {"private_alpha": object(), "aveline": object(), "ling": object()}
    scope_calls: list[str] = []
    global_calls: list[datetime.date] = []

    processor = NightlyProcessor(config={"auto_run": False})
    processor._run_state_store = NightlyRunStateStore(state_path)
    processor._is_in_time_window = lambda: True
    processor.process_user_chat_history = (
        lambda scope, _manager, *, target_date: scope_calls.append(scope) or {}
    )
    processor._run_nightly_global_tasks = (
        lambda date, _managers: global_calls.append(date) or {"daily_summary": True}
    )

    with patch("memory.weighted_memory_manager._instances", scopes):
        completed = processor.process_all_users(
            trigger_reason="verify", target_date=target_date
        )
    _assert(completed, "首次运行完成")
    _assert(sorted(scope_calls) == sorted(scopes), "每个 scope 恰好运行一次")
    _assert(global_calls == [target_date], "全局阶段每个目标日期只运行一次")

    restarted = NightlyProcessor(config={"auto_run": False})
    restarted._run_state_store = NightlyRunStateStore(state_path)
    restarted._is_in_time_window = lambda: True
    restarted.process_user_chat_history = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("已完成日期不应重跑 scope")
    )
    restarted._run_nightly_global_tasks = lambda *_args: (_ for _ in ()).throw(
        AssertionError("已完成日期不应重跑全局阶段")
    )
    with patch("memory.weighted_memory_manager._instances", scopes):
        completed_after_restart = restarted.process_all_users(
            trigger_reason="restart", target_date=target_date
        )
    _assert(completed_after_restart, "重启后读取持久状态并跳过已完成日期")


def verify_sleep_trigger_precedes_fallback() -> None:
    """同时满足时优先记录 sleep，fallback 只作兜底。"""
    from memory.nightly_processor import NightlyProcessor

    source = inspect.getsource(NightlyProcessor._sleep_aware_scheduler_loop)
    _assert(
        source.index('trigger_reason="sleep"')
        < source.index('trigger_reason="fallback"'),
        "sleep 延迟触发优先于 05:00 fallback",
    )


def verify_partial_resume(temp_dir: Path) -> None:
    """部分失败后只补跑失败 scope，不重复全局阶段。"""
    from memory.nightly.run_state import NightlyRunStateStore
    from memory.nightly_processor import NightlyProcessor

    target_date = datetime.date(2026, 8, 23)
    state_path = temp_dir / "resume.json"
    scopes = {"scope_ok": object(), "scope_retry": object()}
    attempts: list[str] = []
    global_calls: list[datetime.date] = []

    processor = NightlyProcessor(config={"auto_run": False})
    processor._run_state_store = NightlyRunStateStore(state_path)
    processor._is_in_time_window = lambda: True

    def process_scope(scope: str, _manager: Any, *, target_date: datetime.date) -> dict:
        attempts.append(scope)
        if scope == "scope_retry" and attempts.count(scope) == 1:
            raise RuntimeError("模拟 scope 失败")
        return {}

    processor.process_user_chat_history = process_scope
    processor._run_nightly_global_tasks = (
        lambda date, _managers: global_calls.append(date) or {"daily_summary": True}
    )

    with patch("memory.weighted_memory_manager._instances", scopes):
        first = processor.process_all_users(target_date=target_date)
        second = processor.process_all_users(target_date=target_date)

    _assert(not first and second, "部分失败保留 partial，下一轮补跑后完成")
    _assert(attempts.count("scope_ok") == 1, "已成功 scope 不重复执行")
    _assert(attempts.count("scope_retry") == 2, "只重试失败 scope")
    _assert(global_calls == [target_date], "补跑时不重复已完成全局阶段")


def verify_calendar_window() -> None:
    """分析窗口严格使用目标自然日，不再使用滚动 24 小时。"""
    from memory.nightly.analysis_service import NightlyAnalysisService
    from memory.nightly.config import DEFAULT_NIGHTLY_CONFIG

    target_date = datetime.date(2026, 8, 24)
    tz = datetime.timezone(datetime.timedelta(hours=8))

    def timestamp(day: datetime.date, hour: int) -> float:
        return datetime.datetime.combine(
            day, datetime.time(hour=hour), tzinfo=tz
        ).timestamp()

    class FakeManager:
        lock = threading.RLock()
        weighted_memories = {
            "previous": {"timestamp": timestamp(target_date - datetime.timedelta(days=1), 23)},
            "target": {"timestamp": timestamp(target_date, 12), "content": "目标日消息"},
            "next": {"timestamp": timestamp(target_date + datetime.timedelta(days=1), 1)},
        }

        @staticmethod
        def get_weighted_memories(**_kwargs: Any) -> list:
            return []

    service = NightlyAnalysisService(DEFAULT_NIGHTLY_CONFIG.copy())
    service.save_analysis_result = lambda *_args, **_kwargs: None
    result = service.process_user_chat_history(
        "scope_calendar",
        FakeManager(),
        target_date=target_date,
        run_nightly_async_tasks=lambda *_args: {"distilled_count": 0},
    )
    _assert(result["total_messages"] == 1, "目标自然日窗口不混入相邻日期消息")
    _assert(result["target_date"] == target_date.isoformat(), "分析结果记录目标日期")


def verify_cold_disk_scope_scan(temp_dir: Path) -> None:
    """冷启动扫描能发现不含 __scope__ 的 private 加权记忆文件。"""
    from memory.nightly.user_loader import load_users_from_disk

    old_cwd = Path.cwd()
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        os.chdir(temp_dir)
        weighted_dir = Path("companion_data/aveline_data/memories/weighted")
        weighted_dir.mkdir(parents=True)
        (weighted_dir / "private_alpha_weighted.json").write_text(
            '{"records": ["' + ("x" * 150) + '"]}', encoding="utf-8"
        )
        with patch(
            "memory.weighted_memory_manager.get_weighted_memory_manager",
            side_effect=lambda scope: {"scope": scope},
        ):
            loaded = load_users_from_disk()
    finally:
        os.chdir(old_cwd)
    _assert("private_alpha" in loaded, "冷启动包含 plain private scope")


async def verify_model_routes_and_cache_shape() -> None:
    """nightly 场景模型来自配置，偏好合并使用稳定 system 前缀。"""
    from config.model_config import get_character_daily_plan_model, get_journal_model
    from core.agents.chat_agent_components.persona_system.prompt.self_improvement_prompts import (
        PREFERENCE_MERGE_SYSTEM_PROMPT,
    )
    from core.services.self_improvement.core_memory_llm_merge import _call_llm
    from memory.nightly.config import get_memory_distillation_model, get_nightly_model_routes

    routes = get_nightly_model_routes()
    _assert(
        routes["daily_summary"] == get_journal_model(),
        "daily summary 模型来自 journal_model",
    )
    _assert(
        routes["user_plan"] == get_character_daily_plan_model(),
        "plan 模型来自 character_daily_models",
    )
    _assert(
        routes["distillation"] == get_memory_distillation_model(),
        "distillation 模型来自 memory_models",
    )

    captured: dict[str, Any] = {}

    class FakeLlm:
        async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
            captured["messages"] = messages
            captured["model_hint"] = kwargs.get("model_hint")
            return '{"merge_groups": []}'

    with patch("core.llm.get_llm_module", return_value=FakeLlm()):
        await _call_llm(
            PREFERENCE_MERGE_SYSTEM_PROMPT,
            "1. 动态偏好条目",
            routes["preference_merge"],
        )
    messages = captured["messages"]
    _assert([item["role"] for item in messages] == ["system", "user"], "偏好合并拆分 system/user")
    _assert("动态偏好条目" not in messages[0]["content"], "稳定 system prompt 不含动态条目")
    _assert(
        captured["model_hint"] == routes["preference_merge"],
        "偏好合并复用 journal 模型路由",
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="nightly_verify_") as temp:
        temp_dir = Path(temp)
        verify_once_and_persistent_skip(temp_dir)
        verify_sleep_trigger_precedes_fallback()
        verify_partial_resume(temp_dir)
        verify_calendar_window()
        verify_cold_disk_scope_scan(temp_dir / "disk")
        asyncio.run(verify_model_routes_and_cache_shape())
    print("nightly orchestration verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
