"""
QQ适配器 - 表情/情绪管理
管理表情注入、情绪选择、emo标签提取

合并自 emotion.py + face_processor.py
"""

import hashlib
import re
import logging

from clients.bots.qq.utils import resolve_emotion_face_label, _normalize_qq_face_position

logger = logging.getLogger(__name__)


class EmotionManager:
    """表情/情绪管理器"""

    def __init__(self):
        self._session_emotions: dict[str, dict] = {}

    def update_emotion(self, session_id: str, emotion_data: dict) -> None:
        """更新会话情绪数据"""
        self._session_emotions[session_id] = emotion_data

    def select_face_label_from_emotion(self, session_id: str) -> str:
        """根据情绪数据选择表情标签"""
        data = self._session_emotions.get(session_id)
        if not isinstance(data, dict) or not data:
            return ""
        best_key = ""
        best_weight = -1.0
        for k, v in data.items():
            try:
                w = float(v)
            except Exception:
                continue
            if w > best_weight:
                best_key = str(k or "").strip().lower()
                best_weight = w
        if best_weight < 0.25:
            return ""
        return resolve_emotion_face_label(best_key)

    def augment_face_label(self, session_id: str, content: str) -> str:
        """为内容添加表情标签（概率性）"""
        text = str(content or "").strip()
        if not text:
            return text
        if "[CQ:" in text:
            return text
        if re.search(r"\[[^\]]{1,12}\]", text):
            return text
        if len(text) > 260:
            return text
        label = self.select_face_label_from_emotion(session_id)
        if not label:
            return text
        gate_seed = hashlib.sha1(f"{session_id}|{text}".encode("utf-8")).hexdigest()
        if (int(gate_seed[-2:], 16) % 100) >= 42:
            return text
        return f"{text} [{label}]"

    @staticmethod
    def extract_emo_label(content: str) -> tuple[str, str]:
        """从内容中提取 emo 标签，返回 (清理后内容, 情绪标签)"""
        text = str(content or "")
        hits = re.findall(r"\[\s*emo\s*:\s*([\s\S]*?)\]", text, flags=re.IGNORECASE)
        if not hits:
            hits = re.findall(r"【\s*emo\s*:\s*([\s\S]*?)】", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"^\s*\[\s*emo\s*:[\s\S]*?\]\s*", "", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"\[\s*emo\s*:[\s\S]*?\]", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^\s*【\s*emo\s*:[^】]*】\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"【\s*emo\s*:[^】]*】", "", cleaned, flags=re.IGNORECASE)
        raw = str(hits[0] if hits else "").strip().lower()
        keyed = re.search(
            r"(?:mood|emotion|primary_emotion)\s*[:=]\s*['\"]?([a-zA-Z0-9_\u4e00-\u9fa5]+)",
            raw,
            flags=re.IGNORECASE,
        )
        if keyed:
            raw = str(keyed.group(1) or "").strip().lower()
        return cleaned, resolve_emotion_face_label(raw)


class FaceProcessor:
    """消息表情处理器，为文本内容添加表情标签。"""

    def __init__(self, emotion_manager: EmotionManager, face_injector):
        self.emotion_manager = emotion_manager
        self.face_injector = face_injector

    def build_processor(self, session_id: str, emo_label: str):
        """构建用于 transport.send_message 的 face_processor 回调"""

        def face_processor(c: str) -> str:
            if "[CQ:record" not in c and "[CQ:image" not in c:
                if emo_label and "[" not in c and "]" not in c:
                    c = f"{c} [{emo_label}]"
                c = self.emotion_manager.augment_face_label(session_id, c)
                c = self.face_injector.apply(c, scope=session_id)
                c = _normalize_qq_face_position(c)
            return c

        return face_processor
