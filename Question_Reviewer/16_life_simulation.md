# 生命模拟与自动进食

本分类共 7 条记录。按时间倒序（最新在前）排列。

---

### Q2026070401 AI 永久低精力（energy 一直 0 或十几） (2026-07-04)

*   **问题描述**: AI 一直跟用户说精力很低，只有十几，而且说现在是 0。状态文件显示 energy=0，nightmare_level=severe，impact_level=severe，sleep_inertia_score=60.5。
*   **复现步骤**:
    1. 查看 cache/life_stats_state.json，发现 energy=0 且 nightmare/impact 都是 severe
    2. 分析 life_stats.py 的 decay_stats 逻辑，发现 impact_level=severe 会额外扣 0.1 energy/分钟，sleep_inertia_score>=30 再扣 0.02
    3. 追溯 sleep_manager.py，发现 nightmare_level 一旦设置永不清零，导致 impact_level 永久非 none
    4. 检查 _update_runtime_state，发现跨天只更新 state.date，不重置任何日级字段
*   **预期行为**:
    1. AI 精力应该能正常恢复，白天衰减合理（0.1~0.2/分钟），睡觉时恢复 0.42/分钟
    2. nightmare_level / impact_level 等日级字段应该在跨天时重置为 none
*   **实际行为**:
    1. energy 永久为 0，AI 一直说精力很低
    2. nightmare_level=severe 永久残留，impact_level 每次起床都被重算为 severe
    3. 白天每分钟扣 0.22~0.32 energy，从满血到 0 只要 5-8 小时
    4. character_daily 把角色永久钉在 SLEEP_RECOVERY 活动
    5. active_care 的 due_reminder 被长期推迟，主动关怀被压制
*   **根因**:
    1. sleep_manager.py 缺失跨天重置逻辑，9 个日级字段一旦设置永不清零
    2. _maybe_roll_nightmare 的守卫 if state.nightmare_level != none: return 导致死循环
