"""被动回复策略的状态提示模板与 builder（reply_policy 的子模块）

集中管理以下内容：
- 状态提示模板（注入到 service_dynamic_context，让 LLM 表演困倦/被打断/刚做完）
- 强制唤醒概率递增表（让"被吵醒"更真实，不是固定 N 条就醒）
- build_xxx_hint() builder 函数

设计原则：
- 所有提示文案集中于此，方便调优
- builder 是纯函数（无副作用），可独立测试
- evaluate_reply_state 只调用 builder，不直接拼字符串

设计变更（2026-06-27）：
- 去掉占位消息池（zZz.../专注中...），DND/BUSY 第 1 条统一静默累积
- 真实场景下"消息没回"比"发个占位说睡着了"更自然
- 消息留到活动结束后（起床/做完）统一处理

按项目规则：单文件 ≤500 行，从 reply_policy.py 拆出。
"""

from typing import List



# ============================================================
# 简短人设提示（延迟回复 + 注入，让 LLM 表演状态）
# ============================================================

# 不可打扰但仍回复时（注入 prompt，让 LLM 表演困倦）
_DND_PERSONA_HINT = (
    "【状态提示】你正在睡觉，被消息吵醒。"
    "反应应该困倦、迷糊、可能有点起床气，回复要简短，"
    "可以打哈欠、揉眼睛、嘟囔，不要长篇大论。"
)

# 忙碌但延迟回复时（注入 prompt，让 LLM 表演被打断）
_BUSY_INTERRUPTED_PERSONA_HINT = (
    "【状态提示】你正在做事，被消息打断。"
    "回复可以简短一些，体现被打扰的感觉，但不要冷淡。"
    "可以提一句自己在做什么。"
)


# ============================================================
# 强制唤醒概率递增表（让"被吵醒"更真实，不是固定 N 条就醒）
# ============================================================

# key = 之前已拒回的消息数（不含本次），value = 本次被强制唤醒的概率
# 设计意图：睡得浅时 2-3 条就醒，睡得深时 5-6 条才醒，硬上限兜底防止无限拒回
_FORCE_WAKE_PROB_TABLE = [
    0.0,   # 第 1 条消息（之前拒回 0 条）：0% 醒，正常走 DND 流程
    0.08,  # 第 2 条（之前拒回 1 条）：8% 醒 —— 偶尔睡得浅
    0.25,  # 第 3 条：25% 醒 —— 开始被吵得有点醒了
    0.55,  # 第 4 条：55% 醒 —— 大概率醒了
    0.85,  # 第 5 条：85% 醒 —— 几乎肯定醒了
]


def _force_wake_probability(prev_count: int, hard_threshold: int) -> float:
    """拒回 prev_count 条后，本次被强制唤醒的概率

    Args:
        prev_count: 之前已拒回的消息数（不含本次）
        hard_threshold: 累计达到此数后 100% 唤醒（硬上限兜底）

    Returns:
        0.0 ~ 1.0
    """
    total = prev_count + 1  # 本次累计条数
    if total >= hard_threshold:
        return 1.0
    if prev_count < len(_FORCE_WAKE_PROB_TABLE):
        return _FORCE_WAKE_PROB_TABLE[prev_count]
    return 1.0  # 超出表范围，兜底 100%


# ============================================================
# 强制唤醒/打断/完成后处理 的"长提示"模板（注入 prompt）
# ============================================================

# 不可打扰且被强制唤醒（连发多条）时的人设提示模板
# {prev_count}: 前几条没回的消息数；{total_count}: 用户连发的总消息数（含本次）
_DND_FORCE_WAKE_TEMPLATE = (
    "【状态提示】你正在睡觉，被用户连续发了 {total_count} 条消息吵醒。\n"
    "前 {prev_count} 条消息你都没回（迷迷糊糊没听见），现在用户又发了一条终于把你彻底吵醒了。\n\n"
    "【重要】下面是用户发给你但还没回的所有消息（按时间顺序），请逐条回应每一条，不要只回最后一条：\n"
    "{messages}\n\n"
    "反应应该：\n"
    "- 困倦但清醒过来，意识到对方可能有急事或者就是要找你\n"
    "- 可以有起床气，但必须回应上面每一条消息的内容\n"
    "- 可以揉眼睛、打哈欠、嘟囔，但内容要有实质回应\n"
    "- 如果有具体内容（比如用户说了吃了什么、抱怨了什么），一定要回应这些具体内容\n"
    '- 不要只回"嗯""怎么了"这种敷衍的内容\n'
)

