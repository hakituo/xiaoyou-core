import json
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

from core.utils.atomic_io import safe_json_dump
from core.utils.conversation_labels import _sanitize_segment, get_conversation_label_info
from core.utils.data_paths import (
    get_all_chat_history_dirs,
    get_chat_history_dir_for_conversation,
    normalize_data_scope,
    resolve_data_scope_from_conversation_id,
)
from core.utils.time_utils import get_current_time


_LOCK = threading.Lock()
_INSTANCE = None

#: 已就"索引不可用、已回退文件扫描"告警过的 root，避免热路径刷日志
_FALLBACK_LOGGED: set[str] = set()
_FALLBACK_LOG_LOCK = threading.Lock()


def _log_index_fallback(root: Path, reason: str) -> None:
    key = f"{root}|{reason}"
    with _FALLBACK_LOG_LOCK:
        if key in _FALLBACK_LOGGED:
            return
        _FALLBACK_LOGGED.add(key)
    try:
        from core.utils.logger import get_logger

        get_logger("ChatHistoryStore").warning(
            f"chat_history SQLite 索引不可用（{reason}），已回退文件扫描: {root}"
        )
    except Exception:
        pass


def _tokenize_query(query: str) -> list[str]:
    """将查询拆分为用于子串匹配的词元列表

    原实现按空格切分，中文查询（如"初中女生"）会作为整串参与匹配，
    导致匹配不到词面相近的原文（如"初二的女生"）。
    改用 jieba 分词后每个词元独立参与 OR 匹配，同时保留整串兜底，
    保证精确短语匹配能力不退化。
    """
    normalized = str(query or "").strip().lower()
    if not normalized:
        return []

    tokens: list[str] = []
    try:
        import jieba

        jieba.setLogLevel(60)
        for word in jieba.cut(normalized, cut_all=False):
            w = str(word).strip()
            if len(w) >= 2:
                tokens.append(w)
    except Exception:
        pass

    # jieba 不可用或全部切成单字时，回退为空格切分
    if not tokens:
        tokens = [t for t in normalized.split() if t]

    # 保留整串作为兜底词元：长查询的精确短语匹配语义不受分词影响
    if normalized not in tokens:
        tokens.append(normalized)
    return tokens


