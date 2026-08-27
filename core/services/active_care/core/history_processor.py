"""Active Care 历史消息处理器

负责从原始历史消息中解析、提取、清洗所需信息（纯解析，无副作用）。
从 executor.py 拆分而来，方法签名与原 _xxx 方法保持一致。
"""
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from config.debug_config import is_debug_enabled
from core.utils.logger import get_module_logger
from core.services.active_care.shared.constants import format_message_age_human
from core.utils.timestamp_utils import safe_timestamp

logger = get_module_logger("ACTIVE_CARE_EXECUTOR", "active_care_schedule.log")


class HistoryProcessor:
    """历史消息纯解析器

    所有方法均无副作用，仅依赖传入参数。可独立单元测试。
    """

    @staticmethod
    def strip_emojis_from_text(text: str) -> str:
        """剥离文本中的所有emoji字符，保留中文和其他正常文字"""
        raw = str(text or "").strip()
        if not raw:
            return raw
        # 匹配所有emoji范围（不包含中文字符）
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # 表情符号
            "\U0001F300-\U0001F5FF"  # 符号和象形文字
            "\U0001F680-\U0001F6FF"  # 交通和地图符号
            "\U0001F1E0-\U0001F1FF"  # 旗帜
            "\U00002702-\U000027B0"  # 杂项符号
            "\U0001f926-\U0001f937"  # 补充符号
            "\U00010000-\U0010ffff"  # 补充平面
            "\u200d"                 # 零宽连接符
            "\u2640-\u2642"          # 性别符号
            "\u2600-\u2B55"          # 杂项符号
            "\u23cf"                 # 推出符号
            "\u23e9"                 # 快进符号
            "\u231a"                 # 手表
            "\ufe0f"                 # 变体选择符
            "\u3030"                 # 波浪破折号
            "]+",
            flags=re.UNICODE,
        )
        cleaned = emoji_pattern.sub("", raw)
        # 清理多余的空格
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def build_recent_history_text(
        self, history_msgs: List[Dict[str, Any]], now_ts: Optional[float] = None
    ) -> Tuple[str, str]:
        """构建最近历史记录文本"""
        if not history_msgs:
            return "", ""
        now_anchor = float(now_ts or time.time())
        lines = ["\n【最近聊天记录】(注意：标注'主程序回复'的是聊天主程序说的话，你作为Active Care不要重复这些内容)"]
        last_user_message = ""
        trimmed = history_msgs[-8:]
        for m in trimmed:
            role = str(m.get("role") or "").strip().lower()
            if role not in ("user", "assistant"):
                continue
            content = str(m.get("content") or "").strip()
            if not content:
                continue
            # 剥离历史记录中的emoji
            content = self.strip_emojis_from_text(content)
            if len(content) > 180:
                content = content[:180] + "..."
            role_text = "User" if role == "user" else "Assistant"
            # 兜底：标记 peer_chat 剧本消息，避免 LLM 误以为是用户对话
            is_peer = bool(
                m.get("is_peer_script")
                or m.get("category") == "peer_chat"
                or (isinstance(m.get("metadata"), dict) and m["metadata"].get("is_peer_script"))
            )
            if is_peer:
                role_text = "AI间私聊(非用户对话)" if role == "assistant" else "AI间私聊"
            # 标记主动消息，让 Active Care LLM 知道这是自己之前主动发起的
            is_proactive = bool(
                m.get("is_proactive")
                or (isinstance(m.get("metadata"), dict) and m["metadata"].get("is_proactive"))
            )
            if not is_peer and role == "assistant":
                if is_proactive:
                    role_text = "Assistant(你之前主动发起)"
                else:
                    # 主程序（chat agent）的回复，明确标注，让 LLM 知道不要重复
                    role_text = "Assistant(主程序回复,不要重复)"
            age_text = format_message_age_human(m.get("timestamp"), now_anchor)
            lines.append(f"- {role_text}{age_text}: {content}")
            if role == "user":
                last_user_message = str(m.get("content") or "").strip()
        if len(lines) == 1:
            return "", last_user_message
        return "\n".join(lines) + "\n", last_user_message

    def extract_last_assistant_messages(
        self, history_msgs: List[Dict[str, Any]], recent_limit: int = 5
    ) -> Tuple[str, str, List[str]]:
        """提取最后的助手消息

        返回:
            last_assistant_message: 最后一条助手消息
            last_proactive_assistant_message: 最后一条主动助手消息
            recent_assistant_messages: 最近 recent_limit 条助手消息（含普通对话），
                用于去重锚点，解决多条历史话题合并导致单条相似度被稀释的问题
        """
        last_assistant_message = ""
        last_proactive_assistant_message = ""
        recent_assistant_messages: List[str] = []
        for item in reversed(history_msgs or []):
            role = str(item.get("role") or "").strip().lower()
            if role != "assistant":
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            if not last_assistant_message:
                last_assistant_message = content
            # 收集最近多条助手消息（去重用）
            if len(recent_assistant_messages) < recent_limit:
                recent_assistant_messages.append(content)
            metadata = item.get("metadata") or {}
            msg_type = str(item.get("type") or "").strip().lower()
            is_proactive = bool(
                item.get("is_proactive")
                or (isinstance(metadata, dict) and metadata.get("is_proactive"))
                or (
                    isinstance(metadata, dict)
                    and str(metadata.get("type") or "").strip().lower() == "proactive"
                )
                or msg_type == "proactive"
            )
            if is_proactive and not last_proactive_assistant_message:
                last_proactive_assistant_message = content
            if last_assistant_message and last_proactive_assistant_message and len(recent_assistant_messages) >= recent_limit:
                break
        # recent_assistant_messages 是倒序的（最新在前），保持这个顺序
        return last_assistant_message, last_proactive_assistant_message, recent_assistant_messages

    def resolve_last_user_timestamp(
        self, history_msgs: List[Dict[str, Any]], cached_ts: Any,
    ) -> float:
        """解析最后用户时间戳"""
        last_user_ts = 0.0
        for item in reversed(history_msgs or []):
            if str(item.get("role") or "").strip().lower() != "user":
                continue
            try:
                last_user_ts = safe_timestamp(item.get("timestamp"))
            except Exception:
                if is_debug_enabled("active_care_executor"):
                    logger.info("解析用户消息时间戳失败", exc_info=True)
                last_user_ts = 0.0
            if last_user_ts > 0:
                break
        if last_user_ts <= 0:
            try:
                last_user_ts = safe_timestamp(cached_ts)
            except Exception:
                if is_debug_enabled("active_care_executor"):
                    logger.info("解析缓存时间戳失败", exc_info=True)
                last_user_ts = 0.0
        return float(last_user_ts or 0.0)

    def resolve_last_assistant_timestamp(
        self, history_msgs: List[Dict[str, Any]],
    ) -> float:
        """解析最后助手消息时间戳"""
        for item in reversed(history_msgs or []):
            if str(item.get("role") or "").strip().lower() != "assistant":
                continue
            try:
                ts = safe_timestamp(item.get("timestamp"))
            except Exception:
                if is_debug_enabled("active_care_executor"):
                    logger.info("解析助手消息时间戳失败", exc_info=True)
                ts = 0.0
            if ts > 0:
                return float(ts)
        return 0.0
