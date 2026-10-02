"""core/modules/llm/stream_generator.py 的单元测试补强。

策略：
- 全部使用替身（FakeModule / 假 stream / 假 streamer / 假 scheduler），
  绝不加载真实模型、绝不联网、绝不 sleep 等待真实网络时序。
- 异步代码统一用「同步测试函数 + asyncio.run(...)」。
- 时间相关分支用可控的假时钟（sg.time 替换）触发，不依赖真实耗时。
"""

from __future__ import annotations

import asyncio
import sys
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from core.modules.llm import stream_generator as sg
from core.modules.llm.stream_generator import StreamGenerator


# --------------------------------------------------------------------------
# 基础替身
# --------------------------------------------------------------------------


class _DummyAsyncLock:
    """最小异步上下文管理器，避免 asyncio.Lock 跨事件循环绑定问题。"""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeResourceLock:
    """替身 GPU 资源锁，只记录调用，不做真实信号量等待。"""

    def __init__(self):
        self.calls = []

    @asynccontextmanager
    async def acquire(self, requestor, *, reject_if_full=False):
        self.calls.append((requestor, reject_if_full))
        yield self


class _RaisingDict(dict):
    """get() 永远抛异常的 dict，用来触发防御性 except 分支。"""

    def get(self, key, default=None):
        raise RuntimeError(f"config get failed: {key}")


class _FakeClock:
    """假时钟：按序吐出预设时间戳，用尽后重复最后一个值。"""

    def __init__(self, values):
        self._values = list(values)
        self._last = self._values[-1] if self._values else 0.0

    def time(self):
        if self._values:
            self._last = self._values.pop(0)
        return self._last


class _FakeTensor:
    def cuda(self):
        return self

    def to(self, *args, **kwargs):
        return self


class _FakeTokenizer:
    eos_token_id = 0

    def __init__(self, template_raises=False):
        self.template_raises = template_raises

    def __call__(self, text, return_tensors=None):
        return {"input_ids": _FakeTensor()}

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
        if self.template_raises:
            raise ValueError("no chat template")
        return "TEMPLATE"


class _FakeStreamer:
    """预编排好的流式片段序列。"""

    pieces = ("你", "好")

    def __init__(self, tokenizer=None, skip_prompt=True, skip_special_tokens=True):
        self.tokenizer = tokenizer
        self.skip_prompt = skip_prompt
        self.skip_special_tokens = skip_special_tokens
        self._pieces = list(self.__class__.pieces)

    def __iter__(self):
        return iter(self._pieces)


class _FakeCuda:
    def __init__(self, available=True, name_raises=False):
        self._available = available
        self._name_raises = name_raises
        self.empty_cache_calls = 0
        self.ipc_collect_calls = 0

    def is_available(self):
        return self._available

    def get_device_name(self, idx):
        if self._name_raises:
            raise RuntimeError("no device")
        return "FakeGPU"

    def get_device_properties(self, idx):
        return SimpleNamespace(total_memory=8 * (1024**3))

    def memory_allocated(self, idx):
        return 1024**3

    def memory_reserved(self, idx):
        return 2 * (1024**3)

    def empty_cache(self):
        self.empty_cache_calls += 1

    def ipc_collect(self):
        self.ipc_collect_calls += 1


class _FakeTorch:
    def __init__(self, cuda):
        self.cuda = cuda


class _FakeLlamaModel:
    """替身 llama_model：可配置 n_ctx / n_gpu_layers / 流式响应块。"""

    def __init__(
        self,
        chunks=None,
        n_ctx=2048,
        n_ctx_raises=False,
        n_gpu_layers=None,
        n_gpu_layers_raises=False,
        chat_error=None,
        chat_error_once=None,
    ):
        self._chunks = chunks if chunks is not None else []
        self._n_ctx = n_ctx
        self._n_ctx_raises = n_ctx_raises
        self._n_gpu_layers = n_gpu_layers
        self._n_gpu_layers_raises = n_gpu_layers_raises
        self._chat_error = chat_error
        self._chat_error_once = chat_error_once
        self.calls = []

    def n_ctx(self):
        if self._n_ctx_raises:
            raise RuntimeError("n_ctx failed")
        return self._n_ctx

    def n_gpu_layers(self):
        if self._n_gpu_layers_raises:
            raise RuntimeError("n_gpu_layers failed")
        return self._n_gpu_layers

    def create_chat_completion(self, messages=None, **kwargs):
        self.calls.append((messages, kwargs))
        if self._chat_error_once is not None:
            err = self._chat_error_once
            self._chat_error_once = None
            raise err
        if self._chat_error is not None:
            raise self._chat_error
        return iter(list(self._chunks))


class FakeModule:
    """LLMModule 的最小替身。"""

    def __init__(self, **over):
        self.settings = SimpleNamespace(
            model=_model_settings(), scheduler=SimpleNamespace(worker_count=2)
        )
        self.config = {}
        self.text_model_path = "models/llm/demo.gguf"
        self.device = "cpu"
        self.is_gguf = False
        self.is_loaded = True
        self.llama_model = None
        self.model = SimpleNamespace(generate=lambda **kw: None)
        self.tokenizer = _FakeTokenizer()
        self._lock = _DummyAsyncLock()
        self._thread_lock = threading.Lock()
        self.last_used = 0.0
        self._last_load_error = None
        self._recovery_task = None
        self._last_timeout_at = None
        self._force_cpu_after_timeout = False
        self._use_cpp_scheduler_for_llm = False
        self._load_results = [True]
        self._load_model_calls = 0
        self._unload_calls = 0
        for k, v in over.items():
            setattr(self, k, v)

    async def _load_model_wrapper(self, loader):
        self._load_model_calls += 1
        if self._load_results:
            return self._load_results.pop(0)
        return True

    async def _unload_model_unsafe(self, sleep_s: float = 0.5):
        self._unload_calls += 1
        return True


