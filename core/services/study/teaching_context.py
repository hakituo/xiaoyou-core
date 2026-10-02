"""教学上下文构建 —— 把持久化学习状态汇总成 LLM / 工具能用的形式。

从 ``teaching_orchestrator.py`` 抽出的**只读层**：概念解析、六路数据汇总、
ZPD 与建议动作、以及注入 prompt 的紧凑文本块。这里不写任何状态。

放在单独模块的理由：上下文构建涉及多个数据源与限额裁剪，逻辑独立且易变；
编排器只管编排与写入，避免两者混在一个大文件里。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.services.study.concept_state import ConceptState, ConceptStateManager
from core.services.study.learning_event import (
    LearningEventStore,
    LearningEventType,
)
from core.services.study.signal_detector import detect_learning_signal
from core.services.study.zpd import decide_action, judge_zpd
from core.utils.logger import get_logger
from core.utils.time_utils import now_str

logger = get_logger("TeachingContext")

# 已被评价的事件类型。出现这些即代表对应的作答已经处理过，不算「待评价」。
EVALUATED_EVENT_TYPES = frozenset(
    {
        LearningEventType.ANSWER_CORRECT.value,
        LearningEventType.ANSWER_INCORRECT.value,
        LearningEventType.ANSWER_PARTIAL.value,
        LearningEventType.REVIEW_SUCCESS.value,
        LearningEventType.REVIEW_FAILURE.value,
    }
)

# 上下文里最多带多少条，避免 prompt 膨胀
MAX_CONTEXT_CONCEPTS = 6
MAX_DUE_ITEMS = 5
MAX_RECENT_EVENTS = 5
MAX_TARGET_CONCEPTS = 3
MAX_MATCHED_CONCEPTS = 3


class TeachingContextBuilder:
    """汇总学习状态供 LLM / 工具读取。"""

    def __init__(self, concepts: ConceptStateManager, events: LearningEventStore):
        self._concepts = concepts
        self._events = events

    # ------------------------------------------------------------------
    # 概念解析
    # ------------------------------------------------------------------

    def resolve_concepts(
        self, message: str, subject: Optional[str] = None, *, create: bool = False
    ) -> List[ConceptState]:
        """把消息里的候选知识点解析成 ConceptState。

        Args:
            create: 是否允许创建不存在的知识点。**读工具必须为 False**——
                否则「讲讲胡克定律」会凭空建出一个空概念的「胡克定律」，
                而模型实际讲解时可能用「F = -kx」，学习证据被劈成两份。
                写入路径（record_teaching 等）才需要创建。

        抽取策略：
        1. 先用 ``signal_detector`` 抽取显式知识点（引号、"讲讲X"、"X是什么"、公式）；
        2. 抽不到时，用消息去**匹配已存在的知识点名**——用户往往只回一句
           「简谐运动」，这时应命中已记录的知识点，而不是新建一个同名副本。
        """
        signal = detect_learning_signal(message)
        subj = subject or signal.subject
        names = list(signal.concepts)
        if not names and message:
            names = self.match_existing_concept_names(message, subj)
        if not subj or not names:
            return []

        resolved: List[ConceptState] = []
        for name in names:
            state = self._concepts.get_by_name(subj, name)
            if state is None:
                state = self._concepts._find_by_loose_name(subj, name)
            if state is None and create:
                state = self._concepts.get_or_create(subj, name)
            if state is not None:
                resolved.append(state)
        return resolved

    def match_existing_concept_names(
        self, message: str, subject: Optional[str]
    ) -> List[str]:
        """用消息匹配已记录的知识点名（精确或包含）。"""
        text = str(message or "").strip()
        if not text:
            return []
        candidates = self._concepts.all_concepts()
        if subject:
            key = ConceptState.normalize_subject(subject)
            candidates = [c for c in candidates if c.subject == key]
        # 名称更长的优先，避免「导数」抢走「偏导数」
        candidates.sort(key=lambda c: len(c.name), reverse=True)
        matched: List[str] = []
        for concept in candidates:
            if concept.name and (concept.name == text or concept.name in text):
                matched.append(concept.name)
                if len(matched) >= MAX_MATCHED_CONCEPTS:
                    break
        return matched

    def latest_concept(self, subject: Optional[str] = None) -> Optional[ConceptState]:
        """取最近接触过的知识点（用于承接「我没听懂」这类无主语消息）。

        **只认有真实学习证据的知识点**（``is_confirmed_state``）。历史数据里
        混着被动观察留下的空壳（「哼哼猜猜看」那种），它们从没被真正教过，
        却被算成「最近讨论过的知识点」——一旦被 fallback 命中，就会成为新证据的
        载体，把假阳性继续传下去。排除它们既是纠错，也是断链。

        候选（还没通过准入的）不参与排序：它们不是知识点，只是遥测。
        """
        items = [c for c in self._concepts.all_concepts() if c.is_confirmed_state]
        if subject:
            key = ConceptState.normalize_subject(subject)
            items = [c for c in items if c.subject == key]
        if not items:
            return None
        items.sort(
            key=lambda c: max(
                c.last_tested_at or "", c.last_taught_at or "", c.first_seen_at or ""
            ),
            reverse=True,
        )
        return items[0]

    # ------------------------------------------------------------------
    # 上下文汇总
    # ------------------------------------------------------------------

    def get_context(
        self, message: Optional[str] = None, subject: Optional[str] = None
    ) -> Dict[str, Any]:
        """汇总持久化学习状态，供教学前读取。

        **recent_events 只喂已确认的学习事实，且必须有明确的知识点指向。**

        为什么解析不到知识点时宁可回空、也不给「最近事件」：无指向的历史事件
        一旦进 prompt，被动观察捞到的假阳性就会被 LLM 当成学习上下文，进而
        触发 ``study_record_*`` 把它提升成正式事实——晋升门被绕过。
        所以这里的规则是「解析到 X 才谈 X」：没有 X，就没有上下文可谈。
        """
        signal = detect_learning_signal(message or "")
        subj = subject or signal.subject

        target_concepts: List[ConceptState] = []
        if message:
            target_concepts = self.resolve_concepts(message, subj)[:MAX_TARGET_CONCEPTS]

        due_concepts = self._concepts.list_due()
        due_count = len(due_concepts)

        zpd: Dict[str, Any] = {}
        action: Dict[str, Any] = {}
        if target_concepts:
            zpd = judge_zpd(target_concepts[0], self._concepts)
            action = decide_action(
                signal.intent, zpd, target_concepts[0], due_count=due_count
            )

        # 只有解析到目标知识点时才读历史事件，且只读该知识点的 confirmed 事件。
        recent_events = (
            self._events.read(
                concept_id=target_concepts[0].concept_id,
                days=30,
                limit=MAX_RECENT_EVENTS,
            )
            if target_concepts
            else []
        )

        return {
            "date": now_str("%Y-%m-%d"),
            "intent": signal.intent.value,
            "subject": subj,
            "target_concepts": [c.model_dump(mode="json") for c in target_concepts],
            "weak_concepts": [
                c.model_dump(mode="json")
                for c in self._concepts.list_weak(limit=MAX_CONTEXT_CONCEPTS)
            ],
            "due_reviews": [
                {
                    "concept_id": c.concept_id,
                    "subject": c.subject,
                    "name": c.name,
                    "status": c.status.value,
                    "mastery": c.mastery,
                    "next_review_at": c.next_review_at,
                }
                for c in due_concepts[:MAX_DUE_ITEMS]
            ],
            "due_count": due_count,
            "pending_evaluations": self._pending_evaluations(),
            "recent_events": [e.model_dump(mode="json") for e in recent_events],
            "zpd": zpd,
            "recommended_action": action,
            "student": self._student_snapshot(),
            "today": self._today_snapshot(),
            "resources": self._resources_for(target_concepts),
        }

    def _pending_evaluations(self) -> List[Dict[str, Any]]:
        """全局找出「疑似作答但还没被评价」的知识点。

        **必须全局扫描，不能只看当前消息解析出的概念**：用户作答时通常不写
        知识点名（「答案是朝左」「我选 B」），按当前消息解析会得到空集合，
        导致提醒永远不出现——这正是待评价机制要兜底的场景，不能反被它卡死。

        判定方式：按时间顺序扫近期事件，遇到评价事件就把该概念的计数清零，
        遇到待评价痕迹就累加；最终计数 > 0 的说明评价还没补上。

        **只看 ``confirmed``**：待评价痕迹由被动观察写入，若把 observed 也算进来，
        遥测就换了条路径回到 LLM 眼前（第一版结论：observed pending 不进 prompt）。
        真需要提醒的场景——LLM 自己提过问然后忘了评——会有 ``question_asked``
        的 confirmed 痕迹兜底。
        """
        try:
            events = self._events.read(days=7, limit=500)
        except Exception as e:  # noqa: BLE001
            logger.debug("读取学习事件失败，跳过待评价统计：%s", e)
            return []
        if not events:
            return []

        counters: Dict[str, int] = {}
        meta: Dict[str, Dict[str, str]] = {}
        for event in events:
            cid = event.concept_id
            if not cid:
                continue
            meta.setdefault(cid, {"subject": event.subject, "name": event.concept_name})
            counters.setdefault(cid, 0)
            if event.event_type.value in EVALUATED_EVENT_TYPES:
                counters[cid] = 0
            elif event.event_type == LearningEventType.ANSWER_PENDING_EVALUATION:
                counters[cid] += 1

        out = [
            {
                "subject": meta[cid]["subject"],
                "name": meta[cid]["name"],
                "count": count,
            }
            for cid, count in counters.items()
            if count > 0 and cid in meta
        ]
        out.sort(key=lambda item: -item["count"])
        return out

    def get_context_block(self, message: Optional[str] = None) -> str:
        """把学习状态压成紧凑文本，用于 prompt 注入（约 10 行以内）。"""
        try:
            ctx = self.get_context(message)
        except Exception as e:  # noqa: BLE001
            logger.warning("构建学习状态上下文失败：%s", e)
            return ""

        lines: List[str] = []

        for c in (ctx.get("target_concepts") or [])[:2]:
            lines.append(
                f"· 当前知识点 {c['name']}（{c['status']}，掌握度 {c['mastery']:.2f}，"
                f"独立答对 {c['independent_success_streak']} 次）"
            )

        weak = ctx.get("weak_concepts") or []
        if weak:
            preview = "、".join(f"{c['name']}({c['mastery']:.2f})" for c in weak[:3])
            lines.append(f"· 已知薄弱：{preview}")

        due = ctx.get("due_reviews") or []
        if due:
            preview = "、".join(f"{d['subject']}·{d['name']}" for d in due[:3])
            lines.append(f"· 到期复习 {ctx.get('due_count', 0)} 项：{preview}")

        events = ctx.get("recent_events") or []
        if events:
            # 只在解析出目标知识点时才有 events（见 get_context），
            # 这里的 event_type 必定来自已确认的学习事实。
            last = events[-1]
            lines.append(
                f"· 最近事件：{last['event_type']} @ {last['concept_name'] or last['subject']}"
            )

        student = ctx.get("student") or {}
        if student.get("current_streak"):
            lines.append(f"· 连续学习 {student['current_streak']} 天")

        resources = ctx.get("resources") or []
        if resources:
            parts = []
            for item in resources[:2]:
                title = str(item.get("title") or "")
                location = str(item.get("location") or "")
                excerpt = str(item.get("excerpt") or "")
                if not (title or location):
                    continue
                text = f"{title}（{location}）" if location else title
                if excerpt:
                    text += f"：{excerpt}"
                parts.append(text)
            if parts:
                lines.append(
                    "· 本地笔记可参考：" + "；".join(parts) + "；需要全文时用学习文件工具读取"
                )

        pending = ctx.get("pending_evaluations") or []
        if pending:
            total = sum(int(item.get("count") or 0) for item in pending)
            preview = "、".join(str(item.get("name", "")) for item in pending[:2])
            lines.append(
                f"· 有 {total} 次作答尚未评价（{preview}）；"
                "若上一轮你确实提过问，请调用 study_record_answer 记录评价结果"
            )

        action = ctx.get("recommended_action") or {}
        if action.get("action"):
            lines.append(f"· 建议动作：{action['action']}（{action.get('rationale', '')}）")

        if not lines:
            return ""

        header = "【学习状态（来自持久化学习记录，不是猜测）】"
        footer = (
            "要求：讲解前先利用上面的历史状态，不要重复讲已掌握的内容；"
            "检验环节先让用户独立回答，再逐步给提示；"
            "不要因为用户说「懂了」就直接认为已掌握。"
        )
        return "\n".join([header, *lines, footer])

    # ------------------------------------------------------------------
    # 内部：轻量快照
    # ------------------------------------------------------------------

    @staticmethod
    def _student_snapshot() -> Dict[str, Any]:
        try:
            from core.services.study.student_state import get_student_state_manager

            info = get_student_state_manager().get_streak_info()
            return {
                "current_streak": info.get("current_streak", 0),
                "longest_streak": info.get("longest_streak", 0),
            }
        except Exception as e:  # noqa: BLE001
            logger.debug("读取学生 streak 快照失败，本次上下文省略该字段：%s", e)
            return {}

    @staticmethod
    def _today_snapshot() -> Dict[str, Any]:
        try:
            from core.services.study.daily_tracker import get_daily_tracker

            stats = get_daily_tracker().get_summary_stats()
            return {
                "total_study_minutes": stats.get("total_study_minutes", 0),
                "knowledge_points_new": stats.get("knowledge_points_new", 0),
                "struggles_count": stats.get("struggles_count", 0),
            }
        except Exception as e:  # noqa: BLE001
            logger.debug("读取今日学习快照失败，本次上下文省略该字段：%s", e)
            return {}

    @staticmethod
    def _resources_for(concepts: List[ConceptState]) -> List[Dict[str, Any]]:
        """汇总该知识点可用的可信资料。

        两路来源：用户显式登记的 ``ResourceRegistry``，以及笔记库里按知识点
        检索到的笔记。只返回标题与路径，全文由上层按需读取。
        """
        if not concepts:
            return []
        target = concepts[0]
        out: List[Dict[str, Any]] = []

        # RAG 片段检索：用「科目 + 知识点 + 前置知识」构造 query，
        # 而不是拿用户原话去搜——「为什么那个负号在那里」这种问法搜不到东西。
        try:
            from core.services.study.rag import RetrievalQuery, StudyLibrary

            query = RetrievalQuery(
                subject=target.subject,
                concepts=[c.name for c in concepts[:2]],
                prerequisites=list(target.prerequisites or []),
            )
            out.extend(StudyLibrary().as_context_items(query, top_k=2))
        except Exception as e:  # noqa: BLE001
            logger.debug("RAG 检索失败（不影响主流程）: %s", e)

        try:
            from core.services.study.resources import get_resource_registry

            for ref in get_resource_registry().list_for_concept(target.concept_id)[:2]:
                item = ref.model_dump(mode="json")
                item["source"] = "registry"
                out.append(item)
        except Exception as e:  # noqa: BLE001
            logger.debug("读取已登记可信资源失败：%s", e)

        try:
            from core.services.study.study_library import get_study_library

            for hit in get_study_library().search(target.subject, target.name, limit=3):
                out.append({**hit.to_dict(), "source": "library"})
        except Exception as e:  # noqa: BLE001
            logger.debug("检索笔记库失败：%s", e)

        return out[:4]
