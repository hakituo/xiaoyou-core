"""教学闭环的 runtime 路径测试（Agent / 工具层，而非只测 service 方法）。

验证真实的执行链：
    用户消息 -> 学习信号识别 -> 工具被选中 -> 工具执行 -> 状态落盘
    -> 下一次对话能读到并利用
"""
from __future__ import annotations

import json

from core.agents.chat_agent_components.study import observe_learning_message
from core.services.study.concept_state import ConceptStatus
from core.services.study.learning_event import LearningEventType
from core.services.study.signal_detector import (
    LearningIntent,
    detect_learning_signal,
)
from core.services.study.teaching_orchestrator import get_teaching_orchestrator
from core.tools.registry import ToolRegistry, register_all_tools
from core.tools.tool_policy import select_role_tools


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_all_tools(registry)
    return registry


async def _call(registry: ToolRegistry, name: str, **params) -> dict:
    tool = registry.get_tool(name)
    assert tool is not None, f"工具未注册: {name}"
    raw = await tool._run(**params)
    return json.loads(raw)


# ----------------------------------------------------------------------
# 信号识别 -> 工具选择
# ----------------------------------------------------------------------


def test_ordinary_chat_question_is_recognized_as_learning():
    signal = detect_learning_signal("为什么 F = -kx 里面有负号？")

    assert signal.is_learning is True
    assert signal.intent == LearningIntent.TEACHING_REQUEST
    assert signal.subject == "physics"
    assert any("kx" in c for c in signal.concepts)


def test_non_learning_chatter_is_not_captured():
    assert detect_learning_signal("今天天气怎么样").is_learning is False
    assert detect_learning_signal("为什么你今天不开心").is_learning is False


def test_study_tools_are_selectable_in_chat_and_study_mode():
    study_tools = select_role_tools("为什么 F = -kx 有负号", mode="study")
    assert {"study_get_context", "study_record_answer", "study_record_teaching"} <= set(study_tools)

    chat_tools = select_role_tools("我没听懂", mode="chat")
    assert "study_record_confusion" in chat_tools
    assert "study_get_context" in chat_tools


# ----------------------------------------------------------------------
# 工具执行 -> 状态落盘 -> 下一轮可读
# ----------------------------------------------------------------------


async def test_tool_runtime_closed_loop(study_sandbox):
    registry = _registry()

    # 1) 讲解一个知识点
    taught = await _call(
        registry, "study_record_teaching", subject="physics", concept="简谐运动"
    )
    assert taught["status"] == "success"
    assert taught["status_after"] == "learning"

    # 2) 用户答错
    wrong = await _call(
        registry,
        "study_record_answer",
        subject="physics",
        concept="简谐运动",
        correctness=0.1,
        independent=True,
    )
    assert wrong["verdict"] == "incorrect"
    assert wrong["status_after"] == "weak"

    # 3) 用户独立答对 4 次 -> 掌握
    for _ in range(4):
        ok = await _call(
            registry,
            "study_record_answer",
            subject="physics",
            concept="简谐运动",
            correctness=0.95,
            independent=True,
        )
    assert ok["status_after"] == "mastered"

    # 4) 下一次对话读取状态（模拟新一轮 session）
    ctx = await _call(registry, "study_get_context", message="简谐运动", subject="physics")
    assert ctx["status"] == "success"
    concept = next(
        c for c in ctx["data"]["target_concepts"] if c["name"] == "简谐运动"
    )
    assert concept["status"] == "mastered"
    assert concept["mastery"] >= 0.8


async def test_answer_payload_is_rejected_when_untrustworthy(study_sandbox):
    """载荷不可信时必须放弃状态更新，而不是记成答错。"""
    registry = _registry()
    await _call(registry, "study_record_teaching", subject="math", concept="导数")

    bad = await _call(
        registry,
        "study_record_answer",
        subject="math",
        concept="导数",
        correctness=0.9,
        independent=True,
    )
    # 先确认合法载荷是成功的
    assert bad["status"] == "success"

    orch = get_teaching_orchestrator()
    rejected = orch.record_answer("math", "导数", "not-a-json-payload")
    assert rejected["status"] == "error"

    state = orch.concepts.get_by_name("math", "导数")
    # 非法载荷没有产生额外证据
    assert state.evidence_count == 2


