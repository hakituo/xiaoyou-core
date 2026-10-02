# -*- coding: utf-8 -*-
"""``core.services.data_ops.ye_runtime_state`` 的单元测试。

覆盖叶 Persona 2.0 运行时状态的完整链路：配置读取与缓存、scope 判定、
规则/UIE 现场提取、候选仲裁、状态合并与过期清理、以及原子写回。

全部使用纯替身（假 UIE 提取器 / 桩配置 / 桩时钟），落盘一律隔离到
``tmp_path``，绝不触碰真实的 ``companion_data/`` 角色运行数据目录。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from core.services.data_ops import ye_runtime_state as yrs

# 固定时钟：避免断言真实流逝时间，同时让 ISO 时间戳可精确断言。
FIXED_NOW = datetime(2026, 9, 1, 15, 0, 0, tzinfo=timezone(timedelta(hours=8)))
FIXED_TS = "2026-09-01T15:00:00+08:00"


def _base_config(**overrides):
    """规则模式（automatic）的基础配置，默认不含 UIE。"""
    config = {
        "enabled": True,
        "scope": "ye",
        "scene_write_mode": "automatic",
        "location_terms": ["宿舍", "实验室", "图书馆", "食堂"],
        "physical_terms": ["困", "累", "头疼"],
        "private_mode": {
            "enter_markers": ["进入私密模式"],
            "exit_markers": ["回普通聊天"],
        },
        "limits": {},
    }
    config.update(overrides)
    return config


def _tool_config(state_path=None, **overrides):
    """现场六字段由工具写入的配置。"""
    config = _base_config(scene_write_mode="tool", **overrides)
    if state_path is not None:
        config["runtime_state_path"] = str(state_path)
    return config


def _uie_config(**overrides):
    config = _base_config(
        uie={
            "enabled": True,
            "min_probability": 0.5,
            "schema_by_field": {"clothing": ["衣服"], "location": ["地点"]},
        },
    )
    config.update(overrides)
    return config


def _patch_tool_config(monkeypatch, tmp_path, name="state.json"):
    """把默认配置指向 tmp_path 下的状态文件，并返回目标路径。"""
    target = tmp_path / name
    config = _tool_config(target)
    monkeypatch.setattr(yrs, "_load_default_config", lambda: config)
    return target


def _run(coro):
    """沿用仓库既有习惯：同步测试内用 asyncio.run 驱动协程。"""
    return asyncio.run(coro)


class _FakeUIE:
    """只回放指定 span 的 UIE 替身，并记录调用参数。"""

    def __init__(self, result=None, error=None):
        self.result = {} if result is None else result
        self.error = error
        self.calls = []

    def extract(self, text, schemas):
        self.calls.append((text, tuple(schemas)))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture(autouse=True)
def _isolated_module_state(monkeypatch):
    """隔离模块级可变状态：状态锁、时钟与 lru_cache 配置缓存。"""
    # 先抓住真正的 lru_cache 包装函数：monkeypatch 的撤销发生在本 fixture
    # 收尾之后，若直接调 clear_ye_runtime_state_config_cache() 会命中替身。
    real_loader = yrs._load_default_config
    monkeypatch.setattr(yrs, "_STATE_LOCK", yrs.LazyAsyncLock())
    monkeypatch.setattr(yrs, "get_current_time", lambda: FIXED_NOW)
    real_loader.cache_clear()
    yield
    real_loader.cache_clear()


# --------------------------------------------------------------------------- #
# 配置读取 / 路径 / 工具开关
# --------------------------------------------------------------------------- #

def test_load_default_config_reads_real_config():
    """真实配置可读，且结果被 lru_cache 复用。"""
    first = yrs._load_default_config()
    second = yrs._load_default_config()
    assert isinstance(first, dict)
    assert first["enabled"] is True
    assert first["scope"] == "ye"
    assert first["scene_write_mode"] == "tool"
    assert first is second


def test_load_default_config_returns_empty_on_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(yrs, "_CONFIG_PATH", tmp_path / "nope.json")
    yrs.clear_ye_runtime_state_config_cache()
    assert yrs._load_default_config() == {}


def test_load_default_config_returns_empty_on_bad_json(monkeypatch, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(yrs, "_CONFIG_PATH", path)
    yrs.clear_ye_runtime_state_config_cache()
    assert yrs._load_default_config() == {}


def test_load_default_config_returns_empty_on_non_dict_json(monkeypatch, tmp_path):
    path = tmp_path / "list.json"
    path.write_text("[1, 2]", encoding="utf-8")
    monkeypatch.setattr(yrs, "_CONFIG_PATH", path)
    yrs.clear_ye_runtime_state_config_cache()
    assert yrs._load_default_config() == {}


def test_clear_config_cache_forces_reread(monkeypatch, tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"enabled": True}), encoding="utf-8")
    monkeypatch.setattr(yrs, "_CONFIG_PATH", path)
    yrs.clear_ye_runtime_state_config_cache()
    assert yrs._load_default_config() == {"enabled": True}

    path.write_text(json.dumps({"enabled": False}), encoding="utf-8")
    assert yrs._load_default_config() == {"enabled": True}  # 仍命中缓存
    yrs.clear_ye_runtime_state_config_cache()
    assert yrs._load_default_config() == {"enabled": False}


def test_clear_config_cache_is_repeatable():
    """缓存清理入口可重复调用，且不影响后续读取。"""
    assert yrs._load_default_config()["scope"] == "ye"
    yrs.clear_ye_runtime_state_config_cache()
    assert yrs._load_default_config()["scope"] == "ye"


def test_resolve_state_path_defaults_and_variants():
    assert yrs._resolve_state_path({}) == yrs._DEFAULT_STATE_PATH
    assert yrs._resolve_state_path({"runtime_state_path": "   "}) == yrs._DEFAULT_STATE_PATH
    relative = yrs._resolve_state_path({"runtime_state_path": "some/dir/state.json"})
    assert relative == yrs._PROJECT_ROOT / "some" / "dir" / "state.json"
    absolute = yrs._PROJECT_ROOT / "abs" / "state.json"
    assert yrs._resolve_state_path({"runtime_state_path": str(absolute)}) == absolute


def test_get_ye_runtime_state_path_follows_config(monkeypatch, tmp_path):
    target = tmp_path / "state.json"
    monkeypatch.setattr(
        yrs, "_load_default_config", lambda: {"runtime_state_path": str(target)}
    )
    assert yrs.get_ye_runtime_state_path() == target

    monkeypatch.setattr(yrs, "_load_default_config", lambda: {})
    assert yrs.get_ye_runtime_state_path() == yrs._DEFAULT_STATE_PATH


def test_character_state_tool_enabled_gates(monkeypatch):
    monkeypatch.setattr(yrs, "_is_ye_turn", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        yrs, "_load_default_config", lambda: {"enabled": True, "scene_write_mode": "tool"}
    )
    assert yrs.character_state_tool_enabled("core_ye.json") is True
    assert yrs.character_state_tool_enabled("") is False

    monkeypatch.setattr(
        yrs, "_load_default_config", lambda: {"enabled": False, "scene_write_mode": "tool"}
    )
    assert yrs.character_state_tool_enabled("core_ye.json") is False

    monkeypatch.setattr(
        yrs, "_load_default_config", lambda: {"enabled": True, "scene_write_mode": "automatic"}
    )
    assert yrs.character_state_tool_enabled("core_ye.json") is False

    monkeypatch.setattr(
        yrs, "_load_default_config", lambda: {"enabled": True, "scene_write_mode": "tool"}
    )
    monkeypatch.setattr(yrs, "_is_ye_turn", lambda *args, **kwargs: False)
    assert yrs.character_state_tool_enabled("core_ye.json") is False


def test_character_state_tool_enabled_uses_real_scope_resolution():
    """真实配置下只对 ye 角色开放现场状态工具。"""
    assert yrs.character_state_tool_enabled("core_ye.json") is True
    assert yrs.character_state_tool_enabled("core_aveline.json") is False


# --------------------------------------------------------------------------- #
# scope 判定
# --------------------------------------------------------------------------- #

def test_is_ye_turn_prefers_persona_filename(monkeypatch):
    monkeypatch.setattr(yrs, "resolve_persona_slug_scope", lambda name: "ye")
    assert yrs._is_ye_turn("whatever", "core_ye.json", {"scope": "ye"}) is True
    assert yrs._is_ye_turn("whatever", "core_ye.json", {"scope": "ling"}) is False


def test_is_ye_turn_falls_back_to_conversation_id(monkeypatch):
    monkeypatch.setattr(
        yrs, "resolve_data_scope_from_conversation_id", lambda cid, default=None: "ye"
    )
    assert yrs._is_ye_turn("shared__persona__ye", None, {"scope": "ye"}) is True


def test_is_ye_turn_defaults_scope_to_ye(monkeypatch):
    monkeypatch.setattr(yrs, "resolve_persona_slug_scope", lambda name: "ye")
    assert yrs._is_ye_turn("", "core_ye.json", {}) is True


# --------------------------------------------------------------------------- #
# 纯函数小工具
# --------------------------------------------------------------------------- #

def test_clean_text_collapses_whitespace():
    assert yrs._clean_text("  a \n\t b  ") == "a b"
    assert yrs._clean_text(None) == ""
    assert yrs._clean_text(123) == "123"


def test_is_question_only_checks_tail():
    assert yrs._is_question("你现在在哪？") is True
    assert yrs._is_question("吃饭了吗") is True
    assert yrs._is_question("") is False
    assert yrs._is_question("问" * 40 + "？") is True
    assert yrs._is_question("？" + "啊" * 40) is False


def test_default_document_and_empty_scalar_shapes():
    document = yrs._default_document()
    assert document["character"] == "ye"
    assert document["schema_version"] == "2.0"
    assert set(yrs.SCENE_STATE_FIELDS) <= set(document["state"])
    assert document["state"]["ongoing_interaction"]["mode"] == "ordinary"
    assert document["runtime_meta"]["processed_message_ids"] == []
    assert yrs._empty_scalar() == {
        "value": None, "source": None, "updated_at": None, "confidence": None,
    }
    assert yrs._default_document() is not document


def test_normalize_document_fills_missing_pieces():
    normalized = yrs._normalize_document({})
    assert normalized["character"] == "ye"
    assert normalized["state"]["location"] == yrs._empty_scalar()
    assert normalized["runtime_meta"]["processed_message_ids"] == []

    broken = yrs._normalize_document({"state": "oops", "runtime_meta": "oops"})
    assert isinstance(broken["state"], dict)
    assert broken["state"]["activity"] == yrs._empty_scalar()
    assert broken["runtime_meta"] == {"processed_message_ids": []}

    kept = yrs._normalize_document(
        {"state": {"location": {"value": "宿舍"}}, "character": "other"}
    )
    assert kept["character"] == "other"
    assert kept["state"]["location"] == {"value": "宿舍"}
    assert kept["state"]["activity"] == yrs._empty_scalar()


def test_add_candidate_skips_empty_values():
    changes: dict = {}
    for empty in ("", None, [], {}):
        yrs._add_candidate(changes, "location", empty, "user_explicit", 1.0)
    assert changes == {}

    yrs._add_candidate(changes, "location", "宿舍", "user_explicit", 0.9)
    assert changes["location"] == [
        {"value": "宿舍", "source": "user_explicit", "confidence": 0.9}
    ]


def test_merge_candidates_extends_existing_lists():
    target = {"location": [{"value": "宿舍"}]}
    yrs._merge_candidates(
        target,
        {"location": [{"value": "实验室"}], "activity": [{"value": "看论文"}]},
    )
    assert [item["value"] for item in target["location"]] == ["宿舍", "实验室"]
    assert target["activity"] == [{"value": "看论文"}]


def test_best_candidate_priority_then_confidence():
    changes = {
        "location": [
            {"value": "uie", "source": "assistant_uie", "confidence": 0.99},
            {"value": "rule", "source": "assistant_rule", "confidence": 0.1},
            {"value": "explicit", "source": "user_explicit", "confidence": 0.2},
            {"value": "confirm", "source": "assistant_confirmation", "confidence": 0.5},
        ]
    }
    assert yrs._best_candidate(changes, "location")["value"] == "explicit"
    assert yrs._best_candidate(changes, "missing") is None
    assert yrs._best_candidate({"x": []}, "x") is None

    unknown = {
        "x": [
            {"value": "a", "source": "nope", "confidence": 1.0},
            {"value": "b", "source": "nope", "confidence": 2.0},
        ]
    }
    assert yrs._best_candidate(unknown, "x")["value"] == "b"


def test_upsert_list_replaces_by_identity_and_filters_non_dicts():
    new_item = {"type": "borrow", "target": "腿", "text": "旧", "extra": True}
    existing = ["bad", {"type": "borrow", "target": "腿", "text": "旧"}]
    result = yrs._upsert_list(existing, new_item, ("type", "target", "text"))
    assert result == [new_item]

    appended = yrs._upsert_list(
        result, {"type": "instruction", "text": "写作业"}, ("type", "target", "text")
    )
    assert [item.get("text") for item in appended] == ["旧", "写作业"]


def test_prune_expired_removes_only_expired_items():
    state = {
        "active_rules": [
            {"target": "腿", "expires_at": (FIXED_NOW - timedelta(hours=1)).isoformat()},
            {"target": "书", "expires_at": (FIXED_NOW + timedelta(hours=1)).isoformat()},
        ],
        "time_constraints": [
            {"label": "x", "expires_at": (FIXED_NOW - timedelta(minutes=1)).isoformat()}
        ],
        "explicit_facts": [{"fact": "keep"}],
    }
    changed = yrs._prune_expired(state, FIXED_NOW)
    assert changed == {"active_rules", "time_constraints"}
    assert [item["target"] for item in state["active_rules"]] == ["书"]
    assert state["time_constraints"] == []
    assert state["explicit_facts"] == [{"fact": "keep"}]
    assert yrs._prune_expired({"active_rules": "not a list"}, FIXED_NOW) == set()


def test_is_expired_branches():
    assert yrs._is_expired("not a mapping", FIXED_NOW) is False
    assert yrs._is_expired({}, FIXED_NOW) is False
    assert yrs._is_expired({"expires_at": ""}, FIXED_NOW) is False
    assert yrs._is_expired({"expires_at": "not-a-date"}, FIXED_NOW) is False
    assert (
        yrs._is_expired({"expires_at": (FIXED_NOW - timedelta(seconds=1)).isoformat()}, FIXED_NOW)
        is True
    )
    assert (
        yrs._is_expired({"expires_at": (FIXED_NOW + timedelta(seconds=1)).isoformat()}, FIXED_NOW)
        is False
    )

    # naive 到期时间按当前时区补齐后再比较
    naive_past = (FIXED_NOW.replace(tzinfo=None) - timedelta(hours=1)).isoformat()
    assert yrs._is_expired({"expires_at": naive_past}, FIXED_NOW) is True
    # 无时区的 now 与 naive 到期时间直接比较
    assert yrs._is_expired({"expires_at": naive_past}, FIXED_NOW.replace(tzinfo=None)) is True


def test_parse_expiry_periods_and_rollover():
    assert yrs._parse_expiry("随便说说", FIXED_NOW) is None
    assert yrs._parse_expiry("下午五点", FIXED_NOW) == "2026-09-01T17:00+08:00"
    assert yrs._parse_expiry("晚上11点30", FIXED_NOW) == "2026-09-01T23:30+08:00"
    # 已经过点的时刻顺延到次日
    assert yrs._parse_expiry("上午九点", FIXED_NOW) == "2026-09-02T09:00+08:00"
    assert yrs._parse_expiry("12:00", FIXED_NOW) == "2026-09-02T12:00+08:00"
    # 中午 / 凌晨的特殊换算
    assert yrs._parse_expiry("中午10点", FIXED_NOW) == "2026-09-01T22:00+08:00"
    assert yrs._parse_expiry("中午12点", FIXED_NOW) == "2026-09-02T12:00+08:00"
    assert yrs._parse_expiry("凌晨12点", FIXED_NOW) == "2026-09-02T00:00+08:00"
    assert yrs._parse_expiry("25点", FIXED_NOW) is None


def test_cn_number_variants():
    assert yrs._cn_number("8") == 8
    assert yrs._cn_number("十") == 10
    assert yrs._cn_number("十二") == 12
    assert yrs._cn_number("二十") == 20
    assert yrs._cn_number("二十五") == 25
    assert yrs._cn_number("五") == 5
    assert yrs._cn_number("零") is None


def test_strip_tail_repeatedly_trims():
    assert yrs._strip_tail("白T恤呢呀", ("呢", "呀")) == "白T恤"
    assert yrs._strip_tail("无尾巴", ("呢",)) == "无尾巴"


def test_item_identity_joins_known_keys():
    assert yrs._item_identity({"target": "腿", "text": "", "type": "borrow"}) == "腿  borrow"
    assert yrs._item_identity("raw") == "raw"


def test_limit_reads_config_with_fallback():
    assert yrs._limit({}, "active_rules", 20) == 20
    assert yrs._limit({"limits": "oops"}, "active_rules", 20) == 20
    assert yrs._limit({"limits": {"active_rules": 3}}, "active_rules", 20) == 3
    assert yrs._limit({"limits": {"active_rules": "bad"}}, "active_rules", 20) == 20
    assert yrs._limit({"limits": {"active_rules": None}}, "active_rules", 20) == 20
    assert yrs._limit({"limits": {"active_rules": 0}}, "active_rules", 20) == 1


# --------------------------------------------------------------------------- #
# 正则提取
# --------------------------------------------------------------------------- #

def test_find_location_requires_text_and_terms():
    assert yrs._find_location("", ("宿舍",), subject_pattern="") == ""
    assert yrs._find_location("我在宿舍", (), subject_pattern="") == ""
    assert yrs._find_location("我在宿舍", ("宿舍",), subject_pattern=r"(?:我)?(?:现在)?") == "宿舍"
    assert yrs._find_location("我在图书馆", ("宿舍",), subject_pattern="") == ""


def test_find_activity_verbs_then_location_context():
    assert yrs._find_activity("我在跑步", ()) == "跑步"
    assert yrs._find_activity("我今天很好", ()) == ""
    # 无已知动词时，靠地点上下文里的“做/看/写”短语
    assert yrs._find_activity("我正在图书馆看书呢", ("图书馆",)) == "看书"
    assert yrs._find_activity("我正在图书馆发呆", ("图书馆",)) == ""


def test_extract_assistant_scene_all_fields():
    changes: dict = {}
    text = "我现在在图书馆看论文，穿着白T恤，舍友也在旁边，有点困，手里拿着实验记录本。"
    yrs._extract_assistant_scene(changes, text, ("图书馆",), ("困", "累"))
    assert changes["location"][0]["value"] == "图书馆"
    assert changes["location"][0]["source"] == "assistant_rule"
    assert changes["activity"][0]["value"] == "看论文"
    assert changes["clothing"][0]["value"] == "白T恤"
    assert changes["people_present"][0]["value"] == "舍友"
    assert changes["physical_state"][0]["value"] == "困"
    assert changes["current_possessions"][0]["value"] == "实验记录本"


def test_extract_assistant_scene_skips_blank_text():
    changes: dict = {}
    yrs._extract_assistant_scene(changes, "", ("图书馆",), ("困",))
    assert changes == {}


def test_extract_assistant_scene_trims_clothing_tail():
    changes: dict = {}
    yrs._extract_assistant_scene(changes, "我今天穿着黑色长裙呢。", (), ())
    assert changes["clothing"][0]["value"] == "黑色长裙"


def test_extract_assistant_scene_people_and_physical_variants():
    changes: dict = {}
    yrs._extract_assistant_scene(changes, "我和导师一起在实验室。", ("实验室",), ())
    assert changes["people_present"][0]["value"] == "导师"

    changes = {}
    yrs._extract_assistant_scene(changes, "我又困又累，头疼。", (), ("困", "累", "困"))
    assert changes["physical_state"][0]["value"] == "困、累"


def test_extract_user_corrections_uses_explicit_facts():
    changes: dict = {}
    yrs._extract_user_corrections(changes, "Ye在宿舍。", ("宿舍",))
    assert changes["location"][0]["value"] == "宿舍"
    assert changes["location"][0]["source"] == "user_explicit"

    changes = {}
    yrs._extract_user_corrections(changes, "Ye在宿舍吗？", ("宿舍",))
    assert changes == {}


def test_extract_confirmed_question_requires_affirmative_and_location():
    changes: dict = {}
    yrs._extract_confirmed_question(changes, "你现在在实验室吗？", "对。", ("实验室",))
    assert changes["location"][0] == {
        "value": "实验室", "source": "assistant_confirmation", "confidence": 0.96,
    }

    changes = {}
    yrs._extract_confirmed_question(changes, "你现在在实验室吗？", "不，我在宿舍。", ("实验室",))
    assert changes == {}

    changes = {}
    yrs._extract_confirmed_question(changes, "", "对。", ("实验室",))
    assert changes == {}

    changes = {}
    yrs._extract_confirmed_question(changes, "你在吗？", "", ("实验室",))
    assert changes == {}

    changes = {}
    yrs._extract_confirmed_question(changes, "你在吗？", "对。", ("实验室",))
    assert changes == {}


def test_extract_relationship_rules_ignores_blank_user_text():
    changes: dict = {}
    yrs._extract_relationship_rules(changes, "", "写完了。", FIXED_NOW)
    assert changes == {}


def test_extract_relationship_rules_return_and_borrow():
    changes: dict = {}
    yrs._extract_relationship_rules(changes, "把腿还给我。", "", FIXED_NOW)
    assert changes["active_rules_remove"][0]["value"] == "腿"

    changes = {}
    yrs._extract_relationship_rules(changes, "腿借你到下午五点。", "", FIXED_NOW)
    rule = changes["active_rules_add"][0]["value"]
    assert rule["type"] == "borrow"
    assert rule["target"] == "腿"
    assert rule["holder"] == "ye"
    assert rule["expires_at"] == "2026-09-01T17:00+08:00"
    assert rule["expires_label"] == "下午五点"
    assert changes["time_constraints_add"][0]["value"]["related_type"] == "borrow"


def test_extract_relationship_rules_instruction_pending_and_complete():
    changes: dict = {}
    yrs._extract_relationship_rules(changes, "你记得写作业。", "好。", FIXED_NOW)
    assert changes["active_rules_add"][0]["value"]["type"] == "instruction"
    assert "记得写作业" in changes["active_rules_add"][0]["value"]["text"]
    assert "pending_actions_add" not in changes

    changes = {}
    yrs._extract_relationship_rules(changes, "你去写作业。", "好。", FIXED_NOW)
    assert changes["pending_actions_add"][0]["value"] == {
        "action": "去写作业", "status": "pending",
    }

    # 疑问句里的“去写作业”不算待办
    changes = {}
    yrs._extract_relationship_rules(changes, "你去写作业吗？", "好。", FIXED_NOW)
    assert "pending_actions_add" not in changes

    changes = {}
    yrs._extract_relationship_rules(changes, "嗯。", "我写完了。", FIXED_NOW)
    assert changes["pending_actions_complete"][0]["value"] == "latest"


def test_extract_private_mode_enter_exit_and_precedence():
    config = _base_config()

    changes: dict = {}
    yrs._extract_private_mode(changes, "我们进入私密模式吧", config)
    assert changes["ongoing_interaction"][0]["value"] == "private"

    changes = {}
    yrs._extract_private_mode(changes, "回普通聊天", config)
    assert changes["ongoing_interaction"][0]["value"] == "ordinary"

    # 退出标记优先于进入标记
    changes = {}
    yrs._extract_private_mode(changes, "先进入私密模式，再回普通聊天", config)
    assert [item["value"] for item in changes["ongoing_interaction"]] == ["ordinary"]

    changes = {}
    yrs._extract_private_mode(changes, "普通内容", config)
    assert changes == {}

    changes = {}
    yrs._extract_private_mode(changes, "进入私密模式", {"private_mode": "oops"})
    assert changes == {}


def test_select_uie_fields_gates():
    assert yrs._select_uie_fields("我在图书馆", _tool_config()) == set()
    assert yrs._select_uie_fields("", _uie_config()) == set()
    assert yrs._select_uie_fields("我在图书馆", _base_config()) == set()
    assert yrs._select_uie_fields("我在图书馆", _base_config(uie={"enabled": False})) == set()
    assert yrs._select_uie_fields("我在图书馆", _base_config(uie="oops")) == set()


def test_select_uie_fields_marker_mapping():
    config = _uie_config()
    fields = yrs._select_uie_fields(
        "我在图书馆看书，穿着白T恤，舍友在旁边，有点困，手里拿着书包。", config
    )
    assert fields == {
        "location",
        "activity",
        "clothing",
        "people_present",
        "physical_state",
        "current_possessions",
    }
    assert yrs._select_uie_fields("外套有点旧", config) == {"clothing"}
    assert yrs._select_uie_fields("路上", config) == {"location", "activity"}


def test_extract_rule_changes_tool_mode_skips_scene_extraction():
    changes = yrs._extract_rule_changes(
        user_text="你现在在图书馆吗？",
        assistant_text="对，我在图书馆。",
        config=_tool_config(),
        now=FIXED_NOW,
    )
    assert "location" not in changes


def test_extract_rule_changes_automatic_mode_collects_scene():
    changes = yrs._extract_rule_changes(
        user_text="你现在在图书馆吗？",
        assistant_text="对，我在图书馆看论文。",
        config=_base_config(),
        now=FIXED_NOW,
    )
    assert changes["location"][0]["value"] == "图书馆"
    assert changes["activity"][0]["value"] == "看论文"


def test_extract_rule_changes_sanitizes_term_lists():
    config = _base_config(location_terms=["宿舍", "", None, 123], physical_terms=["困", ""])
    changes = yrs._extract_rule_changes(
        user_text="", assistant_text="我在123。", config=config, now=FIXED_NOW,
    )
    assert changes["location"][0]["value"] == "123"


def test_uie_item_value_restores_original_span():
    text = "白T恤和牛仔裤"
    assert yrs._uie_item_value(text, {"text": "白 t 恤", "start": 0, "end": 2}) == "白T恤"
    assert yrs._uie_item_value(text, {"text": "牛仔裤", "start": 4, "end": 6}) == "牛仔裤"


def test_uie_item_value_falls_back_to_decoded_text():
    text = "白T恤和牛仔裤"
    assert yrs._uie_item_value(text, {"text": "白 t 恤"}) == "白t恤"
    assert yrs._uie_item_value(text, {"text": "白T恤", "start": "x", "end": 2}) == "白T恤"
    assert yrs._uie_item_value(text, {"text": "白T恤", "start": -1, "end": 2}) == "白T恤"
    assert yrs._uie_item_value(text, {"text": "白T恤", "start": 5, "end": 2}) == "白T恤"
    assert yrs._uie_item_value(text, {"text": "白T恤", "start": 0, "end": 99}) == "白T恤"
    # span 与解码文本不一致时以解码文本为准
    assert yrs._uie_item_value(text, {"text": "牛仔裤", "start": 0, "end": 2}) == "牛仔裤"
    # span 全是标点时视为空，回退到解码文本
    assert yrs._uie_item_value("，。！", {"text": "白T恤", "start": 0, "end": 1}) == "白T恤"


def test_merge_uie_spans_returns_best_for_non_mergeable_field():
    accepted = [
        {"value": "图书馆", "confidence": 0.6, "start": 0, "end": 2},
        {"value": "宿舍", "confidence": 0.9, "start": 5, "end": 6},
    ]
    assert yrs._merge_uie_spans("图书馆和宿舍", "location", accepted)["value"] == "宿舍"


def test_merge_uie_spans_merges_adjacent_clothing_spans():
    text = "白T恤和牛仔裤"
    accepted = [
        {"value": "白T恤", "confidence": 0.9, "start": 0, "end": 2},
        {"value": "牛仔裤", "confidence": 0.6, "start": 4, "end": 6},
    ]
    assert yrs._merge_uie_spans(text, "clothing", accepted) == {
        "value": "白T恤和牛仔裤", "confidence": 0.6,
    }


def test_merge_uie_spans_keeps_best_when_gap_too_large():
    text = "白T恤放在柜子里的牛仔裤"
    accepted = [
        {"value": "白T恤", "confidence": 0.9, "start": 0, "end": 2},
        {"value": "牛仔裤", "confidence": 0.8, "start": 9, "end": 11},
    ]
    assert yrs._merge_uie_spans(text, "clothing", accepted)["value"] == "白T恤"


def test_merge_uie_spans_ignores_out_of_range_positions():
    text = "白T恤和牛仔裤"
    accepted = [
        {"value": "白T恤", "confidence": 0.9, "start": 0, "end": 2},
        {"value": "越界", "confidence": 0.8, "start": 0, "end": 99},
    ]
    assert yrs._merge_uie_spans(text, "clothing", accepted)["value"] == "白T恤"


def test_merge_uie_spans_skips_unpositioned_and_overlapping():
    text = "白T恤和牛仔裤"
    accepted = [
        {"value": "白T恤", "confidence": 0.9, "start": None, "end": None},
        {"value": "牛仔裤", "confidence": 0.8, "start": 4, "end": 6},
    ]
    assert yrs._merge_uie_spans(text, "clothing", accepted)["value"] == "白T恤"

    overlapping = [
        {"value": "白T恤", "confidence": 0.9, "start": 0, "end": 5},
        {"value": "牛仔裤", "confidence": 0.8, "start": 3, "end": 6},
    ]
    assert yrs._merge_uie_spans(text, "clothing", overlapping)["value"] == "白T恤"


# --------------------------------------------------------------------------- #
# 状态合并
# --------------------------------------------------------------------------- #

def test_apply_changes_writes_scene_fields_and_lists():
    state = yrs._default_document()["state"]
    changes = {
        "location": [{"value": "图书馆", "source": "assistant_rule", "confidence": 0.9}],
        "active_rules_add": [
            {"value": {"type": "instruction", "text": "写作业"}, "source": "user_explicit",
             "confidence": 0.96}
        ],
        "pending_actions_add": [
            {"value": {"action": "写作业"}, "source": "user_explicit", "confidence": 0.93}
        ],
        "time_constraints_add": [
            {"value": {"label": "下午五点", "related_type": "borrow", "target": "腿"},
             "source": "user_explicit", "confidence": 1.0}
        ],
        "explicit_facts_add": [
            {"value": {"fact": "Ye喜欢猫"}, "source": "user_explicit", "confidence": 1.0}
        ],
    }
    changed = yrs._apply_changes(state, changes, FIXED_TS, FIXED_NOW, _base_config())
    assert changed == {
        "location", "active_rules", "pending_actions", "time_constraints", "explicit_facts",
    }
    assert state["location"] == {
        "value": "图书馆", "source": "assistant_rule",
        "updated_at": FIXED_TS, "confidence": 0.9,
    }
    assert state["active_rules"][0]["type"] == "instruction"
    assert state["pending_actions"][0]["action"] == "写作业"
    assert state["pending_actions"][0]["updated_at"] == FIXED_TS
    assert state["time_constraints"][0]["target"] == "腿"
    assert state["explicit_facts"][0]["fact"] == "Ye喜欢猫"


def test_apply_changes_skips_non_dict_list_items():
    state = yrs._default_document()["state"]
    changes = {
        "pending_actions_add": [
            {"value": "不是字典", "source": "user_explicit", "confidence": 1.0}
        ]
    }
    assert yrs._apply_changes(state, changes, FIXED_TS, FIXED_NOW, _base_config()) == set()
    assert state["pending_actions"] == []


def test_apply_changes_removes_matching_active_rule():
    state = yrs._default_document()["state"]
    state["active_rules"] = [
        {"target": "腿", "type": "borrow"},
        {"target": "书", "type": "borrow"},
    ]
    changes = {
        "active_rules_remove": [{"value": "腿", "source": "user_explicit", "confidence": 1.0}]
    }
    changed = yrs._apply_changes(state, changes, FIXED_TS, FIXED_NOW, _base_config())
    assert changed == {"active_rules"}
    assert [item["target"] for item in state["active_rules"]] == ["书"]

    # 目标不存在时不产生变更
    state["active_rules"] = [{"target": "书"}]
    assert yrs._apply_changes(state, changes, FIXED_TS, FIXED_NOW, _base_config()) == set()


def test_apply_changes_completes_latest_pending_action():
    state = yrs._default_document()["state"]
    state["pending_actions"] = [
        {"action": "写作业", "status": "pending"},
        {"action": "做实验", "status": "completed"},
        {"action": "看书", "status": "pending"},
    ]
    changes = {
        "pending_actions_complete": [
            {"value": "latest", "source": "assistant_rule", "confidence": 0.9}
        ]
    }
    changed = yrs._apply_changes(state, changes, FIXED_TS, FIXED_NOW, _base_config())
    assert changed == {"pending_actions"}
    assert state["pending_actions"][-1]["status"] == "completed"
    assert state["pending_actions"][-1]["completed_at"] == FIXED_TS
    assert state["pending_actions"][-1]["completion_source"] == "assistant_rule"
    assert state["pending_actions"][0]["status"] == "pending"


def test_apply_changes_complete_skips_non_pending_entries():
    state = yrs._default_document()["state"]
    state["pending_actions"] = [
        {"action": "写作业", "status": "pending"},
        {"action": "做实验", "status": "completed"},
        "不是字典",
    ]
    changes = {
        "pending_actions_complete": [
            {"value": "latest", "source": "assistant_rule", "confidence": 0.9}
        ]
    }
    # 反向遍历时先跳过非字典与已完成项，再标记最近的 pending
    assert yrs._apply_changes(state, changes, FIXED_TS, FIXED_NOW, _base_config()) == {
        "pending_actions"
    }
    assert state["pending_actions"][0]["status"] == "completed"
    assert state["pending_actions"][1]["status"] == "completed"
    assert state["pending_actions"][2] == "不是字典"


def test_apply_changes_complete_without_pending_is_noop():
    state = yrs._default_document()["state"]
    changes = {
        "pending_actions_complete": [
            {"value": "latest", "source": "assistant_rule", "confidence": 0.9}
        ]
    }
    assert yrs._apply_changes(state, changes, FIXED_TS, FIXED_NOW, _base_config()) == set()


def test_apply_changes_ongoing_interaction_modes():
    state = yrs._default_document()["state"]
    private = {
        "ongoing_interaction": [
            {"value": "private", "source": "user_explicit", "confidence": 1.0}
        ]
    }
    assert yrs._apply_changes(state, private, FIXED_TS, FIXED_NOW, _base_config()) == {
        "ongoing_interaction"
    }
    assert state["ongoing_interaction"] == {
        "mode": "private",
        "label": "private_relationship",
        "started_at": FIXED_TS,
        "state": "active",
        "source": "user_explicit",
    }

    ordinary = {
        "ongoing_interaction": [
            {"value": "ordinary", "source": "user_explicit", "confidence": 1.0}
        ]
    }
    assert yrs._apply_changes(state, ordinary, FIXED_TS, FIXED_NOW, _base_config()) == {
        "ongoing_interaction"
    }
    assert state["ongoing_interaction"]["mode"] == "ordinary"
    assert state["ongoing_interaction"]["label"] is None
    assert state["ongoing_interaction"]["updated_at"] == FIXED_TS


def test_apply_changes_respects_limit_truncation():
    state = yrs._default_document()["state"]
    changes = {
        "pending_actions_add": [
            {"value": {"action": "a"}, "source": "user_explicit", "confidence": 1.0},
            {"value": {"action": "b"}, "source": "user_explicit", "confidence": 1.0},
        ]
    }
    changed = yrs._apply_changes(
        state, changes, FIXED_TS, FIXED_NOW, _base_config(limits={"pending_actions": 1})
    )
    assert changed == {"pending_actions"}
    assert [item["action"] for item in state["pending_actions"]] == ["b"]


# --------------------------------------------------------------------------- #
# UIE 提取（异步）
# --------------------------------------------------------------------------- #

def test_extract_uie_changes_returns_empty_for_bad_config():
    assert _run(
        yrs._extract_uie_changes("text", {"clothing"}, {"uie": "oops"}, uie_extractor=_FakeUIE())
    ) == {}
    assert _run(
        yrs._extract_uie_changes(
            "text", {"clothing"}, {"uie": {"schema_by_field": "oops"}}, uie_extractor=_FakeUIE()
        )
    ) == {}
    assert _run(yrs._extract_uie_changes("text", set(), _uie_config(), uie_extractor=_FakeUIE())) == {}
    # 字段没有配置 schema 时直接返回
    assert _run(
        yrs._extract_uie_changes("text", {"unknown"}, _uie_config(), uie_extractor=_FakeUIE())
    ) == {}


def test_extract_uie_changes_accepts_above_threshold_items():
    text = "我身上是白T恤。"
    fake = _FakeUIE({"衣服": [{"text": "白T恤", "probability": 0.9, "start": 4, "end": 6}]})
    changes = _run(
        yrs._extract_uie_changes(text, {"clothing"}, _uie_config(), uie_extractor=fake)
    )
    assert fake.calls == [(text, ("衣服",))]
    assert changes["clothing"] == [
        {"value": "白T恤", "source": "assistant_uie", "confidence": 0.9}
    ]


def test_extract_uie_changes_filters_low_probability_and_non_mapping():
    text = "我身上是白T恤。"
    fake = _FakeUIE(
        {
            "衣服": [
                {"text": "白T恤", "probability": 0.2, "start": 4, "end": 6},
                "not a mapping",
                {"text": "", "probability": 0.99, "start": 4, "end": 6},
            ]
        }
    )
    assert _run(
        yrs._extract_uie_changes(text, {"clothing"}, _uie_config(), uie_extractor=fake)
    ) == {}


def test_extract_uie_changes_tolerates_non_mapping_result():
    fake = _FakeUIE(result=["not", "a", "mapping"])
    assert _run(
        yrs._extract_uie_changes("我身上是白T恤。", {"clothing"}, _uie_config(), uie_extractor=fake)
    ) == {}


def test_extract_uie_changes_swallows_extractor_errors():
    fake = _FakeUIE(error=RuntimeError("模型不可用"))
    assert _run(
        yrs._extract_uie_changes("我身上是白T恤。", {"clothing"}, _uie_config(), uie_extractor=fake)
    ) == {}


def test_extract_uie_changes_defaults_threshold_when_zero():
    text = "我身上是白T恤。"
    config = _uie_config(
        uie={"enabled": True, "min_probability": 0, "schema_by_field": {"clothing": ["衣服"]}}
    )
    fake = _FakeUIE({"衣服": [{"text": "白T恤", "probability": 0.4, "start": 4, "end": 6}]})
    # min_probability=0 会被 `or 0.5` 归回默认 0.5，0.4 因此被过滤
    assert _run(yrs._extract_uie_changes(text, {"clothing"}, config, uie_extractor=fake)) == {}


def test_extract_uie_changes_dedupes_schemas():
    config = _uie_config(
        uie={
            "enabled": True,
            "min_probability": 0.5,
            "schema_by_field": {"location": ["地点"], "activity": ["地点", "活动内容"]},
        }
    )
    fake = _FakeUIE({})
    _run(yrs._extract_uie_changes("我在图书馆", {"location", "activity"}, config, uie_extractor=fake))
    assert len(fake.calls) == 1
    assert set(fake.calls[0][1]) == {"地点", "活动内容"}


def test_extract_uie_changes_resolves_default_extractor(monkeypatch):
    import core.services.data_ops.uie_extractor as uie_mod

    text = "我身上是白T恤。"
    fake = _FakeUIE({"衣服": [{"text": "白T恤", "probability": 0.9, "start": 4, "end": 6}]})
    monkeypatch.setattr(uie_mod, "get_uie_extractor", lambda: fake)
    changes = _run(
        yrs._extract_uie_changes(text, {"clothing"}, _uie_config(), uie_extractor=None)
    )
    assert changes["clothing"][0]["value"] == "白T恤"
    assert fake.calls


# --------------------------------------------------------------------------- #
# 现场状态工具写回
# --------------------------------------------------------------------------- #

def test_update_character_scene_state_disabled(monkeypatch):
    monkeypatch.setattr(
        yrs, "_load_default_config", lambda: {"enabled": False, "scene_write_mode": "tool"}
    )
    result = _run(
        yrs.update_character_scene_state(
            conversation_id="cid",
            persona_filename="core_ye.json",
            updates={"location": "宿舍"},
            evidence="测试",
        )
    )
    assert result == {"ok": False, "error": "角色现场状态工具未启用"}


def test_update_character_scene_state_wrong_write_mode(monkeypatch):
    monkeypatch.setattr(
        yrs, "_load_default_config", lambda: {"enabled": True, "scene_write_mode": "automatic"}
    )
    result = _run(
        yrs.update_character_scene_state(
            conversation_id="cid",
            persona_filename="core_ye.json",
            updates={"location": "宿舍"},
            evidence="测试",
        )
    )
    assert result["ok"] is False


def test_update_character_scene_state_rejects_non_ye(monkeypatch):
    monkeypatch.setattr(
        yrs,
        "_load_default_config",
        lambda: {"enabled": True, "scene_write_mode": "tool", "scope": "ye"},
    )
    monkeypatch.setattr(yrs, "_is_ye_turn", lambda *args, **kwargs: False)
    result = _run(
        yrs.update_character_scene_state(
            conversation_id="cid",
            persona_filename="core_ye.json",
            updates={"location": "宿舍"},
            evidence="测试",
        )
    )
    assert result == {"ok": False, "error": "当前角色未配置现场状态存储"}


def test_update_character_scene_state_validates_updates(monkeypatch, tmp_path):
    _patch_tool_config(monkeypatch, tmp_path)
    cases = (
        {},
        {"location": "宿舍", "unknown": "x"},
        {"location": 123},
        {"location": "   "},
        {"location": "长" * 241},
    )
    for updates in cases:
        with pytest.raises(ValueError):
            _run(
                yrs.update_character_scene_state(
                    conversation_id="cid",
                    persona_filename="core_ye.json",
                    updates=updates,
                    evidence="依据",
                )
            )


def test_update_character_scene_state_validates_evidence(monkeypatch, tmp_path):
    _patch_tool_config(monkeypatch, tmp_path)
    for bad in (None, "", "   ", "长" * 301):
        with pytest.raises(ValueError):
            _run(
                yrs.update_character_scene_state(
                    conversation_id="cid",
                    persona_filename="core_ye.json",
                    updates={"location": "宿舍"},
                    evidence=bad,
                )
            )


def test_update_character_scene_state_creates_default_document(monkeypatch, tmp_path):
    target = _patch_tool_config(monkeypatch, tmp_path)
    result = _run(
        yrs.update_character_scene_state(
            conversation_id="shared__persona__ye",
            persona_filename="core_ye.json",
            updates={"location": "宿舍", "activity": "看论文"},
            evidence=" 主人看到Ye在宿舍 ",
        )
    )
    assert result["ok"] is True
    assert result["updated"] is True
    assert result["fields"] == ["location", "activity"]
    assert result["state"]["location"] == {
        "value": "宿舍", "source": "llm_tool",
        "updated_at": FIXED_TS, "confidence": None,
    }

    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["state"]["location"]["value"] == "宿舍"
    assert document["state"]["activity"]["value"] == "看论文"
    assert document["state"]["physical_state"] == {}
    assert document["updated_at"] == FIXED_TS
    assert document["runtime_meta"]["last_tool_update"] == {
        "conversation_id": "shared__persona__ye",
        "fields": ["location", "activity"],
        "evidence": "主人看到Ye在宿舍",
        "updated_at": FIXED_TS,
    }


def test_update_character_scene_state_no_change_does_not_write(monkeypatch, tmp_path):
    target = _patch_tool_config(monkeypatch, tmp_path)
    original = {"character": "ye", "state": {"location": {"value": "宿舍"}}}
    target.write_text(json.dumps(original), encoding="utf-8")
    result = _run(
        yrs.update_character_scene_state(
            conversation_id="cid",
            persona_filename="core_ye.json",
            updates={"location": "宿舍"},
            evidence="重复",
        )
    )
    assert result == {
        "ok": True,
        "updated": False,
        "fields": [],
        "state": {"location": {"value": "宿舍"}},
    }
    assert json.loads(target.read_text(encoding="utf-8")) == original


def test_update_character_scene_state_clears_with_null(monkeypatch, tmp_path):
    target = _patch_tool_config(monkeypatch, tmp_path)
    # 旧值可能是裸字符串（历史格式），此时走 isinstance 的 else 分支
    target.write_text(json.dumps({"state": {"location": "宿舍"}}), encoding="utf-8")
    result = _run(
        yrs.update_character_scene_state(
            conversation_id="cid",
            persona_filename="core_ye.json",
            updates={"location": None},
            evidence="Ye离开了宿舍",
        )
    )
    assert result["fields"] == ["location"]
    assert result["state"]["location"]["value"] is None
    assert json.loads(target.read_text(encoding="utf-8"))["state"]["location"]["value"] is None


def test_update_character_scene_state_rejects_corrupt_document(monkeypatch, tmp_path):
    target = _patch_tool_config(monkeypatch, tmp_path)
    for payload in (["not", "a", "dict"], {"state": "oops"}):
        target.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="已有角色状态格式异常"):
            _run(
                yrs.update_character_scene_state(
                    conversation_id="cid",
                    persona_filename="core_ye.json",
                    updates={"location": "宿舍"},
                    evidence="依据",
                )
            )


def test_update_character_scene_state_propagates_broken_json(monkeypatch, tmp_path):
    """损坏的 JSON 视为拒绝覆盖，而不是当成空状态重建。"""
    target = _patch_tool_config(monkeypatch, tmp_path)
    target.write_text("{ not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        _run(
            yrs.update_character_scene_state(
                conversation_id="cid",
                persona_filename="core_ye.json",
                updates={"location": "宿舍"},
                evidence="依据",
            )
        )


# --------------------------------------------------------------------------- #
# 每轮对话后的状态写回
# --------------------------------------------------------------------------- #

def test_after_turn_disabled_and_not_ye(tmp_path):
    state_path = tmp_path / "s.json"
    disabled = _run(
        yrs.update_ye_runtime_state_after_turn(
            conversation_id="shared__persona__ye",
            user_text="你好",
            assistant_text="你好",
            state_path=state_path,
            config=_base_config(enabled=False),
        )
    )
    assert disabled == {"updated": False, "skipped": "disabled", "fields": []}

    not_ye = _run(
        yrs.update_ye_runtime_state_after_turn(
            conversation_id="shared__persona__aveline",
            user_text="你好",
            assistant_text="你好",
            state_path=state_path,
            config=_base_config(),
        )
    )
    assert not_ye == {"updated": False, "skipped": "not_ye", "fields": []}
    assert not state_path.exists()


def test_after_turn_empty_texts(tmp_path):
    result = _run(
        yrs.update_ye_runtime_state_after_turn(
            conversation_id="shared__persona__ye",
            user_text="   ",
            assistant_text="\n",
            state_path=tmp_path / "s.json",
            config=_base_config(),
        )
    )
    assert result == {"updated": False, "skipped": "empty", "fields": []}


def test_after_turn_duplicate_message_id(tmp_path):
    state_path = tmp_path / "s.json"
    kwargs = dict(
        conversation_id="shared__persona__ye",
        persona_filename="core_ye.json",
        user_text="进入私密模式",
        assistant_text="好。",
        message_id="m-1",
        state_path=state_path,
        config=_base_config(),
    )
    first = _run(yrs.update_ye_runtime_state_after_turn(**kwargs))
    assert first["updated"] is True

    second = _run(yrs.update_ye_runtime_state_after_turn(**kwargs))
    assert second == {"updated": False, "skipped": "duplicate", "fields": []}


def test_after_turn_no_change_returns_no_change(tmp_path):
    state_path = tmp_path / "s.json"
    result = _run(
        yrs.update_ye_runtime_state_after_turn(
            conversation_id="shared__persona__ye",
            persona_filename="core_ye.json",
            user_text="你好",
            assistant_text="你好",
            state_path=state_path,
            config=_base_config(),
        )
    )
    assert result == {"updated": False, "skipped": "no_change", "fields": []}
    assert not state_path.exists()


def test_after_turn_writes_rule_changes(tmp_path):
    state_path = tmp_path / "s.json"
    result = _run(
        yrs.update_ye_runtime_state_after_turn(
            conversation_id="shared__persona__ye",
            persona_filename="core_ye.json",
            user_text="你现在在图书馆吗？",
            assistant_text="对，我在图书馆看论文，有点困。",
            message_id="m-1",
            state_path=state_path,
            config=_base_config(),
        )
    )
    assert result["updated"] is True
    assert result["skipped"] is None
    assert result["state_path"] == str(state_path)
    assert set(result["fields"]) >= {"location", "activity", "physical_state"}
    assert result["uie_fields"] == []
    assert result["uie_values"] == {}

    document = json.loads(state_path.read_text(encoding="utf-8"))
    assert document["state"]["location"]["value"] == "图书馆"
    assert document["state"]["activity"]["value"] == "看论文"
    assert document["state"]["physical_state"]["value"] == "困"
    assert document["runtime_meta"]["processed_message_ids"] == ["m-1"]
    assert document["runtime_meta"]["last_message_id"] == "m-1"
    assert document["runtime_meta"]["last_processed_at"] == FIXED_TS
    assert document["updated_at"] == FIXED_TS


def test_after_turn_with_uie_extractor(tmp_path):
    state_path = tmp_path / "s.json"
    fake = _FakeUIE(
        {"衣服": [{"text": "白T恤和牛仔裤", "probability": 0.9, "start": 4, "end": 10}]}
    )
    result = _run(
        yrs.update_ye_runtime_state_after_turn(
            conversation_id="shared__persona__ye",
            persona_filename="core_ye.json",
            user_text="你今天穿什么？",
            assistant_text="我身上是白T恤和牛仔裤。",
            message_id="uie-1",
            state_path=state_path,
            config=_uie_config(),
            uie_extractor=fake,
        )
    )
    assert result["uie_fields"] == ["clothing"]
    assert result["uie_values"] == {"clothing": "白T恤和牛仔裤"}
    assert fake.calls

    document = json.loads(state_path.read_text(encoding="utf-8"))
    assert document["state"]["clothing"]["value"] == "白T恤和牛仔裤"
    assert document["state"]["clothing"]["source"] == "assistant_uie"


def test_after_turn_resolves_path_from_config(tmp_path):
    target = tmp_path / "nested" / "state.json"
    result = _run(
        yrs.update_ye_runtime_state_after_turn(
            conversation_id="shared__persona__ye",
            persona_filename="core_ye.json",
            user_text="进入私密模式",
            assistant_text="好。",
            message_id="cfg-1",
            config=_base_config(runtime_state_path=str(target)),
        )
    )
    assert result["state_path"] == str(target)
    assert target.is_file()


def test_after_turn_falls_back_to_default_config(tmp_path):
    """未传 config 时读取真实默认配置（scene_write_mode=tool）。"""
    state_path = tmp_path / "s.json"
    result = _run(
        yrs.update_ye_runtime_state_after_turn(
            conversation_id="shared__persona__ye",
            persona_filename="core_ye.json",
            user_text="进入私密模式",
            assistant_text="好。",
            message_id="default-cfg",
            state_path=state_path,
        )
    )
    assert result["updated"] is True
    document = json.loads(state_path.read_text(encoding="utf-8"))
    assert document["state"]["ongoing_interaction"]["mode"] == "private"


def test_after_turn_recovers_from_non_dict_document(tmp_path):
    state_path = tmp_path / "s.json"
    state_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    result = _run(
        yrs.update_ye_runtime_state_after_turn(
            conversation_id="shared__persona__ye",
            persona_filename="core_ye.json",
            user_text="进入私密模式",
            assistant_text="好。",
            message_id="recover",
            state_path=state_path,
            config=_base_config(),
        )
    )
    assert result["updated"] is True
    document = json.loads(state_path.read_text(encoding="utf-8"))
    assert document["character"] == "ye"
    assert document["state"]["ongoing_interaction"]["mode"] == "private"


def test_after_turn_prunes_expired_rules(tmp_path):
    state_path = tmp_path / "s.json"
    state_path.write_text(
        json.dumps(
            {
                "state": {
                    "active_rules": [
                        {"type": "borrow", "target": "腿", "expires_at": "2026-09-01T14:00+08:00"}
                    ],
                    "time_constraints": [
                        {"label": "x", "expires_at": "2026-09-01T14:00+08:00"}
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    result = _run(
        yrs.update_ye_runtime_state_after_turn(
            conversation_id="shared__persona__ye",
            persona_filename="core_ye.json",
            user_text="嗯。",
            assistant_text="嗯。",
            state_path=state_path,
            config=_base_config(),
        )
    )
    assert result["updated"] is True
    assert set(result["fields"]) == {"active_rules", "time_constraints"}
    document = json.loads(state_path.read_text(encoding="utf-8"))
    assert document["state"]["active_rules"] == []
    assert document["state"]["time_constraints"] == []


def test_after_turn_truncates_processed_message_ids(tmp_path):
    state_path = tmp_path / "s.json"
    config = _base_config(limits={"processed_message_ids": 2})
    for index in range(3):
        _run(
            yrs.update_ye_runtime_state_after_turn(
                conversation_id="shared__persona__ye",
                persona_filename="core_ye.json",
                user_text="进入私密模式",
                assistant_text="好。",
                message_id=f"m-{index}",
                state_path=state_path,
                config=config,
            )
        )
    document = json.loads(state_path.read_text(encoding="utf-8"))
    assert document["runtime_meta"]["processed_message_ids"] == ["m-1", "m-2"]
    assert document["runtime_meta"]["last_message_id"] == "m-2"


def test_after_turn_uses_current_time_when_now_missing(tmp_path):
    state_path = tmp_path / "s.json"
    result = _run(
        yrs.update_ye_runtime_state_after_turn(
            conversation_id="shared__persona__ye",
            persona_filename="core_ye.json",
            user_text="进入私密模式",
            assistant_text="好。",
            message_id="clock",
            state_path=state_path,
            config=_base_config(),
        )
    )
    assert result["updated"] is True
    document = json.loads(state_path.read_text(encoding="utf-8"))
    assert document["updated_at"] == FIXED_TS
    assert document["state"]["ongoing_interaction"]["started_at"] == FIXED_TS