def _model_settings(**over):
    base = dict(
        max_new_tokens=64,
        temperature=0.5,
        min_p=None,
        repetition_penalty=1.1,
        top_p=0.9,
        top_k=None,
        n_gpu_layers=-1,
        n_ctx=None,
        first_token_timeout=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _collect(async_gen):
    """同步收集异步生成器的全部产出。"""

    async def _run():
        return [item async for item in async_gen]

    return asyncio.run(_run())


def _patch_scheduler_enabled(monkeypatch, value: bool):
    from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

    monkeypatch.setattr(CPPSchedulerEngine, "enabled", property(lambda self: value))


@pytest.fixture()
def no_gpu_gate(monkeypatch):
    """默认把 GPU 资源锁换成替身，避免真实信号量跨事件循环绑定。"""
    lock = _FakeResourceLock()
    monkeypatch.setattr(sg, "get_resource_lock", lambda: lock)
    return lock


# --------------------------------------------------------------------------
# _prompt_to_text / _calculate_first_token_timeout / _parse_context_window_error
# --------------------------------------------------------------------------


def test_prompt_to_text_covers_all_message_shapes():
    gen = StreamGenerator(FakeModule())
    prompt = [
        {"role": "user", "content": "hi"},  # 正常 role+content
        {"content": "only-content"},  # role 缺失
        {"role": "assistant"},  # content 缺失
        {},  # role/content 都缺失
        "raw-string",  # 非 dict
    ]
    text = gen._prompt_to_text(prompt)
    assert "user: hi" in text
    assert "only-content" in text
    assert "assistant:" in text
    assert text.count("\n") == 4


def test_prompt_to_text_non_str_and_str_and_failure():
    gen = StreamGenerator(FakeModule())
    assert gen._prompt_to_text("plain") == "plain"

    class _Str:
        def __str__(self):
            return "converted"

    assert gen._prompt_to_text(_Str()) == "converted"

    class _BadStr:
        def __str__(self):
            raise ValueError("nope")

    # 转换失败应回退为空字符串
    assert gen._prompt_to_text(_BadStr()) == ""


def test_calculate_first_token_timeout_gpu_and_cpu():
    gen = StreamGenerator(FakeModule())
    # 无 token 估算时直接返回 base_timeout
    assert gen._calculate_first_token_timeout("", 12.5, False) == 12.5

    gpu_val = gen._calculate_first_token_timeout("hello world " * 20, 5.0, False)
    cpu_val = gen._calculate_first_token_timeout("hello world " * 20, 5.0, True)
    assert gpu_val >= 5.0
    assert cpu_val >= gpu_val
    # 上限被 120.0 截断
    huge = gen._calculate_first_token_timeout("字" * 5000, 1.0, True)
    assert huge == 120.0


def test_parse_context_window_error_hit_and_miss():
    gen = StreamGenerator(FakeModule())
    assert gen._parse_context_window_error("nothing here") is None
    assert gen._parse_context_window_error(None) is None
    parsed = gen._parse_context_window_error(
        "requested tokens (300) exceed context window of 128"
    )
    assert parsed == (300, 128)


def test_parse_context_window_error_int_failure_branch(monkeypatch):
    """int() 转换失败分支：用替身 re.search 强制返回会抛异常的 match。"""
    gen = StreamGenerator(FakeModule())

    class _BadMatch:
        def group(self, idx):
            raise ValueError("bad group")

    monkeypatch.setattr(sg.re, "search", lambda *a, **k: _BadMatch())
    assert gen._parse_context_window_error("whatever") is None


# --------------------------------------------------------------------------
# _retry_context_window_stream
# --------------------------------------------------------------------------


def test_retry_context_window_stream_returns_none_when_unparsable():
    module = FakeModule(llama_model=_FakeLlamaModel())
    gen = StreamGenerator(module)
    assert gen._retry_context_window_stream([], {}, 100, "no match") is None
    assert module.llama_model.calls == []


def test_retry_context_window_stream_shrinks_and_halves():
    model = _FakeLlamaModel(chunks=[{"ok": 1}])
    module = FakeModule(llama_model=model)
    gen = StreamGenerator(module)

    # max_tokens 很小 -> 收缩结果被 16 兜底，进而触发 >= max_tokens 的折半分支
    err = "requested tokens (140) exceed context window of 128"
    out = gen._retry_context_window_stream(
        [{"role": "user", "content": "x"}], {"temperature": 0.5}, 16, err
    )
    assert out is not None
    assert model.calls[0][1]["max_tokens"] == 16


def test_retry_context_window_stream_normal_shrink():
    model = _FakeLlamaModel(chunks=[{"ok": 1}])
    module = FakeModule(llama_model=model)
    gen = StreamGenerator(module)

    err = "requested tokens (140) exceed context window of 128"
    out = gen._retry_context_window_stream([], {"temperature": 0.5}, 200, err)
    assert out is not None
    # 200 - 12 - 32 = 156
    assert model.calls[0][1]["max_tokens"] == 156


def test_retry_context_window_stream_type_error_retry():
    model = _FakeLlamaModel(
        chunks=[{"ok": 1}], chat_error_once=TypeError("unexpected keyword argument 'min_p'")
    )
    module = FakeModule(llama_model=model)
    gen = StreamGenerator(module)
    err = "requested tokens (140) exceed context window of 128"
    out = gen._retry_context_window_stream(
        [], {"temperature": 0.5, "min_p": 0.1}, 200, err
    )
    assert out is not None
    assert len(model.calls) == 2
    assert "min_p" not in model.calls[1][1]


# --------------------------------------------------------------------------
# generate：早退 / 调度器 / 加载 / 切换
# --------------------------------------------------------------------------


def test_generate_rejects_cloud_model_path():
    module = FakeModule()
    gen = StreamGenerator(module)
    items = _collect(gen.generate("hi", model_path="cloud:qwen-max"))
    assert len(items) == 1
    assert items[0]["done"] is True
    assert "cloud" in items[0]["error"].lower() or "Cloud" in items[0]["error"]


def test_generate_delegates_to_cpp_scheduler(monkeypatch, no_gpu_gate):
    module = FakeModule(is_loaded=True, _use_cpp_scheduler_for_llm=True)
    gen = StreamGenerator(module)
    _patch_scheduler_enabled(monkeypatch, True)

    class _Scheduler:
        _running = True

        async def submit_llm_task(self, prompt, **kwargs):
            yield {"content": "A"}
            yield {"done": True}

    monkeypatch.setattr(
        "core.services.scheduler.task.task_scheduler.get_global_scheduler",
        lambda: _Scheduler(),
    )
    items = _collect(gen.generate("hi"))
    assert items == [{"content": "A"}, {"done": True}]
    assert module._unload_calls == 1


def test_generate_scheduler_start_failure_yields_error(monkeypatch, no_gpu_gate):
    module = FakeModule(_use_cpp_scheduler_for_llm=True)
    gen = StreamGenerator(module)
    _patch_scheduler_enabled(monkeypatch, True)

    class _Scheduler:
        _running = False

        async def start(self, worker_count=3, llm_model_path=None):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "core.services.scheduler.task.task_scheduler.get_global_scheduler",
        lambda: _Scheduler(),
    )
    items = _collect(gen.generate("hi"))
    assert items[0]["done"] is True
    assert "全局调度器启动失败" in items[0]["error"]


def test_generate_scheduler_worker_count_fallback(monkeypatch, no_gpu_gate):
    """settings.scheduler 异常时 worker_count 回退到 4。"""
    module = FakeModule(_use_cpp_scheduler_for_llm=True)
    module.settings.scheduler = SimpleNamespace(worker_count="not-a-number")
    gen = StreamGenerator(module)
    _patch_scheduler_enabled(monkeypatch, True)

    captured = {}

    class _Scheduler:
        _running = False

        async def start(self, worker_count=3, llm_model_path=None):
            captured["worker_count"] = worker_count

        async def submit_llm_task(self, prompt, **kwargs):
            yield {"content": "X"}

    monkeypatch.setattr(
        "core.services.scheduler.task.task_scheduler.get_global_scheduler",
        lambda: _Scheduler(),
    )
    items = _collect(gen.generate("hi"))
    assert captured["worker_count"] == 4
    assert items == [{"content": "X"}]


