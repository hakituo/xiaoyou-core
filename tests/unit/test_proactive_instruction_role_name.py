# -*- coding: utf-8 -*-
"""单元测试：主动消息 instruction 必须用角色显示名称呼角色。

回归 2026-09-18：instruction 里 `你（{role_id}）` 填进去是内部 ID `ling`，
模型看到「你（ling）」角色代入被削弱；配合模板缺第一人称要求，
产出了「要上课了先回去了」这种没有主语、像用户在报备日程的句子。

详见 docs/important/ACTIVE_CARE_REPLY_CONTINUITY_PLAN.md R5 / P4。
"""

from __future__ import annotations

import pathlib
import re

import pytest

_ADDRESS_RE = re.compile(r"你（([^）]*)）")
_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _builders():
    from core.services.active_care.good_morning_proactive import (
        _build_specific_instruction as good_morning,
    )
    from core.services.active_care.goodnight_proactive import (
        _build_specific_instruction as goodnight,
    )
    from core.services.character_daily.activity_return.instruction import (
        build_activity_start_farewell_instruction,
        build_busy_done_active_instruction,
        build_return_instruction,
        build_sleep_during_chat_farewell_instruction,
    )

    return {
        "activity_farewell": lambda r: build_activity_start_farewell_instruction(r, "studying"),
        "return_work": lambda r: build_return_instruction(r, "studying", "work"),
        "return_sleep": lambda r: build_return_instruction(r, "sleeping", "sleep"),
        "sleep_during_chat": lambda r: build_sleep_during_chat_farewell_instruction(r),
        "busy_done": lambda r: build_busy_done_active_instruction(r, "studying", ["在吗"]),
        "goodnight": lambda r: goodnight(r, False),
        "sleep_again": lambda r: goodnight(r, True),
        "good_morning": lambda r: good_morning(r, False),
        "stay_up_recovery": lambda r: good_morning(r, True),
    }


@pytest.mark.parametrize("role_id", ["ling", "aveline", "ye", "lin", "rushuang", "yeye"])
def test_address_uses_display_name(role_id):
    """每个注册角色的 instruction 称呼都必须是显示名，不能是内部 ID。"""
    from core.services.dual_role.personas import resolve_role_name

    expected = resolve_role_name(role_id)
    assert expected, f"{role_id} 应能解析出显示名"

    for name, build in _builders().items():
        text = build(role_id)
        match = _ADDRESS_RE.search(text)
        assert match is not None, f"{name} 缺少「你（…）」称呼"
        assert match.group(1) == expected, (
            f"{name} 称呼应为 {expected!r}，实际 {match.group(1)!r}"
        )


def test_ling_farewell_first_line():
    """事故场景：活动切换告别的首行必须写「你（Ling）」。"""
    from core.services.character_daily.activity_return.instruction import (
        build_activity_start_farewell_instruction,
    )

    first_line = build_activity_start_farewell_instruction("ling", "studying").split("\n")[0]
    assert "你（Ling）" in first_line
    assert "你（ling）" not in first_line


def test_unknown_role_falls_back_to_raw_id():
    """未知 role_id 退回原值，不抛异常、不丢称呼。"""
    from core.services.dual_role.personas import resolve_role_name

    assert resolve_role_name("nobody") == "nobody"
    assert resolve_role_name("") == ""

    for name, build in _builders().items():
        text = build("nobody")
        assert "你（nobody）" in text, f"{name} 未知角色兜底失败"


def test_no_role_id_placeholder_left_in_templates():
    """源码级防回归：这些文件里不许再出现「你（{role_id}）」。"""
    targets = [
        "core/services/character_daily/activity_return/instruction.py",
        "core/services/active_care/goodnight_proactive.py",
        "core/services/active_care/good_morning_proactive.py",
    ]
    for rel in targets:
        src = (_ROOT / rel).read_text(encoding="utf-8")
        assert "你（{role_id}）" not in src, f"{rel} 仍有「你（{{role_id}}）」占位符"
