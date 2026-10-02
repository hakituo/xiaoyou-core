"""回归消息文案与决策提示构建。"""

from __future__ import annotations

from typing import Literal, Optional

from core.services.character_daily.activity_model import ACTIVITY_VERBS_ONGOING, ActivityType


# 角色 ID → QQ 人设文件名：权威源已收敛到 personas.get_qq_persona_filename
# （读 multi_qq_config.json 的 persona_filename 字段），与 goodnight_proactive /
# good_morning_proactive 共用同一数据源，新增 QQ 角色时配置即生效。
# 注意：人设文件名必须与 QQ adapter 登记的 persona_filename 完全一致。
# executor 会用 persona_filename 构建 conversation_id（__persona__<slug>），
# QQ 机器人客户端 receiver.py 在 dual QQ 模式下会校验 conversation_id 的 persona 后缀
# 是否匹配当前 adapter 的 persona_filename，不一致会丢弃消息（服务端日志显示"已实时送达"
# 但用户收不到）。现在 Aveline/Ling直接用核心人设（core_aveline.json / core_ling.json），
# 只要与 multi_qq_config.json 保持一致即可，两边不再有"QQ 专属 / 核心"之分。
# 本模块的两个调用方（send_activity_return_message、activity_transition）都固定
# client_type="qq"，因此统一使用 QQ 人设文件名是正确的。
# 未知 role_id 返回 None：避免未接入 active_care 的角色（如 xiaolu/yeye）
# 被误挂到 aveline 名义发消息，由调用方检查后跳过。
from core.services.dual_role.personas import get_qq_persona_filename as _get_qq_persona_filename

_WORK_RETURN_TEMPLATE = (
    "你（{role_name}）刚才被用户打断，暂时放下了「{activity_verb}」来陪他聊天。\n"
    "现在聊天窗口快结束了，请你根据用户最近这条消息的氛围，判断该回去了还是再陪一会儿：\n"
    "\n"
    "- 如果用户明显在挽留你（比如『再聊会』『别走』『等等』『还有话跟你说』『今天有点不开心』等），\n"
    "  自然地说自己把安排往后推一推、再陪他一会儿，态度温和，先回应他的具体原因；\n"
    "- 如果用户没有挽留、聊得差不多了、或者已经道别（『去吧』『嗯嗯』『拜拜』之类），\n"
    "  就温和地告诉用户你该回去继续{activity_verb}了，明确提一句要去做什么。\n"
    "\n"
    "要求：\n"
    "- 1-2 句话，语气像真的在和他道别或顺延，不要机械\n"
    "- 如果决定回去，必须明确提到你要回去继续做什么\n"
    "- 如果决定顺延，不要直接说『好，再聊会』，可以自然带一句『安排往后挪一下』之类的话\n"
    "- 不要在结尾敷衍反问『还有事吗』『还要我陪你吗』，这种反问很奇怪\n"
    "- 如果用户有具体挽留原因（比如『今天有点不开心』『想跟你说件事』），优先回应这个原因再决定"
)

# 活动自然切换时的告别/顺延决策模板（非 /打断 场景，计划时段到了自然切换）
# {role_name}: 角色显示名（如 Ling），不要用内部 ID
# {activity_verb}: 即将开始的活动动词（学习/做饭/午休...）
_ACTIVITY_START_FAREWELL_TEMPLATE = (
    "你（{role_name}）刚才在陪用户聊天，但接下来的计划时间到了，你该去{activity_verb}了。\n"
    "请主动给用户发一条消息，根据用户最近消息的氛围判断该顺延还是告别：\n"
    "\n"
    "- 如果用户明显还想继续聊（比如最近消息有挽留、撒娇、分享重要事、说『再聊会儿』），\n"
    "  自然地说自己把安排稍微往后推一推，再陪一会儿；\n"
    "- 如果聊得差不多了、用户最近消息只是简单回应（『嗯』『哈哈』『好』之类）或已道别，\n"
    "  就温和地告别，说自己得去{activity_verb}了。\n"
    "\n"
    "要求：\n"
    "- 1-2 句话，语气自然，像真的在道别或顺延，不要机械\n"
    "- 如果决定告别，必须明确提到你要去做什么\n"
    "- 如果决定告别，不要提问（你要去做事了不该期待回复）\n"
    "- 如果决定顺延，可以轻轻带一句『再聊会儿』之类的话，不要假装自己完全没有后续安排\n"
    "- 不要突然硬切断（聊得好好的突然说要走很奇怪），但也不要每次都顺延"
)