def test_generate_transformers_end_to_end(monkeypatch, no_gpu_gate):
    module = FakeModule(is_loaded=True, is_gguf=False, device="cpu")
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "TextIteratorStreamer", _FakeStreamer)
    items = _collect(gen.generate("hi", max_tokens=8, temperature=0.2))
    assert items == [{"content": "你"}, {"content": "好"}]


def test_generate_transformers_list_prompt_and_cuda(monkeypatch, no_gpu_gate):
    """列表 prompt + cuda 设备 + top_k/min_p 非 None。"""
    module = FakeModule(
        is_loaded=True,
        is_gguf=False,
        device="cuda",
        tokenizer=_FakeTokenizer(template_raises=True),
    )
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "TextIteratorStreamer", _FakeStreamer)
    monkeypatch.setattr(
        "core.resource_manager.get_global_resource_manager",
        lambda: _fake_rm(),
    )
    items = _collect(gen.generate([{"role": "user", "content": "hi"}], max_tokens=8))
    assert items == [{"content": "你"}, {"content": "好"}]
    assert no_gpu_gate.calls  # cuda 设备触发了 GPU 资源锁


async def _fake_rm():
    class _RM:
        async def prepare_for_heavy_task(self, task_type="llm"):
            return True

    return _RM()


def test_generate_gguf_end_to_end_with_gpu_gate(monkeypatch, no_gpu_gate):
    """gguf + config 读取失败：覆盖 need_gpu_gate 兜底与 GPU 状态检测兜底。"""
    model = _FakeLlamaModel(
        chunks=[
            {"choices": [{"delta": {"content": "片段"}}]},
            {"choices": [{"delta": {}}]},
        ],
        n_ctx=2048,
    )
    module = FakeModule(
        is_loaded=True, is_gguf=True, config=_RaisingDict(), llama_model=model
    )
    gen = StreamGenerator(module)
    monkeypatch.setattr(
        "core.resource_manager.get_global_resource_manager", lambda: _fake_rm()
    )
    items = _collect(gen.generate("你好"))
    assert items == [{"content": "片段"}]
    assert no_gpu_gate.calls  # need_gpu_gate 兜底为 True


def test_generate_model_switch_and_load_failure(monkeypatch, no_gpu_gate):
    module = FakeModule(is_loaded=True, _load_results=[False, False])
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "TextIteratorStreamer", _FakeStreamer)
    items = _collect(gen.generate("hi", model_path="D:/models/other.gguf"))
    assert items[0]["done"] is True
    assert items[0]["status"] == "error"
    # 触发了模型切换卸载 + 加载 + 回退加载
    assert module._unload_calls >= 1
    assert module._load_model_calls == 2


def test_generate_load_failure_with_successful_fallback(monkeypatch, no_gpu_gate):
    module = FakeModule(is_loaded=True, _load_results=[False, True])
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "TextIteratorStreamer", _FakeStreamer)
    items = _collect(gen.generate("hi", model_path="D:/models/other.gguf"))
    assert items == [{"content": "你"}, {"content": "好"}]
    assert module._load_model_calls == 2


def test_generate_resets_inconsistent_loaded_flag(monkeypatch, no_gpu_gate):
    """is_loaded=True 但本地推理对象缺失 -> 强制重载，随后 tokenizer/model 仍缺失。"""
    module = FakeModule(is_loaded=True, is_gguf=False, model=None, tokenizer=None)
    gen = StreamGenerator(module)
    items = _collect(gen.generate("hi"))
    assert items[0]["done"] is True
    assert "未正确初始化" in items[0]["error"]
    assert module._load_model_calls == 1


def test_generate_error_when_last_load_error_missing(monkeypatch, no_gpu_gate):
    module = FakeModule(
        is_loaded=False, _load_results=[False], _last_load_error=None
    )
    gen = StreamGenerator(module)
    items = _collect(gen.generate("hi"))
    assert items[0]["error"] == "模型加载失败"


# --------------------------------------------------------------------------
# _generate_with_scheduler 直接测试
# --------------------------------------------------------------------------


def _run_scheduler(monkeypatch, module, scheduler):
    # 标记调度器已在运行，跳过 start 分支
    scheduler._running = True
    monkeypatch.setattr(
        "core.services.scheduler.task.task_scheduler.get_global_scheduler",
        lambda: scheduler,
    )
    gen = StreamGenerator(module)
    return _collect(
        gen._generate_with_scheduler("hi", None, None, "models/llm/x.gguf", 5.0, None)
    )


def test_generate_with_scheduler_token_shapes(monkeypatch):
    module = FakeModule(is_loaded=False)

    class _Scheduler:
        async def submit_llm_task(self, prompt, **kwargs):
            yield {"content": "A"}
            yield {"status": "progress"}
            yield "plain-token"
            yield {"done": True}
            yield {"content": "never"}

    items = _run_scheduler(monkeypatch, module, _Scheduler())
    assert items == [
        {"content": "A"},
        {"status": "progress"},
        {"content": "plain-token"},
        {"done": True},
    ]


def test_generate_with_scheduler_error_token_returns(monkeypatch):
    module = FakeModule(is_loaded=False)

    class _Scheduler:
        async def submit_llm_task(self, prompt, **kwargs):
            yield {"error": "boom", "done": True}
            yield {"content": "never"}

    items = _run_scheduler(monkeypatch, module, _Scheduler())
    assert items == [{"error": "boom", "done": True}]


def test_generate_with_scheduler_generic_exception(monkeypatch):
    module = FakeModule(is_loaded=False)

    class _Scheduler:
        async def submit_llm_task(self, prompt, **kwargs):
            raise RuntimeError("backend down")
            yield  # pragma: no cover

    items = _run_scheduler(monkeypatch, module, _Scheduler())
    assert items[0]["done"] is True
    assert "调度服务暂时不可用" in items[0]["error"]


def test_generate_with_scheduler_cancelled_with_stop_hook(monkeypatch):
    module = FakeModule(is_loaded=False)
    called = {"stop": 0}

    class _Scheduler:
        _running = True

        async def submit_llm_task(self, prompt, **kwargs):
            raise asyncio.CancelledError()
            yield  # pragma: no cover

        async def request_stop_current_inference(self):
            called["stop"] += 1

    gen = StreamGenerator(module)
    monkeypatch.setattr(
        "core.services.scheduler.task.task_scheduler.get_global_scheduler",
        lambda: _Scheduler(),
    )
    with pytest.raises(asyncio.CancelledError):
        _collect(gen._generate_with_scheduler("hi", None, None, "m.gguf", 5.0, None))
    assert called["stop"] == 1


