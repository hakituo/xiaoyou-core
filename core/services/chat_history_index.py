"""ChatHistory 的 SQLite 派生索引。

定位（与 PLAN_history_sqlite_memory_perf.md §1 一致）：

```
JSONL   = durable source of truth（不动、不迁移、不删除）
              ↓ 增量同步 / 全量 rebuild
SQLite  = derived / disposable history index（可随时删，删后能重建）
```

三条硬约束：

1. **不阻断聊天**：JSONL append 成功而 DB 写失败时吞异常 + warning，下次
   ``ensure_sync`` / ``rebuild`` 补齐；返回值与文件扫描实现完全一致。
2. **不改变查询语义**：platform 的 ``qq`` 兼容空值、``chat_thought`` 排除、
   同角色文件过滤、event_id 去重 + 时间升序取尾部，全部按
   ``ChatHistoryStore`` 现有文件扫描实现逐条对齐。
3. **中文词面搜索维持 jieba 子串**：v1 不建 FTS5（trigram 对 <3 字查询不命中，
   中文 2 字词元是高频主体，上 FTS5 会直接漏召回），改用 ``content LIKE '%tok%'``
   在已过滤子集上执行，语义与 ``content.lower()`` 子串 OR 等价。

与计划文档的两处有意扩展（为语义等价服务，见 §1.3 备注）：

- ``events.readable_title``：JSONL 事件里本来就有，缺了会让
  ``/export`` 之类直接透传 payload 的调用方丢字段。
- ``events.file_stem``：现有同角色过滤与"排除当前会话文件"都是按
  **文件名 stem** 判定的（``rglob(f"{safe_cid}.jsonl")`` / ``path.stem``），
  只按 payload 的 ``conversation_id`` 过滤在旧数据上不等价，因此额外落一列。

索引集合与计划文档 §1.3 的差异：去掉了 role / event_type / platform 三个低基数
单列索引（实测会让"最近 N 条"退化成 TEMP B-TREE 排序，3.65 万事件下 0.6ms → 32ms），
改为 ``(file_stem, timestamp)`` 复合索引，直接服务最主要的"某会话文件按时间排序"查询。
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

logger = logging.getLogger(__name__)

#: schema 版本；不匹配（含未来变更）一律视为过期，drop 后整体 rebuild，
#: 绝不默默用旧结构读。
SCHEMA_VERSION = 1

#: ``ensure_sync`` 的默认节流窗口：窗口内不重复 rglob 文件清单。
#: append 走增量同步，因此这个 TTL 只影响"外部进程/手工改动"的发现延迟。
DEFAULT_SYNC_TTL_SECONDS = 30.0

_INDEX_DIR_NAME = "indexes"
_LEGACY_ID_PREFIX = "legacy:"

# 事件行插入语句：INSERT OR IGNORE + event_id 主键，天然幂等去重。
_INSERT_EVENT_SQL = """
INSERT OR IGNORE INTO events (
    event_id, conversation_id, storage_scope, role, event_type,
    timestamp, created_at, message_id, relative_path, file_stem,
    platform, content, metadata_json, readable_title
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_UPSERT_FILE_SQL = "INSERT OR REPLACE INTO files (relative_path, synced_bytes) VALUES (?, ?)"

# 首次进索引的文件先记成 0 字节偏移（= 尚未同步），由 ensure_sync 从头 tail 补齐，
# 避免"只索引了本次新写的行、却声称整个文件已同步"导致旧行永久丢失。
_INSERT_FILE_IF_ABSENT_SQL = (
    "INSERT OR IGNORE INTO files (relative_path, synced_bytes) VALUES (?, 0)"
)

_SCHEMA_SQL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS events (
        event_id        TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        storage_scope   TEXT NOT NULL DEFAULT '',
        role            TEXT NOT NULL DEFAULT 'system',
        event_type      TEXT NOT NULL DEFAULT 'message',
        timestamp       REAL NOT NULL DEFAULT 0,
        created_at      TEXT NOT NULL DEFAULT '',
        message_id      TEXT NOT NULL DEFAULT '',
        relative_path   TEXT NOT NULL,
        file_stem       TEXT NOT NULL DEFAULT '',
        platform        TEXT NOT NULL DEFAULT '',
        content         TEXT NOT NULL DEFAULT '',
        metadata_json   TEXT NOT NULL DEFAULT '{}',
        readable_title  TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS files (
        relative_path TEXT PRIMARY KEY,
        synced_bytes  INTEGER NOT NULL DEFAULT 0
    )
    """,
    # 索引集合按"真实查询形状"选，而不是按列各建一个：
    # role / event_type / platform 都是 2~3 个取值的低基数单列索引，SQLite 会优先
    # 用它们过滤再对结果做 TEMP B-TREE 排序——实测 3.65 万事件下"最近 N 条"
    # 从 0.6ms 劣化到 32ms。因此这三列不建单列索引，只保留能直接服务排序的复合索引。
    "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_events_conv_ts ON events(conversation_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_events_scope_ts ON events(storage_scope, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_events_file_stem_ts ON events(file_stem, timestamp)",
)

_TABLE_NAMES = ("events", "files")


def _to_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _file_stem_of(relative_path: str) -> str:
    """从相对 posix 路径取文件名 stem（``a/b/c.jsonl`` → ``c``）。"""
    tail = str(relative_path or "").replace("\\", "/").rsplit("/", 1)[-1]
    if tail.endswith(".jsonl"):
        tail = tail[: -len(".jsonl")]
    return tail


def _legacy_event_id(payload: Dict[str, Any]) -> str:
    """无 event_id 的旧记录用内容签名兜底。

    与 ``SearchChatHistoryTool._dedup_and_trim`` 的 ``legacy:`` 签名同源，
    保证索引路径与文件扫描路径对同一批旧数据去重结果一致。
    """
    try:
        signature = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    except Exception:
        signature = str(payload)
    digest = hashlib.sha1(signature.encode("utf-8", "replace")).hexdigest()
    return f"{_LEGACY_ID_PREFIX}{digest}"


def _like_pattern(value: str) -> str:
    """把字面量转成 ``%value%`` 的 LIKE 模式（转义 ``\\`` / ``%`` / ``_``）。"""
    text = str(value or "")
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def resolve_index_db_path(root: Path) -> Path:
    """按 root 派生 DB 路径，不硬编码 scope。

    - 标准 root ``companion_data/{scope}_data/chat_history``
      → ``companion_data/{scope}_data/indexes/chat_history.db``
    - 自定义 base_dir（测试/脚本）同规则派生，与真源同层、不混进数据目录。
    """
    root = Path(root)
    return root.parent / _INDEX_DIR_NAME / f"{root.name}.db"


class ChatHistoryIndex:
    """一个 chat_history 根目录对应的 SQLite 派生索引。

    并发模型：每实例单连接 ``check_same_thread=False`` + ``RLock`` 串行化
    全部访问；``journal_mode=WAL`` + ``synchronous=NORMAL``。锁内操作都是
    毫秒级索引读写，单连接足够（正确性由锁保证）。
    """

    def __init__(self, root: Path, *, db_path: Optional[Path] = None):
        self.root = Path(root).resolve()
        self.db_path = Path(db_path).resolve() if db_path else resolve_index_db_path(self.root)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._last_sync_at = 0.0
        self._last_sync_result: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    @property
    def version(self) -> int:
        return SCHEMA_VERSION

    def close(self) -> None:
        with self._lock:
            conn, self._conn = self._conn, None
            if conn is None:
                return
            try:
                conn.commit()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def _connect(self) -> sqlite3.Connection:
        conn = self._conn
        if conn is not None:
            return conn
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=10.0,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            # 内存库/只读介质等不支持 WAL 时继续用默认日志模式
            pass
        self._conn = conn
        self._ensure_schema(conn)
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version == SCHEMA_VERSION and self._tables_present(conn):
            return
        # schema 过期或结构缺失：整体重建，绝不按旧结构读。
        self._drop_all(conn)
        for statement in _SCHEMA_SQL:
            conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")
        conn.commit()
        self._last_sync_at = 0.0

    @staticmethod
    def _tables_present(conn: sqlite3.Connection) -> bool:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?)",
            _TABLE_NAMES,
        ).fetchall()
        return len(rows) == len(_TABLE_NAMES)

    @staticmethod
    def _drop_all(conn: sqlite3.Connection) -> None:
        for name in _TABLE_NAMES:
            conn.execute(f"DROP TABLE IF EXISTS {name}")

    def clear(self) -> None:
        """清空表数据，保留 schema。"""
        with self._lock:
            conn = self._connect()
            conn.execute("DELETE FROM events")
            conn.execute("DELETE FROM files")
            conn.commit()
            self._last_sync_at = 0.0

    def health(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "ok": False,
            "schema_version": 0,
            "expected_schema_version": SCHEMA_VERSION,
            "events": 0,
            "files": 0,
            "stale": False,
            "db_path": str(self.db_path),
        }
        with self._lock:
            try:
                conn = self._connect()
                info["schema_version"] = int(
                    conn.execute("PRAGMA user_version").fetchone()[0]
                )
                info["events"] = self._count(conn, "events")
                info["files"] = self._count(conn, "files")
                info["ok"] = info["schema_version"] == SCHEMA_VERSION
                # 磁盘有 JSONL 却一条都没索引 → 索引没跟上真源，调用方应回退文件扫描。
                info["stale"] = bool(
                    info["ok"] and info["files"] == 0 and self._root_has_jsonl()
                )
            except Exception as exc:  # pragma: no cover - 依赖文件系统异常
                info["error"] = str(exc)
        return info

    def is_usable(self) -> bool:
        """索引可读且没有"磁盘有文件、索引却为空"的异常状态。

        比 :meth:`health` 便宜（不做磁盘探测），供查询热路径调用；
        存在性判断用 ``LIMIT 1`` 而不是 ``COUNT(*)``，避免每次查询都全表数一遍。
        """
        with self._lock:
            try:
                conn = self._connect()
                if int(conn.execute("PRAGMA user_version").fetchone()[0]) != SCHEMA_VERSION:
                    return False
                if conn.execute("SELECT 1 FROM events LIMIT 1").fetchone() is not None:
                    return True
                # 事件为空：只有"确实没有文件"才算正常空库
                return conn.execute("SELECT 1 FROM files LIMIT 1").fetchone() is None
            except Exception:
                return False

    @staticmethod
    def _count(conn: sqlite3.Connection, table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _root_has_jsonl(self) -> bool:
        try:
            if not self.root.exists():
                return False
            return next(self.root.rglob("*.jsonl"), None) is not None
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def append_events(
        self,
        payloads: Sequence[Dict[str, Any]],
        *,
        relative_path: str,
        expected_bytes: Optional[int] = None,
        synced_bytes: Optional[int] = None,
    ) -> int:
        """增量写入一批事件，返回实际新增行数。

        偏移推进是有条件的：只有当该文件在本次 append 前**已经完整同步到**
        ``expected_bytes`` 时，才把 ``files.synced_bytes`` 推进到 ``synced_bytes``。
        否则保持原值，由 ``ensure_sync`` 从旧偏移 tail 补齐（``INSERT OR IGNORE``
        幂等），避免丢掉本进程更早写入、但索引还没见过的历史行。
        """
        rel = str(relative_path or "").replace("\\", "/")
        if not rel:
            return 0
        stem = _file_stem_of(rel)
        rows = []
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            rows.append(self._payload_to_row(payload, rel, stem))
        if not rows:
            return 0
        with self._lock:
            conn = self._connect()
            try:
                before = conn.total_changes
                conn.executemany(_INSERT_EVENT_SQL, rows)
                inserted = conn.total_changes - before
                conn.execute(_INSERT_FILE_IF_ABSENT_SQL, (rel,))
                if expected_bytes is not None:
                    offset = (
                        int(synced_bytes)
                        if synced_bytes is not None
                        else self._file_size(rel)
                    )
                    conn.execute(
                        "UPDATE files SET synced_bytes = ? "
                        "WHERE relative_path = ? AND synced_bytes = ?",
                        (offset, rel, int(expected_bytes)),
                    )
                conn.commit()
                return inserted
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise

    def delete_conversation(self, conversation_id: str) -> int:
        """按 conversation_id 与文件名 stem 删除事件行，并清掉对应 files 项。"""
        cid = str(conversation_id or "").strip()
        if not cid:
            return 0
        from core.utils.conversation_labels import _sanitize_segment

        stem = _sanitize_segment(cid)
        with self._lock:
            conn = self._connect()
            try:
                before = conn.total_changes
                conn.execute(
                    "DELETE FROM events WHERE conversation_id = ? OR file_stem = ?",
                    (cid, stem),
                )
                conn.execute(
                    "DELETE FROM files WHERE relative_path LIKE ? ESCAPE '\\'",
                    (_like_pattern(f"{stem}.jsonl"),),
                )
                deleted = conn.total_changes - before
                conn.commit()
                return deleted
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise

    def delete_file(self, relative_path: str) -> int:
        rel = str(relative_path or "").replace("\\", "/")
        if not rel:
            return 0
        with self._lock:
            conn = self._connect()
            try:
                before = conn.total_changes
                conn.execute("DELETE FROM events WHERE relative_path = ?", (rel,))
                conn.execute("DELETE FROM files WHERE relative_path = ?", (rel,))
                deleted = conn.total_changes - before
                conn.commit()
                return deleted
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise

    def _file_size(self, relative_path: str) -> int:
        try:
            return int((self.root / relative_path).stat().st_size)
        except Exception:
            return 0

    @staticmethod
    def _payload_to_row(payload: Dict[str, Any], relative_path: str, stem: str) -> tuple:
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        platform = str(metadata.get("platform") or "").strip().lower()
        event_id = str(payload.get("event_id") or "").strip() or _legacy_event_id(payload)
        return (
            event_id,
            str(payload.get("conversation_id") or ""),
            str(payload.get("storage_scope") or ""),
            str(payload.get("role") or "system"),
            str(payload.get("event_type") or "message"),
            _to_float(payload.get("timestamp")),
            str(payload.get("created_at") or ""),
            str(payload.get("message_id") or ""),
            relative_path,
            stem,
            platform,
            str(payload.get("content") or ""),
            json.dumps(metadata, ensure_ascii=False),
            str(payload.get("readable_title") or ""),
        )

    @staticmethod
    def _row_to_payload(row: sqlite3.Row) -> Dict[str, Any]:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except Exception:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        return {
            "event_id": row["event_id"],
            "conversation_id": row["conversation_id"],
            "message_id": row["message_id"],
            "event_type": row["event_type"],
            "role": row["role"],
            "content": row["content"],
            "timestamp": _to_float(row["timestamp"]),
            "created_at": row["created_at"],
            "metadata": metadata,
            "readable_title": row["readable_title"],
            "storage_scope": row["storage_scope"],
        }

    # ------------------------------------------------------------------
    # 同步
    # ------------------------------------------------------------------
    def _iter_jsonl_files(self) -> list[Path]:
        """列出全部 JSONL（只读目录，不读内容），路径排序保证重建确定性。"""
        if not self.root.exists():
            return []
        try:
            return sorted(self.root.rglob("*.jsonl"))
        except Exception:
            return []

    @staticmethod
    def _read_tail(file_path: Path, start: int) -> tuple[list[Dict[str, Any]], int]:
        """从 ``start`` 字节偏移读完整行，返回 (payloads, 新偏移)。

        只消费最后一个 ``\\n`` 之前的内容：末尾半行（写入中途/崩溃）留到下次同步，
        因此偏移永远落在字符边界上，也不会把半行 JSON 当坏行丢掉。
        """
        try:
            with open(file_path, "rb") as handle:
                handle.seek(max(int(start), 0))
                raw = handle.read()
        except Exception:
            return [], max(int(start), 0)
        if not raw:
            return [], max(int(start), 0)
        last_break = raw.rfind(b"\n")
        if last_break < 0:
            return [], max(int(start), 0)
        payloads: list[Dict[str, Any]] = []
        for line in raw[:last_break].split(b"\n"):
            if not line.strip():
                continue
            try:
                item = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            if isinstance(item, dict):
                payloads.append(item)
        return payloads, max(int(start), 0) + last_break + 1

    def mark_stale(self) -> None:
        """标记索引需要重新同步：下次 ``ensure_sync`` 不再受 TTL 节流。

        增量写入失败时调用，避免"索引暂时落后"被 TTL 放大成几十秒的可见性缺口。
        """
        with self._lock:
            self._last_sync_at = 0.0

    def ensure_sync(
        self,
        *,
        force: bool = False,
        ttl: float = DEFAULT_SYNC_TTL_SECONDS,
    ) -> Dict[str, Any]:
        """把索引补齐到与 JSONL 一致；幂等，可重复调用。

        返回 ``{synced_files, inserted_events, removed_files, skipped}``。
        """
        with self._lock:
            now = time.monotonic()
            if not force and self._last_sync_at and (now - self._last_sync_at) < ttl:
                result = dict(self._last_sync_result)
                result["skipped"] = True
                return result
            result = self._sync_locked()
            self._last_sync_at = time.monotonic()
            self._last_sync_result = dict(result)
            return result

    def _sync_locked(self) -> Dict[str, Any]:
        conn = self._connect()
        known = {
            str(row["relative_path"]): int(row["synced_bytes"] or 0)
            for row in conn.execute("SELECT relative_path, synced_bytes FROM files")
        }
        synced_files = 0
        inserted_events = 0
        seen: set[str] = set()
        try:
            for file_path in self._iter_jsonl_files():
                try:
                    rel = file_path.relative_to(self.root).as_posix()
                except Exception:
                    continue
                seen.add(rel)
                try:
                    size = int(file_path.stat().st_size)
                except OSError:
                    continue
                offset = known.get(rel)
                if offset is None or size < offset:
                    # 新文件 / 文件被重写或截断：整文件重读
                    if offset is not None:
                        conn.execute("DELETE FROM events WHERE relative_path = ?", (rel,))
                    start = 0
                elif size == offset:
                    continue
                else:
                    start = offset
                payloads, new_offset = self._read_tail(file_path, start)
                if payloads:
                    stem = _file_stem_of(rel)
                    rows = [self._payload_to_row(item, rel, stem) for item in payloads]
                    before = conn.total_changes
                    conn.executemany(_INSERT_EVENT_SQL, rows)
                    inserted_events += conn.total_changes - before
                conn.execute(_UPSERT_FILE_SQL, (rel, int(new_offset)))
                synced_files += 1

            removed_files = 0
            for rel in [path for path in known if path not in seen]:
                conn.execute("DELETE FROM events WHERE relative_path = ?", (rel,))
                conn.execute("DELETE FROM files WHERE relative_path = ?", (rel,))
                removed_files += 1
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        return {
            "synced_files": synced_files,
            "inserted_events": inserted_events,
            "removed_files": removed_files,
            "skipped": False,
        }

    def rebuild(self) -> Dict[str, Any]:
        """清空 → 按日期序全量导入 → 重建索引；幂等。"""
        with self._lock:
            conn = self._connect()
            conn.execute("DELETE FROM events")
            conn.execute("DELETE FROM files")
            conn.commit()
            events = 0
            files = 0
            try:
                for file_path in self._iter_jsonl_files():
                    try:
                        rel = file_path.relative_to(self.root).as_posix()
                    except Exception:
                        continue
                    payloads, offset = self._read_tail(file_path, 0)
                    if payloads:
                        stem = _file_stem_of(rel)
                        rows = [self._payload_to_row(item, rel, stem) for item in payloads]
                        before = conn.total_changes
                        conn.executemany(_INSERT_EVENT_SQL, rows)
                        events += conn.total_changes - before
                    conn.execute(_UPSERT_FILE_SQL, (rel, int(offset)))
                    files += 1
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
            self._last_sync_at = time.monotonic()
            self._last_sync_result = {
                "synced_files": files,
                "inserted_events": events,
                "removed_files": 0,
                "skipped": False,
            }
            return {"events": events, "files": files, "db_path": str(self.db_path)}

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def distinct_file_stems(self) -> list[str]:
        """该 root 下出现过的会话文件 stem（数量级 = 会话数，不是文件数）。"""
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT DISTINCT file_stem FROM events WHERE file_stem <> ''"
            ).fetchall()
            stems = {str(row[0]) for row in rows}
            rows = conn.execute("SELECT relative_path FROM files").fetchall()
        stems.update(_file_stem_of(str(row[0])) for row in rows)
        stems.discard("")
        return sorted(stems)

    def get_content(self, event_id: str) -> Optional[str]:
        """按主键点查事件正文；未命中返回 None（由调用方回退文件读）。"""
        eid = str(event_id or "").strip()
        if not eid:
            return None
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT content FROM events WHERE event_id = ?", (eid,)
            ).fetchone()
        return str(row["content"]) if row is not None else None

    def query(
        self,
        *,
        conversation_ids: Optional[Sequence[str]] = None,
        file_stems: Optional[Sequence[str]] = None,
        storage_scope: Optional[str] = None,
        roles: Optional[Sequence[str]] = None,
        event_types: Optional[Sequence[str]] = None,
        exclude_event_types: Optional[Sequence[str]] = None,
        platform: Optional[str] = None,
        before: Optional[float] = None,
        after: Optional[float] = None,
        query_tokens: Optional[Sequence[str]] = None,
        exclude_conversation_ids: Optional[Sequence[str]] = None,
        conversation_id_like_any: Optional[Sequence[str]] = None,
        relative_path_like_any: Optional[Sequence[str]] = None,
        exclude_file_stems: Optional[Sequence[str]] = None,
        limit: int = 0,
        offset: int = 0,
    ) -> list[Dict[str, Any]]:
        """统一查询入口，返回事件 payload 列表。

        ``limit > 0`` 时按"时间升序取尾部 limit 条"语义返回（与文件扫描实现
        的 ``result[-limit:]`` 一致）；``offset`` 从尾部起算。``limit == 0``
        返回全部命中，按时间升序。
        """
        clauses: list[str] = ["1=1"]
        params: list[Any] = []

        def _in_clause(column: str, values: Sequence[str]) -> str:
            placeholders = ",".join("?" for _ in values)
            params.extend(str(item) for item in values)
            return f"{column} IN ({placeholders})"

        if conversation_ids is not None:
            values = [str(item) for item in conversation_ids if str(item).strip()]
            if not values:
                return []
            clauses.append(_in_clause("conversation_id", values))
        if file_stems is not None:
            values = [str(item) for item in file_stems if str(item).strip()]
            if not values:
                return []
            clauses.append(_in_clause("file_stem", values))
        if exclude_file_stems:
            values = [str(item) for item in exclude_file_stems if str(item).strip()]
            if values:
                clauses.append(f"file_stem NOT IN ({','.join('?' for _ in values)})")
                params.extend(values)
        if exclude_conversation_ids:
            values = [str(item) for item in exclude_conversation_ids if str(item).strip()]
            if values:
                clauses.append(f"conversation_id NOT IN ({','.join('?' for _ in values)})")
                params.extend(values)
        if conversation_id_like_any:
            parts = []
            for keyword in conversation_id_like_any:
                if not str(keyword).strip():
                    continue
                parts.append("conversation_id LIKE ? ESCAPE '\\'")
                params.append(_like_pattern(str(keyword).lower()))
            if parts:
                clauses.append("(" + " OR ".join(parts) + ")")
        if relative_path_like_any:
            parts = []
            for keyword in relative_path_like_any:
                if not str(keyword).strip():
                    continue
                parts.append("lower(relative_path) LIKE ? ESCAPE '\\'")
                params.append(_like_pattern(str(keyword).lower()))
            if parts:
                clauses.append("(" + " OR ".join(parts) + ")")
        if storage_scope is not None:
            clauses.append("storage_scope = ?")
            params.append(str(storage_scope))
        if roles:
            values = [str(item).strip().lower() for item in roles if str(item).strip()]
            if not values:
                return []
            clauses.append(_in_clause("role", values))
        if event_types:
            values = [str(item).strip() for item in event_types if str(item).strip()]
            if not values:
                return []
            clauses.append(_in_clause("event_type", values))
        if exclude_event_types:
            values = [str(item).strip() for item in exclude_event_types if str(item).strip()]
            if values:
                clauses.append(f"event_type NOT IN ({','.join('?' for _ in values)})")
                params.extend(values)
        if platform:
            normalized = str(platform).strip().lower()
            if normalized == "qq":
                # 存量历史无 platform 字段，默认归 QQ（Obsidian 是新接入的）
                clauses.append("(platform = '' OR platform = 'qq')")
            elif normalized:
                clauses.append("platform = ?")
                params.append(normalized)
        if before is not None:
            clauses.append("timestamp < ?")
            params.append(float(before))
        if after is not None:
            clauses.append("timestamp >= ?")
            params.append(float(after))
        if query_tokens:
            parts = []
            for token in query_tokens:
                text = str(token or "")
                if not text:
                    continue
                parts.append("content LIKE ? ESCAPE '\\'")
                params.append(_like_pattern(text))
            if parts:
                clauses.append("(" + " OR ".join(parts) + ")")

        sql = "SELECT * FROM events WHERE " + " AND ".join(clauses)
        page = int(limit) if limit and int(limit) > 0 else 0
        skip = max(int(offset), 0)

        with self._lock:
            conn = self._connect()
            if page:
                # 先按时间倒序取"最新 page+skip 条"，翻回升序后丢掉最新的 skip 条
                rows = list(
                    conn.execute(
                        sql + " ORDER BY timestamp DESC, rowid DESC LIMIT ?",
                        [*params, page + skip],
                    ).fetchall()
                )
                rows.reverse()
                if skip:
                    rows = rows[:-skip] if skip < len(rows) else []
            else:
                sql = sql + " ORDER BY timestamp ASC, rowid ASC"
                if skip:
                    sql += " LIMIT -1 OFFSET ?"
                    params.append(skip)
                rows = conn.execute(sql, params).fetchall()
        return [self._row_to_payload(row) for row in rows]


# ----------------------------------------------------------------------
# 模块级实例注册表
# ----------------------------------------------------------------------
_REGISTRY_LOCK = threading.Lock()
_REGISTRY: Dict[str, ChatHistoryIndex] = {}


def get_history_index(root: Path, *, db_path: Optional[Path] = None) -> ChatHistoryIndex:
    """按 root 缓存索引实例；DB 被删后下次调用自动重建 schema。"""
    resolved = Path(root).resolve()
    key = str(resolved)
    with _REGISTRY_LOCK:
        index = _REGISTRY.get(key)
        if index is None:
            index = ChatHistoryIndex(resolved, db_path=db_path)
            _REGISTRY[key] = index
        return index


def reset_history_index_registry() -> None:
    """清空注册表并关闭连接（测试与维护脚本用）。"""
    with _REGISTRY_LOCK:
        indexes = list(_REGISTRY.values())
        _REGISTRY.clear()
    for index in indexes:
        index.close()


def rebuild_history_index(scope: Optional[str] = None) -> Dict[str, Any]:
    """重建索引；``scope`` 为空表示所有已注册角色的 chat_history 根。"""
    from core.utils.data_paths import get_all_chat_history_dirs, get_role_chat_history_dir

    if scope:
        roots: Iterable[Path] = [get_role_chat_history_dir(scope)]
    else:
        roots = get_all_chat_history_dirs()

    result: Dict[str, Any] = {}
    for root in roots:
        key = str(Path(root))
        try:
            result[key] = get_history_index(root).rebuild()
        except Exception as exc:
            logger.warning("重建 chat_history 索引失败: %s (%s)", root, exc)
            result[key] = {"error": str(exc)}
    return result