*   **修复方案**:
    1. 在 _update_runtime_state 开头加跨天检测，调用新增的 _reset_daily_fields 方法
    2. 重置 nightmare_level/impact_level/sleep_quality_score/sleep_inertia_score/sleep_debt_hours/night_wake_count/last_sleep_duration_hours/overslept/night_wake/quality_impact
    3. 手动清理两个状态文件的僵尸值
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\role_sleep\verify_daily_reset_sleep_fields.py`
    2. `验证脚本覆盖 4 个场景：跨天重置触发、同一天不重置、噩梦摇骰子不再卡住、端到端 energy 不被僵尸值拖累`

### 10.128 AUTO_EAT LLM选食永远fallback随机（max_tokens不足） (2026-06-18)

*   **问题描述**: 自动进食模块每次 LLM 选食都 fallback 到随机选择，日志显示“理由: 随机选的”
*   **复现步骤**:
    1. 饥饿/口渴值低于阈值，触发自动进食
    2. `_choose_food_by_llm` 调用 `scheduler.submit_llm_task(prompt, max_tokens=120)`
    3. LLM 返回的 JSON 可能被截断（max_tokens 不足），`extract_json_object` 返回 None
    4. `food_id` 为空，触发 fallback 随机选择
*   **根本原因**: `max_tokens=120` 太小，LLM 响应 JSON（含中文 reason）可能超过 120 token 被截断，导致 JSON 不完整无法解析
*   **修复方法**: `max_tokens` 从 120 提升到 512；新增 always-on 日志（raw_out 为空、JSON 解析失败时输出详细信息）
*   **教训**: LLM 输出中文 JSON 时需预留足够 token（中文每个字约 2-3 token）；关键 LLM 调用不应只在 debug 模式下输出结果

### 10.127 AUTO_EAT LLM选食失败 KeyError('food_id') (2026-06-15)

*   **问题描述**: 自动进食模块日志反复出现 `LLM选食失败: '"food_id"'`，导致每次都 fallback 到随机选食
*   **复现步骤**:
    1. 饥饿/口渴值低于阈值，触发自动进食
    2. `_choose_food_by_llm` 构建 prompt 并调用 `AUTO_EAT_DECISION_PROMPT.format(...)`
    3. `format()` 抛出 `KeyError('food_id')`
*   **根本原因**: `AUTO_EAT_DECISION_PROMPT` 中包含 JSON 示例 `{"food_id":"候选中的id","reason":"简短原因"}`，Python 的 `str.format()` 将 `{food_id}` 和 `{reason}` 解析为占位符，但调用者只传了 `target_type`/`hunger`/`thirst`/`candidates_text` 四个参数，未提供 `food_id` 和 `reason`
*   **修复方法**: 将 JSON 示例中的 `{`/`}` 转义为 `{{`/`}}`，即 `'{{"food_id":"候选中的id","reason":"简短原因"}}'`
*   **教训**: 在使用 `str.format()` 的模板中，任何字面量花括号都必须转义（`{{`/`}}`），尤其是 JSON 示例

### 10.118 心情一直为0 + prompt直接注入状态 (2026-05-30)

*   **问题描述**: 七濑澪提到"Ling心情还是零分"，但心情应该是80分默认值
*   **复现步骤**:
    1. 查看 actor_states.json，Ling的 mood_score 为 0.0
    2. 查看 qq_peer_context.py 的 `_get_peer_bio_summary` 函数
    3. 发现读取的是 `actor_state.get("mood")`，但实际字段是 `mood_score`
    4. 另外发现 `_get_peer_bio_summary` 结果直接注入 prompt，七濑澪不需要调用工具就能看到状态
*   **预期行为**:
    1. 心情字段正确读取 `mood_score`
    2. mood_score 不会无限下降到 0
    3. 状态信息通过工具调用获取，而非直接注入 prompt
*   **实际行为**:
    1. 字段名错误导致心情永远读不到
    2. hunger/thirst 低于阈值时 mood 每分钟 -0.6，最终降到 0 无法恢复
    3. 状态被直接注入 prompt，绕过了工具调用机制
*   **根本原因**: 字段名不匹配 + 缺少 mood 最低保护 + prompt 直接注入设计问题
*   **修复**: 
    1. `qq_peer_context.py` 中 `mood` → `mood_score`
    2. `actor_manager.py` 中设置最低值 10 分，基本需求满足时 mood +0.2 恢复
    3. 删除 `_get_peer_bio_summary` 函数，注册 `CheckPeerStatusTool` 工具供 LLM 按需调用
*   **状态**: ✅ 已修复

### 10.39 handler.py 调用已删除的 EmotionResponder.get_response_strategy 导致硬件控制指令永远丢失 (2026-04-26)

*   **问题描述**: `core/agents/chat_agent_components/handler.py:675` 调用 `agent.emotion_manager.get_response_strategy(user_id)`，但该方法随旧 `EmotionResponder` 一起被删除，导致 `strategy` 永远为 `None`，后续的硬件控制指令（呼吸灯颜色/频率）无法传递到前端。由于被 try/except 包裹，不会崩溃但功能静默失效。
*   **复现步骤**:
    1. 启动服务，发送任意消息
    2. 观察 handler.py 中 `strategy` 变量，始终为 `None`
    3. 前端永远收不到硬件控制指令
*   **预期行为**: `get_response_strategy` 应返回包含硬件控制意图的策略对象，前端可根据情绪变化调整呼吸灯。
*   **实际行为**: `strategy` 为 `None`，硬件控制指令丢失。
*   **修复方案**: 在 `EmotionManager` 中新增 `get_response_strategy()` 方法，返回 `ResponseStrategy` dataclass，`metadata` 中包含 `_HardwareIntent` 对象（兼容 handler.py 的 `to_dict()` 调用链）。

### 10.39 ActorManager.get_actor_life_state 浅拷贝导致外部可意外修改内部状态 (2026-04-26)

*   **问题描述**: `get_actor_life_state` 使用 `dict(st)` 浅拷贝，嵌套的 `food_inventory`（list）和 `digestion_queue`（list）仍为共享引用。外部代码修改返回值中的这些列表会直接影响内部状态。
*   **复现步骤**:
    1. 调用 `mgr.get_actor_life_state("aveline")`
    2. 修改返回值中的 `food_inventory` 列表
    3. 再次调用 `get_actor_life_state`，发现内部状态已被修改
*   **预期行为**: 返回的状态应与内部状态完全隔离。
*   **实际行为**: 嵌套列表是共享引用，修改返回值会影响内部状态。
*   **修复方案**: 改用 `deepcopy(st)` 进行深拷贝。

### 10.38 FoodSystem.tick_digestion 从错误数据源读取 cpu_temp 导致新陈代谢倍率永远为1.0 (2026-04-26)

*   **问题描述**: `FoodSystem.tick_digestion()` 从 `self.life_stats` 读取 `cpu_temp`，但 `cpu_temp` 实际存储在 `LifeSimulationService.status` 中，`life_stats` 里没有这个字段，永远返回默认值 45.0，导致 `metabolism_multiplier = 1.0 + max(0.0, (45.0 - 45.0) / 50.0) = 1.0`，新陈代谢倍率永远不变。
*   **复现步骤**:
    1. 启动 LifeSimulationService
    2. 观察 `tick_digestion` 中的 `cpu_temp` 值，始终为 45.0
    3. 即使 CPU 温度升高到 85°C，消化速度也不会加快
*   **预期行为**: `tick_digestion` 应从 `status` 字典读取 `cpu_temp`，CPU 温度越高消化越快。
*   **实际行为**: `cpu_temp` 始终为默认值 45.0，新陈代谢倍率永远为 1.0。
*   **修复方案**: `FoodSystem.__init__` 新增 `status` 参数，`tick_digestion` 改为 `self.status.get("cpu_temp")`。

### QR-20260704-SLEEP-STAYUP SleepManager STAY_UP_LATE 白天卡死导致角色永久 phone_scrolling 且 peer chat 从未触发 (2026-07-04)
*   **问题描述**: 用户反馈 AI 很久没进行 peer chat。日志显示两个角色从 7:05 到 8:36 一直停在 phone_scrolling，daily_state.json 中 last_peer_chat_ts=0.0（从未触发过 peer chat）。
*   **复现步骤**:
    1. 查看 logs/2026/7/4/active_care_schedule.log，发现 PeerChatScheduler 启动后被 CharacterDailyEngine 接管退出
    2. 查看 companion_data/character_daily/sleep_states.json，发现两个角色 phase=stay_up_late，stay_up_activity=phone_scrolling，最近一次 sleep_recovery_decision 在 6月29日 23:21
    3. 查看 xiaoyou_main.log，ACTIVE_CARE_CHECKER 注入活动状态一直是 aveline=phone_scrolling, ling=phone_scrolling
    4. 查看 daily_state.json，last_peer_chat_ts=0.0，today_peer_chat_count=0
*   **预期行为**:
    1. 角色熬夜后，白天应自动恢复为 WAKING_UP/FULLY_AWAKE，按 plan 执行 reading/studying/cooking 等活动
    2. peer chat 在 9-22 点时间窗口内、双方空闲时按概率触发
*   **实际行为**:
    1. 角色从 6月29日熬夜后，phase 永久卡在 STAY_UP_LATE，stay_up_activity=phone_scrolling 覆盖所有 plan 活动
    2. peer chat 从未触发过（last_peer_chat_ts=0.0）
*   **根因**:
    1. _update_runtime_state 跨天不重置 phase，睡眠窗口逻辑显式排除 STAY_UP_LATE，白天无 STAY_UP_LATE → FULLY_AWAKE 转换路径
    2. finalize_sleep_recovery_check 只在用户发消息后触发，用户不发消息则永久卡死
*   **修复方案**:
    1. 在 _update_runtime_state 中新增白天恢复逻辑：dt >= wake_dt 且 phase 在 (STAY_UP_LATE, NIGHT_AWAKE, SLEEP_LATER) 时转换为 WAKING_UP
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\verify_sleep_stay_up_late_recovery.py`