def test_generate_with_scheduler_cancelled_without_stop_hook(monkeypatch):
    """scheduler 没有 stop 方法时走 cpp_scheduler_engine 兜底。"""
    module = FakeModule(is_loaded=False)
    stop_calls = {"n": 0}

    from core.services.scheduler import cpp_scheduler_engine as cse

    async def _fake_stop(*args, **kwargs):
        stop_calls["n"] += 1

    monkeypatch.setattr(
        cse.cpp_scheduler_engine, "request_stop_current_inference", _fake_stop
    )

    class _Scheduler:
        _running = True

        async def submit_llm_task(self, prompt, **kwargs):
            raise asyncio.CancelledError()
            yield  # pragma: no cover

    gen = StreamGenerator(module)
    monkeypatch.setattr(
        "core.services.scheduler.task.task_scheduler.get_global_scheduler",
        lambda: _Scheduler(),
    )
    with pytest.raises(asyncio.CancelledError):
        _collect(gen._generate_with_scheduler("hi", None, None, "m.gguf", 5.0, None))
    assert stop_calls["n"] == 1


# --------------------------------------------------------------------------
# _prepare_gpu_resources
# --------------------------------------------------------------------------


def test_prepare_gpu_resources_gguf_layers_from_config(monkeypatch):
    module = FakeModule(
        is_gguf=True, config={"n_gpu_layers": 0}, text_model_path="a.gguf"
    )
    gen = StreamGenerator(module)
    rm_calls = []

    async def _rm():
        class _RM:
            async def prepare_for_heavy_task(self, task_type="llm"):
                rm_calls.append(task_type)

        return _RM()

    monkeypatch.setattr(
        "core.resource_manager.get_global_resource_manager", lambda: _rm()
    )
    asyncio.run(gen._prepare_gpu_resources())
    # n_gpu_layers=0 -> 不准备 GPU
    assert rm_calls == []


def test_prepare_gpu_resources_gguf_layers_from_settings(monkeypatch):
    module = FakeModule(
        is_gguf=True, config={}, text_model_path="a.gguf", device="cpu"
    )
    module.settings.model = _model_settings(n_gpu_layers=-1)
    gen = StreamGenerator(module)
    rm_calls = []

    async def _rm():
        class _RM:
            async def prepare_for_heavy_task(self, task_type="llm"):
                rm_calls.append(task_type)

        return _RM()

    monkeypatch.setattr(
        "core.resource_manager.get_global_resource_manager", lambda: _rm()
    )
    asyncio.run(gen._prepare_gpu_resources())
    assert rm_calls == ["llm"]


def test_prepare_gpu_resources_int_conversion_failure(monkeypatch):
    module = FakeModule(
        is_gguf=True, config={"n_gpu_layers": "bad"}, text_model_path="a.gguf"
    )
    gen = StreamGenerator(module)
    rm_calls = []

    async def _rm():
        class _RM:
            async def prepare_for_heavy_task(self, task_type="llm"):
                rm_calls.append(task_type)

        return _RM()

    monkeypatch.setattr(
        "core.resource_manager.get_global_resource_manager", lambda: _rm()
    )
    asyncio.run(gen._prepare_gpu_resources())
    assert rm_calls == ["llm"]


def test_prepare_gpu_resources_outer_exception_and_rm_failure(monkeypatch):
    class _BadDevice:
        def __str__(self):
            raise RuntimeError("bad device")

    module = FakeModule(is_gguf=False, text_model_path=None, device=_BadDevice())
    gen = StreamGenerator(module)
    # 外层 except -> should_prepare_gpu=True，随后资源管理器调用抛异常被吞掉
    monkeypatch.setattr(
        "core.resource_manager.get_global_resource_manager",
        lambda: _raising_rm(),
    )
    asyncio.run(gen._prepare_gpu_resources())


async def _raising_rm():
    raise RuntimeError("rm unavailable")


# --------------------------------------------------------------------------
# _try_fallback_model
# --------------------------------------------------------------------------


def test_try_fallback_model_success(monkeypatch):
    module = FakeModule(
        is_loaded=True, _load_results=[True], _use_cpp_scheduler_for_llm=True
    )
    gen = StreamGenerator(module)
    ok = asyncio.run(gen._try_fallback_model("D:/models/old.gguf"))
    assert ok is True
    assert module.text_model_path == "D:/models/old.gguf"
    # scheduler 标志被恢复
    assert module._use_cpp_scheduler_for_llm is True


def test_try_fallback_model_exception_returns_false():
    module = FakeModule()
    gen = StreamGenerator(module)

    async def _boom(sleep_s=0.5):
        raise RuntimeError("unload failed")

    module._unload_model_unsafe = _boom
    assert asyncio.run(gen._try_fallback_model("D:/models/old.gguf")) is False


# --------------------------------------------------------------------------
# _clamp_max_tokens_for_gguf
# --------------------------------------------------------------------------


def test_clamp_max_tokens_no_clamp_when_small():
    module = FakeModule(llama_model=_FakeLlamaModel(n_ctx=100000))
    gen = StreamGenerator(module)
    assert gen._clamp_max_tokens_for_gguf(100) == 100


def test_clamp_max_tokens_clamps_large_value():
    module = FakeModule(llama_model=_FakeLlamaModel(n_ctx=1024))
    gen = StreamGenerator(module)
    # max(512, 1024*0.8=819) = 819
    assert gen._clamp_max_tokens_for_gguf(5000) == 819


def test_clamp_max_tokens_n_ctx_raises_then_config_fallback():
    module = FakeModule(
        llama_model=_FakeLlamaModel(n_ctx_raises=True), config={"n_ctx": 1024}
    )
    gen = StreamGenerator(module)
    assert gen._clamp_max_tokens_for_gguf(5000) == 819


def test_clamp_max_tokens_without_n_ctx_attr():
    module = FakeModule(llama_model=SimpleNamespace(), config={})
    module.settings.model = _model_settings(n_ctx=512)
    gen = StreamGenerator(module)
    # 512*0.8=409 -> max(512,409)=512
    assert gen._clamp_max_tokens_for_gguf(5000) == 512


def test_clamp_max_tokens_exception_returns_input():
    module = FakeModule(llama_model=SimpleNamespace(), config=_RaisingDict())
    gen = StreamGenerator(module)
    assert gen._clamp_max_tokens_for_gguf(1234) == 1234


# --------------------------------------------------------------------------
# _adjust_timeout
# --------------------------------------------------------------------------


def test_adjust_timeout_invalid_base_uses_config():
    module = FakeModule(config={"first_token_timeout": 7.0}, device="cpu")
    gen = StreamGenerator(module)
    out = gen._adjust_timeout("hi", 0)
    assert out >= 7.0


def test_adjust_timeout_config_exception_falls_back_to_10():
    module = FakeModule(config=_RaisingDict(), device="cpu", is_gguf=False)
    gen = StreamGenerator(module)
    out = gen._adjust_timeout("hi", -1)
    assert out >= 10.0


def test_adjust_timeout_gguf_clamps_and_detects_cpu():
    module = FakeModule(
        is_gguf=True,
        config={"n_gpu_layers": 0},
        llama_model=_FakeLlamaModel(n_ctx=2048),
    )
    gen = StreamGenerator(module)
    out = gen._adjust_timeout("字" * 20000, 5.0)
    assert out >= 5.0


