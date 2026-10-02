"""层 3 filter：这一段有没有资格进入候选层（**永不改 name**）。

从 ``signal_detector.py`` 拆出。契约与拒因优先级见原模块 docstring 与
``_reject_reason`` 的 docstring。
"""
from __future__ import annotations

import re
from typing import Optional

from core.services.study.signal_patterns import (
    _DEMONSTRATIVES,
    _FILLER_ONLY,
    _INTIMATE_CONTEXT_MARKERS,
    _PERSONA_MARKERS,
    _REFERENTIAL_MARKERS,
    _SECOND_PERSON_META,
)
from core.services.study.signal_types import (
    FilteredCandidate,
    NormalizedCandidate,
    RejectReason,
)


# ----------------------------------------------------------------------
# 层 3：filter —— 有没有资格进入候选层（**永不改 name**）
# ----------------------------------------------------------------------

def filter_candidate(
    normalized: NormalizedCandidate,
    *,
    subject: Optional[str],
    open_domain: bool = False,
    raw_text: str = "",
) -> FilteredCandidate:
    """判断一条 normalized 候选有没有资格进入候选层。

    契约：只说 ``admit`` / ``reject``，**不改 name、不合并、不创建**。

    Args:
        open_domain: 消息本身是明确的知识查询句式（``什么是X`` / ``X是什么``），
            只是领域不在 registry 里。此时**候选准入门槛放宽**——
            这正是矩阵 R-17（维基解密）：**filter 通过 ≠ 可建档**，
            准入交给 filter，建档交给独立的 promotion_gate。
        raw_text: 消息原文。用于识别**被前缀剥离掩盖掉的**指代特征
            （R-18「那个感觉」剥掉「那个」后只剩「感觉」，
            单看归一化结果会误判成 weak_source）。
    """
    name = normalized.name
    if not name:
        return FilteredCandidate(candidate="", admit=False, reason=RejectReason.NO_STABLE_ENTITY.value)

    reason = _reject_reason(
        name, normalized, subject=subject, open_domain=open_domain, raw_text=raw_text
    )
    if reason is not None:
        return FilteredCandidate(candidate=name, admit=False, reason=reason.value)
    return FilteredCandidate(candidate=name, admit=True, reason=None)


