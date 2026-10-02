"""教学闭环端到端验证脚本。

用法（项目规则：用 venv_core / venv_cpu 运行，不要用全局环境）：

    venv_core\\Scripts\\python.exe tests/scripts/study/verify_teaching_closed_loop.py

它模拟一次**真实的普通聊天学习对话**，逐段验证需求里要求跑通的那条链：

    用户提出学习问题
    -> 教学
    -> 检索已有学习状态
    -> 用户回答 / 反馈
    -> 评价
    -> LearningEvent
    -> ConceptState 更新
    -> Weakness / review 更新
    -> 下一次对话能读取并利用这个状态

全程在临时目录里跑，不会碰用户真实的 D:\\AI\\Study。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class Report:
    """极简验证报告器。"""

    def __init__(self) -> None:
        self.checks: list[tuple[bool, str]] = []

    def check(self, ok: bool, label: str) -> None:
        self.checks.append((bool(ok), label))
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")

    def summary(self) -> int:
        failed = [label for ok, label in self.checks if not ok]
        print("\n" + "=" * 64)
        print(f"总计 {len(self.checks)} 项，通过 {len(self.checks) - len(failed)} 项")
        if failed:
            print("失败项：")
            for label in failed:
                print(f"  - {label}")
            return 1
        print("教学闭环验证通过 ✅")
        return 0


def _isolate(tmp_root: Path) -> None:
    """把学习系统状态根目录指向临时目录，并重置全部单例。"""
    from core.services.study import paths

    paths.get_study_root = lambda: tmp_root  # type: ignore[assignment]

    from core.services.study import (
        concept_state,
        daily_tracker,
        learning_event,
        resources,
        student_state,
        teaching_orchestrator,
        weakness_tracker,
    )

    concept_state.ConceptStateManager._instance = None
    learning_event.LearningEventStore._instance = None
    resources.ResourceRegistry._instance = None
    weakness_tracker.WeaknessTracker._instance = None
    student_state.StudentStateManager._instance = None
    teaching_orchestrator.TeachingOrchestrator._instance = None
    daily_tracker.DailyTracker._instance = None


def main() -> int:
    report = Report()
    tmp_root = Path(tempfile.mkdtemp(prefix="study_loop_")) / "study"
    (tmp_root / ".state").mkdir(parents=True, exist_ok=True)
    _isolate(tmp_root)

    from core.agents.chat_agent_components.study import observe_learning_message
    from core.services.study.concept_state import get_concept_state_manager
    from core.services.study.learning_event import LearningEventType, get_learning_event_store
    from core.services.study.teaching_orchestrator import get_teaching_orchestrator
    from core.services.study.weakness_tracker import get_weakness_tracker
    from core.tools.registry import ToolRegistry, register_all_tools
    from core.tools.tool_policy import select_role_tools

    registry = ToolRegistry()
    register_all_tools(registry)
    orch = get_teaching_orchestrator()
    events = get_learning_event_store()

    # ---------------- 第 1 轮：普通聊天提出学习问题 ----------------
    print("\n[1] 普通聊天：用户问「为什么 F = -kx 里面有负号？」")
    question = "为什么 F = -kx 里面有负号？"

    from core.services.study.mode_detector import is_study_mode

    report.check(is_study_mode(question), "普通聊天消息被识别为学习场景")
    tools = select_role_tools(question, mode="study")
    report.check(
        "study_get_context" in tools and "study_record_answer" in tools,
        "教学工具进入本轮可用工具集",
    )

    observed = observe_learning_message(question)
    report.check(observed.get("status") == "recorded", "自动记录用户提问（question_asked）")

    # ---------------- 第 2 轮：教学 + 检索已有状态 ----------------
    print("\n[2] 教学：记录讲解，并读取已有学习状态")
    taught = orch.record_teaching("physics", "F = -kx", action="taught")
    report.check(taught["status_after"] == "learning", "讲解后状态为 learning（不是 mastered）")

    ctx = orch.get_context("F = -kx 是什么")
    block = orch.get_context_block("F = -kx 是什么")
    report.check("F = -kx" in block, "LLM 上下文能读到刚讲过的知识点")
    report.check(bool(ctx["recommended_action"].get("action")), "返回了下一步教学动作建议")

    # ---------------- 第 3 轮：用户回答（答错）----------------
    print("\n[3] 用户作答：答错 -> 评价 -> 状态更新")
    answer = orch.record_answer(
        "physics",
        "F = -kx",
        {
            "correctness": 0.2,
            "independent": True,
            "used_hint": False,
            "misconception": "把负号理解成数值大小而不是方向",
        },
        user_answer="因为 k 是负数",
    )
    report.check(answer["status"] == "success", "评价载荷被接受")
    report.check(answer["verdict"] == "incorrect", "判定为答错")
    report.check(answer["status_after"] == "weak", "ConceptState 降级为 weak")

    # ---------------- 第 4 轮：LearningEvent 落库 ----------------
    print("\n[4] 学习证据：LearningEvent 落库")
    concept = get_concept_state_manager().get_by_name("physics", "F = -kx")
    concept_events = events.read(concept_id=concept.concept_id, days=1, limit=50)
    types = [e.event_type for e in concept_events]
    report.check(LearningEventType.QUESTION_ASKED in types, "记录了 question_asked")
    report.check(LearningEventType.TAUGHT in types, "记录了 taught")
    report.check(LearningEventType.ANSWER_INCORRECT in types, "记录了 answer_incorrect")
    report.check(
        any(e.misconception for e in concept_events if e.misconception),
        "记录了具体误区（misconception）",
    )

    # ---------------- 第 5 轮：Weakness / review 更新 ----------------
    print("\n[5] 薄弱与复习：weak 知识点进入复习调度")
    tracker = get_weakness_tracker()
    projected = next(
        (i for i in tracker._get_items() if i.topic == "F = -kx"), None
    )
    report.check(projected is not None, "薄弱视图出现该知识点（单向投影）")
    report.check(
        projected is not None and projected.confidence == round(concept.mastery * 10, 2),
        "薄弱视图掌握度与 ConceptState 一致（不会两套状态打架）",
    )

    # 把复习日期拨到今天就到期，验证复习路径
    from core.utils.time_utils import now_str

    concept.next_review_at = now_str("%Y-%m-%d")
    get_concept_state_manager().save()
    orch.project(concept)
    due = orch.get_review_items(limit=10)
    report.check(
        any(i["name"] == "F = -kx" for i in due["items"]), "到期复习清单包含该知识点"
    )

    # ---------------- 第 6 轮：用户自述没听懂 ----------------
    print("\n[6] 查漏补缺：用户说「我还是没听懂」")
    confusion = observe_learning_message("我还是没听懂")
    report.check(confusion.get("intent") == "confusion", "识别为自述没听懂")
    report.check(
        confusion.get("concepts") == ["F = -kx"], "回落到最近讨论的知识点"
    )

    # ---------------- 第 7 轮：提示辅助成功 != 独立成功 ----------------
    print("\n[7] 提示辅助成功不计入独立掌握")
    hinted = orch.record_answer(
        "physics",
        "F = -kx",
        {"correctness": 0.95, "independent": False, "used_hint": True},
    )
    hinted_state = get_concept_state_manager().get_by_name("physics", "F = -kx")
    report.check(hinted["used_hint"] is True, "标记为使用提示")
    report.check(
        hinted_state.independent_success_streak == 0,
        "提示成功不增加独立成功连击",
    )

    # ---------------- 第 8 轮：连续独立答对 -> mastered ----------------
    print("\n[8] 连续独立答对 -> 掌握 -> 退出薄弱列表")
    for _ in range(4):
        final = orch.record_answer(
            "physics",
            "F = -kx",
            {"correctness": 0.95, "independent": True},
            is_review=True,
        )
    report.check(final["status_after"] == "mastered", "4 次独立答对后进入 mastered")
    report.check(
        all(i.topic != "F = -kx" for i in tracker._get_items()),
        "掌握后不再出现在薄弱列表",
    )

    # ---------------- 第 9 轮：下一次对话读取并利用状态 ----------------
    print("\n[9] 下一次对话：读取并利用持久化状态")
    # 模拟进程重启：清空单例，重新从磁盘加载
    _isolate(tmp_root)
    from core.services.study.teaching_orchestrator import (
        get_teaching_orchestrator as get_orch_again,
    )

    fresh_orch = get_orch_again()
    next_ctx = fresh_orch.get_context("F = -kx")
    reloaded = get_concept_state_manager().get_by_name("physics", "F = -kx")
    report.check(reloaded is not None, "重启后仍能读到该知识点")
    report.check(reloaded is not None and reloaded.status.value == "mastered", "状态被正确持久化")
    report.check(
        any(c["name"] == "F = -kx" for c in next_ctx["target_concepts"]),
        "下一轮能定位到该知识点",
    )
    report.check(
        next_ctx["zpd"]["level"] == "mastered",
        "下一轮 ZPD 判定为已掌握（会改用检索检验而非重复讲解）",
    )
    report.check(
        next_ctx["recommended_action"]["action"] == "retrieval_test",
        "下一轮建议动作为 retrieval_test",
    )

    # ---------------- 第 10 轮：状态文件与词库隔离 ----------------
    print("\n[10] 兼容性：状态文件隔离，不触碰背单词主链")
    state_files = sorted(p.name for p in (tmp_root / ".state").iterdir())
    report.check("concepts.json" in state_files, "生成 concepts.json")
    report.check("learning_events" in state_files, "生成 learning_events 目录")
    report.check(
        not any("vocab" in name for name in state_files),
        "教学状态目录内没有词库进度文件",
    )

    print("\n状态文件：")
    for name in state_files:
        print(f"  - {name}")

    snapshot = get_concept_state_manager().to_dict()
    print("\nConceptState 快照：")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2)[:1200])

    return report.summary()


if __name__ == "__main__":
    raise SystemExit(main())
