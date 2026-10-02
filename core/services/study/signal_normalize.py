"""层 2 normalize：它实际说的是哪一段（结构性改写，不做语义判断）。

从 ``signal_detector.py`` 拆出。允许的 transform 见 ``ALLOWED_TRANSFORMS``，
硬边界见原模块 docstring。
"""
from __future__ import annotations

import re
from typing import List, Tuple

from core.services.study.signal_patterns import (
    _CLAUSE_BOUNDARY_RE,
    _COGNITIVE_TAIL_RE,
    _DISCOURSE_MARKERS,
    _FILLER_ONLY,
    _LEADING_PUNCT_RE,
    _MAX_CONCEPT_LEN,
    _REFERENTIAL_MARKERS,
    _STRIP_PREFIXES,
    _STRIP_SUFFIXES,
    _WEAK_FILLER_WORDS,
)
from core.services.study.signal_types import NormalizedCandidate, RawCandidate


# ----------------------------------------------------------------------
# normalize：允许的 transforms（枚举即边界声明）
# ----------------------------------------------------------------------

ALLOWED_TRANSFORMS = (
    "strip_prefix",       # 去掉开头的语气/指示前缀（一下/这个/那个/的/啊/呢/嘛）
    "strip_suffix",       # 去掉结尾的语气/指代尾巴（那个/啊喂/呢）
    "truncate_clause",    # 在从句边界截断，保留首个完整语义段
    "strip_quote_marks",  # 去掉包裹引号
    "collapse_space",     # 合并空白
    "normalize_formula",  # 规范公式/化学式的书写形式
)

# normalize **明确禁止**做的事（不做语义判断）：
#   补全原文没有的实体（如把「它」还原成具体名词）
#   把指代升级为具体知识点
#   按「是否像学习内容」做取舍
#   改写同义词或做语义归并


# ----------------------------------------------------------------------
# 层 2：normalize —— 它实际说的是哪一段（结构性改写）
# ----------------------------------------------------------------------

def normalize_candidate(raw: RawCandidate) -> NormalizedCandidate:
    """把 raw 片段规范成「它实际说的那一段」。

    **硬边界**：只做结构性改写（去包裹/去语气残留/截从句/规范形式），
    **不做任何语义判断**——不补实体、不升级指代、不按「像不像学习内容」取舍。
    """
    transforms: List[str] = []
    name = str(raw.name or "")

    # 1) 去包裹引号
    stripped = name.strip().strip("「」『』“”\"'《》()（）[]【】")
    if stripped != name:
        transforms.append("strip_quote_marks")
        name = stripped

    # 2) 公式优先：公式只做格式规范化，不走中文前缀/后缀剥离
    if raw.source in ("formula", "chemistry_formula"):
        normalized = _normalize_formula(name)
        if normalized != name:
            transforms.append("normalize_formula")
            name = normalized
    else:
        # 3) 截从句：拼接从句只保留首个完整语义段
        truncated = _truncate_clause(name)
        if truncated != name:
            transforms.append("truncate_clause")
            name = truncated

        # 4) 去开头语气/指示前缀（取**最长**命中，并按标点循环）
        #    ``at_message_start``：只有片段确实位于消息开头时，转折标记
        #    （``不过`` / ``其实``）才算「它自己的一句话」，才剥得掉。
        stripped_head, prefix_hits = _apply_strip_prefix(
            name, at_message_start=raw.start == 0
        )
        if prefix_hits:
            transforms.extend(prefix_hits)
            name = stripped_head

        # 5) 去结尾语气/指代尾巴
        for suffix in _STRIP_SUFFIXES:
            if name.endswith(suffix) and len(name) > len(suffix) + 1:
                transforms.append("strip_suffix")
                name = name[: -len(suffix)]
                break

    # 6) 合并空白
    collapsed = " ".join(name.split())
    if collapsed != name:
        transforms.append("collapse_space")
        name = collapsed

    name = name[:_MAX_CONCEPT_LEN].strip()
    # 短到没有承载能力的片段按「无候选」处理，而不是拒（拒是 filter 的事）
    if len(name) < 2 or not re.search(r"[0-9A-Za-z\u4e00-\u9fff]", name):
        name = ""

    return NormalizedCandidate(
        name=name,
        derived_from=raw.id,
        raw_name=str(raw.name or ""),
        transforms=list(dict.fromkeys(transforms)),
        source=raw.source,
        raw_strength=raw.strength,
        normalized_strength=_normalized_strength(name, raw),
    )


