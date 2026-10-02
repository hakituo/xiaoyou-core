"""core/utils/text_similarity.py 单元测试。

本模块存在的原因（见模块 docstring）：同一个"两个集合有多像"的计算在项目里
被重复实现了多遍，分母时而取 max、时而取 min、时而取并集，名字却都叫"相似度"。
因此本测试的重点不是"函数能算出一个数"，而是**用同一对输入钉住三个度量的差异**，
防止将来有人再把口径合并/改错分母而无人察觉。
"""

from __future__ import annotations

import pytest

from core.utils.text_similarity import (
    char_ngrams,
    cjk_chars,
    containment,
    intersection_over_max,
    jaccard,
)


class TestIntersectionOverMax:
    """|A∩B| / max(|A|,|B|)：分母取较大集合，对长度悬殊的文本更宽容。"""

    def test_empty_left_returns_zero(self):
        assert intersection_over_max([], [1, 2]) == 0.0

    def test_empty_right_returns_zero(self):
        assert intersection_over_max([1, 2], []) == 0.0

    def test_both_empty_returns_zero(self):
        assert intersection_over_max([], []) == 0.0

    def test_identical_sets_return_one(self):
        assert intersection_over_max([1, 2, 3], [1, 2, 3]) == 1.0

    def test_subset_uses_larger_size_as_denominator(self):
        """A ⊆ B 时得 |A|/|B|，不是 1.0。

        1.0 是 ``containment`` 的行为（分母取较小集合）。本函数的分母是
        max(|A|,|B|)，所以 [1,2] 对 [1,2,3,4] 得 2/4。
        """
        assert intersection_over_max([1, 2], [1, 2, 3, 4]) == pytest.approx(0.5)

    def test_partial_overlap_divides_by_larger_size(self):
        # |{1,2,3} ∩ {3,4}| = 1，max(3, 2) = 3 → 1/3
        assert intersection_over_max([1, 2, 3], [3, 4]) == pytest.approx(1 / 3)

    def test_disjoint_returns_zero(self):
        assert intersection_over_max([1, 2], [3, 4]) == 0.0

    def test_duplicates_are_collapsed(self):
        # 按集合语义去重：|{1}| / max(1, 1) = 1.0
        assert intersection_over_max([1, 1, 1], [1]) == 1.0

    def test_accepts_arbitrary_iterables(self):
        # 参数是 Iterable，生成器与字符串同样可用
        assert intersection_over_max(iter("ab"), "abc") == pytest.approx(2 / 3)


class TestContainment:
    """|A∩B| / min(|A|,|B|)：分母取较小集合，衡量"短的那段是否被覆盖"。"""

    def test_empty_left_returns_zero(self):
        assert containment([], [1, 2]) == 0.0

    def test_empty_right_returns_zero(self):
        assert containment([1, 2], []) == 0.0

    def test_both_empty_returns_zero(self):
        assert containment([], []) == 0.0

    def test_shorter_argument_fully_covered_returns_one(self):
        assert containment([1, 2], [1, 2, 3, 4]) == 1.0

    def test_longer_argument_fully_covered_returns_one(self):
        # 分母取较小集合，所以谁在前不影响结果
        assert containment([1, 2, 3, 4], [1, 2]) == 1.0

    def test_partial_overlap_divides_by_smaller_size(self):
        # |{1,2,3} ∩ {2,3,4,5}| = 2，min(3, 4) = 3 → 2/3
        assert containment([1, 2, 3], [2, 3, 4, 5]) == pytest.approx(2 / 3)

    def test_disjoint_returns_zero(self):
        assert containment([1, 2], [3, 4]) == 0.0


class TestJaccard:
    """标准 Jaccard：|A∩B| / |A∪B|。"""

    def test_empty_left_returns_zero(self):
        assert jaccard([], [1, 2]) == 0.0

    def test_empty_right_returns_zero(self):
        assert jaccard([1, 2], []) == 0.0

    def test_both_empty_returns_zero(self):
        assert jaccard([], []) == 0.0

    def test_identical_sets_return_one(self):
        assert jaccard([1, 2, 3], [1, 2, 3]) == 1.0

    def test_standard_denominator_is_union(self):
        # |{1,2} ∩ {2,3}| = 1，|{1,2} ∪ {2,3}| = 3 → 1/3
        assert jaccard([1, 2], [2, 3]) == pytest.approx(1 / 3)

    def test_disjoint_returns_zero(self):
        assert jaccard([1, 2], [3, 4]) == 0.0


class TestMetricDistinction:
    """三个度量在同一对输入上的数值差异——这是本模块存在的全部理由。

    若将来有人把某个度量的分母改回"更顺手"的写法，这里会立刻失败。
    """

    A = [1, 2, 3]
    B = [2, 3, 4, 5]

    def test_three_metrics_disagree_on_same_input(self):
        # 交集 2：max(3,4)=4 → 2/4；min(3,4)=3 → 2/3；并集 5 → 2/5
        assert intersection_over_max(self.A, self.B) == pytest.approx(2 / 4)
        assert containment(self.A, self.B) == pytest.approx(2 / 3)
        assert jaccard(self.A, self.B) == pytest.approx(2 / 5)

    def test_containment_is_never_below_the_other_two(self):
        assert containment(self.A, self.B) >= intersection_over_max(self.A, self.B)
        assert containment(self.A, self.B) >= jaccard(self.A, self.B)

    def test_subset_case_separates_max_from_union(self):
        # A ⊂ B 时：max 口径给 |A|/|B|，Jaccard 给 |A|/|B|，containment 给 1.0
        a, b = [1, 2], [1, 2, 3, 4]
        assert intersection_over_max(a, b) == pytest.approx(0.5)
        assert jaccard(a, b) == pytest.approx(0.5)
        assert containment(a, b) == 1.0


class TestCharNgrams:
    """按字符切 n-gram。"""

    def test_empty_string_returns_empty_set(self):
        assert char_ngrams("") == set()

    def test_none_is_coerced_to_empty_set(self):
        assert char_ngrams(None) == set()

    def test_string_shorter_than_n_returns_whole_string(self):
        assert char_ngrams("a") == {"a"}
        assert char_ngrams("ab", 3) == {"ab"}

    def test_default_bigrams(self):
        assert char_ngrams("abcd") == {"ab", "bc", "cd"}

    def test_custom_n_of_one(self):
        assert char_ngrams("abcd", 1) == {"a", "b", "c", "d"}

    def test_non_string_input_is_coerced(self):
        assert char_ngrams(12345) == {"12", "23", "34", "45"}

    def test_cjk_text_is_split_by_character(self):
        assert char_ngrams("Ye") == {"Ye"}


class TestCjkChars:
    """只保留中文字符集合。"""

    def test_extracts_only_cjk_characters(self):
        assert cjk_chars("你好abc世界!") == {"你", "好", "世", "界"}

    def test_empty_string_returns_empty_set(self):
        assert cjk_chars("") == set()

    def test_none_is_coerced_to_empty_set(self):
        assert cjk_chars(None) == set()

    def test_text_without_cjk_returns_empty_set(self):
        assert cjk_chars("abc123 !?") == set()

    def test_duplicate_characters_are_collapsed(self):
        assert cjk_chars("好好好") == {"好"}

    def test_non_string_input_is_coerced(self):
        assert cjk_chars(123) == set()
