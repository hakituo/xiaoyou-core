"""验证「复习到期英语词汇」计划项的实时数字不会被结转旧快照顶掉

背景（2026-09-10）：
    用户反馈：Aveline 说「复习到期英语词汇（61 个）」，但背单词 app 里
    实际显示 84 个待复习。核查 ``companion_data/user_data/daily`` 发现：

        9-09 plan.json  复习到期英语词汇（61 个）   source_key=vocab:due_review
        9-10 plan.json  复习到期英语词汇（61 个）   source_key=carryover:vocab:due_review

    9-10 的队列（``_review_queue_state.json``）实际是 84 个，说明计划里的
    61 是 9-09 生成那一刻的快照，被睡眠结算结转到 9-10 后一直没更新。

    两个独立缺陷叠加：

    1. 结转项的 base_score（14.0）高于实时到期候选（12.0）。两者
       repeat_key 都是 "vocab:due_review"，按 ``build`` 的去重规则
       「保留 base_score 更高的」，留下的永远是旧快照，当天正确数字
       被静默丢弃。

    2. 结转候选写回 ``PlanItem.source_key`` 时用的是 candidate.key
       （``carryover:<key>``），次日再结转又加一层，键会漂移成
       ``carryover:carryover:vocab:due_review``。同一个 repeat_key 不再
       相等，去重彻底失效，9-09 就同时存在 176 与 61 两条词汇计划。

本脚本固化两条约束：

- 词汇复习项按实时队列每天重算，不参与结转；
- 结转键必须剥离累积的 ``carryover:`` 前缀，保持跨天稳定。
"""

from __future__ import annotations

import inspect
import sys
from datetime import datetime
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


def _item(
    item_id: str,
    title: str,
    source_key: str,
    status: str = "skipped",
    settlement_reason: str = "sleep",
    carryover_count: int = 0,
    source_type: str = "algorithm",
):
    from core.services.journal.models import PlanItem

    return PlanItem(
        id=item_id,
        title=title,
        source_key=source_key,
        source_type=source_type,
        status=status,
        settlement_reason=settlement_reason,
        carryover_count=carryover_count,
    )


def _build(previous_items, due_today: int):
    from core.services.journal.models import DailyPlan
    from core.services.journal.plan_candidate_builder import (
        JournalPlanCandidateBuilder,
        JournalPlanningFacts,
    )
    from core.services.journal.plan_policy import JournalPlanSettings

    builder = JournalPlanCandidateBuilder(
        storage=None, settings=JournalPlanSettings()
    )
    previous = DailyPlan(date="2026-09-09", items=list(previous_items))
    facts = JournalPlanningFacts(
        review_overview={"due_today_count": due_today},
        previous_plan=previous,
    )
    return builder.build(datetime(2026, 9, 10), facts)


def test_live_vocab_beats_carryover_snapshot() -> None:
    _section("测试 1: 实时队列数字胜出，不再被结转旧快照顶掉")
    bundle = _build(
        [
            _item(
                "p_vocab",
                "复习到期英语词汇（61 个）",
                "vocab:due_review",
            ),
        ],
        due_today=84,
    )
    vocab = [
        candidate
        for candidate in bundle.candidates
        if (candidate.repeat_key or candidate.key) == "vocab:due_review"
    ]
    if len(vocab) == 1:
        _ok("词汇候选只有一条（不会与结转项并存）")
    else:
        _fail("词汇候选重复", f"共 {len(vocab)} 条: {[c.title for c in vocab]}")
        return
    title = vocab[0].title
    if "84" in title:
        _ok(f"标题使用当天实时数字: {title}")
    else:
        _fail("标题仍是结转旧快照", title)
    if vocab[0].base_score == 12.0:
        _ok("保留的是实时 due 候选（base_score=12.0）")
    else:
        _fail("保留的不是实时 due 候选", str(vocab[0].base_score))


