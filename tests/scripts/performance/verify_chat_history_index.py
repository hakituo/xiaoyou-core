"""验证 chat_history SQLite 派生索引相对文件扫描的耗时曲线与加速比。

运行：
    venv_core\\Scripts\\python.exe tests/scripts/performance/verify_chat_history_index.py
    venv_core\\Scripts\\python.exe tests/scripts/performance/verify_chat_history_index.py --days 30,180,365

做法：按 `天数 × 会话数 × 每文件事件数` 合成真实目录结构（YYYY/MM/DD/segment/cid.jsonl），
在**同一个数据集**上分别跑"文件扫描实现"和"SQLite 索引实现"，逐项取多次运行的
**最小值**（规避调度抖动），输出耗时表与加速比。

覆盖的真实热路径：
- `list_recent_events(limit=120)`：Memory 启动回填 / 主对话上下文补齐
- `list_conversation_events(query=...)`：指定会话的关键词查询
- `get_event_content`：记忆 readable 回源点查
- `SearchChatHistoryTool._search_in_store`：搜索工具"当前会话 + 同角色全部会话"
- peer 搜索：跨 scope 关键词匹配

注意：这是性能验证脚本，不做断言（不进入 CI）；正确性断言在
`tests/unit/test_chat_history_index.py` 与 `tests/unit/test_chat_history_search.py`。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.services import chat_history_index  # noqa: E402
from core.services.chat_history_index import reset_history_index_registry  # noqa: E402
from core.services.chat_history_store import ChatHistoryStore  # noqa: E402
from core.tools.search_chat_history_tool import (  # noqa: E402
    _PEER_MATCH_KEYWORDS,
    SearchChatHistoryTool,
)
from core.utils.data import data_paths as data_paths_module  # noqa: E402
from core.utils.data import scope_registry  # noqa: E402

# 全部同角色：让"同角色全部会话"扫描覆盖整个 scope，扫描与索引面对同一批数据
_CONVERSATIONS = [
    "shared__persona__core_aveline",
    "aveline_side",
    "aveline_love",
    "aveline_daily",
]
_KEYWORD = "火锅"
_FILLER = "今天出去骑车，天气不错，顺便买了点东西回来"
_BASE_DAY = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="chat_history 索引加速比验证")
    parser.add_argument("--days", default="30,180,365", help="逗号分隔的天数档位")
    parser.add_argument("--conversations", type=int, default=4)
    parser.add_argument("--per-file", type=int, default=25, help="每会话每天的事件数")
    parser.add_argument("--repeat", type=int, default=3, help="每个测量取最小值")
    return parser.parse_args()


def _build_dataset(root: Path, *, days: int, conversations: int, per_file: int) -> int:
    """按日期升序合成 JSONL，返回总事件数。"""
    total = 0
    for day_offset in range(days):
        day = _BASE_DAY - timedelta(days=day_offset)
        day_dir = (
            root / day.strftime("%Y") / day.strftime("%m") / day.strftime("%d") / "lane"
        )
        day_dir.mkdir(parents=True, exist_ok=True)
        for cid in _CONVERSATIONS[:conversations]:
            lines = []
            for index in range(per_file):
                timestamp = (day + timedelta(minutes=index)).timestamp()
                content = f"{_FILLER} #{day_offset}-{index}"
                if index == per_file - 1:
                    content = f"晚上吃了{_KEYWORD}，很满足 #{day_offset}"
                lines.append(
                    json.dumps(
                        {
                            "event_id": f"{cid}-{day_offset}-{index}",
                            "conversation_id": cid,
                            "message_id": f"m-{day_offset}-{index}",
                            "event_type": "message",
                            "role": "user" if index % 2 == 0 else "assistant",
                            "content": content,
                            "timestamp": timestamp,
                            "created_at": day.strftime("%Y-%m-%d 12:00:00"),
                            "metadata": {"platform": "qq"},
                            "readable_title": "Aveline / 主线对话",
                            "storage_scope": "aveline",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                total += 1
            (day_dir / f"{cid}.jsonl").write_text("".join(lines), encoding="utf-8")
    return total


def _time_it(fn, repeat: int) -> float:
    best = float("inf")
    for _ in range(max(repeat, 1)):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best


def _measure(root: Path, *, repeat: int) -> dict:
    cid = _CONVERSATIONS[0]
    event_ref = {
        "event_id": f"{cid}-0-0",
        "relative_path": f"2026/09/17/lane/{cid}.jsonl",
        "storage_scope": "aveline",
    }

    def _fake_role(conversation_id: str) -> str:
        text = str(conversation_id or "").lower()
        if "ling" in text:
            return "ling"
        if "aveline" in text:
            return "aveline"
        return ""

    original = {
        "dir_for_conv": data_paths_module.get_chat_history_dir_for_conversation,
        "all_dirs": data_paths_module.get_all_chat_history_dirs,
        "store_dirs": sys.modules[
            "core.services.chat_history_store"
        ].get_all_chat_history_dirs,
        "get_store": sys.modules["core.services.chat_history_store"].get_chat_history_store,
        "matched_role": scope_registry.matched_persona_scope,
        "index_factory": chat_history_index.get_history_index,
    }

    data_paths_module.get_chat_history_dir_for_conversation = lambda _cid: root
    data_paths_module.get_all_chat_history_dirs = lambda: [root]
    sys.modules["core.services.chat_history_store"].get_all_chat_history_dirs = (
        lambda: [root]
    )
    sys.modules["core.services.chat_history_store"].get_chat_history_store = (
        lambda: ChatHistoryStore(root)
    )
    scope_registry.matched_persona_scope = _fake_role

    tool = SearchChatHistoryTool()
    peer_keywords = _PEER_MATCH_KEYWORDS["aveline"]

    def peer_file_filter(fp: Path) -> bool:
        fp_text = str(fp).lower()
        return any(kw.lower() in fp_text for kw in peer_keywords)

    try:
        # 冷启动：全新索引的第一次搜索（含全量 ensure_sync 导入）
        reset_history_index_registry()
        cold_start = _time_it(
            lambda: tool._search_in_store(
                conversation_id=cid,
                query=_KEYWORD,
                limit=20,
                roles=None,
                before_ts=None,
                after_ts=None,
                scope="sfw",
                source="all",
            ),
            repeat=1,
        )

        store_indexed = ChatHistoryStore(root)

        def indexed_ops() -> dict:
            return {
                "recent_120": lambda: store_indexed.list_recent_events(
                    limit=120, roles=["user", "assistant"]
                ),
                "conversation_query": lambda: store_indexed.list_conversation_events(
                    cid, limit=0, query=_KEYWORD
                ),
                "event_content": lambda: store_indexed.get_event_content(event_ref),
                "scope_search": lambda: tool._search_in_store(
                    conversation_id=cid,
                    query=_KEYWORD,
                    limit=20,
                    roles=None,
                    before_ts=None,
                    after_ts=None,
                    scope="sfw",
                    source="all",
                ),
                "peer_search": lambda: tool._peer_search_indexed(
                    search_roots=[root],
                    match_keywords=peer_keywords,
                    query=_KEYWORD,
                    limit=20,
                    roles=None,
                    before_ts=None,
                    after_ts=None,
                    source="all",
                ),
            }

        # 关闭索引：所有查询退回文件扫描实现
        def _boom(*_args, **_kwargs):
            raise RuntimeError("index disabled for baseline")

        chat_history_index.get_history_index = _boom
        reset_history_index_registry()
        store_scanned = ChatHistoryStore(root)

        def scanned_ops() -> dict:
            return {
                "recent_120": lambda: store_scanned.list_recent_events(
                    limit=120, roles=["user", "assistant"]
                ),
                "conversation_query": lambda: store_scanned.list_conversation_events(
                    cid, limit=0, query=_KEYWORD
                ),
                "event_content": lambda: store_scanned.get_event_content(event_ref),
                "scope_search": lambda: tool._search_in_store(
                    conversation_id=cid,
                    query=_KEYWORD,
                    limit=20,
                    roles=None,
                    before_ts=None,
                    after_ts=None,
                    scope="sfw",
                    source="all",
                ),
                "peer_search": lambda: tool._scan_events(
                    search_roots=[root],
                    query=_KEYWORD,
                    limit=20,
                    roles=None,
                    before_ts=None,
                    after_ts=None,
                    scope="sfw",
                    file_filter=peer_file_filter,
                    source="all",
                ),
            }

        # 预热（把文件读进 OS 缓存）
        for fn in scanned_ops().values():
            fn()

        scanned = {name: _time_it(fn, repeat) for name, fn in scanned_ops().items()}
        chat_history_index.get_history_index = original["index_factory"]
        reset_history_index_registry()
        for fn in indexed_ops().values():
            fn()
        indexed = {name: _time_it(fn, repeat) for name, fn in indexed_ops().items()}
    finally:
        data_paths_module.get_chat_history_dir_for_conversation = original["dir_for_conv"]
        data_paths_module.get_all_chat_history_dirs = original["all_dirs"]
        sys.modules["core.services.chat_history_store"].get_all_chat_history_dirs = (
            original["store_dirs"]
        )
        sys.modules["core.services.chat_history_store"].get_chat_history_store = original[
            "get_store"
        ]
        scope_registry.matched_persona_scope = original["matched_role"]
        chat_history_index.get_history_index = original["index_factory"]
        reset_history_index_registry()

    return {
        "cold_first_search_seconds": cold_start,
        "scanned": scanned,
        "indexed": indexed,
    }


def main() -> int:
    args = _parse_args()
    days_list = [int(item) for item in str(args.days).split(",") if item.strip()]

    ops = ["recent_120", "conversation_query", "event_content", "scope_search", "peer_search"]
    header = f"{'天数':>6} {'事件数':>8} {'冷启动搜索(s)':>14} " + " ".join(
        f"{name}(扫描/索引/s)" for name in ops
    )
    print(header, flush=True)
    print("-" * len(header), flush=True)

    summary = []
    for days in days_list:
        tmp = tempfile.mkdtemp(prefix="xy_history_index_")
        try:
            root = Path(tmp) / "chat_history"
            root.mkdir(parents=True, exist_ok=True)
            events = _build_dataset(
                root,
                days=days,
                conversations=args.conversations,
                per_file=args.per_file,
            )
            result = _measure(root, repeat=args.repeat)
            cells = []
            for name in ops:
                scanned = result["scanned"][name]
                indexed = result["indexed"][name]
                speedup = scanned / indexed if indexed > 0 else float("inf")
                cells.append(f"{scanned:.4f}/{indexed:.4f}({speedup:.1f}x)")
            print(
                f"{days:>6} {events:>8} {result['cold_first_search_seconds']:>14.4f} "
                + " ".join(cells),
                flush=True,
            )
            summary.append({"days": days, "events": events, **result})
        finally:
            # 必须先关闭连接，Windows 才能删掉临时目录里的 db 文件
            reset_history_index_registry()
            shutil.rmtree(tmp, ignore_errors=True)

    print("-" * len(header), flush=True)
    print("明细：", json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
