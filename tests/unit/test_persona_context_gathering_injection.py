"""单元测试：persona prompt 上下文采集的「注入类」函数。

覆盖 get_context_injection / prepare_emotion_context / determine_model_info /
prepare_life_stats / _resolve_peer_names。全部纯 mock：
模块级 ``from X import y`` 的符号 patch 被测模块自身属性；函数体内的惰性 import
则 patch 其来源模块属性。历史记录与记忆均打桩，不触碰任何真实数据目录。
"""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from core.agents.chat_agent_components.persona_system.prompt import context_gathering as m


class _MM:
    """WeightedMemoryManager 最小桩（lock / short_term_memory / weighted_memories）。"""

    def __init__(self, short_term=None, weighted=None, prompts=None):
        self.lock = nullcontext()
        self.short_term_memory = list(short_term or [])
        self.weighted_memories = dict(weighted or {})
        self._prompts = prompts

    def get_important_prompts(self):
        return self._prompts


class _BoomPsutil:
    """任何调用都抛异常的 psutil 替身。"""

    def cpu_percent(self, interval=None):
        raise RuntimeError("cpu boom")

    def virtual_memory(self):
        raise RuntimeError("mem boom")


def _raiser(msg):
    def _boom(*a, **k):
        raise RuntimeError(msg)

    return _boom


def _fix_time(monkeypatch, now):
    monkeypatch.setattr(m, "time", SimpleNamespace(time=lambda: now))


def _isolate(monkeypatch):
    """周边依赖全部失败 + 历史记录返回空 + 把 _MM 认作 WeightedMemoryManager。"""
    monkeypatch.setattr(m, "WeightedMemoryManager", _MM)
    monkeypatch.setattr(m, "get_life_simulation_service", _raiser("life_sim"))
    monkeypatch.setattr(m, "get_weighted_memory_manager", _raiser("mm"))
    monkeypatch.setattr(m, "psutil", _BoomPsutil())
    monkeypatch.setattr("core.emotion.get_emotion_manager", _raiser("emotion"))
    monkeypatch.setattr(
        "core.services.chat_history_store.get_chat_history_store",
        lambda: SimpleNamespace(list_conversation_events=lambda *a, **k: []),
    )


# ------------------------------- get_context_injection ------------------------------- #
def test_context_injection_defaults(monkeypatch):
    """依赖全挂 → 静态默认值；debug 开关以正确模块名查询。"""
    _isolate(monkeypatch)
    seen = []
    monkeypatch.setattr(m, "is_debug_enabled", lambda name: seen.append(name) or False)

    ctx = m.get_context_injection("u1")

    assert ctx == {
        "user_physiology": "", "life_sim_state": {}, "emotion": {}, "cpu_temp": 45,
        "ram_usage": 50, "vision_summary": "视觉传感器正常", "last_conversation_seconds": None,
    }
    assert seen == ["context_gathering"]


def test_context_injection_debug_log(monkeypatch):
    """debug 打开时记录「获取最后对话时间失败」。"""
    _isolate(monkeypatch)
    monkeypatch.setattr(m, "is_debug_enabled", lambda name: True)
    logs = []
    monkeypatch.setattr(
        m, "logger",
        SimpleNamespace(info=lambda msg, *a, **k: logs.append(msg), warning=lambda *a, **k: None),
    )

    ctx = m.get_context_injection("u1")

    assert ctx["last_conversation_seconds"] is None
    assert len(logs) == 1 and "获取最后对话时间失败" in logs[0]


def test_context_injection_happy_deps(monkeypatch):
    """生活模拟 / 情绪 / psutil 正常返回时写入对应字段。"""
    _isolate(monkeypatch)
    state = {"vision_summary": "夜视", "life": {"hunger": 10}}
    monkeypatch.setattr(
        m, "get_life_simulation_service", lambda: SimpleNamespace(get_state=lambda: state)
    )
    payload = {"primary_emotion": "joy"}
    monkeypatch.setattr(
        "core.emotion.get_emotion_manager",
        lambda *a, **k: SimpleNamespace(get_effective_payload=lambda uid: payload),
    )
    monkeypatch.setattr(
        m, "psutil",
        SimpleNamespace(cpu_percent=lambda interval=None: 20.0,
                        virtual_memory=lambda: SimpleNamespace(percent=33.0)),
    )

    ctx = m.get_context_injection("u", memory_manager=_MM())

    assert (ctx["life_sim_state"], ctx["vision_summary"], ctx["emotion"],
            ctx["cpu_temp"], ctx["ram_usage"]) == (state, "夜视", payload, 50.0, 33.0)


