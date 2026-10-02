"""学习专项总结（StudySummaryGenerator）接入知识点级数据的测试。

重点守两条：
1. 知识点级段落必须真的出现在给 LLM 的结构化上下文里；
2. 靠提示答出的不能被写进「独立答对」，否则总结会夸大掌握程度。
"""
from __future__ import annotations

from core.services.study.summary_generator import StudySummaryGenerator
from core.services.study.teaching_orchestrator import get_teaching_orchestrator
from core.utils.time_utils import now_str


def _seed() -> None:
    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "简谐运动")
    orch.record_answer("physics", "简谐运动", {"correctness": 0.1, "independent": True})
    orch.record_answer("physics", "胡克定律", {"correctness": 0.9, "independent": True})
    orch.record_answer(
        "math", "导数", {"correctness": 0.9, "independent": False, "used_hint": True}
    )
    orch.record_confusion("physics", "相位", description="没听懂")


def _context() -> str:
    return StudySummaryGenerator()._build_structured_context(now_str("%Y-%m-%d"))


def test_concept_section_present(study_sandbox):
    _seed()
    ctx = _context()

    assert "【知识点级学习状态】" in ctx
    assert "知识点总数: 4" in ctx


def test_day_activity_is_listed(study_sandbox):
    _seed()
    ctx = _context()

    assert "当天讲解过: 简谐运动" in ctx
    assert "当天答错: 简谐运动" in ctx
    assert "当天自述没听懂: 相位" in ctx


def test_hint_assisted_is_not_counted_as_independent(study_sandbox):
    """靠提示答出的知识点不能出现在「独立答对」里。"""
    _seed()
    ctx = _context()

    assert "当天独立答对: 胡克定律" in ctx
    assert "当天靠提示答出（未真正掌握）: 导数" in ctx
    # 导数只应在「靠提示」那一行，不能同时算独立答对
    independent_line = next(line for line in ctx.splitlines() if "当天独立答对" in line)
    assert "导数" not in independent_line


def test_weak_and_unverified_reported(study_sandbox):
    _seed()
    ctx = _context()

    assert "目前仍薄弱" in ctx
    assert "还没检验过" in ctx


def test_no_concepts_yields_no_section(study_sandbox):
    """没有任何知识点时不能输出空段落，也不能报错。"""
    ctx = _context()

    assert "【知识点级学习状态】" not in ctx


def test_daily_concept_summary_has_total(study_sandbox):
    """消费方依赖 total_concepts 字段，缺失会导致静默 KeyError。"""
    _seed()

    summary = get_teaching_orchestrator().get_daily_concept_summary()

    assert summary["total_concepts"] == 4
    assert summary["weak_count"] == 2
