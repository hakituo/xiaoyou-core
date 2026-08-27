import hashlib
import json
import logging
import os
import time
from typing import Any

from memory.core.readable_ops import remove_readable_history_files
from memory.core.lock_utils import get_write_lock
from memory.core.storage import is_short_term_dialogue


logger = logging.getLogger(__name__)


def _backfill_short_term_from_chat_history(manager: Any) -> None:
    """程序启动时，从 ChatHistoryStore 回填短期记忆中缺失的对话

    解决程序重启后短期记忆丢失最近的对话的问题（自动保存间隔300秒）。
    修剪逻辑已优化为按马尔科夫性质保留最近对话，此处只需补充重启丢失的部分。
    """
    import uuid as _uuid

    try:
        from core.services.chat_history_store import get_chat_history_store

        store = get_chat_history_store()
        conversation_id = str(manager.user_id or "").strip() or "default"

        events = store.list_conversation_events(
            conversation_id,
            limit=120,
            roles=["user", "assistant"],
        )

        if not events:
            return

        existing_ts_set = set()
        for m in manager.short_term_memory:
            ts = float(m.get("timestamp", 0) or 0)
            if ts > 0:
                existing_ts_set.add(int(ts))

        backfill_count = 0
        for event in events:
            if not isinstance(event, dict):
                continue

            event_ts = float(event.get("timestamp", 0) or 0)
            if event_ts <= 0:
                continue
            if int(event_ts) in existing_ts_set:
                continue

            role = str(event.get("role") or "").strip().lower()
            if role not in ("user", "assistant"):
                continue

            content = str(event.get("content") or "").strip()
            if not content:
                continue

            event_type = str(event.get("event_type") or "").strip().lower()
            if event_type == "chat_thought":
                continue

            metadata = event.get("metadata") or {}
            if isinstance(metadata, dict) and metadata.get("hidden"):
                continue

            source = role
            category = "daily" if role == "assistant" else "uncategorized"

            record = {
                "id": str(_uuid.uuid4()),
                "content": content,
                "timestamp": event_ts,
                "created_at": event.get("created_at", ""),
                "last_access_time": event_ts,
                "weight": 2.0,
                "topics": [],
                "emotions": ["neutral"],
                "emotion": "neutral",
                "is_important": False,
                "source": source,
                "role": role,
                "category": category,
                "summary": None,
                "search_keywords": [],
                "display_tags": ["对话"],
                "keywords": [],
                "is_distilled": False,
                "metadata": {
                    "message_id": event.get("message_id", ""),
                    "model_hint": (metadata if isinstance(metadata, dict) else {}).get("model_hint", ""),
                    "timestamp": event_ts,
                    "trace_id": str(_uuid.uuid4()),
                    "backfilled": True,
                },
                "scopes": ["local", "cloud"],
                "status": "active",
                "memory_type": "dialogue",
            }

            manager.short_term_memory.append(record)
            existing_ts_set.add(int(event_ts))
            backfill_count += 1

        if backfill_count > 0:
            manager.short_term_memory.sort(key=lambda x: x.get("timestamp", 0))
            logger.info(
                "短期记忆回填：从 ChatHistoryStore 补充了 %d 条消息（短期记忆原有 %d 条）",
                backfill_count,
                len(manager.short_term_memory) - backfill_count,
            )
    except Exception as e:
        logger.warning(f"短期记忆回填失败: {e}")


def safe_save_all(manager: Any) -> None:
    try:
        short_file = str(manager.short_term_dir / f"{manager.user_id}_short.json")
        sensitive_file = str(manager.sensitive_dir / f"{manager.user_id}_sensitive.json")

        if manager.short_term_memory:
            short_disk_records = manager._build_short_term_disk_records(manager.short_term_memory)
            manager._safe_json_dump(short_disk_records, short_file)
        else:
            try:
                os.remove(short_file)
            except FileNotFoundError:
                pass

        try:
            os.remove(sensitive_file)
        except FileNotFoundError:
            pass

        manager._save_weighted_data_locked()
        manager._save_important_prompts_locked()
        if bool(getattr(manager, "enable_readable_history_mirror", False)):
            manager._write_readable_history_mirror()
        else:
            remove_readable_history_files(manager)
        manager.last_save_time = time.time()
    except Exception as e:
        logger.error(f"安全保存所有数据失败: {e}")
        raise


