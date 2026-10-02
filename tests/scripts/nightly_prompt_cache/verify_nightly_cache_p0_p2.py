"""验证 nightly 全链路 prompt cache 改造（P0 可观测 / P1 路由 / P2 prompt 结构）。

背景：
- nightly 全部场景已切到 `cloud:minimax:MiniMax-M3`。MiniMax 是被动前缀缓存
  （输入 ≥512 token 自动生效，匹配顺序 tools → system → user，缓存块粒度 128 token），
  但流式默认不返回 usage，且只回 `prompt_tokens_details.cached_tokens`。
- 改造前因此出现两个盲区：流式调用没有 usage 可统计；有 usage 时 miss 恒为 0，
  命中率被算成 100%（实测 128/4287 却显示 S 级）。

本脚本不发送真实 LLM 请求，只做静态与打桩验证：
P0a  MiniMax 流式 payload 带 stream_options.include_usage
P0b  MiniMax 只有 cached_tokens 时用 prompt_tokens 反推 miss，不再假报 100%
P1   偏好语义合并 / LLM 日记走 model_path，不再因 model_hint 被丢弃掉回默认 provider
P2a  学习总结 / 月报 / 月度蒸馏拆成 system + user 双段，旧单串常量 .format 仍可用
P2b  人物提取 user 段「已有档案」前置、蒸馏批量 user 段条数后置

运行：
    venv_core\\Scripts\\python.exe -m tests.scripts.nightly_prompt_cache.verify_nightly_cache_p0_p2
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

_passed = 0
_failed = 0


def check(name: str, ok: bool, err: str = "") -> None:
    global _passed, _failed
    if ok:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed += 1
        print(f"  [FAIL] {name} {err}")


# ─────────────────────────────────────────────────────────
# P0a：MiniMax 流式 usage
# ─────────────────────────────────────────────────────────

def test_minimax_stream_requests_usage() -> None:
    """MiniMax 流式必须显式开启 include_usage，否则拿不到缓存统计。"""
    from core.llm.openai_compat.minimax_client import MiniMaxClient

    client = MiniMaxClient(api_key="test-key")
    stream_payload = client._build_payload(
        [{"role": "user", "content": "你好"}],
        stream=True,
        temperature=0.3,
        max_tokens=128,
    )
    check(
        "流式带 stream_options.include_usage",
        stream_payload.get("stream_options") == {"include_usage": True},
        f"stream_options={stream_payload.get('stream_options')}",
    )
    check("MiniMax payload 仍带 reasoning_split", stream_payload.get("reasoning_split") is True)

    sync_payload = client._build_payload(
        [{"role": "user", "content": "你好"}],
        stream=False,
        temperature=0.3,
    )
    check(
        "非流式不加 stream_options",
        "stream_options" not in sync_payload,
        f"payload keys={sorted(sync_payload)}",
    )


# ─────────────────────────────────────────────────────────
# P0b：命中率统计口径
# ─────────────────────────────────────────────────────────

def _log_one_usage(usage: dict) -> dict:
    """调用 log_prompt_cache_usage 一次，返回写入的 JSONL 记录（日志落在临时目录）。"""
    from core.llm import llm_logger

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "prompt_cache_stats.log"
        original = llm_logger._prompt_cache_stats_log
        llm_logger._prompt_cache_stats_log = target
        try:
            llm_logger.log_prompt_cache_usage(
                provider="openai_compat",
                model="MiniMax-M3",
                usage=usage,
                extra={"mode": "stream"},
                source="verify::test",
            )
            lines = target.read_text(encoding="utf-8").strip().splitlines()
        finally:
            llm_logger._prompt_cache_stats_log = original
    return json.loads(lines[-1])


def test_minimax_miss_is_inferred_from_prompt_tokens() -> None:
    """MiniMax 只回 cached_tokens 时，miss 由 prompt_tokens 反推（修复前恒为 0 → 假 100%）。"""
    record = _log_one_usage(
        {
            "prompt_tokens": 4287,
            "completion_tokens": 300,
            "prompt_tokens_details": {"cached_tokens": 128},
        }
    )
    check("hit=128", record["hit_tokens"] == 128, f"hit={record['hit_tokens']}")
    check(
        "miss=prompt_tokens-hit",
        record["miss_tokens"] == 4287 - 128,
        f"miss={record['miss_tokens']}",
    )
    check(
        "命中率约 3% 而非 100%",
        record["hit_rate"] is not None and record["hit_rate"] < 0.05,
        f"hit_rate={record['hit_rate']}",
    )
    check("等级为 D（很低）", record["level"] == "D", f"level={record['level']}")


def test_deepseek_usage_fields_still_work() -> None:
    """DeepSeek 的 hit/miss 双字段不受影响（回归）。"""
    record = _log_one_usage(
        {
            "prompt_tokens": 5396,
            "prompt_cache_hit_tokens": 3584,
            "prompt_cache_miss_tokens": 1812,
        }
    )
    check("hit=3584", record["hit_tokens"] == 3584)
    check("miss=1812", record["miss_tokens"] == 1812)
    check(
        "命中率约 66%",
        0.6 < (record["hit_rate"] or 0) < 0.7,
        f"hit_rate={record['hit_rate']}",
    )


# ─────────────────────────────────────────────────────────
# P1：model_hint → model_path 路由修复
# ─────────────────────────────────────────────────────────

def test_preference_merge_uses_model_path() -> None:
    """偏好语义合并必须传 model_path，否则 LLM 层静默丢弃、掉回默认 provider。"""
    from core.services.self_improvement.core_memory_llm_merge import llm_merge_preferences

    llm = MagicMock()
    llm.chat = AsyncMock(return_value={"status": "success", "response": '{"merge_groups": []}'})

    with patch("core.llm.get_llm_module", return_value=llm):
        asyncio.run(
            llm_merge_preferences(
                ["用户喜欢猫", "用户爱猫"], model_hint="cloud:minimax:MiniMax-M3"
            )
        )

    check("llm.chat 被调用", llm.chat.await_count == 1)
    kwargs = llm.chat.await_args.kwargs if llm.chat.await_args else {}
    check(
        "传 model_path",
        kwargs.get("model_path") == "cloud:minimax:MiniMax-M3",
        f"model_path={kwargs.get('model_path')!r}",
    )
    check("不再传失效的 model_hint", "model_hint" not in kwargs)


def test_llm_diary_uses_model_path() -> None:
    """LLM 日记（journal/persona_exports）同样是 model_path。"""
    source = (
        Path(__file__).resolve().parents[3]
        / "core"
        / "services"
        / "journal"
        / "persona_exports.py"
    ).read_text(encoding="utf-8")
    check(
        "persona_exports 用 model_path 调 llm.chat",
        "model_path=journal_model_hint" in source,
    )
    check("persona_exports 不再用 model_hint 调 llm.chat", "model_hint=journal_model_hint" not in source)


# ─────────────────────────────────────────────────────────
# P2a：三个单串 prompt 拆双段
# ─────────────────────────────────────────────────────────

def test_new_prompt_constants_are_double_segment() -> None:
    """学习总结 / 月报 / 月度蒸馏都有固定 system + 动态 user 两段。"""
    from core.agents.chat_agent_components.persona_system.prompt.components import (
        JOURNAL_MEMORY_DISTILL_SYSTEM_PROMPT,
        JOURNAL_MEMORY_DISTILL_USER_PROMPT_TEMPLATE,
        JOURNAL_MONTHLY_SUMMARY_SYSTEM_PROMPT,
        JOURNAL_MONTHLY_SUMMARY_USER_PROMPT_TEMPLATE,
        STUDY_DAILY_SUMMARY_SYSTEM_PROMPT,
        STUDY_DAILY_SUMMARY_USER_PROMPT_TEMPLATE,
    )

    cases: List[Tuple[str, str, str, str]] = [
        ("学习总结", STUDY_DAILY_SUMMARY_SYSTEM_PROMPT, STUDY_DAILY_SUMMARY_USER_PROMPT_TEMPLATE, "{study_chat_context}"),
        ("月报", JOURNAL_MONTHLY_SUMMARY_SYSTEM_PROMPT, JOURNAL_MONTHLY_SUMMARY_USER_PROMPT_TEMPLATE, "{full_context}"),
        ("月度蒸馏", JOURNAL_MEMORY_DISTILL_SYSTEM_PROMPT, JOURNAL_MEMORY_DISTILL_USER_PROMPT_TEMPLATE, "{monthly_summary_json}"),
    ]
    dynamic_placeholders = (
        "{date_str}",
        "{month_str}",
        "{total_days}",
        "{full_context}",
        "{monthly_summary_json}",
        "{study_chat_context}",
        "{study_stats_context}",
        "{student_profile}",
    )
    for label, system_prompt, user_template, placeholder in cases:
        check(f"{label} system 段非空", bool(system_prompt.strip()))
        check(
            f"{label} system 段无动态占位符",
            not any(p in system_prompt for p in dynamic_placeholders),
        )
        check(f"{label} user 段含 {placeholder}", placeholder in user_template)


def test_legacy_single_string_templates_still_format() -> None:
    """旧单串常量仍可 .format（system 段花括号已转义，不会 KeyError）。"""
    from core.agents.chat_agent_components.persona_system.prompt.components import (
        JOURNAL_MEMORY_DISTILL_PROMPT_TEMPLATE,
        JOURNAL_MONTHLY_SUMMARY_PROMPT_TEMPLATE,
        STUDY_DAILY_SUMMARY_PROMPT_TEMPLATE,
    )

    study = STUDY_DAILY_SUMMARY_PROMPT_TEMPLATE.format(
        date_str="2026-09-11",
        study_chat_context="聊了定语从句",
        study_stats_context="{}",
        student_profile="视觉型学习者",
    )
    check("学习总结旧模板可用", "定语从句" in study and '"date"' in study)

    monthly = JOURNAL_MONTHLY_SUMMARY_PROMPT_TEMPLATE.format(
        month_str="2026-08", full_context="8 月记录", total_days=31
    )
    check("月报旧模板可用", "8 月记录" in monthly and '"month"' in monthly)

    distill = JOURNAL_MEMORY_DISTILL_PROMPT_TEMPLATE.format(monthly_summary_json="{}")
    check("月度蒸馏旧模板可用", "认知心理学家" in distill)


# ─────────────────────────────────────────────────────────
# P2b：稳定块前置 / 动态块后置
# ─────────────────────────────────────────────────────────

def test_people_prompt_puts_stable_profiles_first() -> None:
    """人物提取：已有档案（同晚每批相同）必须在对话内容之前。"""
    from core.character.people.extractor import PeopleProfileExtractor

    extractor = PeopleProfileExtractor()
    first = extractor._build_prompt("本批对话 A" * 20, "张三；李四")[1]["content"]
    second = extractor._build_prompt("本批对话 B" * 20, "张三；李四")[1]["content"]

    check(
        "已有档案在对话内容之前",
        first.find("张三；李四") < first.find("本批对话 A"),
        f"profiles@{first.find('张三；李四')} content@{first.find('本批对话 A')}",
    )
    marker = "## 本批对话内容"
    check(
        "两批的档案前缀逐字一致（可命中缓存）",
        first[: first.find(marker)] == second[: second.find(marker)],
    )


def test_batch_distillation_count_goes_last() -> None:
    """蒸馏批量 user：条数放到末尾，开头保持稳定前缀。"""
    from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
        MEMORY_DISTILLATION_BATCH_USER_TEMPLATE,
    )

    rendered = MEMORY_DISTILLATION_BATCH_USER_TEMPLATE.format(count=10, items="【条目1】内容")
    check("开头是固定引导语", rendered.startswith("对话内容列表："), rendered[:20])
    check("条数在末尾", rendered.rstrip().endswith("（共 10 条）"))
    check("{count} 不在开头 20 字符内", "{count}" not in rendered[:20])


def main() -> int:
    print("=" * 70)
    print("Nightly prompt cache 改造验证（P0 可观测 / P1 路由 / P2 prompt 结构）")
    print("=" * 70)

    print("\n▶ P0a MiniMax 流式 usage")
    test_minimax_stream_requests_usage()

    print("\n▶ P0b 命中率统计口径")
    test_minimax_miss_is_inferred_from_prompt_tokens()
    test_deepseek_usage_fields_still_work()

    print("\n▶ P1 model_hint → model_path")
    test_preference_merge_uses_model_path()
    test_llm_diary_uses_model_path()

    print("\n▶ P2a 单串 prompt 拆双段")
    test_new_prompt_constants_are_double_segment()
    test_legacy_single_string_templates_still_format()

    print("\n▶ P2b 稳定块前置 / 动态块后置")
    test_people_prompt_puts_stable_profiles_first()
    test_batch_distillation_count_goes_last()

    print("\n" + "=" * 70)
    print(f"结果: {_passed} passed, {_failed} failed")
    print("=" * 70)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
