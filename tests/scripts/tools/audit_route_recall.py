"""审计关键词路由的真实召回率：用口语化说法去打高频工具。

只读脚本。与 audit_tool_reachability.py 的分工：
- reachability 看「有没有路径能看到」；
- 本脚本看「真人说法能不能真的触发那条路径」。
路由是子串匹配，关键词写成三字短语时用户中间插个字就漏了，这里用日常问法量化漏召率。

运行：
    venv_core/Scripts/python.exe tests/scripts/tools/audit_route_recall.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PERSONA = "core_aveline.json"

# (真人说法, 期望被召回的工具)。说法刻意不照抄关键词，模拟口语里插字、换说法的情况。
CASES: list[tuple[str, str]] = [
    # 回忆 / 聊天记录
    ("你还记得上次我们聊的那家店吗", "search_chat_history"),
    ("咱之前提过的那个事儿是什么来着", "search_chat_history"),
    ("那次跟你讲过的电影叫啥", "search_chat_history"),
    ("帮我翻一下聊天记录", "search_chat_history"),
    ("之前说过的那个餐厅在哪", "search_chat_history"),
    # 记忆与偏好
    ("你还记得我喜欢喝什么吗", "search_memory"),
    ("我说过的习惯你还记着吗", "search_memory"),
    ("以后我都喝美式，记住了", "record_preference"),
    # 日记
    ("今天发生的事帮我写进日记", "write_diary"),
    ("把今天的日记给我看看", "read_diary"),
    ("这个月都发生了什么啊", "read_monthly_summary"),
    # 计划与待办
    ("我今天要干点啥来着", "get_plan"),
    ("明天再背一百个单词吧，加上", "add_plan_item"),
    ("数学写完了", "mark_plan_item_status"),
    ("帮我记一下明天要交作业", "manage_todo"),
    # 日常记录
    ("我刚吃了碗面", "record_daily_activity"),
    ("昨天晚上十一点多睡的", "update_sleep_record"),
    ("今天都干了点啥", "get_daily_summary"),
    # 提醒
    ("二十分钟后叫我去晾衣服", "set_reminder"),
    ("明早八点提醒我起床", "set_reminder"),
    # 时间与天气
    ("这都几点了", "get_current_time"),
    ("外面下没下雨", "get_weather"),
    ("明天出门要带伞吗", "get_weather"),
    # 学习
    ("这道物理题我还是没搞懂", "study_record_confusion"),
    ("我哪块掌握得不好", "get_study_profile"),
    ("这个公式再给我讲一遍", "study_record_teaching"),
    # 食物与商城
    ("给你买了块蛋糕", "feed_food"),
    ("冰箱里还有啥吃的", "show_inventory"),
    ("我想吃火锅", "crave_food"),
    # 同伴与状态
    ("Aveline现在在干嘛呢", "check_peer_status"),
    ("你饿不饿", "get_bionic_state"),
    ("你今天都做了什么", "get_character_daily_plan"),
    # 人物档案与健康
    ("Ling是我什么人来着", "query_person_profile"),
    ("我今天走了多少步", "query_health_data"),
    # 主动关怀
    ("你别老给我发消息了", "adjust_active_care_frequency"),
    ("让我安静一会儿", "pause_active_care"),
]


# 补关键词的代价是可能误召回：这里用一批纯闲聊确认没有污染常驻集合。
# 期望是「几乎没有额外工具被加载」，否则说明词根加得太泛。
SMALL_TALK = [
    "今天心情还不错",
    "嗯嗯",
    "你今天真好看",
    "我好累啊",
    "哈哈哈哈哈",
    "跟你说个好玩的事",
    "我想睡觉",
    "晚安",
    "好无聊啊",
    "你在干嘛呢",
]


def main() -> int:
    from core.tools.tool_policy import select_role_tools

    hits: dict[str, int] = defaultdict(int)
    total: dict[str, int] = defaultdict(int)
    missed: list[tuple[str, str]] = []

    for utterance, expected in CASES:
        total[expected] += 1
        picked = select_role_tools(utterance, persona_filename=PERSONA)
        if expected in picked:
            hits[expected] += 1
        else:
            missed.append((expected, utterance))

    total_cases = len(CASES)
    total_hit = sum(hits.values())
    print("=" * 74)
    print(f"关键词路由召回审计（角色 {PERSONA}）")
    print(f"共 {total_cases} 句口语问法，命中 {total_hit} 句，召回率 {total_hit / total_cases:.0%}")
    print("=" * 74)

    print("\n按工具统计（漏召回的排前面）")
    rows = sorted(total, key=lambda name: (hits[name] / total[name], -total[name], name))
    for name in rows:
        rate = hits[name] / total[name]
        flag = "OK  " if rate == 1 else "漏  "
        print(f"  {flag} {name:<28} {hits[name]}/{total[name]}")

    if missed:
        print(f"\n漏召回明细（{len(missed)} 句）")
        for name, utterance in missed:
            print(f"  - [{name}] {utterance}")

    baseline = set(select_role_tools("嗯", persona_filename=PERSONA))
    print(f"\n闲聊误召回检查（常驻基线 {len(baseline)} 个）")
    noisy = 0
    for utterance in SMALL_TALK:
        extra = [n for n in select_role_tools(utterance, persona_filename=PERSONA) if n not in baseline]
        if extra:
            noisy += 1
            print(f"  +{len(extra)} {utterance} -> {', '.join(extra)}")
    if not noisy:
        print("  无额外工具被加载")
    else:
        print(f"  {noisy}/{len(SMALL_TALK)} 句闲聊触发了额外工具，确认是否可接受")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
