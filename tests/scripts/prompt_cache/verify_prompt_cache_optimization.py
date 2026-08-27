#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 Prompt 缓存优化（P0 + P1）改动是否成功。

背景（2026-08-16）：用户反馈 prompt cache 命中率太低，参考 AI IDE 的缓存工程经验做了三处改动：
- P0：缓存命中率统计 + 分级（S/A/B/C/D），数据源与 DeepSeek 开放平台同源
  （usage.prompt_cache_hit_tokens / prompt_cache_miss_tokens）
- P1a：模式提示（学习模式等）从 system 静态部分移到 user 前缀的 <system-reminder>，
  保证 system 跨模式字节级一致，进/出模式不再让整段前缀失效
- P1b：tools schema 注册后缓存复用，保证 tools 参数字节级稳定（参与缓存键匹配）

本脚本不发送真实 LLM 请求，仅做结构与行为验证：
1. classify_cache_hit_rate 分级边界（S>=90 / A>=70 / B>=50 / C>=20 / D<20 / N/A）
2. log_prompt_cache_usage 写入 logs JSONL 且分级正确（含兜底 prompt_tokens_details）
3. 流式结束块 usage 提取（stream_parser）与非流式 _attach_usage
4. registry.get_openai_tools 缓存：同集合字节级一致、enable/disable 失效重建、
   同 include_names 不同 exclude_categories 不串缓存
5. assembler：模式提示在 dynamic_part（<system-reminder>）而非 static_part，
   且 system 跨不同模式状态保持字节级一致

运行：
    venv_core\\Scripts\\python.exe tests/scripts/prompt_cache/verify_prompt_cache_optimization.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import types
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

# 添加项目根目录到 path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# 1. 缓存命中率分级边界
# ============================================================

def test_classify_cache_hit_rate_levels() -> None:
    """S>=90 / A>=70 / B>=50 / C>=20 / D<20，无数据返回 N/A"""
    from core.llm.llm_logger import classify_cache_hit_rate

    cases = [
        # (hit, miss, expected_level, expected_rate)
        (9, 1, "S", 0.9),     # 90% 边界 → S
        (90, 10, "S", 0.9),   # 90% → S
        (70, 30, "A", 0.7),   # 70% 边界 → A
        (69, 31, "B", 0.69),  # 69% → B
        (50, 50, "B", 0.5),   # 50% 边界 → B
        (49, 51, "C", 0.49),  # 49% → C
        (20, 80, "C", 0.2),   # 20% 边界 → C
        (19, 81, "D", 0.19),  # 19% → D（低于 20% 视为很低）
        (1, 9, "D", 0.1),     # 10% → D
        (0, 0, "N/A", None),  # 无数据 → N/A
    ]
    for hit, miss, lv, rate in cases:
        r, code, name = classify_cache_hit_rate(hit, miss)
        assert code == lv, f"hit={hit} miss={miss} 应为 {lv}，实际 {code}"
        if rate is None:
            assert r is None and name == "无数据"
        else:
            assert abs(r - rate) < 1e-9, f"hit={hit} miss={miss} 命中率应为 {rate}，实际 {r}"
    print(f"[OK] classify_cache_hit_rate 分级边界 {len(cases)} 项全部正确")


# ============================================================
# 2. log_prompt_cache_usage 落盘与分级
# ============================================================

def _read_last_record(log_path: Path) -> dict:
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert lines, "prompt_cache_stats.log 不应为空"
    return json.loads(lines[-1])


def test_log_prompt_cache_usage_primary() -> None:
    """主字段 prompt_cache_hit_tokens/miss_tokens → 分级 A，extra 透传"""
    from core.llm import llm_logger

    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "prompt_cache_stats.log"
        with patch.object(llm_logger, "_prompt_cache_stats_log", log_path):
            llm_logger.log_prompt_cache_usage(
                "openai_compat", "deepseek-chat",
                {"prompt_cache_hit_tokens": 800, "prompt_cache_miss_tokens": 200},
                extra={"mode": "sync"},
            )
        rec = _read_last_record(log_path)
        assert rec["hit_rate"] == 0.8, rec
        assert rec["level"] == "A" and rec["level_name"] == "良好", rec
        assert rec["provider"] == "openai_compat"
        assert rec["model"] == "deepseek-chat"
        assert rec["hit_tokens"] == 800 and rec["miss_tokens"] == 200
        assert rec["mode"] == "sync"
        assert rec["timestamp"]
    print("[OK] log_prompt_cache_usage 主字段记录并分级（A/良好）")


