"""验证安卓端背完单词后，当天计划的英语词汇项会被标记为 completed

背景（2026-09-03）：
    用户反馈"我都背完了，他为什么会 skip"。核查发现计划里的
    "复习到期英语词汇"项**从未变成 completed**，全是 skipped：

        9/2   08:00（166 个）skipped / 09:10（169 个）skipped / 10:20（34 个）skipped
        9/1   08:00（166 个）skipped / 09:10（72 个）skipped / 10:20（169 个）skipped
        8/31  08:00（72 个）skipped / 09:10（57 个）skipped / 10:20（166 个）skipped

    根因链条：
      1. 用户在安卓端背完单词，没有任何机制把计划项标记为 completed；
      2. 晚上睡眠结算把未完成项统一打成 skipped（settlement_reason=sleep）；
      3. plan_candidate_builder 允许这类 skipped 项结转到次日
         （item.status == "skipped" and item.settlement_reason == "sleep"）；
      4. 结转项与当天新生成的计划叠加，"复习到期英语词汇"出现多条、
         数字天天漂移（166 / 169 / 34 / 72 …）；
      5. AI 读到前几天结转来的旧数字，于是说出与 app 不符的词数。

    修复：在 POST /vocab/review 提交评分后调用
    ``_mark_vocab_plan_completed_if_done``，一旦实时状态显示今日词汇任务
    已完成，就把当天计划里的英语词汇项标记为 completed，从源头切断结转链。
    该模式参照已有的起床提醒处理（checker_event_handler 中同样调用
    journal.mark_plan_item_status 标记 completed）。

本脚本校验：未完成时不动作、完成时正确标记、只认词汇项、异常被吞掉不影响主流程。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

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


def _make_plan(items: List[Any]):
    return SimpleNamespace(items=items)


def _item(item_id: str, title: str, source_key: str, status: str = "pending"):
    return SimpleNamespace(
        id=item_id, title=title, source_key=source_key, status=status,
        end_reminder_id=None,
    )


def _install_fake_journal(monkeypatch, plan) -> Dict[str, Any]:
    """替换 journal 服务，记录被调用的情况。"""
    calls: Dict[str, Any] = {"marked": [], "get_plan_calls": 0}

    async def fake_get_plan(date=None):
        calls["get_plan_calls"] += 1
        return plan

    async def fake_mark(date, item_id, status):
        calls["marked"].append((date, item_id, status))
        return SimpleNamespace(id=item_id, status=status)

    fake_journal = SimpleNamespace(
        get_plan=fake_get_plan, mark_plan_item_status=fake_mark
    )

    import core.services.journal.service as journal_mod

    monkeypatch.setattr(journal_mod, "get_journal_service", lambda: fake_journal)
    return calls


def test_no_action_when_incomplete() -> None:
    _section("测试 1: 今日尚未完成时不做任何事")
    import pytest

    from routers.v1.vocab import _mark_vocab_plan_completed_if_done

    monkeypatch = pytest.MonkeyPatch()
    try:
        calls = _install_fake_journal(monkeypatch, _make_plan([
            _item("p1", "复习到期英语词汇（52 个）", "vocab:due_review"),
        ]))
        service = SimpleNamespace(
            get_today_review_status=lambda: {"completed": False, "reviewed_words": 3}
        )
        got = asyncio.run(_mark_vocab_plan_completed_if_done(service))
        if got is False:
            _ok("未完成时返回 False")
        else:
            _fail("未完成却返回 True")
        if calls["marked"]:
            _fail("未完成却标记了计划项", str(calls["marked"]))
        else:
            _ok("未调用 mark_plan_item_status")
    finally:
        monkeypatch.undo()


def test_marks_completed_when_done() -> None:
    _section("测试 2: 今日完成时标记词汇计划项")
    import pytest

    from routers.v1.vocab import _mark_vocab_plan_completed_if_done

    monkeypatch = pytest.MonkeyPatch()
    try:
        calls = _install_fake_journal(monkeypatch, _make_plan([
            _item("p_other", "巩固昨日重点：english", "yesterday_subject:english"),
            _item("p_vocab", "复习到期英语词汇（52 个）", "vocab:due_review"),
        ]))
        service = SimpleNamespace(
            get_today_review_status=lambda: {
                "completed": True, "reviewed_words": 52, "remaining_words": 0,
            }
        )
        got = asyncio.run(_mark_vocab_plan_completed_if_done(service))
        if got is True:
            _ok("完成时返回 True")
        else:
            _fail("完成却未返回 True")

        if len(calls["marked"]) == 1:
            date, item_id, status = calls["marked"][0]
            _ok(f"标记了 1 项: id={item_id} status={status}")
            if item_id == "p_vocab":
                _ok("标记的是词汇项（未误标其它计划）")
            else:
                _fail("标记了错误的项", item_id)
            if status == "completed":
                _ok("状态为 completed（不再是 skipped）")
            else:
                _fail("状态不是 completed", status)
        else:
            _fail("标记数量异常", str(calls["marked"]))
    finally:
        monkeypatch.undo()


def test_skips_already_completed() -> None:
    _section("测试 3: 已完成的项不重复标记")
    import pytest

    from routers.v1.vocab import _mark_vocab_plan_completed_if_done

    monkeypatch = pytest.MonkeyPatch()
    try:
        calls = _install_fake_journal(monkeypatch, _make_plan([
            _item("p_vocab", "复习到期英语词汇（52 个）", "vocab:due_review",
                  status="completed"),
        ]))
        service = SimpleNamespace(
            get_today_review_status=lambda: {"completed": True}
        )
        got = asyncio.run(_mark_vocab_plan_completed_if_done(service))
        if got is False and not calls["marked"]:
            _ok("已是 completed 时跳过，不重复标记")
        else:
            _fail("仍尝试标记已完成项", str(calls["marked"]))
    finally:
        monkeypatch.undo()


def test_matches_by_title_when_key_missing() -> None:
    _section("测试 4: source_key 缺失时按标题匹配")
    import pytest

    from routers.v1.vocab import _mark_vocab_plan_completed_if_done

    monkeypatch = pytest.MonkeyPatch()
    try:
        calls = _install_fake_journal(monkeypatch, _make_plan([
            _item("p_legacy", "复习到期英语词汇（34 个）", ""),
        ]))
        service = SimpleNamespace(
            get_today_review_status=lambda: {"completed": True}
        )
        got = asyncio.run(_mark_vocab_plan_completed_if_done(service))
        if got is True and calls["marked"] and calls["marked"][0][1] == "p_legacy":
            _ok("按标题兜底匹配成功（兼容历史计划项）")
        else:
            _fail("标题兜底匹配失败", str(calls["marked"]))
    finally:
        monkeypatch.undo()


def test_exception_swallowed() -> None:
    _section("测试 5: 异常被吞掉，不影响复习主流程")
    import pytest

    from routers.v1.vocab import _mark_vocab_plan_completed_if_done

    monkeypatch = pytest.MonkeyPatch()
    try:
        # journal 抛异常
        import core.services.journal.service as journal_mod

        def boom():
            raise RuntimeError("journal 不可用")

        monkeypatch.setattr(journal_mod, "get_journal_service", boom)
        service = SimpleNamespace(
            get_today_review_status=lambda: {"completed": True}
        )
        got = asyncio.run(_mark_vocab_plan_completed_if_done(service))
        if got is False:
            _ok("journal 异常时安全返回 False，不向上抛")
        else:
            _fail("异常未被吞掉")

        # service 本身异常
        bad_service = SimpleNamespace(
            get_today_review_status=lambda: (_ for _ in ()).throw(ValueError("x"))
        )
        got2 = asyncio.run(_mark_vocab_plan_completed_if_done(bad_service))
        if got2 is False:
            _ok("service 异常时安全返回 False")
        else:
            _fail("service 异常未被吞掉")
    finally:
        monkeypatch.undo()


def main() -> int:
    print("=" * 66)
    print("安卓端背完单词 → 计划项标记 completed 验证")
    print("=" * 66)

    try:
        import pytest  # noqa: F401
    except ImportError:
        print("需要 pytest（提供 MonkeyPatch）")
        return 1

    test_no_action_when_incomplete()
    test_marks_completed_when_done()
    test_skips_already_completed()
    test_matches_by_title_when_key_missing()
    test_exception_swallowed()

    print("\n" + "=" * 66)
    print(f"结果: {_PASSED} 通过 / {_FAILED} 失败")
    print("=" * 66)
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
