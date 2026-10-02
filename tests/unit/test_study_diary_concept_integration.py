"""知识点级学习数据接入角色日记的测试。

覆盖三件事：
1. 按日期读取学习事件（日记要回溯目标日期，不能用「最近 N 个文件」）；
2. 知识点日汇总的当天行为 / 当前快照两层口径；
3. 渲染进日记句子时「靠提示答出」不能被算成「自己答出」。
"""
from __future__ import annotations

from core.services.journal.persona_exports import (
    _build_concept_sentences,
    _build_study_sentence,
)
from core.services.study.learning_event import (
    AUTHORITY_OBSERVED,
    LearningEventType,
    get_learning_event_store,
)
from core.services.study.summary_builder import StudySummaryBuilder
from core.services.study.subject_analyzer import StudySubjectAnalyzer
from core.services.study.teaching_orchestrator import get_teaching_orchestrator
from core.utils.time_utils import now_str


# ----------------------------------------------------------------------
# 1. 按日期读取事件
# ----------------------------------------------------------------------


def test_read_date_returns_only_that_day(study_sandbox):
    store = get_learning_event_store()
    today = now_str("%Y-%m-%d")
    store.record(
        authority="confirmed",
        event_type=LearningEventType.TAUGHT,
        subject="physics",
        concept_id="c1",
        concept_name="简谐运动",
    )

    assert len(store.read_date(today)) == 1
    assert store.read_date("1999-01-01") == []


def test_read_date_does_not_fall_back_to_older_days(study_sandbox):
    """read(days=1) 会退回最近存在的文件，read_date 必须精确到天。"""
    store = get_learning_event_store()
    store.record(
        authority="confirmed",
        event_type=LearningEventType.TAUGHT,
        subject="math",
        concept_id="c1",
        concept_name="导数",
    )

    # 最近 N 天能读到（退回到今天这份文件）
    assert store.read(days=1, limit=10)
    # 精确日期查一个没有记录的过去日期，必须是空
    assert store.read_date("2000-06-06") == []


def test_diary_ignores_passive_telemetry(study_sandbox):
    """日记只记学习事实，不记遥测。

    被动观察捞到的「疑似提问 / 自称掌握」进不了日记——否则遥测就换了条路径
    被当成学习成果展示给用户，而用户没有任何办法分辨真假。
    """
    store = get_learning_event_store()
    today = now_str("%Y-%m-%d")
    store.record(
        authority=AUTHORITY_OBSERVED,
        event_type=LearningEventType.MASTERY_CLAIM,
        subject="physics",
        concept_name="哼哼猜猜看",
    )

    assert store.read_date(today) == []
    # 显式要求全量时才看得到
    assert len(store.read_date(today, authority=None)) == 1


# ----------------------------------------------------------------------
# 2. 知识点日汇总
# ----------------------------------------------------------------------


def _seed_mixed_day() -> None:
    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "简谐运动")
    orch.record_answer("physics", "简谐运动", {"correctness": 0.1, "independent": True})
    orch.record_answer("physics", "胡克定律", {"correctness": 0.9, "independent": True})
    orch.record_answer(
        "math", "导数", {"correctness": 0.9, "independent": False, "used_hint": True}
    )
    orch.record_confusion("physics", "相位", description="没听懂相位")


def test_daily_concept_summary_groups_events(study_sandbox):
    _seed_mixed_day()

    summary = get_teaching_orchestrator().get_daily_concept_summary()

    assert "简谐运动" in summary["taught"]
    assert "胡克定律" in summary["correct"]
    assert "简谐运动" in summary["incorrect"]
    assert "相位" in summary["confused"]
    assert "导数" in summary["hint_assisted"]


def test_daily_concept_summary_reports_snapshot(study_sandbox):
    _seed_mixed_day()

    summary = get_teaching_orchestrator().get_daily_concept_summary()

    # 当前快照部分
    assert summary["mastered_total"] == 0
    weak_names = {w["name"] for w in summary["weak"]}
    assert {"简谐运动", "相位"} <= weak_names
    assert summary["unverified_count"] >= 1


def test_daily_concept_summary_empty_without_data(study_sandbox):
    assert get_teaching_orchestrator().get_daily_concept_summary() == {}


def test_daily_concept_summary_for_past_date_has_no_today_activity(study_sandbox):
    _seed_mixed_day()

    summary = get_teaching_orchestrator().get_daily_concept_summary("2000-06-06")

    assert summary["taught"] == []
    assert summary["correct"] == []
    # 快照仍在，但渲染时会用「目前」措辞，不会写成「今天」
    assert "mastered_total" in summary


# ----------------------------------------------------------------------
# 3. 渲染成日记句子
# ----------------------------------------------------------------------


def test_diary_sentence_renders_concept_activity(study_sandbox):
    _seed_mixed_day()

    summary = get_teaching_orchestrator().get_daily_concept_summary()
    sentence = _build_study_sentence({"session": {}, "vocab": {}, "concepts": summary})

    assert "简谐运动" in sentence
    assert "胡克定律" in sentence
    assert "没听懂" in sentence