def test_log_prompt_cache_usage_fallback() -> None:
    """兜底 prompt_tokens_details.cached_tokens/uncached_tokens → 分级 B"""
    from core.llm import llm_logger

    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "prompt_cache_stats.log"
        with patch.object(llm_logger, "_prompt_cache_stats_log", log_path):
            llm_logger.log_prompt_cache_usage(
                "openai_compat", "m",
                {"prompt_tokens_details": {"cached_tokens": 50, "uncached_tokens": 50}},
            )
        rec = _read_last_record(log_path)
        assert rec["hit_rate"] == 0.5 and rec["level"] == "B", rec
    print("[OK] log_prompt_cache_usage 兜底 prompt_tokens_details 分级正确（B/一般）")


def test_log_prompt_cache_usage_no_data() -> None:
    """空 usage → hit_rate None / N/A；usage 为 None → 不写文件"""
    from core.llm import llm_logger

    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "prompt_cache_stats.log"
        with patch.object(llm_logger, "_prompt_cache_stats_log", log_path):
            llm_logger.log_prompt_cache_usage("p", "m", {})
            rec = _read_last_record(log_path)
            assert rec["hit_rate"] is None and rec["level"] == "N/A", rec

        log_path2 = Path(td) / "prompt_cache_stats2.log"
        with patch.object(llm_logger, "_prompt_cache_stats_log", log_path2):
            llm_logger.log_prompt_cache_usage("p", "m", None)
            assert not log_path2.exists(), "usage 为 None 时不应写文件"
    print("[OK] log_prompt_cache_usage 无数据场景正确（N/A / 不写文件）")


# ============================================================
# 3. usage 提取链路（流式结束块 + 非流式 _attach_usage）
# ============================================================

class _FakeContent:
    """模拟 aiohttp 流式响应内容"""

    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_any(self):
        for c in self._chunks:
            yield c


def test_stream_parser_extracts_usage() -> None:
    """流式结束块（无 choices 只带 usage）应被提取为 usage 块"""
    from core.llm.openai_compat.stream_parser import (
        _extract_sse_content,
        parse_sse_stream,
    )

    usage = {"prompt_cache_hit_tokens": 100, "prompt_cache_miss_tokens": 50}
    parsed, new_mode = _extract_sse_content({"choices": [], "usage": usage}, False)
    assert parsed == {"type": "usage", "data": usage}
    assert new_mode is False

    async def _collect():
        items = []
        async for chunk in parse_sse_stream(
            _FakeContent([
                b'data: {"choices": [], "usage": {"prompt_cache_hit_tokens": 100, '
                b'"prompt_cache_miss_tokens": 50}}\n\n',
                b"data: [DONE]\n\n",
            ])
        ):
            items.append(chunk)
        return items

    items = asyncio.run(_collect())
    assert items == [{"usage": usage}], items
    print("[OK] 流式结束块 usage 提取链路正确（_extract_sse_content + parse_sse_stream）")


def test_stream_parser_content_unaffected() -> None:
    """普通 content 块不受 usage 提取影响（choices 存在时走正常分支）"""
    from core.llm.openai_compat.stream_parser import _extract_sse_content

    data = {"choices": [{"delta": {"content": "你好"}}], "usage": {"prompt_cache_hit_tokens": 1}}
    parsed, _ = _extract_sse_content(data, False)
    assert parsed == {"type": "content", "data": "你好"}
    print("[OK] 带 usage 的普通 content 块仍走内容分支")


def test_attach_usage() -> None:
    """非流式响应 _attach_usage：有 usage 附加、无 usage 原样返回、非 dict 不崩"""
    from core.llm.openai_compat.response_parser import _attach_usage

    r = _attach_usage({"content": "hi"}, {"usage": {"prompt_cache_hit_tokens": 5}})
    assert r["usage"] == {"prompt_cache_hit_tokens": 5}

    r2 = _attach_usage({"content": "hi"}, {"other": 1})
    assert "usage" not in r2

    r3 = _attach_usage({"content": "hi"}, "not-a-dict")
    assert "usage" not in r3
    print("[OK] _attach_usage 附加/透传/容错正确")


# ============================================================
# 4. tools schema 缓存
# ============================================================

def _make_registry() -> tuple:
    """构造带 3 个假工具的注册表（分属不同 category），返回 (registry, names)"""
    from pydantic import BaseModel, Field

    from core.tools.base import BaseTool
    from core.tools.registry import ToolRegistry

    class _ArgsA(BaseModel):
        query: str = Field(description="查询内容")

    class _FakeTool(BaseTool):
        def __init__(self, name, description, category, args_schema=None):
            self.name = name
            self.description = description
            self.short_description = None
            self.category = category
            self.args_schema = args_schema
            self.enabled_by_default = True

        async def _run(self, *args, **kwargs):
            return "ok"

    registry = ToolRegistry()
    registry.register(_FakeTool("tool_a", "工具A：搜索", "cat_x", args_schema=_ArgsA))
    registry.register(_FakeTool("tool_b", "工具B：天气", "cat_y"))
    registry.register(_FakeTool("tool_c", "工具C：翻译", "cat_z"))
    return registry


