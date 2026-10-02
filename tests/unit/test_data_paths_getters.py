"""单元测试：core/utils/data/data_paths.py —— 初始化与各目录入口。

覆盖 _ensure_initialized（含双重检查与幂等早退）与全部 get_* 路径入口，
以及 study 学习目录辅助函数。

路径断言全部基于注入的临时项目根（patch dp.get_project_root），
不触碰真实 companion_data，也不断言本机真实路径。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from core.utils.data import data_paths as dp


@pytest.fixture()
def dp_root(tmp_path, monkeypatch):
    """把项目根指向临时目录，并重置初始化标志，保证每个用例独立初始化。"""
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setattr(dp, "get_project_root", lambda: root)
    monkeypatch.setattr(dp, "_INITIALIZED", False)
    return root


# ────────────────────────── _ensure_initialized ──────────────────────────


def test_ensure_initialized_creates_layout(dp_root):
    """首次初始化会建 user_data 与各角色的 {scope}_data/{scope}_life/life_records。"""
    dp._ensure_initialized()
    base = dp_root / dp._BASE_NAME
    assert (base / dp._USER_DIR).is_dir()
    for scope in dp._get_role_scopes():
        assert (base / f"{scope}_data" / f"{scope}_life").is_dir()
        assert (base / f"{scope}_data" / "life_records").is_dir()
    assert dp._INITIALIZED is True
    assert dp._INIT_SECONDS >= 0.0


def test_ensure_initialized_skips_when_initialized(monkeypatch):
    """已初始化时直接早退，不再解析项目根。"""
    calls = []
    monkeypatch.setattr(dp, "_INITIALIZED", True)
    monkeypatch.setattr(dp, "get_project_root", lambda: calls.append(1) or Path("x"))
    dp._ensure_initialized()
    assert calls == []


def test_ensure_initialized_double_check_inside_lock(monkeypatch):
    """进入锁后若已被并发初始化，则二次检查早退。"""

    class _FlipLock:
        def __enter__(self):
            dp._INITIALIZED = True  # 模拟另一线程已完成初始化
            return self

        def __exit__(self, *exc):
            return False

    calls = []
    monkeypatch.setattr(dp, "_INITIALIZED", False)
    monkeypatch.setattr(dp, "_LOCK", _FlipLock())
    monkeypatch.setattr(dp, "get_project_root", lambda: calls.append(1) or Path("x"))
    dp._ensure_initialized()
    assert calls == []


# ────────────────────────── 无参 get_* 入口 ──────────────────────────

_NOARG_GETTERS = [
    ("get_companion_data_dir", ("companion_data",)),
    ("get_user_data_dir", ("companion_data", "user_data")),
    ("get_aveline_data_dir", ("companion_data", "aveline_data")),
    ("get_ling_data_dir", ("companion_data", "ling_data")),
    ("get_xiaolu_data_dir", ("companion_data", "xiaolu_data")),
    ("get_yeye_data_dir", ("companion_data", "yeye_data")),
    ("get_dual_role_data_dir", ("companion_data", "dual_role")),
    ("get_dual_role_reminder_assignment_path", ("companion_data", "dual_role", "reminder_assignment_today.json")),
    ("get_proactive_assignment_path", ("companion_data", "dual_role", "proactive_assignment_today.json")),
    ("get_user_daily_dir", ("companion_data", "user_data", "daily")),
    ("get_user_daily_records_dir", ("companion_data", "user_data", "daily_records")),
    ("get_user_chat_history_dir", ("companion_data", "user_data", "chat_history")),
    ("get_user_weighted_history_dir", ("companion_data", "user_data", "history")),
    ("get_user_schedule_dir", ("companion_data", "user_data", "schedule")),
    ("get_user_status_dir", ("companion_data", "user_data", "status")),
    ("get_user_reminders_file", ("companion_data", "user_data", "reminders.json")),
    ("get_user_latest_device_context_file", ("companion_data", "user_data", "latest_device_context.json")),
    ("get_aveline_life_dir", ("companion_data", "aveline_data", "aveline_life")),
    ("get_aveline_life_records_dir", ("companion_data", "aveline_data", "life_records")),
    ("get_ling_life_dir", ("companion_data", "ling_data", "ling_life")),
    ("get_ling_life_records_dir", ("companion_data", "ling_data", "life_records")),
    ("get_aveline_persona_data_dir", ("companion_data", "aveline_data", "persona_data")),
    ("get_ling_persona_data_dir", ("companion_data", "ling_data", "persona_data")),
    ("get_user_person_profile_path", ("companion_data", "user_data", "person_profile.json")),
    ("get_user_people_profiles_dir", ("companion_data", "user_data", "people_profiles")),
    ("get_background_circle_dir", ("companion_data", "dual_role", "background_circle")),
]


@pytest.mark.parametrize(("name", "parts"), _NOARG_GETTERS)
def test_noarg_getter_paths(dp_root, name, parts):
    """各无参入口返回「临时根/companion_data/...」下的解析路径。"""
    assert getattr(dp, name)() == dp_root.joinpath(*parts).resolve()


# ────────────────────────── 带参 get_* 入口 ──────────────────────────

_ARG_GETTERS = [
    ("get_role_data_dir", (None,), ("companion_data", "user_data")),
    ("get_role_data_dir", ("user",), ("companion_data", "user_data")),
    ("get_role_data_dir", ("dual_role",), ("companion_data", "dual_role")),
    ("get_role_data_dir", ("aveline",), ("companion_data", "aveline_data")),
    ("get_role_data_dir", ("ling",), ("companion_data", "ling_data")),
    ("get_role_chat_history_dir", ("ling",), ("companion_data", "ling_data", "chat_history")),
    ("get_chat_history_dir_for_conversation", ("core_ling",), ("companion_data", "ling_data", "chat_history")),
    ("get_chat_history_dir_for_conversation", (None,), ("companion_data", "aveline_data", "chat_history")),
    ("get_role_daily_dir", ("ling",), ("companion_data", "ling_data", "daily")),
    ("get_daily_dir_for_conversation", ("core_ling",), ("companion_data", "ling_data", "daily")),
    ("get_active_care_dir", ("ling",), ("companion_data", "ling_data", "active_care")),
    ("get_active_care_dir", (None,), ("companion_data", "aveline_data", "active_care")),
    ("get_role_memories_dir", ("ling",), ("companion_data", "ling_data", "memories")),
    ("get_memories_dir_for_conversation", ("core_ling",), ("companion_data", "ling_data", "memories")),
    ("get_sessions_file_for_scope", ("ling",), ("companion_data", "ling_data", "memories", "sessions.json")),
    ("get_role_profiles_dir", ("aveline",), ("companion_data", "aveline_data", "persona_data", "profiles")),
    ("get_role_profiles_dir", (None,), ("companion_data", "aveline_data", "persona_data", "profiles")),
    ("get_role_profiles_dir", ("user",), ("companion_data", "aveline_data", "persona_data", "profiles")),
    ("get_role_profiles_dir", ("dual_role",), ("companion_data", "aveline_data", "persona_data", "profiles")),
    ("get_role_profile_path", ("ling", "Ling", "Aveline"), ("companion_data", "ling_data", "persona_data", "profiles", "Ling_Aveline.json")),
    ("get_role_profile_path", (None, "", ""), ("companion_data", "aveline_data", "persona_data", "profiles", "Role_default.json")),
    ("get_user_people_profile_path", ("ling",), ("companion_data", "user_data", "people_profiles", "ling.json")),
    ("get_user_people_profile_path", ("",), ("companion_data", "user_data", "people_profiles", "unknown.json")),
]


@pytest.mark.parametrize(("name", "args", "parts"), _ARG_GETTERS)
def test_arg_getter_paths(dp_root, name, args, parts):
    """带参入口按 scope / conversation_id 落到正确子目录。"""
    assert getattr(dp, name)(*args) == dp_root.joinpath(*parts).resolve()


def test_get_all_chat_history_dirs(dp_root):
    """汇总所有角色 + user + dual_role 的 chat_history，且结果去重。"""
    dirs = dp.get_all_chat_history_dirs()
    base = dp_root / dp._BASE_NAME
    expected = {
        (base / dp._USER_DIR / "chat_history").resolve(),
        (base / "dual_role" / "chat_history").resolve(),
    }
    for scope in dp._get_role_scopes():
        expected.add((base / f"{scope}_data" / "chat_history").resolve())
    assert set(dirs) == expected
    assert len(dirs) == len(set(dirs))


# ────────────────────────── study 目录辅助 ──────────────────────────


def test_study_root_uses_settings(monkeypatch):
    """settings.study.study_root 非空时交给跨平台解析层。"""
    import config.integrated_config as ic

    calls = []
    monkeypatch.setattr(dp, "resolve_cross_platform_path", lambda raw: calls.append(raw) or Path("/sentinel"))

    class _Study:
        study_root = "/data/study"

    class _Settings:
        study = _Study()

    monkeypatch.setattr(ic, "get_settings", lambda: _Settings())
    assert dp.get_study_root_dir() == Path("/sentinel")
    assert calls == ["/data/study"]


@pytest.mark.parametrize("scenario", ["raises", "none_study", "empty_root"])
def test_study_root_fallback(monkeypatch, scenario):
    """读配置异常 / study 为 None / 根为空串时回退到默认盘符路径。"""
    import config.integrated_config as ic

    calls = []
    monkeypatch.setattr(dp, "resolve_cross_platform_path", lambda raw: calls.append(raw) or Path("/sentinel"))
    if scenario == "raises":

        def _boom():
            raise RuntimeError("no config")

        monkeypatch.setattr(ic, "get_settings", _boom)
    elif scenario == "none_study":

        class _S:
            study = None

        monkeypatch.setattr(ic, "get_settings", lambda: _S())
    else:

        class _Study:
            study_root = "   "

        class _S:
            study = _Study()

        monkeypatch.setattr(ic, "get_settings", lambda: _S())

    assert dp.get_study_root_dir() == Path("/sentinel")
    assert calls == [r"D:\projects\study"]


def test_study_daily_dirs(tmp_path, monkeypatch):
    """Daily 与 YYYY/MM/DD 子目录基于注入的学习根。"""
    monkeypatch.setattr(dp, "get_study_root_dir", lambda: tmp_path / "study")
    assert dp.get_study_daily_dir() == (tmp_path / "study" / "Daily").resolve()
    date = datetime(2024, 3, 7)
    assert dp.get_study_daily_date_dir(date) == (
        tmp_path / "study" / "Daily" / "2024" / "03" / "07"
    ).resolve()