def test_vocab_not_carried_over() -> None:
    _section("测试 2: 词汇复习项不参与结转")
    from core.services.journal.models import DailyPlan
    from core.services.journal.plan_candidate_builder import (
        JournalPlanCandidateBuilder,
    )
    from core.services.journal.plan_policy import JournalPlanSettings

    builder = JournalPlanCandidateBuilder(
        storage=None, settings=JournalPlanSettings()
    )
    items = [
        _item("p1", "复习到期英语词汇（61 个）", "vocab:due_review"),
        _item(
            "p2",
            "复习到期英语词汇（176 个）",
            "carryover:carryover:vocab:due_review",
            carryover_count=1,
        ),
        _item(
            "p3",
            "复核昨日词汇复习线索（7 个）",
            "vocab:due_review",
        ),
    ]
    eligible = builder._eligible_carryovers(  # noqa: SLF001
        DailyPlan(date="2026-09-09", items=items)
    )
    if eligible == []:
        _ok("三种形态的词汇项（实时/多层前缀/复核线索）都被排除")
    else:
        _fail("词汇项仍在结转候选里", str([item.title for item in eligible]))


def test_non_vocab_still_carries_over() -> None:
    _section("测试 3: 非词汇项仍可结转，且不因排除逻辑误删")
    bundle = _build(
        [
            _item(
                "p_general",
                "巩固昨日重点：general",
                "yesterday_subject:general",
            ),
        ],
        due_today=0,
    )
    carryovers = [
        candidate for candidate in bundle.candidates if candidate.source == "carryover"
    ]
    if [candidate.title for candidate in carryovers] == ["巩固昨日重点：general"]:
        _ok("普通未完成项正常结转")
    else:
        _fail("普通项结转异常", str([c.title for c in carryovers]))


def test_carryover_key_prefix_stripped() -> None:
    _section("测试 4: 结转键剥离累积前缀，repeat_key 跨天稳定")
    from core.services.journal.plan_candidate_builder import (
        JournalPlanCandidateBuilder,
    )

    item = _item(
        "p_general",
        "巩固昨日重点：general",
        "carryover:carryover:yesterday_subject:general",
        carryover_count=1,
    )
    stable = JournalPlanCandidateBuilder._stable_key(item)  # noqa: SLF001
    if stable == "yesterday_subject:general":
        _ok(f"三层前缀被剥离为稳定键: {stable}")
    else:
        _fail("稳定键剥离失败", stable)

    bundle = _build([item], due_today=0)
    carryover = next(
        candidate for candidate in bundle.candidates if candidate.source == "carryover"
    )
    if carryover.repeat_key == "yesterday_subject:general":
        _ok("结转候选 repeat_key 回到稳定键（不再逐日累积）")
    else:
        _fail("repeat_key 仍带累积前缀", str(carryover.repeat_key))
    if carryover.key == "carryover:yesterday_subject:general":
        _ok("候选 key 保留单个 carryover 前缀作为来源标识")
    else:
        _fail("候选 key 形态异常", carryover.key)


def test_production_code_has_guard() -> None:
    _section("测试 5: 生产代码确实接入词汇项排除逻辑")
    from core.services.journal.plan_candidate_builder import (
        JournalPlanCandidateBuilder,
    )

    src = inspect.getsource(JournalPlanCandidateBuilder._eligible_carryovers)  # noqa: SLF001
    if "_is_live_vocab_review" in src:
        _ok("_eligible_carryovers 已排除实时词汇项")
    else:
        _fail("_eligible_carryovers 未接入排除逻辑", src[:400])

    carryover_src = inspect.getsource(
        JournalPlanCandidateBuilder._build_carryover_candidates  # noqa: SLF001
    )
    if "_stable_key" in carryover_src:
        _ok("_build_carryover_candidates 使用稳定键")
    else:
        _fail("结转候选仍直接用被污染的 source_key", carryover_src[:400])


def main() -> int:
    print("=" * 64)
    print("词汇计划实时数字新鲜度 & 结转键稳定性 验证")
    print("=" * 64)

    test_live_vocab_beats_carryover_snapshot()
    test_vocab_not_carried_over()
    test_non_vocab_still_carries_over()
    test_carryover_key_prefix_stripped()
    test_production_code_has_guard()

    print("\n" + "=" * 64)
    print(f"结果: {_PASSED} 通过 / {_FAILED} 失败")
    print("=" * 64)
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