@pytest.mark.parametrize("state", [None, {"life": {}}], ids=["none", "no-vision-key"])
def test_context_injection_vision_fallback(monkeypatch, state):
    """生活模拟状态非 dict 或缺 vision_summary 时回退默认文案。"""
    _isolate(monkeypatch)
    monkeypatch.setattr(
        m, "get_life_simulation_service", lambda: SimpleNamespace(get_state=lambda: state)
    )

    ctx = m.get_context_injection("u", memory_manager=_MM())

    assert ctx["life_sim_state"] == state
    assert ctx["vision_summary"] == "视觉传感器正常"


def _rec(**kw):
    rec = {
        "source": "device", "is_stale": False,
        "metrics": {"heart_rate_bpm": 72, "spo2_percent": 98,
                    "sleep_hours_last_night": 7.5, "stress_level": "低"},
        "flags": {"urgent_needs": ["疲劳"]},
    }
    rec.update(kw)
    return rec


def _phys(monkeypatch, rec):
    monkeypatch.setattr(
        "core.services.user_physiology.service.get_user_physiology_service",
        lambda: SimpleNamespace(get_latest=lambda uid: rec),
    )


def test_user_health_full(monkeypatch):
    """有效记录拼接完整健康字符串（含预警）。"""
    _isolate(monkeypatch)
    _phys(monkeypatch, _rec())

    ctx = m.get_context_injection("u", include_user_health=True)

    assert ctx["user_physiology"] == (
        "\n- 用户健康状态: 心率:72bpm, 血氧:98%, 昨晚睡眠:7.5h, 压力:低, 预警:疲劳"
    )


@pytest.mark.parametrize(
    "rec",
    [_rec(is_stale=True), _rec(source="tests"), _rec(source="Debug"), None],
    ids=["stale", "test-src", "debug-src", "none"],
)
def test_user_health_skipped(monkeypatch, rec):
    """过期 / 测试来源 / 非 dict 记录都不注入。"""
    _isolate(monkeypatch)
    _phys(monkeypatch, rec)

    assert m.get_context_injection("u", include_user_health=True)["user_physiology"] == ""


def test_user_health_empty_metrics(monkeypatch):
    """有记录但 metrics/flags 为空 → u_parts 为空，不注入。"""
    _isolate(monkeypatch)
    _phys(monkeypatch, _rec(metrics={}, flags={}))

    assert m.get_context_injection("u", include_user_health=True)["user_physiology"] == ""


def test_user_health_service_raises(monkeypatch):
    """生理服务抛异常时静默跳过。"""
    _isolate(monkeypatch)
    monkeypatch.setattr(
        "core.services.user_physiology.service.get_user_physiology_service", _raiser("phys")
    )

    ctx = m.get_context_injection("u", include_user_health=True)

    assert (ctx["user_physiology"], ctx["cpu_temp"]) == ("", 45)


def test_memory_manager_elapsed(monkeypatch):
    """传 memory_manager：逆序取最后有效时间戳，跳过 falsy / 非数值。"""
    _isolate(monkeypatch)
    _fix_time(monkeypatch, 1000.0)
    mm = _MM(short_term=[{"timestamp": 111.0}, {"timestamp": None}, {"timestamp": "bad"}])

    assert m.get_context_injection("u", memory_manager=mm)["last_conversation_seconds"] == 889


def test_memory_manager_zero_elapsed(monkeypatch):
    """时间戳等于当前时间时写入 0。"""
    _isolate(monkeypatch)
    _fix_time(monkeypatch, 700.0)

    ctx = m.get_context_injection("u", memory_manager=_MM(short_term=[{"timestamp": 700.0}]))

    assert ctx["last_conversation_seconds"] == 0


def test_memory_manager_factory_path(monkeypatch):
    """未传 memory_manager → 走工厂单例且 ensure_loaded=False。"""
    _isolate(monkeypatch)
    _fix_time(monkeypatch, 500.0)
    got = {}

    def _factory(uid, ensure_loaded=True):
        got.update(uid=uid, ensure_loaded=ensure_loaded)
        return _MM(short_term=[{"timestamp": 200.0}])

    monkeypatch.setattr(m, "get_weighted_memory_manager", _factory)

    assert m.get_context_injection("u2")["last_conversation_seconds"] == 300
    assert got == {"uid": "u2", "ensure_loaded": False}


