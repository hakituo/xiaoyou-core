"""单元测试：persona prompt 上下文采集的「prompt 片段构建」函数。

覆盖 get_tool_injection / get_instruction_injection /
get_study_folder_history_injection / build_food_context_text /
get_inventory_and_digestion_summary。全部纯 mock，时间通过 patch 被测模块的
``time`` 固定，保证不依赖真实时间流逝、可稳定复跑。
"""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from core.agents.chat_agent_components.persona_system.prompt import context_gathering as m


class _MM:
    """WeightedMemoryManager 最小桩。"""

    def __init__(self, weighted=None, prompts=None):
        self.lock = nullcontext()
        self.weighted_memories = dict(weighted or {})
        self._prompts = prompts

    def get_important_prompts(self):
        return self._prompts


class _MMNoPrompts:
    """不提供 get_important_prompts，用于覆盖 hasattr 为假的分支。"""

    def __init__(self, weighted=None):
        self.lock = nullcontext()
        self.weighted_memories = dict(weighted or {})


class _DictLike:
    """有 .get 但不是 dict，用于覆盖 isinstance(x, dict) 为假的分支。"""

    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


class _FlakyFloat:
    """首次 float() 成功、之后抛错的值对象：触发消化摘要二次解析的兜底 except。"""

    def __init__(self, value):
        self._value = float(value)
        self._calls = 0

    def __float__(self):
        self._calls += 1
        if self._calls > 1:
            raise ValueError("second float() boom")
        return self._value


def _raiser(msg):
    def _boom(*a, **k):
        raise RuntimeError(msg)

    return _boom


def _fix_time(monkeypatch, now):
    monkeypatch.setattr(m, "time", SimpleNamespace(time=lambda: now))


def _seen_logger(seen):
    return SimpleNamespace(
        warning=lambda *a, **k: seen.append(("warning", a, k)),
        info=lambda *a, **k: seen.append(("info", a, k)),
    )


# ---------------------------------- get_tool_injection -------------------------------- #
@pytest.mark.parametrize("active", [None, []], ids=["none", "empty"])
def test_tool_injection_no_active_tools(active):
    """active_tools 为空 / None → 空串。"""
    assert m.get_tool_injection(None, None, active) == ""


def test_tool_injection_intimate_filter():
    """非Ling剔除 intimate 工具后为空；Ling保留并输出总规则。"""
    assert m.get_tool_injection(
        None, None, ["enter_intimate_mode", "apply_status_effect"],
        persona_filename="core_aveline.json",
    ) == ""
    assert "【工具调用总规则】" in m.get_tool_injection(
        None, None, ["enter_intimate_mode"], persona_filename="core_ling.json"
    )


def test_tool_injection_search_chat_history():
    """激活 search_chat_history → 注入优先级引导。"""
    result = m.get_tool_injection(
        None, None, ["search_chat_history"], persona_filename="core_aveline.json"
    )
    assert "【工具使用优先级】" in result and "search_chat_history" in result


def test_tool_injection_message_peer_with_peer():
    """message_peer + 有互聊对象 → 注入含正确 peer 名的引导。"""
    result = m.get_tool_injection(
        None, None, ["message_peer"], persona_filename="core_aveline.json"
    )
    assert "【互聊工具引导】" in result and "给Ling发QQ消息" in result


def test_tool_injection_message_peer_without_peer(monkeypatch):
    """message_peer + 无互聊对象 → 记录 warning 且不注入引导。"""
    seen = []
    monkeypatch.setattr(m, "logger", _seen_logger(seen))

    result = m.get_tool_injection(
        None, None, ["message_peer"], persona_filename="core_ye.json"
    )

    assert "【互聊工具引导】" not in result
    warns = [e for e in seen if e[0] == "warning"]
    assert len(warns) == 1 and warns[0][1][1] == "core_ye.json"
    assert "没有注册互聊对象" in warns[0][1][0]


def test_tool_injection_multiple_sections_order():
    """多片段按 总规则 → 优先级 → 互聊 顺序拼接。"""
    result = m.get_tool_injection(
        None, None, ["search_chat_history", "message_peer"], persona_filename="core_aveline.json"
    )
    assert result.index("【工具调用总规则】") < result.index("【工具使用优先级】")
    assert result.index("【工具使用优先级】") < result.index("【互聊工具引导】")


