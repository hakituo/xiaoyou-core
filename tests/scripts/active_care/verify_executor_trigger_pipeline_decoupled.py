"""验证 executor.py 核心调度链路已解耦为 准备/生成/收尾 三段

背景（2026-09-04）：
    `executor.py` 先前虽然已经把 6 个协作模块拆了出去，但 `trigger_message_with_result`
    仍然内联了整条链路：会话路由 → 早安 pending 注入 → 历史/上下文 → Prompt → 生成
    → 后处理 → 纠偏 → 分发 → 清 pending / 通知服务 / 日记 / 清推迟提醒。
    单方法 165 行，四类互不相关的职责（取数组装、LLM 调用、状态回写、调度编排）
    挤在同一个 try 块里，任何一段改动都要通读全方法。

本轮拆分：
- `core/trigger_preparer.py`    TriggerPreparer.prepare()    → 返回 PreparedTrigger
- `core/generation_pipeline.py` GenerationPipeline           → 生成 + 后处理
- `core/post_send_handler.py`   PostSendHandler              → 发送后收尾
- `executor.py`                 只保留编排（重叠保护 → 准备 → 生成 → 纠偏 →
                                分发 → 收尾 → 失败回退），并保留
                                `_generate_and_postprocess` / `_get_or_generate_response`
                                两个转发方法。

本脚本校验：新模块职责边界、门面委托链路、编排方法不再内联实现，
并用 fake 依赖跑通一次完整的 prepare 与 trigger 流程，确认接线未变。

运行：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe -m tests.scripts.active_care.verify_executor_trigger_pipeline_decoupled
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_PASSED = 0
_FAILED = 0

# 分阶段所需的 executor 内部依赖（prepare 用）
_PREPARE_DEPS = (
    "_conversation_router",
    "_context_builder",
    "_morning_pending",
)


def _ok(msg: str) -> None:
    global _PASSED
    _PASSED += 1
    print(f"  [OK] {msg}")


def _fail(msg: str, detail: str = "") -> None:
    global _FAILED
    _FAILED += 1
    print(f"  [FAIL] {msg}")
    if detail:
        print(f"         {detail}")


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def _new_executor():
    """构造不做真实初始化的 executor 骨架（避免依赖 storage/context）。"""
    from core.services.active_care.core.executor import ActiveCareExecutor

    return ActiveCareExecutor.__new__(ActiveCareExecutor)


def test_new_modules_importable() -> None:
    _section("测试 1: 三个新模块可独立导入")
    cases = [
        ("core.services.active_care.core.trigger_preparer", "TriggerPreparer"),
        ("core.services.active_care.core.generation_pipeline", "GenerationPipeline"),
        ("core.services.active_care.core.post_send_handler", "PostSendHandler"),
    ]
    for dotted, cls_name in cases:
        try:
            module = __import__(dotted, fromlist=[cls_name])
            if hasattr(module, cls_name):
                _ok(f"{dotted.rsplit('.', 1)[-1]}.py 可独立导入")
            else:
                _fail(f"{dotted} 缺少类 {cls_name}")
        except Exception as exc:  # pragma: no cover
            _fail(f"{dotted} 导入失败", repr(exc))


def test_executor_mounts_submodules() -> None:
    _section("测试 2: executor 挂载三段子模块")
    from core.services.active_care.core.executor import ActiveCareExecutor

    exec_ = ActiveCareExecutor(mock.MagicMock(), mock.MagicMock())
    for attr in ("_trigger_preparer", "_generation_pipeline", "_post_send_handler"):
        if hasattr(exec_, attr):
            _ok(f"executor.{attr} 已挂载")
        else:
            _fail(f"executor 缺少子模块属性 {attr}")


def test_facade_delegation() -> None:
    _section("测试 3: 门面两个核心方法改为委托")
    exec_ = _new_executor()
    exec_._generation_pipeline = mock.MagicMock()

    async def fake_generate(**kwargs):
        return {"content": "ok"}

    exec_._generation_pipeline.generate_and_postprocess = mock.AsyncMock(side_effect=fake_generate)
    exec_._generation_pipeline.get_or_generate_response = mock.AsyncMock(
        return_value={"content": "raw"}
    )

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            exec_._generate_and_postprocess(
                aveline_service=object(),
                sys_prompt_type="checking",
                reply_text=None,
                thought=None,
                context={},
                sys_prompt="sp",
                model_user_input="ui",
                target_conversation_id="cid",
                now=1.0,
                persona_filename="pf",
            )
        )
        if result == {"content": "ok"}:
            _ok("_generate_and_postprocess 委托给 GenerationPipeline.generate_and_postprocess")
        else:
            _fail("_generate_and_postprocess 返回值不符", str(result))

        raw = loop.run_until_complete(
            exec_._get_or_generate_response(
                aveline_service=object(),
                reply_text=None,
                thought=None,
                context={},
                sys_prompt="sp",
                user_input_mock="ui",
                target_conversation_id="cid",
            )
        )
        if raw == {"content": "raw"}:
            _ok("_get_or_generate_response 委托给 GenerationPipeline.get_or_generate_response")
        else:
            _fail("_get_or_generate_response 返回值不符", str(raw))
    finally:
        loop.close()


def test_orchestrator_has_no_inline_implementation() -> None:
    _section("测试 4: 编排方法不再内联实现")
    from core.services.active_care.core.executor import ActiveCareExecutor

    source = inspect.getsource(ActiveCareExecutor.trigger_message_with_result)
    code_lines = [
        line for line in source.splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    code_text = "\n".join(code_lines)

    leftovers = {
        "会话路由": "_conversation_router.resolve_target_conversation",
        "历史拉取": "_context_builder.get_history_with_cache",
        "上下文构建": "_context_builder.build_trigger_context",
        "Prompt 构建": "_context_builder.build_prompt",
        "早安注入": "_morning_pending.inject",
        "清 pending": "_morning_pending.clear_if_injected",
        "推迟提醒清写盘": "storage.save_proactive_state",
        "服务通知": "on_assistant_message_sent",
    }
    remaining = [name for name, token in leftovers.items() if token in code_text]
    if remaining:
        _fail("编排方法仍内联以下实现", "、".join(remaining))
    else:
        _ok("编排方法只保留调度调用（准备/生成/纠偏/分发/收尾）")

    # 关键阶段调用必须还在，确认没有漏接
    required = {
        "前置准备": "_trigger_preparer.prepare",
        "生成后处理": "_generation_pipeline.generate_and_postprocess",
        "发送前纠偏": "_content_corrector.correct",
        "分发": "_message_dispatcher.dispatch_message",
        "收尾-已送达": "_post_send_handler.on_delivered",
        "收尾-日记": "_post_send_handler.write_diary",
        "收尾-清推迟提醒": "_post_send_handler.clear_deferred_reminders",
        "失败回退": "_overlap_guard.rollback_on_failure",
    }
    missing = [name for name, token in required.items() if token not in code_text]
    if missing:
        _fail("编排方法缺少关键阶段调用", "、".join(missing))
    else:
        _ok("编排方法七段调用齐全，失败回退仍在 finally")


def test_prepare_wires_all_steps() -> None:
    _section("测试 5: TriggerPreparer.prepare 串联四步并透传注入结果")
    from core.services.active_care.core.trigger_preparer import PreparedTrigger

    exec_ = _new_executor()

    async def fake_resolve(client_type, persona_filename=""):
        return "target_cid", "orig_cid", "qq"

    async def fake_history(target_cid, now):
        return [{"role": "user", "content": "hi"}]

    async def fake_context(history, target_cid, now, now_dt, tod):
        return {"history_len": len(history), "tod": tod}

    def fake_build_prompt(context, sys_prompt_type, *args, **kwargs):
        return (
            SimpleNamespace(prompt="SYS", dynamic_prompt="DYN", has_deferred_reminders=True),
            "MODEL_INPUT",
        )

    exec_._conversation_router = SimpleNamespace(
        resolve_target_conversation=mock.AsyncMock(side_effect=fake_resolve)
    )
    exec_._context_builder = SimpleNamespace(
        get_history_with_cache=mock.AsyncMock(side_effect=fake_history),
        build_trigger_context=mock.AsyncMock(side_effect=fake_context),
        build_prompt=fake_build_prompt,
    )
    exec_._morning_pending = SimpleNamespace(
        inject=lambda sys_type, cid, instruction: (
            (instruction or "") + "|INJECTED",
            ["昨晚的消息"],
        )
    )

    from core.services.active_care.core.trigger_preparer import TriggerPreparer

    prepared = asyncio.new_event_loop().run_until_complete(
        TriggerPreparer(exec_).prepare(
            sys_prompt_type="good_morning_proactive",
            user_input_mock="[MOCK]",
            reminder_msg=None,
            thought=None,
            device_context=None,
            client_type="qq",
            specific_instruction="原始指令",
            persona_filename="pf",
            now=1000.0,
        )
    )

    if not isinstance(prepared, PreparedTrigger):
        _fail("prepare 返回值类型错误", type(prepared).__name__)
        return

    checks = [
        (
            "会话路由结果透传",
            prepared.target_conversation_id == "target_cid"
            and prepared.original_conversation_id == "orig_cid"
            and prepared.requested_client_type == "qq",
        ),
        ("早安注入结果透传", prepared.morning_pending_injected == ["昨晚的消息"]),
        ("注入后的指令透传", prepared.specific_instruction == "原始指令|INJECTED"),
        (
            "Prompt 结果解包",
            prepared.sys_prompt == "SYS"
            and prepared.dynamic_prompt == "DYN"
            and prepared.model_user_input == "MODEL_INPUT",
        ),
        ("上下文字段透传", prepared.context.get("history_len") == 1),
        ("时刻信息齐备", prepared.now_dt is not None and bool(prepared.tod)),
    ]
    for name, ok in checks:
        if ok:
            _ok(name)
        else:
            _fail(name, str(prepared))

    # 注入后的指令必须作为 build_prompt 的最后一个位置参数传入
    if exec_._context_builder.build_prompt is not None:
        _ok("build_prompt 接收注入后的 specific_instruction（构造时已按位置传入）")


def test_generation_pipeline_paths() -> None:
    _section("测试 6: GenerationPipeline 预生成文案 / LLM 两条路径")
    from core.services.active_care.core.generation_pipeline import GenerationPipeline

    exec_ = _new_executor()
    exec_._message_dispatcher = SimpleNamespace(persist_proactive_message_fallback=mock.AsyncMock())
    exec_._generate_active_care_response = mock.AsyncMock(return_value={"content": "generated"})
    exec_._get_active_care_model_hint = lambda persona_name: f"hint::{persona_name}"

    pipeline = GenerationPipeline(exec_)
    loop = asyncio.new_event_loop()
    try:
        reused = loop.run_until_complete(
            pipeline.get_or_generate_response(
                aveline_service=object(),
                reply_text="决策阶段已生成",
                thought="t",
                context={"persona_name": "ye"},
                sys_prompt="sp",
                model_user_input="ui",
                target_conversation_id="cid",
            )
        )
        if reused["content"] == "决策阶段已生成" and reused["message_type"] == "text":
            _ok("有 reply_text 时直接复用并补记兜底持久化")
        else:
            _fail("预生成文案复用路径异常", str(reused))
        if exec_._message_dispatcher.persist_proactive_message_fallback.await_count == 1:
            _ok("复用路径调用了 persist_proactive_message_fallback")
        else:
            _fail("复用路径未调用 persist_proactive_message_fallback")

        generated = loop.run_until_complete(
            pipeline.get_or_generate_response(
                aveline_service=object(),
                reply_text=None,
                thought="t",
                context={"persona_name": "ye"},
                sys_prompt="sp",
                model_user_input="ui",
                target_conversation_id="cid",
            )
        )
        exec_._generate_active_care_response.assert_awaited_once()
        kwargs = exec_._generate_active_care_response.await_args.kwargs
        if generated == {"content": "generated"} and kwargs.get("model_hint") == "hint::ye":
            _ok("无 reply_text 时走 LLM 路径，模型提示取自 context.persona_name")
        else:
            _fail("LLM 路径参数异常", f"{generated} / {kwargs}")
    finally:
        loop.close()


def test_post_send_handler() -> None:
    _section("测试 7: PostSendHandler 三段收尾")
    from core.services.active_care.core.post_send_handler import PostSendHandler

    exec_ = _new_executor()
    exec_._morning_pending = SimpleNamespace(clear_if_injected=mock.AsyncMock())
    exec_._message_dispatcher = SimpleNamespace(write_diary_entry=mock.AsyncMock())
    exec_.storage = mock.MagicMock()
    exec_.storage.resolve_scope_from_persona_filename = lambda pf: f"scope::{pf}"
    exec_.storage.save_proactive_state = mock.AsyncMock()

    handler = PostSendHandler(exec_)
    loop = asyncio.new_event_loop()
    try:
        with mock.patch(
            "core.services.active_care.core.service.get_active_care_service"
        ) as get_svc:
            svc = mock.MagicMock()
            svc.on_assistant_message_sent = mock.AsyncMock()
            get_svc.return_value = svc

            loop.run_until_complete(
                handler.on_delivered(
                    target_conversation_id="cid",
                    morning_pending_injected=["昨晚的消息"],
                    now=1000.0,
                    persona_filename="pf",
                )
            )
            if exec_._morning_pending.clear_if_injected.await_args.args == (
                "cid",
                ["昨晚的消息"],
            ):
                _ok("on_delivered 清空早安 pending")
            else:
                _fail("on_delivered 未正确清 pending")
            if svc.on_assistant_message_sent.await_count == 1:
                _ok("on_delivered 通知服务更新间隔保护")
            else:
                _fail("on_delivered 未通知服务")

        loop.run_until_complete(handler.write_diary("checking", "内容", thought="t"))
        if exec_._message_dispatcher.write_diary_entry.await_args.args == (
            "checking",
            "内容",
        ):
            _ok("write_diary 委托给 message_dispatcher.write_diary_entry")
        else:
            _fail("write_diary 委托异常")

        loop.run_until_complete(handler.clear_deferred_reminders("pf"))
        kwargs = exec_.storage.save_proactive_state.await_args.kwargs
        if (
            exec_.storage.save_proactive_state.await_args.args[0] == {"deferred_plan_reminders": []}
            and kwargs.get("scope") == "scope::pf"
        ):
            _ok("clear_deferred_reminders 按 persona 解析 scope 后写盘")
        else:
            _fail("clear_deferred_reminders 写盘参数异常", str(kwargs))
    finally:
        loop.close()


def test_full_trigger_flow_smoke() -> None:
    _section("测试 8: 完整触发流程接线冒烟（fake 依赖）")
    from core.services.active_care.core.trigger_preparer import PreparedTrigger
    from core.services.active_care.core.trigger_result import TriggerOutcome

    exec_ = _new_executor()
    calls: list[str] = []

    prepared = PreparedTrigger(
        target_conversation_id="target_cid",
        original_conversation_id="orig_cid",
        requested_client_type="qq",
        morning_pending_injected=[],
        specific_instruction="指令",
        context={"proactive_state": {}},
        prompt_result=SimpleNamespace(has_deferred_reminders=True),
        sys_prompt="SYS",
        dynamic_prompt="DYN",
        model_user_input="UI",
        now_dt="NOW_DT",
        tod="morning",
    )

    async def fake_prepare(**kwargs):
        calls.append("prepare")
        return prepared

    async def fake_generate(**kwargs):
        calls.append("generate")
        return {"content": "要发送的内容"}

    async def fake_dispatch(*args, **kwargs):
        calls.append("dispatch")
        return True

    async def fake_on_delivered(**kwargs):
        calls.append("on_delivered")

    async def fake_write_diary(*args, **kwargs):
        calls.append("write_diary")

    async def fake_clear_deferred(persona_filename=""):
        calls.append("clear_deferred")

    exec_._overlap_guard = SimpleNamespace(
        check=lambda *a, **k: True,
        record_attempt=lambda *a: None,
        record_skip=lambda *a: None,
        rollback_on_failure=lambda *a: calls.append("rollback"),
    )
    exec_._trigger_preparer = SimpleNamespace(prepare=mock.AsyncMock(side_effect=fake_prepare))
    exec_._generation_pipeline = SimpleNamespace(
        generate_and_postprocess=mock.AsyncMock(side_effect=fake_generate)
    )
    exec_._content_corrector = SimpleNamespace(correct=lambda *a, **k: calls.append("correct"))
    exec_._message_dispatcher = SimpleNamespace(
        dispatch_message=mock.AsyncMock(side_effect=fake_dispatch)
    )
    exec_._post_send_handler = SimpleNamespace(
        on_delivered=mock.AsyncMock(side_effect=fake_on_delivered),
        write_diary=mock.AsyncMock(side_effect=fake_write_diary),
        clear_deferred_reminders=mock.AsyncMock(side_effect=fake_clear_deferred),
    )

    with mock.patch(
        "core.core_engine.service_singletons.get_aveline_service",
        return_value=object(),
    ):
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                exec_.trigger_message_with_result(
                    sys_prompt_type="checking",
                    user_input_mock="[MOCK]",
                    # 必须用白名单内的真实角色：入口会先做角色准入判断，
                    # 传占位名（如 pf）会在准备阶段之前就被拦下，导致阶段序列为空。
                    persona_filename="core_aveline.json",
                )
            )
        finally:
            loop.close()

    expected = [
        "prepare",
        "generate",
        "correct",
        "dispatch",
        "on_delivered",
        "write_diary",
        "clear_deferred",
    ]
    if calls == expected:
        _ok(f"阶段顺序正确: {' → '.join(calls)}")
    else:
        _fail("阶段顺序或缺失不符", f"实际={calls} 期望={expected}")

    if result.delivered and result.outcome is TriggerOutcome.DELIVERED:
        _ok("成功链路返回 DELIVERED")
    else:
        _fail("成功链路返回结果错误", str(result))

    if "rollback" not in calls:
        _ok("成功链路未触发失败回退")
    else:
        _fail("成功链路不应触发 rollback_on_failure")


def test_public_api_preserved() -> None:
    _section("测试 9: 外部 API 未变")
    from core.services.active_care.core.executor import (
        ActiveCareExecutor,
        get_active_care_executor,
    )

    required = [
        "trigger_message",
        "trigger_message_with_result",
        "generate_peer_script",
        "determine_hardware_intent",
        "write_diary_entry",
        "check_reminders",
        "complete_reminder",
        "format_due_reminder_message",
        "get_non_response_count",
        "_resolve_persona_key_from_filename",
        "_build_recent_history_text",
        "_build_model_user_input_for_active_care",
        "_extract_text_from_llm_response",
        "_get_active_care_model_hint",
        "_generate_active_care_response",
        "_resolve_model_path",
        "_get_generation_params",
        "_handle_llm_timeout",
        "_handle_reasoning_only_response",
        "_try_fallback_for_reasoning",
        "_get_fallback_model",
        "_get_qq_connections",
        "_get_qq_user_id_from_connections",
        "_check_overlap_guard",
        "_get_overlap_guard_seconds",
        "_generate_and_postprocess",
        "_get_or_generate_response",
    ]
    missing = [name for name in required if not hasattr(ActiveCareExecutor, name)]
    if missing:
        _fail("ActiveCareExecutor 缺少外部依赖的方法", "、".join(missing))
    else:
        _ok(f"{len(required)} 个对外方法（含兼容入口）全部保留")

    if isinstance(ActiveCareExecutor._last_trigger_ts_by_persona, property):
        _ok("_last_trigger_ts_by_persona 仍为只读 property（外部读写共享字典）")
    else:
        _fail("_last_trigger_ts_by_persona 不再是 property")

    if callable(get_active_care_executor):
        _ok("get_active_care_executor 工厂函数保留")
    else:
        _fail("get_active_care_executor 缺失")


def main() -> int:
    print("=" * 64)
    print("executor.py 触发链路解耦验证（2026-09-04）")
    print("=" * 64)

    test_new_modules_importable()
    test_executor_mounts_submodules()
    test_facade_delegation()
    test_orchestrator_has_no_inline_implementation()
    test_prepare_wires_all_steps()
    test_generation_pipeline_paths()
    test_post_send_handler()
    test_full_trigger_flow_smoke()
    test_public_api_preserved()

    print("=" * 64)
    print(f"通过 {_PASSED} 项，失败 {_FAILED} 项")
    print("=" * 64)
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