def _stable(registry, **kwargs) -> str:
    """序列化 get_openai_tools 结果，用于字节级对比"""
    return json.dumps(registry.get_openai_tools(**kwargs), ensure_ascii=False)


def test_registry_cache_byte_stable() -> None:
    """同集合重复调用字节级一致；集合顺序无关；不同集合内容不同"""
    registry = _make_registry()

    all1 = _stable(registry)
    all2 = _stable(registry)
    assert all1 == all2, "全量 tools 两次调用必须字节级一致（参与缓存键匹配）"

    sub1 = _stable(registry, include_names=["tool_a", "tool_b"])
    sub2 = _stable(registry, include_names=["tool_b", "tool_a"])
    assert sub1 == sub2, "同集合不同顺序必须一致"

    sub_a = _stable(registry, include_names=["tool_a"])
    assert sub_a != sub1, "不同工具集合内容必须不同"
    assert "工具A" in sub_a and "工具B" not in sub_a
    print("[OK] registry tools 缓存字节级稳定（同集合一致、异集合不同）")


def test_registry_cache_invalidate_on_toggle() -> None:
    """enable/disable 后缓存失效重建，恢复后回到原内容"""
    registry = _make_registry()

    before = _stable(registry)
    registry.disable_tool("tool_b")
    after_disable = _stable(registry)
    assert "工具B" not in after_disable and before != after_disable, \
        "disable 后 tools 应剔除且与之前不同"

    registry.enable_tool("tool_b")
    after_enable = _stable(registry)
    assert after_enable == before, "enable 恢复后应回到原始字节内容"
    print("[OK] registry tools 缓存随 enable/disable 正确失效重建")


def test_registry_cache_key_includes_exclude() -> None:
    """同 include_names 不同 exclude_categories 不得串缓存（缓存键加固）"""
    registry = _make_registry()

    x1 = _stable(registry, include_names=["tool_a", "tool_b"], exclude_categories=["cat_x"])
    x2 = _stable(registry, include_names=["tool_a", "tool_b"], exclude_categories=["cat_y"])
    assert "工具A" not in x1 and "工具B" in x1, x1[:200]
    assert "工具A" in x2 and "工具B" not in x2, x2[:200]
    assert x1 != x2, "不同 exclude_categories 必须返回不同结果"
    print("[OK] registry tools 缓存键包含 exclude_categories，不串缓存")


# ============================================================
# 5. assembler：模式提示移到 user 前缀（P1a）
# ============================================================

def _stub_prompt_data() -> SimpleNamespace:
    """构造 get_prompt_data 的最小桩数据"""
    return SimpleNamespace(
        base_template="【角色设定】静态人设模板 v1\n一些固定的性格描述",
        dialogue_injection="",
        is_qq_source=False,
        resolved_user_name="测试用户",
        last_conversation_seconds=3600,
        emotion_data=("平静", 0.5, 0.8, {}),
        persona_filename="Aveline_QQ_Master.json",
        life_sim_state={},
        life_stats={},
        cpu_temp=40,
        ram_usage=0.5,
        persona_name="Aveline",
        mode="normal",
        is_sensitive_mode=False,
        persona_data={},
    )


def _patch_assembler_deps(study_return=None):
    """统一打桩 assembler 的数据与上下文依赖，返回一个上下文管理器"""
    import core.agents.chat_agent_components.persona_system.prompt.assembler as assembler

    # 屏蔽 self-improvement 配置加载，避免真实 settings 初始化（本测试不关心）
    fake_cfg = types.ModuleType("config.integrated_config")
    fake_cfg.get_settings = Mock(return_value=SimpleNamespace(
        self_improvement=SimpleNamespace(
            enabled=False, prompt_injection=False, correction_detection=False,
            learning_log=False, core_memory=False, drift_guard=False,
        ),
    ))
    stack = ExitStack()
    stack.enter_context(patch.dict(sys.modules, {"config.integrated_config": fake_cfg}))
    stack.enter_context(patch.multiple(
        assembler,
        get_prompt_data=Mock(return_value=_stub_prompt_data()),
        is_bionic_character=Mock(return_value=False),
        build_time_context=Mock(return_value=""),
        build_emotion_context=Mock(return_value=""),
        build_food_context=Mock(return_value=""),
        build_study_context=Mock(return_value=""),
        build_mentioned_people_injection=Mock(return_value=""),
        get_special_day_prompt=Mock(return_value=None),
        get_upcoming_birthday_prompt=Mock(return_value=None),
        filter_tool_names=Mock(return_value=[]),
        get_tool_injection=Mock(return_value=""),
        finalize_and_clean_prompt=Mock(side_effect=lambda x, **kw: x),
    ))
    stack.enter_context(patch(
        "core.tools.study_mode_tool.get_study_prompt_for_injection",
        return_value=study_return,
    ))
    return stack


