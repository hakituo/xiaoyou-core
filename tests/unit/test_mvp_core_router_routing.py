import os
import sys
import asyncio


def _add_mvp_core_to_path() -> None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    legacy_root = os.path.join(repo_root, "legacy")
    mvp_root = os.path.join(legacy_root, "mvp_core")

    if legacy_root not in sys.path:
        sys.path.insert(0, legacy_root)
    if mvp_root not in sys.path:
        sys.path.insert(0, mvp_root)


def _reset_mvp_container() -> None:
    from shared.di import Container

    Container._instances.clear()
    Container._factories.clear()


class _DummyLLM:
    async def generate(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        raise RuntimeError("不应走到 LLMInterface.generate")

    async def stream_generate(self, prompt: str, system_prompt: str = None, **kwargs):
        raise RuntimeError("不应走到 LLMInterface.stream_generate")


class _FakeScheduler:
    def __init__(self):
        self.called = False
        self.last_prompt = None
        self.last_system_prompt = None

    async def submit_llm_task(self, prompt: str, **kwargs):
        self.called = True
        self.last_prompt = prompt
        self.last_system_prompt = kwargs.get("system_prompt")
        yield "OK"


def test_mvp_chatservice_routes_llm_via_scheduler():
    _add_mvp_core_to_path()
    _reset_mvp_container()

    from shared.di import container
    from domain.interfaces.base_interfaces import LLMInterface, MemoryInterface
    from data.repositories.memory_repository import InMemoryMemoryRepository
    from domain.entities.character import CharacterProfile
    from domain.services.chat_service import ChatService
    from mvp_core.services.task_scheduler import GlobalTaskScheduler

    scheduler = _FakeScheduler()
    container.register(GlobalTaskScheduler, scheduler)
    container.register(LLMInterface, _DummyLLM())
    container.register(MemoryInterface, InMemoryMemoryRepository())

    character = CharacterProfile(
        name="Aveline",
        system_prompt="You are Aveline",
        sensory_triggers=[],
        behavior_chains=[],
    )
    svc = ChatService(character)

    async def _run():
        chunks = []
        async for item in svc.process_message("hello"):
            if item.get("type") == "token":
                chunks.append(item.get("data"))
        return chunks

    tokens = asyncio.run(_run())
    assert "".join(tokens) == "OK"
    assert scheduler.called is True
    assert scheduler.last_prompt == "user: hello"
    assert isinstance(scheduler.last_system_prompt, str)
    assert "Current State" in scheduler.last_system_prompt


def test_mvp_scheduler_fallback_streams_tokens():
    _add_mvp_core_to_path()

    from mvp_core.services.task_scheduler import GlobalTaskScheduler

    class _Adapter:
        async def generate(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
            return "FULL"

        async def stream_generate(self, prompt: str, system_prompt: str = None, **kwargs):
            yield "A"
            yield "B"

    scheduler = GlobalTaskScheduler()

    async def _fake_get_adapter():
        return _Adapter()

    scheduler._get_fallback_llm_adapter = _fake_get_adapter

    import types

    fake_mod = types.SimpleNamespace(cpp_scheduler_engine=types.SimpleNamespace(enabled=False))
    sys.modules["mvp_core.services.cpp_scheduler_engine"] = fake_mod

    async def _run():
        out = []
        async for token in scheduler.submit_llm_task("hi", system_prompt="sys"):
            out.append(token)
        return "".join(out)

    assert asyncio.run(_run()) == "AB"


def test_mvp_scheduler_image_backpressure_queue_full():
    _add_mvp_core_to_path()

    from mvp_core.services.task_scheduler import GlobalTaskScheduler

    scheduler = GlobalTaskScheduler()
    scheduler._read_image_backpressure_settings = lambda: (1, 1)

    async def _fake_schedule(prompt: str, **kwargs) -> str:
        await asyncio.sleep(0.2)
        return "out.ppm"

    scheduler.schedule_image_generation = _fake_schedule

    async def _run():
        await scheduler.ensure_image_workers_started()

        jid1, s1, r1 = await scheduler.try_enqueue_image_generation("p1")
        jid2, s2, r2 = await scheduler.try_enqueue_image_generation("p2")

        full = False
        try:
            await scheduler.try_enqueue_image_generation("p3")
        except Exception:
            full = True

        await s1
        await s2

        assert await r1 == "out.ppm"
        assert await r2 == "out.ppm"
        assert full is True
        assert jid1.startswith("imgjob_")
        assert jid2.startswith("imgjob_")

    asyncio.run(_run())