def test_adjust_timeout_gguf_n_ctx_raises_and_bad_layers():
    module = FakeModule(
        is_gguf=True,
        config={"n_gpu_layers": "bad"},
        llama_model=_FakeLlamaModel(n_ctx_raises=True),
    )
    gen = StreamGenerator(module)
    out = gen._adjust_timeout("hi", 5.0)
    assert out >= 5.0


# --------------------------------------------------------------------------
# _iterate_stream
# --------------------------------------------------------------------------


def _iter_stream(gen, stream, start_gen_time, is_gpu_infer=False, layers=0, clock=None, monkeypatch=None):
    puts = []
    if clock is not None:
        monkeypatch.setattr(sg, "time", SimpleNamespace(time=clock.time))
    gen._iterate_stream(stream, start_gen_time, is_gpu_infer, layers, puts.append)
    return puts


def test_iterate_stream_none_stream():
    gen = StreamGenerator(FakeModule())
    puts = _iter_stream(gen, None, 0.0)
    assert puts[0]["done"] is True
    assert "stream" in puts[0]["error"].lower()


def test_iterate_stream_skips_bad_chunks(monkeypatch):
    gen = StreamGenerator(FakeModule())
    stream = iter(
        [
            "not-a-dict",
            {},
            {"choices": []},
            {"choices": [{"delta": {}}]},
            {"choices": [{"delta": {"content": "ok"}}]},
        ]
    )
    clock = _FakeClock([0.0])
    puts = _iter_stream(gen, stream, 0.0, clock=clock, monkeypatch=monkeypatch)
    assert puts == [{"content": "ok"}]


def test_iterate_stream_first_chunk_long_delay_branch(monkeypatch):
    """count==0 且迭代超过 10s -> GPU 诊断分支。"""
    fake_torch = _FakeTorch(_FakeCuda(available=True))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    gen = StreamGenerator(FakeModule())
    stream = iter([{"choices": [{"delta": {"content": "x"}}]}])
    clock = _FakeClock([0.0, 0.0, 11.0, 11.0, 11.0])
    puts = _iter_stream(gen, stream, 0.0, clock=clock, monkeypatch=monkeypatch)
    assert puts == [{"content": "x"}]


def test_iterate_stream_first_chunk_long_delay_cuda_error_swallowed(monkeypatch):
    fake_torch = _FakeTorch(_FakeCuda(available=True, name_raises=True))
    fake_torch.cuda.is_available = lambda: (_ for _ in ()).throw(RuntimeError("no cuda"))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    gen = StreamGenerator(FakeModule())
    stream = iter([{"choices": [{"delta": {"content": "y"}}]}])
    clock = _FakeClock([0.0, 0.0, 11.0, 11.0, 11.0])
    puts = _iter_stream(gen, stream, 0.0, clock=clock, monkeypatch=monkeypatch)
    assert puts == [{"content": "y"}]


def test_iterate_stream_chunk_stall_branch(monkeypatch):
    """count>0 且距上次 chunk 超过 30s -> 卡住告警分支。"""
    gen = StreamGenerator(FakeModule())
    stream = iter(
        [
            {"choices": [{"delta": {"content": "a"}}]},
            {"choices": [{"delta": {"content": "b"}}]},
        ]
    )
    clock = _FakeClock([0.0, 0.0, 1.0, 1.0, 40.0, 40.0])
    puts = _iter_stream(gen, stream, 0.0, clock=clock, monkeypatch=monkeypatch)
    assert puts == [{"content": "a"}, {"content": "b"}]


def test_iterate_stream_stop_iteration_branch():
    class _StopChunk(dict):
        def __getitem__(self, key):
            raise StopIteration()

    gen = StreamGenerator(FakeModule())
    stream = iter([_StopChunk({"choices": [{"delta": {"content": "x"}}]})])
    puts = _iter_stream(gen, stream, 0.0)
    # StopIteration 被吞掉，不产生任何内容
    assert puts == []


def test_iterate_stream_exception_branch():
    gen = StreamGenerator(FakeModule())

    def _bad_stream():
        yield {"choices": [{"delta": {"content": "x"}}]}
        raise RuntimeError("stream broke")

    puts = _iter_stream(gen, _bad_stream(), 0.0)
    assert puts[0]["content"] == "x"
    assert puts[1]["done"] is True
    assert "GPU推理stream异常" in puts[1]["error"]


# --------------------------------------------------------------------------
# _cleanup_and_retry_cpu
# --------------------------------------------------------------------------


def test_cleanup_and_retry_cpu_success(monkeypatch):
    module = FakeModule(
        llama_model=_FakeLlamaModel(), config={"n_gpu_layers": -1, "n_ctx": 4096}
    )
    gen = StreamGenerator(module)
    fake_torch = _FakeTorch(_FakeCuda(available=True))
    monkeypatch.setattr(sg, "get_torch", lambda: fake_torch)

    def _load_sync(self):
        self.module.llama_model = _FakeLlamaModel()
        return True

    monkeypatch.setattr(
        "core.modules.llm.model_loader.ModelLoader.load_sync", _load_sync
    )
    gen._cleanup_and_retry_cpu()
    assert module.config["n_gpu_layers"] == 0
    assert module.config["n_ctx"] == 2048
    assert module.is_loaded is False
    assert fake_torch.cuda.empty_cache_calls == 1
    assert fake_torch.cuda.ipc_collect_calls == 1


def test_cleanup_and_retry_cpu_raises_when_reload_fails(monkeypatch):
    module = FakeModule(llama_model=_FakeLlamaModel(), config={"n_ctx": "bad"})
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "get_torch", lambda: None)
    monkeypatch.setattr(
        "core.modules.llm.model_loader.ModelLoader.load_sync",
        lambda self: False,
    )
    with pytest.raises(RuntimeError, match="切换到CPU模式后重新加载失败"):
        gen._cleanup_and_retry_cpu()
    # n_ctx int() 失败 -> 回退 2048
    assert module.config["n_ctx"] == 2048


def test_cleanup_and_retry_cpu_handles_del_failure(monkeypatch):
    class _NoDel:
        """llama_model 存在但 del 时抛异常。"""

        def __del__(self):
            raise RuntimeError("cannot del")

    module = FakeModule(config={})
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "get_torch", lambda: None)
    monkeypatch.setattr(
        "core.modules.llm.model_loader.ModelLoader.load_sync",
        lambda self: False,
    )
    with pytest.raises(RuntimeError):
        gen._cleanup_and_retry_cpu()
    assert module.llama_model is None


# --------------------------------------------------------------------------
# _generate_transformers 分支
# --------------------------------------------------------------------------


def test_generate_transformers_missing_runtime():
    module = FakeModule(model=None, tokenizer=None)
    gen = StreamGenerator(module)
    puts = []
    gen._generate_transformers("hi", 8, 0.5, 0.9, None, 1.1, None, puts.append)
    assert puts[0]["done"] is True


