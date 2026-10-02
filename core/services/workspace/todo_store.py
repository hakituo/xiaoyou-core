"""待办清单存储。

设计要点：
- **按角色隔离**：待办是"这个角色记下的、关于主人的事"，不是主人自己的共享清单。
  Aveline记的待办只有Aveline看得到，叶有叶自己的一份，存 ``companion_data/<scope>_data/todo_list.json``。
- 同步文件 IO：待办文件很小，既供工具调用，也供每轮 prompt 注入（prompt 拼装是
  同步上下文，无法 await），统一同步读写最省事。
- 写入用 tmp + os.replace 原子替换；空清单直接删文件，避免残留空壳。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.utils.data.data_paths import get_role_data_dir
from core.utils.time.time_utils import now_str

TODO_FILE_NAME = "todo_list.json"

STATUS_PENDING = "pending"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"
VALID_STATUSES = (STATUS_PENDING, STATUS_DONE, STATUS_CANCELLED)

PRIORITY_HIGH = "high"
PRIORITY_NORMAL = "normal"
PRIORITY_LOW = "low"
VALID_PRIORITIES = (PRIORITY_HIGH, PRIORITY_NORMAL, PRIORITY_LOW)

# 未完成条目上限：防止模型反复写入把清单撑爆，也保护 prompt 注入长度
MAX_ACTIVE_ITEMS = 50
MAX_TITLE_LEN = 60
MAX_NOTE_LEN = 200
MAX_DUE_LEN = 32

_TS_FORMAT = "%Y-%m-%d %H:%M"
_PRIORITY_LABELS = {PRIORITY_HIGH: "重要", PRIORITY_NORMAL: "普通", PRIORITY_LOW: "有空再说"}
_PRIORITY_ORDER = {PRIORITY_HIGH: 0, PRIORITY_NORMAL: 1, PRIORITY_LOW: 2}


def _clean_text(value: Any, max_len: int) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) > max_len:
        text = text[:max_len].rstrip()
    return text


class TodoStore:
    """待办清单读写。参数非法时抛 ``ValueError``，由工具层转成自然语言返回。"""

    def __init__(self, scope: Optional[str] = None, file_path: Optional[Path] = None):
        if file_path is not None:
            self._file_path = Path(file_path).resolve()
        else:
            self._file_path = (get_role_data_dir(scope or "user") / TODO_FILE_NAME).resolve()
        self.scope = str(scope or "").strip()

    @property
    def file_path(self) -> Path:
        return self._file_path

    # ── 读写 ──────────────────────────────────────────────────
    def _read(self) -> Dict[str, Any]:
        if not self._file_path.exists():
            return {"version": 1, "items": []}
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                raw = json.loads(f.read() or "{}")
        except Exception:
            # 损坏文件不覆盖、不抛出：退化为空清单，避免整个工具链崩掉
            return {"version": 1, "items": []}
        items = raw.get("items") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            return {"version": 1, "items": []}
        return {"version": 1, "items": [i for i in items if isinstance(i, dict)]}

    def _write(self, data: Dict[str, Any]) -> None:
        items = data.get("items") or []
        if not items:
            if self._file_path.exists():
                self._file_path.unlink()
            return
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._file_path.with_suffix(self._file_path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "items": items}, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self._file_path)

    # ── 内部工具 ──────────────────────────────────────────────
    @staticmethod
    def _next_id(items: List[Dict[str, Any]]) -> str:
        max_id = 0
        for item in items:
            try:
                max_id = max(max_id, int(str(item.get("id") or "0")))
            except ValueError:
                continue
        return str(max_id + 1)

    @staticmethod
    def _sort_key(item: Dict[str, Any]) -> tuple:
        status = str(item.get("status") or STATUS_PENDING)
        status_rank = 0 if status == STATUS_PENDING else 1
        priority = str(item.get("priority") or PRIORITY_NORMAL).lower()
        try:
            seq = int(str(item.get("id") or "0"))
        except ValueError:
            seq = 0
        return (status_rank, _PRIORITY_ORDER.get(priority, 1), seq)

    @staticmethod
    def _find(items: List[Dict[str, Any]], item_id: str) -> Optional[Dict[str, Any]]:
        target = str(item_id).strip().lstrip("#")
        for item in items:
            if str(item.get("id")) == target:
                return item
        return None

    # ── 对外操作 ──────────────────────────────────────────────
    def list_items(self, *, include_done: bool = False, limit: int = 20) -> List[Dict[str, Any]]:
        items = list(self._read().get("items") or [])
        if not include_done:
            items = [
                item for item in items
                if str(item.get("status") or STATUS_PENDING) == STATUS_PENDING
            ]
        items.sort(key=self._sort_key)
        if limit and limit > 0:
            items = items[:limit]
        return items

    def count_pending(self) -> int:
        return len([
            item for item in (self._read().get("items") or [])
            if str(item.get("status") or STATUS_PENDING) == STATUS_PENDING
        ])

    def add_item(
        self,
        title: str,
        *,
        priority: str = PRIORITY_NORMAL,
        due: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        clean_title = _clean_text(title, MAX_TITLE_LEN)
        if not clean_title:
            raise ValueError("待办内容不能为空")
        clean_priority = str(priority or PRIORITY_NORMAL).strip().lower()
        if clean_priority not in VALID_PRIORITIES:
            clean_priority = PRIORITY_NORMAL

        data = self._read()
        items = list(data.get("items") or [])
        pending = [
            item for item in items
            if str(item.get("status") or STATUS_PENDING) == STATUS_PENDING
        ]
        if len(pending) >= MAX_ACTIVE_ITEMS:
            raise ValueError(f"未完成待办已达上限 {MAX_ACTIVE_ITEMS} 条，先划掉或删掉几条再记新的")
        for item in pending:
            if str(item.get("title") or "").strip() == clean_title:
                raise ValueError(f"已经有同样的待办了（#{item.get('id')}），不用重复记")

        now = now_str(_TS_FORMAT)
        new_item = {
            "id": self._next_id(items),
            "title": clean_title,
            "status": STATUS_PENDING,
            "priority": clean_priority,
            "due": _clean_text(due, MAX_DUE_LEN),
            "note": _clean_text(note, MAX_NOTE_LEN),
            "created_at": now,
            "updated_at": now,
            "completed_at": "",
        }
        items.append(new_item)
        self._write({"items": items})
        return new_item

    def update_item(self, item_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        data = self._read()
        items = list(data.get("items") or [])
        item = self._find(items, item_id)
        if item is None:
            raise ValueError(f"找不到待办 #{item_id}，先用 get_todo_list 看看现在的编号")

        if updates.get("title") is not None:
            clean_title = _clean_text(updates["title"], MAX_TITLE_LEN)
            if not clean_title:
                raise ValueError("待办内容不能为空")
            item["title"] = clean_title
        if updates.get("note") is not None:
            item["note"] = _clean_text(updates["note"], MAX_NOTE_LEN)
        if updates.get("due") is not None:
            item["due"] = _clean_text(updates["due"], MAX_DUE_LEN)
        if updates.get("priority") is not None:
            priority = str(updates["priority"]).strip().lower()
            if priority not in VALID_PRIORITIES:
                raise ValueError(f"优先级只能是 {'/'.join(VALID_PRIORITIES)}")
            item["priority"] = priority
        if updates.get("status") is not None:
            status = str(updates["status"]).strip().lower()
            if status not in VALID_STATUSES:
                raise ValueError(f"状态只能是 {'/'.join(VALID_STATUSES)}")
            item["status"] = status
            item["completed_at"] = now_str(_TS_FORMAT) if status != STATUS_PENDING else ""
        item["updated_at"] = now_str(_TS_FORMAT)

        self._write({"items": items})
        return item

    def remove_item(self, item_id: str) -> Dict[str, Any]:
        data = self._read()
        items = list(data.get("items") or [])
        item = self._find(items, item_id)
        if item is None:
            raise ValueError(f"找不到待办 #{item_id}")
        items = [row for row in items if row is not item]
        self._write({"items": items})
        return item

    # ── 展示 ──────────────────────────────────────────────────
    @staticmethod
    def format_item(item: Dict[str, Any]) -> str:
        parts = [f"#{item.get('id')} {item.get('title') or ''}"]
        status = str(item.get("status") or STATUS_PENDING)
        if status == STATUS_DONE:
            parts.append("（已划掉）")
        elif status == STATUS_CANCELLED:
            parts.append("（不做了）")
        else:
            priority = str(item.get("priority") or PRIORITY_NORMAL).lower()
            if priority != PRIORITY_NORMAL:
                parts.append(f"（{_PRIORITY_LABELS.get(priority, priority)}）")
        if item.get("due"):
            parts.append(f"（{item.get('due')}）")
        if item.get("note"):
            parts.append(f"——{item.get('note')}")
        return "".join(parts)

    def format_for_llm(self, *, include_done: bool = False, limit: int = 20) -> str:
        items = self.list_items(include_done=include_done, limit=limit)
        if not items:
            return "现在没有待办。"
        head = "待办清单：" if include_done else f"待办 {self.count_pending()} 条："
        lines = [head]
        lines.extend(f"- {self.format_item(item)}" for item in items)
        return "\n".join(lines)

    def format_for_prompt(self, limit: int = 5) -> str:
        """给每轮 prompt 注入用的极简摘要；没有待办时返回空字符串。"""
        items = self.list_items(include_done=False, limit=limit)
        if not items:
            return ""
        pending_count = self.count_pending()
        more = f"（只列前 {limit} 条）" if pending_count > len(items) else ""
        lines = [f"当前待办 {pending_count} 条{more}："]
        lines.extend(f"- #{item.get('id')} {item.get('title')}" for item in items)
        return "\n".join(lines)


_stores: Dict[str, TodoStore] = {}


def get_todo_store(scope: Optional[str] = None) -> TodoStore:
    """按角色 scope 取待办 store；未登记的人设落到 user 目录。

    测试可直接 ``TodoStore(file_path=...)`` 构造，不经过缓存。
    """
    key = str(scope or "").strip().lower() or "user"
    store = _stores.get(key)
    if store is None:
        store = TodoStore(key)
        _stores[key] = store
    return store