async def test_teaching_never_marks_mastered(study_sandbox):
    registry = _registry()
    for _ in range(5):
        await _call(
            registry, "study_record_teaching", subject="math", concept="极限", action="taught"
        )

    state = get_teaching_orchestrator().concepts.get_by_name("math", "极限")
    assert state.taught_count == 5
    assert state.status.value == "learning"
    assert state.mastery == 0.0


# ----------------------------------------------------------------------
# 普通聊天自动观察：**非权威遥测，永不建状态、永不改状态**
# ----------------------------------------------------------------------


def test_observe_message_records_question_without_creating_concept(study_sandbox):
    """普通聊天里的提问只留遥测痕迹，**不建知识点**。

    这是被测过的那条错误路径：以前 observe 会 ``get_or_create``，于是一句
    「为什么 F = -kx 里面有负号？」就把「F = -kx」永久物化成知识点。现在
    它必须只落一条 ``observed`` 事件，ConceptState 里什么都不该多出来。
    """
    result = observe_learning_message("为什么 F = -kx 里面有负号？")

    assert result["status"] == "recorded"
    assert result["intent"] == "teaching_request"
    assert result["authority"] == "observed"

    orch = get_teaching_orchestrator()
    # 核心不变量：被动观察无权创建知识点
    assert orch.concepts.get_by_name("physics", "F = -kx") is None

    # 痕迹照样落盘（能观察、能留痕），只是没有 concept_id
    observed = orch.events.read(days=1, limit=10, authority="observed")
    assert len(observed) == 1
    assert observed[0].event_type.value == "question_asked"
    assert observed[0].concept_id == ""


def test_observe_message_does_not_record_plain_chatter(study_sandbox):
    result = observe_learning_message("今天好累啊")
    assert result["status"] == "skipped"


def test_observe_confusion_does_not_downgrade_state(study_sandbox):
    """被动困惑**不能**把知识点推成 weak。

    用户对 AI 说「我没听懂」和有正则从聊天记录里捞到一句「没听懂」是两回事。
    后者只能留痕；要真正改状态，必须由 LLM 显式调 ``study_record_confusion``。
    """
    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "简谐运动")
    before = orch.concepts.get_by_name("physics", "简谐运动")

    result = observe_learning_message("我还是没听懂")

    assert result["status"] == "recorded"
    assert result["intent"] == "confusion"
    assert result["concepts"] == ["简谐运动"]
    assert result["authority"] == "observed"

    after = orch.concepts.get_by_name("physics", "简谐运动")
    # 状态、掌握度、证据计数一个都不能动
    assert after.status.value == before.status.value == "learning"
    assert after.mastery == before.mastery == 0.0
    assert after.evidence_count == before.evidence_count

    # 但痕迹绑定到了正确的知识点上，方便后续追溯
    observed = orch.events.read(days=1, limit=10, authority="observed")
    assert [e.concept_id for e in observed] == [before.concept_id]
    assert observed[0].event_type.value == "self_reported_confusion"


def test_observe_does_not_create_concept_from_loose_text(study_sandbox):
    """连科目都靠回落时，也不能造概念。"""
    orch = get_teaching_orchestrator()

    result = observe_learning_message("我没听懂，压缩是什么意思")

    # 没有任何已确认的知识点可回落 → 跳过，而不是新建「压缩」
    assert result["status"] == "skipped"
    assert orch.concepts.get_by_name("physics", "压缩") is None


def test_mastery_claim_does_not_grant_mastery(study_sandbox):
    """自称掌握只留痕，绝不置为 mastered。"""
    orch = get_teaching_orchestrator()
    orch.record_teaching("math", "导数")

    observe_learning_message("导数我懂了")

    state = orch.concepts.get_by_name("math", "导数")
    assert state.status.value != "mastered"
    assert state.mastery == 0.0


def test_explicit_confusion_does_downgrade_state(study_sandbox):
    """对照组：显式 API 才有权改状态。

    只断言「存在对应的 confirmed confusion 事件」，不对 confirmed 事件总数做
    脆弱断言——``record_teaching`` 本来就先写了一条 TAUGHT，总数不是本用例的意图。
    """
    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "简谐运动")

    orch.record_confusion("physics", "简谐运动", description="没听懂相位", source="tool")

    state = orch.concepts.get_by_name("physics", "简谐运动")
    assert state.status.value == "weak"

    confirmed = orch.events.read(days=1, limit=10)
    confusions = [
        e for e in confirmed if e.event_type == LearningEventType.SELF_REPORTED_CONFUSION
    ]
    assert len(confusions) == 1
    assert confusions[0].authority == "confirmed"


