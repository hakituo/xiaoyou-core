"""验证 NightlyTaskRunner 与 PeopleProfileExtractor 的职责拆分。"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def _line_count(relative_path: str) -> int:
    return len((PROJECT_ROOT / relative_path).read_text(encoding="utf-8").splitlines())


def verify_facade_sizes() -> None:
    """门面文件不得再次膨胀成业务实现容器。"""
    task_runner_lines = _line_count("memory/nightly/task_runner.py")
    extractor_lines = _line_count("core/character/people/extractor.py")
    _assert(task_runner_lines <= 300, f"NightlyTaskRunner 保持薄门面（{task_runner_lines} 行）")
    _assert(extractor_lines <= 350, f"PeopleProfileExtractor 保持薄门面（{extractor_lines} 行）")


def verify_nightly_boundaries() -> None:
    """Nightly 编排、执行和文本转换分别有明确模块。"""
    from memory.nightly.distillation_codec import DistillationCodec
    from memory.nightly.distillation_service import MemoryDistillationService
    from memory.nightly.global_tasks import NightlyGlobalTaskService
    from memory.nightly.task_runner import NightlyTaskRunner

    runner_source = inspect.getsource(NightlyTaskRunner)
    _assert("get_journal_service" not in runner_source, "TaskRunner 不再实现日记/计划业务")
    _assert("submit_llm_task" not in runner_source, "TaskRunner 不再实现蒸馏请求循环")
    _assert(
        hasattr(MemoryDistillationService, "distill_memories_async"),
        "蒸馏执行由 MemoryDistillationService 承担",
    )
    _assert(
        hasattr(DistillationCodec, "parse_profile_signals"),
        "Prompt/解析由 DistillationCodec 承担",
    )
    _assert(hasattr(NightlyGlobalTaskService, "run"), "全局任务由独立服务编排")


def verify_people_profile_boundaries() -> None:
    """人物门面不再直接读 JSONL、解析 JSON 或持久化事实。"""
    from core.character.people.conversation_source import PeopleConversationSource
    from core.character.people.external_profile_service import (
        ExternalPeopleProfileService,
    )
    from core.character.people.extractor import PeopleProfileExtractor
    from core.character.people.role_update_service import RoleProfileUpdateService
    from core.character.people.signal_gate import PeopleProfileSignalGate

    extractor_source = inspect.getsource(PeopleProfileExtractor)
    _assert("rglob(" not in extractor_source, "Extractor 不再扫描 chat_history 文件")
    _assert("json.loads" not in extractor_source, "Extractor 不再实现 JSON 解析")
    _assert("KnownFact(" not in extractor_source, "Extractor 不再持久化档案事实")
    _assert(hasattr(PeopleConversationSource, "load_new_messages"), "对话读取职责独立")
    _assert(hasattr(PeopleProfileSignalGate, "select_batches"), "人物候选门控职责独立")
    _assert(hasattr(ExternalPeopleProfileService, "extract_batches"), "外部人物提取职责独立")
    _assert(hasattr(RoleProfileUpdateService, "extract_updates"), "角色演化提取职责独立")


def verify_compatibility_facades() -> None:
    """旧调用方使用的解析与 Prompt 方法继续可调用。"""
    from core.character.people.extractor import PeopleProfileExtractor
    from memory.nightly.task_runner import NightlyTaskRunner

    summary, keywords = NightlyTaskRunner.parse_distillation_response(
        "【梗概】：兼容摘要\n【关键词】：兼容,测试"
    )
    _assert(summary == "兼容摘要" and keywords == ["兼容", "测试"], "蒸馏兼容门面可用")
    people = PeopleProfileExtractor()._parse_response('{"people": []}')
    _assert(people == [], "人物 JSON 解析兼容门面可用")


def main() -> int:
    verify_facade_sizes()
    verify_nightly_boundaries()
    verify_people_profile_boundaries()
    verify_compatibility_facades()
    print("\n[PASS] Nightly 与人物档案职责拆分验证全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
