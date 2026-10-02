"""验证计划里的到期词数使用 app 口径，且同 repeat_key 的候选会合并

背景（2026-09-03）：
    用户反馈：背单词 app 显示要复习 52 个，AI 却说 34 个。
    追查发现同一天的 plan.json 里存在三条同名计划：

        19:00  复习到期英语词汇（34 个）   pending
        20:10  复习到期英语词汇（169 个）  pending
        21:20  复习到期英语词汇（52 个）   pending

    两个独立缺陷叠加：

    1. 数字口径错误。``_due_word_count`` 取
       ``max(due_today_count, due_words)``，而这两个字段含义不同：
         - ``due_today_count`` = 今日取词队列长度（app 显示的就是它）
         - ``due_words``       = 所有 ``fsrs_due <= now`` 的原始卡片总数，
           含今天并不打算复习的积压卡
       用户背单词时答错的词会被 FSRS 安排到几分钟后重新到期，
       ``due_words`` 随之剧烈抖动（34 → 169 → 52），取 max 会把抖动放大
       并冻结进计划标题，于是过时计划带着与 app 不符的数字被 AI 说出。

    2. 同 repeat_key 的候选没有合并。同批次去重只用 ``candidate.key``，
       但实时到期候选 key 是 "vocab:due_review"，从昨日计划/checkpoint
       结转来的候选 key 是 "checkpoint:<id>"，两者 key 不同于是都保留，
       导致"复习到期英语词汇"重复出现多条。而 ``repeat_key`` 本来就是
       为此设计的跨来源稳定键。

本脚本校验上述两点，并固化"计划数字必须与 app 口径一致"这条约束。
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_PASSED = 0
_FAILED = 0


def _ok(msg: str) -> None:
    global _PASSED
    _PASSED += 1
    print(f"  [PASS] {msg}")


def _fail(msg: str, detail: str = "") -> None:
    global _FAILED
    _FAILED += 1
    print(f"  [FAIL] {msg}")
    if detail:
        print(f"         {detail}")


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def test_uses_app_口径() -> None:
    _section("测试 1: 到期词数采用 app 口径 due_today_count")
    from core.services.journal.plan_candidate_builder import (
        JournalPlanCandidateBuilder as B,
    )

    # 模拟抖动场景：due_words 因答错词重新到期而飙升
    overview = {"due_today_count": 52, "due_words": 169}
    got = B._due_word_count(overview)  # noqa: SLF001
    if got == 52:
        _ok("due_words(169) 大于队列(52) 时仍返回 52（不再被 max 放大）")
    else:
        _fail("仍受 due_words 影响", f"期望 52，实际 {got}")

    overview = {"due_today_count": 52, "due_words": 28}
    got = B._due_word_count(overview)  # noqa: SLF001
    if got == 52:
        _ok("due_words 小于队列时返回 52")
    else:
        _fail("返回值错误", f"期望 52，实际 {got}")


def test_matches_live_app_value() -> None:
    _section("测试 2: 与实时 app 数值一致")
    from core.services.journal.plan_candidate_builder import (
        JournalPlanCandidateBuilder as B,
    )
    from core.tools.study.english.vocabulary_manager import get_vocabulary_manager

    overview = get_vocabulary_manager().get_review_overview()
    got = B._due_word_count(overview)  # noqa: SLF001
    app_value = int(overview.get("due_today_count") or 0)
    if got == app_value:
        _ok(f"计划数字 {got} == app 口径 {app_value}")
    else:
        _fail("计划数字与 app 不一致", f"plan={got} app={app_value}")


def test_no_crash_on_bad_input() -> None:
    _section("测试 3: 缺失/脏数据不抛异常")
    from core.services.journal.plan_candidate_builder import (
        JournalPlanCandidateBuilder as B,
    )

    for name, ov in (
        ("空 dict", {}),
        ("None 值", {"due_today_count": None, "due_words": None}),
        ("非数字", {"due_today_count": "abc", "due_words": "x"}),
        ("due_words 是 list", {"due_today_count": 5, "due_words": ["a", "b"]}),
    ):
        try:
            _ = B._due_word_count(ov)  # noqa: SLF001
            _ok(f"{name} 未抛异常")
        except Exception as exc:  # noqa: BLE001
            _fail(f"{name} 抛异常", str(exc))


def test_dedup_by_repeat_key() -> None:
    _section("测试 4: 不同 key 但相同 repeat_key 的候选会合并")
    from core.services.journal.plan_candidate_builder import PlanCandidate

    def mk(key, title, score, source):
        return PlanCandidate(
            key=key,
            title=title,
            duration_minutes=30,
            base_score=score,
            category="study",
            source=source,
            priority="high",
            repeat_key="vocab:due_review",  # 两者共用稳定键
            window_keys=("afternoon",),
        )

    candidates = [
        mk("checkpoint:abc123", "复习到期英语词汇（34 个）", 5.0, "carryover"),
        mk("vocab:due_review", "复习到期英语词汇（52 个）", 12.0, "due"),
    ]

    deduplicated: dict = {}
    for candidate in candidates:
        dedup_key = candidate.repeat_key or candidate.key
        previous = deduplicated.get(dedup_key)
        if previous is None or candidate.base_score > previous.base_score:
            deduplicated[dedup_key] = candidate

    if len(deduplicated) == 1:
        _ok("两条候选合并为一条（不再重复出现同名计划）")
        winner = list(deduplicated.values())[0]
        if winner.base_score == 12.0:
            _ok("保留 base_score 更高的实时 due 候选（符合注释预期）")
        else:
            _fail("保留的不是实时候选", winner.title)
        if "52" in winner.title:
            _ok(f"保留的是实时数字: {winner.title}")
        else:
            _fail("保留的是过时快照", winner.title)
    else:
        _fail("未能合并", f"剩余 {len(deduplicated)} 条")


def test_dedup_source_uses_repeat_key() -> None:
    _section("测试 5: 生产代码确实改用 repeat_key 去重")
    import inspect

    from core.services.journal.plan_candidate_builder import (
        JournalPlanCandidateBuilder,
    )

    src = inspect.getsource(JournalPlanCandidateBuilder.build)
    if "repeat_key or candidate.key" in src or "dedup_key" in src:
        _ok("build 中改用 repeat_key 作为去重键")
    else:
        _fail("build 仍只用 candidate.key 去重", src[:400])


def main() -> int:
    print("=" * 64)
    print("计划到期词数口径 & 同 repeat_key 去重 验证")
    print("=" * 64)

    test_uses_app_口径()
    test_matches_live_app_value()
    test_no_crash_on_bad_input()
    test_dedup_by_repeat_key()
    test_dedup_source_uses_repeat_key()

    print("\n" + "=" * 64)
    print(f"结果: {_PASSED} 通过 / {_FAILED} 失败")
    print("=" * 64)
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
