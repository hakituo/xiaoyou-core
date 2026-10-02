from core.services.study.catalog import build_tools_metadata, build_subject_profiles
from core.services.study.persona import StudyPersonaProfile
from core.services.study.subject_analyzer import StudySubjectAnalyzer
from core.services.study.summary_builder import StudySummaryBuilder
from core.services.study.mode_detector import is_study_mode, classify_subject, SUBJECT_KEYWORDS
from core.services.study.session import StudySession
from core.services.study.dispatch import ToolDispatcher
from core.services.study.summary_generator import StudySummaryGenerator
from core.services.study.student_state import StudentStateManager, get_student_state_manager
from core.services.study.daily_tracker import DailyTracker, get_daily_tracker
from core.services.study.weakness_tracker import WeaknessTracker, get_weakness_tracker
from core.services.study.tutor_engine import TutorEngine, get_tutor_engine

# 通用教学系统（ConceptState / LearningEvent / 教学编排）
from core.services.study.concept_rules import ConceptStatus
from core.services.study.concept_state import (
    ConceptState,
    ConceptStateManager,
    get_concept_state_manager,
)
from core.services.study.learning_event import (
    LearningEvent,
    LearningEventStore,
    LearningEventType,
    get_learning_event_store,
)
from core.services.study.evaluation import (
    EvaluationResult,
    EvaluationService,
    get_evaluation_service,
)
from core.services.study.signal_detector import (
    LearningIntent,
    LearningSignal,
    detect_learning_signal,
)
from core.services.study.teaching_orchestrator import (
    TeachingOrchestrator,
    get_teaching_orchestrator,
)
from core.services.study.teaching_context import TeachingContextBuilder
from core.services.study.teaching_writer import TeachingWriter
from core.services.study.zpd import (
    ACTION_ASK_QUESTION,
    ACTION_EXPLAIN,
    ACTION_RETRIEVAL_TEST,
    ZPD_MASTERED,
    ZPD_PREREQUISITE_GAP,
    decide_action,
    judge_zpd,
)
from core.services.study.resources import (
    ResourceRef,
    ResourceRegistry,
    get_resource_registry,
)
from core.services.study.study_library import (
    LibraryHit,
    StudyLibraryIndex,
    get_study_library,
)

__all__ = [
    "build_tools_metadata",
    "build_subject_profiles",
    "StudyPersonaProfile",
    "StudySubjectAnalyzer",
    "StudySummaryBuilder",
    "is_study_mode",
    "classify_subject",
    "SUBJECT_KEYWORDS",
    "StudySession",
    "ToolDispatcher",
    "StudySummaryGenerator",
    "StudentStateManager",
    "get_student_state_manager",
    "DailyTracker",
    "get_daily_tracker",
    "WeaknessTracker",
    "get_weakness_tracker",
    "TutorEngine",
    "get_tutor_engine",
    # 通用教学系统
    "ConceptState",
    "ConceptStateManager",
    "ConceptStatus",
    "get_concept_state_manager",
    "LearningEvent",
    "LearningEventStore",
    "LearningEventType",
    "get_learning_event_store",
    "EvaluationResult",
    "EvaluationService",
    "get_evaluation_service",
    "LearningIntent",
    "LearningSignal",
    "detect_learning_signal",
    "TeachingOrchestrator",
    "get_teaching_orchestrator",
    "TeachingContextBuilder",
    "TeachingWriter",
    "ZPD_MASTERED",
    "ZPD_PREREQUISITE_GAP",
    "ACTION_EXPLAIN",
    "ACTION_ASK_QUESTION",
    "ACTION_RETRIEVAL_TEST",
    "judge_zpd",
    "decide_action",
    "ResourceRef",
    "ResourceRegistry",
    "get_resource_registry",
    "LibraryHit",
    "StudyLibraryIndex",
    "get_study_library",
]
