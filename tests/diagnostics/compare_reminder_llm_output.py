"""对比新旧 reminder prompt 下 LLM 真实输出的自然度与重复检测通过率

背景：
- 6/27 active_care 的 reminder 几乎全部失败，根因是 reminder_msg 太机械
  （"我来盯你一下，该开始「X」了。"），LLM 顺着输出短模板话，
  被句子级部分包含检测拦截
- 优化后 reminder_msg 变成结构化上下文（带 description），
  TASK_REMINDER_TEMPLATE 加了 5 条差异化约束

本脚本：
1. 加载 6/27 plan.json 真实计划项
2. 对每个计划项，分别用旧逻辑（机械模板话）和新逻辑（结构化上下文）组装 prompt
3. 调真实 LLM 生成回复
4. 跑 deduplicator 检测：
   - is_semantically_repetitive：和模拟历史 anchor 对比
   - is_partially_repetitive：和 anchor list 对比
5. 输出对比，证明新逻辑生成的输出更自然、更不容易被拦
"""
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

# 加入项目根目录到 path
# parents[0]=active_care_review, [1]=diagnostics, [2]=tests, [3]=xiaoyou-core
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from config.integrated_config import get_settings
from config.model_config import resolve_active_care_model_path
from core.llm import get_llm_module
from core.services.active_care.core.reminder_handler import ReminderHandler
from core.services.active_care.postprocess.deduplicator import Deduplicator
from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
    STYLE_ENFORCEMENT_TEMPLATE,
    AVELINE_TONE_REFERENCE,
    TASK_REMINDER_TEMPLATE,
)
from core.utils.time_utils import get_time_period


# ── 模拟"前几天发过的机械模板话"作为重复检测锚点 ──────────────
# 这些是 6/27 之前理论上发过的同类提醒，模拟历史 anchor
# 这种"短模板话"是最容易让 LLM 顺着输出的，也是最容易被重复检测命中的场景
MOCK_HISTORICAL_ANCHORS: List[str] = [
    "该开始英语晨读了。",
    "英语晨读时间到了。",
    "该开始数学基础复习了。",
    "数学复习时间到了，该开始了。",
    "该开始物理专项训练了。",
    "物理训练时间到了。",
    "该开始化学选择题练习了。",
    "化学练习时间到了。",
    "该开始生物知识点梳理了。",
    "生物复习时间到了。",
]


@dataclass
class PlanItemCase:
    """单个测试用例：来自 6/27 plan.json 的真实计划项"""
    title: str
    description: str
    category: str
    subject: str
    time: str  # "HH:MM"


@dataclass
class MockReminder:
    """模拟 WorkspaceReminder 对象（只用到我们关心的字段）"""
    id: str = "mock"
    message: str = ""
    trigger_ts: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"


def load_real_plan_items() -> List[PlanItemCase]:
    """从 6/27 plan.json 加载真实计划项，挑 5 个有代表性的（每个科目一个）"""
    plan_path = (
        PROJECT_ROOT / "companion_data" / "user_data" / "daily"
        / "2026" / "06" / "27" / "plan.json"
    )
    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    # 挑 5 个有代表性的：英语、数学、物理、化学、生物
    target_titles = {
        "英语晨读", "数学基础复习", "物理专项训练",
        "化学选择题练习", "生物知识点梳理",
    }
    items: List[PlanItemCase] = []
    for raw in plan.get("items", []):
        title = raw.get("title", "")
        if title in target_titles:
            items.append(PlanItemCase(
                title=title,
                description=raw.get("description") or "",
                category=raw.get("category") or "",
                subject=raw.get("subject") or "",
                time=raw.get("time") or "",
            ))
    # 按 time 排序，输出更整齐
    items.sort(key=lambda x: x.time)
    return items


def build_old_reminder_msg(item: PlanItemCase) -> str:
    """旧版：机械模板话（修复前的真实输出）"""
    return f"我来盯你一下，该开始「{item.title}」了。"


def build_new_reminder_msg(
    item: PlanItemCase, reminder_handler: ReminderHandler
) -> str:
    """新版：用 ReminderHandler.format_due_reminder_message 拿结构化上下文"""
    reminder = MockReminder(
        message=f"该开始「{item.title}」了",
        metadata={
            "source": "daily_task",
            "type": "start",
            "task_title": item.title,
            "task_description": item.description,
            "task_category": item.category,
            "task_subject": item.subject,
        },
    )
    return reminder_handler.format_due_reminder_message(reminder)


def build_sys_prompt() -> str:
    """组装 sys_prompt：风格约束 + Aveline 傲娇语气参考"""
    return STYLE_ENFORCEMENT_TEMPLATE + AVELINE_TONE_REFERENCE


def build_user_input(reminder_msg: str) -> str:
    """组装 user_input：TASK_REMINDER_TEMPLATE 填充"""
    return TASK_REMINDER_TEMPLATE.format(
        tod=get_time_period(),
        reminder_msg=reminder_msg,
    )


async def call_llm(llm, model_path: str, sys_prompt: str, user_input: str) -> str:
    """调真实 LLM 生成回复"""
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_input},
    ]
    try:
        raw = await llm.chat(
            messages,
            temperature=0.65,
            max_new_tokens=400,
            model_path=model_path,
        )
    except Exception as e:
        return f"[LLM_ERROR] {e}"

    # 复用 ActiveCareResponseGenerator.extract_text_from_llm_response 的提取逻辑
    if isinstance(raw, dict):
        if raw.get("status") == "success":
            return str(raw.get("response") or raw.get("text") or "").strip()
        if raw.get("response"):
            return str(raw.get("response") or "").strip()
        if raw.get("error"):
            return f"[LLM_ERROR] {raw.get('error')}"
        return ""
    return str(raw or "").strip()