def migrate_legacy_data(manager: Any, *, encoding: str) -> None:
    migrated_count = 0
    need_save = False
    with get_write_lock(manager):
        long_file = manager.long_term_dir / f"{manager.user_id}_long.json"
        if not long_file.exists():
            long_file = manager.legacy_long_term_dir / f"{manager.user_id}_long.json"
        if not long_file.exists():
            return

        try:
            with open(long_file, "r", encoding=encoding) as f:
                legacy_long_term = json.load(f)
        except Exception:
            legacy_long_term = []

        if not legacy_long_term:
            return

        logger.info("开始迁移旧长期记忆数据...")

        for item in legacy_long_term:
            mem_id = item.get("id")
            if not mem_id:
                content = item.get("content", "")
                role = item.get("role", "")
                timestamp = item.get("timestamp", 0)
                raw_id = f"{role}:{content}:{timestamp}"
                mem_id = hashlib.md5(raw_id.encode("utf-8")).hexdigest()
                item["id"] = mem_id

            if mem_id in manager.weighted_memories:
                continue

            if "weight" not in item:
                item["weight"] = 1.0

            if "category" not in item:
                topics = item.get("topics", [])
                item["category"] = topics[0] if topics else "uncategorized"

            if "timestamp" not in item:
                item["timestamp"] = time.time()

            manager.weighted_memories[mem_id] = item
            cat = item.get("category", "uncategorized")
            manager.category_index[cat].append(mem_id)
            migrated_count += 1

        if migrated_count > 0:
            logger.info(f"已迁移 {migrated_count} 条旧长期记忆到权重系统")
            need_save = True

        try:
            if long_file.exists():
                backup_file = manager.long_term_dir / f"{manager.user_id}_long.json.bak"
                if backup_file.exists():
                    backup_file.unlink()
                long_file.rename(backup_file)
                logger.info(f"旧长期记忆文件已重命名为: {backup_file}")
        except Exception as e:
            logger.error(f"重命名旧长期记忆文件失败: {e}")

    if need_save:
        manager._save_weighted_data_locked()


def load_memory(manager: Any, *, encoding: str) -> None:
    try:
        with get_write_lock(manager):
            short_file = str(manager.short_term_dir / f"{manager.user_id}_short.json")
            old_short_file = str(manager.legacy_history_dir / f"{manager.user_id}_short.json")

            if os.path.exists(short_file):
                try:
                    with open(short_file, "r", encoding=encoding) as f:
                        loaded_short = json.load(f)
                    if isinstance(loaded_short, list):
                        manager.short_term_memory = manager._hydrate_short_term_records(loaded_short)
                    else:
                        manager.short_term_memory = []
                except Exception:
                    manager.short_term_memory = []
            elif os.path.exists(old_short_file):
                try:
                    with open(old_short_file, "r", encoding=encoding) as f:
                        loaded_short = json.load(f)
                    if isinstance(loaded_short, list):
                        manager.short_term_memory = manager._hydrate_short_term_records(loaded_short)
                    else:
                        manager.short_term_memory = []
                    logger.info(f"从旧位置迁移短期记忆: {old_short_file}")
                except Exception:
                    manager.short_term_memory = []
            else:
                manager.short_term_memory = []

            loaded_count = len(manager.short_term_memory)
            manager.short_term_memory = [
                record
                for record in manager.short_term_memory
                if is_short_term_dialogue(record)
            ]
            filtered_count = loaded_count - len(manager.short_term_memory)
            if filtered_count:
                logger.info(
                    "加载时清理短期记忆: 移除 %d 条非对话记录, 保留 %d 条",
                    filtered_count,
                    len(manager.short_term_memory),
                )

            manager.sensitive_memories = []
            sensitive_file = str(manager.sensitive_dir / f"{manager.user_id}_sensitive.json")
            if not os.path.exists(sensitive_file):
                sensitive_file = str(manager.legacy_sensitive_dir / f"{manager.user_id}_sensitive.json")
            if os.path.exists(sensitive_file):
                try:
                    with open(sensitive_file, "r", encoding=encoding) as f:
                        legacy_sensitive = json.load(f)
                    if isinstance(legacy_sensitive, list):
                        for item in legacy_sensitive:
                            if not isinstance(item, dict):
                                continue
                            mem_id = str(item.get("id") or "").strip()
                            if not mem_id:
                                continue
                            item["category"] = "sensitive"
                            item["scopes"] = ["local"]
                            if mem_id not in manager.weighted_memories:
                                manager.weighted_memories[mem_id] = item
                                manager.category_index["sensitive"].append(mem_id)
                except Exception:
                    pass

            _backfill_short_term_from_chat_history(manager)

            # 加载/backfill 后立即裁剪,防止文件膨胀累积
            # (之前 load 不 trim + backfill 追加 + trim 延迟 30s 可能没执行,
            #  导致多次启动后 short_term 文件从 60 条膨胀到几千条)
            try:
                removed = manager._trim_short_term_memory()
                if isinstance(removed, list) and removed:
                    logger.info(
                        f"加载时裁剪短期记忆: 移除 {len(removed)} 条, "
                        f"保留 {len(manager.short_term_memory)} 条"
                    )
            except Exception as trim_err:
                logger.warning(f"加载时裁剪短期记忆失败(忽略): {trim_err}")

            manager._update_topic_index()
    except Exception:
        pass


