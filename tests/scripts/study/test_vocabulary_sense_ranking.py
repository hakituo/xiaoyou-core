# -*- coding: utf-8 -*-
"""回归测试：词书构建期 learner sense priority。

可直接运行：
    python tests/scripts/study/test_vocabulary_sense_ranking.py
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from scripts.study.vocabulary.generate_sense_rankings import (  # noqa: E402
    _validate_result,
)
from scripts.study.vocabulary.sense_ranking import (  # noqa: E402
    compile_sense_rankings,
    load_sense_rankings,
)
from scripts.study.vocabulary.wordbook_builder import (  # noqa: E402
    load_overrides,
    parse_translations,
)


class VocabularySenseRankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rankings = load_sense_rankings()
        cls.overrides = load_overrides()

    def _parse(self, word: str, raw: str, override=None):
        return parse_translations(
            raw,
            override=override,
            sense_ranking=self.rankings.get(word),
        )

    def test_perspective_viewpoint_precedes_visual_and_vista(self) -> None:
        primary, extended, fallback = self._parse(
            "perspective",
            "n. 远景\nn. 透视；透视法\nn. 观点；视角",
        )
        self.assertEqual(
            [item["translation"] for item in primary],
            ["观点；视角", "透视；透视法", "远景"],
        )
        self.assertEqual(extended, [])
        self.assertFalse(fallback)

    def test_no_ranking_preserves_source_order(self) -> None:
        raw = "n. 后一个义\nn. 前一个义\nvt. 处理"
        primary, extended, fallback = parse_translations(raw)
        self.assertEqual(
            [item["translation"] for item in primary],
            ["后一个义", "前一个义", "处理"],
        )
        self.assertEqual(extended, [])
        self.assertFalse(fallback)

    def test_partial_ranking_keeps_unmatched_source_slot(self) -> None:
        ranking = compile_sense_rankings(
            {
                "version": 1,
                "words": {
                    "perspective": {
                        "n": [
                            {
                                "sense_id": "viewpoint",
                                "rank": 1,
                                "aliases_zh": ["观点"],
                            },
                            {
                                "sense_id": "visual",
                                "rank": 2,
                                "aliases_zh": ["透视"],
                            },
                        ]
                    }
                },
            }
        )["perspective"]
        primary, _, _ = parse_translations(
            "n. 未知新义\nn. 透视\nn. 观点",
            sense_ranking=ranking,
        )
        self.assertEqual(
            [item["translation"] for item in primary],
            ["未知新义", "观点", "透视"],
        )

    def test_ambiguous_candidate_is_not_guessed(self) -> None:
        ranking = compile_sense_rankings(
            {
                "version": 1,
                "words": {
                    "demo": {
                        "n": [
                            {"sense_id": "a", "rank": 1, "aliases_zh": ["观点"]},
                            {"sense_id": "b", "rank": 2, "aliases_zh": ["透视"]},
                            {"sense_id": "c", "rank": 3, "aliases_zh": ["远景"]},
                        ]
                    }
                },
            }
        )["demo"]
        primary, _, _ = parse_translations(
            "n. 观点；透视\nn. 远景",
            sense_ranking=ranking,
        )
        self.assertEqual(
            [item["translation"] for item in primary],
            ["观点；透视", "远景"],
        )

    def test_manual_override_is_always_highest_precedence(self) -> None:
        synthetic = compile_sense_rankings(
            {
                "version": 1,
                "words": {
                    "issue": {
                        "n": [
                            {
                                "sense_id": "special",
                                "rank": 1,
                                "aliases_zh": ["特殊义"],
                            },
                            {
                                "sense_id": "problem",
                                "rank": 2,
                                "aliases_zh": ["问题"],
                            },
                        ]
                    }
                },
            }
        )
        primary, extended, _ = parse_translations(
            "n. 特殊义\nn. 问题",
            override=self.overrides["issue"],
            sense_ranking=synthetic["issue"],
        )
        self.assertEqual(primary[0]["translation"], "问题；议题")
        self.assertTrue(primary[0].get("primary"))
        self.assertEqual(primary[1]["translation"], "发布；发行；发给")
        self.assertEqual(
            [item["translation"] for item in extended],
            ["特殊义", "问题"],
        )

    def test_address_noun_and_verb_rankings_do_not_pollute_each_other(self) -> None:
        ranking = compile_sense_rankings(
            {
                "version": 1,
                "words": {
                    "address": {
                        "n": [
                            {"sense_id": "postal", "rank": 1, "aliases_zh": ["地址"]},
                            {"sense_id": "speech", "rank": 2, "aliases_zh": ["演说"]},
                        ],
                        "v": [
                            {"sense_id": "deal_with", "rank": 1, "aliases_zh": ["处理"]},
                            {
                                "sense_id": "speak_to",
                                "rank": 2,
                                "aliases_zh": ["向……讲话"],
                            },
                        ],
                    }
                },
            }
        )["address"]
        primary, _, _ = parse_translations(
            "n. 演说\nvt. 向……讲话\nn. 地址\nvt. 处理",
            sense_ranking=ranking,
        )
        self.assertEqual(
            [(item["type"], item["translation"]) for item in primary],
            [
                ("n", "地址"),
                ("vt", "处理"),
                ("n", "演说"),
                ("vt", "向……讲话"),
            ],
        )

    def test_conduct_v_rule_applies_to_vt_without_touching_noun(self) -> None:
        ranking = compile_sense_rankings(
            {
                "version": 1,
                "words": {
                    "conduct": {
                        "n": [
                            {"sense_id": "behavior", "rank": 1, "aliases_zh": ["行为"]},
                            {"sense_id": "demeanor", "rank": 2, "aliases_zh": ["举止"]},
                        ],
                        "v": [
                            {"sense_id": "carry_out", "rank": 1, "aliases_zh": ["实施"]},
                            {"sense_id": "direct", "rank": 2, "aliases_zh": ["指挥"]},
                        ],
                    }
                },
            }
        )["conduct"]
        primary, _, _ = parse_translations(
            "n. 举止\nvt. 指挥\nn. 行为\nvt. 实施",
            sense_ranking=ranking,
        )
        self.assertEqual(
            [item["translation"] for item in primary],
            ["行为", "实施", "举止", "指挥"],
        )

    def test_domain_meanings_stay_extended(self) -> None:
        primary, extended, fallback = self._parse(
            "matter",
            "n. [物] 物质的专门定义\nn. 事情\nn. 物质",
        )
        self.assertEqual(
            [item["translation"] for item in primary],
            ["事情", "物质"],
        )
        self.assertEqual(len(extended), 1)
        self.assertEqual(extended[0]["translation"], "物质的专门定义")
        self.assertEqual(extended[0]["domains"], ["物"])
        self.assertFalse(fallback)

    def test_domain_only_fallback_is_unchanged(self) -> None:
        primary, extended, fallback = parse_translations(
            "n. [物] 第一专业义\nn. [化] 第二专业义"
        )
        self.assertEqual(
            [item["translation"] for item in primary],
            ["第一专业义", "第二专业义"],
        )
        self.assertEqual(extended, [])
        self.assertTrue(fallback)

    def test_seed_multi_sense_words_have_stable_learning_order(self) -> None:
        cases = {
            "approach": ("n. 接近\nn. 方法", ["方法", "接近"]),
            "figure": (
                "n. 身材\nn. 图形\nn. 人物\nn. 数字",
                ["数字", "人物", "图形", "身材"],
            ),
            "matter": ("n. 物质\nn. 事情", ["事情", "物质"]),
            "subject": (
                "n. 臣民\nn. 学科\nn. 主题",
                ["主题", "学科", "臣民"],
            ),
            "charge": (
                "n. 电荷\nn. 责任\nn. 指控\nn. 费用",
                ["费用", "指控", "责任", "电荷"],
            ),
            "point": ("n. 分数\nn. 点\nn. 要点", ["要点", "点", "分数"]),
            "scale": ("n. 鳞片\nn. 刻度\nn. 规模", ["规模", "刻度", "鳞片"]),
        }
        for word, (raw, expected) in cases.items():
            with self.subTest(word=word):
                primary, _, _ = self._parse(word, raw)
                self.assertEqual(
                    [item["translation"] for item in primary],
                    expected,
                )

    def test_ranking_is_deterministic(self) -> None:
        raw = "n. 鳞片\nn. 刻度\nn. 规模\nv. 攀登\nv. 缩放"
        first = self._parse("scale", raw)
        second = self._parse("scale", raw)
        self.assertEqual(first, second)

    def test_duplicate_alias_in_same_pos_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            compile_sense_rankings(
                {
                    "version": 1,
                    "words": {
                        "bad": {
                            "n": [
                                {"sense_id": "a", "rank": 1, "aliases_zh": ["同义"]},
                                {"sense_id": "b", "rank": 2, "aliases_zh": ["同义"]},
                            ]
                        }
                    },
                }
            )

    def test_offline_generator_rejects_invented_candidate(self) -> None:
        group = {
            "word": "perspective",
            "pos": "n",
            "candidates": [
                {"id": "c0", "translation": "远景"},
                {"id": "c1", "translation": "观点"},
            ],
        }
        with self.assertRaises(ValueError):
            _validate_result(
                group,
                {
                    "senses": [
                        {
                            "sense_id": "viewpoint",
                            "rank": 1,
                            "tier": "core",
                            "candidate_ids": ["c1", "invented"],
                            "confidence": 0.9,
                        },
                        {
                            "sense_id": "vista",
                            "rank": 2,
                            "tier": "rare",
                            "candidate_ids": ["c0"],
                            "confidence": 0.9,
                        },
                    ]
                },
            )

    def test_offline_generator_rejects_missing_candidate(self) -> None:
        group = {
            "word": "perspective",
            "pos": "n",
            "candidates": [
                {"id": "c0", "translation": "远景"},
                {"id": "c1", "translation": "观点"},
            ],
        }
        with self.assertRaises(ValueError):
            _validate_result(
                group,
                {
                    "senses": [
                        {
                            "sense_id": "viewpoint",
                            "rank": 1,
                            "tier": "core",
                            "candidate_ids": ["c1"],
                            "confidence": 0.9,
                        }
                    ]
                },
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