def _apply_strip_prefix(name: str, *, at_message_start: bool = False) -> Tuple[str, List[str]]:
    """剥掉开头的语气/指示前缀，返回 ``(新名, 命中的 transform 列表)``。

    **只做结构性剥离**，不判断语义。矩阵 v3 逐例验证的规则：

    1. **至多剥一个实词前缀**（``_STRIP_PREFIXES`` / 句首的 ``_DISCOURSE_MARKERS``）。
       连剥两个会破坏语义单位：``不过那个时候的学生`` 若剥掉 ``不过`` 再剥 ``那``，
       就只剩 ``时候的学生``——``那个时候`` 是**一个指示短语**，
       拆开会把「那一段内容」拆坏（矩阵 R-07 要求结果恰为 ``那个时候的学生``）。
       ``那奶头和胸`` 只剥 ``那``（矩阵 R-11），同理。
    2. **转折标记只在句首剥**（``at_message_start``）：
       ``不过那个时候的学生`` 位于消息开头 → 剥掉 ``不过``；
       ``不过你头发`` 位于逗号之后 → 保留（矩阵 R-05 vs R-07 的分界）。
    3. **标点/省略号残留**可以继续清（它不是词）：
       ``这样吗…不过你头发`` 先命中 ``这样吗``，剩下 ``…不过你头发``
       以省略号开头，清掉省略号后得 ``不过你头发``（矩阵 R-05 的 normalize 链）。

    这些都不算「语义理解」——语气词、指示词与标点本来就不是
    「它实际说的那一段」的组成部分。
    """
    head = name
    hits: List[str] = []

    # 先清开头的标点/省略号残留（语气残留，不是词）
    cleaned = _LEADING_PUNCT_RE.sub("", head)
    if cleaned != head and len(cleaned) >= 2:
        head = cleaned
        hits.append("strip_prefix")

    # 至多剥**一个**实词前缀
    pool = list(_STRIP_PREFIXES)
    if at_message_start:
        pool = pool + list(_DISCOURSE_MARKERS)
    matched = max(
        (p for p in pool if head.startswith(p) and len(head) > len(p) + 1),
        key=len,
        default=None,
    )
    if matched is not None:
        remainder = head[len(matched):]
        # **不从已知语气词中间切开**：``诶对哦`` 是**一整块**语气词，
        # 剥掉 ``诶`` 得 ``对哦`` 并不产生信息增益，反而抹掉了
        # 「它本来就是一整句语气」这个事实。矩阵 R-06 明确要求
        # ``诶对哦`` 原样进入 filter，由 ``no_stable_entity`` 判定拒绝
        # （那是 filter 的职责，不是 normalize 的）。
        #
        # 反例（必须能剥）：``哼哼猜猜看`` 不在 ``_FILLER_ONLY`` 里——
        # 它是「语气前缀 ``哼哼`` + 填充词 ``猜猜看``」两段拼接，
        # 剥掉前缀后才露出真正要让 filter 判定的那个词（矩阵 R-10）。
        if head not in _FILLER_ONLY:
            head = remainder
            hits.append("strip_prefix")

    return head, list(dict.fromkeys(hits))


def _truncate_clause(name: str) -> str:
    """在从句边界截断，保留首个完整语义段。

    **只在确有必要时截断**：若整段本身就是完整语义（``不过那个时候的学生``），
    截断会破坏它。触发条件只有一个——段内**含有附带认知状态**
    （``我不知道国外`` / ``可能吧``），此时前段才是真正的话题。

    只处理结构性拼接，不做语义取舍。
    """
    if not _COGNITIVE_TAIL_RE.search(name):
        # 没有认知尾巴，不截断；交由 strip_prefix / strip_suffix 做纯外壳剥离
        return name
    head = _COGNITIVE_TAIL_RE.split(name, maxsplit=1)[0]
    return head.strip()


def _normalize_formula(name: str) -> str:
    """规范公式书写：去多余空格，统一比较/等号两侧。"""
    text = str(name or "").strip()
    text = re.sub(r"\s*([=≈∝+\-*/^])\s*", r"\1", text)
    return text


def _normalized_strength(name: str, raw: RawCandidate) -> str:
    """**normalized** strength：filter 前的重新评估。

    注意与 ``raw_strength`` 分开保存——**不覆盖**原值，
    否则事后就不知道 detector 最初有多离谱。
    """
    if not name:
        return "weak"
    if raw.source in ("quoted", "formula", "chemistry_formula", "registry", "explicit_tool"):
        return raw.strength
    # **弱填充词**（猜猜看 / 哼哼）：有语义、仍不承载知识点 → weak。
    # 矩阵 R-10 要求它的拒因是 ``weak_source``（不是 ``no_stable_entity``）——
    # 「有语义但没知识」与「连语义都没有」是两条不同的拒因。
    if name in _WEAK_FILLER_WORDS:
        return "weak"
    # 片段以标点/省略号收尾、或含未清理的从句残留：说明它**没被规范干净**，
    # 不足以支撑准入（矩阵 R-05「紫色的…」）。
    if re.search(r"[，。！？,.!?;；…\s]$", name) or _CLAUSE_BOUNDARY_RE.search(name):
        return "weak"
    # 相关指代/语气残留：同样不构成稳定实体
    if any(marker in name for marker in _REFERENTIAL_MARKERS):
        return "weak"
    # explicit_topic：能被抽成完整片段的给 medium，其余保持 weak
    return "medium" if len(name) >= 4 else "weak"