def test_generate_transformers_missing_streamer(monkeypatch):
    module = FakeModule()
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "TextIteratorStreamer", None)
    puts = []
    gen._generate_transformers("hi", 8, 0.5, 0.9, None, 1.1, None, puts.append)
    assert "TextIteratorStreamer" in puts[0]["error"]


def test_generate_transformers_top_k_conversion_failure(monkeypatch):
    module = FakeModule(device="cpu")
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "TextIteratorStreamer", _FakeStreamer)
    puts = []
    gen._generate_transformers("hi", 8, 0.5, 0.9, object(), 1.1, 0.05, puts.append)
    assert puts == [{"content": "你"}, {"content": "好"}]


def test_generate_transformers_list_prompt_template(monkeypatch):
    module = FakeModule(device="cpu")
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "TextIteratorStreamer", _FakeStreamer)
    puts = []
    gen._generate_transformers(
        [{"role": "user", "content": "hi"}], 8, 0.5, 0.9, 4, 1.1, None, puts.append
    )
    assert len(puts) == 2


# --------------------------------------------------------------------------
# _consume_queue
# --------------------------------------------------------------------------


def test_consume_queue_normal_and_sentinel():
    module = FakeModule(_force_cpu_after_timeout=True, _last_timeout_at=123.0)
    gen = StreamGenerator(module)
    queue = asyncio.Queue()

    async def _run():
        await queue.put({"content": "a"})
        await queue.put({"error": "warn-only"})
        await queue.put(None)
        return [item async for item in gen._consume_queue(queue, 5.0)]

    items = asyncio.run(_run())
    assert items == [{"content": "a"}, {"error": "warn-only"}]
    # 收到过 token -> 复位标志
    assert module._force_cpu_after_timeout is False
    assert module._last_timeout_at is None


def test_consume_queue_first_token_timeout_triggers_recovery(monkeypatch):
    module = FakeModule()
    gen = StreamGenerator(module)
    queue = asyncio.Queue()
    clock = _FakeClock([0.0, 2.0, 6.0, 6.0, 6.0, 6.0, 6.0])
    monkeypatch.setattr(sg, "time", SimpleNamespace(time=clock.time))

    async def _run():
        return [item async for item in gen._consume_queue(queue, 5.0)]

    items = asyncio.run(_run())
    assert items[0]["done"] is True
    assert "5.0" in items[0]["error"]
    assert module._force_cpu_after_timeout is True
    assert module.config["n_gpu_layers"] == 0


# --------------------------------------------------------------------------
# _trigger_recovery
# --------------------------------------------------------------------------


def test_trigger_recovery_returns_when_task_running():
    class _RunningTask:
        def done(self):
            return False

    module = FakeModule()
    module._recovery_task = _RunningTask()
    gen = StreamGenerator(module)
    asyncio.run(gen._trigger_recovery())
    # 提前返回，未改动标志
    assert module._force_cpu_after_timeout is False


def test_trigger_recovery_normal_completes():
    module = FakeModule()
    gen = StreamGenerator(module)
    asyncio.run(gen._trigger_recovery())
    assert module.is_loaded is False
    assert module._recovery_task is None
    assert module._force_cpu_after_timeout is True


def test_trigger_recovery_create_task_failure(monkeypatch):
    module = FakeModule()
    gen = StreamGenerator(module)

    def _boom(coro):
        coro.close()
        raise RuntimeError("cannot create task")

    monkeypatch.setattr(sg.asyncio, "create_task", _boom)
    asyncio.run(gen._trigger_recovery())
    assert module._recovery_task is None
    assert module._force_cpu_after_timeout is True


def test_trigger_recovery_timeout_breaks_loop(monkeypatch):
    """恢复任务长时间不结束 -> 命中 30s 超时 break。"""

    class _NeverLock:
        def acquire(self, timeout=None):
            return False

        def release(self):
            pass

        def locked(self):
            return False

    module = FakeModule()
    module._thread_lock = _NeverLock()
    gen = StreamGenerator(module)
    clock = _FakeClock([0.0, 100.0, 100.0])
    monkeypatch.setattr(sg, "time", SimpleNamespace(time=clock.time))
    asyncio.run(gen._trigger_recovery())
    assert module._force_cpu_after_timeout is True


# --------------------------------------------------------------------------
# _do_generate 生产者线程分支
# --------------------------------------------------------------------------


class _FakeThreadLock:
    """可控线程锁替身。"""

    def __init__(self, locked_flags, acquire_results):
        self._locked_flags = list(locked_flags)
        self._acquire_results = list(acquire_results)
        self.release_calls = 0

    def locked(self):
        if self._locked_flags:
            return self._locked_flags.pop(0)
        return False

    def acquire(self, timeout=None):
        if self._acquire_results:
            return self._acquire_results.pop(0)
        return True

    def release(self):
        self.release_calls += 1


def test_do_generate_recovers_lock_after_force_release(monkeypatch, no_gpu_gate):
    """locked()=True -> 首次 acquire 失败 -> 强制释放 -> 再次 acquire 成功。"""
    module = FakeModule(
        is_gguf=False,
        _thread_lock=_FakeThreadLock([True], [False, True]),
    )
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "TextIteratorStreamer", _FakeStreamer)
    items = _collect(
        gen._do_generate("hi", 8, 0.5, None, 1.1, 0.9, None, 5.0)
    )
    assert items == [{"content": "你"}, {"content": "好"}]


def test_do_generate_lock_timeout_yields_error(monkeypatch, no_gpu_gate):
    module = FakeModule(
        is_gguf=False,
        _thread_lock=_FakeThreadLock([True], [False, False]),
    )
    gen = StreamGenerator(module)
    items = _collect(gen._do_generate("hi", 8, 0.5, None, 1.1, 0.9, None, 1.0))
    assert items[0]["done"] is True
    assert "占用" in items[0]["error"]


def test_do_generate_bad_timeout_value_falls_back(monkeypatch, no_gpu_gate):
    module = FakeModule(is_gguf=False)
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "TextIteratorStreamer", _FakeStreamer)
    items = _collect(
        gen._do_generate("hi", 8, 0.5, None, 1.1, 0.9, None, object())
    )
    assert items == [{"content": "你"}, {"content": "好"}]


def test_do_generate_producer_exception_is_reported(monkeypatch, no_gpu_gate):
    module = FakeModule(is_gguf=True, llama_model=SimpleNamespace())
    gen = StreamGenerator(module)
    items = _collect(gen._do_generate("hi", 8, 0.5, None, 1.1, 0.9, None, 5.0))
    assert items[0]["done"] is True
    assert "create_chat_completion" in items[0]["error"]


# --------------------------------------------------------------------------
# _generate_gguf 分支
# --------------------------------------------------------------------------


def _gguf_module(**over):
    model = _FakeLlamaModel(chunks=[{"choices": [{"delta": {"content": "z"}}]}], n_ctx=2048)
    base = dict(is_gguf=True, llama_model=model, config={"n_gpu_layers": 0})
    base.update(over)
    module = FakeModule(**base)
    return module, model


