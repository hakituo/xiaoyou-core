"""共享确定性计划引擎端到端静态/行为验证。

运行：venv_core/Scripts/python.exe tests/scripts/planning/verify_deterministic_planning.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.services.character_daily.daily_plan import DailyPlanGenerator  # noqa: E402
from core.services.journal.models import DailyPlan, PlanItem  # noqa: E402
from core.services.journal.plan_candidate_builder import (  # noqa: E402
    JournalPlanCandidateBuilder,
    JournalPlanningFacts,
)
from core.services.journal.plan_policy import JournalPlanSettings  # noqa: E402
from core.services.planning import (  # noqa: E402
    DeterministicPlanEngine,
    PlanPolicy,
    minutes_to_hhmm,
)


def _assert_no_overlap(entries) -> None:
    intervals = sorted((entry.start_minute, entry.end_minute) for entry in entries)
    assert all(left[1] <= right[0] for left, right in zip(intervals, intervals[1:]))


def _verify_no_plan_llm_path() -> None:
    forbidden = {
        "core/services/journal/plan_service.py": (
            "call_llm_stream",
            "submit_llm_task",
        ),
        "core/services/journal/plan_checkpoint_service.py": (
            "PLAN_REASSESSMENT",
            "submit_llm_task",
            "get_global_scheduler",
        ),
        "core/services/character_daily/engine.py": (
            "from core.services.character_daily.llm_plan_generator import",
            "isinstance(self._generator, LLMPlanGenerator)",
            "for role_id in KNOWN_ROLES",
            "role_ids=KNOWN_ROLES",
        ),
    }
    for relative_path, tokens in forbidden.items():
        text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        for token in tokens:
            assert token not in text, f"{relative_path} 仍包含计划 LLM 路径: {token}"


def _build_user_example() -> list[dict]:
    settings = JournalPlanSettings()
    previous = DailyPlan(
        date="2099-01-04",
        items=[
            PlanItem(
                title="完成昨日数学错题",
                subject="数学",
                status="skipped",
                settlement_reason="sleep",
                source_key="math:error_review",
            )
        ],
    )
    facts = JournalPlanningFacts(
        review_overview={"due_today_count": 10, "due_words": 7},
        due_weaknesses=[
            {
                "id": "physics-induction",
                "subject": "物理",
                "topic": "电磁感应综合题",
                "confidence": 2.0,
            }
        ],
        yesterday_summary={
            "subjects": [{"subject": "化学", "minutes": 50}],
            "overview": {"total_sessions": 3, "top_subjects": ["化学"]},
            "next_day_blueprint": {
                "timed_blocks": [
                    {"name": "核心学习块", "time": "14:00", "duration_minutes": 60}
                ],
                "untimed_blocks": [
                    {"name": "记录今日学习总结", "duration_minutes": 20}
                ],
                "priority_subjects": ["化学"],
            },
        },
        previous_plan=previous,
    )
    builder = JournalPlanCandidateBuilder(storage=None, settings=settings)
    bundle = builder.build(datetime(2099, 1, 5), facts)
    result = DeterministicPlanEngine().schedule(
        plan_key="user|2099-01-05",
        candidates=bundle.candidates,
        windows=bundle.policy.windows,
        policy=PlanPolicy(
            max_items=bundle.policy.max_items,
            capacity_minutes=bundle.policy.capacity_minutes,
            buffer_minutes=10,
        ),
    )
    assert len(result.scheduled) <= bundle.policy.max_items
    assert result.used_minutes <= bundle.policy.capacity_minutes
    _assert_no_overlap(result.scheduled)
    return [
        {
            "time": minutes_to_hhmm(entry.start_minute),
            "title": entry.candidate.title,
            "minutes": entry.candidate.duration_minutes,
            "source": entry.candidate.source,
            "score": round(entry.score, 2),
        }
        for entry in result.scheduled
    ]


def _build_role_examples() -> dict[str, object]:
    generator = DailyPlanGenerator()
    output: dict[str, list[dict]] = {}
    generated_roles: list[str] = []
    for role_id in generator.role_ids:
        plan = generator.generate(role_id, "2099-01-05")
        assert plan is not None
        generated_roles.append(role_id)
        if role_id in {"aveline", "ling"}:
            output[role_id] = [
                {
                    "time": slot.planned_start.strftime("%H:%M"),
                    "activity": slot.activity.value,
                    "minutes": round(slot.duration_minutes()),
                }
                for slot in plan.slots[:8]
            ]
    assert tuple(generated_roles) == generator.role_ids
    assert output["aveline"] != output["ling"]
    return {
        "generated_roles": generated_roles,
        "examples": output,
    }


def main() -> int:
    _verify_no_plan_llm_path()
    payload = {
        "user_plan_example": _build_user_example(),
        "character_plan_examples": _build_role_examples(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("PASS: 共享确定性计划引擎、全部模板角色覆盖、无计划 LLM 路径验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