# 起床后处理累积消息的人设提示模板
# 触发条件：角色已不在 DND 状态（起床了），且有睡觉期间累积的未处理消息
_MORNING_AFTER_TEMPLATE = (
    "【状态提示】你刚才在睡觉，现在已经起床了。\n"
    "在你睡觉的时候，用户给你发了 {count} 条消息，你当时没回（睡着了）。\n\n"
    "【重要】下面是用户在你睡觉时发的所有消息（按时间顺序），请逐条回应每一条，不要只回最后一条：\n"
    "{messages}\n\n"
    "反应应该：\n"
    "- 自然地提到「刚醒」或者「看到你刚才/昨晚发的消息了」\n"
    "- 必须回应上面每一条消息的具体内容\n"
    "- 可以有刚起床的迷糊感，但内容要有实质回应\n"
    "- 如果有具体内容（比如用户说了吃了什么、抱怨了什么），一定要回应\n"
    "- 如果消息跨度较长（比如半夜到早晨），可以体现时间感\n"
)

# 忙碌时被强制打断（连发多条）的人设提示模板
# {prev_count}: 前几条没回的消息数；{total_count}: 用户连发的总消息数（含本次）
# {activity_verb}: 正在做的活动动词（学习/做饭...）
_BUSY_INTERRUPT_TEMPLATE = (
    "【状态提示】你正在{activity_verb}，被用户连续发了 {total_count} 条消息打断。\n"
    "前 {prev_count} 条消息你都没回（专注做事没看手机），现在用户又发了一条把你彻底打断了。\n\n"
    "【重要】下面是用户发给你但还没回的所有消息（按时间顺序），请逐条回应每一条，不要只回最后一条：\\n"
    "{messages}\n\n"
    "反应应该：\n"
    "- 从专注状态被拉回来，可能有点恍惚或被打断的不爽\n"
    "- 必须回应上面每一条消息的具体内容\n"
    "- 可以提一句自己在做什么、被吵到了\n"
    "- 如果有具体内容（比如用户说了吃了什么、抱怨了什么），一定要回应\n"
    '- 不要只回"嗯""怎么了"这种敷衍的内容\n'
)

# 忙碌结束后处理累积消息的人设提示模板
# 触发条件：角色已不在忙碌状态（做完了），且有忙碌期间累积的未处理消息
_BUSY_DONE_TEMPLATE = (
    "【状态提示】你刚才在{activity_verb}，现在做完了。\n"
    "在你做事的时候，用户给你发了 {count} 条消息，你当时没回（没看手机）。\n\n"
    "【重要】下面是用户在你做事时发的所有消息（按时间顺序），请逐条回应每一条，不要只回最后一条：\n"
    "{messages}\n\n"
    "反应应该：\n"
    "- 自然地提到「刚做完xx」或者「刚才没看手机」\n"
    "- 必须回应上面每一条消息的具体内容\n"
    "- 可以有刚做完事的放松感，但内容要有实质回应\n"
    "- 如果有具体内容（比如用户说了吃了什么、抱怨了什么），一定要回应\n"
    "- 如果消息跨度较长（比如学习了一上午），可以体现时间感\n"
)

_PLAN_TRANSITION_TEMPLATE = (
    "【状态提示】你的下一个计划快到了：大约 {remaining_minutes} 分钟后，"
    "{start_time} 左右要去{next_activity}。\n"
    "这条回复里必须自然体现你已经意识到这个时间点，不要机械报时，也不要完全不提。\n"
    "你可以根据聊天氛围自行选择其一：\n"
    "- 如果还想继续聊几句，可以自然地提到自己把接下来的安排稍微顺延一下\n"
    "- 如果该去做下一项了，就礼貌收尾、打个招呼再离开\n"
    "- 不要突然硬切断，也不要假装自己完全没有后续安排"
)

_SOFT_DELAY_REPLY_TEMPLATE = (
    "【状态提示】你刚刚在{activity_verb}，不是故意不理人，"
    "只是隔了大约 {delay_seconds} 秒才看到消息。\n"
    "回复要自然，像是稍微隔了一会儿才回过来，"
    "可以轻轻带一句自己刚才在做什么，但不要解释得很机械。"
)


# ============================================================
# builder 函数（纯函数，可独立测试）
# ============================================================

def _format_messages_block(messages: List[str]) -> str:
    """把消息列表格式化为带编号的预览块（截断过长消息）"""
    lines = []
    for i, msg in enumerate(messages, 1):
        preview = msg[:200] + ("..." if len(msg) > 200 else "")
        lines.append(f"{i}. {preview}")
    return "\n".join(lines)