def test_generate_gguf_clamps_list_and_str_prompts(monkeypatch):
    module, model = _gguf_module()
    gen = StreamGenerator(module)
    puts = []
    gen._generate_gguf("x" * 50000, 8, 0.5, 0.9, None, 1.1, None, puts.append)
    assert puts == [{"content": "z"}]

    puts2 = []
    gen._generate_gguf(
        [{"role": "user", "content": "y" * 50000}], 8, 0.5, 0.9, None, 1.1, None, puts2.append
    )
    assert puts2 == [{"content": "z"}]


def test_generate_gguf_type_error_retry(monkeypatch):
    module, model = _gguf_module()
    model._chat_error_once = TypeError("unexpected keyword argument 'min_p'")
    gen = StreamGenerator(module)
    puts = []
    gen._generate_gguf("hi", 8, 0.5, 0.9, 5, 1.1, 0.1, puts.append)
    assert puts == [{"content": "z"}]
    assert len(model.calls) == 2


def test_generate_gguf_gpu_detection_branches(monkeypatch):
    """覆盖 GPU 检测：cuda 可用 / n_gpu_layers 为 0 的告警。"""
    module, model = _gguf_module(config={"n_gpu_layers": -1})
    model._n_gpu_layers = 0
    gen = StreamGenerator(module)
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch(_FakeCuda(available=True)))
    puts = []
    gen._generate_gguf("hi", 8, 0.5, 0.9, None, 1.1, None, puts.append)
    assert puts == [{"content": "z"}]


def test_generate_gguf_gpu_cuda_unavailable(monkeypatch):
    module, model = _gguf_module(config={"n_gpu_layers": -1})
    model._n_gpu_layers = 8
    gen = StreamGenerator(module)
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch(_FakeCuda(available=False)))
    puts = []
    gen._generate_gguf("hi", 8, 0.5, 0.9, None, 1.1, None, puts.append)
    assert puts == [{"content": "z"}]


def test_generate_gguf_gpu_cuda_check_exception(monkeypatch):
    module, model = _gguf_module(config={"n_gpu_layers": -1})
    model._n_gpu_layers = 8
    gen = StreamGenerator(module)
    monkeypatch.setitem(
        sys.modules, "torch", _FakeTorch(_FakeCuda(available=True, name_raises=True))
    )
    puts = []
    gen._generate_gguf("hi", 8, 0.5, 0.9, None, 1.1, None, puts.append)
    assert puts == [{"content": "z"}]


def test_generate_gguf_model_gpu_layers_raises(monkeypatch):
    module, model = _gguf_module(config={"n_gpu_layers": -1})
    model._n_gpu_layers_raises = True
    gen = StreamGenerator(module)
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch(_FakeCuda(available=True)))
    puts = []
    gen._generate_gguf("hi", 8, 0.5, 0.9, None, 1.1, None, puts.append)
    assert puts == [{"content": "z"}]


def test_generate_gguf_creation_error_reraised(monkeypatch):
    module, model = _gguf_module()
    model._chat_error = ValueError("some other failure")
    gen = StreamGenerator(module)
    with pytest.raises(ValueError):
        gen._generate_gguf("hi", 8, 0.5, 0.9, None, 1.1, None, [].append)


def test_generate_gguf_cuda_backend_error_triggers_cpu_retry(monkeypatch):
    module, model = _gguf_module(config={"n_gpu_layers": -1})
    model._chat_error = RuntimeError("ggml-cuda: cuda error occurred")
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "get_torch", lambda: None)

    def _load_sync(self):
        self.module.llama_model = _FakeLlamaModel()
        return True

    monkeypatch.setattr(
        "core.modules.llm.model_loader.ModelLoader.load_sync", _load_sync
    )
    puts = []
    gen._generate_gguf("hi", 8, 0.5, 0.9, None, 1.1, None, puts.append)
    assert puts == []
    assert module.config["n_gpu_layers"] == 0


def test_generate_gguf_context_window_retry_success(monkeypatch):
    module, model = _gguf_module(config={"n_gpu_layers": 0})
    err = RuntimeError("requested tokens (300) exceed context window of 128")
    model._chat_error_once = err
    gen = StreamGenerator(module)
    puts = []
    gen._generate_gguf("hi", 100, 0.5, 0.9, None, 1.1, None, puts.append)
    assert puts == [{"content": "z"}]
    assert len(model.calls) == 2


def test_generate_gguf_context_window_unparsable_yields_error(monkeypatch):
    module, model = _gguf_module(config={"n_gpu_layers": 0})
    model._chat_error = RuntimeError("requested exceed context window somehow")
    gen = StreamGenerator(module)
    puts = []
    gen._generate_gguf("hi", 100, 0.5, 0.9, None, 1.1, None, puts.append)
    assert puts[0]["done"] is True
    assert "上下文窗口" in puts[0]["error"]


def test_generate_gguf_slow_stream_creation_warning(monkeypatch):
    """stream 创建耗时 >5s 且 GPU 推理 -> 告警分支。"""
    module, model = _gguf_module(config={"n_gpu_layers": -1})
    model._n_gpu_layers = 8
    gen = StreamGenerator(module)
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch(_FakeCuda(available=True)))
    clock = _FakeClock([0.0, 10.0, 10.0, 10.0, 10.0, 10.0])
    monkeypatch.setattr(sg, "time", SimpleNamespace(time=clock.time))
    puts = []
    gen._generate_gguf("hi", 8, 0.5, 0.9, None, 1.1, None, puts.append)
    assert puts == [{"content": "z"}]


# --------------------------------------------------------------------------
# generate：gguf 全链路 + 中断
# --------------------------------------------------------------------------


def test_generate_gguf_full_flow_with_cancellation(monkeypatch, no_gpu_gate):
    """gguf 全链路：消费到 done 后停止，覆盖 generate->_do_generate->_consume_queue。"""
    module, model = _gguf_module(config={"n_gpu_layers": 0})
    module.is_loaded = True
    gen = StreamGenerator(module)

    async def _run():
        out = []
        async for item in gen.generate("你好", max_tokens=16):
            out.append(item)
        return out

    items = asyncio.run(_run())
    assert items == [{"content": "z"}]


# --------------------------------------------------------------------------
# 补充：settings 兜底 / 释放锁异常 / 关闭 loop 的 put
# --------------------------------------------------------------------------


def test_generate_gguf_layers_none_falls_back_to_settings(monkeypatch, no_gpu_gate):
    """config 中 n_gpu_layers 显式为 None 时，回退到 settings.model.n_gpu_layers。"""
    model = _FakeLlamaModel(
        chunks=[{"choices": [{"delta": {"content": "q"}}]}], n_ctx=2048
    )
    module = FakeModule(
        is_loaded=True,
        is_gguf=True,
        config={"n_gpu_layers": None},
        llama_model=model,
    )
    module.settings.model = _model_settings(n_gpu_layers=0)
    gen = StreamGenerator(module)
    items = _collect(gen.generate("hi"))
    assert items == [{"content": "q"}]
    # need_gpu_gate 经 settings 判定为 0 层 -> 未申请 GPU 资源锁
    assert no_gpu_gate.calls == []


