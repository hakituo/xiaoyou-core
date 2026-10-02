"""单元测试：core/utils/data/data_paths.py —— scope 解析与共享会话 ID。

覆盖：委托入口是否原样透传参数、persona slug/别名 → scope、共享
conversation_id 构造（含哈希兜底）、chat_history 根遍历、daily event 的
scope 归属解析。

所有 IO 落 tmp_path，不触碰真实 companion_data；路径断言全部基于注入的临时根。
"""
from __future__ import annotations

import hashlib
import json

import pytest

from core.utils.data import data_paths as dp
from core.utils.data.scope_registry import get_registered_role_scopes


@pytest.fixture()
def debug_on(monkeypatch):
    """打开 data_paths 的 debug 日志开关，用于覆盖调试日志分支。"""
    monkeypatch.setattr(dp, "is_debug_enabled", lambda module: True)


# ────────────────────────── 委托入口：证明参数原样透传 ──────────────────────────


def test_normalize_data_scope_delegates(monkeypatch):
    """normalize_data_scope 把 scope / default 原样交给注册表实现。"""
    calls = []

    def fake(scope, *, default="user"):
        calls.append((scope, default))
        return "SENTINEL"

    monkeypatch.setattr(dp, "_normalize_registered_scope", fake)
    assert dp.normalize_data_scope("ling", default="dual_role") == "SENTINEL"
    assert calls == [("ling", "dual_role")]


def test_resolve_conversation_scope_delegates(monkeypatch):
    """resolve_data_scope_from_conversation_id 透传 cid 与 default。"""
    calls = []

    def fake(conversation_id, *, default):
        calls.append((conversation_id, default))
        return "SENTINEL"

    monkeypatch.setattr(dp, "_resolve_registered_conversation_scope", fake)
    assert dp.resolve_data_scope_from_conversation_id("cid", default="user") == "SENTINEL"
    assert calls == [("cid", "user")]


def test_resolve_scope_from_persona_slug_delegates(monkeypatch):
    """_resolve_scope_from_persona_slug 走注册表 slug 解析。"""
    calls = []
    monkeypatch.setattr(dp, "resolve_persona_slug_scope", lambda s: calls.append(s) or "SENTINEL")
    assert dp._resolve_scope_from_persona_slug("core_ling") == "SENTINEL"
    assert calls == ["core_ling"]


def test_resolve_scope_from_active_persona_delegates(monkeypatch):
    """_resolve_scope_from_active_persona 走注册表活跃 persona 解析。"""
    calls = []
    monkeypatch.setattr(
        dp, "_resolve_registered_active_persona_scope", lambda: calls.append(1) or "SENTINEL"
    )
    assert dp._resolve_scope_from_active_persona() == "SENTINEL"
    assert calls == [1]


def test_resolve_memory_user_id_delegates(monkeypatch):
    """resolve_memory_user_id 透传 conversation_id。"""
    calls = []
    monkeypatch.setattr(dp, "_resolve_registered_memory_user_id", lambda c: calls.append(c) or "SENTINEL")
    assert dp.resolve_memory_user_id("cid") == "SENTINEL"
    assert calls == ["cid"]


def test_resolve_data_scope_from_source_delegates(monkeypatch):
    """resolve_data_scope_from_source 透传 source 与 default。"""
    calls = []

    def fake(source, *, default):
        calls.append((source, default))
        return "SENTINEL"

    monkeypatch.setattr(dp, "_resolve_registered_source_scope", fake)
    assert dp.resolve_data_scope_from_source("ling", default="aveline") == "SENTINEL"
    assert calls == [("ling", "aveline")]


# ────────────────────────── 真实注册表行为 ──────────────────────────


def test_get_role_scopes_matches_registry():
    """_get_role_scopes 等价于注册表角色 scope 集合。"""
    assert dp._get_role_scopes() == get_registered_role_scopes()
    assert {"aveline", "ling"} <= dp._get_role_scopes()


def test_get_valid_scopes_adds_special():
    """_get_valid_scopes = 角色 scope + user/dual_role。"""
    assert dp._get_valid_scopes() == dp._get_role_scopes() | {"user", "dual_role"}


@pytest.mark.parametrize(("scope", "expected"), [("aveline", "aveline_data"), ("x", "x_data")])
def test_role_data_dir_name(scope, expected):
    """目录名统一为 {scope}_data。"""
    assert dp._role_data_dir_name(scope) == expected


@pytest.mark.parametrize(
    ("scope", "default", "expected"),
    [
        ("ling", "user", "ling"),
        (None, "user", "user"),
        (None, "aveline", "aveline"),
    ],
)
def test_normalize_data_scope_real(scope, default, expected):
    """真实注册表下的归一化结果。"""
    assert dp.normalize_data_scope(scope, default=default) == expected


def test_resolve_conversation_scope_real():
    """cid 能解析出角色；None 走默认角色。"""
    assert dp.resolve_data_scope_from_conversation_id("core_ling") == "ling"
    assert dp.resolve_data_scope_from_conversation_id(None) == "aveline"


def test_resolve_source_and_memory_user_id_real():
    """source 解析与 memory user_id 归一化。"""
    assert dp.resolve_data_scope_from_source("ling") == "ling"
    assert dp.resolve_memory_user_id("core_ling") == "shared__scope__ling"
    assert dp._resolve_scope_from_persona_slug("core_ling") == "ling"