def force_wake_probability(prev_count: int, hard_threshold: int) -> float:
    """对外暴露的强制唤醒概率（外部测试用）"""
    return _force_wake_probability(prev_count, hard_threshold)


def build_force_wake_hint(accumulated_messages: List[str]) -> str:
    """构建"被吵醒且前几条没回"的人设提示

    Args:
        accumulated_messages: 前几条被拒回的用户消息列表（按时间顺序）

    Returns:
        注入 prompt 的人设提示
    """
    prev_count = len(accumulated_messages)
    if prev_count == 0:
        return _DND_PERSONA_HINT

    messages_block = _format_messages_block(accumulated_messages)
    total_count = prev_count + 1
    return _DND_FORCE_WAKE_TEMPLATE.format(
        prev_count=prev_count,
        total_count=total_count,
        messages=messages_block,
    )


def build_morning_after_hint(accumulated_messages: List[str]) -> str:
    """构建"起床后处理累积消息"的人设提示

    触发条件：角色已不在 DND 状态（起床了），
    且有睡觉期间累积的未处理消息。

    Args:
        accumulated_messages: 睡觉期间用户发的消息列表（按时间顺序）

    Returns:
        注入 prompt 的人设提示，空列表返回空字符串
    """
    count = len(accumulated_messages)
    if count == 0:
        return ""

    messages_block = _format_messages_block(accumulated_messages)
    return _MORNING_AFTER_TEMPLATE.format(count=count, messages=messages_block)


def build_busy_interrupt_hint(
    accumulated_messages: List[str],
    activity_verb: str = "做事",
) -> str:
    """构建"忙碌时被强制打断且前几条没回"的人设提示

    Args:
        accumulated_messages: 前几条被拒回的用户消息列表（按时间顺序）
        activity_verb: 正在做的活动动词（"学习"/"做饭"...），默认"做事"

    Returns:
        注入 prompt 的人设提示
    """
    prev_count = len(accumulated_messages)
    if prev_count == 0:
        return _BUSY_INTERRUPTED_PERSONA_HINT

    messages_block = _format_messages_block(accumulated_messages)
    total_count = prev_count + 1
    return _BUSY_INTERRUPT_TEMPLATE.format(
        activity_verb=activity_verb,
        prev_count=prev_count,
        total_count=total_count,
        messages=messages_block,
    )


def build_busy_done_hint(
    accumulated_messages: List[str],
    activity_verb: str = "做事",
) -> str:
    """构建"忙碌结束后处理累积消息"的人设提示

    触发条件：角色已不在忙碌状态（做完了），
    且有忙碌期间累积的未处理消息。

    Args:
        accumulated_messages: 忙碌期间用户发的消息列表（按时间顺序）
        activity_verb: 刚做完的活动动词（"学习"/"做饭"...），默认"做事"

    Returns:
        注入 prompt 的人设提示，空列表返回空字符串
    """
    count = len(accumulated_messages)
    if count == 0:
        return ""

    messages_block = _format_messages_block(accumulated_messages)
    return _BUSY_DONE_TEMPLATE.format(
        activity_verb=activity_verb,
        count=count,
        messages=messages_block,
    )


def build_plan_transition_hint(
    next_activity: str,
    start_time: str,
    remaining_minutes: int,
) -> str:
    """构建“下一个计划即将开始”的提示。"""
    hint = _PLAN_TRANSITION_TEMPLATE.format(
        next_activity=next_activity,
        start_time=start_time,
        remaining_minutes=max(1, int(remaining_minutes)),
    )
    if any(keyword in str(next_activity) for keyword in ("睡", "午休", "起床")):
        hint += (
            "\n- 这次如果决定收尾，优先自然提一句自己准备去睡/去休息了，"
            "不要像普通白天聊天那样直接忽略这件事"
        )
    return hint


def build_soft_delay_reply_hint(activity_verb: str, delay_seconds: int) -> str:
    """构建轻活动下静默几十秒后再回复的人设提示。"""
    return _SOFT_DELAY_REPLY_TEMPLATE.format(
        activity_verb=activity_verb,
        delay_seconds=max(1, int(delay_seconds)),
    )


__all__ = [
    # 概率
    "force_wake_probability",
    # 长 hint builder
    "build_force_wake_hint",
    "build_morning_after_hint",
    "build_busy_interrupt_hint",
    "build_busy_done_hint",
    "build_plan_transition_hint",
    "build_soft_delay_reply_hint",
]