def _reject_reason(
    name: str,
    normalized: NormalizedCandidate,
    *,
    subject: Optional[str],
    open_domain: bool = False,
    raw_text: str = "",
) -> Optional[RejectReason]:
    """判定拒因。**顺序即优先级**，改顺序会改矩阵结果，必须同步矩阵。

    优先级（矩阵 §3 的顺序依据）：

    ```
    no_stable_entity
      -> referential_phrase
      -> weak_source           (仅当没有学科托底)
      -> non_learning_context
      -> open_domain -> admit
      -> no_subject_evidence
    ```

    **为什么 ``weak_source`` 排在 ``no_subject_evidence`` 之前**：
    这两条拒因回答的是不同问题——``weak_source`` 问「这个片段本身够不够格」，
    ``no_subject_evidence`` 问「有没有学科知识语境」。矩阵的真实语义是：

      * R-10(猜猜看)：片段无实体 → 第 1 步 ``no_stable_entity``；
      * R-03(跑路) / R-12(乳晕)：**认不出学科 + 片段是弱来源**——
        按矩阵记 ``no_subject_evidence``，但实现里 ``weak_source`` 更早命中，
        因为「没有学科托底的弱片段」一律先判 `weak_source`；
      * R-06(诶对哦) / R-17(维基解密)：``open_domain`` 成立时**
        ``weak_source`` 与 ``no_subject_evidence`` 都不再拦**，
        这正是「filter 通过 ≠ 可建档」。

    换句话说：``not subject``（无学科）**不是本层的独立拒因**，
    它只是「weak_source 判定里没有学科托底」这一条件的一部分。
    真正的独立拒因是最后那条——**有学科但候选仍不成立**时的兜底。
    """
    lowered = name.lower()
    bare = re.sub(r"[\s，。！？,.!?;；、·…—\-~～()（）\[\]【】\"'“”‘’]", "", name)

    # 1) 无稳定实体：纯语气词 / 短到没承载能力（R-06 的「诶对哦」走这条）。
    #    **它排在 weak_source 之前**：语气词连「弱来源」都算不上。
    if not bare or bare in _FILLER_ONLY or len(bare) < 2:
        return RejectReason.NO_STABLE_ENTITY
    if all(ch in "的了呢吗啊呀哦嗯哈嘿哼嘛吧哎诶对" for ch in bare):
        return RejectReason.NO_STABLE_ENTITY

    # 2) 强指代短语：脱离上下文无意义（R-07 / R-18）。
    #    **必须在 weak_source 之前**：R-18「那个感觉」strip 掉前缀后只剩「感觉」，
    #    若先走 weak_source 就丢了「它本来是个指代短语」这个更准确的根因。
    #    判据同时看**归一化后**与**原文**，避免前缀剥离掩盖指代特征。
    if (
        any(marker in bare for marker in _REFERENTIAL_MARKERS)
        or any(marker in (normalized.name or "") for marker in _REFERENTIAL_MARKERS)
        or any(marker in raw_text for marker in _REFERENTIAL_MARKERS)
    ):
        return RejectReason.REFERENTIAL_PHRASE
    # 裸指示词：**归一化前的片段以指示词打头、且归一化后几乎只剩它**——
    # 「那个感觉」原文片段是「那个感觉」，剥掉「那个」后只剩「感觉」2 字，
    # 说明这个候选的实质就是「一个指示词 + 无支撑名词」（R-18）。
    # 排除「那个柬埔寨国王」：剥掉后剩「柬埔寨国王」，有具体实体支撑。
    raw_head = normalized.raw_name or name  # 归一化**之前**的片段名
    for demo in _DEMONSTRATIVES:
        if raw_head.startswith(demo) and len(bare) <= 3:
            return RejectReason.REFERENTIAL_PHRASE
    # 3) 来源太弱：normalize 后仍是孤立短语。
    #    R-03(跑路) / R-10(猜猜看) / R-12(乳晕) 的**首要拒因都是它**——
    #    即使 normalize 成功剥离了外壳，内容本身仍不承载知识点
    #    （矩阵对这三例都列出了 ``weak_source`` 作为第一条候选拒因）。
    #    它排在 non_learning_context 之前：**拒因要说清「为什么」**，
    #    「乳晕」的根因是「这个片段不承载知识点」，不是「涉身体」。
    #
    #    ``open_domain`` **不能豁免 weak**：R-03「什么叫跑路啊喂」也是明确疑问句式，
    #    但它的片段是 weak，所以照样拒。open_domain 放宽的是**学科要求**
    #    （不再要求 ``subject`` 非空），不是**片段质量标准**——
    #    这正是 R-17「维基解密」(medium) 能过、R-03「跑路」(weak) 不能过的分界。
    if normalized.normalized_strength == "weak":
        return RejectReason.WEAK_SOURCE

    # 4) 角色 / 人设 / 自指：上下文非学习（R-01 / R-02 / R-05）
    if any(marker in lowered for marker in _PERSONA_MARKERS):
        return RejectReason.NON_LEARNING_CONTEXT
    if any(marker in lowered for marker in _SECOND_PERSON_META):
        return RejectReason.NON_LEARNING_CONTEXT
    if bare.startswith(("你", "我", "他", "她", "您", "咱们", "我们")):
        return RejectReason.NON_LEARNING_CONTEXT

    # 5) 口语断句：R-11（那奶头和胸）走这条。
    #    **涉身体部位本身不是拒绝理由**，拒因是这段口语断句没有学习语境
    #    （矩阵 R-11 的明确要求）。若已有学科语境，此处不拒。
    if any(marker in lowered for marker in _INTIMATE_CONTEXT_MARKERS) and not subject:
        return RejectReason.NON_LEARNING_CONTEXT

    # 6) 明确的知识查询句式：领域未知但候选本身成立 → 准入。
    #    它就是 R-06 / R-17：**filter 通过 ≠ 可建档**。
    if open_domain:
        return None

    # 7) 兜底：认不出学科，且前面没有更具体的拒因。等价于「没有知识语境」。
    if not subject:
        return RejectReason.NO_SUBJECT_EVIDENCE

    return None