### QR-20260705-WAKE-ACTIVITY-STALE /wake 立即唤醒后 ReplyPolicy 仍按 activity=sleeping 静默累积消息 (2026-07-05)
*   **问题描述**: 用户发送 /wake 命令，API 返回成功且 sleep_summary.phase=night_awake，但紧随其后的消息仍被 ReplyPolicy 判定为 dnd_sleeping_silent(activity=sleeping, ac_sleeping=False) 静默累积，角色唤不醒。
*   **复现步骤**:
    1. 角色处于睡眠窗口内，phase=sleeping, is_sleeping=True
    2. 用户私聊发送 /wake
    3. wake API 返回 action=woken_up, sleep_summary.phase=night_awake
    4. 5 秒后用户私聊发送『小澪？』
    5. 后端日志显示 ReplyPolicy: 睡觉中，静默累积消息 (dnd_sleeping_silent(activity=sleeping, ac_sleeping=False) count=2, will_process_on_wake)
*   **预期行为**:
    1. /wake 成功后 character_daily 的 plan.current_activity 应立即从 sleeping 切换为非 DND 活动（如 idle）
    2. 后续消息 ReplyPolicy.is_dnd 应为 False，正常进入 LLM 回复流程
*   **实际行为**:
    1. /wake 后 sleep_manager 状态正确更新（phase=NIGHT_AWAKE, is_sleeping=False, ac_sleeping=False）
    2. 但 character_daily engine 的 plan.current_activity 仍为上次 tick 时的 sleeping（缓存过期）
    3. engine.get_current_activity() 直接返回缓存值，未重算
    4. ReplyPolicy 读取到 activity=sleeping，判定 is_dnd=True，消息被静默累积
    5. 需等待 character_daily 主循环下一次 tick（最长 2.4 分钟）才能恢复
