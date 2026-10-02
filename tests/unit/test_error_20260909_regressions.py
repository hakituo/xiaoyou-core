"""2026-09-09 错误记录对应的回归测试。"""

import ast
from collections import deque
import json
from pathlib import Path
import threading
from unittest.mock import AsyncMock, patch

import pytest

from core.character.people.extractor import PeopleProfileExtractor
from core.character.managers.persona_manager import PersonaManager
from core.llm.openai_compat.client import OpenAIClient
from core.services.active_care.core.response_generator import ActiveCareResponseGenerator
from memory.core.runtime_ops import schedule_save
from memory.core.concurrency_optimized import ReadWriteLock
from memory.core.keyword_index import rebuild_keyword_index
from memory.core.lifecycle_ops import safe_save_all


class _SaveManager:
    def __init__(self) -> None:
        self._data_loaded_event = threading.Event()
        self._save_pending_during_load = False
        self._save_queue = deque(maxlen=4)
        self._save_event = threading.Event()
        self.start_count = 0

    def _start_async_save(self) -> None:
        self.start_count += 1


def test_schedule_save_waits_for_background_load() -> None:
    """后台加载完成前不得启动保存线程或序列化半加载字典。"""
    manager = _SaveManager()

    schedule_save(manager)

    assert manager._save_pending_during_load is True
    assert list(manager._save_queue) == []
    assert manager.start_count == 0
    assert manager._save_event.is_set() is False

    manager._data_loaded_event.set()
    schedule_save(manager)

    assert len(manager._save_queue) == 1
    assert manager.start_count == 1
    assert manager._save_event.is_set() is True


class _LockedSaveManager:
    """safe_save_all 的最小替身：保存过程可在 _build_short_term_disk_records 暂停"""

    def __init__(self) -> None:
        self.user_id = "locked_save"
        self.short_term_memory = [
            {"id": "s1", "content": "测试消息", "role": "user", "timestamp": 1.0}
        ]
        self.weighted_memories: dict = {}
        self.topic_weights: dict = {}
        self.emotion_memory_map: dict = {}
        self.last_save_time = 0.0
        self.enable_readable_history_mirror = False
        self._rw_lock = ReadWriteLock()
        self._use_rw_lock = True
        self.lock = threading.RLock()
        self.short_term_dir = Path("short")
        self.sensitive_dir = Path("sensitive")
        self.readable_history_root = Path("readable")
        self.save_started = threading.Event()
        self.save_can_finish = threading.Event()

    def _build_short_term_disk_records(self, messages):
        self.save_started.set()
        self.save_can_finish.wait(timeout=10.0)
        return list(messages)

    def _safe_json_dump(self, data, file_path) -> None:
        return None

    def _save_weighted_data_locked(self) -> None:
        return None

    def _save_important_prompts_locked(self) -> None:
        return None


def test_safe_save_all_holds_read_lock_during_save() -> None:
    """保存期间必须持读锁，否则落盘快照会与写入方并发遍历同一批字典。"""
    manager = _LockedSaveManager()
    writer_state = {"acquired": False}

    def _try_write() -> None:
        with manager._rw_lock.write_lock():
            writer_state["acquired"] = True

    writer = threading.Thread(target=_try_write, daemon=True)
    save_thread = threading.Thread(target=safe_save_all, args=(manager,), daemon=True)
    save_thread.start()
    try:
        assert manager.save_started.wait(timeout=10.0), "保存线程未进入序列化阶段"
        writer.start()
        # 保存线程持有读锁时，写者必须被挡在写锁上（0.5s 足以区分“被挡住”和“立刻拿到”）
        writer.join(timeout=0.5)
        assert writer.is_alive() is True, (
            "保存期间写者仍拿到了写锁，说明 safe_save_all 没有持读锁"
        )
        assert writer_state["acquired"] is False
    finally:
        manager.save_can_finish.set()
        save_thread.join(timeout=10.0)
        writer.join(timeout=10.0)

    assert manager.last_save_time > 0


def test_rebuild_keyword_index_survives_concurrent_insert() -> None:
    """重建关键词索引时并发插入记忆不得抛 dictionary changed size。"""
    weighted_memories: dict = {}
    for i in range(5):
        mid = f"m{i}"
        weighted_memories[mid] = {
            "id": mid,
            "content": f"内容 {i}",
            "topics": ["daily"],
            "keywords": [],
        }

    injected = {"done": False}

    def _extract_keywords(text: str) -> set:
        if not injected["done"]:
            injected["done"] = True
            weighted_memories["injected"] = {
                "id": "injected",
                "content": "遍历中途插入",
                "topics": ["daily"],
                "keywords": [],
            }
        return set()

    rebuild_keyword_index(weighted_memories, _extract_keywords)

    assert injected["done"] is True


