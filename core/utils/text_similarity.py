"""文本相似度：集合度量的共享实现

背景（2026-09-03）：
    同一个"两个集合有多像"的计算在项目里被写了多遍，分母有时取 max、
    有时取 min、有时取并集，名字却都叫"相似度"或"重叠率"。结果是同一对
    文本在不同环节得到完全不同的数值，阈值之间无法互相参考：

      - ``deduplicator.similarity_score``       → |A∩B| / max(|A|, |B|)
      - ``deduplicator._char_unigram_overlap``  → |A∩B| / min(|A|, |B|)
      - ``topic_diversity._compute_keyword_overlap`` → |A∩B| / min(|A|, |B|)
      - ``style_retriever._calculate_similarity``    → Jaccard |A∩B| / |A∪B|

    其中 ``_char_unigram_overlap`` 与 ``_compute_keyword_overlap`` 的度量
    完全一致（都是 containment），只是分词不同；``similarity_score`` 则用了
    另一种分母。度量口径被重复实现、分词差异却被混在同一层，是这次要消
    除的"两套记法"。

职责边界：
    本模块只提供**集合度量**与最基础的分词工具。各场景特有的分词方式
    （如 Deduplicator 的"拉丁词 + 中文 bigram"）仍保留在原处——分词差异
    是合理的，度量公式的重复实现才是问题。

改名提醒：
    历史上 ``similarity_score`` 这个名字容易让人误以为是 Jaccard，实际它
    的分母是 max 而非并集。这里按真实语义命名为 ``intersection_over_max``。
"""

from __future__ import annotations

import re
from typing import Iterable, Set

_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")


def intersection_over_max(a: Iterable, b: Iterable) -> float:
    """|A∩B| / max(|A|, |B|)

    分母取较大集合，因此得分恒 ≥ Jaccard（分母 max(|A|,|B|) ≤ 并集）。
    当一方完整包含另一方（A ⊆ B 或 B ⊆ A）时与 Jaccard 相等，都是 |A|/|B|；
    两个集合各自持有对方没有的元素时，本口径比 Jaccard 更宽容。

    注意这不是 Jaccard（Jaccard 分母是并集）；也不是 containment——
    ``containment`` 在 A ⊆ B 时得 1.0，本函数得 |A|/|B|。
    """
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(max(len(sa), len(sb), 1))


def containment(a: Iterable, b: Iterable) -> float:
    """|A∩B| / min(|A|, |B|)

    分母取较小集合，衡量"较短那段是否被较长那段覆盖"。
    比 Jaccard 更适合短文本：只要核心内容被覆盖就能得高分。
    """
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    # 上面已保证 sa / sb 都非空，故 min(len(sa), len(sb)) 必 ≥ 1，
    # 原先那层 `if not denom: return 0.0` 恒不成立（2026-09-23 删除，行为零变化）。
    return len(sa & sb) / float(min(len(sa), len(sb)))


def jaccard(a: Iterable, b: Iterable) -> float:
    """标准 Jaccard：|A∩B| / |A∪B|"""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    # 同理：sa / sb 都非空 ⇒ 并集必非空，`if not union` 恒不成立
    # （2026-09-23 删除，行为零变化）。
    return len(sa & sb) / float(len(sa | sb))


def char_ngrams(text: str, n: int = 2) -> Set[str]:
    """按字符切 n-gram（不区分大小写由调用方保证）"""
    s = str(text or "")
    if len(s) < n:
        return {s} if s else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def cjk_chars(text: str) -> Set[str]:
    """提取中文字符集合"""
    return set(_CJK_PATTERN.findall(str(text or "")))