# 聊天中入睡的告别模板（到了睡觉时间但用户正在聊天）
# {role_name}: 角色显示名（如 Ling），不要用内部 ID
_SLEEP_DURING_CHAT_FAREWELL_TEMPLATE = (
    "你（{role_name}）刚才在陪用户聊天，但现在已经到了你的睡觉时间。\n"
    "请主动给用户发一条消息，根据聊天氛围自行判断：\n"
    "- 如果聊得正起劲、用户明显还想继续，可以自然地说自己再陪一会儿，稍微晚点睡\n"
    "- 如果聊得差不多了、或者真的困了该睡了，就温和地告别，说自己得去睡了\n"
    "要求：\n"
    "- 1-2 句话，语气自然，像真的在道别或顺延\n"
    "- 如果决定去睡，必须明确包含晚安/告别词（如『晚安』『先去睡了』『困了，睡啦』等）\n"
    "- 如果决定顺延，可以轻轻带一句'再聊会儿'之类的话，不要提晚安\n"
    "- 不要突然硬切断（聊得好好的突然说晚安很奇怪），也不要假装没到睡觉时间\n"
    "- 如果决定去睡，禁止提问（你要睡了不该期待回复）"
)

_SLEEP_RETURN_TEMPLATE = (
    "你（{role_name}）半夜被叫醒后跟用户聊了一会儿，现在决定睡回去继续睡觉。\n"
    "主动给用户发一句简短的告别消息，让他知道你睡去了。\n"
    "要求：\n"
    "- 1-2 句话即可\n"
    "- 必须明确包含睡回去的告别词（如『我先去睡了』『困了，继续睡啦』『再睡会儿』等）\n"
    "- 不要再发『晚安』\n"
    "- 禁止提问"
)


# 做事结束后主动处理累积消息的指令模板
# {role_name}: 角色显示名（如 Ling），不要用内部 ID
# {activity_verb_ongoing}: 刚做的活动进行时动词（如"学习"）
# {activity_verb_done}: 刚做的活动完成时动词（如"做完题"）
# {pending_count}: 累积消息条数
# {messages_block}: 用户消息列表（已按时间顺序编号）
_BUSY_DONE_ACTIVE_TEMPLATE = (
    "你（{role_name}）刚才在{activity_verb_ongoing}，现在{activity_verb_done}了，刚有空看手机。\n"
    "在你做事的时候，用户给你发了 {pending_count} 条消息，你当时没回（专注做事没看见）。\n\n"
    "【重要】下面是用户在你做事时发的所有消息（按时间顺序），请主动发一条消息回应：\n"
    "{messages_block}\n\n"
    "要求：\n"
    "- 1-2 句话开头，自然地提到「刚{activity_verb_done}」或者「刚才没看手机」\n"
    "- 然后逐条回应上面每一条消息的具体内容，不要只回最后一条\n"
    "- 如果用户消息里有具体内容（比如说了吃了什么、抱怨了什么、分享了什么），一定要回应这些具体内容\n"
    "- 不要敷衍地只回『嗯』『看到了』，要有实质回应\n"
    "- 如果消息跨度较长（比如学习了一上午），可以体现时间感\n"
    "- 不要在结尾问『还有事吗』这种敷衍反问，自然收尾即可"
)


def _resolve_role_name(role_id: str) -> str:
    """把 role_id 解析成角色显示名（``ling`` → ``Ling``）。

    主动消息的 instruction 里用第二人称称呼角色，必须给显示名而不是内部 ID：
    模型看到「你（ling）」时角色代入会被削弱，容易写出没有主语的句子
    （如「要上课了先回去了」，读起来像用户在报备自己的日程）。
    详见 docs/important/ACTIVE_CARE_REPLY_CONTINUITY_PLAN.md R5 / P4。

    解析不出时退回原 role_id，保证不因注册表异常而丢失称呼。
    """
    from core.services.dual_role.personas import resolve_role_name

    return resolve_role_name(role_id)


def resolve_persona_filename(role_id: str) -> Optional[str]:
    """根据 role_id 解析 persona 文件名（委托 personas 权威注册表）。

    未知 role_id 返回 None：避免未接入 active_care 的角色
    被误挂到 aveline 名义发消息。
    """
    return _get_qq_persona_filename(str(role_id or "").strip().lower())


def _resolve_activity_verb(activity: str) -> str:
    """把活动类型转成自然语言动词（进行时）。"""
    activity_type = ActivityType.from_str(activity)
    return ACTIVITY_VERBS_ONGOING.get(activity_type, "做事")


def _resolve_activity_verb_done(activity: str) -> str:
    """把活动类型转成自然语言动词（完成时，如"做完题"）。"""
    activity_type = ActivityType.from_str(activity)
    # ACTIVITY_VERBS 是完成时映射（"做完题"/"看完书"/"做完家务"...）
    from core.services.character_daily.activity_model import ACTIVITY_VERBS
    return ACTIVITY_VERBS.get(activity_type, "做完事")


