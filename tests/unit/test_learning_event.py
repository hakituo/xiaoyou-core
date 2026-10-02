"""LearningEvent 学习事件日志测试。

覆盖：事件正确写入、顺序正确、不污染其他 subject / concept，
以及 **authority 权威边界**（学习事实 vs 非权威遥测）与老数据兼容。

authority 的要害在于「谁有资格被当成事实」：被动正则捞到的东西只能算遥测，
常规读取（prompt / ZPD / 日记）默认看不到它。这些用例把这条边界钉死。
"""
from __future__ import annotations

import json

import pytest

from core.services.study.learning_event import (
    AUTHORITY_CONFIRMED,
    AUTHORITY_OBSERVED,
    LearningEvent,
    LearningEventStore,
    LearningEventType,
    effective_authority,
)


def _store(sandbox) -> LearningEventStore:
    return LearningEventStore(sandbox / ".state" / "learning_events")


def test_event_is_written_and_readable(study_sandbox):
    store = _store(study_sandbox)
    store.record(
        authority=AUTHORITY_CONFIRMED,
        event_type=LearningEventType.TAUGHT,
        subject="physics",
        concept_id="c1",
        concept_name="胡克定律",
    )

    events = store.read(days=1, limit=10)
    assert len(events) == 1
    assert events[0].event_type == LearningEventType.TAUGHT
    assert events[0].concept_name == "胡克定律"
    assert events[0].timestamp
    assert events[0].authority == AUTHORITY_CONFIRMED


def test_event_order_is_preserved(study_sandbox):
    store = _store(study_sandbox)
    for event_type in (
        LearningEventType.TAUGHT,
        LearningEventType.QUESTION_ASKED,
        LearningEventType.ANSWER_INCORRECT,
        LearningEventType.HINT_GIVEN,
        LearningEventType.ANSWER_CORRECT,
    ):
        store.record(
            authority=AUTHORITY_CONFIRMED,
            event_type=event_type,
            subject="physics",
            concept_id="c1",
            concept_name="胡克定律",
        )

    events = store.read(days=1, limit=10)
    assert [e.event_type for e in events] == [
        LearningEventType.TAUGHT,
        LearningEventType.QUESTION_ASKED,
        LearningEventType.ANSWER_INCORRECT,
        LearningEventType.HINT_GIVEN,
        LearningEventType.ANSWER_CORRECT,
    ]


def test_events_do_not_leak_across_subject_or_concept(study_sandbox):
    store = _store(study_sandbox)
    store.record(
        authority=AUTHORITY_CONFIRMED,
        event_type=LearningEventType.TAUGHT,
        subject="physics",
        concept_id="c-physics",
        concept_name="简谐运动",
    )
    store.record(
        authority=AUTHORITY_CONFIRMED,
        event_type=LearningEventType.TAUGHT,
        subject="math",
        concept_id="c-math",
        concept_name="导数",
    )

    physics = store.read(concept_id="c-physics", days=1, limit=10)
    math = store.read(concept_id="c-math", days=1, limit=10)
    math_by_subject = store.read(subject="math", days=1, limit=10)

    assert [e.concept_name for e in physics] == ["简谐运动"]
    assert [e.concept_name for e in math] == ["导数"]
    assert [e.concept_name for e in math_by_subject] == ["导数"]


def test_event_quality_is_clamped(study_sandbox):
    store = _store(study_sandbox)
    event = store.record(
        authority=AUTHORITY_CONFIRMED,
        event_type=LearningEventType.ANSWER_CORRECT,
        subject="math",
        concept_id="c1",
        concept_name="导数",
        quality=3.5,
    )
    assert event.quality == 1.0