def test_assembler_mode_prompt_in_dynamic_part() -> None:
    """学习模式提示应出现在 dynamic_part（<system-reminder>），不在 static_part"""
    from core.agents.chat_agent_components.persona_system.prompt import assembler

    study_prompt = "【学习模式已激活】\n专注学习指引：先复习错题，再预习新内容"
    fake_agent = SimpleNamespace(tool_registry=None)

    with _patch_assembler_deps(study_return=study_prompt):
        static_part, dynamic_part = assembler.build_persona_prompt_split(
            agent=fake_agent, user_id="user_1"
        )

    assert study_prompt in dynamic_part, "学习模式提示必须在 dynamic_part"
    assert "<system-reminder>" in dynamic_part, "学习模式提示应以 system-reminder 包裹"
    assert study_prompt not in static_part, "学习模式提示不得进入 static_part（system 必须静态）"
    assert "【角色设定】" in static_part, "人设模板应留在 static_part"
    print("[OK] 模式提示在 dynamic_part 的 <system-reminder> 中，system 保持静态")


def test_assembler_system_stable_across_modes() -> None:
    """system 跨不同模式状态字节级一致 → 进/出模式不破坏缓存前缀"""
    from core.agents.chat_agent_components.persona_system.prompt import assembler

    fake_agent = SimpleNamespace(tool_registry=None)

    # 用户 A 处于学习模式（有注入），用户 B 未进入学习模式（无注入）
    with _patch_assembler_deps(study_return="【学习模式已激活】\n学习指引"):
        static_a, dynamic_a = assembler.build_persona_prompt_split(
            agent=fake_agent, user_id="user_a"
        )
    with _patch_assembler_deps(study_return=None):
        static_b, dynamic_b = assembler.build_persona_prompt_split(
            agent=fake_agent, user_id="user_b"
        )

    assert static_a == static_b, "system 部分必须跨模式字节级一致"
    assert "【学习模式已激活】" in dynamic_a
    assert "【学习模式已激活】" not in dynamic_b
    assert dynamic_a != dynamic_b
    print("[OK] system 跨模式字节级一致，动态差异只在 user 前缀（缓存安全）")


def test_deepseek_stream_options_injected() -> None:
    """DeepSeek 流式 payload 必须注入 stream_options.include_usage（否则拿不到 usage）"""
    from core.llm.openai_compat.deepseek_client import DeepSeekClient

    client = DeepSeekClient(api_key="test", model="deepseek-v4-flash", thinking_enabled=False)
    msgs = [{"role": "user", "content": "hi"}]
    p_stream = client._build_payload(msgs, stream=True)
    p_sync = client._build_payload(msgs, stream=False)

    assert p_stream.get("stream_options") == {"include_usage": True}, p_stream.get("stream_options")
    assert "stream_options" not in p_sync, "非流式不应带 stream_options"
    print("[OK] DeepSeek 流式 payload 注入 stream_options.include_usage，非流式不注入")


# ============================================================
# Main
# ============================================================

def main() -> int:
    print("=" * 72)
    print("Prompt 缓存优化验证（P0 统计分级 + P1 模式切换/tools 缓存）")
    print("=" * 72)

    tests = [
        test_classify_cache_hit_rate_levels,
        test_log_prompt_cache_usage_primary,
        test_log_prompt_cache_usage_fallback,
        test_log_prompt_cache_usage_no_data,
        test_stream_parser_extracts_usage,
        test_stream_parser_content_unaffected,
        test_attach_usage,
        test_registry_cache_byte_stable,
        test_registry_cache_invalidate_on_toggle,
        test_registry_cache_key_includes_exclude,
        test_assembler_mode_prompt_in_dynamic_part,
        test_assembler_system_stable_across_modes,
        test_deepseek_stream_options_injected,
    ]

    failed = 0
    for test in tests:
        print(f"\n▶ {test.__name__}")
        try:
            result = test()
            if asyncio.iscoroutine(result):
                asyncio.run(result)
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR] {type(e).__name__}: {e}")
            failed += 1

    print("\n" + "=" * 72)
    if failed:
        print(f"结果: {failed}/{len(tests)} 失败")
    else:
        print(f"结果: {len(tests)}/{len(tests)} 通过")
    print("=" * 72)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
