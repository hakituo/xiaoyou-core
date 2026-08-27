import re
from typing import Any, Dict

from .bert_definitions import (
    PORTRAIT_TOPIC_DEFINITIONS,
    SILENCE_DETECTION_THRESHOLDS,
    TIME_EXPECTATION_PATTERNS,
    TOPIC_INCOMPLETE_SIGNALS,
    TOPIC_INTERRUPT_FOLLOW_UP_SECONDS,
    URGENCY_DEFINITIONS,
    USER_INCOMPLETE_PATTERNS,
)


class BertProactiveMixin:
    _urgency_embeddings_cache: Dict[str, Any] = None
    _portrait_topic_embeddings_cache: Dict[str, Any] = None

    def _get_urgency_embeddings(self) -> Dict[str, Any]:
        if self._urgency_embeddings_cache is None:
            self._urgency_embeddings_cache = self._compute_embeddings_for_dict(URGENCY_DEFINITIONS)
        return self._urgency_embeddings_cache

    def _get_portrait_topic_embeddings(self) -> Dict[str, Any]:
        if self._portrait_topic_embeddings_cache is None:
            cache = {}
            for topic, definitions in PORTRAIT_TOPIC_DEFINITIONS.items():
                embs = []
                for def_text in definitions:
                    emb = self._get_text_embedding(def_text.lower())
                    if emb is not None:
                        norm = self._np.linalg.norm(emb)
                        if norm > 0:
                            emb = emb / norm
                        embs.append(emb)
                if embs:
                    cache[topic] = embs
            self._portrait_topic_embeddings_cache = cache
        return self._portrait_topic_embeddings_cache
    def analyze_urgency(self, content: str) -> Dict[str, Any]:
        if not self._session:
            return {"urgency": "NONE", "confidence": 0.0, "keywords": [], "reason": "bert_not_ready"}

        content_lower = str(content or "").strip().lower()
        if not content_lower:
            return {"urgency": "NONE", "confidence": 0.0, "keywords": [], "reason": "empty_content"}

        content_emb = self._get_text_embedding(content_lower)
        if content_emb is None:
            return {"urgency": "NONE", "confidence": 0.0, "keywords": [], "reason": "embedding_failed"}

        norm = self._np.linalg.norm(content_emb)
        if norm > 0:
            content_emb = content_emb / norm

        urgency_embeddings = self._get_urgency_embeddings()

        best_urgency = "NONE"
        best_score = -1.0
        matched_keywords = []

        for urgency_level, proto_emb in urgency_embeddings.items():
            if proto_emb is None:
                continue
            score = float(self._np.dot(content_emb, proto_emb))
            if score > best_score:
                best_score = score
                best_urgency = urgency_level

        for urgency_level, keywords in URGENCY_DEFINITIONS.items():
            for kw in keywords:
                if kw in content_lower:
                    matched_keywords.append(kw)
                    if best_urgency == "NONE":
                        best_urgency = urgency_level

        confidence = max(0.0, min(1.0, float(best_score)))

        if best_score < 0.35 and not matched_keywords:
            best_urgency = "NONE"
            confidence = 0.0

        return {
            "urgency": best_urgency,
            "confidence": confidence,
            "keywords": matched_keywords,
            "reason": "bert_zero_shot",
        }

    def extract_time_expectation(self, content: str) -> Dict[str, Any]:
        content_str = str(content or "").strip()
        if not content_str:
            return {
                "has_time_expectation": False,
                "expected_seconds": 0,
                "time_type": "none",
                "original_text": "",
                "action_hint": "",
            }

        chinese_num_map = {
            "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
            "两": 2, "几": 3,
        }

        for pattern, time_type in TIME_EXPECTATION_PATTERNS:
            match = re.search(pattern, content_str)
            if not match:
                continue
            original_text = match.group(0)
            expected_seconds = 0
            action_hint = ""

            if time_type == "minutes":
                expected_seconds = int(match.group(1)) * 60
            elif time_type == "seconds":
                expected_seconds = int(match.group(1))
            elif time_type == "hours":
                expected_seconds = int(match.group(1)) * 3600
            elif time_type == "relative_minutes":
                num = 3
                for cn, cn_num in chinese_num_map.items():
                    if cn in match.group(0):
                        num = cn_num
                        break
                expected_seconds = num * 60
            elif time_type == "short_while":
                expected_seconds = 180
            elif time_type == "immediate":
                expected_seconds = 30
            elif time_type == "very_short":
                expected_seconds = 60
            elif time_type == "after_action":
                if "洗漱" in original_text:
                    expected_seconds = 240
                    action_hint = "洗漱"
                elif "吃" in original_text:
                    expected_seconds = 600
                    action_hint = "吃饭"
                elif "忙" in original_text:
                    expected_seconds = 900
                    action_hint = "忙碌"
                elif "做" in original_text:
                    expected_seconds = 600
                    action_hint = "做事"
                elif "回来" in original_text:
                    expected_seconds = 1200
                    action_hint = "外出"
                else:
                    expected_seconds = 300
                    action_hint = "等待"

            return {
                "has_time_expectation": True,
                "expected_seconds": max(30, expected_seconds),
                "time_type": time_type,
                "original_text": original_text,
                "action_hint": action_hint,
            }

        return {
            "has_time_expectation": False,
            "expected_seconds": 0,
            "time_type": "none",
            "original_text": "",
            "action_hint": "",
        }

    def analyze_proactive_context(self, content: str) -> Dict[str, Any]:
        urgency_result = self.analyze_urgency(content)
        time_result = self.extract_time_expectation(content)

        suggested_seconds = 300
        should_follow_up_soon = False

        if time_result.get("has_time_expectation"):
            suggested_seconds = time_result.get("expected_seconds", 300)
            should_follow_up_soon = True
        elif urgency_result.get("urgency") == "HIGH":
            suggested_seconds = 60
            should_follow_up_soon = True
        elif urgency_result.get("urgency") == "MEDIUM":
            suggested_seconds = 180
            should_follow_up_soon = True

        return {
            "urgency": urgency_result,
            "time_expectation": time_result,
            "suggested_follow_up_seconds": suggested_seconds,
            "should_follow_up_soon": should_follow_up_soon,
        }

    def detect_topic_interrupt(self, content: str) -> Dict[str, Any]:
        content_str = str(content or "").strip()
        if not content_str:
            return {
                "has_interrupt": False,
                "interrupt_type": "",
                "matched_keywords": [],
                "suggested_follow_up_seconds": 0,
                "context_hint": "",
            }

        content_lower = content_str.lower()
        for interrupt_type, keywords in TOPIC_INCOMPLETE_SIGNALS.items():
            for kw in keywords:
                if kw not in content_str and kw not in content_lower:
                    continue
                context_hints = {
                    "PENDING_ACTION": "用户说要做某事",
                    "TEMPORARY_LEAVE": "用户说等一下",
                    "INTERRUPTED_STORY": "话题被打断",
                    "QUESTION_UNANSWERED": "问题还没回答",
                    "EMOTION_UNRESOLVED": "情绪还没解决",
                }
                return {
                    "has_interrupt": True,
                    "interrupt_type": interrupt_type,
                    "matched_keywords": [kw],
                    "suggested_follow_up_seconds": TOPIC_INTERRUPT_FOLLOW_UP_SECONDS.get(interrupt_type, 120),
                    "context_hint": context_hints.get(interrupt_type, ""),
                }

        return {
            "has_interrupt": False,
            "interrupt_type": "",
            "matched_keywords": [],
            "suggested_follow_up_seconds": 0,
            "context_hint": "",
        }

    def analyze_proactive_context_enhanced(self, content: str) -> Dict[str, Any]:
        urgency_result = self.analyze_urgency(content)
        time_result = self.extract_time_expectation(content)
        interrupt_result = self.detect_topic_interrupt(content)

        suggested_seconds = 300
        should_follow_up_soon = False
        follow_up_reason = ""

        if time_result.get("has_time_expectation"):
            suggested_seconds = time_result.get("expected_seconds", 300)
            should_follow_up_soon = True
            follow_up_reason = f"时间预期: {time_result.get('time_type')}"
        elif urgency_result.get("urgency") == "HIGH":
            suggested_seconds = 60
            should_follow_up_soon = True
            follow_up_reason = f"紧急程度: {urgency_result.get('urgency')}"
        elif urgency_result.get("urgency") == "MEDIUM":
            suggested_seconds = 180
            should_follow_up_soon = True
            follow_up_reason = f"紧急程度: {urgency_result.get('urgency')}"
        elif interrupt_result.get("has_interrupt"):
            suggested_seconds = interrupt_result.get("suggested_follow_up_seconds", 120)
            should_follow_up_soon = True
            follow_up_reason = f"话题中断: {interrupt_result.get('interrupt_type')}"

        return {
            "urgency": urgency_result,
            "time_expectation": time_result,
            "topic_interrupt": interrupt_result,
            "suggested_follow_up_seconds": suggested_seconds,
            "should_follow_up_soon": should_follow_up_soon,
            "follow_up_reason": follow_up_reason,
        }

    def analyze_conversation_context(self, recent_messages: list, silence_seconds: float) -> Dict[str, Any]:
        if not recent_messages or silence_seconds < 30:
            return {
                "is_conversation_incomplete": False,
                "incomplete_type": "",
                "suggested_follow_up_seconds": 0,
                "context_hint": "",
                "last_ai_message": "",
                "last_user_message": "",
            }

        last_ai_message = ""
        last_user_message = ""
        for msg in reversed(recent_messages):
            role = str(msg.get("role", "")).lower()
            content = str(msg.get("content", "") or "")
            if role == "assistant" and not last_ai_message:
                last_ai_message = content
            elif role == "user" and not last_user_message:
                last_user_message = content
            if last_ai_message and last_user_message:
                break

        incomplete_type = ""
        context_hint = ""
        suggested_seconds = 0
        ai_has_question = self._detect_ai_question(last_ai_message)
        user_incomplete = self._detect_user_incomplete(last_user_message)

        if ai_has_question and silence_seconds >= SILENCE_DETECTION_THRESHOLDS["short"]:
            incomplete_type = "ai_question_unanswered"
            context_hint = "AI 提问后用户沉默"
            suggested_seconds = max(30, int(SILENCE_DETECTION_THRESHOLDS["short"] - silence_seconds + 30))
        elif user_incomplete and silence_seconds >= SILENCE_DETECTION_THRESHOLDS["short"]:
            incomplete_type = "user_story_interrupted"
            context_hint = "用户话题未说完就沉默"
            suggested_seconds = max(30, int(SILENCE_DETECTION_THRESHOLDS["short"] - silence_seconds + 60))
        elif silence_seconds >= SILENCE_DETECTION_THRESHOLDS["medium"] and self._is_active_conversation(recent_messages):
            incomplete_type = "conversation_stalled"
            context_hint = "对话突然停滞"
            suggested_seconds = 60

        return {
            "is_conversation_incomplete": bool(incomplete_type),
            "incomplete_type": incomplete_type,
            "suggested_follow_up_seconds": max(30, suggested_seconds),
            "context_hint": context_hint,
            "last_ai_message": last_ai_message[:100] if last_ai_message else "",
            "last_user_message": last_user_message[:100] if last_user_message else "",
        }

    _AI_QUESTION_WEAK_PATTERNS = {"呢", "吗", "吧", "呀", "嘛"}
    _AI_QUESTION_STRONG_PATTERNS = [
        "？", "?", "你觉得", "你怎么看", "你认为", "你说",
        "怎么样", "如何", "是不是", "对不对",
        "好不好", "行不行", "可以吗", "愿意吗",
        "想不想", "要不要", "有没有", "知不知道",
    ]

    def _detect_ai_question(self, message: str) -> bool:
        if not message:
            return False
        message_str = str(message).strip()
        for pattern in self._AI_QUESTION_STRONG_PATTERNS:
            if pattern in message_str:
                return True
        for pattern in self._AI_QUESTION_WEAK_PATTERNS:
            if pattern in message_str:
                if len(message_str) <= 10:
                    return True
                if message_str.rstrip()[-1:] in ("?", "？"):
                    return True
        return False

    def _detect_user_incomplete(self, message: str) -> bool:
        if not message:
            return False
        message_str = str(message).strip()
        return any(pattern in message_str for pattern in USER_INCOMPLETE_PATTERNS)

    def _is_active_conversation(self, recent_messages: list) -> bool:
        if len(recent_messages) < 2:
            return False
        recent = recent_messages[-min(6, len(recent_messages)) :]
        user_count = sum(1 for m in recent if str(m.get("role", "")).lower() == "user")
        assistant_count = sum(1 for m in recent if str(m.get("role", "")).lower() == "assistant")
        return user_count >= 2 and assistant_count >= 2

    def analyze_portrait_topic_coverage(
        self, recent_messages: list, candidate_topics: list
    ) -> Dict[str, Any]:
        """
        使用BERT语义相似度分析最近聊天记录中已覆盖的画像话题。

        采用逐条消息检测策略：对每条消息单独计算与话题定义的相似度，
        避免多条消息合并导致的信号稀释问题。

        Args:
            recent_messages: 最近的聊天消息列表
            candidate_topics: 候选画像话题列表 (e.g., ["meal", "sleep", "wakeup"])

        Returns:
            Dict containing:
            - covered_topics: 已覆盖的话题列表
            - uncovered_topics: 未覆盖的话题列表
            - details: 每个话题的相似度详情
        """
        if not self._session or not recent_messages or not candidate_topics:
            return {
                "covered_topics": [],
                "uncovered_topics": list(candidate_topics),
                "details": {},
            }

        # 逐条消息提取文本
        msg_texts = [
            str(m.get("content", "")).strip().lower()
            for m in recent_messages
            if m.get("content")
        ]
        msg_texts = [t for t in msg_texts if t]

        if not msg_texts:
            return {
                "covered_topics": [],
                "uncovered_topics": list(candidate_topics),
                "details": {},
            }

        # 逐条消息计算 embedding
        msg_embeddings = []
        for text in msg_texts:
            emb = self._get_text_embedding(text)
            if emb is not None:
                norm = self._np.linalg.norm(emb)
                if norm > 0:
                    emb = emb / norm
                msg_embeddings.append(emb)

        if not msg_embeddings:
            return {
                "covered_topics": [],
                "uncovered_topics": list(candidate_topics),
                "details": {"error": "embedding_failed"},
            }

        covered = []
        uncovered = []
        details = {}

        portrait_cache = self._get_portrait_topic_embeddings()

        for topic in candidate_topics:
            topic_str = str(topic).lower().strip()

            if topic_str not in portrait_cache:
                uncovered.append(topic)
                details[topic] = {"covered": False, "reason": "no_definitions"}
                continue

            topic_embeddings = portrait_cache[topic_str]

            if not topic_embeddings:
                uncovered.append(topic)
                details[topic] = {"covered": False, "reason": "embedding_failed"}
                continue

            # 对每条消息计算与话题定义的最大相似度，取所有消息中的最高值
            SIMILARITY_THRESHOLD = 0.65
            global_max_similarity = 0.0
            best_msg_idx = -1

            for msg_idx, msg_emb in enumerate(msg_embeddings):
                for topic_emb in topic_embeddings:
                    sim = float(self._np.dot(msg_emb, topic_emb))
                    if sim > global_max_similarity:
                        global_max_similarity = sim
                        best_msg_idx = msg_idx

            is_covered = global_max_similarity >= SIMILARITY_THRESHOLD

            details[topic] = {
                "covered": is_covered,
                "similarity": round(global_max_similarity, 3),
                "threshold": SIMILARITY_THRESHOLD,
                "best_msg_index": best_msg_idx,
            }

            if is_covered:
                covered.append(topic)
            else:
                uncovered.append(topic)

        return {
            "covered_topics": covered,
            "uncovered_topics": uncovered,
            "details": details,
        }