def check_dedup(text: str, anchors: List[str]) -> Dict[str, Any]:
    """对生成文本跑重复检测，返回检测结果

    模拟 postprocessor.postprocess 中的两道关卡：
    1. is_semantically_repetitive：整句重复检测（和任一 anchor 比）
    2. is_partially_repetitive：句子级部分包含检测（50%+ 句子重复即判死）
    """
    # 整句检测：和任一 anchor 比
    sem_hit_anchor: str = ""
    for anchor in anchors:
        if Deduplicator.is_semantically_repetitive(text, anchor):
            sem_hit_anchor = anchor
            break

    # 句子级部分包含检测
    partial_hit = Deduplicator.is_partially_repetitive(text, anchors)

    return {
        "is_semantically_repetitive": sem_hit_anchor != "",
        "sem_hit_anchor": sem_hit_anchor,
        "is_partially_repetitive": partial_hit,
        "blocked": sem_hit_anchor != "" or partial_hit,
    }


async def main():
    print("=" * 80)
    print("对比新旧 reminder prompt 下 LLM 真实输出")
    print("=" * 80)

    # 1. 加载真实计划项
    items = load_real_plan_items()
    print(f"\n[1] 加载 6/27 plan.json，挑出 {len(items)} 个真实计划项：")
    for it in items:
        print(f"    - {it.time} {it.title} ({it.category}/{it.subject or '-'})")
        print(f"      描述：{it.description}")

    # 2. 初始化 LLM
    print("\n[2] 初始化 LLM ...")
    settings = get_settings()
    llm = get_llm_module()
    await llm.initialize()

    model_path = resolve_active_care_model_path(
        model_hint="",
        model_type="content",
        persona_name="aveline",
        settings=settings,
        llm_module=llm,
    )
    print(f"    Active Care 模型路径：{model_path}")

    sys_prompt = build_sys_prompt()
    reminder_handler = ReminderHandler()

    # 3. 跑测试
    print("\n[3] 开始跑测试（每个计划项跑两版：旧版 vs 新版）...\n")

    results: List[Dict[str, Any]] = []
    for item in items:
        print("-" * 80)
        print(f"计划项：{item.time} {item.title}")
        print(f"  描述：{item.description}")
        print(f"  分类：{item.category}/{item.subject or '-'}")

        for version_label, reminder_msg_builder in [
            ("旧版(机械模板)", build_old_reminder_msg),
            ("新版(结构化上下文)",
             lambda it: build_new_reminder_msg(it, reminder_handler)),
        ]:
            reminder_msg = reminder_msg_builder(item)
            user_input = build_user_input(reminder_msg)
            print(f"\n  [{version_label}]")
            print(f"    reminder_msg：{reminder_msg}")
            print(f"    调用 LLM ...", end=" ", flush=True)

            output = await call_llm(llm, model_path, sys_prompt, user_input)
            print("完成")
            print(f"    LLM 输出：{output}")

            dedup_result = check_dedup(output, MOCK_HISTORICAL_ANCHORS)
            print(f"    重复检测：")
            print(f"      - 整句重复：{'是' if dedup_result['is_semantically_repetitive'] else '否'}"
                  + (f" (命中: {dedup_result['sem_hit_anchor'][:40]}...)"
                     if dedup_result['sem_hit_anchor'] else ""))
            print(f"      - 句子级部分包含：{'是' if dedup_result['is_partially_repetitive'] else '否'}")
            print(f"      - 最终：{'❌ 被拦截' if dedup_result['blocked'] else '✅ 通过'}")

            results.append({
                "title": item.title,
                "version": version_label,
                "reminder_msg": reminder_msg,
                "llm_output": output,
                "blocked": dedup_result["blocked"],
                "sem_hit": dedup_result["is_semantically_repetitive"],
                "partial_hit": dedup_result["is_partially_repetitive"],
            })

        # 避免太频繁调用 LLM
        await asyncio.sleep(0.5)

    # 4. 汇总
    print("\n" + "=" * 80)
    print("[4] 汇总对比")
    print("=" * 80)
    header = f"{'计划项':<18} {'版本':<22} {'是否被拦':<10} {'整句重复':<10} {'部分包含':<10}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r['title']:<18} {r['version']:<22} "
              f"{'❌' if r['blocked'] else '✅':<10} "
              f"{'是' if r['sem_hit'] else '否':<10} "
              f"{'是' if r['partial_hit'] else '否':<10}")

    old_results = [r for r in results if "旧版" in r["version"]]
    new_results = [r for r in results if "新版" in r["version"]]
    old_blocked = sum(1 for r in old_results if r["blocked"])
    new_blocked = sum(1 for r in new_results if r["blocked"])
    print(f"\n旧版被拦截：{old_blocked}/{len(old_results)}")
    print(f"新版被拦截：{new_blocked}/{len(new_results)}")

    # 5. 输出每条 LLM 实际输出（方便人工评判自然度）
    print("\n" + "=" * 80)
    print("[5] 新旧 LLM 输出对照（人工评判自然度）")
    print("=" * 80)
    for title in {r["title"] for r in results}:
        print(f"\n【{title}】")
        for r in [x for x in results if x["title"] == title]:
            print(f"  {r['version']}:")
            print(f"    {r['llm_output']}")

    await llm.shutdown()
    print("\n[完成] LLM 已关闭")


if __name__ == "__main__":
    asyncio.run(main())
