"""验证人物档案只在蒸馏发现人物/角色演化线索时调用 LLM。

本脚本不发送真实 LLM 请求，覆盖：
1. 蒸馏响应的人物线索与角色演化线索解析；
2. 普通对话经过门控后人物提取为 0 次 LLM；
3. 蒸馏信号只选中时间相邻的原始聊天批次；
4. 未进入加权记忆的原始聊天仍有零 API 保守兜底；
5. scope 阶段不再执行人物提取，全量 manager 只转交全局阶段一次。

运行：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe \
        -m tests.scripts.nightly_prompt_cache.verify_people_profile_signal_gate
"""

from __future__ import annotations

import asyncio
import datetime
import sys
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def verify_distillation_signal_parsing() -> None:
    """蒸馏同时输出普通梗概和人物门控元数据。"""
    from memory.nightly.task_runner import NightlyTaskRunner

    response = (
        "【梗概】：用户提到张老师会检查项目进度\n"
        "【关键词】：项目,检查\n"
        "【人物线索】：张老师\n"
        "【角色演化】：无"
    )
    metadata = NightlyTaskRunner.parse_profile_signals(response)
    _assert(metadata["profile_signal_analyzed"], "完整解析人物门控字段")
    _assert(metadata["people_mentions"] == ["张老师"], "保留外部人物线索")
    _assert(not metadata["role_update_candidates"], "无角色演化时保持空列表")

    batch_response = (
        "【条目1】\n【梗概】：普通技术讨论\n【关键词】：技术\n"
        "【人物线索】：无\n【角色演化】：无\n\n"
        "【条目2】\n【梗概】：Ling 表达新的长期偏好\n【关键词】：偏好\n"
        "【人物线索】：无\n【角色演化】：Ling"
    )
    batch = NightlyTaskRunner.parse_batch_profile_signals(batch_response)
    _assert(not batch[1]["people_mentions"], "普通条目标记为无人物")
    _assert(
        batch[2]["role_update_candidates"] == ["Ling"],
        "角色演化线索按条目落位",
    )


def verify_distillation_metadata_persistence_path() -> None:
    """批量蒸馏解析后的线索必须传给记忆管理器落盘。"""
    from memory.nightly.task_runner import NightlyTaskRunner

    response = (
        "【条目1】\n【梗概】：用户提到张老师会检查项目\n"
        "【关键词】：项目,检查\n【人物线索】：张老师\n【角色演化】：无"
    )

    class _Chunks:
        def __aiter__(self):
            return self._iterate()

        async def _iterate(self):
            yield response

    class _Scheduler:
        @staticmethod
        def submit_llm_task(_prompt: Any, **_kwargs: Any) -> _Chunks:
            return _Chunks()

    class _DistillManager:
        def __init__(self) -> None:
            self.lock = threading.RLock()
            self.weighted_memories = {
                "m1": {
                    "id": "m1",
                    "role": "user",
                    "content": "今天张老师说会检查项目的缓存实现和测试结果。",
                    "timestamp": time.time() - 7200,
                    "is_distilled": False,
                }
            }
            self.saved_metadata: dict[str, Any] | None = None

        def update_memory_distillation(
            self,
            _memory_id: str,
            _summary: str,
            _keywords: list[str],
            distillation_metadata: dict[str, Any] | None = None,
        ) -> bool:
            self.saved_metadata = distillation_metadata
            return True

    manager = _DistillManager()
    runner = NightlyTaskRunner(
        {
            "distillation_threshold_hours": 1,
            "max_distill_per_night": 10,
            "distillation_batch_size": 10,
            "distillation_group_gap_minutes": 30,
        }
    )
    with patch(
        "memory.nightly.task_runner.get_global_scheduler",
        return_value=_Scheduler(),
    ):
        distilled = asyncio.run(runner.distill_memories_async("scope", manager))
    _assert(distilled == 1, "人物线索条目完成批量蒸馏")
    _assert(
        manager.saved_metadata is not None
        and manager.saved_metadata["people_mentions"] == ["张老师"],
        "蒸馏人物线索沿更新接口传入持久化层",
    )


class _MemoryManager:
    def __init__(self, memories: dict[str, dict[str, Any]]) -> None:
        self.lock = threading.RLock()
        self.weighted_memories = memories


