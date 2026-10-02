#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``core/modules/forge_client.py`` 业务操作层单元测试。

覆盖：``resolve_model_checkpoint`` / ``get_loras`` / ``switch_model`` /
``generate_images`` / ``generate``。

约束：``requests`` 必须 patch **被测模块自身**（``forge_client.requests``），
禁止真实 HTTP；``time`` 用受控时钟替换，不真 sleep；不写磁盘。
"""

from __future__ import annotations

import base64

import pytest

import core.modules.forge_client as fc
from core.modules.forge_client import ForgeClient

# ------------------------------- 替身工具 ------------------------------- #
class FakeClock:
    """受控时钟：完整替代被测模块内的 ``time``。"""

    def __init__(self, now: float = 1000.0):
        self.now = float(now)
        self.sleeps = []

    def time(self):
        return self.now

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += float(seconds)


class FakeResponse:
    """假 HTTP 响应。"""

    def __init__(self, status_code=200, json_data=None, text="", content=b""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.content = content

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeRequests:
    """``requests`` 模块替身：按调用顺序弹出预设结果并记录调用。"""

    def __init__(self, get_results=None, post_results=None):
        self._get_results = list(get_results or [])
        self._post_results = list(post_results or [])
        self.get_calls = []
        self.post_calls = []

    @staticmethod
    def _pop(results):
        if not results:
            return FakeResponse()
        item = results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item() if callable(item) else item

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self._pop(self._get_results)

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self._pop(self._post_results)


def _b64(text: str = "img") -> str:
    """构造合法 base64 字符串。"""
    return base64.b64encode(text.encode()).decode()


def _raiser(exc: Exception):
    """返回一个「调用即抛 exc」的替身函数。"""
    def _f(*args, **kwargs):
        raise exc
    return _f


def _ok(payload=None):
    """构造 200 + 单图响应。"""
    return FakeResponse(200, payload if payload is not None else {"images": [_b64("x")]})

# -------------------------------- fixtures ------------------------------- #
@pytest.fixture()
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(fc, "time", c)
    return c


@pytest.fixture()
def fake_requests(monkeypatch):
    def _install(get_results=None, post_results=None):
        fr = FakeRequests(get_results, post_results)
        monkeypatch.setattr(fc, "requests", fr)
        return fr

    return _install


@pytest.fixture()
def client(clock):
    return ForgeClient()


@pytest.fixture()
def gen_client(clock, monkeypatch):
    """generate_images 专用：把 switch_model 替换为记录型替身。"""
    c = ForgeClient()
    calls = []
    monkeypatch.setattr(c, "switch_model", lambda m: (calls.append(m), True)[1])
    c.switch_calls = calls
    return c

# ------------------------- resolve_model_checkpoint ---------------------- #
def test_resolve_empty(client):
    """空 model_id → None。"""
    assert client.resolve_model_checkpoint("") is None
    assert client.resolve_model_checkpoint(None) is None


def test_resolve_mapped_and_direct(client):
    """命中 model_map 或直接传 .safetensors → 原样/映射返回，不查列表。"""
    assert client.resolve_model_checkpoint("sd1.5") == client.model_map["sd1.5"]
    assert client.resolve_model_checkpoint("C\\My.safetensors") == "C\\My.safetensors"


def test_resolve_no_models(client, monkeypatch):
    """无模型列表 → 返回 resolved 原值。"""
    monkeypatch.setattr(client, "_get_models_cached", lambda *a, **k: [])
    assert client.resolve_model_checkpoint("unknown") == "unknown"


def test_resolve_match_model_name(client, monkeypatch):
    """按 model_name 精确匹配 → 返回 title。"""
    models = [{"title": "Title X", "model_name": "unknown", "filename": "f"}]
    monkeypatch.setattr(client, "_get_models_cached", lambda *a, **k: models)
    assert client.resolve_model_checkpoint("unknown") == "Title X"


def test_resolve_match_title_substring(client, monkeypatch):
    """按 title 子串匹配 → 返回 title。"""
    models = [{"title": "My Cool Model", "model_name": "m", "filename": "f"}]
    monkeypatch.setattr(client, "_get_models_cached", lambda *a, **k: models)
    assert client.resolve_model_checkpoint("cool") == "My Cool Model"


def test_resolve_filename_substring_title_empty(client, monkeypatch):
    """filename 子串匹配但 title 为空 → 回退 resolved。"""
    models = [{"title": "", "model_name": "m", "filename": "path/abcXYZ"}]
    monkeypatch.setattr(client, "_get_models_cached", lambda *a, **k: models)
    assert client.resolve_model_checkpoint("abcxyz") == "abcxyz"


def test_resolve_no_match_and_missing_fields(client, monkeypatch):
    """列表非空但无匹配 / 列表项缺字段 → resolved 原值。"""
    monkeypatch.setattr(
        client, "_get_models_cached", lambda *a, **k: [{"title": "t", "model_name": "m"}]
    )
    assert client.resolve_model_checkpoint("zzz") == "zzz"
    monkeypatch.setattr(client, "_get_models_cached", lambda *a, **k: [{}])
    assert client.resolve_model_checkpoint("zzz") == "zzz"

# -------------------------------- get_loras ------------------------------ #
def test_get_loras_ok(client, fake_requests):
    """200 → 返回列表。"""
    loras = [{"name": "L"}]
    fr = fake_requests(get_results=[FakeResponse(200, loras)])
    assert client.get_loras() == loras
    assert fr.get_calls[0][0].endswith("/sdapi/v1/loras")


@pytest.mark.parametrize(
    "result", [FakeResponse(500, text="x"), ConnectionError("Cannot connect"), ValueError("bad")]
)
def test_get_loras_error(client, fake_requests, result):
    """非 200 / 连接错误 / 其他异常 → []。"""
    fake_requests(get_results=[result])
    assert client.get_loras() == []
    if isinstance(result, ConnectionError):
        assert client._last_unavailable_log_ts == 1000.0

# ------------------------------- switch_model ---------------------------- #
def test_switch_model_already_loaded(client, monkeypatch):
    """目标已在当前模型名中 → 直接 True，不发请求。"""
    target = "SD1.5\\chilloutmix_NiPrunedFp32Fix.safetensors"
    monkeypatch.setattr(client, "resolve_model_checkpoint", lambda m: target)
    monkeypatch.setattr(client, "_get_current_model_filename", lambda: target)
    assert client.switch_model("sd1.5") is True
    assert client.current_model == "sd1.5"
    assert client._last_loaded_checkpoint == target


def test_switch_model_success(client, clock, fake_requests, monkeypatch):
    """切换成功（200）→ True，更新状态并 sleep 1 秒。"""
    monkeypatch.setattr(client, "resolve_model_checkpoint", lambda m: "new.safetensors")
    monkeypatch.setattr(client, "_get_current_model_filename", lambda: "old.safetensors")
    fr = fake_requests(post_results=[FakeResponse(200)])
    assert client.switch_model("sd1.5") is True
    assert client.current_model == "sd1.5"
    assert client._last_loaded_checkpoint == "new.safetensors"
    assert clock.sleeps == [1]
    assert fr.post_calls[0][0].endswith("/sdapi/v1/options")
    assert fr.post_calls[0][1]["json"] == {"sd_model_checkpoint": "new.safetensors"}


@pytest.mark.parametrize(
    "result", [FakeResponse(500, text="bad"), ConnectionError("Cannot connect")]
)
def test_switch_model_failure(client, fake_requests, monkeypatch, result):
    """非 200 / 异常 → False。"""
    monkeypatch.setattr(client, "resolve_model_checkpoint", lambda m: "new.safetensors")
    monkeypatch.setattr(client, "_get_current_model_filename", lambda: "old.safetensors")
    fake_requests(post_results=[result])
    assert client.switch_model("sd1.5") is False

# --------------------- generate_images：成功 / 参数分支 ------------------ #
def test_generate_images_success_basic(gen_client, fake_requests):
    """sd1.5 默认参数 + 单图成功。"""
    fr = fake_requests(post_results=[FakeResponse(200, {"images": [_b64("hello")]})])
    out = gen_client.generate_images("a cat")
    assert out == [b"hello"]
    assert gen_client.switch_calls == ["sd1.5"]
    assert fr.post_calls[0][0].endswith("/sdapi/v1/txt2img")
    payload = fr.post_calls[0][1]["json"]
    assert payload["prompt"] == "a cat"
    assert (payload["steps"], payload["width"], payload["height"]) == (20, 1024, 1024)
    assert payload["cfg_scale"] == 7
    assert payload["restore_faces"] is False
    assert payload["sampler_name"] == "DPM++ 2M Karras"
    assert payload["seed"] == -1
    assert (payload["batch_size"], payload["n_iter"]) == (1, 1)
    assert payload["override_settings"]["sd_vae"] == gen_client.vae_map["anime"]
    assert fr.post_calls[0][1]["timeout"] == (10, 120.0)


@pytest.mark.parametrize("model_type", ["sdxl", "pony"])
def test_generate_images_sdxl_defaults(gen_client, fake_requests, model_type):
    """sdxl/pony 默认 steps=25，且不注入 SD1.5 的 VAE override。"""
    fr = fake_requests(post_results=[_ok()])
    assert gen_client.generate_images("p", model_type=model_type) == [b"x"]
    payload = fr.post_calls[0][1]["json"]
    assert payload["steps"] == 25
    assert payload["cfg_scale"] == 7
    assert "override_settings" not in payload


def test_generate_images_explicit_params(gen_client, fake_requests):
    """显式参数覆盖默认值；None 可选字段被跳过；restore_faces 强制 False。"""
    fr = fake_requests(post_results=[_ok()])
    gen_client.generate_images(
        "p", model_type="sd1.5", width=512, height=768, steps=30, cfg_scale=5,
        restore_faces=True, negative_prompt="bad", seed=42, sampler_name="Euler",
        scheduler="Karras", enable_hr=True, hr_scale=None, script_name="x",
    )
    payload = fr.post_calls[0][1]["json"]
    assert (payload["width"], payload["height"], payload["steps"]) == (512, 768, 30)
    assert payload["cfg_scale"] == 5
    assert payload["restore_faces"] is False
    assert payload["negative_prompt"] == "bad"
    assert payload["seed"] == 42
    assert payload["sampler_name"] == "Euler"
    assert payload["scheduler"] == "Karras"
    assert payload["enable_hr"] is True
    assert "hr_scale" not in payload
    assert payload["script_name"] == "x"


@pytest.mark.parametrize("bs", [None, 0, "notint", 9])
def test_generate_images_batch_size(gen_client, fake_requests, bs):
    """batch_size：None/非法/越界均归一为 1（num_images 恒为 1）。"""
    fr = fake_requests(post_results=[_ok()])
    gen_client.generate_images("p", batch_size=bs)
    assert fr.post_calls[0][1]["json"]["batch_size"] == 1


def test_generate_images_num_images_param_ignored(gen_client, fake_requests):
    """缺陷记录：num_images 命名参数被内部 ``kwargs.pop`` 覆盖，实际恒为 1。"""
    fr = fake_requests(post_results=[_ok({"images": [_b64("a"), _b64("b"), _b64("c")]})])
    out = gen_client.generate_images("p", num_images=3)
    assert len(out) == 1
    assert fr.post_calls[0][1]["json"]["n_iter"] == 1

# --------------------- generate_images：图片解码分支 --------------------- #
def test_generate_images_decode_dict_and_datauri(gen_client, fake_requests):
    """dict(data/image/base64) 与 data-uri 字符串均可解码。"""
    data_uri = "data:image/png;base64," + _b64("png")
    fake_requests(
        post_results=[
            _ok({"images": [{"data": _b64("d")}, {"image": _b64("i")},
                            {"base64": _b64("b")}, data_uri]})
        ]
    )
    assert gen_client.generate_images("p") == [b"d"]


def test_generate_images_skip_invalid_entries(gen_client, fake_requests):
    """非法条目（空 dict / 空串 / 非字符串）被跳过。"""
    fake_requests(post_results=[_ok({"images": [{}, "", 123, _b64("ok")]})])
    assert gen_client.generate_images("p") == [b"ok"]

# --------------------- generate_images：失败 / 重试 / 异常 --------------- #
@pytest.mark.parametrize(
    "resp",
    [
        FakeResponse(400, text="bad request"),
        FakeResponse(500, text="internal error"),
        FakeResponse(200, {"images": []}),
        FakeResponse(200, {"images": "nope"}),
        FakeResponse(200, {"images": [123, ""]}),
    ],
)
def test_generate_images_failures(gen_client, fake_requests, resp):
    """4xx / 5xx 非断管 / 空图 / 非列表 / 全非法 → RuntimeError。"""
    fake_requests(post_results=[resp])
    with pytest.raises(RuntimeError) as ei:
        gen_client.generate_images("p")
    assert "Forge generation failed" in str(ei.value)


def test_generate_images_win_pipe_retry_success(gen_client, clock, fake_requests):
    """WinError233 → 卸载 + 重试成功（重试图片同样支持 dict / data-uri）。"""
    data_uri = "data:image/png;base64," + _b64("png")
    fr = fake_requests(
        post_results=[
            FakeResponse(500, text="[WinError 233] 管道断裂"),
            FakeResponse(200),
            _ok({"images": [{"data": _b64("recovered")}, data_uri]}),
        ]
    )
    assert gen_client.generate_images("p") == [b"recovered"]
    urls = [c[0] for c in fr.post_calls]
    assert urls[0].endswith("/sdapi/v1/txt2img")
    assert urls[1].endswith("/sdapi/v1/unload-checkpoint")
    assert urls[2].endswith("/sdapi/v1/txt2img")
    assert clock.sleeps == [1.0]
    assert gen_client.switch_calls == ["sd1.5", "sd1.5"]


@pytest.mark.parametrize(
    "retry", [FakeResponse(200, {"images": []}), ConnectionError("Cannot connect")]
)
def test_generate_images_win_pipe_retry_failed(gen_client, fake_requests, retry):
    """WinError233 重试无图 / 重试抛异常 → 抛 WinError233 RuntimeError。"""
    fake_requests(
        post_results=[FakeResponse(500, text="[WinError 233] broken"), FakeResponse(200), retry]
    )
    with pytest.raises(RuntimeError) as ei:
        gen_client.generate_images("p")
    assert "WinError 233" in str(ei.value)


def test_generate_images_win_pipe_recovery_hooks_raise(
    gen_client, clock, fake_requests, monkeypatch
):
    """自恢复钩子（unload/sleep/switch）全部抛错也要被吞掉。"""
    monkeypatch.setattr(gen_client, "unload_model", _raiser(RuntimeError("u")))
    state = {"n": 0}

    def _switch(_m):
        state["n"] += 1
        if state["n"] >= 2:
            raise RuntimeError("s")
        return True

    monkeypatch.setattr(gen_client, "switch_model", _switch)
    monkeypatch.setattr(clock, "sleep", _raiser(RuntimeError("sl")))
    fake_requests(
        post_results=[FakeResponse(500, text="[WinError 233] broken"), FakeResponse(200, {"images": []})]
    )
    with pytest.raises(RuntimeError) as ei:
        gen_client.generate_images("p")
    assert "WinError 233" in str(ei.value)


def test_generate_images_connection_error(gen_client, fake_requests):
    """连接错误 → 记录不可用并抛 RuntimeError。"""
    fake_requests(post_results=[ConnectionError("Cannot connect to Forge")])
    with pytest.raises(RuntimeError) as ei:
        gen_client.generate_images("p")
    assert "Forge connection error" in str(ei.value)
    assert gen_client._last_unavailable_log_ts == 1000.0


def test_generate_images_unexpected_error(gen_client, fake_requests):
    """非连接类异常 → 同样包成 RuntimeError。"""
    fake_requests(post_results=[ValueError("boom")])
    with pytest.raises(RuntimeError) as ei:
        gen_client.generate_images("p")
    assert "Forge connection error" in str(ei.value)

# -------------- generate_images：timeout / override / LoRA --------------- #
@pytest.mark.parametrize("rt,expected", [(5, (10, 5.0)), ("abc", (10, 120.0)), (None, (10, 120.0))])
def test_generate_images_request_timeout(gen_client, fake_requests, rt, expected):
    """request_timeout：数值透传，非法/未给回退 120.0。"""
    fr = fake_requests(post_results=[_ok()])
    gen_client.generate_images("p", request_timeout=rt)
    assert fr.post_calls[0][1]["timeout"] == expected


def test_generate_images_override_settings_respected(gen_client, fake_requests):
    """已提供 override_settings.sd_vae → 不被默认 VAE 覆盖。"""
    fr = fake_requests(post_results=[_ok()])
    gen_client.generate_images("p", override_settings={"sd_vae": "Custom"})
    assert fr.post_calls[0][1]["json"]["override_settings"] == {"sd_vae": "Custom"}


def test_generate_images_explicit_sd_vae(gen_client, fake_requests):
    """显式 sd_vae 优先于默认 anime VAE。"""
    fr = fake_requests(post_results=[_ok()])
    gen_client.generate_images("p", sd_vae="MyVAE")
    assert fr.post_calls[0][1]["json"]["override_settings"]["sd_vae"] == "MyVAE"


def test_generate_images_lora_name_backslash(gen_client, fake_requests):
    """lora_name 中的 / 被替换为 \\ 并写入 prompt。"""
    fr = fake_requests(post_results=[_ok()])
    gen_client.generate_images("p", lora_name="sub/dir/lora")
    assert "<lora:sub\\dir\\lora:0.8>" in fr.post_calls[0][1]["json"]["prompt"]


def test_generate_images_loras_dict(gen_client, fake_requests):
    """loras 传 dict → 自动包成单元素列表。"""
    fr = fake_requests(post_results=[_ok()])
    gen_client.generate_images("p", loras={"name": "L1", "weight": 0.5})
    assert "<lora:L1:0.5>" in fr.post_calls[0][1]["json"]["prompt"]


def test_generate_images_loras_not_list(gen_client, fake_requests):
    """loras 非 list/dict → 忽略。"""
    fr = fake_requests(post_results=[_ok()])
    gen_client.generate_images("p", loras="oops")
    assert "<lora:" not in fr.post_calls[0][1]["json"]["prompt"]


def test_generate_images_loras_skip_invalid(gen_client, fake_requests):
    """非法 LoRA 条目被跳过；权重非法回退 lora_weight。"""
    fr = fake_requests(post_results=[_ok()])
    gen_client.generate_images(
        "p", loras=["notdict", {"no": "name"}, {"name": "L", "weight": "bad"}, {"name": "M"}]
    )
    prompt = fr.post_calls[0][1]["json"]["prompt"]
    assert "<lora:L:0.8>" in prompt
    assert "<lora:M:0.8>" in prompt


def test_generate_images_sdxl_sd15_lora_warning(gen_client, fake_requests):
    """SDXL 模型 + SD1.5 LoRA → 记 warning 但仍拼接 prompt。"""
    fr = fake_requests(post_results=[_ok()])
    gen_client.generate_images("p", model_type="sdxl", loras=[{"name": "sd1.5_style"}])
    assert "<lora:sd1.5_style:0.8>" in fr.post_calls[0][1]["json"]["prompt"]

# --------------------------------- generate ------------------------------ #
@pytest.mark.parametrize("ret,expected", [([b"one", b"two"], b"one"), ([], None), (None, None)])
def test_generate_return(monkeypatch, clock, ret, expected):
    """generate：取首图 / 空或非列表返回 None。"""
    c = ForgeClient()
    monkeypatch.setattr(c, "generate_images", lambda *a, **k: ret)
    assert c.generate("p") == expected


def test_generate_passes_through_kwargs(monkeypatch, clock):
    """参数正确透传给 generate_images（num_images 固定为 1）。"""
    c = ForgeClient()
    captured = {}

    def _fake(prompt, **kwargs):
        captured["prompt"] = prompt
        captured.update(kwargs)
        return [b"x"]

    monkeypatch.setattr(c, "generate_images", _fake)
    out = c.generate(
        "hello", model_type="sdxl", lora_name="l", lora_weight=0.3, sd_vae="v", steps=9
    )
    assert out == b"x"
    assert captured["prompt"] == "hello"
    assert captured["model_type"] == "sdxl"
    assert (captured["lora_name"], captured["lora_weight"], captured["sd_vae"]) == ("l", 0.3, "v")
    assert (captured["num_images"], captured["steps"]) == (1, 9)
