"""晚安/早安 prompt 的 LLM 实际输出测试。

验证修改后的 TASK_GOODNIGHT_PROACTIVE_TEMPLATE 是否能让 LLM 生成正确的晚安消息
（角色自己要睡了），而不是"说了晚安又不睡"或"你先休息，等你醒来我们再聊"
这种语义错误的内容。

测试场景：
1. goodnight_proactive（aveline）：首次入睡晚安消息
2. goodnight_proactive（ling）：首次入睡晚安消息
3. good_morning_proactive（aveline）：起床问候
4. good_morning_proactive + reduced_mode（aveline）：起床问候但 active_care 还在 reduced_mode

运行方式：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe -m tests.scripts.active_care.verify_goodnight_prompt_llm

可选参数：
    --model cloud:MiniMax:MiniMax-M2.5  指定模型路径（默认 cloud:MiniMax:MiniMax-M2.5）
    --n 5                           每个场景调用 LLM 的次数（默认 3）
    --scenario goodnight_aveline    只跑指定场景（默认全部）
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import List, Tuple

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
    AVELINE_TONE_REFERENCE,
    CORE_CONSTRAINTS,
    GOODNIGHT_REDUCED_MODE_INSTRUCTION,
    QUIET_MODE_INSTRUCTION,
    STYLE_ENFORCEMENT_TEMPLATE,
    TASK_GOOD_MORNING_PROACTIVE_TEMPLATE,
    TASK_GOODNIGHT_PROACTIVE_TEMPLATE,
)
from core.character.aveline import AvelineCharacter
from core.character.managers.persona_manager import get_persona_manager
from core.llm import get_llm_module


# ── Prompt 构建 ──────────────────────────────────────────────

def _load_persona_prompt(persona_filename: str) -> str:
    """加载 persona prompt，失败时回退到 AvelineCharacter 默认模板。"""
    try:
        pm = get_persona_manager()
        cfg = pm.get_persona_by_filename(persona_filename) or {}
        if isinstance(cfg, dict):
            identity = cfg.get("identity") if isinstance(cfg.get("identity"), dict) else {}
            cn_name = str(identity.get("cn_name") or identity.get("name") or "").strip()
            context = str(identity.get("context") or "").strip()
            if cn_name or context:
                return f"你是{cn_name or '该角色'}。{context}".strip()
    except Exception as exc:
        print(f"  [WARN] 加载 persona {persona_filename} 失败: {exc}")
    try:
        return AvelineCharacter().get_system_prompt_template()
    except Exception:
        return "你是七濑 澪，傲娇毒舌，用命令和嫌弃掩饰关心。"


def build_goodnight_prompt(role: str = "aveline") -> Tuple[str, str]:
    """构建 goodnight_proactive 的完整 prompt（模拟 23:00 首次入睡场景）。

    Returns:
        (sys_prompt, user_msg)
    """
    tod = "深夜 23:00"
    if role == "aveline":
        persona_filename = "qq/Aveline_QQ_Master.json"
        persona_prompt = _load_persona_prompt(persona_filename)
        tone_ref = AVELINE_TONE_REFERENCE
    else:
        persona_filename = "qq/Ling_QQ_Master.json"
        persona_prompt = _load_persona_prompt(persona_filename)
        # ling 用动态 dialogue_examples，测试脚本里用空串模拟
        tone_ref = ""

    sys_prompt = (
        persona_prompt + "\n\n"
        + STYLE_ENFORCEMENT_TEMPLATE
        + tone_ref
        + "\n" + TASK_GOODNIGHT_PROACTIVE_TEMPLATE.format(tod=tod)
        + "\n" + CORE_CONSTRAINTS
    )
    user_msg = "[CHARACTER_GOING_TO_SLEEP]"
    return sys_prompt, user_msg


def build_goodmorning_prompt(
    role: str = "aveline",
    with_reduced_mode: bool = False,
    reduced_reason: str = "goodnight",
) -> Tuple[str, str]:
    """构建 good_morning_proactive 的完整 prompt。

    Args:
        with_reduced_mode: 是否注入低打扰模式指令（模拟 active_care 还在 reduced_mode）
        reduced_reason: reduced_mode 原因（goodnight/probable_sleep/其他）
    """
    tod = "早上 07:30"
    persona_filename = "qq/Aveline_QQ_Master.json" if role == "aveline" else "qq/Ling_QQ_Master.json"
    persona_prompt = _load_persona_prompt(persona_filename)
    tone_ref = AVELINE_TONE_REFERENCE if role == "aveline" else ""

    sys_prompt = (
        persona_prompt + "\n\n"
        + STYLE_ENFORCEMENT_TEMPLATE
        + tone_ref
        + "\n" + TASK_GOOD_MORNING_PROACTIVE_TEMPLATE.format(tod=tod)
        + "\n" + CORE_CONSTRAINTS
    )
    if with_reduced_mode:
        if reduced_reason == "goodnight":
            sys_prompt += GOODNIGHT_REDUCED_MODE_INSTRUCTION
        # probable_sleep 已于 2026-07-30 移除
        else:
            sys_prompt += QUIET_MODE_INSTRUCTION
    user_msg = "[CHARACTER_GOOD_MORNING]"
    return sys_prompt, user_msg


# ── LLM 调用 ──────────────────────────────────────────────

async def call_llm(
    sys_prompt: str,
    user_msg: str,
    model_path: str,
    n: int = 3,
) -> List[str]:
    """调用 LLM 多次，返回输出列表。"""
    llm = get_llm_module()
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_msg},
    ]
    results: List[str] = []
    for i in range(n):
        try:
            raw = await llm.chat(
                messages,
                temperature=0.65,
                max_new_tokens=400,
                model_path=model_path,
            )
            if isinstance(raw, dict):
                text = str(
                    raw.get("response") or raw.get("text") or raw.get("error") or ""
                ).strip()
            else:
                text = str(raw or "").strip()
            results.append(text)
        except Exception as exc:
            results.append(f"[ERROR: {exc}]")
    return results


# ── 输出检查 ──────────────────────────────────────────────

# 通用错误内容（所有场景都不应该出现）
BAD_PHRASES = [
    "说了晚安又不睡",
    "你怎么还不睡",
    "又熬夜",
    "这个点还不睡",
]

# 晚安场景的正确告别词
GOODNIGHT_GOOD_PHRASES = [
    "先睡了", "去睡了", "睡啦", "晚安", "困了", "去休息了",
    "我先去睡了", "继续睡啦", "再睡会儿",
]

# 早安场景的正确问候词
GOODMORNING_GOOD_PHRASES = [
    "早安", "早上好", "醒了", "起床了", "睡醒了", "早",
]

# 低打扰模式收尾语（不应出现在晚安/早安场景）
REDUCED_MODE_PHRASES = [
    "你先休息", "等你醒来", "不用回我", "你先睡",
]


def check_output(text: str, scenario: str) -> List[str]:
    """检查输出是否符合预期，返回问题列表（空列表表示通过）。"""
    issues: List[str] = []

    # 通用错误内容：所有场景都不应该出现"说了晚安又不睡"（这是最严重的语义错误）
    # "你怎么还不睡"/"这个点还不睡"只在晚安场景检查（早安场景下问"昨晚又熬夜"是合理的）
    if "说了晚安又不睡" in text:
        issues.append("包含错误内容: '说了晚安又不睡'")

    if scenario == "goodnight":
        # 晚安场景：检查所有 BAD_PHRASES（都是"指责用户不睡"的语义）
        for phrase in BAD_PHRASES:
            if phrase in text:
                issues.append(f"包含错误内容: '{phrase}'")
        # 晚安场景：应该表达"角色自己要睡了"
        if not any(phrase in text for phrase in GOODNIGHT_GOOD_PHRASES):
            issues.append("未包含晚安告别词（如『先睡了』『去睡了』『睡啦』等）")
        # 不应该出现低打扰模式收尾语
        for phrase in REDUCED_MODE_PHRASES:
            if phrase in text:
                issues.append(f"包含低打扰模式收尾语: '{phrase}'（晚安场景不应出现）")
                break

    elif scenario == "goodmorning":
        # 早安场景：应该表达"角色自己醒了"
        if not any(phrase in text for phrase in GOODMORNING_GOOD_PHRASES):
            issues.append("未包含早安问候词（如『早安』『醒了』『起床了』等）")
        # 不应该出现"你先休息"/"等你醒来"（这是让用户继续睡，不是角色自己醒了）
        for phrase in ["你先休息", "等你醒来"]:
            if phrase in text:
                issues.append(f"包含低打扰模式收尾语: '{phrase}'（早安场景不应出现）")
                break

    return issues


# ── 主流程 ──────────────────────────────────────────────

SCENARIOS = [
    # (name, scenario, role, with_reduced_mode, reduced_reason)
    ("goodnight_aveline", "goodnight", "aveline", False, ""),
    ("goodnight_ling", "goodnight", "ling", False, ""),
    ("goodmorning_aveline", "goodmorning", "aveline", False, ""),
    ("goodmorning_aveline_reduced_goodnight", "goodmorning", "aveline", True, "goodnight"),
    # probable_sleep 场景已于 2026-07-30 移除
    ("goodmorning_aveline_reduced_quiet", "goodmorning", "aveline", True, "quiet"),
]


async def run_scenario(
    name: str,
    scenario: str,
    role: str,
    with_reduced_mode: bool,
    reduced_reason: str,
    model_path: str,
    n: int,
) -> bool:
    """运行单个测试场景，返回是否全部通过。"""
    print(f"\n{'=' * 80}")
    print(f"场景: {name}")
    print(f"{'=' * 80}")

    if scenario == "goodnight":
        sys_prompt, user_msg = build_goodnight_prompt(role)
    else:
        sys_prompt, user_msg = build_goodmorning_prompt(role, with_reduced_mode, reduced_reason)

    print(f"\n[System Prompt 长度]: {len(sys_prompt)} 字符")
    print("[System Prompt 预览（前 600 字）]:")
    preview = sys_prompt[:600]
    print(preview + ("..." if len(sys_prompt) > 600 else ""))
    print(f"\n[User Message]: {user_msg}")
    print(f"\n[LLM 调用中... model={model_path}, n={n}]")

    t0 = time.time()
    results = await call_llm(sys_prompt, user_msg, model_path, n=n)
    elapsed = time.time() - t0
    print(f"[LLM 调用完成，耗时 {elapsed:.1f}s]")

    all_pass = True
    for i, text in enumerate(results, 1):
        print(f"\n  第 {i} 次输出: {text}")
        issues = check_output(text, scenario)
        if issues:
            all_pass = False
            for issue in issues:
                print(f"    X {issue}")
        else:
            print("    OK 符合预期")

    print(f"\n[场景结果]: {'全部通过' if all_pass else '有问题'}")
    return all_pass


async def main():
    parser = argparse.ArgumentParser(description="晚安/早安 prompt LLM 输出测试")
    parser.add_argument(
        "--model",
        default="cloud:MiniMax:MiniMax-M2.5",
        help="模型路径（默认 cloud:MiniMax:MiniMax-M2.5）",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=3,
        help="每个场景调用 LLM 的次数（默认 3）",
    )
    parser.add_argument(
        "--scenario",
        default="",
        help="只跑指定场景（默认全部）",
    )
    args = parser.parse_args()

    print("=" * 80)
    print("晚安/早安 prompt LLM 实际输出测试")
    print(f"模型: {args.model}")
    print(f"每场景调用次数: {args.n}")
    print("=" * 80)

    scenarios = SCENARIOS
    if args.scenario:
        scenarios = [s for s in SCENARIOS if s[0] == args.scenario]
        if not scenarios:
            print(f"[ERROR] 未找到场景: {args.scenario}")
            print(f"可用场景: {[s[0] for s in SCENARIOS]}")
            return 1

    results: List[Tuple[str, bool]] = []
    for name, scenario, role, with_reduced, reduced_reason in scenarios:
        passed = await run_scenario(
            name, scenario, role, with_reduced, reduced_reason,
            model_path=args.model, n=args.n,
        )
        results.append((name, passed))

    # 汇总
    print(f"\n{'=' * 80}")
    print("汇总")
    print(f"{'=' * 80}")
    for name, passed in results:
        status = "OK 通过" if passed else "X 有问题"
        print(f"  {name}: {status}")

    all_pass = all(p for _, p in results)
    print(f"\n[总结果]: {'全部通过' if all_pass else '存在问题，需要检查'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
