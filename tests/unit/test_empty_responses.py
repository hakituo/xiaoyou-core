import sys
import os
import asyncio
import json
from typing import Dict, Any

import requests
import pytest

# 将项目根目录加入 sys.path，便于直接导入核心模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.services.aveline.service import AvelineService  # noqa: E402
from core.agents.chat_agent import ChatAgent, AgentConfig  # noqa: E402

BASE_URL = "http://localhost:8000"


def _print_result(name: str, success: bool, detail: str) -> None:
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status} - {name}")
    print(f"   {detail}")
    print("-" * 60)


async def _direct_service_test(model_hint: str, description: str) -> None:
    """
    直接调用 AvelineService.generate_response，绕过 HTTP，看最终文本是否仍然为空
    """
    service = AvelineService()

    # 使用比较长的一段话，模拟大上下文 / 学习模式场景
    user_input = (
        "这是一个用于测试空回复问题的长文本输入。" * 50
        + "请你随便回答一点内容，哪怕是一句话也可以。"
    )
    conv_id = f"test_conv_{model_hint.replace('/', '_')}"

    reply, meta = await service.generate_response(
        user_input=user_input,
        conversation_id=conv_id,
        model_hint=model_hint,
        save_history=False,
    )

    bad_snippets = [
        "无回复内容",
        "本地模型出错",
        "exceed context window",
        "context window of",
    ]
    if (
        not reply
        or reply.strip() == ""
        or any(snippet in reply for snippet in bad_snippets)
    ):
        _print_result(
            f"Direct Service Test ({description})",
            False,
            f"回复为空或包含无回复内容提示: {repr(reply)} | meta={meta}",
        )
        raise SystemExit(1)
    else:
        _print_result(
            f"Direct Service Test ({description})",
            True,
            f"回复前50字符: {reply[:50]}...",
        )


def _http_test_message(model: str, description: str) -> None:
    """
    通过 /api/v1/message 走一遍完整 HTTP 流程，检查最终 response 字段
    """
    endpoint = f"{BASE_URL}/api/v1/message"
    params: Dict[str, Any] = {}
    if model:
        params["model"] = model

    # 用一个相对短一点的输入，主要检查“无回复内容”兜底是否还会出现
    payload = {
        "content": f"这是一次 {description} 的回归测试调用，请正常回复任意一句话。",
        "conversation_id": f"test_http_{description.replace(' ', '_')}",
    }

    resp = requests.post(endpoint, params=params, json=payload, timeout=60)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}

    if resp.status_code != 200:
        _print_result(
            f"HTTP /api/v1/message ({description})",
            False,
            f"HTTP {resp.status_code}: {data}",
        )
        raise SystemExit(1)

    reply = data.get("reply") or data.get("response") or ""
    bad_snippets = [
        "无回复内容",
        "本地模型出错",
        "exceed context window",
        "context window of",
    ]
    if not reply or any(snippet in reply for snippet in bad_snippets):
        _print_result(
            f"HTTP /api/v1/message ({description})",
            False,
            f"接口返回内容异常: {json.dumps(data, ensure_ascii=False)[:200]}...",
        )
        raise SystemExit(1)

    _print_result(
        f"HTTP /api/v1/message ({description})",
        True,
        f"reply 前50字符: {reply[:50]}...",
    )


async def main() -> None:
    # 1. 直接服务层测试（不依赖正在运行的后端进程）
    await _direct_service_test(model_hint="", description="Local / Default Model")
    await _direct_service_test(
        model_hint="deepseek-ai/DeepSeek-V3.2", description="Cloud DeepSeek"
    )

    # 2. HTTP 层测试（需要后端已在 localhost:8000 运行）
    try:
        requests.get(f"{BASE_URL}/docs", timeout=2)
    except Exception:
        _print_result(
            "HTTP connectivity",
            False,
            "后端 http://localhost:8000 不可达，跳过 HTTP 层测试。",
        )
        return

    _http_test_message(model="", description="Local / Default Model")
    _http_test_message(
        model="deepseek-ai/DeepSeek-V3.2", description="Cloud DeepSeek"
    )


def test_script_entrypoint_exists():
    """
    简单回归：确保测试脚本入口 main 函数存在且可被导入。
    这里不直接运行长时间的集成测试，仅验证模块结构稳定。
    """
    assert callable(main)


def test_handle_message_timeout_response_format(monkeypatch):
    import importlib
    api = importlib.import_module("routers.v1.chat")

    async def runner():
        class _FakeAvelineService:
            async def handle_conversation(self, *args, **kwargs):
                await asyncio.sleep(0.01)
                return {"status": "success", "response": "should not be used"}

        async def fake_wait_for(task, timeout):
            raise asyncio.TimeoutError()

        monkeypatch.setattr(api, "get_aveline_service", lambda: _FakeAvelineService())
        monkeypatch.setattr(api.asyncio, "wait_for", fake_wait_for)

        resp = await api.handle_message({"content": "test"}, conversation_id="test_conv", model=None, voice_id=None)

        assert resp["status"] == "success"
        assert isinstance(resp.get("response"), str)
        assert "抱歉" in resp.get("response", "")
        assert resp.get("error") == "Timeout"

    asyncio.run(runner())