def build_busy_done_active_instruction(
    role_id: str,
    activity: str,
    pending_messages: list[str],
) -> str:
    """构建"做事结束后主动处理累积消息"的 specific_instruction。

    用于：角色从 BUSY 切回 CHAT_ELIGIBLE 时，主动发消息回应做事期间累积的消息。
    注入 active_care executor.trigger_message 的 specific_instruction 字段。

    Args:
        role_id: 角色 ID
        activity: 刚做完的活动类型字符串
        pending_messages: 做事期间累积的用户消息列表（按时间顺序）

    Returns:
        注入 executor 的 specific_instruction
    """
    role_id = str(role_id or "").strip().lower()
    activity_verb_ongoing = _resolve_activity_verb(activity)
    activity_verb_done = _resolve_activity_verb_done(activity)
    # 格式化消息块：每条截断到 200 字，超过加省略号
    lines = []
    for i, msg in enumerate(pending_messages, 1):
        text = str(msg or "")
        preview = text[:200] + ("..." if len(text) > 200 else "")
        lines.append(f"{i}. {preview}")
    messages_block = "\n".join(lines)
    role_name = _resolve_role_name(role_id)
    return _BUSY_DONE_ACTIVE_TEMPLATE.format(
        role_name=role_name,
        activity_verb_ongoing=activity_verb_ongoing,
        activity_verb_done=activity_verb_done,
        pending_count=len(pending_messages),
        messages_block=messages_block,
    )


def build_return_instruction(
    role_id: str,
    activity: str,
    return_type: Literal["work", "sleep"],
) -> str:
    """构建回归消息的 specific_instruction。

    Args:
        role_id: 角色 ID
        activity: 被中断/要回归的活动类型（work 场景）或 sleeping（sleep 场景）
        return_type: work 表示回去做事，sleep 表示睡回去

    Returns:
        注入 active_care executor 的 specific_instruction
    """
    role_id = str(role_id or "").strip().lower()
    role_name = _resolve_role_name(role_id)
    if return_type == "sleep":
        return _SLEEP_RETURN_TEMPLATE.format(role_name=role_name)

    activity_verb = _resolve_activity_verb(activity)
    return _WORK_RETURN_TEMPLATE.format(role_name=role_name, activity_verb=activity_verb)


def build_activity_start_farewell_instruction(
    role_id: str,
    activity: str,
) -> str:
    """构建活动自然切换时的告别/顺延 instruction。

    用于：角色从"可聊天"切到"忙碌"（如学习/做饭）时，若用户最近在聊天，
    主动发一条消息让 LLM 判断是顺延还是告别去做事。

    Args:
        role_id: 角色 ID
        activity: 即将开始的活动类型字符串

    Returns:
        注入 active_care executor 的 specific_instruction
    """
    role_id = str(role_id or "").strip().lower()
    role_name = _resolve_role_name(role_id)
    activity_verb = _resolve_activity_verb(activity)
    return _ACTIVITY_START_FAREWELL_TEMPLATE.format(
        role_name=role_name,
        activity_verb=activity_verb,
    )


def build_sleep_during_chat_farewell_instruction(
    role_id: str,
) -> str:
    """构建聊天中入睡的告别/顺延 instruction。

    用于：到了睡觉时间但用户正在聊天，让 LLM 判断是顺延还是告别去睡。

    Args:
        role_id: 角色 ID

    Returns:
        注入 active_care executor 的 specific_instruction
    """
    role_id = str(role_id or "").strip().lower()
    role_name = _resolve_role_name(role_id)
    return _SLEEP_DURING_CHAT_FAREWELL_TEMPLATE.format(role_name=role_name)


def build_return_decision_hint(
    activity: str,
    return_type: Literal["work", "sleep"],
) -> str:
    """构建用户回复回归消息后的决策提示。

    注入到被动回复的 prompt 中，让 LLM 根据用户回复内容决定继续聊还是回去。
    """
    if return_type == "sleep":
        return (
            "【状态提示】你刚才告诉用户你要睡回去了，他又回了一条消息。\n"
            "请根据他这条回复的内容判断：\n"
            "- 如果他明显还想继续聊（比如挽留、撒娇、说重要的事、说『再聊会』等），"
            "就自然地回应他，并暗示自己可以再醒一会儿。\n"
            "- 如果他只是简单晚安或同意你去睡（如『晚安』『去吧』『嗯嗯』），"
            "就礼貌道晚安，然后真的去睡，不要继续长篇大论。\n"
            "- 不要突然生硬地切断，也不要假装没有说过要睡回去。"
        )

    activity_verb = _resolve_activity_verb(activity)
    return (
        f"【状态提示】你刚才告诉用户你要回去继续{activity_verb}了，他又回了一条消息。\n"
        "请根据他这条回复的内容判断：\n"
        "- 如果他明显还想继续聊（比如挽留、撒娇、说重要的事、说『再聊会』等），"
        "就自然地回应他，并暗示自己可以再陪一会儿。\n"
        "- 如果他只是简单道别或同意你去做事（如『去吧』『嗯嗯』『拜拜』），"
        "就礼貌道别，然后真的去做事，不要继续长篇大论。\n"
        "- 不要突然生硬地切断，也不要假装没有说过要回去。"
    )