def test_hint_assisted_is_not_counted_as_independent(study_sandbox):
    """靠提示答出的知识点不能出现在「他自己答出了」里。"""
    sentences = _build_concept_sentences(
        {
            "taught": [],
            "correct": ["导数", "胡克定律"],
            "hint_assisted": ["导数"],
            "incorrect": [],
            "confused": [],
            "mastered_total": 0,
            "weak": [],
            "unverified_count": 0,
        }
    )
    joined = "；".join(sentences)

    independent_line = next(s for s in sentences if "他自己答出了" in s)
    assert "胡克定律" in independent_line
    assert "导数" not in independent_line
    assert "导数是靠提示才答出的" in joined


def test_snapshot_uses_current_tense_wording(study_sandbox):
    """当前快照必须用「目前」措辞，避免被读成当天发生的事。"""
    sentences = _build_concept_sentences(
        {
            "taught": [],
            "correct": [],
            "incorrect": [],
            "confused": [],
            "hint_assisted": [],
            "mastered_total": 7,
            "weak": [{"subject": "math", "name": "极限", "mastery": 0.2}],
            "unverified_count": 3,
        }
    )
    joined = "；".join(sentences)

    assert "目前累计掌握7个知识点" in joined
    assert "目前还薄弱的有极限" in joined
    assert "另有3个知识点" in joined


def test_concept_sentences_tolerate_bad_input(study_sandbox):
    assert _build_concept_sentences(None) == []
    assert _build_concept_sentences({}) == []
    assert _build_concept_sentences({"mastered_total": "not-a-number"}) == []


def test_study_sentence_keeps_legacy_vocab_part(study_sandbox):
    """原有「时长 / 词汇」部分不能被知识点部分挤掉。"""
    sentence = _build_study_sentence(
        {
            "session": {"study_duration_minutes": 45, "study_session_count": 2},
            "vocab": {"new_words": 8, "reviewed_words": 30},
            "concepts": {"taught": ["简谐运动"]},
        }
    )

    assert "学习时长约45分钟" in sentence
    assert "新增词汇8个" in sentence
    assert "简谐运动" in sentence


# ----------------------------------------------------------------------
# 4. 摘要组装与兼容性
# ----------------------------------------------------------------------


def test_summary_builder_includes_concepts_key(study_sandbox):
    builder = StudySummaryBuilder(StudySubjectAnalyzer())

    summary = builder.build_daily_summary(
        date="2026-09-12",
        dictionary_stats={},
        session_stats={},
        sessions=[],
        concept_summary={"taught": ["导数"]},
    )

    assert summary["concepts"] == {"taught": ["导数"]}


def test_summary_builder_without_concepts_is_backward_compatible(study_sandbox):
    """旧调用方不传 concept_summary 时不能报错，且既有字段保持完整。"""
    builder = StudySummaryBuilder(StudySubjectAnalyzer())

    summary = builder.build_daily_summary(
        date="2026-09-12",
        dictionary_stats={"to_review": 3, "learned_words": 10},
        session_stats={"words_reviewed": 5, "accuracy": 80.0},
        sessions=[],
    )

    assert summary["concepts"] == {}
    for key in ("date", "vocab", "session", "subjects", "overview", "next_day_blueprint", "suggestion"):
        assert key in summary


def test_study_service_digest_carries_concepts(study_sandbox):
    """真实链路：StudyService 的日报摘要要带上知识点级数据。"""
    from core.services.study.service import StudyService

    _seed_mixed_day()

    digest = StudyService().get_study_daily_digest()

    assert isinstance(digest.get("concepts"), dict)
    assert digest["concepts"], "日报摘要应包含知识点级数据"
    assert "简谐运动" in digest["concepts"]["taught"]


def test_study_digest_date_uses_project_timezone(study_sandbox, monkeypatch):
    """日报摘要必须用**项目时区**日期，不能用系统本地时区。

    CI 跑在 UTC 上，而项目时区兜底为 Asia/Shanghai；UTC 16:00 之后两者会差一天。
    若摘要用 time.strftime（系统时区）就会读不到当天事件，学习记录凭空消失。
    """
    import core.services.study.service as service_module
    from core.services.study.service import StudyService

    monkeypatch.setattr(service_module, "today_str", lambda: "2030-01-01")

    assert StudyService().get_study_daily_digest()["date"] == "2030-01-01"


def test_summary_builder_date_uses_project_timezone(monkeypatch):
    import core.services.study.summary_builder as builder_module

    monkeypatch.setattr(builder_module, "today_str", lambda: "2030-02-02")

    summary = StudySummaryBuilder(StudySubjectAnalyzer()).build_daily_summary(
        date="", dictionary_stats={}, session_stats={}, sessions=[]
    )
    assert summary["date"] == "2030-02-02"


def test_digest_reads_same_date_as_events_written(study_sandbox):
    """事件按项目时区落盘，摘要也必须用同一口径去读，否则 taught 为空。"""
    from core.services.study.service import StudyService
    from core.utils.time.time_utils import now_str

    get_teaching_orchestrator().record_teaching("physics", "简谐运动")
    project_date = now_str("%Y-%m-%d")

    digest = StudyService().get_study_daily_digest()

    assert digest["date"] == project_date, "摘要日期与事件落盘日期口径不一致"
    assert "简谐运动" in digest["concepts"]["taught"]

