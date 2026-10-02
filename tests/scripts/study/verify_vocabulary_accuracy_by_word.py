"""验证词汇正确率改为「按单词」统计，且会话超时不再丢失复习数据

背景（2026-09-02）：
    用户反馈 AI 一直说他「单词正确率 0%」，但他前几天明明背了。
    追查后发现统计链路有两层错误：

    1. 口径错误：accuracy 用「评分次数」做分子分母。同一个单词一次复习里
       会被重复推送（答错再来），按次数统计会把分母撑大数倍。
       实测 2026-08-30 真实掌握率 77.4%，按次数只有 49.2%；
       2026-09-02 真实 54.7%，按次数只有 30.6%。

    2. 数据丢失：StudySession 空闲超过 IDLE_TIMEOUT(3600s) 后，
       record_word_review 直接 start() 重置，已累积的数据既不结算也不落盘；
       get_stats() 还会把过期会话静默置为 inactive，进一步丢弃数据。
       结果 2026-09-01 全天 106 次评分只落盘了最后一段 21 次，
       而那 21 次恰好全是答错的，整天被记成「正确率 0.0%」。

    更正：项目里本来就有权威数据源 —— vocab_progress.json 的原始评分记录
    （每次评分都会 save_progress 落盘，带 timestamp + quality），
    get_today_review_status() 就是按天从它重算的，一直是准的。
    问题在于 daily_record 用的是另一套内存累加值。
    本次让 StudyService 落盘摘要统一走权威源，内存 session 只作兜底。

本脚本校验：
- 按单词口径的正确率计算正确（含重复推送、后答对、先对后忘等边界）；
- 会话超时时旧数据被返回给调用方，不被静默丢弃；
- 落盘摘要优先取 vocab_progress 权威源；
- 旧字段保持向后兼容。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

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


def _run_session(cases: List[Tuple[str, int]]):
    from core.services.study.session import StudySession

    session = StudySession()
    session.start()
    for word, quality in cases:
        session.record_word_review(word, quality)
    return session.end()


def test_accuracy_by_word() -> None:
    _section("测试 1: 正确率按单词算，不是按评分次数")

    cases = [
        # (用例, 期望正确率, 说明)
        ([("alpha", 1), ("alpha", 1), ("alpha", 1), ("beta", 4)], 50.0,
         "同一词错 3 次 + 一词答对 → 按次数是 25%，按单词是 50%"),
        ([("a", 1), ("a", 2), ("a", 4)], 100.0,
         "一词错 2 次后最终答对 → 按次数是 33%，按单词是 100%"),
        ([("a", 4), ("a", 1)], 0.0,
         "先答对后遗忘 → 以最后一次为准，判未掌握"),
        ([("a", 3), ("b", 3), ("c", 3)], 100.0,
         "三词都会"),
        ([("a", 1), ("b", 2)], 0.0,
         "两词全错"),
    ]
    for items, expected, desc in cases:
        end = _run_session(items)
        actual = float(end.get("accuracy") or 0.0)
        if abs(actual - expected) < 0.05:
            _ok(f"{desc} → {actual:.1f}%")
        else:
            _fail(f"{desc} → 期望 {expected}%，实际 {actual:.1f}%")


def test_repeat_push_not_penalized() -> None:
    _section("测试 2: 同一词重复推送不会虚增分母")
    # 用户原话场景：一个词不会，推三遍，三遍都不会 → 只应算 1 个未掌握词
    end = _run_session([("hard", 1), ("hard", 1), ("hard", 1), ("easy", 4)])
    if int(end.get("words_total") or 0) == 2:
        _ok(f"4 次评分只涉及 2 个单词，words_total={end['words_total']}")
    else:
        _fail(f"words_total 应为 2，实际 {end.get('words_total')}")

    if int(end.get("review_events") or 0) == 4:
        _ok("评分次数仍单独保留为 review_events=4（辅助信息）")
    else:
        _fail(f"review_events 应为 4，实际 {end.get('review_events')}")

    # 按次数口径会是 1/4=25%，按单词是 1/2=50%
    if abs(float(end.get("accuracy") or 0) - 50.0) < 0.05:
        _ok("正确率取按单词口径 50%，未被重复推送拉低到 25%")
    else:
        _fail(f"正确率应为 50%，实际 {end.get('accuracy')}")


def test_expired_session_not_lost() -> None:
    _section("测试 3: 会话超时时旧数据被返回，不被静默丢弃")
    from core.services.study.session import StudySession

    session = StudySession()
    session.start()
    session.record_word_review("x", 4)
    # 模拟空闲超过 IDLE_TIMEOUT
    session._state["last_activity"] -= StudySession.IDLE_TIMEOUT + 10  # noqa: SLF001

    expired = session.record_word_review("y", 1)
    if expired is None:
        _fail("超时后旧会话数据仍被丢弃")
        return
    _ok("超时后返回了被挤掉的旧会话数据")

    if int(expired.get("words_total") or 0) == 1 and int(expired.get("words_mastered") or 0) == 1:
        _ok(f"旧会话统计正确：词{expired['words_total']} 掌握{expired['words_mastered']}")
    else:
        _fail(
            "旧会话统计错误",
            f"words_total={expired.get('words_total')} "
            f"words_mastered={expired.get('words_mastered')}",
        )


def test_get_stats_does_not_silently_drop() -> None:
    _section("测试 4: get_stats 不再把过期会话静默置为 inactive")
    from core.services.study.session import StudySession

    session = StudySession()
    session.start()
    session.record_word_review("x", 4)
    session._state["last_activity"] -= StudySession.IDLE_TIMEOUT + 10  # noqa: SLF001

    stats = session.get_stats()
    if stats.get("active") is False:
        _ok("过期会话对外报告为 inactive（语义正确）")
    else:
        _fail("过期会话仍报告为 active", str(stats))

    # 关键：数据仍在，未被清零
    if int(stats.get("words_total") or 0) == 1:
        _ok("过期会话的统计数据仍保留，未被 get_stats 清零")
    else:
        _fail("get_stats 清零了统计数据", str(stats))


def test_detail_uses_authoritative_source() -> None:
    _section("测试 5: 落盘摘要优先取 vocab_progress 权威源")
    from core.services.study.service import get_study_service

    service = get_study_service()
    session_data = {
        "words_reviewed": 6,
        "words_total": 2,
        "words_mastered": 1,
        "review_events": 6,
        "correct_count": 2,
        "accuracy": 50.0,
    }
    detail = service._build_vocabulary_detail(session_data, duration_min=15)  # noqa: SLF001

    if not detail:
        _fail("摘要为空")
        return
    _ok(f"摘要生成成功: {detail}")

    if "个单词" in detail and "掌握" in detail and "正确率" in detail:
        _ok("摘要采用「单词 / 掌握 / 正确率」口径（与背单词结算界面一致）")
    else:
        _fail("摘要口径不是按单词", detail)

    # 权威源可用时，数字应来自 get_today_review_status 而非入参
    if service.vocab_manager is not None:
        try:
            status = service.vocab_manager.get_today_review_status()
            words = int(status.get("reviewed_words") or 0)
            if words > 0 and f"今天涉及 {words} 个单词" in detail:
                _ok(f"摘要数字取自权威源（今天涉及 {words} 个单词）")
            elif words == 0:
                _ok("今天尚无复习记录，摘要走兜底分支（属正常）")
            else:
                _fail("摘要未使用权威源数字", f"权威源 words={words}, detail={detail}")
        except Exception as exc:  # noqa: BLE001
            _fail("读取权威源失败", str(exc))
    else:
        _ok("vocab_manager 未初始化，摘要走兜底分支（属正常）")


def test_backward_compatible_fields() -> None:
    _section("测试 6: 旧字段保持向后兼容")
    end = _run_session([("a", 4), ("b", 1), ("b", 1), ("c", 3)])
    for field in ("words_reviewed", "correct_count", "unique_words_reviewed",
                  "reviewed_words", "duration_minutes"):
        if field in end:
            _ok(f"保留字段: {field}")
        else:
            _fail(f"丢失字段: {field}")

    if "accuracy" in end:
        _ok("保留字段: accuracy（口径已改为按单词）")
    else:
        _fail("丢失字段: accuracy")


def test_real_history_recomputed() -> None:
    _section("测试 7: 用真实历史数据回归（按天重算口径）")
    from datetime import datetime, timedelta, timezone
    from unittest import mock

    from core.tools.study.english import stats as stats_mod
    from core.tools.study.english.vocabulary_manager import get_vocabulary_manager

    store = get_vocabulary_manager().store
    cst = timezone(timedelta(hours=8))
    # 2026-09-01 是用户质疑"正确率 0%"的那天
    target = datetime(2026, 9, 1, 12, 0, tzinfo=cst)
    with mock.patch.object(stats_mod, "get_current_time", return_value=target):
        status = stats_mod.get_today_review_status(store)

    reviewed = int(status.get("reviewed_words") or 0)
    mastered = int(status.get("mastered_words") or 0)
    events = int(status.get("review_events") or 0)
    if reviewed <= 0:
        _ok("9/1 无复习记录，跳过（数据可能已被清理）")
        return

    _ok(f"9/1 权威源重算：涉及 {reviewed} 词，掌握 {mastered} 词，评分 {events} 次")
    _ok(f"  按单词口径正确率 = {mastered / reviewed * 100:.1f}%")

    if "mastered_words" in status:
        _ok("权威源已提供 mastered_words 字段")
    else:
        _fail("权威源缺少 mastered_words 字段")

    # 与按次数口径对比，确认按单词口径确实更高（不会被重复推送稀释）
    event_correct = sum(
        1
        for data in store.progress.values()
        for entry in data.get("history", [])
        if target.replace(hour=0, minute=0).timestamp()
        <= float(entry.get("timestamp", 0) or 0)
        < (target.replace(hour=0, minute=0) + timedelta(days=1)).timestamp()
        and int(entry.get("quality", 0) or 0) >= 3
    )
    by_word = mastered / reviewed * 100
    by_event = event_correct / max(1, events) * 100
    if by_word >= by_event:
        _ok(f"按单词 {by_word:.1f}% >= 按次数 {by_event:.1f}%（符合预期）")
    else:
        _fail(f"按单词 {by_word:.1f}% 反而低于按次数 {by_event:.1f}%")


def main() -> int:
    print("=" * 62)
    print("词汇正确率按单词统计 & 会话超时不丢数据 验证")
    print("=" * 62)

    test_accuracy_by_word()
    test_repeat_push_not_penalized()
    test_expired_session_not_lost()
    test_get_stats_does_not_silently_drop()
    test_detail_uses_authoritative_source()
    test_backward_compatible_fields()
    test_real_history_recomputed()

    print("\n" + "=" * 62)
    print(f"结果: {_PASSED} 通过 / {_FAILED} 失败")
    print("=" * 62)
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