def clear_memory(manager: Any, mode: str = "all") -> None:
    with get_write_lock(manager):
        if mode == "short" or mode == "short_term":
            manager.short_term_memory = []
            short_file = str(manager.short_term_dir / f"{manager.user_id}_short.json")
            try:
                os.remove(short_file)
            except FileNotFoundError:
                pass

            logger.info(f"已清除用户 {manager.user_id} 的短期记忆")

            try:
                conversation_file = manager._get_output_conversation_file()
                if conversation_file.exists() and conversation_file.is_file():
                    conversation_file.unlink()
            except Exception:
                pass
            try:
                readable_short = manager._get_readable_history_dir() / "short_term.json"
                if readable_short.exists():
                    readable_short.unlink()
            except Exception:
                pass
            return

        if mode != "all":
            return

        manager.short_term_memory = []
        manager.weighted_memories = {}
        manager.important_prompts = []
        manager.sensitive_memories = []
        manager.topic_weights.clear()
        manager.emotion_memory_map.clear()
        manager._keyword_index.clear()
        manager._cache["l1"].clear()
        manager._cache["l2"].clear()
        manager._cache["access_count"] = {}

        try:
            short_file = str(manager.short_term_dir / f"{manager.user_id}_short.json")
            try:
                os.remove(short_file)
            except FileNotFoundError:
                pass

            weighted_file = manager.weighted_memory_dir / f"{manager.user_id}_weighted.json"
            try:
                os.remove(str(weighted_file))
            except FileNotFoundError:
                pass

            if manager.weighted_memory_dir.exists():
                for item in manager.weighted_memory_dir.iterdir():
                    if item.is_dir() and item.name not in ["short_term", "long_term"]:
                        cat_file = item / f"{manager.user_id}_weighted.json"
                        if cat_file.exists():
                            try:
                                os.remove(cat_file)
                                if not any(item.iterdir()):
                                    item.rmdir()
                            except Exception:
                                pass

            prompts_file = manager._get_important_prompts_file()
            try:
                os.remove(prompts_file)
            except FileNotFoundError:
                pass

            legacy_prompts_file = manager.weighted_memory_dir / "important_prompts.json"
            if manager.user_id == "default" and legacy_prompts_file.exists():
                try:
                    os.remove(legacy_prompts_file)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"清除所有记忆文件失败: {e}")

        try:
            remove_readable_history_files(manager)
        except Exception:
            pass

        logger.info(f"已清除用户 {manager.user_id} 的所有记忆")

        try:
            conversation_file = manager._get_output_conversation_file()
            if conversation_file.exists() and conversation_file.is_file():
                conversation_file.unlink()
        except Exception:
            pass


def shutdown_manager(manager: Any) -> None:
    try:
        manager._stop_event.set()

        if (
            hasattr(manager, "auto_save_thread")
            and getattr(manager.auto_save_thread, "is_alive", lambda: False)()
        ):
            try:
                manager.auto_save_thread.join(timeout=2.0)
            except Exception:
                pass

        if (
            hasattr(manager, "_save_thread")
            and manager._save_thread
            and manager._save_thread.is_alive()
        ):
            try:
                manager._save_event.set()
                manager._save_thread.join(timeout=3.0)
            except Exception:
                pass

        if manager._trim_timer:
            manager._trim_timer.cancel()

        manager.sync_save_memory()
    except Exception:
        pass
