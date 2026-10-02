"""prompt 拼装解耦的护栏：快照对比，证明重构前后产物完全一致。

用法：
    # 重构前存基线
    python tests/scripts/prompt/verify_prompt_decoupling.py --save
    # 重构后比对
    python tests/scripts/prompt/verify_prompt_decoupling.py

快照写到 tests/scripts/prompt/_golden/<persona>.json，比对时逐条消息
逐字符比较；任何差异都会明确指出第几条消息从哪里开始不同。

另外顺带做重复注入检测：统计末尾 user 消息里各标记块出现的次数，
同一标记出现两次即为疑似重复（学习/教学、日期、日程这类容易重复注入）。
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from contextlib import ExitStack
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

GOLDEN_DIR = Path(__file__).resolve().parent / "_golden"

PERSONA_FILES = {
    "aveline": "core_aveline.json",
    "ling": "core_ling.json",
    "ye": "core_ye.json",
    "lin": "core_lin.json",
}

# 非【】形式的标记，单独计数；【】块头统一由正则扫描，避免重复计数
DUPLICATE_MARKERS = (
    "当前时间",
    "<system-reminder>",
)


class _FakeAgent:
    """够用的 agent 替身：拼装只读这几个属性，不触网、不启服务。"""

    tool_registry = None
    config = None

    def _is_study_mode(self, message, model_hint=None) -> bool:
        return False


# 时间相关注入每次跑都变，必须冻结才能做快照对比
FIXED_NOW = datetime(2026, 9, 19, 12, 0, 0)
_TIME_PATCHES = (
    "core.utils.time_utils.get_current_time",
    "core.utils.time.time_utils.get_current_time",
)


def build(persona_filename: str, *, freeze_time: bool = True) -> list[dict]:
    """拼一条完整消息列表。

    freeze_time=True：给快照用的，必须完全冻结才能逐字节比对；
    freeze_time=False：给重复注入扫描用的 —— 冻结时间会让 daily manager 的
    时间运算炸掉（naive/aware 相减），整段活动上下文消失，扫不出真实重复。
    """
    from core.agents.chat_agent_components.persona_system.prompt import (
        assembler,
        dynamic_injections,
    )

    with ExitStack() as stack:
        if freeze_time:
            for target in _TIME_PATCHES:
                try:
                    stack.enter_context(patch(target, return_value=FIXED_NOW))
                except (ModuleNotFoundError, AttributeError):
                    pass
        # 「距上次对话」和「硬件状态」逐轮都变，快照必须冻结。
        # 调用点解耦前在 assembler 命名空间、解耦后在 dynamic_injections，补丁打在新家。
        # 只在 freeze_time 时冻：冻结的假块不含【角色睡眠状态】，会把真实块挡在扫描之外。
        if freeze_time:
            stack.enter_context(
                patch.object(
                    dynamic_injections,
                    "build_time_context",
                    return_value="距上次对话：7小时23分钟",
                )
            )
            stack.enter_context(
                patch.object(
                    dynamic_injections,
                    "get_cached_bionic_state",
                    return_value="你的硬件状态：CPU10% RAM66%",
                )
            )
            # 饱腹/口渴会随时间衰减（实测 1.5 小时掉了 4 点），不冻结基线必然漂移。
            # 护栏比的是拼装结构与顺序，业务数值的漂移必须排除在外。
            stack.enter_context(
                patch.object(
                    dynamic_injections,
                    "build_food_context",
                    return_value=(
                        "【角色饮食状态】\nhunger=80/100 (一般)\n"
                        "thirst=56/100\nenergy=100/100\nfood_inventory_count=0"
                    ),
                )
            )
        return assembler.build_complete_message_list(
            agent=_FakeAgent(),
            user_id="shared__persona__core_aveline",
            message="今天吃了什么，昨天那件事还记得吗",
            user_name="测试用户",
            history_messages=[
                {"role": "user", "content": "早"},
                {"role": "assistant", "content": "早呀"},
            ],
            persona_filename=persona_filename,
            active_tools=["search_chat_history", "web_search"],
        )


def _diff(before: list[dict], after: list[dict]) -> list[str]:
    problems = []
    if len(before) != len(after):
        problems.append(f"消息条数不同: {len(before)} -> {len(after)}")
    for index, (old, new) in enumerate(zip(before, after)):
        if old == new:
            continue
        if old.get("role") != new.get("role"):
            problems.append(f"第{index}条 role 不同: {old.get('role')} -> {new.get('role')}")
            continue
        o, n = old.get("content", ""), new.get("content", "")
        if o == n:
            continue
        offset = next(
            (i for i, (a, b) in enumerate(zip(o, n)) if a != b), min(len(o), len(n))
        )
        problems.append(
            f"第{index}条内容不同（首个差异 @{offset}）：\n"
            f"    旧: ...{o[max(0, offset-40):offset+40]}...\n"
            f"    新: ...{n[max(0, offset-40):offset+40]}..."
        )
    return problems


def check_duplicates(messages: list[dict]) -> list[str]:
    """扫描整条 prompt 里所有【块头】/ system-reminder，出现两次即疑似重复注入。

    只算**行首**的【】：正文里也可能提到某个块名（例如 user_bio 那句
    "作息以【角色睡眠状态】【角色当前活动背景】为准"），那是引用不是注入，
    算进去会误报。
    """
    if not messages:
        return []
    text = "\n".join(str(item.get("content", "")) for item in messages)
    counter: dict[str, int] = {}
    for marker in DUPLICATE_MARKERS:
        counter[marker] = text.count(marker)
    for header in re.findall(r"(?m)^【[^】\n]{1,20}】", text):
        counter[header] = counter.get(header, 0) + 1
    found = [f"{name} ×{count}" for name, count in counter.items() if count >= 2]
    return sorted(found)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true", help="覆盖写入基线快照")
    args = parser.parse_args()

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    if args.save:
        for name, filename in PERSONA_FILES.items():
            try:
                messages = build(filename)
            except Exception as exc:  # noqa: BLE001
                print(f"  [SKIP] {name}: 构建失败 {exc}")
                continue
            (GOLDEN_DIR / f"{name}.json").write_text(
                json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  [SAVED] {name}: {len(messages)} 条消息")
        print("基线快照已写入", GOLDEN_DIR)
        return

    failed = 0
    for name, filename in PERSONA_FILES.items():
        golden_path = GOLDEN_DIR / f"{name}.json"
        if not golden_path.exists():
            print(f"  [SKIP] {name}: 无基线快照")
            continue
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        current = build(filename)
        problems = _diff(golden, current)
        if problems:
            failed += 1
            print(f"  [FAIL] {name}:")
            for item in problems:
                print(f"      {item}")
        else:
            print(f"  [PASS] {name}: 与基线完全一致")

        dupes = check_duplicates(build(filename, freeze_time=False))
        print(f"      重复注入扫描: {'; '.join(dupes) if dupes else '无'}")

    print("\n结果:", "全部一致" if not failed else f"{failed} 个角色不一致")


if __name__ == "__main__":
    main()
