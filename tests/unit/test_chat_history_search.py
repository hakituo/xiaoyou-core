"""SearchChatHistoryTool 接入 SQLite 派生索引（B3）的确定性回归。

重点不是"索引能跑"，而是**索引路径与文件扫描路径结果逐条一致**：
同一批 JSONL，分别在索引可用 / 不可用两种情况下跑同一个查询，断言返回的
event_id 序列完全相同。文件扫描实现是 P0-P2 优化后的兜底本体，它保持可用，
因此天然充当语义基线。

时间相关断言使用固定时间戳；不依赖真实时间流逝。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.services.chat_history_index import reset_history_index_registry
from core.services.chat_history_store import ChatHistoryStore
from core.tools.search_chat_history_tool import (
    _PEER_MATCH_KEYWORDS,
    SearchChatHistoryTool,
)
from core.utils.data import data_paths as data_paths_module
from core.utils.data import scope_registry

_CURRENT = "shared__persona__core_aveline"


def _fake_role(conversation_id: str) -> str:
    text = str(conversation_id or "").lower()
    if "ling" in text:
        return "ling"
    if "aveline" in text:
        return "aveline"
    return ""


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in events),
        encoding="utf-8",
    )


def _event(
    event_id: str,
    timestamp: float,
    *,
    content: str = "消息",
    role: str = "user",
    conversation_id: str = _CURRENT,
    event_type: str = "message",
    metadata: dict | None = None,
) -> dict:
    return {
        "event_id": event_id,
        "conversation_id": conversation_id,
        "message_id": event_id,
        "event_type": event_type,
        "role": role,
        "content": content,
        "timestamp": timestamp,
        "created_at": "2026-09-17 12:00:00",
        "metadata": metadata if metadata is not None else {},
        "storage_scope": "aveline",
    }


def _without_index():
    """上下文管理器：临时关闭索引，强制走文件扫描基线。"""
    return pytest.MonkeyPatch.context()


def _disable_index(mp) -> None:
    """关闭索引，强制走文件扫描基线。

    让索引工厂抛异常即可；不要替换 ``ChatHistoryStore._synced_index``
    （它是 staticmethod，getattr/setattr 往返会退化成普通函数）。
    """
    import core.services.chat_history_index as chat_history_index

    def _boom(*_args, **_kwargs):
        raise RuntimeError("index disabled for baseline")

    mp.setattr(chat_history_index, "get_history_index", _boom)
    reset_history_index_registry()


@pytest.fixture
def history_root(tmp_path, monkeypatch):
    root = tmp_path / "aveline_data" / "chat_history"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        data_paths_module, "get_chat_history_dir_for_conversation", lambda _cid: root
    )
    monkeypatch.setattr(data_paths_module, "get_all_chat_history_dirs", lambda: [root])
    monkeypatch.setattr(
        "core.services.chat_history_store.get_all_chat_history_dirs", lambda: [root]
    )
    monkeypatch.setattr(
        "core.services.chat_history_store.get_chat_history_store",
        lambda: ChatHistoryStore(root),
    )
    monkeypatch.setattr(scope_registry, "matched_persona_scope", _fake_role)
    reset_history_index_registry()
    yield root
    reset_history_index_registry()


def _seed_same_role_history(root: Path) -> None:
    lane = root / "2026" / "09" / "17" / "lane"
    _write_jsonl(
        lane / f"{_CURRENT}.jsonl",
        [
            _event("cur1", 10.0, content="这次又提到初二的女生"),
            _event("cur2", 11.0, content="今天天气不错", role="assistant"),
            _event("cur3", 12.0, content="内心独白", event_type="chat_thought"),
        ],
    )
    # 同角色另一会话：应被合并召回
    _write_jsonl(
        lane / "aveline_side.jsonl",
        [
            _event("side1", 20.0, content="小红书上看到的女生穿搭"),
            _event(
                "side2",
                21.0,
                content="敏感话题不该出现",
                metadata={"topics": ["sensitive"]},
            ),
            _event(
                "side3",
                22.0,
                content="obsidian 上的记录",
                metadata={"platform": "obsidian"},
            ),
            _event("side4", 23.0, content="QQ 上的记录", metadata={"platform": "qq"}),
        ],
    )
    # 其他角色会话：不应被合并召回
    _write_jsonl(
        lane / "ling_love.jsonl",
        [
            _event(
                "ling1",
                30.0,
                content="Ling那边的女生话题",
                conversation_id="ling_love",
            )
        ],
    )
    # 身份不明的旧文件：应放行
    _write_jsonl(
        lane / "legacy_unknown.jsonl",
        [
            _event(
                "legacy1",
                40.0,
                content="来历不明的女生记录",
                conversation_id="legacy_unknown",
            )
        ],
    )


_SEARCH_CASES = [
    {"query": "女生", "limit": 20, "source": "all", "scope": "sfw"},
    {"query": "女生", "limit": 2, "source": "all", "scope": "sfw"},
    {"query": "小红书上看到的", "limit": 20, "source": "all", "scope": "sfw"},
    {"query": "不存在的关键词", "limit": 20, "source": "all", "scope": "sfw"},
    {"query": "女生", "limit": 20, "source": "qq", "scope": "sfw"},
    {"query": "女生", "limit": 20, "source": "obsidian", "scope": "sfw"},
    {"query": "女生", "limit": 20, "source": "all", "scope": "nsfw"},
    {
        "query": "女生",
        "limit": 20,
        "roles": ["assistant"],
        "source": "all",
        "scope": "sfw",
    },
    {"query": "", "limit": 20, "source": "all", "scope": "sfw"},
    {"query": "记录", "limit": 20, "before_ts": 25.0, "source": "all", "scope": "sfw"},
    {"query": "记录", "limit": 20, "after_ts": 25.0, "source": "all", "scope": "sfw"},
]


def _search_params(case: dict) -> dict:
    return {
        "conversation_id": _CURRENT,
        "query": case.get("query", ""),
        "limit": case.get("limit", 20),
        "roles": case.get("roles"),
        "before_ts": case.get("before_ts"),
        "after_ts": case.get("after_ts"),
        "scope": case.get("scope", "sfw"),
        "source": case.get("source", "all"),
    }


def test_search_in_store_index_matches_file_scan(history_root):
    _seed_same_role_history(history_root)
    tool = SearchChatHistoryTool()

    for case in _SEARCH_CASES:
        params = _search_params(case)
        reset_history_index_registry()
        indexed = tool._search_in_store(**params)
        with _without_index() as mp:
            _disable_index(mp)
            scanned = tool._search_in_store(**params)
        assert [item["event_id"] for item in indexed] == [
            item["event_id"] for item in scanned
        ], case


def test_search_in_store_index_hits_expected_events(history_root):
    _seed_same_role_history(history_root)
    tool = SearchChatHistoryTool()
    params = _search_params({"query": "女生", "limit": 20, "scope": "sfw"})

    hits = {item["event_id"] for item in tool._search_in_store(**params)}
    # 当前会话 + 同角色会话 + 身份不明文件；其他角色文件不参与
    assert hits == {"cur1", "side1", "legacy1"}

    # chat_thought 与敏感话题始终排除
    assert "cur3" not in hits
    assert "side2" not in hits

    # 非 sfw scope 放行敏感话题（与文件扫描一致）
    nsfw = _search_params({"query": "敏感话题", "limit": 20, "scope": "nsfw"})
    assert {item["event_id"] for item in tool._search_in_store(**nsfw)} == {"side2"}


def test_search_in_store_falls_back_when_index_unavailable(history_root, monkeypatch):
    _seed_same_role_history(history_root)
    tool = SearchChatHistoryTool()
    params = _search_params({"query": "女生", "limit": 20, "scope": "sfw"})

    monkeypatch.setattr(
        SearchChatHistoryTool, "_usable_index", staticmethod(lambda _root: None)
    )
    assert {item["event_id"] for item in tool._search_in_store(**params)} == {
        "cur1",
        "side1",
        "legacy1",
    }


def test_chinese_search_quality_does_not_regress(history_root):
    """jieba 近义召回 / 精确短语 / 无误伤，在索引路径上逐条成立。"""
    lane = history_root / "2026" / "09" / "17" / "lane"
    _write_jsonl(
        lane / f"{_CURRENT}.jsonl",
        [
            _event("r1", 1.0, content="那个初二的女生今天又叫我嘉豪，无语"),
            _event("r2", 2.0, content="今天天气不错，出去骑车了"),
            _event("r3", 3.0, content="晚上吃了火锅"),
        ],
    )
    tool = SearchChatHistoryTool()

    def hits(query: str) -> set[str]:
        params = _search_params({"query": query, "limit": 20, "scope": "sfw"})
        return {item["event_id"] for item in tool._search_in_store(**params)}

    assert "r1" in hits("初中女生")  # 近义分词召回
    assert "r1" in hits("初二")  # 精确短语
    assert "r3" in hits("火锅")
    assert "r1" not in hits("开车去上班")  # 不误伤


def test_peer_search_index_matches_file_scan(tmp_path, monkeypatch):
    root_a = tmp_path / "aveline_data" / "chat_history"
    root_b = tmp_path / "ling_data" / "chat_history"
    _write_jsonl(
        root_a / "2026" / "09" / "17" / "lane" / "core_aveline.jsonl",
        [_event("pa1", 1.0, content="和Aveline聊到命中关键词的话题")],
    )
    _write_jsonl(
        root_a / "2026" / "09" / "17" / "lane" / "misc.jsonl",
        [_event("pa2", 2.0, content="root 路径命中关键词时整库都算命中")],
    )
    _write_jsonl(
        root_b / "2026" / "09" / "17" / "lane" / "core_aveline.jsonl",
        [_event("pb1", 3.0, content="相对路径命中 core_aveline")],
    )
    _write_jsonl(
        root_b / "2026" / "09" / "17" / "lane" / "ling_love.jsonl",
        [_event("pb2", 4.0, content="不该被 peer 命中")],
    )

    roots = [root_a, root_b]
    keywords = _PEER_MATCH_KEYWORDS["aveline"]
    tool = SearchChatHistoryTool()

    def file_filter(fp: Path) -> bool:
        fp_text = str(fp).lower()
        return any(kw.lower() in fp_text for kw in keywords)

    common = {
        "query": "命中",
        "limit": 20,
        "roles": None,
        "before_ts": None,
        "after_ts": None,
        "source": "all",
    }

    reset_history_index_registry()
    indexed = tool._peer_search_indexed(
        search_roots=roots, match_keywords=keywords, **common
    )
    scanned = tool._scan_events(
        search_roots=roots, scope="sfw", file_filter=file_filter, **common
    )

    assert indexed is not None
    assert [item["event_id"] for item in indexed] == [
        item["event_id"] for item in scanned
    ]
    assert {item["event_id"] for item in indexed} == {"pa1", "pa2", "pb1"}
    assert "pb2" not in {item["event_id"] for item in indexed}


def test_peer_search_returns_none_when_no_index_available(tmp_path):
    root = tmp_path / "aveline_data" / "chat_history"
    root.mkdir(parents=True)
    tool = SearchChatHistoryTool()
    result = tool._peer_search_indexed(
        search_roots=[root],
        match_keywords=[],
        query="x",
        limit=10,
        roles=None,
        before_ts=None,
        after_ts=None,
        source="all",
    )
    assert result is None
