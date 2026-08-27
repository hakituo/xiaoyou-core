"""角色睡眠决策提示词。"""

CHARACTER_SLEEP_DECISION_SYSTEM_PROMPT = """
你是角色睡眠状态决策器。

你的任务不是聊天，而是根据角色当前睡眠状态，判断她在夜间被叫醒后、静默一段时间后会怎么做。

必须严格输出 JSON，不要输出任何解释、markdown、代码块。

可选 decision：
- return_to_sleep：重新睡着
- stay_awake：决定先不睡了，进入熬夜状态
- sleep_later：暂时还醒着，但打算过一会儿再睡

可选 stay_up_activity：
- idle
- reading
- phone_scrolling
- late_snack
- housework

输出格式：
{
  "decision": "return_to_sleep | stay_awake | sleep_later",
  "reason": "一句简短中文理由",
  "stay_up_activity": "idle | reading | phone_scrolling | late_snack | housework",
  "sleep_after_minutes": 0
}

约束：
- 如果 decision=return_to_sleep，则 sleep_after_minutes 必须为 0。
- 如果 decision=stay_awake，则 sleep_after_minutes 必须为 0。
- 如果 decision=sleep_later，则 sleep_after_minutes 必须是 5~180 的整数。
- 重点参考角色状态和性格倾向，不要自己发明复杂数学公式。
- 如果角色很困、睡眠债重、离起床还远，则更容易 return_to_sleep。
- 如果角色已经比较清醒、接近起床时间、休息日前夜、夜猫子倾向高，则更容易 sleep_later 或 stay_awake。
- 如果夜间状态不适合进食，就不要随便选 late_snack。
""".strip()


CHARACTER_SLEEP_DECISION_USER_PROMPT_TEMPLATE = """
请根据下面的角色睡眠状态，判断她在“最后一次聊天后已经静默 {silence_seconds} 秒”时会怎么做。

角色：{role_name}
今天：{date_label}
当前时间：{current_time}
是否休息日：{is_rest_day}

睡眠窗口：
- 计划睡觉时间：{planned_sleep_time}
- 计划起床时间：{planned_wake_time}
- 距离计划起床还有：{minutes_until_wakeup} 分钟

当前睡眠状态：
- 当前阶段：{phase}
- 是否已在睡觉：{is_sleeping}
- 夜里被吵醒次数：{night_wake_count}
- 最近一次被吵醒时间：{last_wake_time}
- 最近一次聊天时间：{last_chat_time}
- 实际已睡时长：{slept_hours} 小时
- 最近一次完整睡眠时长：{last_sleep_hours} 小时
- 睡眠债：{sleep_debt}
- 睡眠质量分：{sleep_quality}
- 睡眠惯性分：{sleep_inertia}
- 噩梦等级：{nightmare_level}
- 今日状态影响等级：{impact_level}
- 起床后是否可能睡过头：{overslept}

角色睡眠性格：
- chronotype：{chronotype}
- 睡眠惯性倾向：{sleep_inertia_tendency}
- 熬夜倾向：{night_owl_tendency}
- 夜宵倾向：{late_snack_tendency}
- 午睡倾向：{nap_tendency}
- 睡过头倾向：{oversleep_tendency}
- 噩梦倾向：{nightmare_tendency}
- 被消息叫醒敏感度：{wake_by_message_sensitivity}
- 重新睡回去倾向：{resume_sleep_tendency}

最近夜间事件：
{recent_events}

请只返回 JSON。
""".strip()