def test_executor_forwards_proactive_assignment_context() -> None:
    """不加载可选模型依赖，静态验证执行器门面的参数与转发契约。"""
    executor_path = (
        Path(__file__).resolve().parents[2]
        / "core"
        / "services"
        / "active_care"
        / "core"
        / "executor.py"
    )
    tree = ast.parse(executor_path.read_text(encoding="utf-8"))
    executor_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ActiveCareExecutor"
    )
    method = next(
        node
        for node in executor_class.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "generate_peer_script"
    )
    expected = {
        "proactive_assignment_mode",
        "aveline_state",
        "ling_state",
        "role_states",
    }
    parameters = {
        arg.arg for arg in (*method.args.args, *method.args.kwonlyargs)
    }
    forwarded = {
        keyword.arg
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "generate_peer_script"
        for keyword in node.keywords
        if keyword.arg is not None
    }

    assert expected <= parameters
    assert expected <= forwarded


class _RejectedResponse:
    status = 422
    content = None

    async def text(self) -> str:
        return '{"error":{"message":"input new_sensitive (1026)"}}'


class _ResponseContext:
    async def __aenter__(self):
        return _RejectedResponse()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _RejectedSession:
    def post(self, *_args, **_kwargs):
        return _ResponseContext()


@pytest.mark.asyncio
async def test_stream_422_is_marked_non_retryable() -> None:
    """内容策略 422 必须带不可重试标志供上层立即停止。"""
    client = object.__new__(OpenAIClient)
    client.initialized = True
    client.base_url = "https://example.invalid/v1/chat/completions"
    client._route_vision_if_needed = AsyncMock(return_value=([{"role": "user", "content": "x"}], ""))
    client._build_payload = lambda *_args, **_kwargs: {"model": "MiniMax-M3"}
    client._get_session = AsyncMock(return_value=_RejectedSession())

    chunks = [
        chunk
        async for chunk in client.stream_chat([{"role": "user", "content": "x"}])
    ]

    assert len(chunks) == 1
    assert chunks[0]["error"] == "API returned 422"
    assert chunks[0]["non_retryable"] is True
    assert chunks[0]["details"]["status"] == 422
    assert client._get_session.await_count == 1


class _NonRetryableScheduler:
    def __init__(self) -> None:
        self.calls = 0

    async def submit_llm_task(self, *_args, **_kwargs):
        self.calls += 1
        yield {
            "error": "API returned 422",
            "non_retryable": True,
            "details": {"body": "input new_sensitive (1026)"},
        }


@pytest.mark.asyncio
async def test_people_extractor_does_not_retry_422() -> None:
    """人物档案提取遇到不可重试输入拒绝时只调用一次上游。"""
    scheduler = _NonRetryableScheduler()
    extractor = PeopleProfileExtractor()

    with (
        patch(
            "core.services.scheduler.task.task_scheduler.get_global_scheduler",
            return_value=scheduler,
        ),
        patch(
            "memory.nightly.config.get_memory_distillation_model",
            return_value="cloud:minimax:MiniMax-M3",
        ),
        patch("asyncio.sleep", new=AsyncMock()) as sleep_mock,
    ):
        result = await extractor._call_llm_with_prompt("test")

    assert result == ""
    assert scheduler.calls == 1
    sleep_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_care_upstream_rejection_is_safely_aborted() -> None:
    """Active Care 上游拒绝不得变成可发送正文，也不重复记 backend ERROR。"""
    llm = AsyncMock()
    llm.chat.return_value = "[DEBUG_ERROR] Error: API returned 422: input new_sensitive"
    generator = ActiveCareResponseGenerator(settings=object())

    with (
        patch(
            "core.services.active_care.core.response_generator.get_llm_module",
            return_value=llm,
        ),
        patch(
            "core.services.active_care.core.response_generator.logger.warning"
        ) as warning_mock,
        patch(
            "core.services.active_care.core.response_generator.logger.error"
        ) as error_mock,
    ):
        result = await generator.generate(
            model_user_input="test",
            sys_prompt="test",
            model_hint="cloud:minimax:MiniMax-M3",
        )

    assert result["content"] == ""
    assert result["error"].startswith("[DEBUG_ERROR]")
    warning_mock.assert_called_once()
    error_mock.assert_not_called()


def test_persona_listing_retries_transient_json_decode_error(tmp_path: Path) -> None:
    """人设保存中途的瞬态半文件应在一次重试后恢复。"""
    persona_path = tmp_path / "transient_persona.json"
    persona_path.write_text(
        json.dumps(
            {
                "identity": {"name": "Ling"},
                "meta": {"version": "1.0.0"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manager = object.__new__(PersonaManager)
    manager.configs_dir = str(tmp_path)
    real_open = open
    failed_once = False

    def flaky_open(file, *args, **kwargs):
        nonlocal failed_once
        if Path(file) == persona_path and not failed_once:
            failed_once = True
            raise json.JSONDecodeError("模拟保存中途的半文件", "{", 1)
        return real_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=flaky_open), patch("time.sleep") as sleep_mock:
        personas = manager.list_personas()

    assert failed_once is True
    sleep_mock.assert_called_once_with(0.1)
    assert [(item["filename"], item["name"]) for item in personas] == [
        ("transient_persona.json", "Ling")
    ]
