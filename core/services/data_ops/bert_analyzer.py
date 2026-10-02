
from core.utils.logger import get_logger
import re
import threading
import time
import numpy as np
from typing import List, Dict, Any, Optional

from .bert_definitions import (
    COMMON_TOPICS,
    INTENT_RULE_OVERRIDES,
)
from .bert_proactive_mixin import BertProactiveMixin
from .bert_runtime_mixin import BertRuntimeMixin
from memory.core.discourse import analyze_discourse, infer_state_event

logger = get_logger("DataOps.BertAnalyzer")

_SINGLETON_LOCK = threading.RLock()


class BertAnalyzer(BertRuntimeMixin, BertProactiveMixin):
    _instance = None
    _model = None
    _tokenizer = None
    _category_embeddings = None
    _intent_embeddings = None
    _topic_embeddings = None
    _importance_embeddings = None
    _discourse_embeddings = None
    _state_event_embeddings = None

    _np = np

    def __new__(cls):
        if cls._instance is None:
            with _SINGLETON_LOCK:
                if cls._instance is None:
                    cls._instance = super(BertAnalyzer, cls).__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _rule_intent_override(
        self, content: str, candidates: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        text = str(content or "").strip()
        if not text:
            return None
        cand_upper = {
            str(c).strip().upper() for c in (candidates or []) if str(c).strip()
        }

        def _allowed(intent: str) -> bool:
            return not cand_upper or intent in cand_upper

        for intent, pattern in INTENT_RULE_OVERRIDES:
            if not _allowed(intent):
                continue
            if re.search(pattern, text):
                return {
                    "intent": intent,
                    "confidence": 0.90,
                    "reason": "rule_signal",
                    "slots": {},
                }
        return None

    def _fuse_rule_and_bert(
        self,
        rule_signal: Optional[Dict[str, Any]],
        bert_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        if rule_signal is None:
            return bert_result

        rule_intent = str(rule_signal.get("intent") or "NONE").upper()
        rule_conf = float(rule_signal.get("confidence") or 0.0)
        bert_intent = str(bert_result.get("intent") or "NONE").upper()
        bert_conf = float(bert_result.get("confidence") or 0.0)

        if rule_intent == "NONE":
            return bert_result

        if bert_intent == rule_intent:
            fused_conf = min(rule_conf * 0.5 + bert_conf * 0.5, 1.0)
            return {
                "intent": rule_intent,
                "confidence": fused_conf,
                "reason": "fusion_rule_bert_agree",
                "slots": rule_signal.get("slots") or bert_result.get("slots") or {},
            }

        if bert_intent != "NONE" and bert_conf > 0.6:
            return bert_result

        if bert_intent == "NONE" and bert_conf < 0.5:
            return {
                "intent": "NONE",
                "confidence": 0.0,
                "reason": "fusion_rule_vetoed_by_bert",
                "slots": {},
            }

        return {
            "intent": rule_intent,
            "confidence": rule_conf * 0.5,
            "reason": "fusion_rule_weak_bert_disagree",
            "slots": rule_signal.get("slots") or {},
        }


    def analyze_intent(self, content: str, candidates: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Analyze intent using Zero-shot BERT embeddings.
        """
        if not self._session:
            return {"intent": "NONE", "confidence": 0.0, "reason": "bert_not_ready"}

        t0 = time.time()
        content = content.strip()
        if not content:
            return {"intent": "NONE", "confidence": 0.0, "reason": "empty_content"}

        rule_signal = self._rule_intent_override(content, candidates)

        if not self._intent_embeddings:
            return {"intent": "NONE", "confidence": 0.0, "reason": "intent_prototypes_not_ready"}

        # 1. 获取内容嵌入
        content_emb = self._get_text_embedding(content)
        if content_emb is None:
            return {"intent": "NONE", "confidence": 0.0, "reason": "embedding_failed"}

        norm = np.linalg.norm(content_emb)
        if norm > 0:
            content_emb = content_emb / norm

        # 2. 匹配意图原型
        best_intent = "NONE"
        best_score = -1.0

        # 如果提供了候选意图，只检查这些（加上NONE）
        target_intents = list(self._intent_embeddings.keys())
        if candidates:
            cands_upper = {c.upper() for c in candidates}
            cands_upper.add("NONE")  # 始终将NONE作为回退选项
            target_intents = [i for i in target_intents if i in cands_upper]

        for intent in target_intents:
            # 优先使用单独样本（最大相似度），如果可用
            # 这对"NONE"等多样化类别更鲁棒
            examples = getattr(self, "_intent_example_embeddings", {}).get(intent)
            if examples:
                scores = [np.dot(content_emb, ex_emb) for ex_emb in examples]
                score = max(scores) if scores else -1.0
            else:
                # 回退到质心匹配
                proto_emb = self._intent_embeddings.get(intent)
                if proto_emb is None:
                    continue
                score = np.dot(content_emb, proto_emb)

            if score > best_score:
                best_score = score
                best_intent = intent

        # 阈值处理
        # 意图检测需要高置信度
        # [Fix] 提高零样本分类阈值，减少中文语义模糊导致的误判（原值0.65过低）
        threshold = 0.70
        if best_score < threshold:
            best_intent = "NONE"
            # 低于阈值时降低置信度
            confidence = max(0.0, float(best_score))
        else:
            confidence = min(1.0, float(best_score))

        latency = (time.time() - t0) * 1000.0
        bert_result = {
            "intent": best_intent,
            "confidence": confidence,
            "reason": f"bert_zero_shot (latency={latency:.1f}ms)",
            "slots": {}
        }
        return self._fuse_rule_and_bert(rule_signal, bert_result)

    def analyze(self, content: str) -> Dict[str, Any]:
        """
        Analyze content to extract category, topics, and weight.

        Returns:
            Dict containing:
            - category: str
            - topics: List[str]
            - confidence: float
            - weight_delta: float
            - reason: str
        """
        if not self._session:
            return {
                "category": "uncategorized",
                "topics": [],
                "confidence": 0.0,
                "weight_delta": 0.0,
                "reason": "bert_model_not_loaded"
            }

        t0 = time.time()
        content = content.strip()
        if not content:
            return {
                "category": "uncategorized",
                "topics": [],
                "confidence": 0.0,
                "weight_delta": 0.0,
                "reason": "empty_content"
            }

        # 1. 获取内容嵌入
        content_emb = self._get_text_embedding(content)
        if content_emb is None:
            return {
                "category": "uncategorized",
                "topics": [],
                "confidence": 0.0,
                "weight_delta": 0.0,
                "reason": "embedding_failed"
            }

        # 归一化内容嵌入
        norm = np.linalg.norm(content_emb)
        if norm > 0:
            content_emb = content_emb / norm

        # 2. 分类类别（零样本）
        best_category = "uncategorized"
        best_score = -1.0

        for category, proto_emb in self._category_embeddings.items():
            score = np.dot(content_emb, proto_emb)
            if score > best_score:
                best_score = score
                best_category = category

        # 分类阈值
        if best_score < 0.3:  # 按需调整阈值
            best_category = "uncategorized"

        # 3. 提取话题（语义原型 + 关键词回退）
        detected_topics: List[str] = []
        if best_category != "uncategorized":
            detected_topics.append(best_category)

        # 语义话题相似度（优先）
        if isinstance(self._topic_embeddings, dict) and self._topic_embeddings:
            scored: List[tuple[str, float]] = []
            for topic, proto_emb in self._topic_embeddings.items():
                if proto_emb is None:
                    continue
                score = float(np.dot(content_emb, proto_emb))
                scored.append((str(topic), score))
            scored.sort(key=lambda x: x[1], reverse=True)
            for topic, score in scored[:8]:
                if score >= 0.35 and topic not in detected_topics:
                    detected_topics.append(topic)

        # 关键词回退（快速，对精确匹配鲁棒）
        lowered = content.lower()
        for topic in COMMON_TOPICS:
            t = str(topic).strip()
            if not t:
                continue
            if t.lower() in lowered and t not in detected_topics:
                detected_topics.append(t)

        detected_topics = detected_topics[:5]

        # 3.5 话语和状态事件预测
        rule_discourse = analyze_discourse(content)
        discourse_label, discourse_confidence = self._classify_with_generic_head(
            text=content,
            fallback_embeddings=getattr(self, "_discourse_embeddings", None),
            content_emb=content_emb,
            fallback_default=str(rule_discourse.get("discourse_label") or "GENERIC_CHAT"),
            min_confidence=0.40,
        )
        discourse = dict(rule_discourse)
        discourse["discourse_label"] = discourse_label
        discourse["model_confidence"] = discourse_confidence

        rule_state_event = infer_state_event(content, discourse)
        state_event, state_event_confidence = self._classify_with_generic_head(
            text=content,
            fallback_embeddings=getattr(self, "_state_event_embeddings", None),
            content_emb=content_emb,
            fallback_default=rule_state_event,
            min_confidence=0.40,
        )
        if discourse.get("trigger_blocked") or discourse.get("contains_negation"):
            state_event = "NONE"
        discourse_label = str(discourse.get("discourse_label") or "GENERIC_CHAT")

        # 4. 计算权重（语义保留导向评分）
        weight_delta = 0.0

        # 保持类别先验较弱，使类别不再主导保留决策。
        if best_category in ["learning", "work", "finance", "tech"]:
            weight_delta += 0.2
        elif best_category in ["entertainment", "daily"]:
            weight_delta -= 0.05

        # 额外的语义重要性评分（原型相似度）
        # 这有助于在同一类别内区分"截止日期/紧急"与闲聊。
        if isinstance(self._importance_embeddings, dict) and self._importance_embeddings:
            emb_imp = self._importance_embeddings.get("IMPORTANT")
            emb_cas = self._importance_embeddings.get("CASUAL")
            if emb_imp is not None and emb_cas is not None:
                s_imp = float(np.dot(content_emb, emb_imp))
                s_cas = float(np.dot(content_emb, emb_cas))
                # 映射到大约 [-1, 1]
                importance = max(-1.0, min(1.0, (s_imp - s_cas)))
                weight_delta += 0.35 * importance

        # 话语感知的保留调整。
        discourse_label = str(discourse.get("discourse_label") or "GENERIC_CHAT")
        if discourse_label in {"INSTRUCTION", "QUESTION", "REPORTED_SPEECH"}:
            weight_delta -= 0.2
        elif discourse_label in {"HYPOTHETICAL", "FUTURE_PLAN"}:
            weight_delta -= 0.12
        elif discourse_label == "RETROSPECTIVE_SELF_REPORT":
            weight_delta -= 0.05
        elif discourse_label == "CURRENT_SELF_REPORT":
            weight_delta += 0.05

        # 置信度源自分类评分
        confidence = max(0.0, min(1.0, float(best_score)))
        trigger_allowed = bool(
            state_event != "NONE"
            and not discourse.get("trigger_blocked")
            and not discourse.get("contains_negation")
        )

        latency = (time.time() - t0) * 1000.0

        return {
            "category": best_category,
            "topics": detected_topics,
            "confidence": confidence,
            "weight_delta": weight_delta,
            "discourse_label": discourse_label,
            "discourse": discourse,
            "state_event": state_event,
            "discourse_confidence": discourse_confidence,
            "state_event_confidence": state_event_confidence,
            "trigger_allowed": trigger_allowed,
            "reason": f"bert_zero_shot (latency={latency:.1f}ms)",
            "source": "bert_local"
        }



def get_bert_analyzer():
    with _SINGLETON_LOCK:
        if BertAnalyzer._instance is None:
            BertAnalyzer._instance = BertAnalyzer()
    return BertAnalyzer._instance
