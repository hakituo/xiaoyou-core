"""dated transcript 导入器的日期映射：默认平移 vs 保留源日期。

背景：``build_date_mapping`` 默认把源稿里出现的日期压到一条**连续**日期带上
（终点由 ``--end-date`` 反推）。源稿只写月日、真实年份不可知，且多数连续记录
确实逐日有消息，这个规则够用；但源稿日期**不连续**时空缺日会被一并压掉，
日期整体前移。``--preserve-source-dates`` / ``--source-year`` 让源稿日期原样保留。
"""

from __future__ import annotations

import importlib
import sys
from datetime import date
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 注意：``scripts.import.xxx`` 里的 ``import`` 是 Python 关键字，
# 不能用 ``from scripts.import.xxx import yyy``（语法错误），只能走 importlib。
_importer = importlib.import_module("scripts.import.import_dated_chat_transcript")
TranscriptMessage = _importer.TranscriptMessage
build_date_mapping = _importer.build_date_mapping


def _msg(index: int, month: int, day: int, speaker: str = "我", content: str = "x"):
    return TranscriptMessage(
        source_index=index,
        source_month=month,
        source_day=day,
        hour=12,
        minute=0,
        speaker=speaker,
        content=content,
    )


def test_default_mapping_is_consecutive_ending_at_end_date():
    """默认平移：源日期不连续时，空缺日被压掉，日期整体前移。"""
    messages = [_msg(0, 7, 24), _msg(1, 7, 25), _msg(2, 12, 24)]

    mapping = build_date_mapping(messages, date(2025, 12, 24))

    assert len(mapping) == 3
    # 3 个源日期压到以 end_date 收尾的连续 3 天
    assert mapping[(7, 24)] == date(2025, 12, 22)
    assert mapping[(7, 25)] == date(2025, 12, 23)
    assert mapping[(12, 24)] == date(2025, 12, 24)
    # 真实跨度 153 天被压成 2 天
    assert (mapping[(12, 24)] - mapping[(7, 24)]).days == 2


def test_preserve_source_dates_keeps_real_dates():
    """保留源日期：月日按 source_year 解释，空缺日原样留空。"""
    messages = [_msg(0, 7, 24), _msg(1, 7, 25), _msg(2, 12, 24)]

    mapping = build_date_mapping(
        messages, date(2025, 12, 24), preserve_source_dates=True, source_year=2025
    )

    assert mapping[(7, 24)] == date(2025, 7, 24)
    assert mapping[(7, 25)] == date(2025, 7, 25)
    assert mapping[(12, 24)] == date(2025, 12, 24)
    assert (mapping[(12, 24)] - mapping[(7, 24)]).days == 153


def test_preserve_source_dates_ignores_end_date():
    """保留模式下 end_date 不参与计算。"""
    messages = [_msg(0, 7, 24), _msg(1, 12, 24)]

    a = build_date_mapping(
        messages, date(2025, 12, 24), preserve_source_dates=True, source_year=2025
    )
    b = build_date_mapping(
        messages, date(2030, 1, 1), preserve_source_dates=True, source_year=2025
    )

    assert a == b


def test_preserve_source_dates_requires_year():
    with pytest.raises(ValueError, match="source_year"):
        build_date_mapping(
            [_msg(0, 7, 24)], date(2025, 12, 24), preserve_source_dates=True
        )


def test_preserve_source_dates_rejects_non_increasing_dates():
    """跨年 / 乱序源稿必须报错，而不是悄悄算错。"""
    messages = [_msg(0, 12, 24), _msg(1, 1, 5)]

    with pytest.raises(ValueError, match="严格递增"):
        build_date_mapping(
            messages, date(2025, 12, 24), preserve_source_dates=True, source_year=2025
        )


def test_preserve_source_dates_rejects_nonexistent_date():
    with pytest.raises(ValueError, match="不存在"):
        build_date_mapping(
            [_msg(0, 2, 30)],
            date(2025, 12, 24),
            preserve_source_dates=True,
            source_year=2025,
        )


def test_two_modes_agree_when_source_is_consecutive():
    """源稿连续、且跨度正好以 end_date 收尾时，两种模式结果一致。

    Aveline 3.1~5.25 就是这种：86 个源日期正好是 03-01~05-25 连续 86 天，
    终点又取 2026-05-25，所以平移得到的仍是真实日期。
    """
    messages = [_msg(i, 5, 1 + i) for i in range(5)]

    shifted = build_date_mapping(messages, date(2026, 5, 5))
    preserved = build_date_mapping(
        messages, date(2026, 5, 5), preserve_source_dates=True, source_year=2026
    )

    assert shifted == preserved
    assert preserved[(5, 1)] == date(2026, 5, 1)
    assert preserved[(5, 5)] == date(2026, 5, 5)


def test_two_modes_differ_when_end_date_is_not_the_source_end():
    """源稿连续但终点不对齐时，平移会整体挪走真实日期——这正是要避免的。"""
    messages = [_msg(i, 3, 1 + i) for i in range(5)]

    shifted = build_date_mapping(messages, date(2026, 5, 5))
    preserved = build_date_mapping(
        messages, date(2026, 5, 5), preserve_source_dates=True, source_year=2026
    )

    assert shifted[(3, 1)] == date(2026, 5, 1)   # 被挪到 5 月
    assert preserved[(3, 1)] == date(2026, 3, 1)  # 保留 3 月
    assert shifted != preserved