def test_history_store_fallback(monkeypatch):
    """记忆无时间戳时回退历史记录，并跳过非 dict / timestamp<=0 的事件。"""
    _isolate(monkeypatch)
    _fix_time(monkeypatch, 900.0)
    seen = {}

    def _list(cid, **kw):
        seen.update(cid=cid, kw=kw)
        return [{"timestamp": 500.0}, {"timestamp": 0}, "not-a-dict"]

    monkeypatch.setattr(
        "core.services.chat_history_store.get_chat_history_store",
        lambda: SimpleNamespace(list_conversation_events=_list),
    )

    ctx = m.get_context_injection("u3", memory_manager=_MM())

    assert seen == {"cid": "u3", "kw": {"limit": 5, "roles": ["user", "assistant"]}}
    assert ctx["last_conversation_seconds"] == 400


def test_history_store_raises(monkeypatch):
    """历史记录查询抛异常时保持 None。"""
    _isolate(monkeypatch)
    monkeypatch.setattr(
        "core.services.chat_history_store.get_chat_history_store", _raiser("store")
    )

    assert m.get_context_injection("u", memory_manager=_MM())["last_conversation_seconds"] is None


# ------------------------------ prepare_emotion_context ------------------------------ #
def test_prepare_emotion_context_defaults():
    """空输入 / 纯空白主情绪 / 非 dict 子情绪 → 默认值。"""
    assert m.prepare_emotion_context({}) == ("neutral", 0, 0, "{}")
    assert m.prepare_emotion_context({"emotion": {"primary_emotion": "   "}})[0] == "neutral"
    assert m.prepare_emotion_context({"emotion": {"sub_emotions": ["a"]}})[3] == "{}"


def test_prepare_emotion_context_full():
    """完整 payload：百分比取整 + 子情绪 JSON 排序输出。"""
    result = m.prepare_emotion_context({
        "emotion": {"primary_emotion": "happy", "intensity": 0.5, "confidence": 0.8,
                    "sub_emotions": {"b": 2, "a": 1}},
    })

    assert result == ("happy", 50, 80, '{"a": 1, "b": 2}')


def test_prepare_emotion_context_bad_numbers():
    """intensity / confidence 非法时各自归零。"""
    result = m.prepare_emotion_context({"emotion": {"intensity": "abc", "confidence": "xyz"}})

    assert (result[1], result[2]) == (0, 0)


def test_prepare_emotion_context_json_dumps_raises(monkeypatch):
    """json.dumps 抛异常时子情绪 JSON 保持空串。"""
    monkeypatch.setattr(m, "json", SimpleNamespace(dumps=_raiser("json")))

    assert m.prepare_emotion_context({"emotion": {"sub_emotions": {"a": 1}}})[3] == ""


def test_prepare_emotion_context_sub_get_raises():
    """payload.get('sub_emotions') 抛异常时保持空 JSON。"""

    class _P(dict):
        def get(self, key, default=None):
            if key == "sub_emotions":
                raise RuntimeError("boom")
            return super().get(key, default)

    assert m.prepare_emotion_context({"emotion": _P()}) == ("neutral", 0, 0, "{}")


# ------------------------------- determine_model_info -------------------------------- #
def test_determine_model_info_defaults():
    """无 llm_module / llm_module 为 None / 无 getter → 全默认。"""
    agents = [
        SimpleNamespace(),
        SimpleNamespace(llm_module=None),
        SimpleNamespace(llm_module=SimpleNamespace()),
    ]
    for agent in agents:
        assert m.determine_model_info(agent) == ("", False, False, None)


@pytest.mark.parametrize(
    "name", ["cloud:gpt-4o", "My-CLOUD:qwen", "cloud:x.gguf"], ids=["prefix", "mixed-case", "cloud-wins"]
)
def test_determine_model_info_cloud(name):
    """含 cloud: 即云端模型，且不解析 prompt 预算。"""
    agent = SimpleNamespace(
        llm_module=SimpleNamespace(get_current_model_name=lambda n=name: n)
    )

    assert m.determine_model_info(agent) == (name, True, False, None)


def test_determine_model_info_none_or_raise():
    """getter 返回 None / 抛异常 → 归一为空串。"""
    a1 = SimpleNamespace(llm_module=SimpleNamespace(get_current_model_name=lambda: None))
    a2 = SimpleNamespace(llm_module=SimpleNamespace(get_current_model_name=_raiser("m")))

    assert m.determine_model_info(a1) == ("", False, False, None)
    assert m.determine_model_info(a2) == ("", False, False, None)


