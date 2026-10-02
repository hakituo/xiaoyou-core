"""BM25 词法检索。

**学习场景不能只靠向量。** 像

    F = -kx    ΔU    v = v0 + at    ATP    NADH    2p

这种公式和缩写，词法匹配常常比 embedding 更准——向量容易把「动量定理」
和「动能定理」混在一起，而关键词不会。

依赖：jieba（项目已有）。不引入新的重依赖。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable, List, Sequence, Tuple

_TOKEN_SPLIT_RE = re.compile(r"[\s,.;:!?()\[\]{}<>\"'、。，；：！？（）【】「」]+")

#: 公式/符号等短 token 至少要保留的字符，避免把 "F" 这种单字母当成噪声丢掉
MIN_TOKEN_LEN = 1


def tokenize(text: str) -> List[str]:
    """中英混合分词。

    - 英文/数字片段整体保留并小写化（F=-kx、NADH 不能被拆碎）
    - 中文用 jieba 切词
    - 过滤纯标点与空白
    """
    text = str(text or "")
    if not text:
        return []

    tokens: List[str] = []
    for raw in _TOKEN_SPLIT_RE.split(text):
        raw = raw.strip()
        if not raw:
            continue
        if re.fullmatch(r"[A-Za-z0-9_\-=+*/^·Δ∑≤≥≈]+", raw):
            tokens.append(raw.lower())
            continue
        # 中英混杂的片段：先按字符类型切开，再对中文部分用 jieba
        for piece in re.findall(r"[A-Za-z0-9_\-=+*/^]+|[^\sA-Za-z0-9_\-=+*/^]+", raw):
            piece = piece.strip()
            if not piece:
                continue
            if re.fullmatch(r"[A-Za-z0-9_\-=+*/^]+", piece):
                tokens.append(piece.lower())
            else:
                tokens.extend(_jieba_cut(piece))
    return [t for t in tokens if len(t) >= MIN_TOKEN_LEN]


_JIEBA_DISABLED = False


def _jieba_cut(text: str) -> List[str]:
    try:
        import jieba

        return [t for t in jieba.cut(text) if t.strip()]
    except Exception:  # noqa: BLE001
        # jieba 不可用时退化为按字切：中文单字检索效果可接受，不至于整体失效
        return [ch for ch in text if ch.strip()]


class BM25:
    """极简 BM25。够用即可，不引入 rank_bm25 之类的额外依赖。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._docs: List[List[str]] = []
        self._tf: List[Counter] = []
        self._df: Counter = Counter()
        self._avg_len = 0.0

    @property
    def size(self) -> int:
        return len(self._docs)

    def add(self, tokens: Sequence[str]) -> int:
        """加入一篇文档，返回其索引。"""
        tokens = list(tokens)
        index = len(self._docs)
        self._docs.append(tokens)
        tf = Counter(tokens)
        self._tf.append(tf)
        for term in tf:
            self._df[term] += 1
        total = sum(len(d) for d in self._docs)
        self._avg_len = total / len(self._docs) if self._docs else 0.0
        return index

    def scores(self, query_tokens: Iterable[str]) -> List[float]:
        """对全部文档打分，返回与 add 顺序一致的分数列表。"""
        query = set(query_tokens)
        if not query or not self._docs:
            return [0.0] * len(self._docs)

        n = len(self._docs)
        results: List[float] = []
        for index, tokens in enumerate(self._docs):
            tf = self._tf[index]
            doc_len = len(tokens) or 1
            score = 0.0
            for term in query:
                freq = tf.get(term, 0)
                if not freq:
                    continue
                df = self._df.get(term, 0)
                # IDF 可能为负（term 出现在多数文档里），截断到 0 更稳
                idf = max(0.0, math.log(1 + (n - df + 0.5) / (df + 0.5)))
                denom = freq + self.k1 * (1 - self.b + self.b * doc_len / (self._avg_len or 1))
                score += idf * (freq * (self.k1 + 1)) / denom
            results.append(score)
        return results

    def best(self, query_tokens: Iterable[str], top_k: int = 5) -> List[Tuple[int, float]]:
        scored = list(enumerate(self.scores(query_tokens)))
        scored = [(i, s) for i, s in scored if s > 0]
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[:top_k]


def highlight_terms(text: str, query_tokens: Iterable[str], width: int = 60) -> str:
    """取命中最密集的一小段，供人工排查「为什么搜到这条」。"""
    tokens = [t for t in query_tokens if t and t in text.lower()]
    if not tokens:
        return text[:width]
    lower = text.lower()
    position = min(lower.find(t) for t in tokens if lower.find(t) >= 0)
    start = max(0, position - width // 3)
    return ("…" if start else "") + text[start : start + width].strip()