def test_generate_with_scheduler_error_without_done_returns(monkeypatch):
    """错误 token 且无 done 字段 -> 走 error 判断直接返回。"""
    module = FakeModule(is_loaded=False)

    class _Scheduler:
        _running = True

        async def submit_llm_task(self, prompt, **kwargs):
            yield {"error": "only-error"}
            yield {"content": "never"}

    items = _run_scheduler(monkeypatch, module, _Scheduler())
    assert items == [{"error": "only-error"}]


class _RaisingReleaseThreadLock:
    """release() 永远抛异常的线程锁替身。"""

    def __init__(self, locked_flags, acquire_results):
        self._locked_flags = list(locked_flags)
        self._acquire_results = list(acquire_results)

    def locked(self):
        if self._locked_flags:
            return self._locked_flags.pop(0)
        return False

    def acquire(self, timeout=None):
        if self._acquire_results:
            return self._acquire_results.pop(0)
        return True

    def release(self):
        raise RuntimeError("release failed")


def test_do_generate_release_failure_is_swallowed(monkeypatch, no_gpu_gate):
    """强制释放锁与 finally 释放锁都抛异常 -> 两个 except 分支被吞掉。"""
    module = FakeModule(
        is_gguf=False,
        _thread_lock=_RaisingReleaseThreadLock([True], [False, True]),
    )
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "TextIteratorStreamer", _FakeStreamer)
    items = _collect(gen._do_generate("hi", 8, 0.5, None, 1.1, 0.9, None, 5.0))
    assert items == [{"content": "你"}, {"content": "好"}]


def test_generate_gguf_n_ctx_raises_falls_back_to_zero():
    """llama_model.n_ctx() 抛异常 -> n_ctx 归零并继续。"""
    model = _FakeLlamaModel(
        chunks=[{"choices": [{"delta": {"content": "n"}}]}], n_ctx_raises=True
    )
    module = FakeModule(is_gguf=True, llama_model=model, config={"n_gpu_layers": 0})
    gen = StreamGenerator(module)
    puts = []
    gen._generate_gguf("hi", 8, 0.5, 0.9, None, 1.1, None, puts.append)
    assert puts == [{"content": "n"}]


class _NoDelAttrModule(FakeModule):
    """del 属性会抛异常的模块替身。"""

    def __delattr__(self, name):
        raise RuntimeError("cannot delete attribute")


def test_cleanup_and_retry_cpu_del_attribute_failure(monkeypatch):
    module = _NoDelAttrModule(llama_model=_FakeLlamaModel(), config={})
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "get_torch", lambda: None)
    monkeypatch.setattr(
        "core.modules.llm.model_loader.ModelLoader.load_sync", lambda self: False
    )
    with pytest.raises(RuntimeError):
        gen._cleanup_and_retry_cpu()
    assert module.llama_model is None


class _BadCacheCuda(_FakeCuda):
    def empty_cache(self):
        raise RuntimeError("empty_cache failed")


def test_cleanup_and_retry_cpu_torch_cache_failure(monkeypatch):
    module = FakeModule(llama_model=_FakeLlamaModel(), config={})
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "get_torch", lambda: _FakeTorch(_BadCacheCuda()))

    def _load_sync(self):
        self.module.llama_model = _FakeLlamaModel()
        return True

    monkeypatch.setattr(
        "core.modules.llm.model_loader.ModelLoader.load_sync", _load_sync
    )
    gen._cleanup_and_retry_cpu()
    assert module.config["n_gpu_layers"] == 0


class _RetryThenReleaseLock:
    """首次 acquire 失败、第二次成功，且 release 抛异常的线程锁替身。"""

    def __init__(self):
        self._acquire_results = [False, True]

    def acquire(self, timeout=None):
        if self._acquire_results:
            return self._acquire_results.pop(0)
        return True

    def release(self):
        raise RuntimeError("release failed")

    def locked(self):
        return False


def test_trigger_recovery_retries_lock_then_releases():
    """恢复流程里 acquire 失败后 sleep 重试，release 异常被吞。"""
    module = FakeModule()
    module._thread_lock = _RetryThenReleaseLock()
    gen = StreamGenerator(module)
    asyncio.run(gen._trigger_recovery())
    assert module.is_loaded is False
    assert module._recovery_task is None
    assert module._force_cpu_after_timeout is True


def test_put_threadsafe_skips_closed_loop(monkeypatch, no_gpu_gate):
    """消费侧提前退出并关闭事件循环后，生产者线程的 put 直接跳过。"""
    gate = threading.Event()
    finished = threading.Event()

    class _GatedStreamer:
        def __init__(self, tokenizer=None, skip_prompt=True, skip_special_tokens=True):
            pass

        def __iter__(self):
            yield "你"
            gate.wait(5.0)
            yield "好"
            finished.set()

    module = FakeModule(is_gguf=False)
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "TextIteratorStreamer", _GatedStreamer)

    async def _run():
        agen = gen._do_generate("hi", 8, 0.5, None, 1.1, 0.9, None, 5.0)
        first = await agen.__anext__()
        await agen.aclose()
        return first

    first = asyncio.run(_run())
    assert first == {"content": "你"}
    # 事件循环已关闭，放行生产者线程，其后续 put 应命中 loop.is_closed() 分支
    gate.set()
    assert finished.wait(5.0)


def test_put_threadsafe_swallows_scheduling_exception(monkeypatch, no_gpu_gate):
    """run_coroutine_threadsafe 抛异常 -> 被 except 吞掉，消费侧走首 token 超时。"""
    module = FakeModule(is_gguf=False)
    gen = StreamGenerator(module)
    monkeypatch.setattr(sg, "TextIteratorStreamer", _FakeStreamer)

    def _boom(coro, loop):
        coro.close()
        raise RuntimeError("loop is not running")

    monkeypatch.setattr(sg.asyncio, "run_coroutine_threadsafe", _boom)
    items = _collect(gen._do_generate("hi", 8, 0.5, None, 1.1, 0.9, None, 0.01))
    assert items[0]["done"] is True


def test_module_import_guard_without_transformers(monkeypatch):
    """transformers 不可用时模块级 ImportError 兜底把 TextIteratorStreamer 置 None。

    这是模块级 import 守卫，只有在 transformers 导入失败时才会命中；
    本环境 transformers 已安装，因此用 sys.modules 屏蔽后 reload 触发。
    测试结束务必恢复（finally 中 reload 回来）。
    """
    import importlib

    monkeypatch.setitem(sys.modules, "transformers", None)
    try:
        importlib.reload(sg)
        assert sg.TextIteratorStreamer is None
    finally:
        monkeypatch.undo()
        importlib.reload(sg)
    assert sg.TextIteratorStreamer is not None