def test_single_corrupt_line_does_not_break_read(study_sandbox):
    store = _store(study_sandbox)
    store.record(
        authority=AUTHORITY_CONFIRMED,
        event_type=LearningEventType.TAUGHT,
        subject="math",
        concept_id="c1",
        concept_name="导数",
    )

    event_dir = study_sandbox / ".state" / "learning_events"
    path = next(event_dir.glob("*.jsonl"))
    with open(path, "a", encoding="utf-8") as f:
        f.write("{ broken json line\n")

    store.record(
        authority=AUTHORITY_CONFIRMED,
        event_type=LearningEventType.ANSWER_CORRECT,
        subject="math",
        concept_id="c1",
        concept_name="导数",
    )

    events = store.read(days=1, limit=10)
    assert len(events) == 2


# ======================================================================
# authority 边界（本模块的核心不变量）
# ======================================================================


def test_record_requires_explicit_authority(study_sandbox):
    """authority 必须显式给出。

    故意不给默认值：默认成 ``confirmed`` 会让遥测静默伪装成事实，
    默认成 ``observed`` 又会让真正的教学记录被降权。两种默认都是错的，
    所以只能强制调用方自己表态。
    """
    store = _store(study_sandbox)
    with pytest.raises(TypeError):
        store.record(  # type: ignore[call-arg]
            event_type=LearningEventType.TAUGHT, subject="physics", concept_name="胡克定律"
        )


def test_record_rejects_invalid_authority(study_sandbox):
    store = _store(study_sandbox)
    with pytest.raises(ValueError):
        store.record(
            authority="maybe",
            event_type=LearningEventType.TAUGHT,
            subject="physics",
            concept_name="胡克定律",
        )


def test_default_read_returns_confirmed_only(study_sandbox):
    """常规读取默认只看学习事实——遥测不能顺手漏进 prompt / ZPD / 日记。"""
    store = _store(study_sandbox)
    store.record(
        authority=AUTHORITY_CONFIRMED,
        event_type=LearningEventType.TAUGHT,
        subject="physics",
        concept_id="c1",
        concept_name="胡克定律",
    )
    store.record(
        authority=AUTHORITY_OBSERVED,
        event_type=LearningEventType.QUESTION_ASKED,
        subject="physics",
        concept_id="c1",
        concept_name="哼哼猜猜看",
    )

    default_events = store.read(days=1, limit=10)
    assert [e.event_type for e in default_events] == [LearningEventType.TAUGHT]

    observed = store.read(days=1, limit=10, authority=AUTHORITY_OBSERVED)
    assert [e.event_type for e in observed] == [LearningEventType.QUESTION_ASKED]

    everything = store.read(days=1, limit=10, authority=None)
    assert len(everything) == 2


def test_read_date_defaults_to_confirmed(study_sandbox):
    """日记按天回溯历史，也只看事实。"""
    from core.utils.time_utils import now_str

    store = _store(study_sandbox)
    day = now_str("%Y-%m-%d")
    store.record(
        authority=AUTHORITY_CONFIRMED,
        event_type=LearningEventType.TAUGHT,
        subject="physics",
        concept_name="胡克定律",
    )
    store.record(
        authority=AUTHORITY_OBSERVED,
        event_type=LearningEventType.MASTERY_CLAIM,
        subject="physics",
        concept_name="哼哼猜猜看",
    )

    assert len(store.read_date(day)) == 1
    assert len(store.read_date(day, authority=None)) == 2


def test_illegal_authority_filter_raises(study_sandbox):
    """筛选值写错比不筛选更危险，宁可炸出来。"""
    store = _store(study_sandbox)
    with pytest.raises(ValueError):
        store.read(days=1, limit=10, authority="confirmedish")


def test_appended_event_must_carry_authority(study_sandbox):
    """``append()`` 同样拦住缺 authority 的事件，不留后门。"""
    store = _store(study_sandbox)
    with pytest.raises(ValueError):
        store.append(LearningEvent(event_type=LearningEventType.TAUGHT, subject="physics"))


# ======================================================================
# 老数据兼容（不重写历史文件）
# ======================================================================


