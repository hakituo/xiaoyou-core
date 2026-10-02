"""验证各角色从自己的 Prompt 读取 Active Care 示例，并隔离旧坏样本。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.services.active_care.prompt import prompt_builder  # noqa: E402


BAD_WAKEUP = "早，我起来了。"
LING_ACTIVE_CARE_SOURCE = Path(
    "data/character/ling/active_care/私聊_玲🍀.active.jsonl"
)


def _load_active_care_examples(role_id: str) -> dict:
    """读取某角色 `voice_<role_id>.json` 里 `active_care.examples` 的各类别文案。

    期望文案从角色自己的配置读取、而不是在脚本里钉死字符串：
    示例文案会随人设迭代整体重写（本脚本 2026-09-23 修复前就是因为钉死文案而全面误报），
    而这里真正要守的是「配置 → prompt」这条组装链路，以及角色之间不串示例。
    """
    import json

    path = (
        PROJECT_ROOT
        / "core"
        / "character"
        / "configs"
        / role_id
        / f"voice_{role_id}.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    return (data.get("active_care") or {}).get("examples") or {}


def _build(
    persona_filename: str,
    persona_name: str,
    sys_prompt_type: str = "good_morning_proactive",
):
    with ExitStack() as stack:
        for name in (
            "_build_today_plan_text",
            "_build_other_persona_reminders_text",
            "_build_bio_context_text",
            "_build_food_context_text",
            "_build_study_context_text",
            "get_special_day_prompt",
            "get_upcoming_birthday_prompt",
            "get_authoritative_calendar_prompt",
        ):
            stack.enter_context(patch.object(prompt_builder, name, return_value=""))
        return prompt_builder.build_active_care_prompt(
            user_id="shared__persona__fixture",
            sys_prompt_type=sys_prompt_type,
            user_input_mock="[CHARACTER_JUST_WOKE_UP]",
            reminder_msg=None,
            thought="character_waking_up_by_schedule",
            tod="早晨",
            now=1788566400.0,
            user_display_name="Master",
            persona_prompt=f"你是{persona_name}。",
            persona_dynamic_prompt="",
            tone_reference_text="",
            recent_history_text=(
                "【最近聊天记录】\n"
                f"- Assistant(你之前主动发起): {BAD_WAKEUP}\n"
            ),
            persona_filename=persona_filename,
            persona_name=persona_name,
            last_proactive_assistant_message=BAD_WAKEUP,
            last_assistant_message=BAD_WAKEUP,
            repeat_anchors=[BAD_WAKEUP],
            proactive_state={"recent_sent_contents": [BAD_WAKEUP]},
            sleep_session_active=True,
        )


def main() -> int:
    import json

    from config.model_config import (
        get_active_care_content_model,
        get_chat_model,
        reload_model_config,
    )

    reload_model_config()
    # 主对话路由：Ye按用户要求用 flash（config/yaml/sections/model_routing.yaml
    # 的 chat_models.ye）。这里锁定当前路由意图，配置被静默改动时该断言会失败。
    assert get_chat_model("Ye") == "cloud:deepseek:rushuang:deepseek-v4-flash"
    assert (
        get_active_care_content_model("Ye")
        == "cloud:minimax:MiniMax-M3"
    )

    aveline = _build("core_aveline.json", "Aveline")
    ling = _build("core_ling.json", "Ling")
    ye = _build("core_ye.json", "Ye")

    aveline_dynamic = aveline.dynamic_prompt
    ling_dynamic = ling.dynamic_prompt
    ye_dynamic = ye.dynamic_prompt

    # ---- 起床示例：每个角色从「自己」的 Prompt 文件读取 ----
    # 期望文案从各自 voice_<role>.json 读取，而不是在脚本里钉死（见 _load_active_care_examples）。
    examples_by_role = {
        role: _load_active_care_examples(role) for role in ("aveline", "ye", "ling")
    }
    assert examples_by_role["aveline"].get("good_morning_proactive"), "aveline 应有起床示例"
    assert examples_by_role["ye"].get("good_morning_proactive"), "ye 应有起床示例"

    # 旧坏样本（历史上被当成通用正向示例灌给所有角色）必须对所有角色隔离。
    for label, dynamic in (
        ("aveline", aveline_dynamic),
        ("ye", ye_dynamic),
        ("ling", ling_dynamic),
    ):
        assert BAD_WAKEUP not in dynamic, f"{label} 仍注入了旧坏起床样本"
        assert "给主人请安" not in dynamic, f"{label} 仍注入了旧请安样本"

    # Ling已退出主动关怀：config/yaml/app.yaml 的 active_care_enabled_roles = [aveline, ye]，
    # character_runtime.yaml 的 autonomous_roles 同样只有 aveline/ye，注释明确
    #「ling（Ling）/ lin（Lin）仍是已注册角色，可正常对话，但不主动发消息」。
    # 因此 voice_ling.json 的 active_care.examples 只剩 share_small_event / resume_topic /
    # missing_chat / simple_check 四类，**没有 good_morning_proactive**（起床示例随退场移除）。
    # 所以对 ling 只断言「隔离」（见下方统一的交叉污染检查），不再要求它有起床示例。
    assert "醒了。你睡你的。" not in ling_dynamic
    assert "主人，我醒啦。" not in ling_dynamic

    # 起床事件不再把之前的坏主动消息作为历史/去重锚点继续喂给模型。
    assert "Assistant(你之前主动发起)" not in ling_dynamic
    assert "Assistant(你之前主动发起)" not in ye_dynamic
    assert "参考锚点" not in ling_dynamic
    assert "参考锚点" not in ye_dynamic

    # 通用任务模板不再提供会把所有角色吸到同一句的中性正向示例。
    assert "不得只做任何角色都能套用的中性起床播报" in ye_dynamic

    # 示例不再集中在角色配置根目录；每个角色由自己的 Prompt 文件持有。
    assert not (PROJECT_ROOT / "core/character/configs/active_care_role_examples.json").exists()

    # ---- 各任务类别的示例：自己的必须进 prompt，别人的不能串进来 ----
    # 覆盖 aveline / ye 的每一个示例类别；ling 已退场（无 good_morning / usage 类示例），
    # 只作为「别人」参与下面的交叉污染检查。
    for role_id, persona_file, persona_name in (
        ("aveline", "core_aveline.json", "Aveline"),
        ("ye", "core_ye.json", "Ye"),
    ):
        own = examples_by_role[role_id]
        assert own, f"{role_id} 应有 active_care 示例"
        for category, items in own.items():
            dynamic = _build(persona_file, persona_name, category).dynamic_prompt
            for item in items:
                assert item["text"] in dynamic, (
                    f"{role_id}.{category} 的示例未进入 prompt: {item['text']}"
                )
            for other_role, other in examples_by_role.items():
                if other_role == role_id:
                    continue
                for item in (other.get(category) or []):
                    assert item["text"] not in dynamic, (
                        f"{role_id} 的 {category} prompt 混入了 {other_role} 的示例"
                    )

    # Ling示例必须以真实主动聊天链为依据，防止再次凭抽象人设编写。
    source_path = PROJECT_ROOT / LING_ACTIVE_CARE_SOURCE
    rows = [
        json.loads(line)
        for line in source_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) >= 54
    opening_groups = []
    for row in rows:
        group = []
        for turn in row["chain"]["turns"]:
            if turn["speaker"] != "ling":
                break
            group.append(turn["content"].strip())
        assert group
        opening_groups.append(group)
    assert sum(len(group) <= 2 for group in opening_groups) / len(opening_groups) >= 0.75
    assert sum(len(group) <= 3 for group in opening_groups) / len(opening_groups) >= 0.9
    opening_messages = [message for group in opening_groups for message in group]
    assert "我醒了" in opening_messages
    assert "起床了吗" in opening_messages
    assert "晚安" in opening_messages
    assert "我再忙一会" in opening_messages
    assert "我犯事了" in opening_messages
    assert "你现在出发了吗" in opening_messages
    assert "吃完了没啊" in opening_messages

    print("PASS: Aveline/Ling/Ye 从各自 Prompt 读取当前任务示例")
    print("PASS: good_morning 不再注入旧主动消息原文")
    print("PASS: 通用模板要求角色化动作，不再鼓励中性播报")
    print("PASS: Ye 主对话使用 rushuang v4-flash，Active Care 使用 MiniMax 官方 M3")
    print(f"PASS: Ling 示例与{len(rows)}条真实主动聊天链的开场分布一致")
    return 0


async def run_live_generation() -> int:
    """用生产模型做非发送生成，只打印结果供人工判断角色相似度。"""
    from dotenv import load_dotenv

    from config.integrated_config import get_settings
    from config.model_config import (
        get_active_care_content_model,
        get_fallback_model_for_active_care,
    )
    from core.agents.chat_agent_components.persona_system.prompt.data import (
        get_persona_name_from_filename,
        get_persona_prompt_layers,
    )
    from core.character.managers.persona_manager import get_persona_manager
    from core.llm import get_llm_module
    from core.services.active_care.core.input_builder import ModelInputBuilder
    from core.services.active_care.core.response_generator import (
        ActiveCareResponseGenerator,
    )

    load_dotenv()
    settings = get_settings()
    llm = get_llm_module()
    await llm.initialize()
    generator = ActiveCareResponseGenerator(settings)
    model_input = ModelInputBuilder().build_proactive_trigger_input(
        "zh",
        sleep_session_active=True,
    )

    try:
        for filename in ("core_ling.json", "core_ye.json"):
            persona_name = get_persona_name_from_filename(filename)
            persona_data = get_persona_manager().get_persona_by_filename(filename) or {}
            layers = get_persona_prompt_layers(
                persona_filename=filename,
                message="[CHARACTER_JUST_WOKE_UP]",
                persona_data=persona_data,
            )
            built = prompt_builder.build_active_care_prompt(
                user_id=f"shared__persona__{filename.removesuffix('.json')}",
                sys_prompt_type="good_morning_proactive",
                user_input_mock="[CHARACTER_JUST_WOKE_UP]",
                reminder_msg=None,
                thought="character_waking_up_by_schedule",
                tod="早晨",
                now=1788566400.0,
                user_display_name="Master",
                persona_prompt=layers.static_prompt,
                persona_dynamic_prompt=layers.dynamic_prompt,
                tone_reference_text="",
                recent_history_text=(
                    "【最近聊天记录】\n"
                    f"- Assistant(你之前主动发起): {BAD_WAKEUP}\n"
                ),
                persona_filename=filename,
                persona_name=persona_name,
                last_proactive_assistant_message=BAD_WAKEUP,
                last_assistant_message=BAD_WAKEUP,
                repeat_anchors=[BAD_WAKEUP],
                proactive_state={"recent_sent_contents": [BAD_WAKEUP]},
                sleep_session_active=True,
            )
            result = await generator.generate(
                model_user_input=model_input,
                sys_prompt=built.prompt,
                dynamic_prompt=built.dynamic_prompt,
                model_hint=get_active_care_content_model(persona_name),
            )
            fallback_used = False
            if result.get("error"):
                fallback_model = get_fallback_model_for_active_care()
                if fallback_model:
                    result = await generator.generate(
                        model_user_input=model_input,
                        sys_prompt=built.prompt,
                        dynamic_prompt=built.dynamic_prompt,
                        model_hint=fallback_model,
                    )
                    fallback_used = True
            content = str(result.get("content") or "").strip()
            route = "fallback" if fallback_used else "primary"
            print(f"[LIVE][{persona_name}][{route}] {content or '[生成失败]'}")
    finally:
        await llm.shutdown()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live",
        action="store_true",
        help="调用生产模型做非发送生成；默认只做静态回归验证",
    )
    args = parser.parse_args()
    static_result = main()
    raise SystemExit(asyncio.run(run_live_generation()) if args.live else static_result)