*   **根因**:
    1. wake API 只调用 sim.notify_sleep_interruption() 更新 sleep_manager 状态，未触发 character_daily engine 重新计算 plan.current_activity
    2. engine.get_current_activity() 是纯读取方法，不触发重算
    3. engine._update_current_activity() 是私有方法，仅在 _tick() 中调用，tick 间隔 2 分钟
*   **修复方案**:
    1. 在 CharacterDailyEngine 新增公开方法 refresh_current_activity(role_id)，强制重算 plan.current_activity 并立即持久化
    2. 在 routers/v1/life.py 新增辅助函数 _refresh_character_daily_activity(role_id)，封装 engine 调用与异常容错
    3. 在 wake API 的两个返回分支（is_sleeping=True 主分支、ac_cleared=True 残留晚安态清理分支）调用 _refresh_character_daily_activity(role_id)
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests/unit/test_life_sleep_wake_route.py -v`
    2. `venv_core\Scripts\python.exe -m pytest tests/unit/test_reply_policy_support.py tests/character_daily/test_character_daily_plan_tool.py -v`
    3. `手动验证：/wake 后立即发消息，观察 ReplyPolicy 日志 activity 应不再是 sleeping`

### QR-2026-07-10-001 /wake 命令无法唤醒午睡中角色，消息被静默累积 (2026-07-10)
*   **问题描述**: 用户发 /wake 命令后，角色仍不回消息。日志显示 /wake 返回 fully_awake，但 ReplyPolicy 判定 activity=napping 静默累积消息。
*   **复现步骤**:
    1. 角色处于午睡时段，character_daily plan.current_activity=napping
    2. 用户发 /wake 命令，API 返回 already_awake（sleep_manager 判定未在睡）
    3. 用户发消息，ReplyPolicy 调用 engine.get_current_activity() 拿到过时的 napping
    4. 消息被静默累积，用户连续发多条均无回复
*   **预期行为**:
    1. /wake 命令应让角色恢复回复能力，无论角色是夜间睡眠还是午睡
    2. 用户发 /wake 后再发消息应能正常收到回复
*   **实际行为**:
    1. /wake 返回 already_awake，不刷新 character_daily 活动
    2. ReplyPolicy 仍按 napping 静默累积，用户收不到回复
    3. 用户连续发 /wake 两次、消息多条，均无效
*   **根因**:
    1. /wake 只处理 sleep_manager 夜间睡眠，不处理 character_daily DND 活动
    2. already_awake 分支不刷新 character_daily 活动也不打断 DND
    3. sleep_manager 与 character_daily 是两套独立状态系统，午睡由 plan schedule 管理
*   **修复方案**:
    1. _refresh_character_daily_activity 返回刷新后的 ActivityType
    2. already_awake 分支刷新后若仍为 DND，自动激活中断窗口（source=wake_auto_interrupt_dnd）
    3. 补充单元测试 test_wake_auto_interrupts_dnd_activity_when_already_awake 和 test_wake_already_awake_when_character_daily_idle
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\unit\test_life_sleep_wake_route.py -v`

### BUG-2026-07-16-01 /wake 唤醒后角色仍被判定 overslept_recovery 导致消息静默累积不回复 (2026-07-16)
*   **问题描述**: 用户发送 /wake 命令成功唤醒角色（API 返回 fully_awake），随后发消息角色仍不回复，reply_policy 日志显示 dnd_sleeping_silent(activity=overslept_recovery, ac_sleeping=False)。
*   **复现步骤**:
    1. 13:25:30 用户 /wake，API 返回 phase=fully_awake，提示「已立即唤醒 ling」
    2. 13:25:35 用户发送私聊消息「玲玲还去睡觉了呀」
    3. 13:25:36 日志输出 ReplyPolicy: 睡觉中，静默累积消息 (dnd_sleeping_silent(activity=overslept_recovery, ac_sleeping=False) count=1, will_process_on_wake)
    4. 角色未回复该消息，消息被静默累积
*   **预期行为**:
    1. /wake 成功后角色 phase 变为 fully_awake，后续用户消息应正常走 LLM 回复分支
    2. 即使 overslept 标记残留，phase 已清醒时不应继续按 OVERSLEPT_RECOVERY（DND）处理
*   **实际行为**:
    1. engine._update_current_activity 中 overslept 检查不看 phase，只要 overslept=True 就返回 OVERSLEPT_RECOVERY
    2. refresh_current_activity 因此返回 overslept_recovery，reply_policy 走 DND 静默累积分支
    3. 角色被唤醒后仍不回复用户消息