@pytest.mark.parametrize(
    "event_type, source, expected",
    [
        (LearningEventType.TAUGHT, "chat", AUTHORITY_CONFIRMED),
        (LearningEventType.EXPLAINED, "chat", AUTHORITY_CONFIRMED),
        (LearningEventType.HINT_GIVEN, "chat", AUTHORITY_CONFIRMED),
        (LearningEventType.ANSWER_CORRECT, "chat", AUTHORITY_CONFIRMED),
        (LearningEventType.ANSWER_INCORRECT, "chat", AUTHORITY_CONFIRMED),
        (LearningEventType.ANSWER_PARTIAL, "chat", AUTHORITY_CONFIRMED),
        (LearningEventType.REVIEW_SUCCESS, "review", AUTHORITY_CONFIRMED),
        (LearningEventType.REVIEW_FAILURE, "review", AUTHORITY_CONFIRMED),
        (LearningEventType.QUESTION_ASKED, "chat", AUTHORITY_OBSERVED),
        (LearningEventType.ANSWER_PENDING_EVALUATION, "chat", AUTHORITY_OBSERVED),
        (LearningEventType.MASTERY_CLAIM, "api", AUTHORITY_OBSERVED),
    ],
)
def test_legacy_authority_inferred_by_event_type(event_type, source, expected):
    """老数据缺 authority 时按事件类型推断；source 不参与这类判断。"""
    event = LearningEvent(event_type=event_type, source=source)
    assert event.authority == ""
    assert effective_authority(event) == expected


@pytest.mark.parametrize(
    "source, expected",
    [
        ("tool", AUTHORITY_CONFIRMED),
        ("api", AUTHORITY_CONFIRMED),
        ("review", AUTHORITY_CONFIRMED),
        ("self_reported", AUTHORITY_CONFIRMED),
        ("chat", AUTHORITY_OBSERVED),
        ("", AUTHORITY_OBSERVED),
    ],
)
def test_legacy_confusion_uses_source_only_for_ambiguity(source, expected):
    """自述没听懂是最有歧义的一类：对 AI 说的算事实，聊天流里捞的不算。

    判不准时**失败关闭**降级为 observed：宁可少认一条事实，不可多认一条。
    """
    event = LearningEvent(
        event_type=LearningEventType.SELF_REPORTED_CONFUSION, source=source
    )
    assert effective_authority(event) == expected


def test_explicit_authority_beats_inference(study_sandbox):
    """写了 authority 就以它为准，不再回头猜类型。"""
    event = LearningEvent(
        event_type=LearningEventType.TAUGHT, source="chat", authority=AUTHORITY_OBSERVED
    )
    assert effective_authority(event) == AUTHORITY_OBSERVED


def test_legacy_file_without_authority_is_readable(study_sandbox):
    """老 JSONL 没有 authority 字段，仍要能读出来，且**不重写原文件**。

    这是 append-only 的底线：兼容靠读取时推断，不靠改写历史。
    """
    store = _store(study_sandbox)
    event_dir = study_sandbox / ".state" / "learning_events"
    event_dir.mkdir(parents=True, exist_ok=True)
    from core.utils.time_utils import now_str

    day = now_str("%Y-%m-%d")
    path = event_dir / f"{day}.jsonl"
    legacy = {
        "event_id": "legacy0001",
        "event_type": "taught",
        "subject": "physics",
        "concept_id": "c1",
        "concept_name": "胡克定律",
        "timestamp": f"{day}T10:00:00",
        "source": "chat",
    }
    path.write_text(json.dumps(legacy, ensure_ascii=False) + "\n", encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    # 老数据按类型推断成 confirmed，因此默认读取能拿到
    events = store.read(days=1, limit=10)
    assert len(events) == 1
    assert events[0].concept_name == "胡克定律"
    assert effective_authority(events[0]) == AUTHORITY_CONFIRMED

    # 原文件一个字节都没被动过
    assert path.read_text(encoding="utf-8") == before
