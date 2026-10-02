# -*- coding: utf-8 -*-
"""验证 search_chat_history 工具的 source 来源过滤功能。

验证项：
1. _match_source: source='all' 不过滤任何事件
2. _match_source: source='qq' 包含 platform='qq' 和无 platform 的老数据
3. _match_source: source='qq' 屏蔽 platform='obsidian' 的事件
4. _match_source: source='obsidian' 仅保留 platform='obsidian'
5. _match_source: source='obsidian' 屏蔽无 platform 的老数据
6. _event_matches: source='qq' 时含关键词的 obsidian 事件不匹配
7. _event_matches: source='obsidian' 时含关键词的 qq 事件不匹配
8. _event_matches: source='all' 时 qq/obsidian 事件都匹配（含关键词）

运行：venv_core\\scripts\\python.exe tests\\scripts\\tools\\verify_search_history_source_filter.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core.tools.search_chat_history_tool import SearchChatHistoryTool  # noqa: E402


def _ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    raise AssertionError(msg)


def _make_event(platform: str | None, content: str = "你好", role: str = "user") -> dict:
    """构造测试事件。platform=None 表示无 platform 字段（老数据）。"""
    event: dict = {
        "event_type": "chat_message",
        "role": role,
        "content": content,
        "timestamp": 1700000000.0,
    }
    if platform is not None:
        event["metadata"] = {"platform": platform}
    else:
        event["metadata"] = {}
    return event


def test_match_source_all() -> None:
    """source='all' 不过滤任何事件。"""
    print("[1] 测试 source='all' 不过滤...")
    for pf in ("qq", "obsidian", ""):
        ev = _make_event(pf if pf else None)
        if not SearchChatHistoryTool._match_source(ev, "all"):
            _fail(f"source='all' 不应过滤 platform='{pf}' 的事件")
    _ok("source='all' 保留所有平台事件")


def test_match_source_qq_keeps_qq() -> None:
    """source='qq' 保留 platform='qq' 和无 platform 的老数据。"""
    print("[2] 测试 source='qq' 保留 QQ 和老数据...")
    ev_qq = _make_event("qq")
    if not SearchChatHistoryTool._match_source(ev_qq, "qq"):
        _fail("source='qq' 应保留 platform='qq' 的事件")
    ev_legacy = _make_event(None)
    if not SearchChatHistoryTool._match_source(ev_legacy, "qq"):
        _fail("source='qq' 应保留无 platform 的老数据（默认归 QQ）")
    _ok("source='qq' 保留 platform='qq' 和无 platform 的老数据")


def test_match_source_qq_blocks_obsidian() -> None:
    """source='qq' 屏蔽 platform='obsidian' 的事件。"""
    print("[3] 测试 source='qq' 屏蔽 Obsidian...")
    ev_obs = _make_event("obsidian")
    if SearchChatHistoryTool._match_source(ev_obs, "qq"):
        _fail("source='qq' 不应保留 platform='obsidian' 的事件")
    _ok("source='qq' 屏蔽 platform='obsidian' 的事件")


def test_match_source_obsidian_keeps_obsidian() -> None:
    """source='obsidian' 仅保留 platform='obsidian'。"""
    print("[4] 测试 source='obsidian' 仅保留 Obsidian...")
    ev_obs = _make_event("obsidian")
    if not SearchChatHistoryTool._match_source(ev_obs, "obsidian"):
        _fail("source='obsidian' 应保留 platform='obsidian' 的事件")
    _ok("source='obsidian' 保留 platform='obsidian' 的事件")


def test_match_source_obsidian_blocks_qq_and_legacy() -> None:
    """source='obsidian' 屏蔽 platform='qq' 和无 platform 的老数据。"""
    print("[5] 测试 source='obsidian' 屏蔽 QQ 和老数据...")
    ev_qq = _make_event("qq")
    if SearchChatHistoryTool._match_source(ev_qq, "obsidian"):
        _fail("source='obsidian' 不应保留 platform='qq' 的事件")
    ev_legacy = _make_event(None)
    if SearchChatHistoryTool._match_source(ev_legacy, "obsidian"):
        _fail("source='obsidian' 不应保留无 platform 的老数据")
    _ok("source='obsidian' 屏蔽 platform='qq' 和无 platform 的老数据")


def test_event_matches_qq_blocks_obsidian() -> None:
    """_event_matches: source='qq' 时含关键词的 obsidian 事件不匹配。"""
    print("[6] 测试 _event_matches source='qq' 屏蔽 obsidian 事件...")
    ev_obs = _make_event("obsidian", content="我想吃火锅")
    matched = SearchChatHistoryTool._event_matches(
        ev_obs, ["火锅"], set(), None, None, "qq"
    )
    if matched:
        _fail("source='qq' 时 obsidian 事件即使含关键词也不应匹配")
    _ok("source='qq' 时 obsidian 事件被屏蔽（即使含关键词）")


def test_event_matches_obsidian_blocks_qq() -> None:
    """_event_matches: source='obsidian' 时含关键词的 qq 事件不匹配。"""
    print("[7] 测试 _event_matches source='obsidian' 屏蔽 qq 事件...")
    ev_qq = _make_event("qq", content="我想吃火锅")
    matched = SearchChatHistoryTool._event_matches(
        ev_qq, ["火锅"], set(), None, None, "obsidian"
    )
    if matched:
        _fail("source='obsidian' 时 qq 事件即使含关键词也不应匹配")
    _ok("source='obsidian' 时 qq 事件被屏蔽（即使含关键词）")


def test_event_matches_all_keeps_both() -> None:
    """_event_matches: source='all' 时 qq/obsidian 事件都匹配（含关键词）。"""
    print("[8] 测试 _event_matches source='all' 保留双方...")
    for pf in ("qq", "obsidian"):
        ev = _make_event(pf, content="我想吃火锅")
        matched = SearchChatHistoryTool._event_matches(
            ev, ["火锅"], set(), None, None, "all"
        )
        if not matched:
            _fail(f"source='all' 时 platform='{pf}' 含关键词的事件应匹配")
    _ok("source='all' 时 qq/obsidian 事件都匹配（含关键词）")


def main() -> None:
    print("=" * 60)
    print("验证 search_chat_history 的 source 来源过滤")
    print("=" * 60)
    test_match_source_all()
    test_match_source_qq_keeps_qq()
    test_match_source_qq_blocks_obsidian()
    test_match_source_obsidian_keeps_obsidian()
    test_match_source_obsidian_blocks_qq_and_legacy()
    test_event_matches_qq_blocks_obsidian()
    test_event_matches_obsidian_blocks_qq()
    test_event_matches_all_keeps_both()
    print("=" * 60)
    print("全部验证通过！source 来源过滤工作正常。")
    print("=" * 60)


if __name__ == "__main__":
    main()
