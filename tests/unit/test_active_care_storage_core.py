"""ActiveCareStorage 存储层单元测试。

覆盖目标：``core/services/active_care/storage/storage.py``

约定：
- 数据目录统一指向 pytest 的 ``tmp_path``（替换模块级 ``get_active_care_dir``），
  绝不写入真实 ``companion_data/``。
- 时间戳全部注入可控值，不依赖真实当前时间；不 sleep、不依赖随机。
- 异步方法统一用「同步测试函数 + ``asyncio.run``」驱动（仓库惯例）。
- 共享的类级 ``_user_profile_cache`` 在用例前后清理，避免跨用例污染。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import core.character.managers.persona_manager as persona_manager_module
import core.utils.data.scope_registry as scope_registry_module
from core.services.active_care.shared.state_keys import StateKeys
from core.services.active_care.storage import storage as storage_module
from core.services.active_care.storage.storage import ActiveCareStorage


def _run(coro):
    """用新事件循环驱动协程（仓库惯例）。"""
    return asyncio.run(coro)


def _write_json(path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@pytest.fixture()
def ac(tmp_path, monkeypatch):
    """把 Active Care 数据目录重定向到 tmp_path，并隔离共享类缓存。"""
    root = tmp_path / "companion_data"

    def _fake_get_active_care_dir(scope=None):
        d = root / str(scope or "aveline")
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr(
        storage_module, "get_active_care_dir", _fake_get_active_care_dir
    )
    ActiveCareStorage._user_profile_cache.clear()
    inst = ActiveCareStorage()
    yield inst, root
    ActiveCareStorage._user_profile_cache.clear()


# ==================== 构造 / scope ====================


def test_init_state_defaults(ac):
    inst, _ = ac
    assert inst.get_runtime_scope() == "aveline"
    assert inst._proactive_state_cache is None
    assert inst._user_sleep_state_cache is None
    assert inst._policy_scores == {}
    assert inst._proactive_count_cache is None
    assert inst._pending_updates == {}
    assert inst._flush_task is None
    assert inst._dirty is False
    assert inst._flush_interval == 2.0


def test_set_runtime_scope_normalizes_and_resets_caches(ac):
    inst, _ = ac
    inst._proactive_state_cache = {"a": 1}
    inst._policy_scores = {"b": 2}
    inst._proactive_count_cache = {"c": 3}

    inst.set_runtime_scope("  YEYE ")

    assert inst.get_runtime_scope() == "yeye"
    assert inst._proactive_state_cache is None
    assert inst._policy_scores == {}
    assert inst._proactive_count_cache is None


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_set_runtime_scope_blank_falls_back_to_aveline(ac, raw):
    inst, _ = ac
    inst.set_runtime_scope(raw)
    assert inst.get_runtime_scope() == "aveline"


def test_set_runtime_scope_same_value_keeps_caches(ac):
    inst, _ = ac
    inst.set_runtime_scope("ling")
    inst._proactive_state_cache = {"keep": True}
    inst.set_runtime_scope("LING")
    assert inst.get_runtime_scope() == "ling"
    assert inst._proactive_state_cache == {"keep": True}


def test_persona_token_helpers(ac):
    inst, _ = ac
    assert (
        inst._normalize_persona_token_from_filename("personas\\Wang_Ling.JSON")
        == "ling"
    )
    assert inst._extract_persona_token("qq__persona__yeye__123") == "yeye"
    assert inst._extract_persona_token("no-marker-here") == ""


# ==================== resolve_scope_from_persona_filename ====================


def test_resolve_scope_persona_filename_registry_hit(ac, monkeypatch):
    inst, _ = ac
    monkeypatch.setattr(
        scope_registry_module, "resolve_persona_slug_scope", lambda slug: "chiba"
    )
    assert inst.resolve_scope_from_persona_filename("whatever.json") == "chiba"


def test_resolve_scope_persona_filename_registry_error_falls_back(ac, monkeypatch):
    inst, _ = ac

    def _boom(slug):
        raise RuntimeError("registry down")

    monkeypatch.setattr(scope_registry_module, "resolve_persona_slug_scope", _boom)
    assert inst.resolve_scope_from_persona_filename("yeye.json") == "yeye"


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("ling.json", "ling"),
        ("aveline.json", "aveline"),
        ("Aveline.json", "aveline"),
        ("yeye.json", "yeye"),
        ("Coco.json", "yeye"),
        ("susuomu.json", "yeye"),
        ("xiaolu.json", "xiaolu"),
        ("Fawn.json", "xiaolu"),
        ("rushuang.json", "rushuang"),
        ("Frost.json", "rushuang"),
        ("shenrushuang.json", "rushuang"),
        ("mianmian.json", "mianmian"),
        ("Mian.json", "mianmian"),
        ("yemian.json", "mianmian"),
        ("叶眠.json", "mianmian"),
        ("chiba.json", "chiba"),
        ("Chiba.json", "chiba"),
        ("Chiba.json", "chiba"),
        ("nobody.json", "aveline"),
        ("", "aveline"),
    ],
)
def test_resolve_scope_persona_filename_name_fallback(
    ac, monkeypatch, filename, expected
):
    inst, _ = ac
    monkeypatch.setattr(
        scope_registry_module, "resolve_persona_slug_scope", lambda slug: ""
    )
    assert inst.resolve_scope_from_persona_filename(filename) == expected


# ==================== resolve_scope_from_conversation_id ====================


def _patch_conversation_scope(monkeypatch, result="", *, raise_error=False):
    if raise_error:

        def _resolver(conversation_id, default=""):
            raise RuntimeError("registry down")

    else:

        def _resolver(conversation_id, default=""):
            return result

    monkeypatch.setattr(
        scope_registry_module, "resolve_data_scope_from_conversation_id", _resolver
    )


@pytest.mark.parametrize(
    "cid,expected",
    [
        ("", "aveline"),
        ("plain-conversation", "aveline"),
        ("user__scope__ling", "ling"),
        ("user__scope__bogus", "aveline"),
        ("x__persona__yeye", "yeye"),
        ("x_yeye", "yeye"),
        ("x__persona__xiaolu", "xiaolu"),
        ("x_xiaolu", "xiaolu"),
        ("x__persona__rushuang", "rushuang"),
        ("x_rushuang", "rushuang"),
        ("x__persona__mianmian", "mianmian"),
        ("x_mianmian", "mianmian"),
        ("x__persona__chiba", "chiba"),
        ("x_chiba", "chiba"),
        ("x__persona__Frost", "rushuang"),
        ("x_Mian", "mianmian"),
        ("x_Chiba", "chiba"),
        # 繁体「Chiba」不会命中上面 `"_Chiba" in cid` 的检查（字形不同），
        # 只能靠 token 集合里的 "Chiba" 兜底 —— 专门钉住 storage.py:186 这一行。
        ("x__persona__Chiba", "chiba"),
        ("x__persona__core_ling", "ling"),
    ],
)
def test_resolve_scope_conversation_markers(ac, monkeypatch, cid, expected):
    inst, _ = ac
    _patch_conversation_scope(monkeypatch, "")
    assert inst.resolve_scope_from_conversation_id(cid) == expected


def test_resolve_scope_conversation_registry_hit(ac, monkeypatch):
    inst, _ = ac
    _patch_conversation_scope(monkeypatch, "mianmian")
    assert inst.resolve_scope_from_conversation_id("anything") == "mianmian"


@pytest.mark.parametrize("generic", ["", "user", "aveline"])
def test_resolve_scope_conversation_registry_generic_falls_through(
    ac, monkeypatch, generic
):
    inst, _ = ac
    _patch_conversation_scope(monkeypatch, generic)
    assert inst.resolve_scope_from_conversation_id("x__persona__chiba") == "chiba"


def test_resolve_scope_conversation_registry_error_falls_back(ac, monkeypatch):
    inst, _ = ac
    _patch_conversation_scope(monkeypatch, raise_error=True)
    assert inst.resolve_scope_from_conversation_id("x__persona__yeye") == "yeye"


class _FakePersonaManager:
    def __init__(self, personas, configs):
        self._personas = personas
        self._configs = configs

    def list_personas(self):
        return self._personas

    def get_persona_by_filename(self, filename):
        return self._configs.get(filename)


def _patch_persona_manager(monkeypatch, personas, configs):
    monkeypatch.setattr(
        persona_manager_module,
        "get_persona_manager",
        lambda: _FakePersonaManager(personas, configs),
    )
    _patch_conversation_scope(monkeypatch, "")


@pytest.mark.parametrize(
    "cn_name,name,expected",
    [
        ("Ling", "", "ling"),
        ("", "yeye", "yeye"),
        ("Muqing", "", "yeye"),
        ("林知夏", "", "xiaolu"),
        ("", "xiaolu", "xiaolu"),
        ("沈Frost", "", "rushuang"),
        ("", "rushuang", "rushuang"),
        ("叶眠", "", "mianmian"),
        ("", "mianmian", "mianmian"),
        ("Chiba", "", "chiba"),
        ("", "chiba", "chiba"),
        ("陌生人", "", "aveline"),
    ],
)
def test_resolve_scope_conversation_persona_manager(
    ac, monkeypatch, cn_name, name, expected
):
    inst, _ = ac
    _patch_persona_manager(
        monkeypatch,
        [{"filename": "zzz.json"}],
        {"zzz.json": {"identity": {"cn_name": cn_name, "name": name}}},
    )
    assert inst.resolve_scope_from_conversation_id("__persona__zzz") == expected


def test_resolve_scope_conversation_persona_manager_skips_blank_filename(ac, monkeypatch):
    inst, _ = ac
    _patch_persona_manager(
        monkeypatch,
        [{"filename": ""}, {"filename": "zzz.json"}],
        {"zzz.json": {"identity": {"cn_name": "Ling"}}},
    )
    assert inst.resolve_scope_from_conversation_id("__persona__zzz") == "ling"


def test_resolve_scope_conversation_persona_manager_skips_token_mismatch(
    ac, monkeypatch
):
    inst, _ = ac
    _patch_persona_manager(
        monkeypatch,
        [{"filename": "other.json"}],
        {"other.json": {"identity": {"cn_name": "Ling"}}},
    )
    assert inst.resolve_scope_from_conversation_id("__persona__zzz") == "aveline"


def test_resolve_scope_conversation_persona_manager_non_dict_cfg(ac, monkeypatch):
    inst, _ = ac
    _patch_persona_manager(
        monkeypatch, [{"filename": "zzz.json"}], {"zzz.json": "not-a-dict"}
    )
    assert inst.resolve_scope_from_conversation_id("__persona__zzz") == "aveline"


def test_resolve_scope_conversation_persona_manager_error(ac, monkeypatch):
    inst, _ = ac
    _patch_conversation_scope(monkeypatch, "")

    def _boom():
        raise RuntimeError("persona manager down")

    monkeypatch.setattr(persona_manager_module, "get_persona_manager", _boom)
    assert inst.resolve_scope_from_conversation_id("__persona__zzz") == "aveline"


# ==================== 目录 / 想法读取 ====================


def test_get_runtime_dir_creates_dirs(ac):
    inst, root = ac
    default_dir = Path(inst._get_runtime_dir())
    assert default_dir.is_dir()
    assert default_dir == root / "aveline"

    scoped = Path(inst._get_runtime_dir("ling"))
    assert scoped.is_dir()
    assert scoped == root / "ling"


def test_get_last_thought_uses_cache(ac):
    inst, _ = ac
    inst._proactive_state_cache = {
        "last_thought": " 想你了 ",
        "last_sent_content": "hi",
        "last_sent_type": "share",
    }
    assert _run(inst.get_last_thought()) == {
        "last_thought": "想你了",
        "last_sent_content": "hi",
        "last_sent_type": "share",
    }


def test_get_last_thought_blank_thought_returns_empty(ac):
    inst, _ = ac
    inst._proactive_state_cache = {"last_thought": "   "}
    assert _run(inst.get_last_thought()) == {}


def test_get_last_thought_no_state_returns_empty(ac):
    inst, _ = ac
    assert _run(inst.get_last_thought()) == {}


def test_get_last_thought_loads_from_disk(ac):
    inst, root = ac
    _write_json(root / "aveline" / "proactive_state.json", {"last_thought": "from disk"})
    assert _run(inst.get_last_thought()) == {
        "last_thought": "from disk",
        "last_sent_content": "",
        "last_sent_type": "",
    }


def test_get_last_thought_swallows_errors(ac):
    inst, _ = ac
    inst._proactive_state_cache = ["not", "a", "dict"]
    assert _run(inst.get_last_thought()) == {}


def test_get_last_thought_sync_from_cache(ac):
    inst, _ = ac
    inst._proactive_state_cache = {
        "last_thought": "cached",
        "last_sent_content": "c",
        "last_sent_type": "t",
    }
    assert inst.get_last_thought_sync() == {
        "last_thought": "cached",
        "last_sent_content": "c",
        "last_sent_type": "t",
    }


def test_get_last_thought_sync_missing_file(ac):
    inst, _ = ac
    assert inst.get_last_thought_sync() == {}


def test_get_last_thought_sync_from_disk_caches(ac):
    inst, root = ac
    _write_json(root / "aveline" / "proactive_state.json", {"last_thought": "disk"})
    assert inst.get_last_thought_sync()["last_thought"] == "disk"
    assert inst._proactive_state_cache == {"last_thought": "disk"}


def test_get_last_thought_sync_blank_thought_returns_empty(ac):
    inst, root = ac
    _write_json(root / "aveline" / "proactive_state.json", {"last_thought": " "})
    assert inst.get_last_thought_sync() == {}


def test_get_last_thought_sync_swallows_errors(ac):
    inst, _ = ac
    inst._proactive_state_cache = ["bad"]
    assert inst.get_last_thought_sync() == {}


# ==================== JSON 读写 ====================


def test_read_json_file_variants(ac, tmp_path):
    inst, _ = ac
    assert _run(inst.read_json_file(str(tmp_path / "nope.json"))) == {}

    valid = tmp_path / "valid.json"
    _write_json(valid, {"k": "v"})
    assert _run(inst.read_json_file(str(valid))) == {"k": "v"}

    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    assert _run(inst.read_json_file(str(empty))) == {}

    blank = tmp_path / "blank.json"
    blank.write_text("   \n", encoding="utf-8")
    assert _run(inst.read_json_file(str(blank))) == {}

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert _run(inst.read_json_file(str(broken))) == {}

    directory = tmp_path / "adir"
    directory.mkdir()
    assert _run(inst.read_json_file(str(directory))) == {}


def test_write_json_file_roundtrip(ac, tmp_path):
    inst, _ = ac
    target = tmp_path / "out.json"
    _run(inst.write_json_file(str(target), {"a": 1, "中文": "值"}))
    assert _read_json(target) == {"a": 1, "中文": "值"}


def test_write_json_file_unlocked_swallows_errors(ac, tmp_path):
    inst, _ = ac
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    target = blocker / "sub.json"

    _run(inst._write_json_file_unlocked(str(target), {"a": 1}))

    assert not target.exists()


# ==================== proactive_state ====================


def test_get_proactive_state_scope_path(ac):
    inst, root = ac
    _write_json(root / "ling" / "proactive_state.json", {"last_thought": "ling"})
    state = _run(inst.get_proactive_state(scope="ling"))
    assert state["last_thought"] == "ling"
    assert inst._proactive_state_cache is None


def test_get_proactive_state_scope_missing_file(ac):
    inst, _ = ac
    assert _run(inst.get_proactive_state(scope="rushuang")) == {}


def test_get_proactive_state_scope_bad_payload_returns_empty(ac):
    inst, root = ac
    _write_json(root / "ling" / "proactive_state.json", [1, 2])
    assert _run(inst.get_proactive_state(scope="ling")) == {}


def test_get_proactive_state_caches_disk_state(ac):
    inst, root = ac
    _write_json(root / "aveline" / "proactive_state.json", {"last_thought": "hi"})
    assert _run(inst.get_proactive_state())["last_thought"] == "hi"
    assert inst._proactive_state_cache == {"last_thought": "hi"}


def test_get_proactive_state_prefers_cache(ac):
    inst, root = ac
    inst._proactive_state_cache = {"cached": 1}
    _write_json(root / "aveline" / "proactive_state.json", {"disk": 1})
    assert _run(inst.get_proactive_state())["cached"] == 1


def test_get_proactive_state_missing_file_sets_empty_cache(ac):
    inst, _ = ac
    assert _run(inst.get_proactive_state()) == {}
    assert inst._proactive_state_cache == {}


def test_save_proactive_state_immediate_flush(ac):
    inst, root = ac
    result = _run(inst.save_proactive_state({"last_thought": "hi"}, immediate=True))
    assert result["last_thought"] == "hi"
    assert _read_json(root / "aveline" / "proactive_state.json") == {"last_thought": "hi"}
    assert inst._dirty is False


def test_save_proactive_state_deferred_schedules_flush(ac):
    inst, _ = ac

    async def _scenario():
        result = await inst.save_proactive_state({"last_thought": "later"})
        task = inst._flush_task
        assert task is not None and not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return result

    result = _run(_scenario())
    assert result["last_thought"] == "later"
    assert inst._dirty is True
    assert inst._pending_updates["last_thought"] == "later"


def test_save_proactive_state_merges_existing_file(ac):
    inst, root = ac
    _write_json(root / "aveline" / "proactive_state.json", {"old": 1})
    assert _run(inst.save_proactive_state({"new": 2}, immediate=True)) == {
        "old": 1,
        "new": 2,
    }


def test_save_proactive_state_scope_write(ac):
    inst, root = ac
    result = _run(inst.save_proactive_state({"last_thought": "s"}, scope="ling"))
    assert result == {"last_thought": "s"}
    assert _read_json(root / "ling" / "proactive_state.json") == {"last_thought": "s"}


def test_save_proactive_state_scope_merges_existing(ac):
    inst, root = ac
    _write_json(root / "ling" / "proactive_state.json", {"old": 1})
    assert _run(inst.save_proactive_state({"new": 2}, scope="ling")) == {
        "old": 1,
        "new": 2,
    }


def test_save_proactive_state_scope_empty_removes_file(ac):
    inst, root = ac
    target = root / "ling" / "proactive_state.json"
    _write_json(target, {})
    assert _run(inst.save_proactive_state({}, scope="ling")) == {}
    assert not target.exists()


def test_save_proactive_state_scope_empty_without_file(ac):
    inst, _ = ac
    assert _run(inst.save_proactive_state({}, scope="ling")) == {}


def _patch_read_raises(monkeypatch, inst):
    """让下游读盘协作者抛异常，验证降级分支（不 patch 被测方法本身）。"""

    async def _boom(filepath):
        raise RuntimeError("read failed")

    monkeypatch.setattr(inst, "_read_json_file", _boom)


def test_get_proactive_state_non_scope_read_error_uses_empty_cache(ac, monkeypatch):
    inst, root = ac
    _write_json(root / "aveline" / "proactive_state.json", {"last_thought": "x"})
    # 预置用户级睡眠缓存，避免 _merge_user_sleep_state 触发 bootstrap 读盘
    inst._user_sleep_state_cache = {}
    _patch_read_raises(monkeypatch, inst)

    assert _run(inst.get_proactive_state()) == {}
    assert inst._proactive_state_cache == {}


def test_save_proactive_state_scope_read_error_starts_empty(ac, monkeypatch):
    inst, root = ac
    _write_json(root / "ling" / "proactive_state.json", {"old": 1})
    _patch_read_raises(monkeypatch, inst)

    assert _run(inst.save_proactive_state({"new": 2}, scope="ling")) == {"new": 2}


def test_save_proactive_state_non_scope_read_error_starts_empty(ac, monkeypatch):
    inst, root = ac
    _write_json(root / "aveline" / "proactive_state.json", {"old": 1})
    _patch_read_raises(monkeypatch, inst)

    assert _run(inst.save_proactive_state({"new": 2}, immediate=True)) == {"new": 2}


# ==================== 延迟写入 ====================


def test_ensure_flush_task_without_running_loop(ac):
    inst, _ = ac
    inst._ensure_flush_task()
    assert inst._flush_task is None


def test_delayed_flush_writes_pending(ac):
    inst, root = ac
    inst._flush_interval = 0
    inst._proactive_state_cache = {"last_thought": "delayed"}
    inst._dirty = True

    _run(inst._delayed_flush())

    assert _read_json(root / "aveline" / "proactive_state.json") == {
        "last_thought": "delayed"
    }


def test_flush_pending_updates_noop_when_clean(ac):
    inst, root = ac
    inst._dirty = False
    _run(inst._flush_pending_updates())
    assert not (root / "aveline" / "proactive_state.json").exists()


def test_flush_pending_updates_none_cache_returns(ac):
    inst, root = ac
    inst._dirty = True
    inst._proactive_state_cache = None
    _run(inst._flush_pending_updates())
    assert not (root / "aveline" / "proactive_state.json").exists()


def test_flush_pending_updates_empty_cache_removes_file(ac):
    inst, root = ac
    target = root / "aveline" / "proactive_state.json"
    _write_json(target, {"old": 1})
    inst._dirty = True
    inst._proactive_state_cache = {}

    _run(inst._flush_pending_updates())

    assert not target.exists()
    assert inst._dirty is False


def test_flush_pending_updates_writes_and_clears_pending(ac):
    inst, root = ac
    inst._dirty = True
    inst._proactive_state_cache = {"k": "v"}
    inst._pending_updates = {"k": "v"}

    _run(inst._flush_pending_updates())

    assert _read_json(root / "aveline" / "proactive_state.json") == {"k": "v"}
    assert inst._pending_updates == {}


class _DirtyClearingLock:
    """可控替身：进入临界区时把 ``_dirty`` 置 False，模拟双重检查命中。

    不制造真实争抢，只验证 ``_flush_pending_updates`` 的二次检查分支。
    """

    def __init__(self, inst):
        self._inst = inst

    async def __aenter__(self):
        self._inst._dirty = False
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


def test_flush_pending_updates_second_dirty_check_skips_write(ac):
    inst, root = ac
    inst._dirty = True
    inst._proactive_state_cache = {"k": "v"}
    inst._pending_updates = {"k": "v"}
    inst._file_lock = _DirtyClearingLock(inst)

    _run(inst._flush_pending_updates())

    assert not (root / "aveline" / "proactive_state.json").exists()
    assert inst._pending_updates == {"k": "v"}


# ==================== 用户级睡眠状态 ====================


def test_get_user_sleep_state_file_path(ac):
    inst, _ = ac
    path = inst._get_user_sleep_state_file()
    assert Path(path).name == "user_sleep_state.json"
    assert Path(path).parent.is_dir()


def test_get_user_sleep_state_cache_hit_returns_copy(ac):
    inst, _ = ac
    inst._user_sleep_state_cache = {StateKeys.LAST_GOODNIGHT_TS: 123.0}
    result = _run(inst.get_user_sleep_state())
    assert result == {StateKeys.LAST_GOODNIGHT_TS: 123.0}
    assert result is not inst._user_sleep_state_cache


def test_get_user_sleep_state_from_file(ac):
    inst, root = ac
    _write_json(
        root / "user" / "user_sleep_state.json",
        {StateKeys.LAST_GOODNIGHT_TS: 555.0},
    )
    assert _run(inst.get_user_sleep_state()) == {StateKeys.LAST_GOODNIGHT_TS: 555.0}


def test_get_user_sleep_state_bootstraps_and_persists(ac):
    inst, root = ac
    _write_json(
        root / "aveline" / "proactive_state.json",
        {StateKeys.LAST_GOODNIGHT_TS: 900.0, "last_thought": "ignored"},
    )

    result = _run(inst.get_user_sleep_state())

    assert result == {StateKeys.LAST_GOODNIGHT_TS: 900.0}
    assert _read_json(root / "user" / "user_sleep_state.json") == result


def test_get_user_sleep_state_bootstrap_empty_skips_write(ac):
    inst, root = ac
    assert _run(inst.get_user_sleep_state()) == {}
    assert not (root / "user" / "user_sleep_state.json").exists()


def test_save_user_sleep_state_filters_unknown_keys(ac):
    inst, root = ac
    result = _run(
        inst.save_user_sleep_state(
            {StateKeys.LAST_GOODNIGHT_TS: 1000.0, "not_a_sleep_key": "x"},
            mirror_persona=False,
        )
    )
    assert result[StateKeys.LAST_GOODNIGHT_TS] == 1000.0
    assert "not_a_sleep_key" not in result
    assert _read_json(root / "user" / "user_sleep_state.json") == {
        StateKeys.LAST_GOODNIGHT_TS: 1000.0
    }
    assert not (root / "aveline" / "proactive_state.json").exists()


def test_save_user_sleep_state_mirrors_current_persona(ac):
    inst, root = ac
    _run(
        inst.save_user_sleep_state(
            {StateKeys.LAST_GOODMORNING_TS: 2000.0},
            immediate=True,
            scope=None,
            mirror_persona=True,
        )
    )
    mirror = _read_json(root / "aveline" / "proactive_state.json")
    assert mirror[StateKeys.LAST_GOODMORNING_TS] == 2000.0


def test_save_user_sleep_state_mirrors_explicit_scope(ac):
    inst, root = ac
    _run(
        inst.save_user_sleep_state(
            {StateKeys.LAST_GOODNIGHT_TS: 3000.0},
            immediate=True,
            scope="ling",
            mirror_persona=True,
        )
    )
    mirror = _read_json(root / "ling" / "proactive_state.json")
    assert mirror[StateKeys.LAST_GOODNIGHT_TS] == 3000.0


def test_merge_user_sleep_state_empty_user_state_returns_unchanged(ac):
    inst, _ = ac
    inst._user_sleep_state_cache = {}
    assert _run(inst._merge_user_sleep_state({"a": 1})) == {"a": 1}


def test_merge_user_sleep_state_overrides_persona_keys(ac):
    inst, _ = ac
    inst._user_sleep_state_cache = {StateKeys.LAST_GOODNIGHT_TS: 42.0}
    merged = _run(
        inst._merge_user_sleep_state({StateKeys.LAST_GOODNIGHT_TS: 1.0, "keep": "x"})
    )
    assert merged[StateKeys.LAST_GOODNIGHT_TS] == 42.0
    assert merged["keep"] == "x"


def test_merge_user_sleep_state_global_sleep_mode_active(ac):
    inst, _ = ac
    inst._user_sleep_state_cache = {
        StateKeys.REDUCED_MODE_ACTIVE: True,
        StateKeys.REDUCED_MODE_REASON: "sleep",
        StateKeys.REDUCED_MODE_LABEL: "睡眠中",
        StateKeys.REDUCED_MODE_STARTED_TS: 10.0,
        StateKeys.REDUCED_MODE_EXPECTED_END_TS: 20.0,
    }
    merged = _run(inst._merge_user_sleep_state({}))
    assert merged[StateKeys.REDUCED_MODE_ACTIVE] is True
    assert merged[StateKeys.REDUCED_MODE_LABEL] == "睡眠中"
    assert merged[StateKeys.REDUCED_MODE_STARTED_TS] == 10.0
    assert merged[StateKeys.REDUCED_MODE_EXPECTED_END_TS] == 20.0


def test_merge_user_sleep_state_clears_stale_persona_sleep_mode(ac):
    inst, _ = ac
    inst._user_sleep_state_cache = {StateKeys.LAST_GOODNIGHT_TS: 5.0}
    merged = _run(
        inst._merge_user_sleep_state(
            {
                StateKeys.REDUCED_MODE_ACTIVE: True,
                StateKeys.REDUCED_MODE_REASON: "goodnight",
                StateKeys.REDUCED_MODE_LABEL: "晚安",
                StateKeys.REDUCED_MODE_STARTED_TS: 1.0,
                StateKeys.REDUCED_MODE_EXPECTED_END_TS: 2.0,
            }
        )
    )
    assert merged[StateKeys.REDUCED_MODE_ACTIVE] is False
    assert merged[StateKeys.REDUCED_MODE_REASON] == "none"
    assert merged[StateKeys.REDUCED_MODE_LABEL] == ""
    assert merged[StateKeys.REDUCED_MODE_STARTED_TS] == 0.0
    assert merged[StateKeys.REDUCED_MODE_EXPECTED_END_TS] == 0.0


def test_merge_user_sleep_state_keeps_persona_focus_mode(ac):
    inst, _ = ac
    inst._user_sleep_state_cache = {StateKeys.LAST_GOODNIGHT_TS: 5.0}
    merged = _run(
        inst._merge_user_sleep_state(
            {
                StateKeys.REDUCED_MODE_ACTIVE: True,
                StateKeys.REDUCED_MODE_REASON: "focus",
            }
        )
    )
    assert merged[StateKeys.REDUCED_MODE_ACTIVE] is True
    assert merged[StateKeys.REDUCED_MODE_REASON] == "focus"


def test_bootstrap_user_sleep_state_picks_latest_scope(ac):
    inst, root = ac
    _write_json(root / "aveline" / "proactive_state.json", {StateKeys.LAST_GOODNIGHT_TS: 800.0})
    _write_json(root / "yeye" / "proactive_state.json", {StateKeys.LAST_GOODNIGHT_TS: 900.0})
    assert _run(inst._bootstrap_user_sleep_state()) == {
        StateKeys.LAST_GOODNIGHT_TS: 900.0
    }


def test_bootstrap_user_sleep_state_skips_older_scope(ac):
    inst, root = ac
    _write_json(root / "aveline" / "proactive_state.json", {StateKeys.LAST_GOODNIGHT_TS: 900.0})
    _write_json(root / "yeye" / "proactive_state.json", {StateKeys.LAST_GOODNIGHT_TS: 100.0})
    assert _run(inst._bootstrap_user_sleep_state()) == {
        StateKeys.LAST_GOODNIGHT_TS: 900.0
    }


def test_bootstrap_user_sleep_state_ignores_irrelevant_keys(ac):
    inst, root = ac
    _write_json(root / "aveline" / "proactive_state.json", {"last_thought": "x"})
    assert _run(inst._bootstrap_user_sleep_state()) == {}


def test_bootstrap_user_sleep_state_includes_dynamic_scopes(ac, monkeypatch):
    inst, root = ac
    monkeypatch.setattr(
        scope_registry_module,
        "list_dynamic_scopes",
        lambda: {"zzz": {"dir": "zzz", "slugs": []}},
    )
    _write_json(root / "zzz" / "proactive_state.json", {StateKeys.LAST_GOODMORNING_TS: 777.0})
    assert _run(inst._bootstrap_user_sleep_state()) == {
        StateKeys.LAST_GOODMORNING_TS: 777.0
    }


def test_bootstrap_user_sleep_state_dynamic_scope_error_ignored(ac, monkeypatch):
    inst, _ = ac

    def _boom():
        raise RuntimeError("no registry")

    monkeypatch.setattr(scope_registry_module, "list_dynamic_scopes", _boom)
    assert _run(inst._bootstrap_user_sleep_state()) == {}


# ==================== Bandit 策略分值 ====================


def test_load_policy_scores_from_disk(ac):
    inst, root = ac
    payload = {"a": {"avg_reward": 1.0, "count": 2}}
    _write_json(root / "aveline" / "active_care_policy.json", payload)
    scores = _run(inst.load_policy_scores())
    assert scores == payload
    assert inst._policy_scores == payload


def test_load_policy_scores_missing_file(ac):
    inst, _ = ac
    assert _run(inst.load_policy_scores()) == {}


def test_load_policy_scores_blank_file(ac):
    inst, root = ac
    target = root / "aveline" / "active_care_policy.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("   ", encoding="utf-8")
    assert _run(inst.load_policy_scores()) == {}


def test_load_policy_scores_broken_json_returns_empty(ac):
    inst, root = ac
    target = root / "aveline" / "active_care_policy.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{broken", encoding="utf-8")
    assert _run(inst.load_policy_scores()) == {}


def test_save_policy_scores_writes_file(ac, monkeypatch):
    inst, root = ac
    monkeypatch.setattr(storage_module, "is_debug_enabled", lambda module: True)
    payload = {"a": {"avg_reward": 0.5, "count": 1}}

    _run(inst.save_policy_scores(payload))

    assert inst._policy_scores == payload
    assert _read_json(root / "aveline" / "active_care_policy.json") == payload


def test_save_policy_scores_empty_removes_file(ac):
    inst, root = ac
    target = root / "aveline" / "active_care_policy.json"
    _write_json(target, {"a": 1})

    _run(inst.save_policy_scores({}))

    assert not target.exists()
    assert inst._policy_scores == {}


def test_update_policy_reward_incremental_average(ac, monkeypatch):
    inst, root = ac
    monkeypatch.setattr(storage_module, "is_debug_enabled", lambda module: True)
    policy_file = root / "aveline" / "active_care_policy.json"

    async def _scenario():
        await inst.update_policy_reward("share_thought", 1.0)
        first = _read_json(policy_file)
        await inst.update_policy_reward("share_thought", 0.0)
        second = _read_json(policy_file)
        return first, second

    first, second = _run(_scenario())
    assert first["share_thought"] == {"avg_reward": 1.0, "count": 1}
    assert second["share_thought"] == {"avg_reward": 0.5, "count": 2}


# ==================== MDP Q 表 ====================


def test_load_mdp_q_from_disk(ac):
    inst, root = ac
    _write_json(root / "aveline" / "active_care_mdp.json", {"s::a": {"q": 1.5}})
    assert _run(inst.load_mdp_q()) == {"s::a": {"q": 1.5}}


def test_load_mdp_q_missing_file(ac):
    inst, _ = ac
    assert _run(inst.load_mdp_q()) == {}


def test_load_mdp_q_blank_and_broken(ac):
    inst, root = ac
    target = root / "aveline" / "active_care_mdp.json"
    target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text("  ", encoding="utf-8")
    assert _run(inst.load_mdp_q()) == {}

    target.write_text("{bad", encoding="utf-8")
    assert _run(inst.load_mdp_q()) == {}


def test_save_mdp_q_writes_then_clears(ac, monkeypatch):
    inst, root = ac
    monkeypatch.setattr(storage_module, "is_debug_enabled", lambda module: True)
    target = root / "aveline" / "active_care_mdp.json"

    async def _scenario():
        await inst.save_mdp_q({"s::a": 1})
        written = _read_json(target)
        await inst.save_mdp_q({})
        return written

    written = _run(_scenario())
    assert written == {"s::a": 1}
    assert inst._mdp_q_cache == {}
    assert not target.exists()


# ==================== 主动计数 / 计划 / 画像 ====================


def test_proactive_count_cache_miss_then_increment(ac):
    inst, root = ac

    async def _scenario():
        before = await inst.get_proactive_count("2026-09-23")
        await inst.increment_proactive_count("2026-09-23")
        after = await inst.get_proactive_count("2026-09-23")
        return before, after

    before, after = _run(_scenario())
    assert before == 0
    assert after == 1
    assert inst._proactive_count_cache == {"2026-09-23": 1}
    assert _read_json(root / "aveline" / "proactive_count.json") == {"2026-09-23": 1}


def test_proactive_count_from_disk_and_none_value(ac):
    inst, root = ac
    _write_json(
        root / "aveline" / "proactive_count.json",
        {"2026-09-23": 3, "none_key": None},
    )

    async def _scenario():
        return (
            await inst.get_proactive_count("2026-09-23"),
            await inst.get_proactive_count("none_key"),
        )

    present, none_value = _run(_scenario())
    assert present == 3
    assert none_value == 0


def test_plan_roundtrip_and_clear(ac):
    inst, root = ac
    target = root / "aveline" / "proactive_plan.json"

    async def _scenario():
        await inst.save_plan({"plan": "x"})
        loaded = await inst.get_plan()
        await inst.save_plan({})
        cleared = await inst.get_plan()
        return loaded, cleared

    loaded, cleared = _run(_scenario())
    assert loaded == {"plan": "x"}
    assert cleared == {}
    assert not target.exists()


def test_get_user_profile_caches_disk_value(ac):
    inst, root = ac
    _write_json(root / "aveline" / "user_profile.json", {"name": "小友"})
    assert _run(inst.get_user_profile()) == {"name": "小友"}
    assert ActiveCareStorage._user_profile_cache["aveline"] == {"name": "小友"}

    _write_json(root / "aveline" / "user_profile.json", {"name": "改了"})
    assert _run(inst.get_user_profile()) == {"name": "小友"}


def test_get_user_profile_missing_file(ac):
    inst, _ = ac
    assert _run(inst.get_user_profile()) == {}


def test_get_user_profile_explicit_scope(ac):
    inst, root = ac
    _write_json(root / "ling" / "user_profile.json", {"name": "Ling"})
    assert _run(inst.get_user_profile(scope="ling")) == {"name": "Ling"}


def test_get_user_profile_swallows_read_error(ac, monkeypatch):
    inst, root = ac
    _write_json(root / "aveline" / "user_profile.json", {"name": "x"})

    async def _boom(filepath):
        raise RuntimeError("read failed")

    monkeypatch.setattr(inst, "_read_json_file", _boom)
    assert _run(inst.get_user_profile()) == {}


def test_save_user_profile_merges_and_persists(ac):
    inst, root = ac
    _write_json(root / "aveline" / "user_profile.json", {"name": "小友"})

    result = _run(inst.save_user_profile({"city": "上海"}))

    assert result == {"name": "小友", "city": "上海"}
    assert _read_json(root / "aveline" / "user_profile.json") == result
    assert ActiveCareStorage._user_profile_cache["aveline"] == result


def test_save_user_profile_empty_removes_file(ac):
    inst, root = ac
    target = root / "aveline" / "user_profile.json"
    _write_json(target, {})

    assert _run(inst.save_user_profile({})) == {}

    assert not target.exists()


def test_invalidate_user_profile_cache_by_scope_and_all(ac):
    inst, _ = ac
    ActiveCareStorage._user_profile_cache["aveline"] = {"a": 1}
    ActiveCareStorage._user_profile_cache["ling"] = {"b": 2}

    inst.invalidate_user_profile_cache("aveline")
    assert "aveline" not in ActiveCareStorage._user_profile_cache
    assert "ling" in ActiveCareStorage._user_profile_cache

    inst.invalidate_user_profile_cache()
    assert ActiveCareStorage._user_profile_cache == {}