@pytest.mark.parametrize(
    "n_ctx,budget", [(2000, 2400), (500, 1200), (10000, 3500)], ids=["mid", "clamp-low", "clamp-high"]
)
def test_determine_model_info_gguf_budget(monkeypatch, n_ctx, budget):
    """本地 gguf：按 n_ctx*1.2 夹逼到 [1200, 3500]。"""
    monkeypatch.setattr(
        "config.integrated_config.get_settings",
        lambda: SimpleNamespace(model=SimpleNamespace(n_ctx=n_ctx)),
    )
    agent = SimpleNamespace(llm_module=SimpleNamespace(get_current_model_name=lambda: "q.gguf"))

    assert m.determine_model_info(agent) == ("q.gguf", False, True, budget)


def test_determine_model_info_gguf_zero_and_settings_raises(monkeypatch):
    """n_ctx=0 不设预算；读取配置失败回退 2500。"""
    agent = SimpleNamespace(llm_module=SimpleNamespace(get_current_model_name=lambda: "q.gguf"))
    monkeypatch.setattr(
        "config.integrated_config.get_settings",
        lambda: SimpleNamespace(model=SimpleNamespace(n_ctx=0)),
    )
    assert m.determine_model_info(agent) == ("q.gguf", False, True, None)

    monkeypatch.setattr("config.integrated_config.get_settings", _raiser("cfg"))
    assert m.determine_model_info(agent) == ("q.gguf", False, True, 2500)


# --------------------------------- prepare_life_stats -------------------------------- #
def test_prepare_life_stats():
    """空输入 / 原样返回子 dict / 子字段非 dict 回退。"""
    assert m.prepare_life_stats({}) == ({}, {}, {})
    life, immune, bio = {"a": 1}, {"b": 2}, {"c": 3}
    got = m.prepare_life_stats({"life": life, "immune": immune, "bio": bio})
    assert got[0] is life and got[1] is immune and got[2] is bio
    assert m.prepare_life_stats({"life": ["x"], "immune": None, "bio": "s"}) == ({}, {}, {})


# --------------------------------- _resolve_peer_names ------------------------------- #
def test_resolve_peer_names_empty_input():
    """None / 空串 / 纯空白 → 空列表。"""
    for value in (None, "", "   "):
        assert m._resolve_peer_names(value) == []


def test_resolve_peer_names_real_registry():
    """权威注册表：aveline↔ling 互为 peer；ye/yeye/rushuang 无 peer。"""
    assert m._resolve_peer_names("core_aveline.json") == ["Ling"]
    assert m._resolve_peer_names("core_ling.json") == ["Aveline"]
    for fn in ("core_ye.json", "qq/Yeye.json", "sensitive/Frost.json"):
        assert m._resolve_peer_names(fn) == []


def test_resolve_peer_names_not_found_or_unregistered(monkeypatch):
    """匹配不到画像 / 画像 role_id 未注册 → 空列表。"""
    p = "core.services.dual_role.personas."
    monkeypatch.setattr(p + "find_persona_by_filename_hint", lambda fn: None)
    assert m._resolve_peer_names("x.json") == []

    monkeypatch.setattr(p + "find_persona_by_filename_hint", lambda fn: SimpleNamespace(role_id="ghost"))
    monkeypatch.setattr(p + "get_persona", lambda rid: None)
    assert m._resolve_peer_names("g.json") == []


def test_resolve_peer_names_skip_blank_and_dedupe(monkeypatch):
    """空中文名跳过；重复名字去重且保持首次出现顺序。"""
    p = "core.services.dual_role.personas."
    monkeypatch.setattr(p + "find_persona_by_filename_hint", lambda fn: SimpleNamespace(role_id="aveline"))
    monkeypatch.setattr(p + "get_persona", lambda rid: SimpleNamespace(role_id=rid))
    monkeypatch.setattr(p + "get_peer_role_ids", lambda rid: ["ling", "blank", "ling", "yeye"])
    names = {"ling": {"cn_name": "Ling"}, "blank": {"cn_name": ""}, "yeye": {"cn_name": "Coco"}}
    monkeypatch.setattr(p + "get_role_names", lambda rid: names.get(rid, {}))

    assert m._resolve_peer_names("core_aveline.json") == ["Ling", "Coco"]


def test_resolve_peer_names_exception(monkeypatch):
    """解析抛异常 → 记录 warning 并返回空列表。"""
    monkeypatch.setattr(
        "core.services.dual_role.personas.find_persona_by_filename_hint", _raiser("boom")
    )
    seen = []
    monkeypatch.setattr(
        m, "logger",
        SimpleNamespace(warning=lambda *a, **k: seen.append(a), info=lambda *a, **k: None),
    )

    assert m._resolve_peer_names("core_aveline.json") == []
    assert len(seen) == 1 and "解析互聊对象名失败" in seen[0][0]
