"""用真人设 + 真实 LLM 验证教学闭环是否真的成立。

要回答的问题只有一个：**LLM 会不会主动调 `study_record_answer`**，
也就是教学闭环的写入端在真实对话里能不能被触发。

离线（默认，不调模型）：
  - 教学工具是否真的进入本轮可用工具集
  - 学习状态是否真的注入了 system prompt
  - 导出请求预览（含工具 schema），人工可查

--live（真跑，用角色绑定的 DeepSeek 路由）：
  - 第 1 轮：用户提问 -> 期望调用 study_get_context / study_record_teaching
  - 第 2 轮：用户作答 -> **期望调用 study_record_answer**（核心断言）
  - 工具调用直接在本地执行，验证 ConceptState 真的被更新

已知边界：生产链路是「先出工具调用 -> 回填结果 -> 再生成正文」两趟，
本脚本每轮只调一次 LLM，因此只验证**工具是否被调用**，不覆盖最终话术。
回复文本为空属正常现象，不代表失败。

学习状态写在临时目录，**不会污染真实 D:\\AI\\Study**；
笔记库索引仍指向真实笔记库（只读），以保证检索是真实场景。

用法：
    venv_core\\Scripts\\python.exe tests/scripts/study/verify_teaching_loop_live.py --persona aveline
    venv_core\\Scripts\\python.exe tests/scripts/study/verify_teaching_loop_live.py --persona ye --live
    venv_core\\Scripts\\python.exe tests/scripts/study/verify_teaching_loop_live.py --persona all --live
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

PERSONAS = {
    "aveline": {
        "filename": "core_aveline.json",
        "user_id": "shared__persona__core_aveline",
        "display": "Aveline",
    },
    "ye": {
        "filename": "core_ye.json",
        "user_id": "shared__persona__core_ye",
        "display": "Ye",
    },
}

TEACHING_TOOLS = (
    "study_get_context",
    "study_record_teaching",
    "study_record_answer",
    "study_record_confusion",
)

# 一轮真实的学习对话：先提问，被反问，再作答
QUESTION = "为什么 F = -kx 里面有负号？"
# 模型上一轮讲完后追问（放在 history 里，模拟它确实提了问）
ASSISTANT_ASK = (
    "因为 k 前面的负号表示回复力的方向总是跟位移方向相反：你把弹簧拉向右边，"
    "它就往左拉你。先不急着记公式——你说一下，如果位移 x 是负的（压缩状态），"
    "这时候弹力朝哪个方向？"
)
ANSWER = "位移是负的话，弹力应该朝正方向，因为 -kx 前面那个负号把方向翻过来了"

REAL_STUDY_ROOT = Path("D:/AI/Study")

# ----------------------------------------------------------------------
# 多轮场景：一次更接近真实的辅导对话
#
# 每轮的 assistant 文案是预置的——因为本脚本每轮只调一次 LLM，拿不到正文
# （生产是「先出工具调用 -> 回填 -> 再生成正文」两趟）。这点在报告里标明。
#
# 重点验证两条规则在真对话里成不成立：
#   1. 用户答错 -> 评价必须记下来，不能因为他说「懂了」就跳过；
#   2. 用户自称「我懂了」 -> **绝不能**直接变成已掌握。
# ----------------------------------------------------------------------
FULL_SCENARIO = [
    {
        "user": "讲讲胡克定律",
        "assistant": (
            "胡克定律：弹簧弹力 F = -kx，x 是相对原长的位置移，k 是劲度系数。"
            "先别急着背公式——如果把弹簧往左压短，这时候弹力朝哪边？"
        ),
    },
    {
        "user": "我没听懂，压缩是什么意思",
        "assistant": "压缩就是把弹簧压短，这时 x 是负的。那么弹力方向呢？",
        "must_have": "study_record_confusion",
    },
    {
        "user": "答案是朝右",
        "assistant": "不对哦，再想想 -kx 前面那个负号起了什么作用。",
        "must_have": "study_record_answer",
    },
    {
        "user": "答案是朝左，因为负号把方向翻过来了",
        "assistant": "对了，就是这个意思。要不要再看个例子？",
        "must_have": "study_record_answer",
    },
    {
        # 「我懂了」是自称掌握，没有对应的写入工具（生产由 observe_message
        # 记一条 mastery_claim 事件），因此**不要求**本轮调用任何工具——
        # 真正要验证的是它不会把知识点变成已掌握，见后面的状态断言。
        "user": "我懂了",
        "assistant": None,
        "require_tool": False,
    },
]


def _scenario_turns(args) -> list[dict]:
    """按 --scenario 返回本轮的对话脚本。"""
    if args.scenario == "full":
        return list(FULL_SCENARIO)
    return [
        {
            "user": QUESTION,
            "expect_any": tuple(TEACHING_TOOLS[:2]),
            "assistant": ASSISTANT_ASK,
        },
        {
            "user": ANSWER,
            "expect_any": tuple(TEACHING_TOOLS),
            "must_have": "study_record_answer",
        },
    ]


class Report:
    def __init__(self) -> None:
        self.checks: list[tuple[bool, str]] = []

    def check(self, ok: bool, label: str) -> None:
        self.checks.append((bool(ok), label))
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")

    @property
    def failed(self) -> list[str]:
        return [label for ok, label in self.checks if not ok]


def isolate_study_root(tmp: Path) -> None:
    """把学习状态写到临时目录，同时让笔记库指向真实笔记库（只读）。

    必须**重置学习系统单例**：一次进程跑多个角色时，单例里的
    ConceptStateManager / LearningEventStore 仍指向上一个角色的临时目录，
    第二个角色会沿用第一个的状态（表现如 mastery 累加成 0.40 而非 0.20）。
    """
    from core.services.study import (
        concept_state,
        daily_tracker,
        learning_event,
        paths,
        resources,
        student_state,
        study_library,
        teaching_orchestrator,
        weakness_tracker,
    )

    paths.get_study_root = lambda: tmp  # type: ignore[assignment]
    for manager in (
        concept_state.ConceptStateManager,
        learning_event.LearningEventStore,
        resources.ResourceRegistry,
        weakness_tracker.WeaknessTracker,
        student_state.StudentStateManager,
        teaching_orchestrator.TeachingOrchestrator,
    ):
        manager._instance = None
    if daily_tracker.DailyTracker._instance is not None:
        daily_tracker.DailyTracker._instance._cache.clear()
    daily_tracker.DailyTracker._instance = None

    study_library.StudyLibraryIndex._instance = study_library.StudyLibraryIndex(
        root=REAL_STUDY_ROOT
    )


def build_persona_prompt(persona: dict, message: str) -> tuple[str, str]:
    """按角色各自的封装方式构建 prompt，返回 (static, dynamic)。

    Ye的 v2 分层封装必须把 dynamic 也算进去，否则会严重低估实际 token 量。
    """
    filename = persona["filename"]
    if filename.startswith("core_ye"):
        from core.agents.chat_agent_components.persona_system.prompt.ye_layered_prompt import (
            build_ye_persona_layers,
        )

        layers = build_ye_persona_layers(
            persona_filename=filename,
            message=message,
            runtime_state={"state": {}},
        )
        return str(layers.static_prompt), str(layers.dynamic_prompt)

    from core.agents.chat_agent_components.persona_system.prompt.data import get_template_data

    prompt, _ = get_template_data(persona_filename=filename)
    return str(prompt), ""


def build_agent():
    """构造最小 agent 替身。

    **必须带上 `_is_study_mode`**：生产链路 `prepare_active_tools` 靠它决定
    tool_mode，缺了它 mode 永远是 chat，教学工具不会被选中——那样测出来的
    结论是假的（会在测试里通过、线上却不生效）。
    """
    from core.agents.chat_agent_components.study import is_study_mode
    from core.tools.registry import ToolRegistry, register_all_tools

    registry = ToolRegistry()
    register_all_tools(registry)
    agent = SimpleNamespace(
        tool_registry=registry,
        _is_study_mode=lambda message, model_hint=None: is_study_mode(message, model_hint),
    )
    return agent, registry


async def resolve_tools(agent, message: str, persona_filename: str) -> list[str]:
    """用生产链路解析本轮可用工具（必须是 await，不能再用 asyncio.run 包一层）。"""
    from core.agents.chat_agent_components.context_persona import prepare_active_tools

    return list(await prepare_active_tools(agent, message, None, persona_filename=persona_filename))


def estimate_tokens(text: str) -> tuple[int, str]:
    """统计 token 数。优先用项目自带的 C++ 快速分词器，否则退回字符估算。

    注意：这里只统计**人设 + 学习状态**部分，真实请求还会叠加
    对话历史、记忆上下文、角色日常上下文和工具 schema。
    """
    try:
        from core.services.scheduler.inference.inference_utils import (
            rough_estimate_tokens_from_text,
        )

        value = rough_estimate_tokens_from_text(text)
        if isinstance(value, int) and value > 0:
            return value, "tokenizer"
    except Exception:
        pass
    return max(1, int(len(text) / 1.5)), "estimate(char/1.5)"


async def run_persona(args, persona_key: str) -> int:
    persona = PERSONAS[persona_key]
    report = Report()

    tmp = Path(tempfile.mkdtemp(prefix=f"teaching_loop_{persona_key}_"))
    isolate_study_root(tmp)

    from core.services.study.teaching_orchestrator import get_teaching_orchestrator

    orchestrator = get_teaching_orchestrator()

    print(f"\n=== {persona['display']}（{persona['filename']}）===")

    # ---- 1. 学习信号与上下文注入 ----
    static_prompt, dynamic_prompt = build_persona_prompt(persona, QUESTION)
    # 先落一条学习记录再验证注入块：没有历史状态时注入块本就应为空，
    # 它传递的是「已有状态」而不是凭空造出来的东西。
    orchestrator.record_teaching("physics", "F = -kx")
    context_block = orchestrator.get_context_block(QUESTION)
    report.check(bool(context_block), "有学习状态后能产出持久化注入块")
    report.check("F = -kx" in context_block, "注入块包含已记录的知识点")

    agent, registry = build_agent()
    active_tools = await resolve_tools(agent, QUESTION, persona["filename"])
    available = [name for name in active_tools if registry.is_enabled(name)]

    print(f"  本轮可用工具: {available}")
    selected = [name for name in TEACHING_TOOLS if name in available]
    report.check(bool(selected), f"教学工具进入可用工具集: {selected}")

    # ---- 2. 工具 schema ----
    openai_tools = registry.get_openai_tools(include_names=available)
    tool_names_in_schema = [
        item["function"]["name"] for item in openai_tools if "function" in item
    ]
    report.check(
        all(name in tool_names_in_schema for name in selected),
        "教学工具的 OpenAI schema 已生成",
    )

    # 实际发送的 prompt = static + dynamic + 学习状态注入块
    sent_prompt = "\n".join(p for p in (static_prompt, dynamic_prompt, context_block) if p)
    prompt_chars = len(sent_prompt)
    prompt_tokens, token_source = estimate_tokens(sent_prompt)
    print(
        f"  prompt: static {len(static_prompt)} + dynamic {len(dynamic_prompt)} "
        f"+ 学习状态 {len(context_block)} = {prompt_chars} 字符 / {prompt_tokens} tokens ({token_source})"
    )
    print("    注：仅人设+学习状态；真实请求还含历史、记忆、角色日常与工具 schema")

    # ---- 3. 导出预览 ----
    messages = [
        {"role": "system", "content": static_prompt},
        {"role": "system", "content": context_block} if context_block else None,
    ]
    if dynamic_prompt:
        messages.append({"role": "system", "content": dynamic_prompt})
    messages.append({"role": "user", "content": QUESTION})
    messages = [m for m in messages if m]

    result = {
        "persona": persona_key,
        "persona_filename": persona["filename"],
        "model": "",
        "prompt_chars": prompt_chars,
        "prompt_tokens": prompt_tokens,
        "prompt_tokens_source": token_source,
        "static_chars": len(static_prompt),
        "dynamic_chars": len(dynamic_prompt),
        "learning_context_chars": len(context_block),
        "prompt_sha256": hashlib.sha256(sent_prompt.encode("utf-8")).hexdigest(),
        "active_tools": available,
        "teaching_tools_selected": selected,
        "context_block": context_block,
        "messages": messages,
        "turns": [],
    }

    if not args.live:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        target = args.report.with_name(f"{args.report.stem}_{persona_key}.json")
        target.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  预览已写入: {target}")
        if report.failed:
            print("FAIL 项：", report.failed)
            return 1
        print("PASS: 离线自检通过（未调用线上模型）")
        return 0

    # ---- 4. 真实 LLM ----
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    from config.model_config import get_persona_default_model
    from core.llm import get_llm_module
    from core.tools.execution import execute_tool_call

    route = args.model or get_persona_default_model(persona["filename"])
    result["model"] = route
    print(f"  模型路由: {route}")
    assert route.startswith("cloud:"), "此验证只允许显式云路由，禁止加载本地模型"

    llm = get_llm_module()
    try:
        turns = _scenario_turns(args)
        for turn_index, spec in enumerate(turns, start=1):
            user_text = spec["user"]
            expect_any = spec.get("expect_any", tuple(TEACHING_TOOLS))
            must_have = spec.get("must_have")

            if turn_index > 1:
                prev_assistant = turns[turn_index - 2].get("assistant")
                if prev_assistant:
                    messages.append({"role": "assistant", "content": prev_assistant})
                messages.append({"role": "user", "content": user_text})
            elif messages[-1].get("content") != user_text:
                messages.append({"role": "user", "content": user_text})

            # 复现生产：handler 每轮会先调 observe_message 记录低风险证据
            # （作答会留下「待评价」痕迹），下一轮 prompt 才会带上提醒。
            # 少了这一步，待评价提醒机制完全不参与，测出来的不是真实行为。
            observed = orchestrator.observe_message(user_text)
            if observed.get("status") == "recorded":
                print(f"    observe_message -> {observed['intent']}: {observed['concepts']}")

            # 每轮刷新学习状态注入块（生产每轮重建 prompt，状态是实时的）
            fresh_block = orchestrator.get_context_block(user_text)
            if fresh_block:
                messages.append({"role": "system", "content": fresh_block})

            raw = await llm.chat(
                messages,
                model_path=route,
                tools=openai_tools,
                tool_choice="auto",
                temperature=0.55,
                max_tokens=4096,
                fallback_local=False,
            )

            calls = extract_tool_calls(raw)
            reply = extract_text(raw)
            print(f"  第 {turn_index} 轮 -> 工具调用: {[c['name'] for c in calls]}")
            if not calls:
                # 提醒是否到位？没调工具时这一步是排查「为什么没调」的关键线索
                pending = orchestrator.get_context(user_text).get("pending_evaluations") or []
                print(f"    （本轮未调工具；当前待评价: {pending or '无'}）")
            if calls and not reply:
                # 生产链路是「先出工具调用 -> 把结果回填 -> 再生成正文」两趟，
                # 本脚本每轮只调一次 LLM，因此只验证工具调用，不覆盖最终话术。
                print("    （本轮只返回工具调用，正文由生产链路第二轮生成）")

            executed = []
            for call in calls:
                payload = await execute_tool_call(
                    agent=agent,
                    tool_name=call["name"],
                    arguments=call["arguments"],
                    user_id=persona["user_id"],
                    allowed_tool_names=available,
                    persona_filename=persona["filename"],
                )
                executed.append({"name": call["name"], "result": str(payload)[:400]})

            result["turns"].append(
                {
                    "turn": turn_index,
                    "user": user_text,
                    "reply": reply[:800],
                    "tool_calls": [
                        {"name": c["name"], "arguments": c["arguments"]} for c in calls
                    ],
                    "executed": executed,
                }
            )

            if spec.get("require_tool", True):
                report.check(
                    any(c["name"] in expect_any for c in calls),
                    f"第 {turn_index} 轮触发了教学工具",
                )
            if must_have:
                report.check(
                    any(c["name"] == must_have for c in calls),
                    f"第 {turn_index} 轮调用了 {must_have}（核心断言）",
                )
    finally:
        await llm.shutdown()

    # ---- 5. 状态是否真的落库 ----
    # 不能硬编码名称：模型可能写成「F = -kx（回复力方向）」这类带后缀的变体，
    # 必须用宽松名匹配（这正是 ConceptState.loose_name 要解决的问题）。
    from core.services.study.concept_state import ConceptState

    # 用核心 token 双向包含匹配，容忍模型加限定词（「胡克定律 F=-kx」）
    # 或带括号后缀（「F = -kx（回复力方向）」）的写法。
    # 多轮场景不绑定具体名称：模型可能把「讲讲胡克定律」落成「F = -kx」，
    # 这是它的自由。这里只要求「确实有物理知识点被写入」，
    # 并取证据最多的那个做后续断言（避免断言依赖模型的命名选择）。
    if args.scenario == "full":
        candidates = [
            c for c in orchestrator.concepts.all_concepts() if c.subject == "physics"
        ]
        concept = max(candidates, key=lambda c: c.evidence_count, default=None)
        concept = concept if concept and concept.evidence_count > 0 else None
        report.check(concept is not None, "多轮辅导后有物理知识点被写入且有证据")
    else:
        target = ConceptState.loose_name("F = -kx")
        concept = next(
            (
                c
                for c in orchestrator.concepts.all_concepts()
                if c.subject == "physics"
                and (
                    target in ConceptState.loose_name(c.name)
                    or ConceptState.loose_name(c.name) in target
                )
            ),
            None,
        )
        report.check(concept is not None, "知识点 F = -kx 已写入 ConceptState")
    if concept is not None:
        print(f"  知识点状态: {concept.status.value} mastery={concept.mastery:.2f}")
        report.check(
            concept.evidence_count > 0, "存在学习证据（evidence_count > 0）"
        )
        if args.scenario == "full":
            # 核心规则：用户说「我懂了」绝不能变成已掌握
            report.check(
                not concept.is_mastered,
                f"自称「我懂了」后仍未判定为已掌握（mastery={concept.mastery:.2f}）",
            )
        report.check(
            bool(orchestrator.events.read(concept_id=concept.concept_id, days=1, limit=50)),
            "LearningEvent 已落库",
        )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    target = args.report.with_name(f"{args.report.stem}_{persona_key}.json")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  报告已写入: {target}")

    if report.failed:
        print("FAIL 项：", report.failed)
        return 1
    print(f"PASS: {persona['display']} 教学闭环在真实模型上成立")
    return 0


def extract_tool_calls(raw) -> list[dict]:
    """从统一 LLM 返回里取出工具调用（兼容 dict / 对象两种形态）。"""
    if raw is None:
        return []
    if isinstance(raw, dict):
        calls = raw.get("tool_calls") or raw.get("tools") or []
    else:
        calls = getattr(raw, "tool_calls", None) or []

    parsed = []
    for call in calls:
        if isinstance(call, dict):
            name = call.get("name") or (call.get("function") or {}).get("name")
            arguments = call.get("arguments") or (call.get("function") or {}).get("arguments")
        else:
            name = getattr(call, "name", None)
            arguments = getattr(call, "arguments", None)
        if not name:
            continue
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (json.JSONDecodeError, ValueError):
                arguments = {}
        parsed.append({"name": str(name), "arguments": arguments or {}})
    return parsed


def extract_text(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, dict):
        return str(raw.get("response") or raw.get("text") or "")
    return str(getattr(raw, "response", "") or getattr(raw, "text", "") or "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--persona", choices=[*PERSONAS, "all"], default="all"
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "data/study/eval/teaching_loop_live.json",
    )
    parser.add_argument("--model", default="", help="覆盖角色默认模型路由")
    parser.add_argument(
        "--scenario",
        choices=("closed", "full"),
        default="closed",
        help="closed=两轮闭环；full=多轮真实辅导（含答错与自称掌握）",
    )
    parser.add_argument("--live", action="store_true", help="真实调用线上模型")
    args = parser.parse_args()

    keys = list(PERSONAS) if args.persona == "all" else [args.persona]
    exit_code = 0
    for key in keys:
        exit_code |= asyncio.run(run_persona(args, key))

    if exit_code:
        print("\n存在失败项，详见上方 FAIL 列表与报告文件")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