# ────────────────────────── build_shared_persona_conversation_id ──────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", "shared"),
        (None, "shared"),
        ("   ", "shared"),
        ("aveline.json", "shared__persona__aveline"),
        ("core/character/configs/aveline.json", "shared__persona__aveline"),
        (r"core\character\ling.json", "shared__persona__ling"),
        ("七濑 Aveline.json", "shared__persona__七濑_Aveline"),
        ("My Role!!.json", "shared__persona__my_role"),
    ],
)
def test_build_shared_persona_conversation_id(raw, expected):
    """空值返回 shared；其余按 slug 归一化。"""
    assert dp.build_shared_persona_conversation_id(raw) == expected


def test_build_shared_persona_conversation_id_digest_fallback():
    """slug 被清洗为空时用 md5 前 8 位兜底（基于归一化后的整串）。"""
    digest = hashlib.md5(b"###").hexdigest()[:8]
    assert dp.build_shared_persona_conversation_id("###") == f"shared__persona__persona_{digest}"


# ────────────────────────── chat_history 根遍历 ──────────────────────────


def test_iter_existing_chat_history_roots_only_existing(tmp_path, monkeypatch):
    """只产出实际存在的 chat_history 根（user 与角色）。"""
    monkeypatch.setattr(dp, "_get_role_scopes", lambda: {"aveline", "ling"})
    base = tmp_path / "companion_data"
    (base / "user_data" / "chat_history").mkdir(parents=True)
    (base / "ling_data" / "chat_history").mkdir(parents=True)
    roots = set(dp._iter_existing_chat_history_roots(base))
    assert roots == {
        (base / "user_data" / "chat_history").resolve(),
        (base / "ling_data" / "chat_history").resolve(),
    }


def test_iter_existing_chat_history_roots_none(tmp_path, monkeypatch):
    """一个都不存在时产出空序列。"""
    monkeypatch.setattr(dp, "_get_role_scopes", lambda: {"aveline"})
    base = tmp_path / "companion_data"
    base.mkdir()
    assert list(dp._iter_existing_chat_history_roots(base)) == []


# ────────────────────────── 聊天记录路径 → scope ──────────────────────────


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (["Ling", "c.jsonl"], "ling"),
        (["LING", "c.jsonl"], "ling"),
        (["other", "c.jsonl"], "aveline"),
        ([None, "", "other"], "aveline"),
        ([], "aveline"),
    ],
)
def test_resolve_scope_from_chat_history_path(parts, expected):
    """含「Ling」/ling 判 ling，其余归 aveline，空片段被过滤。"""
    assert dp._resolve_scope_from_chat_history_path(parts) == expected


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (["a", "b", "c", "d", "e"], ["a", "b", "c", "e"]),
        ([None, "a", "b"], ["a", "b"]),
        (["a", "b", "c", "d"], ["a", "b", "c", "d"]),
        ([], []),
    ],
)
def test_target_chat_history_parts(parts, expected):
    """层级 >= 5 时去掉第 4 段（索引 3），否则原样（过滤空片段）。"""
    assert dp._target_chat_history_parts(parts) == expected


# ────────────────────────── daily event → scope ──────────────────────────


def test_split_daily_event_scope_invalid_json_default(debug_on):
    """非法 JSON 返回默认 scope。"""
    assert dp._split_daily_event_scope("not json", default_scope="aveline") == "aveline"


def test_split_daily_event_scope_non_dict_default():
    """JSON 不是对象时返回默认 scope。"""
    assert dp._split_daily_event_scope("[1, 2]", default_scope="ling") == "ling"


def test_split_daily_event_scope_delegates_conversation_id(monkeypatch):
    """有 conversation_id 时交给 conversation 解析器并透传 default。"""
    calls = []
    monkeypatch.setattr(
        dp,
        "resolve_data_scope_from_conversation_id",
        lambda cid, *, default: calls.append((cid, default)) or "SENTINEL",
    )
    line = json.dumps({"conversation_id": "cid1"})
    assert dp._split_daily_event_scope(line, default_scope="aveline") == "SENTINEL"
    assert calls == [("cid1", "aveline")]


def test_split_daily_event_scope_delegates_source(monkeypatch):
    """无 conversation_id 时交给 source 解析器并透传 default。"""
    calls = []
    monkeypatch.setattr(
        dp,
        "resolve_data_scope_from_source",
        lambda src, *, default: calls.append((src, default)) or "SENTINEL",
    )
    line = json.dumps({"source": "ling"})
    assert dp._split_daily_event_scope(line, default_scope="user") == "SENTINEL"
    assert calls == [("ling", "user")]


def test_split_daily_event_scope_real_and_empty():
    """两个字段都为空走默认；真实注册表下能解析出角色。"""
    assert dp._split_daily_event_scope("{}", default_scope="aveline") == "aveline"
    assert dp._split_daily_event_scope(json.dumps({"conversation_id": "core_ling"}), default_scope="aveline") == "ling"
    assert dp._split_daily_event_scope(json.dumps({"source": "ling"}), default_scope="aveline") == "ling"