def verify_no_signal_means_zero_llm() -> None:
    """蒸馏确认无线索，且本地兜底未命中时，详细提取不发请求。"""
    from core.character.people.extractor import PeopleProfileExtractor

    extractor = PeopleProfileExtractor()
    extractor._load_state = lambda: {"last_processed_timestamp": 0.0}
    extractor._get_new_messages = lambda _last_ts: [
        {"role": "user", "content": "今天把缓存命中率调好了", "timestamp": 1000.0},
        {"role": "assistant", "content": "日志已经验证通过", "timestamp": 1001.0},
    ]
    saved_states: list[dict[str, Any]] = []
    extractor._save_state = saved_states.append
    extractor._call_llm_with_prompt = AsyncMock(
        side_effect=AssertionError("无线索批次不应调用 LLM")
    )
    manager = _MemoryManager(
        {
            "m1": {
                "id": "m1",
                "timestamp": 1000.0,
                "distillation_metadata": {
                    "profile_signal_analyzed": True,
                    "people_mentions": [],
                    "role_update_candidates": [],
                },
            }
        }
    )

    result = asyncio.run(
        extractor.extract_and_update(
            "__global__",
            memory_managers={"scope": manager},
        )
    )
    _assert(result["llm_batches"] == 0, "无线索的 nightly 人物提取为 0 次 LLM")
    _assert(result["skipped"] == "no_profile_signals", "记录无线索跳过原因")
    _assert(bool(saved_states), "无线索批次仍推进增量水位，避免下晚重复扫描")
    _assert(extractor._call_llm_with_prompt.await_count == 0, "未进入详细提取器")


def verify_candidate_batch_selection() -> None:
    """人物线索仅放行时间相邻批次，不恢复全量扫描。"""
    from core.character.people.extractor import PeopleProfileExtractor

    batches = [
        [{"role": "user", "content": "项目进展", "timestamp": 1000.0}],
        [{"role": "user", "content": "晚饭记录", "timestamp": 5000.0}],
    ]
    selected = PeopleProfileExtractor._select_candidate_batches(
        batches,
        [{"timestamp": 1000.0, "hints": ["张老师"]}],
        signal_type="people",
    )
    _assert(selected == [batches[0]], "蒸馏人物信号只选中相邻原始批次")

    local_selected = PeopleProfileExtractor._select_candidate_batches(
        [[{"role": "user", "content": "我妈妈明天来", "timestamp": 9000.0}]],
        [],
        signal_type="people",
    )
    _assert(bool(local_selected), "未入加权记忆的人物关系词由零 API 规则兜底")


def verify_scope_and_global_wiring() -> None:
    """人物提取从每个 scope 移到每晚一次的 global 阶段。"""
    from memory.nightly.task_runner import NightlyTaskRunner
    from memory.nightly_processor import NightlyProcessor

    runner = NightlyTaskRunner({"distillation_enabled": True})
    scope_result = asyncio.run(
        runner.execute_scope_tasks(
            "scope_a",
            object(),
            AsyncMock(return_value=2),
        )
    )
    _assert(
        scope_result["people_profiles"] == "deferred_to_global_gate",
        "scope 阶段只蒸馏，不运行人物提取",
    )

    target_date = datetime.date(2026, 8, 24)
    managers = {"scope_a": object(), "scope_b": object()}
    captured: list[tuple[datetime.date, Any]] = []

    class _TaskRunnerBridge:
        async def execute_global_tasks(
            self,
            date: datetime.date,
            memory_managers: Any = None,
        ) -> dict[str, Any]:
            captured.append((date, memory_managers))
            return {"daily_summary": True}

        @staticmethod
        def run_nightly_async_tasks(
            user_id: str,
            manager: Any,
            executor: Any,
        ) -> dict[str, Any]:
            return asyncio.run(executor(user_id, manager))

    processor = NightlyProcessor(config={"auto_run": False})
    bridge = _TaskRunnerBridge()
    processor._get_task_runner = lambda: bridge
    processor._run_nightly_global_tasks(target_date, managers)
    _assert(captured == [(target_date, managers)], "全量 manager 仅转交 global 门控一次")


def main() -> int:
    verify_distillation_signal_parsing()
    verify_distillation_metadata_persistence_path()
    verify_no_signal_means_zero_llm()
    verify_candidate_batch_selection()
    verify_scope_and_global_wiring()
    print("\n[PASS] 人物档案蒸馏线索门控验证全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