# ----------------------------------------------------------------------
# LLM 上下文注入
# ----------------------------------------------------------------------


def test_context_block_exposes_persistent_state(study_sandbox):
    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "简谐运动")
    orch.record_answer("physics", "简谐运动", {"correctness": 0.1, "independent": True})

    block = orch.get_context_block("讲讲简谐运动")

    assert "简谐运动" in block
    assert "学习状态" in block
    # 必须带上「不要因为用户说懂了就认为掌握」这类约束
    assert "懂了" in block


def test_context_block_is_empty_without_learning_state(study_sandbox):
    orch = get_teaching_orchestrator()
    assert orch.get_context_block("今天天气怎么样") == ""


def test_next_action_returns_zpd_and_action(study_sandbox):
    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "简谐运动", prerequisites=["胡克定律"])

    action = orch.next_action("讲讲简谐运动")

    assert action["zpd"]["level"] == "prerequisite_gap"
    assert action["zpd"]["missing_prerequisites"] == ["胡克定律"]
    assert action["action"]["action"] == "prerequisite_review"


def test_next_action_mastered_triggers_retrieval_test(study_sandbox):
    orch = get_teaching_orchestrator()
    for _ in range(4):
        orch.record_answer("math", "导数", {"correctness": 0.95, "independent": True})

    action = orch.next_action("导数是什么")
    assert action["zpd"]["level"] == "mastered"
    assert action["action"]["action"] == "retrieval_test"


def test_review_items_merge_concept_and_weakness_views(study_sandbox):
    orch = get_teaching_orchestrator()
    orch.record_answer("math", "导数", {"correctness": 0.1, "independent": True})
    _make_due_today(orch, "math", "导数")

    items = orch.get_review_items(limit=10)

    assert items["total"] >= 1
    names = {i["name"] for i in items["items"]}
    assert "导数" in names
    # 两个来源合并后不得出现重复项
    ids = [i["concept_id"] for i in items["items"]]
    assert len(ids) == len(set(ids))


def test_plan_includes_concept_reviews(study_sandbox):
    orch = get_teaching_orchestrator()
    orch.record_answer("math", "导数", {"correctness": 0.1, "independent": True})
    _make_due_today(orch, "math", "导数")

    plan = orch.get_plan()

    assert "concept_reviews" in plan
    assert plan["due_concept_count"] >= 1


def test_review_items_are_empty_before_due_date(study_sandbox):
    """间隔未到时不应提前塞进复习清单。"""
    orch = get_teaching_orchestrator()
    orch.record_answer("math", "导数", {"correctness": 0.1, "independent": True})

    assert orch.get_review_items(limit=10)["total"] == 0


# ----------------------------------------------------------------------
# 用户作答的自动识别（只记痕迹，不判对错）
# ----------------------------------------------------------------------


def test_answer_attempt_records_pending_trace(study_sandbox):
    """回答不带知识点名时，应回落最近讨论的知识点并留下「待评价」痕迹。"""
    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "简谐运动")

    result = orch.observe_message("答案是回复力方向跟位移相反")

    assert result["status"] == "recorded"
    assert result["intent"] == "answer_attempt"
    assert result["concepts"] == ["简谐运动"]
    assert result["authority"] == "observed"

    observed = orch.events.read(days=1, limit=10, authority="observed")
    assert [e.event_type.value for e in observed] == ["answer_pending_evaluation"]


def test_answer_attempt_does_not_touch_mastery(study_sandbox):
    """核心约束：自动观察**绝不**改动掌握度，判定权在 LLM。"""
    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "简谐运动")
    before = orch.concepts.get_by_name("physics", "简谐运动")

    orch.observe_message("答案是回复力方向跟位移相反")
    after = orch.concepts.get_by_name("physics", "简谐运动")

    assert after.mastery == before.mastery == 0.0
    assert after.evidence_count == before.evidence_count == 1
    assert after.independent_success_streak == 0
    assert after.successful_retrievals == 0