def test_tool_injection_character_state_injected(monkeypatch):
    """registry 可用 + 激活 search_tools + filter 放行 → 注入角色现场状态。"""
    registry = SimpleNamespace(is_enabled=lambda name: name == "update_character_state")
    calls = []
    monkeypatch.setattr(
        "core.tools.tool_visibility.filter_tool_names",
        lambda names, **kw: calls.append((list(names), kw)) or ["update_character_state"],
    )

    result = m.get_tool_injection(
        SimpleNamespace(tool_registry=registry), None, ["search_tools"],
        persona_filename="core_aveline.json", mode="chat", is_sensitive_mode=True,
    )

    assert "【角色现场状态】" in result
    assert calls == [(
        ["update_character_state"],
        {"tool_registry": registry, "persona_filename": "core_aveline.json",
         "mode": "chat", "is_sensitive_mode": True},
    )]


def test_tool_injection_character_state_skipped(monkeypatch):
    """is_enabled 假 / 激活列表不匹配 / 无 is_enabled → 均跳过且不调用 filter。"""
    calls = []
    monkeypatch.setattr(
        "core.tools.tool_visibility.filter_tool_names",
        lambda *a, **k: calls.append(1) or ["update_character_state"],
    )
    cases = [
        (SimpleNamespace(is_enabled=lambda n: False), ["search_tools"]),
        (SimpleNamespace(is_enabled=lambda n: True), ["search_chat_history"]),
        (SimpleNamespace(), ["update_character_state"]),
    ]
    results = [
        m.get_tool_injection(SimpleNamespace(tool_registry=reg), None, active,
                             persona_filename="core_aveline.json")
        for reg, active in cases
    ]

    assert all("【角色现场状态】" not in r for r in results)
    assert calls == []


def test_tool_injection_character_state_filtered_out(monkeypatch):
    """filter_tool_names 返回空 → 不注入角色现场状态。"""
    monkeypatch.setattr("core.tools.tool_visibility.filter_tool_names", lambda *a, **k: [])
    registry = SimpleNamespace(is_enabled=lambda n: True)

    result = m.get_tool_injection(
        SimpleNamespace(tool_registry=registry), None, ["update_character_state"],
        persona_filename="core_aveline.json",
    )

    assert "【角色现场状态】" not in result


# ------------------------------- get_instruction_injection --------------------------- #
def test_instruction_injection_no_user_id():
    """user_id 为空 → 空串，不触碰 agent。"""
    assert m.get_instruction_injection(None, "") == ""


def test_instruction_injection_non_weighted_manager():
    """memory manager 不是 WeightedMemoryManager → 空串。"""
    agent = SimpleNamespace(_get_memory_manager=lambda uid: SimpleNamespace())
    assert m.get_instruction_injection(agent, "u1") == ""


def test_instruction_injection_important_prompts(monkeypatch):
    """优先使用 get_important_prompts 的返回内容。"""
    monkeypatch.setattr(m, "WeightedMemoryManager", _MM)
    calls = []
    mm = _MM(prompts=[{"content": "记得吃药"}, {"content": "早睡"}])
    agent = SimpleNamespace(_get_memory_manager=lambda uid: calls.append(uid) or mm)

    result = m.get_instruction_injection(agent, "u1")

    assert calls == ["u1"]
    assert result.startswith("\n\n# Important Memories & Instructions (Core Layer)")
    assert "- 记得吃药" in result and "- 早睡" in result


def test_instruction_injection_weighted_fallback(monkeypatch):
    """prompts 为空 → 加权记忆按时间倒序取 user_instruction，满 5 条即停。"""
    monkeypatch.setattr(m, "WeightedMemoryManager", _MM)
    weighted = {
        f"m{i}": {"timestamp": float(i),
                  "topics": ["user_instruction"] if i != 3 else ["other"],
                  "content": f"c{i}"}
        for i in range(1, 7)
    }
    agent = SimpleNamespace(_get_memory_manager=lambda uid: _MM(weighted=weighted, prompts=[]))

    result = m.get_instruction_injection(agent, "u1")

    # 倒序 m6,m5,m4,m3(skip),m2,m1 → 满 5 条 break，故 c1 在、c3 不在
    assert all(f"- c{i}" in result for i in (6, 5, 4, 2, 1))
    assert "- c3" not in result


def test_instruction_injection_no_prompts_method(monkeypatch):
    """无 get_important_prompts → 走加权记忆回退，无匹配则空串。"""
    monkeypatch.setattr(m, "WeightedMemoryManager", _MMNoPrompts)
    mm = _MMNoPrompts(weighted={"m1": {"timestamp": 1.0, "topics": ["other"], "content": "c"}})
    agent = SimpleNamespace(_get_memory_manager=lambda uid: mm)

    assert m.get_instruction_injection(agent, "u1") == ""


def test_instruction_injection_exception_logged(monkeypatch):
    """取记忆抛异常 → warning + 空串。"""
    seen = []
    monkeypatch.setattr(m, "logger", _seen_logger(seen))
    agent = SimpleNamespace(_get_memory_manager=_raiser("mm"))

    assert m.get_instruction_injection(agent, "u1") == ""
    warns = [e for e in seen if e[0] == "warning"]
    assert len(warns) == 1 and "Failed to load user instructions" in warns[0][1][0]


