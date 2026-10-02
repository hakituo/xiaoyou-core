"""学科识别：认出消息在聊哪个学科，并透出来源与置信度。

从 ``signal_detector.py`` 拆出。filter 与消息层都靠它拿「有没有学习语境」。
"""
from __future__ import annotations

from typing import Optional, Tuple

from core.services.study.mode_detector import classify_subject
from core.services.study.signal_patterns import (
    _BIOLOGY_WORDS,
    _CHEM_FORMULA_RE,
    _FORMULA_RE,
    _MATH_SYMBOLS,
    _MATH_WORDS,
    _PHYSICS_WORDS,
    _SUBJECT_WORD_CONFIDENCE,
)


# ----------------------------------------------------------------------
# 兼容层：保留原先的单一入口
# ----------------------------------------------------------------------

def detect_subject(message: str) -> Optional[str]:
    """识别学科。返回 canonical subject id（小写），认不出返回 None。"""
    subject, _source, _confidence = detect_subject_with_source(message)
    return subject


def detect_subject_with_source(
    message: str,
) -> Tuple[Optional[str], Optional[str], float]:
    """识别学科并返回来源与置信度。

    修复点：原先 ``classify_subject`` 的单字关键字（如 physics 的「光」）
    会把任意含该字的句子判成物理，且**没有置信度**可供上层取舍。
    这里给 keyword 命中加**双字下限**，并把来源与置信度透出。
    """
    text = str(message or "")
    if not text.strip():
        return None, None, 0.0

    # 1) Registry：最高可信来源
    try:
        from core.services.study.subject_registry import get_subject_registry

        match = get_subject_registry().match_text(text)
        if match is not None:
            return match.subject_id.lower(), "registry", float(match.confidence)
    except Exception:  # noqa: BLE001 - registry 缺失时走关键字兜底
        pass

    # 2) 内容术语兜底，**分两档**（对齐 registry 的长/短 alias 校准）：
    #    * 概念档（``光合作用`` / ``胡克定律``）：课程标准概念 → 0.9，可拿 accept；
    #    * 话题档（``柬埔寨国王`` / ``财产局``）：领域专名 → 0.75，
    #      只够 candidate_only（矩阵 R-08 / R-09）。
    concept_hint = _match_content_hint(text, tier="concept")
    if concept_hint:
        return concept_hint, "content_hint", 0.9
    topic_hint = _match_content_hint(text, tier="topic")
    if topic_hint:
        return topic_hint, "content_hint", 0.75

    # 3) 关键字兜底：**拒绝单字命中**，避免「这里有光」被判成物理
    detected = classify_subject(text)
    if detected:
        return detected.lower(), "keyword", _keyword_confidence(detected.lower(), text)

    lowered = text.lower()
    if any(w in text for w in _MATH_SYMBOLS) or any(w in lowered for w in _MATH_WORDS):
        return "math", "keyword", _SUBJECT_WORD_CONFIDENCE["math"]
    if any(w in text for w in _PHYSICS_WORDS):
        return "physics", "keyword", _SUBJECT_WORD_CONFIDENCE["physics"]
    if _CHEM_FORMULA_RE.search(text):
        return "chemistry", "formula", 0.9
    if any(w in lowered for w in _BIOLOGY_WORDS):
        return "biology", "keyword", _SUBJECT_WORD_CONFIDENCE["biology"]
    if _FORMULA_RE.search(text):
        # **公式是强领域证据**（矩阵 R-16 reason 明确）：``F=-kx`` 这种
        # 「字母 = 表达式」的形状在自然语言里几乎只出现在理科学习中，
        # 所以它给 0.9，足以拿到 ``accept``。注意这与下面
        # ``chemistry`` 的 0.3 不同——后者只是「撞到学科名」。
        return "physics", "formula", 0.9
    return None, None, 0.0


def _match_content_hint(text: str, *, tier: str = "concept") -> Optional[str]:
    """命中 ``_DOMAIN_CONCEPT_HINTS`` / ``_DOMAIN_TOPIC_HINTS`` 时返回学科 id。

    ``tier="concept"``：课程标准概念名（``光合作用`` / ``胡克定律``），
    本身就是知识实体 → 上层给 0.9。
    ``tier="topic"``：领域话题专名（``柬埔寨国王`` / ``财产局``），
    只说明「在聊这个领域」→ 上层给 0.75。

    **冲突时返回 None**：若同一句同时命中多个学科的内容词
    （如「柬埔寨的季风」同时指向 history / geography），不硬选一个，
    交给下层走 ``_looks_like_knowledge_query`` 的 open_domain 路径。
    """
    from core.services.study.mode_detector import (
        _DOMAIN_CONCEPT_HINTS,
        _DOMAIN_HINTS,
        _DOMAIN_TOPIC_HINTS,
    )

    # **话题档必须让位给更具体的提示表**：``_DOMAIN_HINTS`` 里
    # 装着歧义更低的专有词（``希腊文`` / ``拉丁文`` → linguistics）。
    # 若不加这条，``希腊文和拉丁文`` 会先被话题档的 ``希腊`` 抢走判成 history——
    # 那是**用更粗的词覆盖了更准的词**，属于典型的下位/上位倒挂。
    if tier == "topic" and any(
        hint in text.lower() for _subject, hints in _DOMAIN_HINTS for hint in hints
    ):
        return None

    table = _DOMAIN_CONCEPT_HINTS if tier == "concept" else _DOMAIN_TOPIC_HINTS
    lowered = str(text or "").lower()
    hits = [
        subject
        for subject, hints in table
        if any(hint in lowered for hint in hints)
    ]
    if len(hits) == 1:
        return hits[0]
    return None


def _keyword_confidence(subject: str, text: str) -> float:
    """``SUBJECT_KEYWORDS`` 通用关键字命中的置信度，**与 registry 校准一致**。

    内容术语（``_DOMAIN_CONTENT_HINTS``）不走这里——它们在
    ``detect_subject_with_source`` 里更早命中并直接给 0.9 / ``content_hint``。

    分级：
      * 关键字命中且长度 >= 3 → 0.9（矩阵 R-15「光合作用」的兜底档）
      * 关键字命中但只有 2 字 → 0.75（短 alias 只够 candidate_only）
      * 只剩单字命中（如「光」「力」）→ 0.3，**不足以宣告学科**
    """
    from core.services.study.mode_detector import MIN_KEYWORD_LEN, SUBJECT_KEYWORDS

    lowered = text.lower()
    best = 0.0
    for keyword in SUBJECT_KEYWORDS.get(subject, ()):
        if keyword in lowered and len(keyword) >= MIN_KEYWORD_LEN:
            best = max(best, 0.9 if len(keyword) >= 3 else 0.75)
    # 只剩单字命中（如「光」「力」）：不足以宣告学科
    return best if best > 0.0 else 0.3