def test_observed_pending_does_not_enter_prompt(study_sandbox):
    """被动捞到的「疑似作答」不进 prompt。

    待评价提醒曾经是遥测回到 LLM 眼前的一条捷径：正则捞到「答案是…」→ 落一条
    pending → prompt 提示「有 1 次作答尚未评价」→ LLM 顺手调
    ``study_record_answer`` 把它变成事实。这等于绕过了晋升门。
    第一版的结论很明确：**observed pending 不进 prompt**。
    """
    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "简谐运动")
    orch.observe_message("答案是回复力方向跟位移相反")

    ctx = orch.get_context("简谐运动")
    assert ctx["pending_evaluations"] == []

    block = orch.get_context_block("简谐运动")
    assert "尚未评价" not in block
    assert "study_record_answer" not in block


def test_confirmed_pending_still_nudges_llm(study_sandbox):
    """对照组：LLM 自己提过问却没评，属于**事实层**的缺口，该提醒还得提醒。"""
    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "简谐运动")
    # 显式工具写入的待评价痕迹（LLM 主动提问，尚未评价）
    state = orch.concepts.get_by_name("physics", "简谐运动")
    orch.events.record(
        authority="confirmed",
        event_type=LearningEventType.ANSWER_PENDING_EVALUATION,
        subject="physics",
        concept_id=state.concept_id,
        concept_name=state.name,
        source="tool",
    )

    ctx = orch.get_context("简谐运动")
    assert ctx["pending_evaluations"] == [
        {"subject": "physics", "name": "简谐运动", "count": 1}
    ]

    block = orch.get_context_block("简谐运动")
    assert "尚未评价" in block
    assert "study_record_answer" in block

    # 补上评价后提醒消失，不会反复催
    orch.record_answer("physics", "简谐运动", {"correctness": 0.9, "independent": True})
    assert orch.get_context("简谐运动")["pending_evaluations"] == []


def test_answer_without_concept_and_without_context_is_skipped(study_sandbox):
    """没有最近讨论过的知识点时，不能凭空造一条记录。"""
    orch = get_teaching_orchestrator()

    assert orch.observe_message("答案是这样")["status"] == "skipped"


def test_answer_markers_avoid_high_frequency_words(study_sandbox):
    """「等于」「所以是」这类高频词不能被当成作答，否则会刷出大量误报。"""
    from core.services.study.signal_detector import LearningIntent, detect_learning_signal

    assert detect_learning_signal("这个等于那个").intent != LearningIntent.ANSWER_ATTEMPT
    assert detect_learning_signal("所以是这样的").intent != LearningIntent.ANSWER_ATTEMPT


def _make_due_today(orch, subject: str, name: str) -> None:
    """把某个知识点的复习日期拨到「今天到期」，用于验证到期路径。"""
    from core.utils.time_utils import now_str

    state = orch.concepts.get_by_name(subject, name)
    assert state is not None
    state.next_review_at = now_str("%Y-%m-%d")
    orch.concepts.save()
    orch.project(state)


def test_confusion_without_concept_binds_to_recent_concept(study_sandbox):
    """「我还是没听懂」不带任何 candidate concept 时，回落到最近讨论的知识点。

    这条测的是 **fallback 路径本身**：message 必须解析不出概念，否则走的是
    常规绑定分支，根本没验证回落。所以这里用一句纯困惑表达。
    """
    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "胡克定律")

    result = orch.observe_message("我还是没听懂")

    assert result["status"] == "recorded"
    assert result["intent"] == "confusion"
    assert result["subject"] == "physics"
    assert result["concepts"] == ["胡克定律"]

    state = orch.concepts.get_by_name("physics", "胡克定律")
    observed = orch.events.read(days=1, limit=10, authority="observed")
    assert observed[-1].concept_id == state.concept_id