def test_tts_timeout_response_format(monkeypatch):
    import importlib
    api = importlib.import_module("routers.v1.media")

    async def runner():
        async def fake_generate_tts_with_async(*args, **kwargs):
            await asyncio.sleep(0.01)
            return {"audio_base64": "data:audio/wav;base64,AAA"}

        async def fake_wait_for(task, timeout):
            raise asyncio.TimeoutError()

        monkeypatch.setattr(api, "_generate_tts_with_async", fake_generate_tts_with_async)
        monkeypatch.setattr(api.asyncio, "wait_for", fake_wait_for)

        resp = await api.tts({"text": "hello"})

        assert resp["status"] == "error"
        assert resp.get("error_code") == "TTS_TIMEOUT"
        assert isinstance(resp.get("detail"), str)

    asyncio.run(runner())


def test_local_llm_adapter_skip_preload_when_cpp_llm_enabled(monkeypatch):
    import importlib

    llm_mod = importlib.import_module("core.llm")
    scheduler_engine_mod = importlib.import_module("core.services.scheduler.cpp_scheduler_engine")
    config_mod = importlib.import_module("config.integrated_config")

    class _SchedulerSettings:
        use_cpp = True
        use_cpp_for_llm = True

    class _Settings:
        scheduler = _SchedulerSettings()

    monkeypatch.setattr(config_mod, "get_settings", lambda: _Settings())

    scheduler_engine_mod.cpp_scheduler_engine.enabled = True
    scheduler_engine_mod.cpp_scheduler_engine._gpu_config = {"model_path": "dummy.gguf"}

    class _DummyLocalModule:
        def __init__(self, loaded: bool):
            self._lock = asyncio.Lock()
            self.is_loaded = loaded
            self.load_calls = 0
            self.unload_calls = 0

        async def _load_model(self):
            self.load_calls += 1
            return True

        async def unload_model(self):
            self.unload_calls += 1

    adapter = llm_mod.LocalLLMAdapter.__new__(llm_mod.LocalLLMAdapter)
    adapter.is_available = True

    dummy = _DummyLocalModule(loaded=False)
    adapter.local_module = dummy
    asyncio.run(adapter.initialize())
    assert dummy.load_calls == 0
    assert dummy.unload_calls == 0

    dummy2 = _DummyLocalModule(loaded=True)
    adapter.local_module = dummy2
    asyncio.run(adapter.initialize())
    assert dummy2.load_calls == 0
    assert dummy2.unload_calls == 1


def test_resource_manager_emergency_cleanup_tts_timeout(monkeypatch):
    import importlib

    rm_mod = importlib.import_module("core.resource_manager")
    rm = rm_mod.ResourceManager()

    async def stuck_offload():
        await asyncio.sleep(3600)

    monkeypatch.setattr(rm, "_offload_voice_services", stuck_offload)

    async def runner():
        await asyncio.wait_for(rm._emergency_cleanup(), timeout=6.0)

    asyncio.run(runner())


@pytest.mark.anyio
async def test_prepare_for_heavy_task_image_gen_offloads_llm(monkeypatch):
    import importlib

    rm_mod = importlib.import_module("core.resource_manager")
    rm = rm_mod.ResourceManager()

    called = {"offload": 0}

    async def offload():
        called["offload"] += 1
        m = rm.models.get("llm_engine")
        if m:
            m.device = "CPU"
            m.vram_usage_mb = 0
            m.is_loaded = True

    rm.register_model(
        model_id="llm_engine",
        model_type="llm",
        priority=rm_mod.ResourcePriority.HIGH,
        load_func=lambda: None,
        unload_func=lambda: None,
        offload_func=offload,
        instance=object(),
    )
    rm.mark_model_loaded("llm_engine", True)
    rm.models["llm_engine"].device = "GPU"
    rm.models["llm_engine"].vram_usage_mb = 123

    class _DummyTorchCuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def empty_cache():
            return None

    class _DummyTorch:
        cuda = _DummyTorchCuda()

    monkeypatch.setattr(rm_mod, "torch", _DummyTorch())
    monkeypatch.setattr(rm.monitor, "get_gpu_memory_usage", lambda: (1000, 2000))

    await rm.prepare_for_heavy_task("image_gen")

    assert called["offload"] == 1
    assert rm.models["llm_engine"].device == "CPU"
    assert rm.models["llm_engine"].vram_usage_mb == 0


def test_active_care_health_checker_registration_and_status():
    import asyncio

    from core.async_monitor import get_health_checker
    from core.services.active_care.core.service import get_active_care_service

    async def runner():
        svc = get_active_care_service()
        await svc.initialize()

        hc = get_health_checker()
        assert "active_care_service" in hc.health_checkers

        res = await hc.check_service_health("active_care_service")
        assert res["status"] == "healthy"
        assert isinstance(res.get("details"), dict)

        await svc.shutdown()

        res2 = await hc.check_service_health("active_care_service")
        assert res2["status"] == "unhealthy"

    asyncio.run(runner())


if __name__ == "__main__":
    asyncio.run(main())