# --------------------------- get_study_folder_history_injection ---------------------- #
def test_study_folder_history_injection_delegates(monkeypatch):
    """无参构造 StudyPersonaProfile 并原样返回 build_history_injection 结果。"""
    calls = []

    class _Profile:
        def __init__(self):
            calls.append("init")

        def build_history_injection(self):
            calls.append("build")
            return "STUDY-INJECT"

    monkeypatch.setattr(m, "StudyPersonaProfile", _Profile)

    assert m.get_study_folder_history_injection() == "STUDY-INJECT"
    assert calls == ["init", "build"]


# --------------------------------- build_food_context_text --------------------------- #
def test_food_context_non_dict_returns_empty():
    """life_stats 为 None（无 .get）→ 空串。"""
    assert m.build_food_context_text(None) == ""


@pytest.mark.parametrize(
    "hunger,hint", [(10, "很饿"), (45, "有点饿"), (70, "一般"), (95, "很饱")],
    ids=["very-hungry", "slightly-hungry", "normal", "full"],
)
def test_food_context_fullness_hint(monkeypatch, hunger, hint):
    """饱腹值分段文案。"""
    _fix_time(monkeypatch, 1000.0)

    assert f"饱腹{hunger}（{hint}）" in m.build_food_context_text({"hunger": hunger})


def test_food_context_auto_eat_and_defaults(monkeypatch):
    """hunger>=90 提示可拒绝投喂；空 dict 走默认值。"""
    _fix_time(monkeypatch, 1000.0)

    assert "你可以自己去拿东西吃。" in m.build_food_context_text({"hunger": 89})
    text = m.build_food_context_text({})
    assert "饱腹100（很饱）" in text and "口渴100" in text and "精力100" in text
    assert "食物库存0份" in text
    assert "你已经很饱了，用户投喂时可以拒绝。" in text


def test_food_context_inventory_counting(monkeypatch):
    """库存只累计 quantity>0 的合法项；非 list / 非 dict 输入按 0 处理。"""
    _fix_time(monkeypatch, 1000.0)
    inventory = [{"quantity": 3}, {"quantity": 0}, "not-a-dict",
                 {"quantity": "abc"}, {"quantity": None}]

    assert "食物库存3份" in m.build_food_context_text({"hunger": 50, "food_inventory": inventory})
    assert "食物库存0份" in m.build_food_context_text({"hunger": 50, "food_inventory": {"a": 1}})
    assert "食物库存0份" in m.build_food_context_text(_DictLike({"hunger": 100}))


def test_food_context_digestion_queue(monkeypatch):
    """消化队列：正常项拼接效果与剩余分钟；过期 / 非法 / 非 dict / 坏效果均跳过。"""
    now = 1000.0
    _fix_time(monkeypatch, now)
    queue = [
        {"end_ts": now + 120,
         "effects": {"hunger": 10, "thirst": -5, "energy": 0, "health": 3}, "buff_desc": "苹果"},
        {"end_ts": now + 60, "effects": {}, "buff_desc": ""},
        {"end_ts": now - 10, "effects": {"hunger": 5}, "buff_desc": "过期"},
        {"end_ts": "bad", "effects": {}, "buff_desc": "非法"},
        "not-a-dict",
        {"end_ts": now + 60, "effects": {"hunger": "bad"}, "buff_desc": "坏效果"},
    ]

    text = m.build_food_context_text({"hunger": 50, "digestion_queue": queue})

    assert "- 消化中：" in text
    assert "苹果(饱腹+10, 口渴-5, 健康+3, 剩余3min)" in text
    assert "食物(无效果, 剩余2min)" in text and "坏效果(无效果, 剩余2min)" in text
    assert "过期" not in text and "非法" not in text


def test_food_context_last_meal_variants(monkeypatch):
    """上一顿文案：用户投喂 / 有原因 / 仅食物名 / 无食物名 / 非 dict。"""
    _fix_time(monkeypatch, 1000.0)

    def _text(meal):
        return m.build_food_context_text({"hunger": 50, "_last_meal": meal})

    assert "- 刚刚主人给你投喂了拉面，记得感谢主人！" in _text(
        {"food_name": "拉面", "source": "user_feed", "reason": "x"}
    )
    assert "- 你上一顿吃了拉面，因为饿了" in _text({"food_name": "拉面", "reason": "饿了"})
    assert "- 你上一顿吃了拉面\n" in _text({"food_name": "拉面"})
    assert "上一顿" not in _text({"reason": "饿了"})
    assert "上一顿" not in _text("not-a-dict")