*   **根因**:
    1. overslept 标记在 sleep_manager 中一旦设置只在跨天时清除，/wake 不会清掉该标记
    2. _update_current_activity 未结合 phase 判断角色是否实际清醒，盲目信任 overslept 标记
    3. OVERSLEPT_RECOVERY 被归入 DO_NOT_DISTURB_ACTIVITIES，与 sleeping/napping/waking_up 一起触发 DND 静默累积
*   **修复方案**:
    1. engine.py _update_current_activity：把 phase 提前计算，overslept 检查增加 `and not is_conscious` 条件，phase 为 fully_awake/night_awake 时跳过 OVERSLEPT_RECOVERY 分支
    2. 新增 3 个回归测试：test_fully_awake_with_overslept_does_not_enter_dnd / test_night_awake_with_overslept_does_not_enter_dnd / test_waking_up_with_overslept_keeps_overslept_recovery
    3. 修复相关测试 mock：在 mock_engine 上同步设置 refresh_current_activity.return_value，避免 MagicMock 占位值干扰 DND 判定
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests/character_daily/test_sleep_activity_override.py -v`
    2. `venv_core\Scripts\python.exe -m pytest tests/character_daily/test_force_wake_and_interrupt.py tests/character_daily/test_manual_interrupt_window.py tests/character_daily/test_message_deferral.py::test_dnd_first_message_silently_accumulates tests/unit/test_life_sleep_wake_route.py -v`

### BUG-2026-07-31-02 自动进食永不吃正餐，做饭产出的正餐库存无人消费 (2026-07-31)
*   **问题描述**: 角色每天做饭产出正餐（fried_rice/beef_noodle 等）入库，但自动进食始终只选零食/饮品，饭点也不吃正餐，做好的饭放到过期无人食用。
*   **复现步骤**:
    1. 查看 logs 中 AUTO_EAT 与 CharacterDaily 做饭产出日志
    2. 对比发现"做饭已产出"记录后紧跟的却是 snack/drink，最近三天"选了 meal"记录为 0
*   **预期行为**:
    1. 饭点（早/午/晚餐窗）且已触发进食时，应优先吃正餐，尤其库存里有刚做好的饭
*   **实际行为**:
    1. 始终吃西瓜、豆浆、小笼包等零食饮品，正餐库存放到过期
*   **根因**:
    1. 阈值死区：触发线 hunger<65 与正餐判定线 hunger>=55 不一致，55~65 区间触发进食却判"不够饿"只吃零食，饱腹度被顶回 65 以上，正餐分支永远进不去
    2. 决策顺序：普通补水(thirst<35)与夜宵支路排在正餐判断之前，饭点被反复挤掉
*   **修复方案**:
    1. should_prefer_formal_meal 餐窗内饱腹上限 55→65 与触发线对齐
    2. resolve_food_decision 优先级重排：危急口渴>正餐>夜宵>补水>零食
*   **验证**:
    1. `tests\scripts\food\verify_meal_priority.py 8/8 通过`

### BUG-2026-07-31-03 角色从不按时吃正餐：进食靠饥饿阈值而与做饭日程脱节 (2026-07-31)
*   **问题描述**: 角色每天按点做饭产出正餐，但从不按点吃饭，做出来的正餐库存放到过期无人食用；实测 hunger 常年停在 99 附近。
*   **复现步骤**:
    1. 读 cache/life_stats_state.json 见 hunger=99.16
    2. 读 life_stats.py 衰减速率约 0.07/分钟（4点/小时），从 100 到 65 需 8+ 小时
    3. 对比日志：进食记录几乎全为 thirst 驱动的 drink/snack，正餐从不触发
*   **预期行为**:
    1. 角色应按做饭日程按点吃正餐（早/午/晚餐窗各一次），优先吃自己刚做好的那份
*   **实际行为**:
    1. 只有 thirst<55 时才进食补水，终日喝豆浆啃西瓜，正餐从不被吃
*   **根因**:
    1. 进食触发只看饥饿/口渴阈值，与做饭日程无关联
    2. hunger 衰减过慢，触发线 65 实际永远达不到
*   **修复方案**:
    1. 新增 is_scheduled_meal_due 调度式正餐触发，与饥饿阈值解耦（含跨天去重）
    2. resolve_food_decision 决策链重排，正餐优先于普通补水/零食
    3. maybe_auto_eat 外层触发追加 meal_due，饭点不饿也进食
*   **验证**:
    1. `tests\scripts\food\verify_meal_priority.py 10/10 通过`