class ChatHistoryStore:
    def __init__(self, base_dir: Optional[Path] = None):
        self._base_dir = Path(base_dir).resolve() if base_dir else None
        if self._base_dir is not None:
            self._base_dir.mkdir(parents=True, exist_ok=True)

    def _get_base_dir(self, conversation_id: Optional[str] = None) -> Path:
        if self._base_dir is not None:
            return self._base_dir
        base_dir = Path(get_chat_history_dir_for_conversation(conversation_id)).resolve()
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir

    @staticmethod
    def _iter_day_dirs_desc(base_dir: Path):
        """按 YYYY/MM/DD 从新到旧遍历日期目录，不扫描文件内容。"""
        if not base_dir.exists():
            return
        years = sorted(
            (path for path in base_dir.iterdir() if path.is_dir() and path.name.isdigit()),
            key=lambda path: path.name,
            reverse=True,
        )
        for year_dir in years:
            months = sorted(
                (
                    path
                    for path in year_dir.iterdir()
                    if path.is_dir() and path.name.isdigit()
                ),
                key=lambda path: path.name,
                reverse=True,
            )
            for month_dir in months:
                days = sorted(
                    (
                        path
                        for path in month_dir.iterdir()
                        if path.is_dir() and path.name.isdigit()
                    ),
                    key=lambda path: path.name,
                    reverse=True,
                )
                yield from days

    @staticmethod
    def _index_for(root: Path):
        """返回 root 对应的派生索引实例；不可用时返回 None。"""
        try:
            from core.services.chat_history_index import get_history_index

            return get_history_index(root)
        except Exception:
            return None

    @staticmethod
    def _synced_index(root: Path):
        """返回已补齐到与 JSONL 一致的索引；补齐失败或索引不可用时返回 None。

        SQLite 只是派生层：任何异常都只降级、不向上抛，调用方据此回退文件扫描。
        """
        index = ChatHistoryStore._index_for(root)
        if index is None:
            return None
        try:
            index.ensure_sync()
            if index.is_usable():
                return index
            _log_index_fallback(root, "索引为空但磁盘有数据")
        except Exception as exc:
            _log_index_fallback(root, f"{type(exc).__name__}: {exc}")
        return None

    @staticmethod
    def _sync_index_after_append(
        root: Path,
        payloads: Sequence[Dict[str, Any]],
        rel_path: str,
        *,
        expected_bytes: int,
        synced_bytes: int,
    ) -> None:
        """JSONL 写成功后同步索引；失败只告警，不影响 append 语义。

        接受一批 payload：批量写入时整批一次提交，避免每条消息各开一次事务。
        """
        try:
            from core.services.chat_history_index import get_history_index

            get_history_index(root).append_events(
                payloads,
                relative_path=rel_path,
                expected_bytes=expected_bytes,
                synced_bytes=synced_bytes,
            )
        except Exception as exc:
            try:
                from core.utils.logger import get_logger

                get_logger("ChatHistoryStore").warning(
                    f"chat_history 索引增量写入失败（JSONL 已落盘，稍后由 ensure_sync 补齐）: {exc}"
                )
            except Exception:
                pass
            # 让下次查询立即重新同步，而不是等 TTL 过期
            try:
                from core.services.chat_history_index import get_history_index

                get_history_index(root).mark_stale()
            except Exception:
                pass

    def _prepare_append_payload(
        self,
        *,
        conversation_id: str,
        role: Any,
        content: str,
        message_id: str,
        event_type: Any,
        metadata: Optional[Dict[str, Any]],
        dt: Any,
        label_info: Dict[str, Any],
        storage_scope: str,
    ) -> Dict[str, Any]:
        """构造一条待落盘事件；逐条与批量路径共用，保证两者结构完全一致。"""
        return {
            "event_id": uuid.uuid4().hex,
            "conversation_id": str(conversation_id or "default"),
            "message_id": str(message_id or ""),
            "event_type": str(event_type or "message"),
            "role": str(role or "system"),
            "content": str(content or ""),
            "timestamp": float(dt.timestamp()),
            "created_at": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "metadata": metadata if isinstance(metadata, dict) else {},
            "readable_title": str(label_info.get("readable_title") or ""),
            "storage_scope": storage_scope,
        }

    def _day_file_for(
        self,
        conversation_id: str,
        dt: Any,
        label_info: Dict[str, Any],
        base_dir: Path,
    ) -> tuple[Path, Path, Path]:
        """按 年/月/日/分线 定位落盘位置，返回 (day_dir, lane_dir, file_path)。"""
        safe_cid = _sanitize_segment(conversation_id)
        day_dir = base_dir / dt.strftime("%Y") / dt.strftime("%m") / dt.strftime("%d")
        lane_dir = day_dir
        chat_segments = list(label_info.get("chat_segments") or [])
        if not chat_segments:
            chat_segments = [str(label_info.get("safe_lane") or "default_lane")]
        for segment in chat_segments:
            lane_dir = lane_dir / str(segment)
        return day_dir, lane_dir, lane_dir / f"{safe_cid}.jsonl"

    def _write_event_group(self, group: Dict[str, Any]) -> None:
        """把一个文件组内的事件一次写完，并只更新一次当天索引与派生索引。

        与逐条路径的差别只在「合并次数」：JSONL 仍然追加写、当天 index.json 仍然
        按同一规则重写、派生索引仍然走 append_events，所以落盘结果与逐条完全一致。
        """
        lane_dir: Path = group["lane_dir"]
        file_path: Path = group["file_path"]
        base_dir: Path = group["base_dir"]
        payloads: list[Dict[str, Any]] = group["payloads"]

        lane_dir.mkdir(parents=True, exist_ok=True)
        try:
            size_before = file_path.stat().st_size
        except OSError:
            size_before = 0
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(
                "\n".join(
                    json.dumps(payload, ensure_ascii=False) for payload in payloads
                )
                + "\n"
            )
        self._update_day_index_for_file(
            group["day_dir"],
            base_dir,
            file_path,
            conversation_id=payloads[0]["conversation_id"],
            readable_title=payloads[0]["readable_title"],
        )
        try:
            size_after = file_path.stat().st_size
        except OSError:
            size_after = size_before
        self._sync_index_after_append(
            base_dir,
            payloads,
            group["rel_path"],
            expected_bytes=size_before,
            synced_bytes=size_after,
        )

    def append_event(
        self,
        *,
        conversation_id: str,
        role: str,
        content: str,
        message_id: str,
        event_type: str = "message",
        metadata: Optional[Dict[str, Any]] = None,
        now_dt=None,
    ) -> Dict[str, Any]:
        return self.append_events(
            [
                {
                    "conversation_id": conversation_id,
                    "role": role,
                    "content": content,
                    "message_id": message_id,
                    "event_type": event_type,
                    "metadata": metadata,
                    "now_dt": now_dt,
                }
            ]
        )[0]

    def append_events(self, events: Sequence[Dict[str, Any]]) -> list[Dict[str, Any]]:
        """批量追加事件；语义与逐条 append_event 完全一致，但把落盘与索引操作按文件合并。

        每项事件接受与 ``append_event`` 相同的键：``conversation_id`` / ``role`` /
        ``content`` / ``message_id`` / ``event_type`` / ``metadata`` / ``now_dt``。
        返回值与入参等长、顺序一致；被 debug/error 过滤掉的条目返回与逐条路径相同的
        ``filtered`` 结构（``relative_path`` 为空串）。

        存在的理由：逐条调用时，每条消息都要「打开一次 JSONL + 整份重写当天
        index.json + 派生索引单独提交一次事务」。导入上万条历史记录时这部分固定
        开销占绝对多数（实测单条约 20~30ms，四万余条要跑几十分钟）。本方法按
        (会话, 天, 分线) 归组后，每个文件只打开写一次、当天索引只更新一次、派生
        索引只提交一批，因此批量导入可以快一两个数量级。
        """
        from core.utils.debug_markers import is_debug_context_message

        if not events:
            return []

        refs: list[Dict[str, Any]] = []
        # 按落盘文件归组；dict 保序，且同一文件内按入参顺序追加，行序与逐条一致
        groups: Dict[Path, Dict[str, Any]] = {}
        contexts: Dict[str, Dict[str, Any]] = {}

        for event in events:
            conversation_id = str(event.get("conversation_id") or "")
            role = event.get("role")
            content = str(event.get("content") or "")
            if is_debug_context_message(content):
                from core.utils.logger import get_logger

                get_logger("ChatHistoryStore").info(
                    f"Filtered out debug/error message from chat history store: {content[:100]}"
                )
                refs.append(
                    {
                        "event_id": "filtered",
                        "relative_path": "",
                        "mirror_relative_path": "",
                        "timestamp": 0.0,
                        "role": role,
                        "conversation_id": event.get("conversation_id"),
                        "storage_scope": "filtered",
                    }
                )
                continue

            # 标签与 scope 只跟会话有关，同一批里按会话缓存，省掉逐条重复解析
            context = contexts.get(conversation_id)
            if context is None:
                label_info = get_conversation_label_info(conversation_id)
                label_scope = normalize_data_scope(
                    label_info.get("storage_scope"), default="aveline"
                )
                context = {
                    "label_info": label_info,
                    "storage_scope": resolve_data_scope_from_conversation_id(
                        conversation_id, default=label_scope
                    ),
                    "base_dir": self._get_base_dir(conversation_id),
                }
                contexts[conversation_id] = context

            dt = event.get("now_dt") or get_current_time()
            day_dir, lane_dir, file_path = self._day_file_for(
                conversation_id, dt, context["label_info"], context["base_dir"]
            )
            payload = self._prepare_append_payload(
                conversation_id=conversation_id,
                role=role,
                content=content,
                message_id=str(event.get("message_id") or ""),
                event_type=event.get("event_type"),
                metadata=event.get("metadata"),
                dt=dt,
                label_info=context["label_info"],
                storage_scope=context["storage_scope"],
            )
            rel_path = file_path.relative_to(context["base_dir"]).as_posix()

            group = groups.get(file_path)
            if group is None:
                group = {
                    "day_dir": day_dir,
                    "lane_dir": lane_dir,
                    "file_path": file_path,
                    "base_dir": context["base_dir"],
                    "rel_path": rel_path,
                    "payloads": [],
                }
                groups[file_path] = group
            group["payloads"].append(payload)
            refs.append(
                {
                    "event_id": payload["event_id"],
                    "relative_path": rel_path,
                    "mirror_relative_path": rel_path,
                    "timestamp": payload["timestamp"],
                    "role": payload["role"],
                    "conversation_id": payload["conversation_id"],
                    "storage_scope": context["storage_scope"],
                }
            )

        with _LOCK:
            for group in groups.values():
                self._write_event_group(group)

        return refs

    def rebuild_readable_mirrors(self) -> Dict[str, int]:
        return {"copied": 0, "skipped": 0}

    def delete_conversation(self, conversation_id: str) -> Dict[str, int]:
        safe_cid = _sanitize_segment(conversation_id)
        removed = 0
        reindexed = 0
        candidate_roots = [self._get_base_dir(conversation_id)]
        for root in get_all_chat_history_dirs():
            if root not in candidate_roots:
                candidate_roots.append(root)
        with _LOCK:
            for base_dir in candidate_roots:
                matched_days = set()
                if base_dir.exists():
                    for file_path in list(base_dir.rglob(f"{safe_cid}.jsonl")):
                        try:
                            rel_parts = file_path.relative_to(base_dir).parts
                        except Exception:
                            continue
                        if len(rel_parts) < 4:
                            continue
                        day_dir = base_dir / rel_parts[0] / rel_parts[1] / rel_parts[2]
                        try:
                            file_path.unlink()
                            removed += 1
                            matched_days.add(day_dir)
                        except Exception:
                            continue
                    for day_dir in matched_days:
                        self._write_day_index(day_dir, base_dir)
                        reindexed += 1
                # 索引只是派生数据：删会话时同步清行，失败留给 ensure_sync 兜底。
                # 该 root 没删到文件且索引库还不存在时直接跳过，避免凭空建出空库。
                index = self._index_for(base_dir)
                if index is None:
                    continue
                if not matched_days and not index.db_path.exists():
                    continue
                try:
                    index.delete_conversation(conversation_id)
                except Exception as exc:
                    _log_index_fallback(base_dir, f"delete_conversation: {exc}")
        return {"removed_files": removed, "reindexed_days": reindexed}

    def _update_day_index_for_file(
        self,
        day_dir: Path,
        base_dir: Path,
        file_path: Path,
        *,
        conversation_id: str,
        readable_title: str,
    ) -> None:
        """增量维护当天索引；索引缺失/损坏时才回退全量重建。"""
        try:
            index_path = day_dir / "index.json"
            if not index_path.exists():
                self._write_day_index(day_dir, base_dir)
                return

            try:
                raw = json.loads(index_path.read_text(encoding="utf-8"))
            except Exception:
                self._write_day_index(day_dir, base_dir)
                return

            files = raw.get("files") if isinstance(raw, dict) else None
            if not isinstance(files, list):
                self._write_day_index(day_dir, base_dir)
                return

            rel = file_path.relative_to(base_dir).as_posix()
            item = {
                "relative_path": rel,
                "view": "readable",
                "name": file_path.name,
                "conversation_id": str(conversation_id or file_path.stem or "default"),
                "readable_title": str(readable_title or ""),
            }
            updated = []
            replaced = False
            for existing in files:
                if not isinstance(existing, dict):
                    continue
                if str(existing.get("relative_path") or "") == rel:
                    updated.append(item)
                    replaced = True
                else:
                    updated.append(existing)
            if not replaced:
                updated.append(item)
            updated.sort(key=lambda entry: str(entry.get("relative_path") or ""))
            safe_json_dump({"files": updated}, index_path, encoding="utf-8")
        except Exception:
            # 索引只是派生数据；任何异常都回退到现有全量重建逻辑。
            self._write_day_index(day_dir, base_dir)

    def _write_day_index(self, day_dir: Path, base_dir: Path) -> None:
        try:
            if not day_dir.exists():
                return
            items = []
            for path in sorted(day_dir.rglob("*.jsonl")):
                rel = path.relative_to(base_dir).as_posix()
                cid = str(path.stem or "").strip()
                label_info = get_conversation_label_info(cid)
                items.append(
                    {
                        "relative_path": rel,
                        "view": "readable",
                        "name": path.name,
                        "conversation_id": str(
                            label_info.get("conversation_id") or cid or "default"
                        ),
                        "readable_title": str(label_info.get("readable_title") or ""),
                    }
                )
            index_path = day_dir / "index.json"
            # P0-17: 用原子写入保存聊天历史索引，避免进程崩溃导致索引损坏
            safe_json_dump({"files": items}, index_path, encoding="utf-8")
        except Exception:
            return

    def get_event_content(self, event_ref: Dict[str, Any]) -> Optional[str]:
        if not isinstance(event_ref, dict):
            return None
        rel_path = str(event_ref.get("relative_path") or "").strip()
        event_id = str(event_ref.get("event_id") or "").strip()
        if not rel_path or not event_id:
            return None
        roots = []
        if self._base_dir is not None:
            roots = [self._base_dir]
        else:
            hinted_scope = normalize_data_scope(
                event_ref.get("storage_scope"), default="aveline"
            )
            scope_roots = [
                root for root in get_all_chat_history_dirs() if root.name == "chat_history"
            ]
            preferred = []
            fallback = []
            for root in scope_roots:
                expected_parent = f"{hinted_scope}_data"
                if root.parent.name.lower() == expected_parent.lower():
                    preferred.append(root)
                else:
                    fallback.append(root)
            roots = preferred + fallback

        for root in roots:
            index = self._synced_index(root)
            if index is None:
                continue
            try:
                content = index.get_content(event_id)
            except Exception as exc:
                _log_index_fallback(root, f"get_event_content: {exc}")
                continue
            if content is not None:
                return content

        # 索引未覆盖（旧数据/索引不可用）时回退顺序读文件
        for root in roots:
            file_path = (root / rel_path).resolve()
            try:
                if not str(file_path).startswith(str(root)):
                    continue
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            item = json.loads(line)
                        except Exception:
                            continue
                        if str(item.get("event_id") or "") == event_id:
                            return str(item.get("content") or "")
            except Exception:
                continue
        return None

    def _list_recent_events_from_index(
        self,
        base_dir: Path,
        *,
        limit: int,
        roles: Optional[list[str]],
        predicate: Optional[Callable[[Dict[str, Any]], bool]],
    ) -> Optional[list[Dict[str, Any]]]:
        """索引版 recent-N：单条 SQL 取最近事件，predicate 在 Python 侧过滤。

        语义与文件扫描版一致：全 root 范围 → 时间升序 → 取尾部 limit 条。
        索引不可用时返回 None，由调用方回退按日期倒序的文件扫描。
        """
        index = self._synced_index(base_dir)
        if index is None:
            return None
        normalized_roles = sorted(
            {str(item).strip().lower() for item in (roles or []) if str(item).strip()}
        )
        try:
            # 无 predicate 时按 limit 取即可；有 predicate 会滤掉一部分，多取几倍减少翻页
            if limit and int(limit) > 0:
                page = int(limit) if predicate is None else max(int(limit) * 4, 200)
            else:
                page = 0
            accepted: list[Dict[str, Any]] = []  # 时间倒序（新 → 旧）
            offset = 0
            while True:
                rows = index.query(roles=normalized_roles or None, limit=page, offset=offset)
                if not rows:
                    break
                for item in reversed(rows):
                    if predicate is not None and not predicate(item):
                        continue
                    accepted.append(item)
                    if limit and int(limit) > 0 and len(accepted) >= int(limit):
                        break
                if not page or (limit and int(limit) > 0 and len(accepted) >= int(limit)):
                    break
                if len(rows) < page:
                    break
                offset += page
            if limit and int(limit) > 0:
                accepted = accepted[: int(limit)]
            accepted.reverse()
            return accepted
        except Exception as exc:
            _log_index_fallback(base_dir, f"list_recent_events: {exc}")
            return None

    def _list_conversation_events_from_index(
        self,
        *,
        safe_cid: str,
        candidate_roots: list[Path],
        limit: int,
        before: Optional[float],
        query_tokens: list[str],
        normalized_roles: set[str],
    ) -> Optional[list[Dict[str, Any]]]:
        """索引版会话查询：按文件名 stem 精确命中，语义对齐 rglob(f"{cid}.jsonl")。"""
        items: list[Dict[str, Any]] = []
        usable = False
        for root in candidate_roots:
            index = self._synced_index(root)
            if index is None:
                continue
            usable = True
            try:
                items.extend(
                    index.query(
                        file_stems=[safe_cid],
                        roles=sorted(normalized_roles) or None,
                        before=before,
                        query_tokens=query_tokens or None,
                        limit=0,
                    )
                )
            except Exception as exc:
                _log_index_fallback(root, f"list_conversation_events: {exc}")
                return None
        if not usable:
            return None

        deduped: Dict[str, Dict[str, Any]] = {}
        for item in sorted(items, key=lambda entry: float(entry.get("timestamp") or 0.0)):
            event_id = str(item.get("event_id") or "").strip()
            if event_id:
                deduped[event_id] = item
        result = list(deduped.values())
        if limit > 0 and len(result) > int(limit):
            return result[-int(limit) :]
        return result

    def list_recent_events(
        self,
        *,
        limit: int = 120,
        roles: Optional[list[str]] = None,
        predicate: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> list[Dict[str, Any]]:
        """从指定 history 根目录按日期倒序读取最近事件，够数后停止向旧日期扫描。"""
        base_dir = self._base_dir
        if base_dir is None or not base_dir.exists():
            return []

        indexed = self._list_recent_events_from_index(
            base_dir, limit=limit, roles=roles, predicate=predicate
        )
        if indexed is not None:
            return indexed

        normalized_roles = {
            str(item).strip().lower() for item in (roles or []) if str(item).strip()
        }
        events: Dict[str, Dict[str, Any]] = {}
        for day_dir in self._iter_day_dirs_desc(base_dir):
            for file_path in sorted(day_dir.rglob("*.jsonl")):
                try:
                    with open(file_path, "r", encoding="utf-8") as handle:
                        for line in handle:
                            raw = line.strip()
                            if not raw:
                                continue
                            try:
                                payload = json.loads(raw)
                            except Exception:
                                continue
                            if not isinstance(payload, dict):
                                continue
                            role = str(payload.get("role") or "system").strip().lower()
                            if normalized_roles and role not in normalized_roles:
                                continue
                            if predicate is not None and not predicate(payload):
                                continue
                            event_id = str(payload.get("event_id") or "").strip()
                            if event_id:
                                key = event_id
                            else:
                                key = "legacy:" + json.dumps(
                                    payload, sort_keys=True, ensure_ascii=False
                                )
                            events[key] = payload
                except Exception:
                    continue

            # 同一天可能散落在多个会话文件；先完整读取当天，再决定是否停止。
            if limit > 0 and len(events) >= int(limit):
                break

        result = sorted(
            events.values(), key=lambda entry: float(entry.get("timestamp") or 0.0)
        )
        if limit > 0 and len(result) > int(limit):
            result = result[-int(limit) :]
        return result

    def list_conversation_events(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        before: Optional[float] = None,
        query: Optional[str] = None,
        roles: Optional[list[str]] = None,
    ) -> list[Dict[str, Any]]:
        safe_cid = _sanitize_segment(conversation_id)
        primary_root = self._get_base_dir(conversation_id)
        candidate_roots = [primary_root]

        label_info = get_conversation_label_info(conversation_id)
        label_scope = normalize_data_scope(
            label_info.get("storage_scope"), default="aveline"
        )
        storage_scope = resolve_data_scope_from_conversation_id(
            conversation_id, default=label_scope
        )
        has_explicit_scope = bool(storage_scope)

        if has_explicit_scope:
            found_in_primary = False
            if primary_root.exists():
                for _ in primary_root.rglob(f"{safe_cid}.jsonl"):
                    found_in_primary = True
                    break
            if found_in_primary:
                candidate_roots = [primary_root]
            else:
                for root in get_all_chat_history_dirs():
                    if root not in candidate_roots:
                        candidate_roots.append(root)
        else:
            for root in get_all_chat_history_dirs():
                if root not in candidate_roots:
                    candidate_roots.append(root)

        normalized_query = str(query or "").strip().lower()
        # jieba 分词后 OR 匹配：中文近义表述（初中女生↔初二女生）也能召回
        query_tokens = _tokenize_query(normalized_query) if normalized_query else []
        normalized_roles = {
            str(item).strip().lower() for item in (roles or []) if str(item).strip()
        }

        indexed = self._list_conversation_events_from_index(
            safe_cid=safe_cid,
            candidate_roots=candidate_roots,
            limit=limit,
            before=before,
            query_tokens=query_tokens,
            normalized_roles=normalized_roles,
        )
        if indexed is not None:
            return indexed

        items: list[Dict[str, Any]] = []
        can_stop_early = (
            len(candidate_roots) == 1
            and limit > 0
            and before is None
            and not query_tokens
        )

        for base_dir in candidate_roots:
            if not base_dir.exists():
                continue
            if can_stop_early:
                day_dirs = self._iter_day_dirs_desc(base_dir)
                for day_dir in day_dirs:
                    for file_path in sorted(day_dir.rglob(f"{safe_cid}.jsonl")):
                        self._collect_file_events(
                            file_path,
                            items,
                            normalized_roles=normalized_roles,
                            before=before,
                            query_tokens=query_tokens,
                        )
                    if len(items) >= int(limit):
                        break
            else:
                for file_path in sorted(base_dir.rglob(f"{safe_cid}.jsonl")):
                    self._collect_file_events(
                        file_path,
                        items,
                        normalized_roles=normalized_roles,
                        before=before,
                        query_tokens=query_tokens,
                    )

        deduped: Dict[str, Dict[str, Any]] = {}
        for item in sorted(
            items, key=lambda entry: float(entry.get("timestamp") or 0.0)
        ):
            event_id = str(item.get("event_id") or "").strip()
            if event_id:
                deduped[event_id] = item
        result = list(deduped.values())
        if limit > 0 and len(result) > int(limit):
            return result[-int(limit) :]
        return result

    @staticmethod
    def _collect_file_events(
        file_path: Path,
        items: list[Dict[str, Any]],
        *,
        normalized_roles: set[str],
        before: Optional[float],
        query_tokens: list[str],
    ) -> None:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        continue
                    role = str(payload.get("role") or "system").strip().lower()
                    if normalized_roles and role not in normalized_roles:
                        continue
                    timestamp = float(payload.get("timestamp") or 0.0)
                    if before is not None and timestamp >= float(before):
                        continue
                    content = str(payload.get("content") or "")
                    if query_tokens:
                        lowered_content = content.lower()
                        if not any(token in lowered_content for token in query_tokens):
                            continue
                    items.append(payload)
        except Exception:
            return


def get_chat_history_store() -> ChatHistoryStore:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ChatHistoryStore()
    return _INSTANCE