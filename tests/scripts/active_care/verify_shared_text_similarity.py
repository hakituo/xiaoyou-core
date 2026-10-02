"""验证相似度度量抽取到共享模块后行为零变化

背景（2026-09-03）：
    同一个"两个集合有多像"的计算被写了多遍，分母口径却不一致：

      - deduplicator.similarity_score       → |A∩B| / max(|A|,|B|)
      - deduplicator._char_unigram_overlap  → |A∩B| / min(|A|,|B|)
      - topic_diversity._compute_keyword_overlap → |A∩B| / min(|A|,|B|)

    本轮把**度量公式**抽到 core/utils/text_similarity.py
    （intersection_over_max / containment / jaccard），
    各场景特有的分词方式保留在原处。

    分词差异是合理的，度量公式的重复实现才是问题。但抽取数学公式有改错
    的风险，因此本脚本用"改动前的原始实现"作为参考，逐例比对确认
    **数值完全一致**——这类重构只有在行为零变化时才算安全。

本脚本校验：
- 共享度量的三个公式本身正确（含空集、单元素、长度悬殊等边界）；
- Deduplicator.similarity_score 与旧实现逐例一致；
- Deduplicator._char_unigram_overlap 与旧实现逐例一致；
- topic_diversity._compute_keyword_overlap 与旧实现逐例一致；
- 去重判定端到端不受影响。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_PASSED = 0
_FAILED = 0

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _ok(msg: str) -> None:
    global _PASSED
    _PASSED += 1
    print(f"  [PASS] {msg}")


def _fail(msg: str, detail: str = "") -> None:
    global _FAILED
    _FAILED += 1
    print(f"  [FAIL] {msg}")
    if detail:
        print(f"         {detail}")


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


# ── 改动前的原始实现，作为回归基准 ─────────────────────


def old_similarity_score(dedup_cls, a: str, b: str) -> float:
    ta = dedup_cls.tokenize_for_repeat_check(a)
    tb = dedup_cls.tokenize_for_repeat_check(b)
    if not ta or not tb:
        return 0.0
    sa, sb = set(ta), set(tb)
    return len(sa & sb) / float(max(len(sa), len(sb), 1))


def old_char_unigram_overlap(dedup_cls, a: str, b: str) -> float:
    a_norm = dedup_cls.normalize_for_repeat_check(a)
    b_norm = dedup_cls.normalize_for_repeat_check(b)
    if not a_norm or not b_norm:
        return 0.0
    a_chars = set(_CJK_RE.findall(a_norm))
    b_chars = set(_CJK_RE.findall(b_norm))
    if not a_chars or not b_chars:
        return 0.0
    return len(a_chars & b_chars) / float(min(len(a_chars), len(b_chars)))


def old_keyword_overlap(a: str, b: str, min_len: int = 2) -> float:
    a_lower = str(a or "").strip().lower()
    b_lower = str(b or "").strip().lower()
    if not a_lower or not b_lower:
        return 0.0
    a_grams = {a_lower[i : i + min_len] for i in range(len(a_lower) - min_len + 1)}
    b_grams = {b_lower[i : i + min_len] for i in range(len(b_lower) - min_len + 1)}
    if not a_grams or not b_grams:
        return 0.0
    min_size = min(len(a_grams), len(b_grams))
    return len(a_grams & b_grams) / min_size if min_size else 0.0


SAMPLES = [
    ("", ""),
    ("", "中午吃什么"),
    ("中午吃什么呀", "中午吃什么呀"),
    ("中午吃什么呀", "你论文改完了没"),
    ("在做家务呢，你呢？", "在做家务呢，你呢？"),
    ("在做家务呢", "刚在做饭呢"),
    ("饱了", "饱得很"),
    ("怎么还不去睡觉", "你到底睡不睡"),
    ("今天背单词了吗", "今天背单词了吗"),
    ("今天背单词了吗", "今天背单词了没"),
    ("a", "a"),
    ("abc def", "abc xyz"),
    ("学习 English 单词", "学习 english 词汇"),
    ("很长的一段话用来测试长度悬殊时的表现" * 3, "测试"),
    ("测试", "很长的一段话用来测试长度悬殊时的表现" * 3),
]


def test_shared_formulas() -> None:
    _section("测试 1: 共享度量公式本身正确")
    from core.utils.text_similarity import containment, intersection_over_max, jaccard

    if intersection_over_max({"a", "b"}, {"a", "b"}) == 1.0:
        _ok("intersection_over_max 完全相同 → 1.0")
    else:
        _fail("intersection_over_max 完全相同应为 1.0")

    if intersection_over_max(set(), {"a"}) == 0.0:
        _ok("intersection_over_max 空集 → 0.0")
    else:
        _fail("intersection_over_max 空集应为 0.0")

    # 分母取 max：短集合被长集合包含时仍为 1.0（不被稀释）
    val = intersection_over_max({"a"}, {"a", "b", "c"})
    if abs(val - 1 / 3) < 1e-9:
        _ok(f"intersection_over_max 分母取 max（{{a}} vs {{a,b,c}} → {val:.3f}）")
    else:
        _fail("intersection_over_max 分母不是 max", str(val))

    val = containment({"a"}, {"a", "b", "c"})
    if abs(val - 1.0) < 1e-9:
        _ok(f"containment 分母取 min（{{a}} vs {{a,b,c}} → {val:.3f}）")
    else:
        _fail("containment 分母不是 min", str(val))

    if abs(jaccard({"a", "b"}, {"b", "c"}) - 1 / 3) < 1e-9:
        _ok("jaccard 分母取并集")
    else:
        _fail("jaccard 分母不是并集")


def test_dedup_similarity_score_unchanged() -> None:
    _section("测试 2: Deduplicator.similarity_score 与旧实现逐例一致")
    from core.services.active_care.postprocess.deduplicator import Deduplicator

    bad = []
    for a, b in SAMPLES:
        old = old_similarity_score(Deduplicator, a, b)
        new = Deduplicator.similarity_score(a, b)
        if abs(old - new) > 1e-12:
            bad.append((a[:20], b[:20], old, new))
    if bad:
        _fail(f"{len(bad)} 例数值发生变化", str(bad[:3]))
    else:
        _ok(f"{len(SAMPLES)} 例数值完全一致")


def test_char_unigram_overlap_unchanged() -> None:
    _section("测试 3: Deduplicator._char_unigram_overlap 与旧实现逐例一致")
    from core.services.active_care.postprocess.deduplicator import Deduplicator

    bad = []
    for a, b in SAMPLES:
        old = old_char_unigram_overlap(Deduplicator, a, b)
        new = Deduplicator._char_unigram_overlap(a, b)  # noqa: SLF001
        if abs(old - new) > 1e-12:
            bad.append((a[:20], b[:20], old, new))
    if bad:
        _fail(f"{len(bad)} 例数值发生变化", str(bad[:3]))
    else:
        _ok(f"{len(SAMPLES)} 例数值完全一致")


def test_keyword_overlap_unchanged() -> None:
    _section("测试 4: topic_diversity._compute_keyword_overlap 与旧实现逐例一致")
    from core.services.active_care.prompt.topic_diversity import (
        _compute_keyword_overlap,
    )

    bad = []
    for a, b in SAMPLES:
        old = old_keyword_overlap(a, b)
        new = _compute_keyword_overlap(a, b)
        if abs(old - new) > 1e-12:
            bad.append((a[:20], b[:20], old, new))
    if bad:
        _fail(f"{len(bad)} 例数值发生变化", str(bad[:3]))
    else:
        _ok(f"{len(SAMPLES)} 例数值完全一致")


def test_dedup_end_to_end() -> None:
    _section("测试 5: 去重端到端判定不受影响")
    from core.services.active_care.postprocess.deduplicator import Deduplicator

    repeats = [
        ("中午吃什么呀", "中午吃什么呀"),
        ("在做家务呢，你呢？", "在做家务呢，你呢？"),
        ("今天背单词了吗", "今天背单词了吗"),
    ]
    for a, b in repeats:
        if Deduplicator.is_semantically_repetitive(b, a):
            _ok(f"仍拦截复读: {a!r}")
        else:
            _fail(f"未能拦截明显复读: {a!r}")

    distinct = [
        ("中午吃什么呀", "你论文改完了没"),
        ("在做家务呢", "刚才看到一句话挺有意思的"),
    ]
    for a, b in distinct:
        if not Deduplicator.is_semantically_repetitive(b, a):
            _ok(f"未误杀: {b!r}")
        else:
            _fail(f"误杀无关消息: {b!r}")


def test_module_documents_thresholds() -> None:
    _section("测试 6: 共享模块对三种度量的差异有明确说明")
    doc = (
        _PROJECT_ROOT / "core" / "utils" / "text_similarity.py"
    ).read_text(encoding="utf-8")
    for name in ("intersection_over_max", "containment", "jaccard"):
        if f"def {name}" in doc:
            _ok(f"提供 {name}")
        else:
            _fail(f"缺少 {name}")
    if "不是 Jaccard" in doc or "注意这不是 Jaccard" in doc:
        _ok("已明确标注 intersection_over_max 不等于 Jaccard（避免误用）")
    else:
        _fail("未标注与 Jaccard 的区别，容易被误用")


def main() -> int:
    print("=" * 64)
    print("相似度度量抽取为共享实现 —— 行为零变化 验证")
    print("=" * 64)

    test_shared_formulas()
    test_dedup_similarity_score_unchanged()
    test_char_unigram_overlap_unchanged()
    test_keyword_overlap_unchanged()
    test_dedup_end_to_end()
    test_module_documents_thresholds()

    print("\n" + "=" * 64)
    print(f"结果: {_PASSED} 通过 / {_FAILED} 失败")
    print("=" * 64)
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