def test_confusion_without_subject_binds_to_recent_subject(study_sandbox):
    """抽得出候选概念却认不出科目时（「我没听懂，压缩是什么意思」），
    科目回落到最近讨论过的 physics，整条证据不能因为缺科目被丢弃。

    注意「压缩」本身会被准入闸挡掉（裸名词、无科目证据），所以这里验证的是
    **科目回落**这条路径：丢掉的是候选，留下的是痕迹。
    """
    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "胡克定律")

    result = orch.observe_message("我没听懂，压缩是什么意思")

    assert result["status"] == "recorded"
    assert result["intent"] == "confusion"
    assert result["subject"] == "physics", "科目应回落到最近讨论的 physics"

    # 概念没有被物化（候选被闸挡掉 / 绑不上，都不建）
    assert orch.concepts.get_by_name("physics", "压缩") is None

    observed = orch.events.read(days=1, limit=10, authority="observed")
    assert len(observed) == 1
    assert observed[0].event_type == LearningEventType.SELF_REPORTED_CONFUSION
    # 回落到已确认知识点，因此带上了它的 concept_id
    state = orch.concepts.get_by_name("physics", "胡克定律")
    assert observed[0].concept_id == state.concept_id


def test_confusion_without_any_context_is_skipped(study_sandbox):
    """连最近讨论的知识点都没有时，不能凭空造记录。"""
    orch = get_teaching_orchestrator()

    assert orch.observe_message("我没听懂，这个是什么意思")["status"] == "skipped"


def test_latest_concept_ignores_unknown_shells(study_sandbox):
    """``latest_concept()`` 不能被没有学习证据的空壳劫持。

    历史数据里躺着被动观察留下的假阳性（「哼哼猜猜看」这类）：``get_or_create``
    建出来的 ``UNKNOWN / evidence_count=0`` 空壳，从没被真正教过，却因为
    ``first_seen_at`` 更晚而排在真知识点前面。一旦被 fallback 命中，就会成为
    新证据的载体，把假阳性继续传下去。

    **合法存在 ≠ confirmed**：预建一个 unknown 概念完全可以合法，但用户没学过它，
    就不该成为「我没听懂」的回落目标。
    """
    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "简谐运动")

    # 手工塞一个纯空壳（模拟历史脏数据），时间更晚
    shell = orch.concepts.get_or_create("physics", "哼哼猜猜看")
    assert shell.evidence_count == 0
    assert shell.status.value == "unknown"

    # 空壳因为 first_seen_at 更新而排在前面，但它不满足 confirmed
    assert not shell.is_confirmed_state

    # 回落必须落到真正教过的简谐运动，而不是更晚创建的空壳
    result = orch.observe_message("我还是没听懂")
    assert result["concepts"] == ["简谐运动"]


def test_is_confirmed_state_accepts_unknown_exclusion(study_sandbox):
    """对照：``is_confirmed_state`` 必须把 ``status != UNKNOWN`` 算作 confirmed。

    这里用 ``mark_confused``（不经过 ``mark_taught``）单独建一条——它会产生
    evidence 并把状态推出 UNKNOWN，属于显式权威状态。
    即便将来 ``evidence_count`` 这条判据被弱化，``status != UNKNOWN`` 也必须独立成立。
    """
    orch = get_teaching_orchestrator()

    state = orch.concepts.mark_confused("math", "集合")

    assert state.status != ConceptStatus.UNKNOWN
    assert state.is_confirmed_state

    # 纯 get_or_create 出来的仍是空壳，两者必须被区分开
    shell = orch.concepts.get_or_create("math", "还没学的东西")
    assert shell.status == ConceptStatus.UNKNOWN
    assert shell.evidence_count == 0
    assert not shell.is_confirmed_state


def test_confirmed_pending_evaluations_are_global(study_sandbox):
    """已确认的待评价必须全局可见：作答不写知识点名，按当前消息解析会得到空集合。

    这条保留了原设计的意图（不能只在「当前消息提到该知识点」时才提醒），
    但把输入从 observed 换成 confirmed——提醒是给**事实层缺口**用的。
    """
    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "简谐运动")
    state = orch.concepts.get_by_name("physics", "简谐运动")
    orch.events.record(
        authority="confirmed",
        event_type=LearningEventType.ANSWER_PENDING_EVALUATION,
        subject="physics",
        concept_id=state.concept_id,
        concept_name=state.name,
        source="tool",
    )

    # 用一句完全不带知识点名的话取上下文，仍应看到待评价提醒
    ctx = orch.get_context("嗯")

    assert ctx["pending_evaluations"] == [
        {"subject": "physics", "name": "简谐运动", "count": 1}
    ]
