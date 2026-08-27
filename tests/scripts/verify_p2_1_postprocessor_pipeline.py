"""P2-1 验证：postprocessor.py 拆分为 pipeline step

验证要点：
1. pipeline.py 存在且包含 step 类
2. 每个 step 只负责一个职责（职责分离）
3. PipelineState / PipelineDependencies 数据结构完整
4. run_pipeline 入口函数工作正常
5. ActiveCarePostprocessor.postprocess 委托给 run_pipeline
6. 行为与原实现一致（端到端测试）
7. ctx 模式和参数模式都能工作
8. 中止路径（empty / debug_context / dedup 失败）正确返回 None
"""
from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def test_pipeline_module_exists() -> list[str]:
    issues: list[str] = []
    _section("测试 1：pipeline.py 模块存在且可导入")

    try:
        from core.services.active_care.postprocess.pipeline import (
            PipelineStep,
            DEFAULT_STEPS,
        )
        _ok("pipeline.py 核心组件全部可导入")
    except ImportError as e:
        issues.append(f"pipeline.py 导入失败: {e}")
        return issues

    if not isinstance(DEFAULT_STEPS, list):
        issues.append("DEFAULT_STEPS 不是 list")
    elif len(DEFAULT_STEPS) < 10:
        issues.append(f"DEFAULT_STEPS 步骤数不足: {len(DEFAULT_STEPS)}（应 ≥ 10）")
    else:
        _ok(f"DEFAULT_STEPS 包含 {len(DEFAULT_STEPS)} 个步骤")

    # 验证所有 step 都是 PipelineStep 子类
    for step in DEFAULT_STEPS:
        if not isinstance(step, PipelineStep):
            issues.append(f"step {step} 不是 PipelineStep 实例")
            continue
        if not step.name or step.name == "base":
            issues.append(f"step {type(step).__name__} 缺少 name 属性")
    if not issues:
        _ok("所有 step 都是 PipelineStep 实例且具有 name")

    if not issues:
        _ok("pipeline.py 模块结构验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_step_responsibility_separation() -> list[str]:
    issues: list[str] = []
    _section("测试 2：每个 step 只负责一个职责")

    from core.services.active_care.postprocess.pipeline import DEFAULT_STEPS

    expected_steps = {
        "content_extraction",
        "reasoning_strip",
        "emoji_strip",
        "empty_after_strip_check",
        "debug_context_check",
        "language_rewrite",
        "semantic_dedup",
        "final_dedup_check",
        "partial_repetition",
        "sleep_sanitize",
        "leak_detection",
        "sleep_enforce",
        "final_empty_check",
        "message_type_adjust",
    }

    actual_names = {step.name for step in DEFAULT_STEPS}
    missing = expected_steps - actual_names
    extra = actual_names - expected_steps

    if missing:
        issues.append(f"缺少 step: {missing}")
    if extra:
        issues.append(f"多余 step: {extra}")
    if not missing and not extra:
        _ok(f"step 集合与预期完全一致（{len(expected_steps)} 个）")

    # 验证每个 step 的 run 方法签名
    # 注意：inspect.signature 在 bound method 上不会包含 self
    for step in DEFAULT_STEPS:
        sig = inspect.signature(step.run)
        params = list(sig.parameters.keys())
        # bound method：['state', 'ctx', 'deps']；unbound：['self', 'state', 'ctx', 'deps']
        expected_bound = ["state", "ctx", "deps"]
        expected_unbound = ["self", "state", "ctx", "deps"]
        if params != expected_bound and params != expected_unbound:
            issues.append(
                f"step {step.name} run 方法签名异常: {params}"
            )

    if not issues:
        _ok("所有 step run 方法签名一致 (self, state, ctx, deps)")
        _ok("职责分离验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_pipeline_state_fields() -> list[str]:
    issues: list[str] = []
    _section("测试 3：PipelineState / PipelineDependencies 字段完整")

    from core.services.active_care.postprocess.pipeline import (
        PipelineState,
        PipelineDependencies,
    )
    from dataclasses import fields

    state_fields = {f.name for f in fields(PipelineState)}
    required_state = {
        "final_text",
        "full_raw_text",
        "message_type",
        "llm_thought",
        "response",
        "aborted",
        "abort_reason",
        "skip_dedup",
        "dedup_scene",
    }
    missing_state = required_state - state_fields
    if missing_state:
        issues.append(f"PipelineState 缺少字段: {missing_state}")
    else:
        _ok(f"PipelineState 字段完整: {sorted(state_fields)}")

    deps_fields = {f.name for f in fields(PipelineDependencies)}
    required_deps = {
        "language_handler",
        "deduplicator",
        "sleep_sanitizer",
        "leak_detector",
        "postprocessor",
        "agent",
        "aveline_service",
    }
    missing_deps = required_deps - deps_fields
    if missing_deps:
        issues.append(f"PipelineDependencies 缺少字段: {missing_deps}")
    else:
        _ok(f"PipelineDependencies 字段完整: {sorted(deps_fields)}")

    if not issues:
        _ok("数据结构验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_postprocess_delegates_to_pipeline() -> list[str]:
    issues: list[str] = []
    _section("测试 4：ActiveCarePostprocessor.postprocess 委托给 run_pipeline")

    from core.services.active_care.postprocess.postprocessor import (
        ActiveCarePostprocessor,
        PostprocessContext,
    )

    src = inspect.getsource(ActiveCarePostprocessor.postprocess)
    if "run_pipeline" not in src:
        issues.append("postprocess 未调用 run_pipeline")
    else:
        _ok("postprocess 调用 run_pipeline")

    if "PipelineDependencies" not in src:
        issues.append("postprocess 未构造 PipelineDependencies")
    else:
        _ok("postprocess 构造 PipelineDependencies")

    # 验证 ctx 字段
    ctx_fields = {f.name for f in __import__("dataclasses").fields(PostprocessContext)}
    if "sys_prompt_type" not in ctx_fields:
        issues.append("PostprocessContext 缺少 sys_prompt_type 字段")
    else:
        _ok("PostprocessContext 包含 sys_prompt_type 字段")

    if not issues:
        _ok("委托验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_basic_postprocess_behavior_preserved() -> list[str]:
    issues: list[str] = []
    _section("测试 5：基本 postprocess 行为保持一致")

    from core.services.active_care.postprocess.postprocessor import (
        ActiveCarePostprocessor,
    )

    pp = ActiveCarePostprocessor()

    # 测试 5.1: 正常文本应通过
    response = {"content": "你好，今天天气不错。", "message_type": "text"}
    result = asyncio.run(
        pp.postprocess(
            response=response,
            agent=MagicMock(),
            aveline_service=MagicMock(),
            sys_prompt_type="proactive_chat",
            preferred_language="zh",
        )
    )
    if result is None:
        issues.append("正常文本被错误地中止")
    else:
        if "你好" not in result["content"]:
            issues.append(f"正常文本内容异常: {result}")
        else:
            _ok(f"正常文本通过: {result['content'][:30]}")

    # 测试 5.2: 空内容应中止
    response = {"content": "", "message_type": "text"}
    result = asyncio.run(
        pp.postprocess(
            response=response,
            agent=MagicMock(),
            aveline_service=MagicMock(),
            sys_prompt_type="proactive_chat",
            preferred_language="zh",
        )
    )
    if result is not None:
        issues.append(f"空内容未中止: {result}")
    else:
        _ok("空内容正确中止（返回 None）")

    # 测试 5.3: 仅推理段的内容应中止
    response = {"content": "<think>这是推理</think>", "message_type": "text"}
    result = asyncio.run(
        pp.postprocess(
            response=response,
            agent=MagicMock(),
            aveline_service=MagicMock(),
            sys_prompt_type="proactive_chat",
            preferred_language="zh",
        )
    )
    if result is not None:
        issues.append(f"仅推理段未中止: {result}")
    else:
        _ok("仅推理段正确中止（返回 None）")

    if not issues:
        _ok("基本行为保持一致")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_dedup_bypass_preserved() -> list[str]:
    issues: list[str] = []
    _section("测试 6：短句关怀类去重 bypass 保持一致")

    from core.services.active_care.postprocess.postprocessor import (
        ActiveCarePostprocessor,
    )

    pp = ActiveCarePostprocessor()
    pp._regenerate_non_repetitive_text = AsyncMock(return_value=None)

    # goodnight_proactive 即使与历史锚点重复也应发送
    response = {
        "content": "晚安，Master。我也要睡了，记得明天起来先吃饭。",
        "message_type": "text",
    }
    repeat_anchors = ["晚安，Master。我也要睡了，记得明天起来先吃饭。"]

    result = asyncio.run(
        pp.postprocess(
            response=response,
            agent=MagicMock(),
            aveline_service=MagicMock(),
            sys_prompt_type="goodnight_proactive",
            preferred_language="zh",
            repeat_anchors=repeat_anchors,
        )
    )
    if result is None:
        issues.append("goodnight_proactive 被错误地拦截")
    else:
        _ok(f"goodnight_proactive bypass 生效: {result['content'][:30]}")

    # 普通类型应被去重拦截
    response = {
        "content": "晚安，Master。我也要睡了，记得明天起来先吃饭。",
        "message_type": "text",
    }
    result = asyncio.run(
        pp.postprocess(
            response=response,
            agent=MagicMock(),
            aveline_service=MagicMock(),
            sys_prompt_type="proactive_chat",
            preferred_language="zh",
            repeat_anchors=repeat_anchors,
        )
    )
    if result is not None:
        issues.append(f"普通类型未被去重拦截: {result}")
    else:
        _ok("普通类型正确被去重拦截")

    if not issues:
        _ok("bypass 行为保持一致")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_ctx_mode_works() -> list[str]:
    issues: list[str] = []
    _section("测试 7：ctx 模式工作正常")

    from core.services.active_care.postprocess.postprocessor import (
        ActiveCarePostprocessor,
        PostprocessContext,
    )

    pp = ActiveCarePostprocessor()

    response = {"content": "你好。", "message_type": "text"}
    ctx = PostprocessContext(
        target_conversation_id="test_conv",
        preferred_language="zh",
        sys_prompt_type="proactive_chat",
    )

    result = asyncio.run(
        pp.postprocess(
            response=response,
            agent=MagicMock(),
            aveline_service=MagicMock(),
            ctx=ctx,
        )
    )
    if result is None:
        issues.append("ctx 模式返回 None（应通过）")
    else:
        _ok(f"ctx 模式工作正常: {result['content']}")

    # 验证 ctx 中的 sys_prompt_type 生效（goodnight 应 bypass）
    ctx = PostprocessContext(
        preferred_language="zh",
        sys_prompt_type="goodnight_proactive",
        repeat_anchors=["晚安，Master。"],
    )
    response = {"content": "晚安，Master。", "message_type": "text"}
    result = asyncio.run(
        pp.postprocess(
            response=response,
            agent=MagicMock(),
            aveline_service=MagicMock(),
            ctx=ctx,
        )
    )
    if result is None:
        issues.append("ctx.sys_prompt_type=goodnight_proactive 未生效")
    else:
        _ok(f"ctx.sys_prompt_type 生效: {result['content']}")

    if not issues:
        _ok("ctx 模式验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_message_type_adjust_preserved() -> list[str]:
    issues: list[str] = []
    _section("测试 8：睡眠会话消息类型降级保持一致")

    from core.services.active_care.postprocess.postprocessor import (
        ActiveCarePostprocessor,
    )

    pp = ActiveCarePostprocessor()

    # sleep_session_active + sleep_confirmed_by_silence + voice → text
    response = {"content": "嗯，继续睡吧。", "message_type": "voice"}
    result = asyncio.run(
        pp.postprocess(
            response=response,
            agent=MagicMock(),
            aveline_service=MagicMock(),
            sys_prompt_type="goodnight_proactive",
            preferred_language="zh",
            sleep_session_active=True,
            sleep_confirmed_by_silence=True,
        )
    )
    if result is None:
        issues.append("消息类型降级测试返回 None")
    elif result["message_type"] != "text":
        issues.append(
            f"voice 未降级为 text: {result['message_type']}"
        )
    else:
        _ok(f"voice 正确降级为 text: {result['message_type']}")

    # 不在睡眠会话中，voice 保持
    response = {"content": "嗯，继续睡吧。", "message_type": "voice"}
    result = asyncio.run(
        pp.postprocess(
            response=response,
            agent=MagicMock(),
            aveline_service=MagicMock(),
            sys_prompt_type="goodnight_proactive",
            preferred_language="zh",
            sleep_session_active=False,
            sleep_confirmed_by_silence=False,
        )
    )
    if result is None:
        issues.append("非睡眠会话测试返回 None")
    elif result["message_type"] != "voice":
        issues.append(
            f"非睡眠会话 voice 不应降级: {result['message_type']}"
        )
    else:
        _ok(f"非睡眠会话 voice 保持: {result['message_type']}")

    if not issues:
        _ok("消息类型降级验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_step_isolation() -> list[str]:
    issues: list[str] = []
    _section("测试 9：step 独立可调用（可单元测试）")

    from core.services.active_care.postprocess.pipeline import (
        PipelineState,
        ContentExtractionStep,
        ReasoningStripStep,
        EmptyAfterStripCheckStep,
    )

    # ContentExtractionStep 单独运行
    step = ContentExtractionStep()
    state = PipelineState(response={"content": "hello", "message_type": "text"})
    asyncio.run(step.run(state, ctx=MagicMock(), deps=MagicMock()))
    if state.final_text != "hello":
        issues.append(f"ContentExtractionStep 设置 final_text 异常: {state.final_text}")
    else:
        _ok(f"ContentExtractionStep 独立运行: final_text={state.final_text!r}")

    # ReasoningStripStep 单独运行
    step = ReasoningStripStep()
    state = PipelineState(final_text="<think>推理</think>实际内容", response={})
    asyncio.run(step.run(state, ctx=MagicMock(), deps=MagicMock()))
    if "think" in state.final_text:
        issues.append(f"ReasoningStripStep 未剥离 think: {state.final_text}")
    else:
        _ok(f"ReasoningStripStep 独立运行: final_text={state.final_text!r}")

    # EmptyAfterStripCheckStep 单独运行
    step = EmptyAfterStripCheckStep()
    state = PipelineState(final_text="   ", response={})
    asyncio.run(step.run(state, ctx=MagicMock(), deps=MagicMock()))
    if not state.aborted:
        issues.append("EmptyAfterStripCheckStep 未设置 aborted")
    else:
        _ok(f"EmptyAfterStripCheckStep 独立运行: aborted={state.aborted}, reason={state.abort_reason}")

    if not issues:
        _ok("step 独立性验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def test_no_long_method_in_postprocessor() -> list[str]:
    issues: list[str] = []
    _section("测试 10：postprocess 方法不再是长方法")

    from core.services.active_care.postprocess.postprocessor import (
        ActiveCarePostprocessor,
    )

    src = inspect.getsource(ActiveCarePostprocessor.postprocess)
    line_count = len(src.split("\n"))
    if line_count > 80:
        issues.append(f"postprocess 方法仍过长: {line_count} 行（应 ≤ 80）")
    else:
        _ok(f"postprocess 方法长度合理: {line_count} 行")

    # 验证不再包含具体处理逻辑（应委托给 pipeline）
    forbidden_patterns = [
        "strip_reasoning_segments(final_text)",
        "_strip_emoji_markers(final_text)",
        "is_semantically_repetitive(",
        "sanitize_sleep_time_claims(",
        "looks_like_prompt_or_reasoning_dump(",
    ]
    for pattern in forbidden_patterns:
        if pattern in src:
            issues.append(f"postprocess 仍包含具体处理逻辑: {pattern}")

    if not issues:
        _ok("长方法已拆分，postprocess 仅负责委托")
        _ok("长方法拆分验证通过")
    else:
        for it in issues:
            _fail(it)
    return issues


def main() -> int:
    print("\n" + "=" * 60)
    print("P2-1 验证：postprocessor.py 拆分为 pipeline step")
    print("=" * 60)

    all_issues: list[str] = []

    all_issues.extend(test_pipeline_module_exists())
    all_issues.extend(test_step_responsibility_separation())
    all_issues.extend(test_pipeline_state_fields())
    all_issues.extend(test_postprocess_delegates_to_pipeline())
    all_issues.extend(test_basic_postprocess_behavior_preserved())
    all_issues.extend(test_dedup_bypass_preserved())
    all_issues.extend(test_ctx_mode_works())
    all_issues.extend(test_message_type_adjust_preserved())
    all_issues.extend(test_step_isolation())
    all_issues.extend(test_no_long_method_in_postprocessor())

    print("\n" + "=" * 60)
    if all_issues:
        print(f"❌ 验证失败：发现 {len(all_issues)} 个问题")
        for issue in all_issues:
            print(f"  - {issue}")
        return 1
    else:
        print("✅ 所有验证通过！P2-1 pipeline 拆分完整且正确。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
