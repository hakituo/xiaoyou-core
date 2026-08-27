"""人物档案提取的增量状态与原始对话读取。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from core.utils.logger import get_logger

logger = get_logger("PeopleProfileExtractor")

_MAX_TURNS_PER_BATCH = 5
_MAX_MESSAGE_LENGTH = 500
_MAX_BATCH_LENGTH = 3000
_TIME_WINDOW_DAYS = 1


class PeopleConversationSource:
    """管理人物提取器水位，并把原始聊天转换为有限大小批次。"""

    @staticmethod
    def get_state_path() -> Path:
        """返回全局人物提取增量状态路径。"""
        from core.utils.data_paths import get_user_people_profiles_dir

        return get_user_people_profiles_dir() / "_extractor_state.json"

    @classmethod
    def load_state(cls) -> Dict[str, Any]:
        """加载增量处理状态。"""
        state_path = cls.get_state_path()
        if not state_path.exists():
            return {"last_processed_timestamp": 0.0}
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return {"last_processed_timestamp": 0.0}

    @classmethod
    def save_state(cls, state: Dict[str, Any]) -> None:
        """保存增量处理状态。"""
        state_path = cls.get_state_path()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("保存提取器状态失败: %s", exc)

    @classmethod
    def load_new_messages(cls, last_processed_ts: float) -> List[Dict[str, Any]]:
        """从 chat_history 获取增量 user/assistant 原始消息。"""
        from core.utils.common import get_project_root

        base_dir = get_project_root() / "companion_data"
        messages: List[Dict[str, Any]] = []
        window_start = (
            datetime.now() - timedelta(days=_TIME_WINDOW_DAYS)
        ).timestamp()

        for role_dir in ("aveline_data", "ling_data"):
            source_role = "aveline" if role_dir == "aveline_data" else "ling"
            chat_dir = base_dir / role_dir / "chat_history"
            if not chat_dir.exists():
                continue
            for jsonl_file in chat_dir.rglob("*.jsonl"):
                cls._load_history_file(
                    jsonl_file,
                    source_role,
                    window_start,
                    last_processed_ts,
                    messages,
                )

        messages.sort(key=lambda item: float(item.get("timestamp", 0) or 0))
        return messages

    @staticmethod
    def _load_history_file(
        jsonl_file: Path,
        source_role: str,
        window_start: float,
        last_processed_ts: float,
        messages: List[Dict[str, Any]],
    ) -> None:
        """读取一个 JSONL 对话文件并追加符合窗口的消息。"""
        try:
            with jsonl_file.open(encoding="utf-8") as file_obj:
                for line in file_obj:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        message = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    role = str(message.get("role") or "").strip().lower()
                    if role not in {"user", "assistant"}:
                        continue
                    timestamp = float(message.get("timestamp", 0) or 0)
                    if timestamp < window_start or timestamp <= last_processed_ts:
                        continue
                    message["_source_role"] = source_role
                    messages.append(message)
        except Exception as exc:
            logger.error("读取 chat_history 失败 %s: %s", jsonl_file, exc)

    @staticmethod
    def group_into_batches(
        messages: List[Dict[str, Any]],
    ) -> List[List[Dict[str, Any]]]:
        """按完整对话轮次分组，并限制轮次与文本长度。"""
        batches: List[List[Dict[str, Any]]] = []
        current_batch: List[Dict[str, Any]] = []
        turn_count = 0
        batch_length = 0
        for original in messages:
            role = str(original.get("role") or "").strip().lower()
            content = str(original.get("content") or "").strip()
            if not content:
                continue
            message = original
            if len(content) > _MAX_MESSAGE_LENGTH:
                content = content[:_MAX_MESSAGE_LENGTH] + "..."
                message = {**original, "content": content}
            current_batch.append(message)
            batch_length += len(content)
            if role == "assistant":
                turn_count += 1
            if (
                turn_count >= _MAX_TURNS_PER_BATCH
                or batch_length >= _MAX_BATCH_LENGTH
            ):
                batches.append(current_batch)
                current_batch = []
                turn_count = 0
                batch_length = 0
        if current_batch:
            batches.append(current_batch)
        return batches

    @staticmethod
    def format_batch(batch: List[Dict[str, Any]]) -> str:
        """格式化外部人物提取批次。"""
        lines: List[str] = []
        for message in batch:
            role = str(message.get("role") or "").strip().lower()
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                prefix = "[用户]"
            elif role in {"assistant", "aveline", "ling"}:
                prefix = "[AI]"
            else:
                prefix = f"[{role}]"
            lines.append(f"{prefix} {content}")
        return "\n".join(lines)

    @staticmethod
    def format_existing_profiles(profiles: List[Any]) -> str:
        """格式化已有档案的名字和别名，供 LLM 去重。"""
        if not profiles:
            return "（无）"
        lines: List[str] = []
        for index, profile in enumerate(profiles, 1):
            aliases = ", ".join(profile.aliases) if profile.aliases else "无"
            role = profile.core_fields.get("role", "未知")
            lines.append(
                f"{index}. 名字: {profile.name}, 别名: [{aliases}], 角色: {role}"
            )
        return "\n".join(lines)