# ----------------------- get_inventory_and_digestion_summary ------------------------- #
def test_summary_empty_inputs(monkeypatch):
    """None / 非 dict / 空 dict → 空 / 无。"""
    _fix_time(monkeypatch, 1000.0)

    assert m.get_inventory_and_digestion_summary(None) == ("空", "无")
    assert m.get_inventory_and_digestion_summary(_DictLike({})) == ("空", "无")
    assert m.get_inventory_and_digestion_summary({}) == ("空", "无")


def test_summary_inventory_filters_and_order(monkeypatch):
    """过滤空 food_id / quantity<=0 / 已过期 / 非法 quantity；按到期时间升序展示。"""
    now = 1000.0
    _fix_time(monkeypatch, now)
    stats = {"food_inventory": [
        {"food_id": "apple", "quantity": 2, "expire_at": now + 7200},
        {"food_id": "", "quantity": 1},
        {"food_id": "milk", "quantity": 0},
        {"food_id": "bread", "quantity": 1, "expire_at": now - 100},
        {"food_id": "bad", "quantity": "abc"},
        {"food_id": "water", "quantity": 1},
        "not-a-dict",
    ]}

    assert m.get_inventory_and_digestion_summary(stats)[0] == "3 份：waterx1，applex2(剩2h)"


def test_summary_inventory_top_three_and_bad_expire(monkeypatch):
    """摘要只展示前三项但统计全部；expire_at 非法按 0 处理。"""
    now = 1000.0
    _fix_time(monkeypatch, now)
    four = {"food_inventory": [
        {"food_id": f"f{i}", "quantity": 1, "expire_at": now + (i + 1) * 3600} for i in range(4)
    ]}
    summary = m.get_inventory_and_digestion_summary(four)[0]

    assert summary.startswith("4 份：") and summary.count("x1") == 3
    assert m.get_inventory_and_digestion_summary(
        {"food_inventory": [{"food_id": "apple", "quantity": 1, "expire_at": "bad"}]}
    )[0] == "1 份：applex1"


def test_summary_digestion_full(monkeypatch):
    """消化摘要：项数 / 最近结束分钟 / 效果维度顺序 / 状态去重。"""
    now = 1000.0
    _fix_time(monkeypatch, now)
    queue = [
        {"end_ts": now + 1800, "effects": {"hunger": 5, "thirst": -3}, "buff_desc": "咖啡"},
        {"end_ts": now + 600, "effects": {"energy": 2, "health": 1}, "buff_desc": "咖啡"},
        {"end_ts": now - 5, "effects": {"hunger": 1}, "buff_desc": "过期"},
        {"end_ts": 0, "effects": {"hunger": 1}, "buff_desc": "零"},
        {"end_ts": "bad", "effects": {"hunger": 1}, "buff_desc": "非法"},
        "not-a-dict",
    ]

    assert m.get_inventory_and_digestion_summary({"digestion_queue": queue})[1] == (
        "2 项进行中，最近结束 10min，效果：饱腹/解渴/提神/恢复 / 状态：咖啡"
    )


def test_summary_digestion_without_effects_or_buffs(monkeypatch):
    """无效果 / 无状态 → 省略对应片段；effects 非 dict 或取值非法不影响计数。"""
    now = 1000.0
    _fix_time(monkeypatch, now)

    minimal = m.get_inventory_and_digestion_summary(
        {"digestion_queue": [{"end_ts": now + 120, "effects": {}, "buff_desc": ""}]}
    )
    assert minimal[1] == "1 项进行中，最近结束 2min"

    bad = m.get_inventory_and_digestion_summary({"digestion_queue": [
        {"end_ts": now + 120, "effects": ["x"], "buff_desc": ""},
        {"end_ts": now + 120, "effects": {"hunger": "bad"}, "buff_desc": ""},
    ]})
    assert bad[1] == "2 项进行中，最近结束 2min"


def test_summary_digestion_second_parse_failure(monkeypatch):
    """end_ts 首次可解析、二次解析失败 → 兜底 0，soonest 保持 None（0min）。"""
    now = 1000.0
    _fix_time(monkeypatch, now)
    entry = {"end_ts": _FlakyFloat(now + 120), "effects": {"hunger": 1}, "buff_desc": ""}

    assert m.get_inventory_and_digestion_summary({"digestion_queue": [entry]})[1] == (
        "1 项进行中，最近结束 0min，效果：饱腹"
    )


def test_summary_exception_paths(monkeypatch):
    """life_stats.get 抛异常 → 两个摘要都回退默认值。"""
    _fix_time(monkeypatch, 1000.0)

    class _Boom(dict):
        def get(self, key, default=None):
            raise RuntimeError("boom")

    assert m.get_inventory_and_digestion_summary(_Boom()) == ("空", "无")
