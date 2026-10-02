"""层 1 extract：看到了什么（正则命中片段，不做清洗）。

从 ``signal_detector.py`` 拆出，规范见原模块 docstring 的四层模型。
"""
from __future__ import annotations

from typing import List, Tuple

from core.services.study.signal_patterns import (
    _CHEM_FORMULA_RE,
    _EXPLICIT_TOPIC_RES,
    _FORMULA_RE,
    _MAX_CONCEPTS,
    _QUOTED_RE,
)
from core.services.study.signal_types import RawCandidate


# ----------------------------------------------------------------------
# 层 1：extract —— 看到了什么
# ----------------------------------------------------------------------

def extract_raw_candidates(message: str) -> List[RawCandidate]:
    """正则抽取原样片段，**不做任何清洗**（清洗属于 normalize）。

    ``start`` 记录片段在消息里的起始偏移——供 normalize 判断
    「转折标记是否在句首」（R-05 vs R-07），这是位置信息而非语义判断。
    """
    text = str(message or "")
    if not text.strip():
        return []

    rows: List[Tuple[str, str, int]] = []
    rows.extend(
        (match.group(1), "quoted", match.start(1)) for match in _QUOTED_RE.finditer(text)
    )
    for pattern in _EXPLICIT_TOPIC_RES:
        for match in pattern.finditer(text):
            for index, group in enumerate(match.groups(), start=1):
                if group:
                    rows.append((group, "explicit_topic", match.start(index)))
    formula = _FORMULA_RE.search(text)
    if formula:
        rows.append((formula.group(0), "formula", formula.start()))
    chem = _CHEM_FORMULA_RE.search(text)
    if chem:
        rows.append((chem.group(0), "chemistry_formula", chem.start()))

    out: List[RawCandidate] = []
    seen = set()
    for index, (name, source, start) in enumerate(rows):
        key = " ".join(str(name).split())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(
            RawCandidate(
                id=f"raw-{index}",
                name=str(name),
                source=source,
                strength=_raw_strength(source),
                start=int(start),
            )
        )
        if len(out) >= _MAX_CONCEPTS:
            break
    return out


def _raw_strength(source: str) -> str:
    """**raw** strength：只看来源类型的可信度，不看内容像不像知识点。

    内容质量是 filter 的判断；这里回答「detector 最初有多离谱」，
    所以 ``explicit_topic``（正则拼接命中）一律给 weak/medium，不给 strong。
    """
    return {
        "quoted": "strong",
        "formula": "medium",
        "chemistry_formula": "medium",
        "registry": "strong",
        "explicit_tool": "strong",
    }.get(source, "medium" if source == "explicit_topic" else "weak")
