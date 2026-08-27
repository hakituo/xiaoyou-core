# Active Care 主动关怀

本分类共 84 条记录。按时间倒序（最新在前）排列。

---

### ISSUE-20260810-AC-DIGITAL-WELLBEING 数字健康超限触发假关怀 (2026-08-10)

*   **问题描述**: 用户没在用手机时仍收到应用使用超限的 active care 关怀消息（"哔哩哔哩已使用超过设定时长"）。
*   **根因分析**:
    1. `maybe_notify_exceeded_via_active_care` 只判断 `usage_ms > limit_ms`，不检查应用 `last_used_time`
    2. Android 上报 24h 窗口包含昨天数据 → 后端看到的 usage 始终含昨天峰值 → 每次同步都超限
*   **修复**:
    - `maybe_notify_exceeded_via_active_care` 增加 `_RECENT_ACTIVE_MINUTES=30` 最近活跃窗口，`last_used_time` 超过 30min 则跳过关怀（`core/services/digital_wellbeing/service.py`）
    - Android 上报改为只取今天 00:00 至今，切断昨天数据污染源（`DataSyncWorker.kt` + `UsageLimitMonitor.kt`）

### ISSUE-20260810-AC-MEAL-COVERED 后端已存储今日餐饮仍被追问"早餐吃了没" (2026-08-10)

*   **问题描述**: 用户已通过 `/吃` 等指令把"今天早餐吃什么"写入后端 daily_record 的 meals 列表，但 Active Care 仍主动追问"早餐吃了没？"，造成重复打扰。
*   **复现步骤**:
    1. 通过 food_tool 投喂（eater="user"）记录今日某正餐（如早餐），后端 `daily_manager.get_record()["meals"]` 出现 `{"type":"早餐", ...}`。
    2. 触发 Active Care 决策（portrait_priority 含 "meal"）。
    3. 观察生成的主动消息。
*   **预期行为**: 后端已记录今日早餐/午餐/晚餐等正餐后，Active Care 应把餐饮话题视作已覆盖，不再追问"吃了没/早餐吃了没"。
*   **实际行为**: 修复前 `detect_user_already_covered` 只扫描用户**聊天文字**里的吃饭关键词，后端存储的餐饮记录未被识别，LLM 仍基于"画像缺失 meal"追问。
*   **根因**: `detect_user_already_covered` (`core/services/active_care/decision/portrait_keyword_map.py`) 仅用 `_USER_COVERED_KEYWORDS` 匹配 recent_history 文本，未查询后端 daily_record 中已存的今日餐饮。
*   **修复方案**: 在 `detect_user_already_covered` 中合并 `_detect_backend_meals_covered()`：查询 `get_daily_manager().get_record()` 的 `meals`，若含"早餐/午餐/晚餐"正餐记录则把 "meal" 加入已覆盖集合。命中后 `_build_specific_instruction` 的 `if "meal" in user_already_covered` 硬约束生效，且画像过滤 `filtered_portrait` 会剔除 "meal"。
*   **验证**: 记录今日正餐后触发 Active Care，确认主动消息不再出现"吃了没/早餐吃了没"。

---

### ISSUE-20260702-AC-SLEEP-WAKE 自然语言唤醒未恢复 Active Care (2026-07-02)

*   **问题描述**: 用户发出“起来了/醒了/早安”等自然语言唤醒消息后，角色对话里已经表现为刚醒，但 Active Care 仍保留睡眠低打扰状态，后续长时间不主动发消息。
*   **复现步骤**:
    1. 调用 `set_sleep_mode(active=True, delay_next_check_seconds=7200)` 让 Active Care 进入睡眠低打扰。
    2. 通过聊天入口发送“起来了小澪”一类醒来消息。
    3. 读取 `proactive_state` 与 `get_runtime_status()`，再手动触发一次 `check_active_care()`。
*   **预期行为**:
    1. 聊天入口识别到 `exit_reduced/morning` 后，应同步退出睡眠低打扰状态。
    2. 退出后 `next_decision_in_seconds` 应迅速回落，不应继续保持 7000 秒级别延迟。
*   **实际行为**:
    1. 修复前，聊天入口已识别 `exit_reduced/morning`，但没有调用唤醒同步。
    2. 修复前，`next_decision_in_seconds` 仍维持在 7184 秒左右，手动检查被 `manual_delay` 拦截。
    3. 修复后，`exit_sync_success=true`，`source=clear_sleep_mode`，验证脚本输出 `reduced_mode_active=false` 且 `next_decision_in_seconds=0`。
*   **根因**:
    1. 聊天入口只处理了 `enter_reduced`，遗漏了 `exit_reduced/morning` 的 Active Care 同步。
    2. 退出睡眠时没有回收旧的长延迟，导致 checker 继续等待旧的 7200 秒睡眠门控。
*   **修复方案**:
    1. 补齐 `chat_handlers.py` 中的 `exit_reduced/morning` 睡眠退出同步。
    2. 在 `set_sleep_mode(active=False)` 中同步把下次检查时间重置到近端。
    3. 增加 `verify_sleep_wakeup_resume.py` 验证脚本，防止回归。
*   **验证**:
    1. `venv_core\scripts\python.exe tests\scripts\active_care\verify_sleep_wakeup_resume.py`

### 10.143 Active Care 手动延迟期间仍按动态间隔提前唤醒 (2026-07-02)

*   **问题描述**: Active Care 日志显示 `next_in=162727s` 这类超长手动延迟，但主循环实际仍每隔约 10 分钟醒一次，并重复打印双 QQ 的“跳过旧消息处理”日志，造成用户误以为系统仍在固定频率空转。
*   **复现步骤**:
    1. 让 Active Care 进入 manual_delay，日志出现 `跳过 - 手动延迟 (还需等待16万秒)`
    2. 观察随后数轮主循环日志
    3. 发现 `Active Care 调度` 中的 `sleep` 仍是 546s、635s、603s 等约十分钟级别
    4. 同时每轮都会再次输出两个 persona 的“跳过旧消息处理”
*   **预期行为**:
    1. 在 manual_delay 明确成立且没有外部事件时，主循环应直接睡到下一次允许决策的时间
    2. 双 QQ 的旧消息只应按 persona 各去重一次，不应在每次提前唤醒时重复刷日志
*   **实际行为**:
    1. 主循环仍按 dynamic_interval 提前醒来，即使当前并不允许进行主动决策
    2. 旧消息去重因双 QQ 共享单个签名而失效，导致重复输出旧消息跳过日志
*   **根因**:
    1. manual_delay 只影响 checker 是否执行决策，没有影响 ProactiveLoopRunner 的实际睡眠时间计算
    2. UserResponseHandler 的旧消息去重状态是单值而不是按 persona 隔离
*   **修复方案**:
    1. manual_delay 时让 calculate_sleep_interval() 直接返回 `llm_wait`
    2. 把旧消息签名缓存改为按 persona 存储，并在处理时使用 persona 独立 key
    3. 补充回归测试，锁住长等待睡眠与双 QQ 去重行为
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\unit\test_active_care_due_reminder_and_loop.py -q`

### 11.41 助手吐槽睡觉/起床内容被误判为晚安导致睡眠会话反复激活 (2026-07-01)

*   **问题描述**: 用户在发送“我起来啦”后，Active Care 日志先检测到 WAKEUP_NOW，又从最近助手回复里补充检测出“晚安意图”，导致睡眠会话再次被激活。与此同时，日志中的 wait=300s 与 next_in=59s 混在一起，造成恢复保护是否生效难以判断。
*   **复现步骤**:
    1. 构造一条最近 10 分钟内的助手消息，内容包含“起床”“睡了一整天”等调侃或复述，但并未明确说晚安
    2. 触发 Active Care 的 get_user_signal_and_intent + extract_latest_assistant_goodnight 链路
    3. 观察是否在检测到用户 WAKEUP_NOW 后又被助手历史错误补回 inferred_goodnight
*   **预期行为**:
    1. 只有助手明确表达了晚安/准备去睡/睡前告别时，才应重新激活 sleep session
    2. 单纯提到‘睡觉/起床/早晨’的吐槽、复述、调侃不应被视为助手晚安
    3. 调度日志应能区分全局最早 next_in 与各 persona 的等待时间
*   **实际行为**:
    1. 旧实现直接用 contains_goodnight_intent() 扫描助手消息，导致泛化的‘睡觉/起床’关键词被误判为晚安
    2. 双 QQ 模式下日志只打印全局最早 next_in，容易把另一个 persona 的 59s 误读成当前 persona 的 300s 恢复保护失效
*   **根因**:
    1. 助手消息晚安检测复用了面向通用文本的宽松规则，没有区分‘明确晚安’与‘提到睡觉’
    2. 调度日志缺少 per-persona 剩余等待信息
*   **修复方案**:
    1. 新增 contains_assistant_goodnight_intent() 并切换 extract_latest_assistant_goodnight() 使用更严格的助手晚安判定
    2. 为 Active Care 调度日志增加 per_persona 快照
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\unit\test_active_care_intent_detector.py tests\unit\test_active_care_due_reminder_and_loop.py -q`

### QR-20260630-AC-REMINDER Active Care 睡眠期仍处理 due_reminder 且提醒被拖到凌晨 (2026-06-30)

*   **问题描述**: 角色已进入睡眠，Active Care 仍会在内部处理 due_reminder；同时本应在晚间触发的提醒被拖到凌晨才被捞起。
*   **复现步骤**:
    1. 准备一个带结束提醒的学习计划，例如“化学选择题训练”18:00 开始、45 分钟结束。
    2. 让角色在夜间进入 goodnight 或真实睡眠状态。
    3. 观察 Active Care 日志，能看到凌晨仍出现 `发现到期提醒` 与 `due_reminder 已推迟`。
*   **预期行为**:
    1. 角色睡眠期间不应继续跑 due_reminder 思考链路，最多只做静默推迟。
    2. 提醒应在最近的调度点按时处理，不应被主循环睡过头拖到深夜。
*   **实际行为**:
    1. 睡眠期间仍会进入 due_reminder 处理逻辑，只是最后没有真正发消息。
    2. 18:45 的结束提醒直到 03:15 才被 Active Care 下一轮检查捞起。
*   **根因**:
    1. 事件处理只看 reduced mode，没有优先读取 life_sim 的角色真实睡眠摘要。
    2. 主循环睡眠间隔计算错误地偏向更大的 dynamic_interval，没有向最近 reminder/decision 收敛。
    3. 提醒数据来自 Journal 用户计划链路，因此用户看到的“角色生活计划提醒”与当前 Active Care reminder 源并不一致。
*   **修复方案**:
    1. 新增角色睡眠态硬门控，真睡眠只 defer reminder，夜醒才允许温和 nudge。
    2. 修正调度睡眠间隔，优先服从最近 pending reminder 与 `next_decision_ts`。
    3. 补充单元测试与独立验证脚本，固定回归检查。
*   **验证**:
    1. `.\venv_core\Scripts\python.exe -m pytest tests\unit\test_active_care_due_reminder_and_loop.py tests\unit\test_life_sleep_wake_route.py tests\unit\test_reply_policy_support.py`
    2. `.\venv_core\Scripts\python.exe tests\scripts\active_care\verify_due_reminder_sleep_gate.py`

### QR-20260630-AC-PLAN-ALIGN 计划提醒与角色日常链路存在标题丢失、scope 错位和调度唤醒缺口 (2026-06-30)

*   **问题描述**: 继续排查计划提醒为何不准时以及提醒后角色自己可能又忙到不回时，发现 reminder 注入、deferred 清理和新计划写入后的调度唤醒存在实现缺陷。
*   **复现步骤**:
    1. 让 Journal 计划生成带时间的 reminder，并让用户在 reminder 触发窗口内持续聊天。
    2. 观察聊天注入内容，部分 reminder 只有正文没有任务标题。
    3. 在双 persona 场景下积累 deferred reminders，再让对应角色发送一条主动消息后检查 proactive_state。
    4. 在 Active Care 主循环已经进入较长睡眠窗口时，再写入一个更早的 reminder。
*   **预期行为**:
    1. 聊天注入 reminder 时应携带正确的 `task_title`。
    2. 延后提醒清理应写回当前 persona 对应的标准 scope，不应误清到另一个角色。
    3. 新 reminder 写入后应立即唤醒 Active Care 重算最近检查时间。
*   **实际行为**:
    1. 提醒注入时经常读不到任务标题，只能看到提醒正文。
    2. deferred reminders 的清理逻辑可能把 `persona_filename` 当 scope 使用，双角色下存在错位风险。
    3. 新增 reminder 后主循环不会被显式唤醒，只能依赖当前 sleep interval 自然结束。
*   **根因**:
    1. Reminder 注入代码读取了不存在的 `due_reminder.title`，而真实标题通常在 `metadata.task_title`。
    2. 延后提醒清理时缺少 `persona_filename -> scope` 的标准解析步骤。
    3. Workspace reminder 写入链路与 Active Care 主循环之间缺少直接的唤醒接口。
*   **修复方案**:
    1. 修正 reminder 注入标题读取逻辑，改为元数据优先。
    2. 修正 deferred reminders 清理 scope，统一走 `resolve_scope_from_persona_filename()`。
    3. 新增 reminder/plan 更新唤醒接口，并在 `schedule_message()` 成功写入后主动通知 Active Care。
*   **验证**:
    1. `.\venv_core\Scripts\python.exe -m pytest tests\unit\test_active_care_due_reminder_and_loop.py tests\unit\test_reminder_injection_awaits.py tests\unit\test_workspace_reminder_service.py tests\unit\test_life_sleep_wake_route.py tests\unit\test_reply_policy_support.py`

### QR-20260630-AC-HARD-BUSY-GATE 计划提醒在角色硬忙碌时仍可能主动发出，导致提醒链路和回复链路打架 (2026-06-30)

*   **问题描述**: 角色按用户计划触发 due_reminder 时，如果自己正处于学习等硬忙碌态，系统可能仍主动发提醒；但用户回消息后，ReplyPolicy 又会按忙碌态静默或延迟回复，形成行为冲突。
*   **复现步骤**:
    1. 让 Journal 计划在某个时间点触发开始或结束提醒。
    2. 同时让角色在 character_daily 中处于 `studying` 等硬忙碌活动。
    3. 观察 due_reminder 链路和用户回消息后的 ReplyPolicy 决策。
*   **预期行为**:
    1. 角色在最硬的忙碌态下不应主动打断自己去发计划提醒。
    2. 提醒链路和回复链路应保持基本一致，至少不能出现“她先来提醒你，接着又因为自己忙而不接话”。
*   **实际行为**:
    1. due_reminder 之前只看睡眠，不看硬忙碌活动；提醒可能照发。
    2. 用户回复后 ReplyPolicy 仍按忙碌态处理，造成角色行为前后不一致。
*   **根因**:
    1. Active Care 的计划提醒门控和 ReplyPolicy 的忙碌门控属于两套独立逻辑，没有统一读取 character_daily 当前活动。
    2. 系统只有主动消息后的回接窗口，没有在 due_reminder 发起前先裁掉最硬的忙碌冲突。
*   **修复方案**:
    1. 为 due_reminder 增加 character_daily 当前活动读取。
    2. 把 `HARD_BUSY_ACTIVITIES` 纳入提醒门控，硬忙碌时统一转 deferred reminder。
*   **验证**:
    1. `.\venv_core\Scripts\python.exe -m pytest tests\unit\test_active_care_due_reminder_and_loop.py tests\unit\test_reminder_injection_awaits.py tests\unit\test_workspace_reminder_service.py tests\unit\test_life_sleep_wake_route.py tests\unit\test_reply_policy_support.py`

### QR-20260630-AC-CONFLICT-CLOSURE 计划提醒闭环缺少批量注入与时间轴冲突检查，真实数据已出现大面积延迟和日期错位 (2026-06-30)

*   **问题描述**: 用户要求一次性搞清楚计划提醒为什么不准时、角色自己的日常计划是否和用户计划打架，以及提醒链路是否会因多个接近时间的 reminder 丢数据。
*   **复现步骤**:
    1. 查看 `ReminderInjectionStore` 的实现，确认是否支持多个待注入 reminder 并存。
    2. 读取 `companion_data/user_data/reminders.json` 与 `companion_data/character_daily/daily_state.json`。
    3. 运行 `tests/scripts/active_care/verify_plan_conflict_matrix.py` 输出日期、延迟和冲突矩阵。
*   **预期行为**:
    1. 多个接近时间的 reminder 不应在聊天注入阶段互相覆盖。
    2. 系统应能快速输出用户计划与角色计划是否同日、哪些 reminder 已明显晚发、哪些仍 pending。
    3. 排查结论应可以脚本化复现，而不是每次人工读大文件。
*   **实际行为**:
    1. 提醒注入之前只有单槽，后来的 reminder 会覆盖前面的 reminder。
    2. 验证脚本输出显示最新用户计划日期是 `2026-06-29`，角色日常计划日期是 `2026-06-30`，存在日期错位。
    3. 同一份输出还显示多项 reminder 延迟达到几十到数百分钟，晚间多条 reminder 仍处于 pending。
*   **根因**:
    1. 提醒注入共享状态设计过于简化，只支持单条 pending reminder。
    2. 缺少统一的时间轴检查脚本，导致用户计划、角色计划和 reminders.json 三条链路难以一起验证。
    3. 用户计划日切与角色计划日切没有现成的对账输出，日期错位长期隐藏在磁盘数据里。
*   **修复方案**:
    1. 将提醒注入改为队列化，支持去重、过期清理和多提醒合并。
    2. 新增冲突矩阵验证脚本，直接输出日期错位、提醒延迟和 pending 提醒列表。
*   **验证**:
    1. `.\venv_core\Scripts\python.exe -m pytest tests\unit\test_active_care_due_reminder_and_loop.py tests\unit\test_reminder_injection_awaits.py tests\unit\test_reminder_injection_store.py tests\unit\test_workspace_reminder_service.py tests\unit\test_life_sleep_wake_route.py tests\unit\test_reply_policy_support.py`
    2. `.\venv_core\Scripts\python.exe tests\scripts\active_care\verify_plan_conflict_matrix.py`

### 11.40 Active Care 连接观测日志应改为有变化才输出 (2026-06-30)

*   **问题描述**: 用户认为 QQ 连接探测日志更像防断连/观测日志，不应在连接状态未变化时固定频率刷屏，而应只在状态变化时输出。
*   **复现步骤**:
    1. 让 Active Care 周期性调用 QQConnectionResolver.resolve()
    2. 保持 QQ 连接状态连续多轮不变
    3. 观察 QQAdapter 注册表、QQ 连接数量和 dual_qq_config 解析日志是否重复出现
*   **预期行为**:
    1. 首次探测输出一次连接状态
    2. 连接状态不变时保持静默，仅在状态变化时重新输出
    3. 必要时保留低频心跳而不是固定频率刷屏
*   **实际行为**:
    1. 旧实现每次 resolve() 都直接输出连接观测日志，即使状态完全相同也会重复刷
*   **根因**:
    1. QQConnectionResolver 缺少连接状态签名和变化检测机制
    2. 观测日志与异常日志没有区分对待
*   **修复方案**:
    1. 增加状态签名缓存与变化检测，只在连接状态变化或长时间静默后心跳输出
    2. 增加单测验证状态不变时不重复输出
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\unit\test_active_care_executor_connections.py tests\unit\test_active_care_due_reminder_and_loop.py -q`

### 11.39 Active Care 双 QQ 模式下 stale persona 触发固定 60 秒重复决策 (2026-06-30)

*   **问题描述**: 用户反馈 Active Care 日志稳定每分钟一次进入“开始执行决策流程”，并重复输出 QQAdapter 注册表、QQ 连接数量和 dual_qq_config 解析日志，说明系统仍在真实执行短周期决策。
*   **复现步骤**:
    1. 让 Active Care 在某次决策后未成功写入新的 next_decision_ts，进入 perform_check() finally 的保底路径
    2. 使全局 next_decision_ts 被回退到 now+60，但至少一个 per-persona next_decision_ts 仍然保持过期状态
    3. 在双 QQ 模式下继续运行 perform_check()，观察是否每分钟仍强制进入决策流
*   **预期行为**:
    1. 当使用保底回退时，全局和所有已过期的 per-persona 决策时间都应一起被拉起
    2. 旧消息首次判定为过期后不应每轮重复记录“跳过旧消息处理”日志
    3. 内部构建 primary_cid 的 QQ 连接扫描不应额外输出连接探测详情
*   **实际行为**:
    1. 保底逻辑只更新了全局 next_decision_ts，没有修复已过期的 per-persona 时间戳
    2. 双 QQ 模式检测到某 persona 仍已到期后，继续绕过全局延迟进入决策流，形成稳定 60 秒重复决策
    3. 旧消息没有提前写入 dedup signature，导致每轮都重复打印旧消息跳过日志
    4. 实际决策流构建 primary_cid 时再次输出 QQ 连接解析日志，加重噪音
*   **根因**:
    1. 全局调度时间与 per-persona 调度时间修复不一致，导致双 QQ 下 earliest/global 与 due persona 判定撕裂
    2. 旧消息去重时机过晚，只在年龄校验通过后才设置 signature
    3. QQ 连接解析在内部辅助路径中仍默认 emit_logs=True
*   **修复方案**:
    1. 新增 _repair_stale_next_decision_ts()，统一修复全局和过期的 per-persona 调度时间，保底间隔至少 300s
    2. 旧消息年龄判断前先写入 dedup signature
    3. 双 QQ 决策流构建 primary_cid 时改为静默连接解析
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\unit\test_active_care_due_reminder_and_loop.py tests\unit\test_active_care_executor_connections.py -q`

### 11.38 Active Care 主循环的用户响应扫描仍会按分钟触发 QQ 连接日志 (2026-06-30)

*   **问题描述**: 用户反馈即使 manual_delay 分支已静默，QQ 连接探测日志仍然按分钟稳定出现，说明系统还有其他固定周期入口在调用带日志的 QQ 连接解析。
*   **复现步骤**:
    1. 启动 Active Care 主循环
    2. 保持系统运行但不要求真正进入主动关怀决策
    3. 观察是否仍会周期性出现 QQAdapter 注册表、QQ 连接数量和 dual_qq_config 解析日志
*   **预期行为**:
    1. 仅做内部 persona 扫描时应静默，不应反复输出 QQ 连接探测细节
*   **实际行为**:
    1. _process_user_response() 每轮都会调用 UserResponseHandler._get_active_persona_filenames()
    2. 该函数内部调用 _get_qq_connections() 时默认 emit_logs=True，导致每轮固定触发一组 QQ 连接日志
*   **根因**:
    1. 前一轮只处理了 perform_check/manual_delay 分支，遗漏了主循环开头固定执行的用户响应扫描入口
    2. QQ 连接解析缺少在该入口下的静默调用
*   **修复方案**:
    1. 将 user_response_handler.py 的 persona 扫描改为 _get_qq_connections(emit_logs=False)
    2. 新增单测覆盖静默扫描行为
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\unit\test_active_care_executor_connections.py -q`

### 11.37 Active Care 在 manual_delay 期间重复输出 QQ 连接探测日志 (2026-06-30)

*   **问题描述**: 用户反馈修复后端空转后，日志仍然按分钟重复输出 QQAdapter 注册表查询、QQ 连接数量和 dual_qq_config 解析结果，虽然频率下降，但依旧属于无意义刷屏。
*   **复现步骤**:
    1. 让 Active Care 处于 manual_delay 窗口内
    2. 观察 perform_check() 在 manual_delay 分支的日志输出
    3. 查看是否仍会重复打印 QQ 连接探测相关日志
*   **预期行为**:
    1. manual_delay 期间只需要静默判断是否有 persona 到点，不应反复输出 QQ 连接探测细节
    2. 保留必要的 manual_delay 状态日志即可
*   **实际行为**:
    1. perform_check() 在 manual_delay 分支调用 _get_qq_connections()，触发 QQConnectionResolver 的多条 info 日志
    2. 即使没有真正开始执行主动关怀决策，也会重复输出连接探测细节
*   **根因**:
    1. 连接解析逻辑没有区分‘内部判断’和‘实际执行前的可观测日志’两种场景
    2. manual_delay 只是状态探测，却沿用了默认的 emit_logs=True
*   **修复方案**:
    1. 在 QQConnectionResolver 和 ActiveCareExecutor 中增加 emit_logs 开关
    2. manual_delay 分支改用静默连接解析
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\unit\test_active_care_due_reminder_and_loop.py tests\unit\test_active_care_executor_connections.py -q`

### 11.36 Active Care 在手动延迟期间被 overdue reminder 压成 1 秒轮询 (2026-06-30)

*   **问题描述**: 日志显示 next_decision_ts 还剩四十多秒，但 Active Care 主循环仍然每秒执行一次，并持续输出 QQ 连接解析日志，造成无意义空转与日志刷屏。
*   **复现步骤**:
    1. 让 checker.next_decision_ts 进入手动延迟窗口，剩余时间几十秒
    2. 同时让 workspace 中存在一个已经到点的 pending reminder
    3. 观察 calculate_sleep_interval 与主循环日志
*   **预期行为**:
    1. 既然手动延迟尚未结束，主循环应直接睡到 next_decision_ts 附近，而不是每秒醒来一次
    2. QQ 连接解析日志不应在这段等待窗口内持续刷屏
*   **实际行为**:
    1. calculate_sleep_interval 先拿到 llm_wait=数十秒，又被 overdue reminder 的 reminder_wait=1s 覆盖，最终 sleep_seconds 变成 1
    2. perform_check 由于 manual_delay 不会处理 due_reminder，导致循环每秒空转一次
*   **根因**:
    1. sleep interval 计算没有区分‘提醒已经 overdue 但当前还不允许决策’这个状态
    2. overdue reminder 与 manual delay 的交互导致无意义的 1 秒轮询
*   **修复方案**:
    1. 在 proactive_loop.py 中加入保护：若 llm_wait 仍大于 1 秒且 overdue reminder 只会把睡眠压到 1 秒，则忽略这次 1 秒 reminder_wait
    2. 增加单测覆盖该场景，防止回归
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\unit\test_active_care_due_reminder_and_loop.py -q`

### 11.35 夜间被叫醒后 Active Care 仍把旧计划提醒和学习话题硬塞进来 (2026-06-30)

*   **问题描述**: 用户在凌晨把角色叫醒后，角色明明刚表达过困倦和准备继续睡，却在十分钟左右后主动提起‘昨天有个化学训练没做’、‘现在刚好有空刷几道’之类的学习计划，表现出明显的状态撕裂和话题突兀。
*   **复现步骤**:
    1. 让角色处于 sleeping 状态并在夜里通过聊天把她叫醒，使其进入 night_awake 或后续的 sleep_later/stay_up_late
    2. 等待约 10 分钟，使 Active Care 到达下一次检查窗口
    3. 观察是否会收到关于昨日遗漏任务、学习训练、计划提醒之类的主动消息
*   **预期行为**:
    1. 角色夜里被叫醒后，如果仍处于困倦或准备再睡的恢复阶段，不应突然主动拉学习计划或普通任务提醒
    2. 到期的计划提醒应先推迟，等角色真正清醒后再处理
    3. 普通 Active Care 主动话题也应避开这个恢复窗口
*   **实际行为**:
    1. due_reminder 只在 sleeping、用户 sleep mode、硬忙碌时才会被推迟，night_awake/sleep_later 阶段仍可能直接发送
    2. 普通 Active Care 决策没有睡眠恢复保护，导致角色即使还困也会继续走今日计划/学习相关的主动话题生成
    3. 最终出现一边说困一边主动问要不要练化学的异常表现
*   **根因**:
    1. 睡眠恢复期没有被纳入 Active Care 提醒门控与普通主动话题门控
    2. 旧计划提醒在角色睡眠恢复期被错误视为可立即发送的正常提醒
    3. 普通主动关怀没有基于夜醒后的睡眠债、睡眠惯性和影响等级做硬拦截
*   **修复方案**:
    1. 在 checker_event_handler.py 中新增 _get_sleep_recovery_guard，对 night_awake、sleep_later 以及带夜醒痕迹的 stay_up_late 统一建立恢复保护
    2. 在恢复保护期内将 due_reminder 转入 deferred_plan_reminders，不再立即发送
    3. 在 proactive_checker.py 中新增 guard_general_proactive_during_sleep_recovery，恢复期内直接阻断普通 Active Care 主动话题并延后检查
    4. 补充单测与验证脚本，覆盖夜醒 defer 与普通主动关怀拦截
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\unit\test_active_care_due_reminder_and_loop.py -q`
    2. `venv_core\Scripts\python.exe tests\scripts\active_care\verify_sleep_recovery_guard.py`

### 11.34 主聊天睡眠状态块未覆盖 Ling 且会缓存旧状态，导致被吵醒/临睡前表现失真 (2026-06-30)

*   **问题描述**: 用户反馈角色半夜被叫醒后回复仍像白天正常聊天，几乎没有‘刚被吵醒’的困倦感；同时临近睡觉或下一个计划时，也很少自然提到自己准备去睡或安排快到了。
*   **复现步骤**:
    1. 切到 ling 等非 aveline persona，或在角色刚从 sleeping 进入 night_awake 后立刻继续聊天
    2. 观察主聊天回复是否带出被吵醒、困意、准备再睡等状态
    3. 在下一个计划是睡觉/午休/起床洗漱且时间快到时继续聊天，观察是否自然提到准备去睡或安排快到了
*   **预期行为**:
    1. 所有角色的人设主聊天都能拿到实时睡眠状态，而不是只有仿生体 persona 才有
    2. night_awake、sleep_later、waking_up 等状态要体现出困倦、迷糊、准备再睡或刚醒缓冲
    3. 临睡前或睡觉相关计划切换时，回复里应自然提一句准备去睡/去休息，而不是完全无视
*   **实际行为**:
    1. assembler 只在 is_bionic_character 命中时才注入角色状态块，ling 等角色主聊天缺少睡眠状态提示
    2. prompt/data.py 的 _bionic_state_cache 只按时间失效，睡眠状态变化后仍可能在 5 分钟窗口内复用旧文本
    3. 计划切换提示过于温和，睡觉相关安排容易被模型完全忽略
*   **根因**:
    1. 角色状态注入条件设计过窄，把主聊天睡眠状态误绑到了仿生体分支
    2. 缓存键没有纳入 persona 和 role_sleep_states，导致状态切换后 prompt 文本滞后
    3. 计划切换提示缺少对睡觉相关安排的明确约束
*   **修复方案**:
    1. 修改 bionic_state.py，让非仿生角色也能拿到睡眠状态块，并对 night_awake、sleep_later、waking_up 输出更明确的行为提示
    2. 修改 prompt/data.py，让角色状态缓存按 persona 与 role_sleep_states 即时失效
    3. 修改 reply_hints.py，强化计划切换文案，并在下个安排与睡觉相关时要求优先自然提到准备去睡/去休息
    4. 新增单测和验证脚本，覆盖被吵醒状态注入、缓存失效与临睡前提示强化
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\unit\test_prompt_sleep_context.py tests\unit\test_reply_policy_support.py -q`
    2. `venv_core\Scripts\python.exe -m pytest tests\unit\test_life_sleep_wake_route.py -q`
    3. `venv_core\Scripts\python.exe tests\character_daily\verify_chat_sleep_prompt_context.py`
    4. `venv_core\Scripts\python.exe tests\character_daily\verify_plan_transition_hint.py`

### 10.145 `sleep_state_store.py` 在 Windows 上保存 `sleep_states.json` 触发 `WinError 5`（根因：仍手写固定 `.tmp` + 单次 `Path.replace()`）(2026-06-30)

*   **问题描述**: 后端运行时频繁出现 `[ERROR] [core.services.life_simulation.sleep_state_store] 保存睡眠状态失败: [WinError 5] 拒绝访问`，导致 `companion_data/character_daily/sleep_states.json` 无法稳定落盘，角色睡眠状态可能丢失。
*   **复现步骤**:
    1. 启动系统，让 `SleepManager._persist()` 持续保存 `sleep_states.json`
    2. 在 Windows 环境中让目标文件被短暂占用（如索引器、杀毒、同步工具或其他句柄）
    3. `sleep_state_store.py` 先写 `sleep_states.tmp`
    4. 执行 `tmp_file.replace(self._state_file)`
    5. 立即抛出 `[WinError 5] 拒绝访问`
*   **预期行为**: 即使目标文件短暂被占用，睡眠状态也应通过重试或降级写回稳定保存，不应直接失败。
*   **实际行为**: 当前实现只尝试一次 `Path.replace()`，失败后仅记录错误日志，保存直接丢失。
*   **根因**:
    1. `sleep_state_store.py` 没有复用项目现成的 `core/utils/atomic_io.py`
    2. 保存逻辑仍使用固定 `.tmp` 临时文件名和单次替换
    3. 没有 Windows 锁冲突重试，也没有最终降级直写兜底
    4. 进程内缺少读写锁，读写并发时稳定性更差
*   **修复**:
    1. `sleep_state_store.py` 改为使用 `safe_json_dump()` / `safe_json_load()`
    2. `core/utils/atomic_io.py` 的同步 `fsync` 分支补齐 `OSError` 兜底，避免当前 Windows / 沙箱环境下出现 `[Errno 9] Bad file descriptor` 时把整条保存链路打断
    3. 启用 `use_fsync=True`，沿用统一原子写入模块的重试和降级能力
    4. 增加 `threading.RLock()` 保护睡眠状态文件的进程内读写
    5. 在 `tests/diagnostics/role_sleep/test_sleep_window_fix.py` 中新增 `os.replace` 被拒绝时和同步 `fsync` 句柄异常时的回归测试
    6. 新增 `tests/diagnostics/role_sleep/verify_sleep_store_windows_fallback.py` 做独立验证
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\diagnostics\role_sleep\test_sleep_window_fix.py -q`
    2. `venv_core\Scripts\python.exe tests\diagnostics\role_sleep\verify_sleep_store_windows_fallback.py`
    3. `venv_core\Scripts\python.exe -m ruff check core\services\life_simulation\sleep_state_store.py tests\diagnostics\role_sleep\test_sleep_window_fix.py tests\diagnostics\role_sleep\verify_sleep_store_windows_fallback.py`
*   **教训**:
    1. 项目里已有统一原子写入模块时，不要在业务模块里重复手写 `.tmp + replace`
    2. Windows 文件系统上的“拒绝访问”很多是短暂锁冲突，必须有重试和降级兜底
    3. 对状态文件这类高频持久化点，除了原子替换，还要考虑进程内串行化
    3. 只修“吃不吃”还不够，`hunger/thirst` 的衰减速度也必须同步适配新的角色生活节律
    4. 供 LLM 决策使用的上下文字段，也必须同步为最新活动状态，否则会继续产生违和行为

### 10.144 `submit_llm_task()` 被当成支持 `messages=` 关键字，导致角色日常 LLM 直接回退模板（2026-06-30）

*   **问题描述**: `CharacterDaily` 生成每日计划时，日志持续报 `GlobalTaskScheduler.submit_llm_task() missing 1 required positional argument: 'prompt'`，导致 `LLMPlanGenerator` 每次都走模板回退。
*   **复现步骤**:
    1. 启用 `character_daily.llm_plan.enabled`
    2. 触发 `LLMPlanGenerator.generate(...)`
    3. 执行到 `core/services/character_daily/llm_plan_generator.py` 的 `_call_llm()`
    4. 调用 `scheduler.submit_llm_task(messages=messages, ...)`
    5. 立即抛出 `TypeError: missing 1 required positional argument: 'prompt'`
*   **预期行为**: 调度器应收到消息列表并正常流式返回 LLM 内容，角色日程按 LLM 结果生成。
*   **实际行为**: 因为没有传入位置参数 `prompt`，调用在进入调度器前就失败，整条链路直接回退模板。
*   **根因**:
    1. `GlobalTaskScheduler.submit_llm_task()` 当前签名是 `submit_llm_task(prompt, **kwargs)`，虽然支持 `prompt` 为消息列表，但不支持 `messages=` 这个关键字名
    2. `llm_plan_generator.py` 把接口误当成 OpenAI 风格消息调用
    3. `core/services/life_simulation/sleep_decision.py` 也残留了同类误用，存在相同潜在崩溃点
*   **修复**:
    1. `llm_plan_generator.py` 改为 `scheduler.submit_llm_task(messages, ...)`
    2. `sleep_decision.py` 同步改为把消息列表作为第一个位置参数传入
    3. 新增 `tests/character_daily/test_submit_llm_task_signature.py` 覆盖两个调用点
    4. 新增 `tests/character_daily/verify_submit_llm_task_signature.py` 做独立验证
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\character_daily\test_submit_llm_task_signature.py -q`
    2. `venv_core\Scripts\python.exe tests\character_daily\verify_submit_llm_task_signature.py`
*   **实际行为**: 主动消息资格和被动回复资格完全脱节；前者允许发消息，后者却仍按忙碌态拒回。
*   **根因**:
    1. `reply_policy.py` 只看当前活动、`active_care` 睡眠会话和普通 `reply_window_seconds`
    2. 普通回复窗口只覆盖“上次 BUSY 回复后 120s 内继续聊”，不覆盖“最近主动发起后用户回接”
    3. 双QQ场景下，`ReplyPolicy` 也没有基于 `persona_filename` 去读取同 persona 的 `Active Care` 状态
*   **修复**:
    1. `reply_policy.py` 新增按 `persona_filename` 解析 scope，并读取同 persona 的 `last_sent_ts`
    2. 新增 `proactive_reply_window_seconds`（默认 300s），命中后直接放行回复
    3. `chat_handlers.py` 透传 `persona_filename` 给 `ReplyPolicy`
    4. 新增 `tests/character_daily/verify_proactive_reply_window.py` 验证 219 秒窗口场景

### 11.32 waking_up 瞬时态长时间残留在 daily_state.json，造成“起床一整天”错觉 (2026-06-29)

*   **问题描述**: 用户指出 `waking_up` 只是刚起床后的短暂过渡态，不应在晚上仍显示在 `daily_state.json`。此前即使运行态已经切到别的活动，只要没有新的保存事件，磁盘文件仍可能残留早晨的 `waking_up`，造成非常违和的观感。
*   **复现步骤**:
    1. 早上首次保存 `daily_state.json` 时，角色状态恰好是 `waking_up`
    2. 后续几个小时内没有发生 `peer chat` 或停止引擎
    3. 再查看磁盘文件，`current_activity` 仍可能是早上的 `waking_up`
*   **预期行为**: `waking_up` 只在刚起床后的几分钟内短暂存在；活动切换到 `idle/早餐/其他 slot` 后，应尽快同步到磁盘
*   **实际行为**: `daily_state.json` 会长期保留早晨的瞬时态，给人“角色起床起了一整天”的错觉
*   **解决方案**:
    1. 缩短 `waking_up` 保留窗口，只保留刚起床后的短时间
    2. 新增 `activity_state_sync.py`，在 `current_activity` 发生切换时立即保存状态
    3. 主循环统一走状态同步器，避免过时的瞬时态长期留在磁盘

### 11.31 CharacterDaily 空档期沿用上一活动，导致 peer chat 长时间不触发 (2026-06-29)

*   **问题描述**: 用户反馈近几天几乎看不到两个角色的 `peer chat`。排查发现 `CharacterDailyEngine` 在计划空档期（当前时间没有命中任何 `slot`）不会回落到 `idle`，而是继续保留上一项 `current_activity`。如果上一项是 `dinner/cooking/self_care/studying` 等非空闲活动，会把该状态错误延长几十分钟，直接压掉 `peer chat` 触发窗口。
*   **复现步骤**:
    1. 读取 `companion_data/character_daily/daily_state.json`
    2. 观察 2026-06-29 的计划空档：Aveline `18:15 -> 19:00`、Ling `18:42 -> 19:30`
    3. 查看 `engine.py:_update_current_activity()`，在 `find_current_slot(now)` 返回 `None` 时，除上一状态是 `sleeping` 外不会重置活动
    4. 在空档时间调用活动解析，会继续得到前一项活动而不是 `idle`
*   **预期行为**: 非睡眠空档应回落到 `idle`；仅睡觉结束后的短空档保留为 `waking_up`
*   **实际行为**: 非睡眠空档继续沿用上一项活动，导致 `peer chat` 和被动回复误判角色仍在忙碌/吃饭
*   **解决方案**:
    1. 新增 `activity_resolution.py` 统一解析计划活动
    2. 命中当前 slot 时直接返回 `slot.activity`
    3. 睡觉结束后的短空档保留 `waking_up`
    4. 其他无 slot 的空档统一回落到 `idle`

### 10.144 Active Care 状态同步包装器在事件循环内自锁，日志只剩空白 `同步包装器执行失败`（2026-06-29）

*   **问题描述**: 根目录 `errors_20260629.json` 与 `logs/errors/errors_20260629_*.json` 连续记录 `STATE_BASE` 的 `同步包装器执行失败: `，但异常消息为空，实际导致睡眠/起床等同步接口偶发失效。
*   **复现步骤**:
    1. 在已有运行中事件循环的线程内调用 `SleepStateManager.sync_sleep_time_sync(...)`
    2. 进入 `core/services/active_care/state/base.py` 的 `sync_to_async_wrapper`
    3. `wrapper()` 检测到当前线程存在运行中的 loop
    4. 代码执行 `asyncio.run_coroutine_threadsafe(coro, 当前 loop).result(timeout=30.0)`
    5. 由于等待发生在同一个事件循环线程，loop 无法推进协程，最终超时
    6. `TimeoutError` 的 `str(e)` 为空，日志只留下空白错误信息
*   **预期行为**: 即使同步接口是在事件循环线程里被调用，也应安全完成状态写入，至少不能把自己卡到超时。
*   **实际行为**: 同步包装器把协程重新提交到同一个 loop 后立即阻塞等待，形成同线程自锁；错误日志又因为 `TimeoutError` 字符串为空而丢失关键信息。
*   **根因**:
    1. `run_coroutine_threadsafe()` 只适合“其它线程向目标 loop 投递协程”，不适合同线程回投后再同步等待
    2. `future.result(timeout=30.0)` 直接阻塞了当前事件循环线程，导致协程永远没有机会执行
    3. 日志使用 `str(e)`，碰到 `TimeoutError` 时会得到空字符串，掩盖真实问题
*   **修复**:
    1. `core/services/active_care/state/base.py` 的 `sync_to_async_wrapper()` 改为：若当前线程已有运行中的事件循环，则在线程池中启动独立线程，并在独立线程里用新事件循环执行协程
    2. 保留“无运行中事件循环时直接 `asyncio.run(...)`”的轻量路径
    3. 错误日志改为 `repr(e)` + `exc_info=True`，保证超时类异常也能看见真实类型
    4. 新增 `tests/diagnostics/active_care_review/verify_state_sync_wrapper.py`，直接在 `asyncio.run()` 场景中调用 `sync_sleep_time_sync()` 做回归验证
*   **验证**: `venv_core\Scripts\python.exe tests\diagnostics\active_care_review\verify_state_sync_wrapper.py`
*   **验证**:
    - `venv_core\Scripts\python.exe -m pytest tests\character_daily\test_message_deferral.py -q -k "proactive_reply_window or reply_window_within_window_after_busy_reply or reply_window_expired_after_busy_reply or reply_window_does_not_apply_after_dnd_force_wake or reply_window_with_no_last_reply_state"`
    - `venv_core\Scripts\python.exe tests\character_daily\verify_proactive_reply_window.py`

### 10.143 Active Care 已主动发消息，但 ReplyPolicy 仍把 `sleep_recovery` 当忙碌态静默累积（2026-06-29）

*   **问题描述**: 日志显示 `08:09:32` 已发送 `Active Care reminder`，但用户在 `08:13:11` 回复后，`ReplyPolicy` 仍输出 `busy_defer_silent(activity=sleep_recovery)`，表现成“角色先主动找人，结果用户回她，她却继续不理”。
*   **复现步骤**:
    1. 同一 persona 先通过 `Active Care` 主动发送提醒消息
    2. 角色当前活动仍被 `character_daily.engine` 投影为 `sleep_recovery`
    3. 用户在几分钟内回复该 persona
    4. `chat_handlers` 调用 `evaluate_reply_state(...)`
    5. `ReplyPolicy` 仅依据 `sleep_recovery in BUSY_ACTIVITIES`，直接静默累积
*   **预期行为**: 只要同一个 persona 刚主动发过消息，短时间内用户回她就必须直接接话，不能再被 `sleep_recovery` 或其它 BUSY 投影拦住。

### 10.143 角色睡眠状态白天仍卡在 `sleeping`（根因：睡眠窗口解析把当天起床点错误推进到明天）(2026-06-28)

*   **问题描述**: 新版角色生活系统上线后，角色在白天长时间仍被判定为 `sleeping`，导致 `peer chat` 不触发、当前活动持续被覆盖成 `sleeping`，并在 `sleep_states.json` 中累计出十几小时甚至几十小时的异常睡眠时长。
*   **复现步骤**:
    1. 使用周末或带跨天作息的角色计划启动系统
    2. 让 `sleep_manager` 在白天调用 `get_state()` / `get_summary()`
    3. 观察 `_resolve_sleep_window()` 在白天返回的 `wake_dt` 被推进到次日
    4. `in_sleep_window` 持续为真，角色一直保持 `sleeping`
*   **预期行为**: 白天应回溯到“最近一晚 -> 本次起床”的睡眠窗口；过了起床点后，角色应切到 `waking_up / fully_awake`
*   **实际行为**: 白天使用了“今天睡 -> 明天起”的窗口，导致角色整天都落在错误睡眠窗口里
*   **根因**:
    1. 旧逻辑只根据 `now < wake_dt` 决定是否把 `sleep_dt` 前移或把 `wake_dt` 后移
    2. 当 `now >= wake_dt` 时，不区分“已经起床的白天”和“今晚还没睡”，直接把 `wake_dt` 加到明天
    3. 对 `00:xx 入睡 -> 当天早上起床` 与 `23:xx 入睡 -> 次日早上起床` 两类窗口都不够稳健
*   **修复**:
    1. 在 `sleep_manager.py` 中改为构造“昨天/今天/明天”三个候选睡眠窗口
    2. 优先选择当前时刻所在窗口；若当前不在睡眠中，则回溯到最近结束的窗口
    3. 新增 `next wake` 解析逻辑，单独计算下一次计划起床时间
    4. 增加旧脏状态纠偏，避免历史错误 `actual_sleep_start_ts` 继续算出几十小时睡眠
    5. 唤醒时同步清零 `current_sleep_duration_hours`
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\diagnostics\role_sleep\test_sleep_window_fix.py -q` 3/3 通过
    2. `venv_core\Scripts\python.exe tests\diagnostics\role_sleep\verify_sleep_window_fix.py` 输出 `OK`
    3. 实际刷新真实状态后，`aveline / ling` 已从 `sleeping` 恢复为 `fully_awake`
*   **教训**:
    1. 涉及跨天时间窗时，不能只靠“当前时刻是否小于 wake_dt”做单点判断
    2. 睡眠/作息系统既要支持 `23:xx -> 次日早上`，也要支持 `00:xx -> 当天早上`
    3. 修复状态机 bug 时，要同时考虑已落盘脏状态的自动恢复

### 10.143 ReminderInjection 异步调用漏 await 导致运行时警告与提醒注入失效（2026-06-28）

*   **问题描述**: 对话链路日志出现 `RuntimeWarning: coroutine 'ReminderInjectionStore.get_and_clear' was never awaited`，同时 Active Care 的到期提醒在用户聊天中本应注入主对话，但实际可能未真正写入或读取，提醒自然融入回复的功能失效。
*   **复现步骤**:
    1. 用户正在聊天，`stream_orchestrator` 已更新最近交互时间
    2. Active Care 检测到到期提醒，进入 `CheckerEventHandler.handle_due_reminder()`
    3. 代码调用 `injection_store.set_pending_reminder(...)`，但没有 `await`
    4. 下一轮主对话进入 `stream_chat_impl()`，代码调用 `injection_store.get_and_clear()`，也没有 `await`
    5. 运行时出现 `coroutine ... was never awaited`，提醒对象未按预期进入上下文
*   **预期行为**: 提醒写入和读取都应作为异步调用被正确 `await`，提醒内容能稳定注入主对话上下文，且日志中不再出现未等待协程告警。
*   **实际行为**: 写入侧把协程对象直接丢弃，读取侧把协程对象当成普通结果使用，最终产生运行时警告并破坏提醒注入链路。
*   **根因**:
    1. `core/services/active_care/checker/checker_event_handler.py` 把 `ReminderInjectionStore.set_pending_reminder()` 当成同步函数调用
    2. `core/agents/chat_agent_components/streaming.py` 把 `ReminderInjectionStore.get_and_clear()` 当成同步返回值使用
    3. 这两个方法内部都依赖 `asyncio.Lock`，本质上必须通过 `await` 执行
*   **修复**:
    1. `checker_event_handler.py` 中改为 `await injection_store.set_pending_reminder(...)`
    2. `streaming.py` 中改为 `await injection_store.get_and_clear()`
    3. 新增 `tests/unit/test_reminder_injection_awaits.py`，分别验证写入与读取两侧都真的发生了 await
*   **验证**: `venv_core\Scripts\python.exe -m pytest tests\unit\test_reminder_injection_awaits.py`

### 10.142 `core.tools.study` 删除后，学习服务与主动关怀仍残留旧子模块路径（2026-06-28）

*   **问题描述**: 即使 `ChatAgent` 已做导入降级，`StudyService`、主动关怀每日单词测验、学习工具注册等链路仍保留对 `core.tools.study.english.word_quiz_tool`、数学/生物/语文/地理工具的旧路径引用，一旦触发对应功能仍会继续报 `ModuleNotFoundError` 或暴露不可用工具。
*   **复现步骤**:
    1. 当前仓库缺失大部分历史 `core/tools/study/` 子模块
    2. 访问 `/api/v1/vocab/tools`、主动关怀每日生词测验、或调用学习工具注册的 `word_quiz`
    3. 代码进入 `core.services.study.dispatch`、`core.services.active_care.shared.vocabulary`、`core.tools.study_tools`
    4. 触发旧的 `word_quiz_tool` 或其它未恢复学科工具导入
    5. 出现导入失败，或前端看到实际上不可用的工具项
*   **预期行为**: 项目只暴露当前仓库中仍可用的学习能力；未恢复的旧学科工具不应继续出现在运行链和工具清单中。
*   **实际行为**: 词汇主链可用，但生词测验和工具清单仍连接到已经删除的历史模块。
*   **根因**: `core.tools.study` 当天被整体删除时，仅修了部分入口；业务层、工具层和主动关怀层仍残留对历史学习工具子模块的硬编码路径。
*   **修复**:
    1. 恢复 `core/tools/study/english/vocabulary_manager.py`
    2. 恢复 `core/tools/study/common/data_io.py` 与其依赖 `core/tools/study/common/utils.py`
    3. `StudyService` 去除对未恢复学科工具的硬依赖，综合计划仅保留词汇任务
    4. `ToolDispatcher` 直接基于 `VocabularyManager` 实现 `word_quiz`
    5. Active Care 的每日生词测验改为通过 `StudyService` 调度
    6. 工具清单收敛为当前仍可用的 `english.word_quiz` 与 `study_data.manage`
    7. 删除不再适配当前仓库的 `tests/verification/verify_math_image_generator_split.py`
    8. 新增 `tests/diagnostics/verify_study_vocab_recovery.py` 验证恢复结果
*   **验证**: `venv_core\Scripts\python.exe tests\diagnostics\verify_study_vocab_recovery.py`

## 10. 开发经验与回顾 (Development Retrospective)

### 10.140 Active Care reminder 被"句子级部分包含检测"误判导致整批 reminder 发不出 (2026-06-27)


*   **问题描述**: 用户反馈"这几天他基本都没根据每日计划的时间给我发消息提醒"。检查 `companion_data/user_data/reminders.json` 发现 6/27 全天 reminder status 全是 pending；检查 `logs/2026/6/27/active_care_schedule.log` 发现 LLM 生成成功但被 postprocessor 拦截，日志提示"句子级部分包含检测命中"。
*   **复现步骤**:
    1. `llm_plan_generator` 生成 plan.json（含 description/category/subject 字段）；
    2. `plan_service._sync_plan_to_reminders` 把每个计划项同步为 reminder，但 metadata 只带 `task_title`，丢弃了 description；
    3. reminder 到期，`checker_event_handler.handle_due_reminder` 调 `executor.format_due_reminder_message` 拿到模板话"我来盯你一下，该开始「X」了。"；
    4. `executor.trigger_message` 把模板话注入 `TASK_REMINDER_TEMPLATE` 给 LLM；
    5. LLM 顺着模板话风格输出"该开始X了"之类的短模板句；
    6. `postprocessor.postprocess` 调 `deduplicator.is_partially_repetitive`，命中历史 anchor（同类提醒发过太多次）；
    7. postprocessor 返回 None；
    8. executor L379-381 `if not post_processed: self._last_skip_reason = "generation_failed"; return False`；
    9. 不进入 `dispatch_message` → reminder 永远不发出，也不落盘。
*   **预期行为**: 到了计划时间点，active care 应该自然地提醒用户该做某项计划了，且每次说法不重复。
*   **实际行为**: reminder 全部 pending，从不发出，用户感受不到"联动"。
*   **原因分析**:
    1. `plan_service._sync_plan_to_reminders` 没把 `description`/`category`/`subject` 注入 metadata，下游 LLM 缺差异化素材；
    2. `reminder_handler.format_due_reminder_message` 直接输出固定模板话，LLM 顺着模板风格输出短句；
    3. `TASK_REMINDER_TEMPLATE` 没约束 LLM 避开机械句式，没要求换角度。
*   **解决方案**: 按用户明确要求"让 LLM 输出更自然，不要绕过去重检测"：
    1. `plan_service._sync_plan_to_reminders` 注入 `task_description` / `task_category` / `task_subject` 到 metadata（开始和结束提醒都改）；
    2. `reminder_handler.format_due_reminder_message` 改造为输出结构化上下文"任务「X」到时间该开始了；计划内容：...；分类：..."（兼容旧数据），不再写死模板话；
    3. `active_care_prompts.TASK_REMINDER_TEMPLATE` 加 5 条约束：严禁"该开始X了"等机械模板、基于描述找个性化切入点、不复用旧句式、简短一句。
*   **验证**: 新建 `tests/diagnostics/active_care_review/verify_reminder_natural_output.py` 5/5 通过，关键证明：自然输出 3/3 通过重复检测，机械模板话 2/2 被拦。
*   **状态**: ✅ 已修复，需重启服务后观察次日 reminder 发送情况

### 10.139 NightlyProcessor 记忆蒸馏全部失败：子线程新建 event loop 触发 aiohttp timeout 上下文错误（2026-06-27）

*   **问题描述**: 检查发现 nightly processor 的记忆蒸馏完全没有正常运行。2026-06-26 05:23:00 凌晨处理时 `private_10001__scope__aveline` 有 50 条待蒸馏记忆，50 条全部失败，每条都返回空响应（`summary='', keywords=[], response_len=0`），全部在同一秒内失败返回。
*   **复现步骤**:
    1. NightlyProcessor 调度器在子线程 `nightly-scheduler` 中运行 `process_all_users`（同步方法）；
    2. 调用 `_run_nightly_async_tasks` 桥接异步任务；
    3. 桥接器中 `asyncio.get_running_loop()` 在子线程抛 `RuntimeError`，走 else 分支；
    4. 创建新 event loop 并 `loop.run_until_complete(self._execute_async_tasks(...))`；
    5. 蒸馏协程调用 `scheduler.submit_llm_task` → `llm_module.stream_chat` → `OpenAIClient.stream_chat`；
    6. `aiohttp.ClientSession.post(...)` 流式请求触发 `RuntimeError: Timeout context manager should be used inside a task`；
    7. `stream_chat` 捕获异常后 yield error dict，但 `submit_llm_task` 只取 `content`/`text` 字段，导致 `full_response` 为空字符串；
    8. 解析为空 summary，蒸馏结果为空，跳过更新。
*   **预期行为**: nightly processor 应在主事件循环上调度异步任务（`run_coroutine_threadsafe`），使 aiohttp 的 ClientTimeout 上下文正确检测到 task；记忆蒸馏应正常调用 LLM 并更新梗概/关键词。
*   **实际行为**: 50 条待蒸馏记忆 0 条成功，所有 LLM 调用立即失败返回空。同时分析结果保存也失败（`Permission denied: 'D:\\AI\\history\\analysis\\...'`）。
*   **原因分析**:
    1. `_run_nightly_async_tasks` 的注释说"使用主事件循环执行异步任务"，但实际代码用 `asyncio.get_running_loop()` 仅能拿到当前线程的 running loop，在子线程中永远返回 None，无法获取主 loop；
    2. 创建新 event loop 后，aiohttp 的 `ClientTimeout` 在 Python 3.10+ 通过 `asyncio.tasks.get_current_task()` 检测 task 上下文，新 loop 中流式 async generator 跨层 yield 时丢失 task 上下文，触发错误；
    3. `ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "history" / "analysis"` 多上跳了一级，指向项目外 `D:\AI\history\analysis`（不存在），导致 Permission denied。
*   **解决方案**:
    1. 在 `core/lifecycle/lifespan.py` 中导出 `get_main_loop()` 公开函数，返回 `_main_loop`；
    2. 修改 `nightly_processor._run_nightly_async_tasks`，优先用主 loop 的 `run_coroutine_threadsafe(coro, main_loop).result(timeout=...)`，仅在拿不到主 loop 时才回退到新 loop；
    3. 修复 `ANALYSIS_DIR` 路径为 `parents[1] / "history" / "analysis"`（项目根 `d:\AI\xiaoyou-core\history\analysis`）。
*   **状态**: ✅ 已修复，需重启服务后观察下一晚蒸馏日志验证

### 10.136 Active Care Storage 并发写入 WinError 2（第三次复发，根因：async 临时文件名非唯一）(2026-06-27)

*   **问题描述**: Active Care Storage 写入 `proactive_state.json` 时报错 `[WinError 2] 系统找不到指定的文件。: '...proactive_state.json.tmp' -> '...proactive_state.json'`
*   **复现步骤**:
    1. 多个 `ActiveCareStorage` 实例并发存在（`nightly_processor` / `anomaly_detector` / `active_care/state/base` / `active_care/core/service` 各自 `ActiveCareStorage()`）
    2. 多个实例并发写入同一 scope 的 `proactive_state.json`
    3. `async_safe_json_dump` 使用固定 `.tmp` 临时文件名，实例 A `os.replace` 成功后 `.tmp` 消失，实例 B `os.replace` 报 WinError 2
*   **预期行为**: 并发写入同一目标文件不应失败
*   **实际行为**: 部分写入抛出 `FileNotFoundError` / `WinError 2`
*   **根因**:
    1. **直接原因**: `async_safe_json_dump` 使用 `file_path + ".tmp"` 固定临时文件名（与同步版本不一致），多个并发写入共用同一 `.tmp` 导致竞态
    2. **前两次修复（10.109 / 10.116）未触及根因**: 10.109 把 `.tmp` 写入移入重试循环，10.116 改用 `asyncio.to_thread(os.replace)` + fsync 错误处理，但都仍用固定 `.tmp`，竞态依旧
    3. **`_generate_temp_path` 也不够**: 旧实现 `tmp_{thread_id}_{pid}`，但 asyncio 协程共享同一线程，`threading.get_ident()` 相同，仍会碰撞
*   **修复**:
    1. `_generate_temp_path` 追加 `uuid.uuid4().hex`，保证每次调用唯一（async 协程 + 多线程 + 多进程均安全）
    2. `async_safe_json_dump` 改用 `_generate_temp_path` 替代固定 `.tmp`
    3. 新增 `tests/verification/test_concurrent_atomic_write.py`：20 并发写入 + 多 Storage 实例并发 + 唯一性回归
*   **涉及文件**: `core/utils/atomic_io.py`, `tests/verification/test_concurrent_atomic_write.py`
*   **教训**: 修 Bug 必须定位到根因，不能只处理表面症状。前两次修复都只处理了"重试"和"fsync"，却没发现临时文件名本身才是竞态源头。

### 10.135 `_record_peer_chat` 双计数导致硬上限提前触发（2026-06-26）

*   **问题描述**: CharacterDailyEngine 的 peer chat 硬上限配置为 6 次，但实际第 3 次真实聊天就被阻止。
*   **复现步骤**:
    *   触发一次 peer chat，`_record_peer_chat` 给发起者和对方都 `today_peer_chat_count += 1`
    *   `peer_chat_gate.py` 的 `total_today = plan_a.count + plan_l.count` 求和
    *   每次真实聊天让 `total_today` +2，硬上限 6 在 3 次后触发
*   **预期行为**: 硬上限 6 应允许 6 次真实聊天。
*   **实际行为**: 第 3 次就触发硬上限，CharacterDailyEngine 的频率控制比设计更严格。
*   **原因分析**: `_record_peer_chat` 双方都 +1 是为了同步时间戳，但计数器不应该双方都加。门控的 `total_today` 不应该简单求和。
*   **解决方案**: 只给发起者 `today_peer_chat_count += 1`，门控改用 `max(plan_a.count, plan_l.count)`。

### 10.134 PeerChatScheduler 双系统并行导致 peer chat 频率失控（2026-06-26）

*   **问题描述**: 用户观察到双角色互聊（peer chat）每天触发次数远超预期的 4-6 次。
*   **复现步骤**:
    *   系统启动时 PeerChatScheduler 先初始化并启动 `_run_loop()`
    *   之后 CharacterDailyEngine 初始化并启动自己的主循环
    *   PeerChatScheduler 的 `_run_loop()` 没有退出机制，两个循环同时触发 peer chat
*   **预期行为**: CharacterDailyEngine 启动后，PeerChatScheduler 应让出调度权，只由一个系统触发。
*   **实际行为**: 两个系统各自独立触发，频率叠加，总计可达 15+ 次/天。
*   **原因分析**: `PeerChatScheduler.start()` 只在启动时检查 `_is_character_daily_active()`，已运行的 `_run_loop()` 不会因 CharacterDailyEngine 启动而退出。`ensure_running()` 虽检测到 engine active 但不取消已有 task。
*   **解决方案**: 在 `_run_loop()` 的 while 循环内每次迭代检查 `_is_character_daily_active()`，检测到后主动退出。

### 10.136 Active Care 重复主程序已回过的消息（2026-06-20）

*   **问题描述**: Active Care 在主程序（chat agent）回复用户后 30 分钟内触发时，生成的消息内容与主程序的回复高度重复，像是"回复主程序已回过的消息"。
*   **复现步骤**:
    *   主程序回复用户（如"蚊子包涂花露水了没？然后去吃早饭"）；
    *   30 分钟内（< 1800 秒）Active Care 触发；
    *   Active Care 生成的消息围绕主程序的话题重复（如"饱了""怎么还不去睡觉"）。
*   **预期行为**: Active Care 不应把主程序的回复作为延续锚点，不应围绕主程序的话题重复。
*   **实际行为**: `_build_model_user_input_for_active_care()` 的 `else` 分支把 `last_assistant_message`（主程序回复）作为 `continuation_anchor`，注入 `[LAST_ASSISTANT_MESSAGE]` 要求 LLM"顺着主程序的话往下推进"。同时 `continuation_guard` 在所有模式下都注入，与主动触发模式的"开启新话题"矛盾。
*   **原因分析**:
    *   延续模式不区分"主程序回复"和"active care 主动消息"，把主程序的回复当作自己的话来延续；
    *   `continuation_guard` 在长沉默（主动触发模式）下仍然注入，要求"必须围绕最近话题继续，不要另起新话题"，与 `CONTEXT_GUARD_LONG_SILENCE` 的"开启新话题"直接矛盾；
    *   `recent_history_text` 中所有助手消息都标为 "Assistant"，没有区分主程序回复和主动消息。
*   **解决方案**:
    *   `_build_model_user_input_for_active_care()` 新增"主程序回复防护"：当 `last_assistant_message` 不是 active care 主动消息时，不把它作为延续锚点；
    *   `_build_language_guard()` 新增 `is_long_silence` 参数：长沉默时不注入 `continuation_guard`；
    *   `_build_recent_history_text()` 明确标注 `Assistant(主程序回复,不要重复)` vs `Assistant(你之前主动发起)`。

### 问题 4: dual_role 模块"缺失"实为工具误报 (2026-06-17)


*   **问题描述**: 全面分析报告中称 `core/services/dual_role/` 目录缺失，`persona_exports.py` 的裸 import 是定时炸弹。
*   **复现步骤**: 使用 Glob 工具搜索 `core/services/dual_role/**/*.py` 返回空结果，LS 工具列出 `core/services/` 也未显示 dual_role 目录。
*   **预期行为**: dual_role 模块应存在（被 `persona_exports.py`、`peer_script_generator.py`、`peer_chat_scheduler.py`、测试文件等 7 处引用）。
*   **实际行为**: Glob 和 LS 工具未找到该目录，但 Python import 实际能成功。
*   **根因**: 工具的路径匹配问题（Windows 路径分隔符或大小写）。用 PowerShell `Get-ChildItem -Force` 确认目录完整存在，包含 8 个文件。
*   **结论**: 问题不存在，dual_role 模块健康。peer_chat 是 dual_role 功能的实际承载者（`__init__.py` 注释说明功能已合并到 PeerChatScheduler）。

## 2026-06-27 后端问题修复记录

### 问题 2: ActiveCare storage scope 并发状态泄漏 (2026-06-17)


*   **问题描述**: `ActiveCareStorage._runtime_scope` 是实例级可变状态，`proactive_checker` 在双QQ模式下会调用 `set_runtime_scope` 切换 scope。但 `user_response_handler.reset_interaction_state` 在调用 `save_proactive_state`/`get_proactive_state` 时不设置 scope，会使用 `proactive_checker` 残留的 scope，导致用户交互时间戳写到错误的 persona 目录。更严重的是，延迟写入 `_flush_pending_updates` 在 flush 时调用 `_get_runtime_dir()`，如果 scope 已被切换，数据会写到错误目录。
*   **复现步骤**:
    1. 双QQ模式运行，`proactive_checker` 设置 `scope=aveline` 执行决策
    2. 同时用户发消息触发 `user_response_handler.reset_interaction_state(persona_filename="ling")`
    3. `reset_interaction_state` 调用 `save_proactive_state({"last_user_interaction_ts": ...})` 不传 scope
    4. 数据被写到 aveline 目录而非 ling 目录
*   **预期行为**: `user_response_handler` 的状态写入应写到 `persona_filename` 对应的 scope 目录，不受 `proactive_checker` 的实例状态影响。
*   **实际行为**: 数据写到 `proactive_checker` 残留的 scope 目录，双QQ模式下用户交互时间戳记录混乱。
*   **修复方案**: 给 `_get_runtime_dir`/`get_proactive_state`/`save_proactive_state` 加可选 `scope` 参数。传入时走并发安全独立路径（不使用实例缓存、不依赖实例状态、立即写入不延迟）。`reset_interaction_state` 根据 `persona_filename` 解析 scope 并显式传入。
*   **验证**: `tests/verification/test_p0_fixes.py` 的 `test_p0_4_storage_scope_concurrency` 和 `test_p0_4_concurrent_simulation` 通过（含两个协程并发操作不同 scope 的模拟测试，数据完全隔离）。

### 10.120 Active Care 双QQ模式人设混乱 (2026-06-01)

*   **问题描述**: 双QQ模式下，玲的主动关怀消息像Aveline的语气（"想你了，你先安心休息"），Aveline的主动关怀消息像玲的语气（"emmmm不提那个了"）
*   **复现步骤**:
    1. 启用双QQ模式（Aveline + 玲同时在线）
    2. 等待主动关怀触发
    3. 观察两个角色发出的消息，发现语气互换
*   **预期行为**: 玲的主动关怀应使用玲的语气（随意腼腆），Aveline应使用Aveline的语气（冷淡命令式）
*   **实际行为**: 人设语气互换
*   **根本原因**: `executor.py` 的 `_resolve_target_conversation()` 在方法开头就根据 `resolve_primary_conversation_id()` 设置了scope（双QQ模式下总是返回Aveline的cid），但QQ persona覆盖了 `target_conversation_id` 后没有同步更新scope。导致为玲生成消息时读取了Aveline的 `proactive_state.json`
*   **修复方案**: 将scope设置移到最终 `target_conversation_id` 确定之后，并为两个人设添加 `active_care_guidelines` 强化语气区分

### 10.120 Active Care 看不到聊天上下文 (2026-05-31)

*   **问题描述**: Active Care 发出的消息无视了刚结束的对话上下文，问"看得什么类型的"和"中午吃了吗"，而用户刚聊完外卖和代码
*   **复现步骤**:
    1. Dual QQ 模式下，用户与 Aveline 聊天
    2. 对话结束后约 13 分钟，Active Care 触发主动关怀
    3. 生成的消息不引用最近的对话内容
*   **预期行为**: 消息应延续最近的对话话题
*   **实际行为**: 消息是通用的问候，无视了最近的对话
*   **根因**: `context.py` 的 `get_latest_history` 使用全局 PersonaManager 的 persona token 过滤候选对话。在 dual QQ 模式下，全局 persona 可能与正在处理的 persona 不一致，导致从错误的对话获取历史。
*   **修复**:
    1. `context.py` 的 `get_candidate_conversation_ids` 和 `get_latest_history` 新增 `persona_filename` 参数
    2. `proactive_checker.py` 和 `decision_executor.py` 传递 `persona_filename`

### 10.119 Active Care 消息风格像Ling而不是 Aveline (2026-05-31)

*   **问题描述**: Active Care 发出的消息"哈喽？"、"又被别的事拐跑了？"、"昂～我刚才在看小说lol"风格像Ling而不是 Aveline
*   **复现步骤**:
    1. Dual QQ 模式下，Aveline 和 Wang Ling 各有独立的 QQ adapter
    2. Active Care 触发主动关怀消息，为 Aveline 生成内容
    3. 消息从 Wang Ling 的 QQ 账号发出（因为路由 bug）
*   **预期行为**: 消息应从 Aveline 的 QQ 账号发出
*   **实际行为**: 消息从 Wang Ling 的 QQ 账号发出（由于竞态条件，Wang Ling 的 adapter 先处理了消息）
*   **根因**: `qq_adapter_session.py` 中 proactive message 路由逻辑只检查 `base_cid == self.session_id`，但在 dual QQ 模式下两个 adapter 共享同一个 base_cid，导致两个 adapter 都会匹配。存在竞态条件，错误的 adapter 可能先处理消息。
*   **修复**:
    1. `qq_adapter_session.py` 修复路由逻辑，使用 `build_persona_conversation_id` 构建期望的 conversation_id 进行精确匹配

### 10.118 Active Care 消息从错误的 QQ 账号发送 (2026-05-30)

*   **问题描述**: 用户在和七濑澪聊数学，但 active care 服务从Ling的 QQ 账号发送了消息。
*   **复现步骤**: 用户与七濑澪聊天，active care 服务触发主动关怀消息，消息从Ling的 QQ 发送。
*   **预期行为**: 消息应从七濑澪的 QQ 账号发送。
*   **实际行为**: 消息从Ling的 QQ 账号发送。
*   **调试结果**: 1) 当前 persona 是七濑澪 (Aveline_QQ_Master.json)；2) _recent_user_message_cache 为空；3) 没有检测到活跃的 QQ 连接实例；4) resolve_primary_conversation_id 返回 private_10001。
*   **可能原因**: QQ 适配器实例未注册，或 active care 服务使用了错误的连接。
*   **解决方案**: 在 executor.py 的 _get_qq_connections 方法中添加临时日志，以确认实例注册情况。

### 10.116 Active Care Storage 写入文件失败 Bad file descriptor / WinError 2 (2026-05-29)

*   **问题描述**: Active Care Storage 写入 `proactive_state.json` 时报错：
    - `[Errno 9] Bad file descriptor` - aiofiles 异步文件对象的 fileno() 无效
    - `[WinError 2] 系统找不到指定的文件` - aiofiles.os.replace 在 Windows 上不可靠
*   **复现步骤**:
    1. 使用 aiofiles 异步写入文件
    2. 调用 `os.fsync(f.fileno())` 时文件描述符无效
    3. 调用 `aiofiles.os.replace()` 在 Windows 上失败
*   **预期行为**: 文件正常写入，无报错
*   **实际行为**: 报错 `[Errno 9] Bad file descriptor` 或 `[WinError 2]`
*   **根本原因**: 
    1. `aiofiles` 包装了底层同步文件对象，直接调用 `f.fileno()` 返回的描述符在异步上下文中无效
    2. `aiofiles.os.replace` 在 Windows 上实现有问题，应使用 `os.replace`
*   **修复**: 修改 `core/utils/atomic_io.py`
    1. 使用 `f._file.fileno()` 访问底层同步文件对象
    2. 统一使用 `asyncio.to_thread(os.replace, ...)` 替代 `aiofiles.os.replace`
    3. 添加临时文件存在性检查
    4. 添加 fsync 错误处理，避免因 fsync 失败导致整个写入操作失败

### 10.109 Active Care Storage 写入文件失败 WinError 2 (2026-05-17)

*   **问题描述**: Active Care Storage 写入 `proactive_state.json` 时报错 `[WinError 2] 系统找不到指定的文件。: '...proactive_state.json.tmp' -> '...proactive_state.json'`
*   **复现步骤**:
    1. 系统运行 Active Care 模块，调用 `save_proactive_state` 写入状态
    2. `_write_json_file_unlocked` 先写入 `.tmp` 临时文件，再调用 `os.replace` 原子替换
    3. `os.replace` 抛出 `WinError 2`，源 `.tmp` 文件不存在
*   **预期行为**: `.tmp` 文件写入后应成功被 `os.replace` 替换为目标文件
*   **实际行为**: `os.replace` 因源文件不存在而失败，3次重试均失败（重试不会重新创建 `.tmp` 文件）
*   **根因**: 三重问题叠加：
    1. `aiofiles.open` 写入后没有显式 `flush()` + `os.fsync()`，Windows 上文件可能还在 OS 缓冲区中，尚未真正落盘
    2. Windows 上杀毒软件（如 Windows Defender）可能扫描并临时锁定/删除新创建的 `.tmp` 文件
    3. 重试逻辑有缺陷：当 `os.replace` 因源文件不存在而失败时，重试只是再次调用 `os.replace`，不会重新创建 `.tmp` 文件，导致无限重试一个不存在的文件
*   **修复方案**:
    1. 将 `.tmp` 文件写入移入重试循环内，每次重试都重新写入 `.tmp` 文件
    2. 写入后添加 `await f.flush()` + `os.fsync(f.fileno())` 确保数据落盘
    3. `os.replace` 前检查 `.tmp` 文件是否存在，不存在则等待后重新写入
    4. 最终失败后清理残留的 `.tmp` 文件
*   **涉及文件**: `core/services/active_care/storage.py`

### 10.108 Goodnight 低打扰模式无法退出（用户发早安仍卡在 goodnight 模式）(2026-05-14)

*   **问题描述**: 用户早上发送"早安"后，Active Care 仍然处于 goodnight 低打扰模式，不发送任何消息。日志显示 "due_reminder 跳过，用户处于低打扰模式 (reason=goodnight)"
*   **复现步骤**:
    1. 用户昨晚说了晚安，系统进入 goodnight 低打扰模式
    2. 用户今早发送"早安"
    3. `_reset_interaction_state` 被调用，但只清除 `probable_sleep`/`sleep_hint`，不清除 `goodnight`
    4. 5分钟后 `perform_check` 运行，`_try_exit_goodnight_on_awake_signals` 检测到 `inferred_goodmorning=True`
    5. 但如果 `inferred_signal_after_goodnight=False`（如 `inferred_ts=0`），所有退出条件均失败
    6. 系统卡在 goodnight 模式
*   **预期行为**: 用户发送"早安"后，系统应立即退出 goodnight 模式，恢复正常消息发送
*   **实际行为**: 系统持续处于 goodnight 低打扰模式，不发送任何消息
*   **根因**: 两处逻辑缺陷：
    1. `_try_exit_goodnight_on_awake_signals` 条件1要求 `inferred_goodmorning AND inferred_signal_after_goodnight` 同时为 True，但当 `inferred_ts=0` 时 `inferred_signal_after_goodnight` 为 False，导致 `inferred_goodmorning` 无法独立触发退出。条件1的第三子条件 `recent_user_signal_after_goodnight AND NOT inferred_goodmorning` 在 `inferred_goodmorning=True` 时也为 False，形成死锁
    2. `_reset_interaction_state` 只清除 `probable_sleep`/`sleep_hint` 模式，不清除 `goodnight` 模式，缺少即时退出路径
*   **修复方案**:
    1. `proactive_checker.py`：重构 `_try_exit_goodnight_on_awake_signals`，将 `inferred_goodmorning` 提升为最高优先级退出条件，只要检测到早安意图且处于 goodnight 模式就立即退出，不再要求 `inferred_signal_after_goodnight`
    2. `service.py`：在 `_reset_interaction_state` 中添加 goodnight 模式退出检测——如果用户消息含早安关键词或当前为白天(10-18点)，立即退出 goodnight 模式
    3. 添加详细日志，记录退出条件和信号值，方便诊断
*   **涉及文件**: `core/services/active_care/proactive_checker.py`、`core/services/active_care/service.py`

### 10.106 Active Care LLM 推理过程泄漏为消息 (2026-05-13)

*   **问题描述**: Active Care 将 LLM 的推理过程（"好的，现在我是七濑澪..."、"用户状态显示他身体偏瘦..."等）作为消息发送给用户
*   **复现步骤**:
    1. Active Care 触发消息生成
    2. MiniMax-M2.5 返回推理内容（不用 `<think/>` 标签包裹，是纯文本推理）
    3. `_handle_reasoning_only_response` 调用 `strip_reasoning_segments`，剥离后非空
    4. 方法返回**原始 text**（包含推理），而非 stripped 版本
    5. 推理内容被发送给用户
*   **预期行为**: 推理内容应被过滤，只发送实际消息
*   **实际行为**: LLM 的推理过程被逐行发送为消息
*   **根因**: 1) `_handle_reasoning_only_response` 返回原始 text 而非 stripped；2) `looks_like_prompt_or_reasoning_dump` 不识别 MiniMax-M2.5 的推理格式；3) 之前 Active Care 一直超时，此代码路径很少被执行
*   **修复方案**:
    1. `_handle_reasoning_only_response` 改为返回 stripped 而非原始 text
    2. 添加 `looks_like_prompt_or_reasoning_dump` 检查：剥离后仍像推理泄漏则走 fallback
    3. 增强 `reasoning_language_markers`：添加 "我需要自然衔接"、"现在我是"、"当前时间是"、"用户状态显示" 等
    4. 提取 `_try_fallback_for_reasoning` 方法，避免代码重复
*   **涉及文件**: `core/services/active_care/executor.py`、`core/services/active_care/postprocessor.py`

### 10.105 Active Care 中午12点发送起床提醒（用户已起床） (2026-05-13)

*   **问题描述**: 用户已起床并聊天，但 Active Care 在中午12点发送"小澪让你起床了——别装死，笨蛋"的起床提醒
*   **复现步骤**:
    1. 5月1日系统创建了起床提醒（trigger_ts=5月1日08:15），存入 reminders.json
    2. 由于之前 perform_check 一直超时，提醒从未成功发送
    3. `check_reminders()` 用 `mark_completed=False`，不自动标记完成
    4. `complete_reminder()` 只在发送成功后调用，发送失败则 reminder 永远 pending
    5. 5月13日12点，5月1日的提醒仍然 `trigger_ts <= now`，被 `check_due_messages()` 返回
    6. `_handle_due_reminder` 不检查用户是否已起床，直接发送
*   **预期行为**: 用户已起床后不应发送起床提醒；超过24小时的过期提醒应自动清理
*   **实际行为**: 12天前的起床提醒仍然生效，用户已起床也照发
*   **根因**: 1) reminders.json 中的旧提醒从未被清理；2) `_handle_due_reminder` 不检查用户是否已起床；3) `check_reminders()` 不自动标记过期提醒
*   **修复方案**:
    1. `_handle_due_reminder` 添加过期检查：超过24小时的 pending reminder 自动标记为 completed 并跳过
    2. `_handle_due_reminder` 添加起床检查：如果 reminder 包含起床关键词且用户已起床（`last_goodmorning_ts > 0`），跳过并标记完成
    3. 清理 reminders.json 中的过期数据
*   **涉及文件**: `core/services/active_care/proactive_checker.py`、`companion_data/user_data/reminders.json`

### 10.104 Active Care conversation_incomplete 绕过交互保护导致退避惩罚完全失效 (2026-05-12)

*   **问题描述**: 用户不回复 Active Care 消息时，退避惩罚完全失效，系统仍以约 15-20 分钟频率持续发送消息
*   **复现步骤**:
    1. Active Care 发送消息（如"在干嘛"），系统标记 `conversation_incomplete=True`
    2. 用户不回复，`non_response_count` 递增
    3. 下次检查时，`conversation_incomplete` 为 True，代码绕过 `recent_user_interaction_guard`
    4. 即使 `non_response_count >= 2`，只要过了 `scaled_min_quiet`，也会绕过
    5. 退避惩罚被完全绕过，系统继续发送消息
*   **预期行为**: 连续不回复时，退避惩罚应生效，间隔应显著增加
*   **实际行为**: `conversation_incomplete` 绕过了交互保护，退避惩罚完全失效
*   **根因**: `_execute_send_or_skip` 中 `conversation_incomplete` 的逻辑允许绕过 `recent_user_interaction_guard`，即使 `non_response_count >= 2` 也会在过了安静期后绕过
*   **修复方案**:
    1. `non_response_count >= 2` 时，不再绕过交互保护（无论是否 conversation_incomplete）
    2. 加大退避基数 1.4→1.8，CAP 6.0→12.0
    3. 新增 `MAX_CONSECUTIVE_NON_RESPONSES_BEFORE_SKIP=4`，超过4次直接跳过
*   **涉及文件**: `core/services/active_care/proactive_checker.py`、`core/services/active_care/constants.py`

### 10.103 Active Care 连续无响应时没有有效延时惩罚，每20分钟发一条 (2026-05-12)

*   **问题描述**: 用户不回复 Active Care 消息时，系统仍以约 15-20 分钟的频率持续发送消息，退避惩罚效果太弱
*   **复现步骤**:
    1. Active Care 发送消息，用户不回复
    2. `_update_non_response_count` 递增计数器
    3. 退避乘数 `1.4^n` 太小：3次不回复仅 2.74 倍，5次仅 5.38 倍
    4. `min_gap_seconds=600s * 5.38 = 3226s ≈ 53min`，但 LLM 返回的 `next_check_seconds` 可能更小
    5. 实际间隔仍为 15-20 分钟
*   **预期行为**: 连续不回复时，间隔应显著增加；超过一定次数后应停止发送
*   **实际行为**: 间隔增长太慢，用户被持续打扰
*   **根因**: 1) 退避基数 1.4 太小；2) CAP 6.0 太低；3) 没有连续无响应上限
*   **修复方案**:
    1. 退避基数从 1.4 增加到 1.8（3次不回复就 5.8 倍，5次就 18.9 倍）
    2. CAP 从 6.0 增加到 12.0（最多放大 12 倍，即 2 小时间隔）
    3. 新增 `MAX_CONSECUTIVE_NON_RESPONSES_BEFORE_SKIP=4`，超过 4 次不回复直接跳过，1小时后再检查
*   **涉及文件**: `core/services/active_care/constants.py`、`core/services/active_care/proactive_checker.py`

### 10.102 Active Care 优先级分析缓存未随睡眠状态失效 (2026-05-12)

*   **问题描述**: 用户已起床，但 `analyze_daily_push_priority` 返回的缓存优先级仍包含"叫用户起床"等睡眠相关项目，导致 Active Care 发送"还没起来"的消息
*   **复现步骤**:
    1. 用户说晚安，系统进入 goodnight reduced mode
    2. `analyze_daily_push_priority` 执行 LLM 分析，生成包含"叫起床"的优先级列表，缓存1小时
    3. 用户起床，`reduced_mode_active` 变为 False
    4. 1小时内下次检查时，`analyze_daily_push_priority` 返回缓存结果（仍包含"叫起床"）
    5. Active Care 按缓存优先级发送"还没起来"的消息
*   **预期行为**: 睡眠状态变化时，缓存应失效，重新进行 LLM 分析
*   **实际行为**: 缓存不感知睡眠状态变化，继续返回旧优先级
*   **根因**: `analyze_daily_push_priority` 的缓存逻辑只检查时间间隔，不检查 `reduced_mode_active` 是否变化
*   **修复方案**:
    1. 保存分析结果时同时保存 `daily_push_priority_reduced_mode`（当前 `reduced_mode_active` 值）
    2. 读取缓存时比较 `daily_push_priority_reduced_mode` 和当前 `reduced_mode_active`，不一致则缓存失效
*   **涉及文件**: `core/services/active_care/priority_analyzer.py`、`core/services/active_care/proactive_checker.py`

### 10.101 Active Care 用户已起床但仍发送"还没起来"消息 (2026-05-12)

*   **问题描述**: 用户早上7点多起床并说了"早"，但 Active Care 在10点仍发送"18岁第一天就想睡到下午？赶紧给我滚起来"，认为用户还在睡觉
*   **复现步骤**:
    1. 用户昨晚说了晚安，系统进入 goodnight reduced mode
    2. 用户早上7点多起床并说了"早"
    3. Active Care 检测到 goodmorning 信号，调用 `_exit_goodnight_mode`
    4. `_exit_goodnight_mode` 先执行 `_sync_goodnight_sleep_to_daily_record`，其中 `SleepStateManager.sync_wakeup_time` 卡住
    5. 150s 超时后，`save_proactive_state(goodnight_clear)` **从未执行**
    6. `reduced_mode_active` 仍为 True，`last_goodmorning_ts` 从未设置
    7. 系统一直认为用户在睡觉，后续 Active Care 发送"还没起来"的消息
*   **预期行为**: 用户起床后，系统应立即退出晚安模式
*   **实际行为**: 因为 `_sync_goodnight_sleep_to_daily_record` 卡住，状态从未更新，系统一直认为用户在睡觉
*   **根因**: `_exit_goodnight_mode` 的执行顺序错误——先 sync Daily Record（可能卡住），再 save_state（清除晚安模式）。如果 sync 卡住，state 永远不更新
*   **修复方案**: 调整执行顺序——先 `save_proactive_state(goodnight_clear)`（清除晚安模式），再 `_sync_goodnight_sleep_to_daily_record`。这样即使 sync 卡住，晚安模式也已经被正确清除
*   **涉及文件**: `core/services/active_care/proactive_checker.py`

### 10.100 Active Care wakeup时间不断更新 + 150s超时仍发生 (2026-05-12)

*   **问题描述**: Active Care 每轮检查都重新执行 `_exit_goodnight_mode`，导致 wakeup 时间不断更新（08:00→08:11），同时 150s 超时仍发生
*   **复现步骤**:
    1. 用户说了"早"，系统检测到 goodmorning 信号
    2. `_try_exit_goodnight_on_awake_signals` 触发 `_exit_goodnight_mode`
    3. `_exit_goodnight_mode` 同步 Daily Record 和 SleepStateManager
    4. 下一轮检查时，`state_data` 中 `reduced_mode_active` 可能还没更新，条件再次满足
    5. 再次触发 `_exit_goodnight_mode`，wakeup 时间被更新
*   **预期行为**: 退出晚安模式后，后续检查不应再重复退出
*   **实际行为**: 每轮都重新退出，wakeup 时间不断更新，且卡在 SleepStateManager sync 上导致 150s 超时
*   **根因**: 1) `_try_exit_goodnight_on_awake_signals` 没有检查 `last_goodmorning_ts`，即使已经退出过也会重复触发；2) `SleepStateManager.sync_wakeup_time` 没有超时保护
*   **修复方案**:
    1. `_try_exit_goodnight_on_awake_signals` 开头添加 `last_goodmorning_ts` 检查，如果已经退出过就跳过
    2. `SleepStateManager.sync_sleep_time/sync_wakeup_time` 添加 `asyncio.wait_for` 5s 超时保护
    3. 给 `_exit_goodnight_mode` 和 `_sync_goodnight_sleep_to_daily_record` 内部添加计时日志
*   **涉及文件**: `core/services/active_care/proactive_checker.py`

### 10.98 Active Care LLM 编号列表泄漏到输出消息 (2026-05-11)

*   **问题描述**: Active Care 发送的消息 "3. 问清楚到底发生了什么" 包含编号前缀，是 LLM 模仿 prompt 中的编号格式泄漏到输出
*   **复现步骤**:
    1. Active Care 触发消息生成
    2. LLM 输出包含编号前缀的文本（如 "3. 问清楚到底发生了什么"）
    3. postprocessor 的 LeakDetector 未检测到编号列表泄漏
    4. 消息直接发送给用户
*   **预期行为**: 消息应为自然对话文本，不包含编号前缀
*   **实际行为**: 消息包含 "3. " 编号前缀，看起来像推理产物
*   **根因**: 1) prompt 中使用编号格式（1. 2. 3.）组织指令，LLM 模仿了这种格式；2) LeakDetector 不识别编号列表泄漏；3) strip_reasoning_segments 不清理编号前缀
*   **修复方案**:
    1. LeakDetector.looks_like_prompt_or_reasoning_dump 添加 `re.match(r"^\d+[.、．)\s]", raw)` 检测
    2. strip_reasoning_segments 添加 `re.sub(r"^\d+[.、．)\s]+\s*", "", cleaned, flags=re.MULTILINE)` 清理编号前缀
*   **涉及文件**: `core/services/active_care/postprocessor.py`

### 10.97 Active Care probable_sleep_probe_gap 阻塞10482s导致主动消息无法发送 (2026-05-09)

*   **问题描述**: Active Care 在 `probable_sleep` 模式下，探针间隔策略 `_resolve_probable_sleep_probe_policy` 计算出的 wait_seconds 高达 10482s（约3小时），导致系统长时间不发送主动消息
*   **复现步骤**:
    1. 系统检测到用户可能入睡，进入 `probable_sleep` reduced_mode
    2. 之前有过一次 goodnight probe（`last_goodnight_probe_ts > 0`）
    3. `_resolve_probable_sleep_probe_policy` 计算 `probe_gap = max(goodnight_low_disturb_gap_seconds=10800, PROBABLE_SLEEP_PROBE_GAP_SECONDS=7200) = 10800`
    4. 距离上次 probe 仅过了 318s，wait_seconds = 10800 - 318 = 10482s
    5. 系统设置下次检查在 10482s 后，约3小时内不会发送任何消息
*   **预期行为**: probable_sleep 模式下探针间隔应合理（30分钟-1小时），不应长达3小时
*   **实际行为**: probe_gap 取了 `max(10800, 7200) = 10800`，导致等待时间过长
*   **根因**: 1) `PROBABLE_SLEEP_PROBE_GAP_SECONDS=7200`（2小时）太长；2) `max()` 逻辑错误，应取 `min` 让更短的间隔生效；3) 没有上限保护
*   **修复方案**:
    1. `PROBABLE_SLEEP_PROBE_GAP_SECONDS` 从 7200 降到 1800（30分钟）
    2. `max()` 改为 `min()`，让 PROBABLE_SLEEP_PROBE_GAP_SECONDS 优先
    3. 添加 `max_wait_seconds = 3600` 上限保护
*   **涉及文件**: `core/services/active_care/constants.py`、`core/services/active_care/sleep_policy.py`

### 10.96 Active Care perform_check 持续超时(90s)导致主动消息无法发送 (2026-05-09)

*   **问题描述**: Active Care 每轮 `perform_check` 都在 90 秒时被 `CancelledError` 中断，导致主动关怀消息永远无法发送
*   **复现步骤**:
    1. Active Care 主循环正常运行
    2. 每轮 `perform_check` 进入决策流程后，约 90 秒后被外层 `asyncio.wait_for` 超时取消
    3. 日志显示 "perform_check 被 CancelledError 中断" 和 "perform_check 超时(90s)"
    4. 下一轮重复同样的问题，形成死循环
*   **预期行为**: `perform_check` 应在超时前完成决策和消息发送
*   **实际行为**: 决策流程中的 3 个串行 LLM 调用（`analyze_daily_push_priority` 20s + `decide_proactive_content` 25s + `trigger_message`→`llm.chat` 55s）最坏合计 100s，远超外层 90s 超时
*   **根因**: 外层超时(90s) < 内层 LLM 调用超时总和(100s+)，导致决策流程永远无法在超时前完成
*   **修复方案**:
    1. 外层超时从 90s 增加到 150s
    2. `decide_proactive_content` 超时从 25s 降到 20s
    3. `llm.chat` 主模型超时从 55s 降到 45s，fallback 从 45s 降到 35s
    4. 在决策流程各阶段添加计时日志，方便后续定位瓶颈
*   **涉及文件**: `core/services/active_care/service.py`、`core/services/active_care/proactive_checker.py`、`core/services/active_care/executor.py`

### 10.93 Active Care 白天(10-18点) reduced_mode 不自动退出导致整天不发主动消息 (2026-05-08)

*   **问题描述**: 用户深夜聊天后系统进入 probable_sleep 模式，第二天白天系统仍然不发任何主动消息，长达2小时以上沉默
*   **复现步骤**:
    1. 用户晚上聊天后没说晚安，凌晨2小时无响应
    2. 系统进入 probable_sleep 模式
    3. 第二天白天用户正常在线，但系统不发任何主动消息
*   **预期行为**: 白天(10-18点)系统应自动退出 reduced_mode，恢复正常主动消息频率
*   **实际行为**: reduced_mode 一直卡着，所有覆盖机制被阻止，整天零消息
*   **根因**（3个问题叠加）:
    1. `proactive_checker.py`: probable_sleep/sleep_hint 退出只依赖"早安"/"醒了"等关键词或14小时超时，白天正常聊天不触发退出
    2. `proactive_checker.py`: goodnight 模式白天也不退出
    3. `decision_executor.py`: `_is_override_allowed` 对 goodnight 白天也完全阻止覆盖
*   **修复方案**:
    1. probable_sleep/sleep_hint 在白天(10-18点)无条件自动退出
    2. goodnight 在白天且有用户信号时自动退出
    3. goodnight 白天允许长沉默覆盖（与 probable_sleep 同等待遇）

### 10.92 Active Care 长沉默阈值过低导致忽略用户已知状态 (2026-05-08)

*   **问题描述**: 用户已告知"9点睡6点起"，但15分钟后Active Care主动消息仍问"起来没"
*   **复现步骤**:
    1. 用户与Agent对话，告知"我9点睡的6点起的"
    2. Agent正常回复，确认用户已起床
    3. 约15分钟后，Active Care系统触发主动消息
    4. 主动消息内容为"笨蛋，起来没"，与用户已告知的起床时间矛盾
*   **预期行为**: Agent应记住用户已告知的起床时间，不再追问"起来没"
*   **实际行为**: Agent假装不知道用户已起床，重新询问
*   **根因分析**:
    1. `LONG_SILENCE_THRESHOLD_SECONDS` 原为600s（10分钟），15分钟沉默触发"长沉默"模式
    2. 长沉默模式下，`_build_proactive_trigger_input` 指令为"不要复读或追问用户最后一条消息"
    3. 该指令过于激进，LLM理解为"忽略用户最近说的话"，导致对已知事实假装不知道
    4. 虽然system prompt中包含最近聊天记录，但user message中的指令覆盖了system prompt的上下文
*   **修复方案**:
    1. 将 `LONG_SILENCE_THRESHOLD_SECONDS` 从600s提高到1800s（30分钟），10-30分钟内保持延续模式
    2. 将proactive trigger指令从"不要复读或追问用户最后一条消息"改为"不要复读用户最后一条消息，但用户已告知的事实必须尊重"
*   **涉及文件**: `core/services/active_care/executor.py`, `core/services/active_care/constants.py`

### 10.89 Active Care 无法感知尚未落盘的用户消息，误判用户入睡 (2026-05-08)

*   **问题描述**: 用户发消息后，Active Care 仍然认为用户在睡觉（probable_sleep 模式），不处理用户消息，不发主动关怀
*   **复现步骤**:
    1. 用户长时间未发消息（如隔夜），系统进入 probable_sleep 模式
    2. 用户早上发消息（如"早安"或"哎，昨天真的是"）
    3. WebSocket handler 收到消息，调用 `update_recent_user_message` 更新缓存
    4. 但消息要等 LLM 生成完回复后才保存到记忆管理器历史
    5. Active Care 的 `_process_user_response` 从 `get_latest_history()` 读取，看到最后一条用户消息是旧的（52941s前），超过300s阈值，跳过处理
    6. `_reset_interaction_state` 不被调用，probable_sleep 模式不清除
    7. `get_user_signal_and_intent` 返回旧的 `inferred_ts`，`_try_infer_probable_sleep` 错误推断用户长时间沉默
*   **预期行为**: 用户发消息后，Active Care 应立即感知到，清除 probable_sleep 模式，处理用户意图
*   **实际行为**: Active Care 看不到新消息，继续认为用户在睡觉，日志显示"跳过旧消息处理"和"推断可能已入睡"
*   **根因**: `_process_user_response` 和 `get_user_signal_and_intent` 只从记忆管理器历史读取，不检查 `_recent_user_message_cache` 缓存。而 executor 的 `_get_history_with_cache` 已经有缓存补全逻辑，但这两个方法没有
*   **修复方案**: 在 `_process_user_response` 和 `get_user_signal_and_intent` 中新增缓存检查逻辑，当缓存消息比历史消息更新时使用缓存消息

### 10.87 Active Care 探针在 probable_sleep 模式下完全不工作 (2026-05-07)

*   **问题描述**: 用户深夜聊天后未说晚安，系统进入 probable_sleep 模式，但整晚不发任何探针消息来确认用户是否真的睡了
*   **复现步骤**:
    1. 用户晚上聊天后没说晚安，凌晨2小时无响应
    2. 系统进入 probable_sleep 模式
    3. 整晚没有任何消息发出
    4. 用户第二天回来，发现系统完全沉默
*   **预期行为**: probable_sleep 进入后，应发送首次探针消息确认用户是否真的睡了，后续每2-3小时可再探一次
*   **实际行为**: 整晚零消息，探针机制完全失效
*   **根因**（3个Bug叠加）:
    1. `proactive_checker.py:550`: `last_goodnight_probe_ts` 只在 `sleep_session_active=True`（显式晚安）时更新，probable_sleep 下永远不更新，导致探针间隔控制失效
    2. `decision_executor.py:356`: `_is_override_allowed()` 对 `reduced_mode_active` 一刀切返回 False，所有覆盖机制（长沉默覆盖、force_send）在 probable_sleep 下全部失效
    3. `decision_executor.py:301`: probable_sleep 下 `do_nothing` 权重x3，首次探针时选中概率约43%，大部分时候选不中
*   **修复方案**:
    1. probable_sleep/sleep_hint 下也更新 `last_goodnight_probe_ts`
    2. `_is_override_allowed()` 对 probable_sleep/sleep_hint 放宽：允许长沉默覆盖，但阻止 non_response 压力覆盖
    3. 首次探针排除 `do_nothing`，后续探针 `do_nothing` 权重从3降到1

### 10.86 睡眠/起床时间无法自动识别记录 + 重启后遗忘对话上下文 (2026-05-07)

*   **问题描述**: 用户长时间不回复（明显在睡觉），系统虽然能推断 probable_sleep，但退出时不记录作息时间到 daily_record；程序重启后 AI 表现得像遗忘了之前在聊什么
*   **复现步骤**:
    1. 用户深夜聊天后未说晚安直接去睡
    2. 系统进入 probable_sleep 模式
    3. 用户第二天回来发消息，probable_sleep 退出
    4. 检查 daily_record.json，发现没有睡眠/起床时间记录
    5. 重启主程序后，AI 表现得像忘记了之前的对话内容
*   **预期行为**: 系统应自动推断用户在睡觉，退出 probable_sleep 时自动记录睡眠/起床时间；重启后 AI 应理解之前的对话上下文
*   **实际行为**: Active Care 和 Daily Record 之间只有单向桥接（Daily → Active Care），probable_sleep 退出时不同步作息时间；重启后对话间隔提示不够智能，AI 不知道用户在睡觉
*   **根因**:
    1. Active Care → Daily Record 桥接缺失：`_exit_goodnight_mode()` 和 `_reset_interaction_state()` 只清除状态，不调用 `record_sleep`/`record_wakeup`
    2. 程序重启时不推断睡眠：`_startup_check()` 只设置延迟检查，不根据最后交互时间推断用户是否在睡觉
    3. `build_conversation_gap_context()` 只显示"有约X小时的空白"，不解释原因（如"用户在睡觉"）
*   **修复方案**:
    1. `service.py`: 新增 `_sync_inferred_sleep_to_daily_record()` 和 `_startup_infer_sleep_from_gap()`，退出 probable_sleep 时自动同步作息时间到 daily_record 和 SleepState
    2. `proactive_checker.py`: 新增 `_sync_goodnight_sleep_to_daily_record()` 和 `_sync_probable_sleep_to_daily_record()`，退出晚安/推断睡眠时同步作息时间
    3. `components.py:build_conversation_gap_context()`: 增强间隔提示，根据时段和时长智能判断是否为睡眠间隔，添加记忆连续性提示

### 10.85 Active Care conversation_stalled 覆盖不尊重 non_response_count，用户说"没回就是睡了"后仍持续发消息 (2026-05-07)

*   **问题描述**: 用户说"没回你就是睡了"后，Active Care 在4小时内连续发送13+条消息，间隔仅10-22分钟。延时惩罚和 Bandit 算法均未生效
*   **复现步骤**:
    1. 用户在18:54说"没回你就是睡了"
    2. Bot回复"嗯，睡吧""晚安"等
    3. 用户不再回复
    4. Active Care 检测到 conversation_stalled，每10-22分钟发一条消息，持续到22:55
    5. 00:41用户回复"你怎么还发这么多"
*   **预期行为**: 用户说"没回就是睡了"后，系统应进入 probable_sleep/sleep_hint 模式，大幅降低发送频率；连续不回复时延时惩罚应生效，间隔应从20分钟逐步增加到60分钟
*   **实际行为**: 消息间隔始终在10-22分钟，延时惩罚未生效，Bandit算法被 conversation_stalled 覆盖绕过
*   **根因**:
    1. `conversation_stalled` 覆盖不尊重 `non_response_count`：无论用户多少次不回复，都强制覆盖动作为 `curious_question`，完全绕过 Bandit 算法
    2. `bypass_interaction_guard` 在 `conversation_stalled` 时不考虑 `non_response_count`，绕过用户安静期保护
    3. `probable_sleep` 只在0-6点和6-10点触发，18点用户说"没回就是睡了"无法触发
    4. 缺少"睡眠暗示"意图检测：用户说"没回就是睡了"是条件性睡眠暗示，不是直接晚安
    5. `infer_preferred_language` 返回 "auto" 时无语言约束，LLM 可能输出英文
*   **修复方案**:
    1. `decision_executor.py:apply_action_overrides()`: 当 `non_response_count >= 2` 且 `incomplete_type == "conversation_stalled"` 时，抑制覆盖，让 Bandit 算法正常选择
    2. `proactive_checker.py:_execute_send_or_skip()`: 当 `non_response_count >= 2` 时，提高 `bypass_interaction_guard` 的安静期阈值
    3. `constants.py`: 新增 `SleepHintKeywords`（睡眠暗示关键词）、`SLEEP_HINT_REASON`、晚间 probable_sleep 常量
    4. `intent_detector.py`: 新增 `contains_sleep_hint()` 方法
    5. `proactive_checker.py:_try_infer_probable_sleep()`: 新增睡眠暗示处理（不限时段）和晚间18-24点支持
    6. `postprocessor.py:infer_preferred_language()`: 默认返回 "zh" 而非 "auto"
    7. `prompt_builder.py:_build_language_guard()`: "auto" 也默认使用中文语言守卫

### 10.82 Active Care do_nothing 直接返回跳过 force_send + _is_override_allowed non_response 完全阻止覆盖 (2026-05-05)

*   **问题描述**: 用户未说晚安睡觉后，Active Care 整晚零消息。深入追踪发现两个叠加 bug：(1) bandit 选中 do_nothing 后代码直接 return，完全跳过 LLM 决策和 force_send 兜底；(2) `_is_override_allowed` 在 non_response_count>0 时返回 False，导致 apply_action_overrides 和 should_force_send 的所有覆盖都被阻止
*   **复现步骤**:
    1. 用户正常聊天后睡觉，不说晚安
    2. 凌晨1点，Active Care 检查：bandit 可能选中 do_nothing
    3. apply_action_overrides 尝试覆盖 do_nothing → _is_override_allowed(non_response=True) 返回 False → 覆盖失败
    4. chosen_action 保持 do_nothing → 代码直接 return → 跳过 LLM 和 force_send
    5. 即使 bandit 没选中 do_nothing，LLM 决策 should_send=false 后，force_send 也因 _is_override_allowed(non_response=True) 返回 False 而无法覆盖
    6. 整晚零消息
*   **预期行为**: do_nothing 时应先检查 force_send；non_response 不应完全阻止覆盖，只是需要更长的沉默时间
*   **实际行为**: do_nothing 直接返回；non_response>0 时所有覆盖被完全阻止
*   **根因**:
    1. **do_nothing 直接返回**: `_build_priority_and_select_action` 中 `if chosen_action == "do_nothing": return` 跳过了 `decide_proactive_content` 和 `_apply_silence_overrides`
    2. **_is_override_allowed 过度阻止**: `not has_non_response_pressure` 条件使得一旦用户不回复一条消息，所有覆盖机制（包括 no_send_timeout_fallback）都被永久阻止
*   **修复方案**:
    1. `proactive_checker.py:_build_priority_and_select_action()`: do_nothing 时先调用 `should_force_send` 检查，如果 force_send=True 则继续 LLM 决策
    2. `decision_executor.py:_is_override_allowed()`: 移除 `not has_non_response_pressure` 条件，non_response 的节流由 `should_force_send` 中的 `min_silence_for_force` 阈值控制
*   **关键文件**: `core/services/active_care/proactive_checker.py`, `decision_executor.py`

### 10.81 Active Care 用户未说晚安时深夜长时间不发消息，推断睡眠逻辑缺失 (2026-05-05)

*   **问题描述**: 用户睡觉前没有说晚安，Active Care 在整个睡眠期间（8h+）没有发送任何消息。系统缺少"无晚安自动推断睡眠"的逻辑，导致深夜长时间无响应时 LLM 决策被时间约束压制（should_send=false），而强制发送兜底因沉默超时（>6h）也失效，形成死循环
*   **复现步骤**:
    1. 用户在晚上正常聊天后直接睡觉，不说晚安
    2. 系统未检测到晚安意图，不进入睡眠模式
    3. 凌晨/早上，LLM 决策因时间约束（"凌晨长时间无响应→should_send=false"）选择不发消息
    4. 强制发送兜底（long_silence_fallback）因用户信号超过6h而失效
    5. 整个睡眠期间无任何消息发出
*   **预期行为**: 即使用户未说晚安，系统也应根据深夜长时间无响应自动推断用户可能已入睡，进入低打扰模式并偶尔发送轻量陪伴消息
*   **实际行为**: 整个睡眠期间（8h+）零消息
*   **根因**:
    1. **缺少自动推断睡眠机制**: `_process_sleep_session_state` 只处理显式晚安/早安意图，不处理"深夜长时间无响应"的隐式推断
    2. **LLM 时间约束过度压制**: `decision.py` 中凌晨/早上长时间无响应约束建议 `should_send=false`，但没有区分"已推断睡眠"和"未推断"的情况
    3. **强制发送兜底失效**: `should_force_send` 的 `has_recent_signal_for_long_silence` 要求用户信号在6h内，睡眠超过6h后失效
*   **修复方案**:
    1. `proactive_checker.py`: 新增 `_try_infer_probable_sleep` 方法，当用户深夜（0-6点）2h+或早上（6-10点）3h+无响应且无晚安时，自动进入 `probable_sleep` reduced mode
    2. `sleep_policy.py`: 新增 `_resolve_probable_sleep_probe_policy`，允许每2-3小时发送一条轻量探针
    3. `decision_executor.py`: `build_available_actions` 支持 `probable_sleep` 模式，限制动作为轻量陪伴
    4. `constants.py`: 新增 `PROBABLE_SLEEP_*` 常量和 `build_sleep_status_description` 中的 probable_sleep 描述
    5. `active_care_prompts.py`: 新增 `PROBABLE_SLEEP_REDUCED_MODE_INSTRUCTION` prompt
    6. `decision.py`: 时间约束在 `probable_sleep` 模式下不再建议 `should_send=false`
    7. `service.py`: 用户发消息时自动退出 `probable_sleep` 模式
*   **关键文件**: `core/services/active_care/proactive_checker.py`, `sleep_policy.py`, `decision_executor.py`, `constants.py`, `decision.py`, `service.py`

### 10.80 Active Care 用户未回复时延时惩罚被 LLM 小 next_check_seconds 绕过 (2026-05-04)

*   **问题描述**: 用户从 11:51 到 19:54 一直未回复，但 Active Care 仍每15-20分钟发一条消息，non_response 延时惩罚未生效
*   **复现步骤**:
    1. 用户收到消息后不回
    2. 观察 Active Care 日志，消息间隔未随 non_response 累积而增大
*   **预期行为**: non_response_count 每增加1，下次检查间隔应乘以 1.4（上限6.0），从600s逐步增大到3600s
*   **实际行为**: 间隔保持在15-20分钟，未随 non_response 增大
*   **根因**: `_execute_send_or_skip()` 发送成功后计算 `send_wait_seconds = max(next_check_seconds, required_gap)`，其中 `next_check_seconds` 来自 LLM 决策（可能只有300s），`required_gap = min_gap * min(non_response+1, 6)`。但 `next_check_seconds` 可能大于 `required_gap`，导致惩罚被 LLM 的小值覆盖
*   **修复方案**: `proactive_checker.py:_execute_send_or_skip()`: 强制取 `max(next_check_seconds, required_gap, min_gap_seconds * non_response_backoff)`，确保惩罚始终生效
*   **关键文件**: `core/services/active_care/proactive_checker.py`

### 10.79 Active Care 助手说晚安后未进入低打扰模式，导致高频打扰用户睡眠 (2026-05-04)

*   **问题描述**: 用户收到助手"晚安"消息后，Active Care 在接下来8小时内持续发送了20+条消息（包括"起床了没""太阳晒屁股了"等），完全未进入低打扰模式
*   **复现步骤**:
    1. 聊天系统发送"晚安"消息给用户
    2. 用户不回复（睡觉中）
    3. 观察 Active Care 在 11:51 到 19:54 之间持续发消息
*   **预期行为**: 助手说晚安后，应自动进入睡眠/低打扰模式，至少2-3小时内不再发送非紧急消息
*   **实际行为**: 消息频率约每15-20分钟一条，完全无睡眠保护
*   **根因**:
    1. **助手晚安不触发 reduced_mode**: `_try_enter_goodnight_on_intent()` 要求 `active_care_enable_auto_goodnight_reduced_mode` 配置为 `True`（默认`False`），助手说晚安时虽然检测到 `inferred_goodnight=True`，但不保存 `last_goodnight_ts` 和 `reduced_mode_active`
    2. **due_reminder 低打扰模式返回 False**: `_handle_due_reminder()` 在低打扰模式下返回 `False`，导致决策流程继续执行，后续逻辑可能发送其他类型消息
    3. **sleep_session_active 依赖 last_goodnight_ts**: 由于 `last_goodnight_ts` 未保存，`sleep_session_active` 为 False，`probe_policy` 和 `build_available_actions` 的睡眠限制全部失效
*   **修复方案**:
    1. `proactive_checker.py:_try_enter_goodnight_on_intent()`: 新增 `is_assistant_goodnight` 参数，助手说晚安时强制进入睡眠会话，不受配置限制
    2. `proactive_checker.py:_handle_due_reminder()`: 低打扰模式下返回 `True` 终止决策流程
    3. `proactive_checker.py:_execute_decision_flow()`: 传递 `is_assistant_goodnight=True`
*   **关键文件**: `core/services/active_care/proactive_checker.py`

### 10.78 Active Care 间隔保护多层失效：overlap_guard过短 + 无发送前检查 + finally不同步 (2026-05-04)

*   **问题描述**: 用户未回复时，主动关怀消息仅隔5分钟就再次发送（06:23:18 → 06:28:25），远低于 min_gap_seconds=600s
*   **复现步骤**:
    1. 主动关怀发送消息，用户不回复
    2. 约11分钟后发送第二条（正常）
    3. 仅5分钟后又发送第三条（异常，应至少10分钟）
*   **预期行为**: 任何两次主动消息之间至少间隔 min_gap_seconds（600s），用户不回复时还应叠加延时惩罚
*   **实际行为**: 第二条到第三条仅5分钟，间隔保护完全失效
*   **根因**:
    1. **overlap_guard 对 reminder/proactive_follow_up 类型只有300秒**：`_get_overlap_guard_seconds()` 对这两种类型返回 `max(min_gap//2, 300)=300s`，而LLM返回的intent可能是这些类型，导致5分钟就能通过overlap guard
    2. **`_execute_send_or_skip` 没有发送前间隔检查**：`required_gap` 只用来计算下次检查时间，不阻止当前发送。即使 `required_gap=1200s`，只要 overlap guard 通过（300s），消息就会发出
    3. **`_handle_due_reminder` 完全绕过间隔检查**：到期提醒路径不检查 `last_sent_ts`/`last_attempt_ts`，仅靠 overlap guard
    4. **`finally` 块不同步**：`perform_check` 的 `finally` 块只更新 `next_decision_ts` 不更新 `_next_llm_decision_ts`，可能导致两者不同步
*   **修复方案**:
    1. `executor.py:_get_overlap_guard_seconds()`: 所有类型统一使用 `min_gap_seconds`，不再对 reminder/follow_up 减半
    2. `proactive_checker.py:_execute_send_or_skip()`: 发送前检查 `now - last_activity_ts >= required_gap`，不满足则跳过并设置下次检查时间
    3. `proactive_checker.py:_handle_due_reminder()`: 发送前检查 `now - last_activity_ts >= min_gap_seconds`
    4. `proactive_checker.py:perform_check() finally`: 同时更新 `_next_llm_decision_ts` 和 `next_decision_ts`

### 10.77 Active Care 不感知普通聊天回复，导致延时惩罚被绕过 (2026-05-04)

*   **问题描述**: 用户收到聊天系统的普通回复后未回复，6分钟后又收到主动关怀消息。延时惩罚（backoff + required_gap + overlap_guard）完全失效
*   **复现步骤**:
    1. 用户发消息，聊天系统回复（普通回复，非主动关怀）
    2. 用户不回复
    3. 约5-6分钟后，主动关怀系统又发了一条消息
*   **预期行为**: 任何bot消息发送后，主动关怀系统应至少等待 `min_gap_seconds`（默认600s/10分钟）再发下一条，用户不回复时还应叠加延时惩罚
*   **实际行为**: 普通聊天回复后仅5-6分钟就又发了主动消息，延时惩罚完全无效
*   **根因**:
    1. **主动关怀系统不感知普通聊天回复**：当聊天系统通过 `stream_orchestrator` 发送回复时，主动关怀系统的三个关键状态均未更新：
       - `_last_trigger_ts`（重叠保护时间戳）→ overlap guard 形同虚设
       - `next_decision_ts`（下次决策时间）→ checker 可在很短时间内就触发
       - `last_sent_ts`（最后发送时间）→ 决策上下文认为"很久没发消息了"
    2. **延迟任务回调绕过间隔保护**：`_on_delayed_task_trigger()` 直接调用 `executor.trigger_message()`，仅依赖 overlap guard，未检查 `next_decision_ts` 和 `_last_trigger_ts`
*   **修复方案**:
    1. `service.py`: 新增 `on_assistant_message_sent(timestamp)` 方法，更新 `_last_trigger_ts`、`next_decision_ts`、`last_sent_ts`
    2. `stream_orchestrator.py`: 流式对话完成后调用 `on_assistant_message_sent()`
    3. `service.py:_on_delayed_task_trigger()`: 增加 `next_decision_ts` 和 `_last_trigger_ts` 间隔检查，不满足条件时重新调度而非立即发送
*   **关键文件**: `core/services/active_care/service.py`, `core/services/aveline/stream_orchestrator.py`

### 10.76 Active Care 消息发送过于频繁：backoff 被 `min()` 覆盖 + overlap_guard 间隔太短 (2026-05-03)

*   **问题描述**: 用户没回消息，Active Care 仍每隔几分钟发一条消息，完全没有延时惩罚效果。明明设了 backoff（1.4^n，上限6.0），Checker 也定了 20 分钟的 `next_decision_ts`，但消息仍然频繁发送
*   **复现步骤**: 用户不回消息，等待 3-5 分钟，观察 Active Care 日志显示又触发了一次发送，周而复始
*   **预期行为**: 用户不回消息时，发送间隔应逐步拉长（从 600s → 840s → 1200s... 最高 3600s）
*   **实际行为**: 消息每隔几分钟就发一次，backoff 完全无效
*   **根因**:
    1. **`min()` 导致 backoff 被覆盖**：[service.py:664-666](file:///d:/AI/xiaoyou-core/core/services/active_care/service.py#L664-L666) `_calculate_sleep_interval()` 用 `min(dynamic_interval, llm_wait)` 计算休眠时间，取两者中较短的那个。当 `dynamic_interval` 为 ~420s 而 Checker 的 `next_decision_ts` 设定的间隔为 1200s 时，`min(420, 1200) = 420s`，Checker 的冷却期被完全无视。修复：改为 `max()`，让较长的冷却期生效
    2. **overlap_guard 间隔太短**：[executor.py:953-955](file:///d:/AI/xiaoyou-core/core/services/active_care/executor.py#L953-L955) `_get_overlap_guard_seconds()` 对 reminder/follow_up 类型只给 10 秒保护，其他类型最多 180 秒（`max(30, min(180, 600*0.3))`）。作为防止并发重触的安全网，这个间隔远不够。修复：reminder 类改为 `max(min_gap_seconds//2, 300)`（至少 300s），其他类改为 `min_gap_seconds`（600s）
*   **修复方案**:
    1. `service.py:_calculate_sleep_interval()`: `min` → `max`，确保 `next_decision_ts` 作为最小休眠间隔
    2. `executor.py:_get_overlap_guard_seconds()`: 提升所有类型的 overlap guard 最低间隔
*   **关键文件**: `core/services/active_care/service.py:666`, `core/services/active_care/executor.py:947-956`

### 10.75 `continuation_anchor` 优先选择 proactive 消息，忽略更新的 normal chat 消息 (2026-05-03)

*   **问题描述**: Active Care 的 continuation anchor 使用 proactive 消息而非更新的 normal chat 消息，导致 LLM 看到错误的"上一句"：08:46 normal chat 说"你去睡/睡醒再说"，08:51 Active Care 的 continuation anchor 却显示"喂，再装死我真的不管了"（08:45 proactive），LLM 继续催起床
*   **复现步骤**: 
    1. 08:45 proactive/active care 发 "喂，再装死我真的不管了"
    2. 08:46 用户回复 "来了来了"，normal chat 回复 "你去睡" / "睡醒再说"
    3. 08:51 Active Care 触发，continuation anchor = proactive 消息 → 生成 "还活着没？太阳晒屁股了——起床"
*   **预期行为**: continuation anchor 应为最近的 Assistant 消息（不管是 proactive 还是 normal chat），即 "睡醒再说"，并触发 GOODNIGHT_GUARD
*   **实际行为**: `last_proactive_assistant_message or last_assistant_message` 优先取 proactive，完全忽略了更新的 normal chat
*   **根因**: [executor.py:541-543](file:///d:/AI/xiaoyou-core/core/services/active_care/executor.py#L541-L543) `continuation_anchor` 的 `or` 链把 proactive 放在前面
*   **修复方案**: 改为 `last_assistant_message or last_proactive_assistant_message`，让最近的 Assistant 消息（无论类型）优先
*   **关键文件**: `core/services/active_care/executor.py:541-543`

### 10.74 `elapsed_seconds` 被 Assistant 消息时间覆盖，导致 Active Care 错误判定"长静默" (2026-05-03)

*   **问题描述**: Active Care 生成的主动消息与最近 Assistant 消息矛盾：08:05 说"去睡觉"，08:20 说"太阳晒到床上了起来了"
*   **复现步骤**: Normal chat 中 Assistant 回复"去睡觉"，15分钟后 Active Care 触发，生成叫起床的消息
*   **预期行为**: Assistant 刚说了"去睡觉"，不应在短时间内又叫人起床，应当延续对话上下文
*   **实际行为**: Active Care 判定为长静默，忽略最近对话，基于时间（08:20早晨）生成新话题
*   **根因**: `_build_trigger_context` 中 `elapsed_seconds` 被 Assistant 最近消息时间覆盖：
    ```python
    elapsed_seconds = user_elapsed_seconds  # 初始为用户静默时间
    if assistant_elapsed < elapsed_seconds:
        elapsed_seconds = assistant_elapsed  # ← 被Assistant时间覆盖!
    ```
    Assistant 08:05 说"去睡觉"后 15 分钟（900秒）> `LONG_SILENCE_THRESHOLD_SECONDS=600秒` → `is_long_silence=True` → 使用了 `CONTEXT_GUARD_LONG_SILENCE`（"不要复读，基于当前时间/画像/日程开启新话题"）→ LLM 看到 08:20 早晨 → 生成起床消息
*   **修复方案**:
    1. 新增 `user_elapsed_seconds` 字段，保存未被覆盖的纯用户静默时间
    2. `_build_model_user_input_for_active_care` 和 `build_active_care_prompt` 中改用 `user_elapsed_seconds` 判断 `is_long_silence`
    3. `elapsed_seconds`（被 Assistant 覆盖后的值）保留原样用于其他需要综合考虑双方活动的场景
*   **关键文件**: `core/services/active_care/executor.py:1012-1022,1083,1202,1228`

### 10.71 Active Care 消息类型不匹配导致QQ端收不到主动消息 (2026-05-03)

*   **问题描述**: Active Care 生成的主动消息日志显示"消息已成功分发到前端"，但QQ端始终收不到消息
*   **复现步骤**: 用户离线时触发 Active Care，观察日志显示消息"已分发"，但QQ端从未收到该消息
*   **预期行为**: Active Care 消息应通过 WebSocket 送达 QQ Adapter，再发送到 NapCat/QQ
*   **实际行为**: 消息被 QQ Adapter 的 `_receive_from_xiaoyou()` 静默丢弃
*   **根因**: `AvelineService.dispatch_proactive_message()` 构建的 payload 使用 `"type": "proactive"`，但 QQ Adapter 只处理 `msg_type == "proactive_message"`，没有 `"proactive"` 类型的 handler，消息被静默丢弃。同时日志 `delivered=True` 实际上可能只是存入了离线队列，误导了调试
*   **修复方案**:
    1. 将 `dispatch_proactive_message()` 的 payload type 从 `"proactive"` 改为 `"proactive_message"`，与 QQ Adapter handler 匹配
    2. 在 payload 中添加 `"is_proactive": True` 标志
    3. 修复 QQ Adapter `proactive_message` handler 中 `message_type` 取值错误：从 `data.get("subtype")`（值为 `"active_care"`）改为 `data.get("message_type")`（值为 `"text"`/`"voice"`），否则语音类型判断永远不生效
    4. 新增 `WebSocketManager.is_user_online()` 方法，改进日志区分"实时送达"和"存入离线队列"
*   **关键文件**: `core/services/aveline/service.py`, `clients/bots/qq_adapter_session.py`, `core/interfaces/websocket/websocket_manager.py`, `core/services/active_care/executor.py`

### 10.62 Active Care 提示词泄露到QQ消息 + proactive_message缺少日志 (2026-04-30)

*   **问题描述**: Active Care 发送到QQ的消息内容是系统提示词片段（如"- 【核心指令】主动发起对话，但要自然。"），而非模型生成的实际消息。同时QQ Adapter没有显示"接收并处理主动关怀消息"的日志
*   **复现步骤**:
    1. Active Care 触发主动消息生成
    2. MiniMax-M2.5 返回包含提示词片段的 content
    3. LeakDetector 未检测到泄露（文本仅20字，低于80字阈值；关键词命中率不足）
    4. 提示词片段直接发送到 QQ
*   **预期行为**: 提示词泄露应被检测并拦截，QQ Adapter 应显示接收主动关怀消息的日志
*   **实际行为**: 提示词片段直接发送到用户，QQ Adapter 无相关日志
*   **根因**:
    1. **LeakDetector 阈值过高**：80字符阈值导致短文本泄露完全被跳过
    2. **LeakDetector 关键词缺失**：没有包含"核心指令"、"核心约束"、"主动发起模式"等明显的提示词标记
    3. **QQ Adapter proactive_message 处理缺少日志**：之前添加的 proactive_message 分支没有 INFO 级别的日志输出
*   **修复**:
    1. LeakDetector 添加 `strong_leak_markers` 列表，包含"【核心指令"、"【核心约束"、"【主动发起模式"等标记，命中任一即判定为泄露（无长度限制）
    2. 阈值从 80 降到 40
    3. hit_keywords 添加"主动发起对话"、"核心指令"、"核心约束"
    4. blocked_words 添加"核心指令"、"核心约束"、"主动发起"、"强制字数"
    5. QQ Adapter proactive_message 处理添加 INFO 级别日志

### 10.56 Active Care conversation_id 与主程序不一致导致消息保存到不同文件 (2026-04-30)

*   **问题描述**: Active Care 的消息保存到了 `private_10001_short.json`，而主程序聊天保存到 `private_10001__persona__aveline_qq_master_short.json`，导致两套历史记录完全分离
*   **复现步骤**:
    1. Active Care 触发主动消息生成
    2. `_resolve_target_conversation` 解析出 `target_conversation_id = private_10001__persona__aveline_qq_master`
    3. 但当 `requested_client_type == "qq"` 时，`_get_qq_user_id_from_connections()` 从 WebSocket 连接获取 `user_id = private_10001`
    4. `target_conversation_id` 被覆盖为 `private_10001`（丢失 persona 后缀）
    5. 消息保存到 `private_10001_short.json`
*   **预期行为**: Active Care 消息应保存到与主程序相同的 `private_10001__persona__aveline_qq_master_short.json`
*   **实际行为**: 消息保存到 `private_10001_short.json`，历史记录完全分离
*   **根因**: `_resolve_target_conversation` 中，当 QQ 路由时直接用 WebSocket 连接的 `user_id`（`private_10001`）替换了 `target_conversation_id`（`private_10001__persona__aveline_qq_master`），丢失了 persona 后缀。同时 `dispatch_proactive_message` 用带 persona 后缀的 conversation_id 查找 WebSocket 连接，但 QQ Adapter 注册时用的 `user_id` 不含 persona 后缀，导致找不到连接
*   **修复**:
    1. `_resolve_target_conversation`：当 `target_conversation_id` 含 `__persona__` 且 QQ `user_id` 匹配其 base 部分时，保留 persona 后缀
    2. `dispatch_proactive_message`：查找 WebSocket 连接时，如果带 persona 后缀的 user_id 找不到连接，回退到 base user_id
    3. QQ Adapter `proactive_message` 处理：匹配 `conversation_id` 时，支持 base session_id 匹配带 persona 后缀的 target_id

### 10.54 MiniMax-M2.5 reasoning_split 模式与 Active Care 消息未发到QQ (2026-04-30)

*   **问题描述**: 两个相关问题：(1) MiniMax-M2.5 总是只返回推理内容无实际消息，每次都 fallback 到 GLM-5；(2) Active Care 消息虽然日志显示"已成功分发到前端"，但实际未发送到 QQ
*   **复现步骤**:
    1. Active Care 触发主动消息生成
    2. MiniMax-M2.5 返回 reasoning_content 但 content 为空
    3. `_handle_reasoning_only_response` 检测到剥离后为空，fallback 到 GLM-5
    4. GLM-5 成功生成内容
    5. 日志显示"Active Care: 消息已成功分发到前端"
    6. 但 QQ 端未收到消息
*   **预期行为**: MiniMax-M2.5 应正常生成内容（推理+实际消息）；Active Care 消息应成功发送到 QQ
*   **实际行为**: MiniMax-M2.5 只返回推理；Active Care 消息未到达 QQ
*   **根因**:
    1. **MiniMax-M2.5 默认将推理混入 content 字段**：MiniMax 的 OpenAI 兼容 API 默认把推理内容（`<think...>` 标签）混入 `choices[0].message.content`，导致 content 字段全是推理文本。需要添加 `reasoning_split=True` 参数，让 API 将推理分离到 `reasoning_details` 字段，content 字段只返回实际消息
    2. **QQ Adapter 不处理 `proactive_message` 类型**：AvelineService 的 `dispatch_proactive_message()` 通过 WebSocket 广播 `type="proactive_message"` 的消息，但 QQ Adapter 的 `_receive_from_xiaoyou()` 只处理 `type="message"`，完全忽略了 `proactive_message` 类型的消息
*   **修复**:
    1. MiniMax 客户端 `_build_payload()` 添加 `reasoning_split=True` 参数
    2. OpenAI 客户端 `_parse_non_stream_response()` 增加 `reasoning_details` 字段解析，返回 `reasoning_only` 标志
    3. 流式解析器 `stream_parser.py` 增加 `reasoning_details` 处理
    4. executor 识别 `reasoning_only` 标志，直接走 fallback 路径
    5. QQ Adapter 添加 `msg_type == "proactive_message"` 处理分支

### 10.53 Active Care 推理模型只返回reasoning时消息丢失 (2026-04-29)

*   **问题描述**: Active Care 使用推理模型（如MiniMax-M2.5）生成内容时，模型只返回推理内容（reasoning_content）而无实际消息。fallback到GLM-5后虽然生成了内容，但消息未发到前端
*   **复现步骤**:
    1. Active Care 触发主动消息生成
    2. MiniMax-M2.5 只返回推理内容，无实际消息（content为空）
    3. `_handle_reasoning_only_response` 检测到并触发 fallback 到 GLM-5
    4. GLM-5 成功生成内容，但消息未发到前端
*   **预期行为**: fallback 模型生成内容后，消息应正常发送到前端
*   **实际行为**: GLM-5 生成了内容但消息未到达前端
*   **根因**: 多个问题叠加：
    1. **SiliconFlow `generate` 方法不处理 `reasoning_content`**：当MiniMax-M2.5等推理模型通过SiliconFlow代理时，`generate`方法只提取`content`字段，完全忽略`reasoning_content`，导致推理内容丢失
    2. **`_generate_active_care_response` 的返回值处理缺少 `elif raw.get("response")` 分支**：当云端模型返回`{"response": "...", "finish_reason": "..."}`格式（无`status`字段）时，`response`字段被忽略，`text`变量被设为空字符串
    3. **日志不足**：fallback成功后缺少详细日志，无法诊断消息在哪个环节被拦截
*   **修复**:
    1. SiliconFlow `generate` 和 `_vision_inference` 方法增加 `reasoning_content` 回退逻辑
    2. `_generate_active_care_response` 增加 `elif raw.get("response")` 分支
    3. `_handle_reasoning_only_response` 增加详细日志（fallback模型、生成内容预览、失败原因）
    4. `_dispatch_message` 和 `postprocess` 增加关键节点日志

### 10.52 Active Care 主循环静默停止工作 - 无日志无报错 (2026-04-29)

*   **问题描述**: Active Care 经常不工作，后端没有任何 active Care 日志，像是被锁堵塞了一样
*   **复现步骤**:
    1. 启动 Xiaoyou Core 后端，Active Care 正常运行一段时间
    2. 运行一段时间后，Active Care 突然停止产生任何日志
    3. 没有报错，没有异常，只是静默停止
*   **预期行为**: Active Care 主循环持续运行，定期产生调度日志
*   **实际行为**: 主循环完全停止，无任何日志输出，如同被锁堵塞
*   **根因**: 多个问题叠加导致：
    1. **`_proactive_loop` 任务死亡后无自动重启机制**：`_proactive_task` 只在 `initialize()` 时创建一次，如果因任何原因（CancelledError、未捕获异常等）退出，没有任何机制检测和重启它
    2. **`check_active_care` 手动触发无超时保护**：手动触发 `perform_check` 时没有超时，如果 `perform_check` 卡住，锁会被无限持有，主循环下一轮也会卡死在等锁
    3. **`_proactive_lock` 获取无超时**：`async with self._proactive_lock:` 没有获取超时，如果锁被其他地方持有，主循环会无限等待
    4. **无心跳/看门狗日志**：循环内部没有周期性的存活日志，一旦卡住很难从日志中诊断
    5. **`perform_check` 的 `except Exception` 可能吞掉 CancelledError**（Python 3.8 兼容性问题）
*   **修复**:
    1. 新增 `_watchdog_loop` 看门狗任务，每 120 秒检查主循环是否存活，自动重启已死亡的任务
    2. 新增 `_last_loop_iteration_ts` 心跳时间戳，看门狗据此检测循环是否卡死（>300s 警告，>600s 报错）
    3. 给 `check_active_care` 加 120 秒超时保护（锁获取 + perform_check 各 120s）
    4. 给 `_proactive_loop` 中的锁获取加 120 秒超时，超时后跳过本轮并记录锁状态
    5. 改用 `lock.acquire()/release()` 手动管理锁，确保 CancelledError 时也能正确释放
    6. 在 `perform_check` 中显式 `except asyncio.CancelledError: raise`，防止被 `except Exception` 吞掉
    7. 增强健康检查，包含 `proactive_task_alive`、`loop_stuck_seconds`、`lock_locked`、`loop_restart_count` 等诊断信息
*   **教训**: **异步任务必须有看门狗机制**。`asyncio.Task` 一旦因任何原因退出，如果没有外部监控，整个功能就会静默失效。关键循环应该有：1) 心跳时间戳 2) 看门狗自动重启 3) 锁获取超时 4) 充分的诊断日志

### 10.43 程序启动卡在 active_care_service 初始化不动，Ctrl+C 无法退出 (2026-04-28)

*   **问题描述**: 主程序启动时卡在 `初始化服务: active_care_service` 日志后不动，不出端口，按 Ctrl+C 也无法退出
*   **复现步骤**:
    1. 启动主程序 `python main.py`
    2. 观察日志：`[INFO] [core.core_engine.lifecycle_manager] 初始化服务: active_care_service`
    3. 程序卡死不动，不出端口，Ctrl+C 无效
*   **预期行为**: 所有服务正常初始化完成，端口绑定成功，Ctrl+C 可正常退出
*   **实际行为**: 程序卡死，端口不绑定，Ctrl+C 无法退出
*   **根因**:
    1. `ActiveCareService.__init__` 中调用 `get_bert_analyzer()`，该函数在 `__new__` 中同步执行 `_initialize()`，加载 ONNX 模型、BertTokenizer、计算 embeddings，全部是 CPU 密集型同步操作，会阻塞 asyncio 事件循环
    2. `ProactiveChecker.__init__` 中也调用了 `get_bert_analyzer()`，同样阻塞
    3. 由于 `active_care_service` 和 `aveline_service` 同优先级并行初始化（`asyncio.gather`），阻塞导致整个初始化流程无法完成
    4. 信号处理器（`_install_windows_console_close_handler`）在 `initialize_all()` 之后才安装，所以初始化期间 Ctrl+C 无法被捕获
    5. 即使信号处理器已安装，事件循环被同步阻塞时，`loop.call_soon_threadsafe` 的回调也无法执行
*   **修复**:
    1. 将 `ActiveCareService` 和 `ProactiveChecker` 中的 `get_bert_analyzer()` 改为懒加载属性（`@property`），首次访问时才初始化
    2. 将信号处理器安装提前到 `initialize_all()` 之前
    3. 在 `_request_shutdown` 中添加 3 秒紧急退出看门狗线程，如果事件循环被阻塞无法响应，直接 `os._exit(0)` 强制退出

### 10.40 Active Care 从不发消息 - enable_proactive_checker 未传入 (2026-04-27)

*   **问题描述**: Active Care 模块虽然代码完整（28个核心文件），但从未主动发送过任何消息。整个主动关怀管道完全瘫痪。
*   **复现步骤**:
    1. 启动服务，等待任意时间
    2. 观察日志，Active Care 主循环运行但 `if self.checker:` 始终为 `False`
    3. 无任何主动消息被生成或发送
*   **预期行为**: Active Care 应根据配置 `active_care_enabled: true` 启用 `ProactiveChecker`，定期检查并主动发送关怀消息。
*   **实际行为**: `lifecycle_manager.py:510` 调用 `get_active_care_service()` 时未传入 `enable_proactive_checker=True`，导致 `ProactiveChecker` 从未被创建。
*   **根因**: `get_active_care_service(enable_proactive_checker: bool = False)` 的默认值为 `False`，而 `initialize_active_care_service()` 调用时未传入任何参数。配置文件中的 `active_care_enabled: true` 从未被读取。
*   **修复**: `initialize_active_care_service()` 现在从配置读取 `active_care_enabled` 并传入 `enable_proactive_checker` 参数。

## 10. 开发经验与回顾 (Development Retrospective)

### 10.41 Active Care 单例竞态条件 - 无参调用导致 ProactiveChecker 永远不创建 (2026-04-26)

*   **问题描述**: 即使修复了 lifecycle_manager 读取配置的问题，Active Care 仍然不发消息。诊断脚本显示 `_enable_proactive_checker = False`，`checker = None`。
*   **复现步骤**:
    1. 启动服务（aveline_service 和 active_care_service 并行初始化，优先级都是6）
    2. 用户发消息 → handlers.py 或 aveline/service.py 调用 `get_active_care_service()`（无参）
    3. 单例以 `enable_proactive_checker=False` 被提前创建
    4. `initialize_active_care_service()` 调用 `get_active_care_service(enable_proactive_checker=True)` 时，单例已存在，直接返回
    5. ProactiveChecker 永远不会被创建
*   **预期行为**: 即使单例被提前创建，后续调用 `get_active_care_service(enable_proactive_checker=True)` 时应自动升级。
*   **实际行为**: 单例创建后不可变，`enable_proactive_checker` 永远是 `False`。
*   **根因**: `get_active_care_service()` 是单例模式，但多个调用方使用不同的参数（有参/无参），导致竞态条件。
*   **修复**: `get_active_care_service()` 新增升级逻辑——当单例已存在但 `enable_proactive_checker` 不匹配时，自动创建 `ProactiveChecker` 并初始化。

### 10.35 `verify_daily_task_panel_and_active_care_priority.py` 断言与当前 Priority Focus 逻辑不一致 (2026-04-08)

*   **问题描述**: 运行 `tests/diagnostics/verify_daily_task_panel_and_active_care_priority.py` 时，`verify_active_care_priority_focus()` 断言失败，期望 `focus["task_probe"] is None`，但当前实现返回了非空结构。
*   **复现步骤**:
    *   在项目根目录执行 `.\venv_core\Scripts\python.exe tests\diagnostics\verify_daily_task_panel_and_active_care_priority.py`
    *   前两段 workspace daily task 校验通过
    *   进入 `verify_active_care_priority_focus()` 后在 `assert focus["task_probe"] is None` 处失败
*   **预期行为**: 诊断脚本断言应与当前 `ProactiveChecker._build_priority_focus()` 逻辑保持一致。
*   **实际行为**: 脚本仍按旧行为断言，导致诊断失败。
*   **当前结论**:
    *   该失败与“今日计划落盘 + Active Care 提醒”功能改动无直接关系
    *   后续若继续用该脚本做回归，需要先同步更新断言口径

### 10.34 更正睡觉时间后 Active Care 睡眠时长未同步更新 (2026-04-08)

*   **问题描述**: 用户更正睡觉时间为 21:30 后，Active Care 仍说"睡了将近12小时"（实际应为8小时28分）。
*   **复现步骤**:
    *   用户说"晚安" → `last_goodnight_ts` 被设置为当时时间
    *   用户更正"昨晚九点半睡的" → `daily_record.json` 的 sleep 更新为 21:30
    *   Active Care 计算 → 用旧的 `last_goodnight_ts`，得出 12 小时
*   **预期行为**: 更正睡觉时间后，Active Care 应同步更新睡眠时长。
*   **实际行为**: `daily_record` 和 `proactive_state` 数据不同步，后者仍用旧值。
*   **解决方案**:
    *   新增 `_sync_sleep_to_active_care` 和 `_sync_wakeup_to_active_care` 函数
    *   在 `_apply_correction_by_intent` 中调用同步函数
    *   更正时同步更新 `last_sleep_session_start_ts`/`end_ts` 和 `duration_seconds`

### 10.32 时间解析忽略"晚上"修饰词导致更正失败 (2026-04-08)

*   **问题描述**: 用户说"改回去，我昨晚九点半睡的，今天6点起的"，系统把睡觉时间记录成 09:30（早上），且记录到今天而不是昨天。
*   **复现步骤**:
    *   用户说"改回去，我昨晚九点半睡的"
    *   系统调用 `extract_time_hhmm("昨晚九点半睡的")` 返回 "09:30"
    *   系统调用 `record_sleep("09:30")`，时间不在熬夜范围，记录到今天
*   **预期行为**: "九点半"在"晚上"修饰下应解析为 21:30，"昨晚"应修改昨天的记录。
*   **实际行为**: 时间解析完全忽略"晚上"修饰词，更正逻辑无法指定日期。
*   **解决方案**:
    *   `extract_time_hhmm` 新增 `is_pm`/`is_am` 检测，识别"晚上/晚/夜里/凌晨/早上"等修饰词，自动+12/-12小时
    *   `record_sleep` 新增 `target_date` 参数，允许指定日期
    *   `_apply_correction_by_intent` 识别"昨晚/昨天"关键词，传递 `target_date`

### 10.39 普通对话无 thought 时写入 derived thinking 噪音 + Active Care 未按人设切换 (2026-03-20)

*   **问题描述**:
    *   普通主程序对话若模型未返回 thought，会自动生成“用户刚刚表达了...”模板并写入历史，降低可读性。
    *   Active Care 默认使用 Aveline 人设提示词，当前前台为Ling时仍可能使用 Aveline 口吻。
*   **复现步骤**:
    *   查看 `history/short_term/*_short.json` 中 metadata 的 `thought_source=derived` 记录。
    *   切换前台为Ling后触发 Active Care，观察主动消息口吻与存储状态文件。
*   **预期行为**:
    *   无真实 thought 时不写 thinking 噪音，只保存实际 user/assistant 内容。
    *   Active Care 应根据当前会话人设切换提示词，并具备独立状态存储。
*   **实际行为**:
    *   旧逻辑会写入 derived thinking。
    *   Active Care 状态文件共用单目录，口吻切换不稳定。
*   **解决方案**:
    *   移除普通会话 fallback thinking 自动生成逻辑，thinking 仅在真实 thought 存在时写入。
    *   Active Care 执行器按 `conversation_id` 解析人设 scope，加载 `core_ling.json/core_aveline.json` 对应提示词。
    *   Active Care 存储切到 `companion_data/active_care/{aveline|ling}/`，实现角色独立状态隔离。

### 10.70 Active Care 晚安后仍催聊 + “昨晚X点睡”幻觉记录（2026-03-16）

*   **问题描述**:
    *   用户明确发送“晚安/我睡了”后，夜间 Active Care 仍继续发起聊天，影响免打扰体验。
    *   次日消息中出现“你昨晚七点十五睡的”这类具体就寝时刻表述，但历史中并无该明确事实，属于时间幻觉。
*   **复现步骤**:
    *   晚间触发 goodnight/reduced(goodnight)；
    *   观察夜间主动消息仍触发（尤其在连续检查周期中）；
    *   次日主动消息或衔接消息出现“昨晚 X 点睡”的具体时分推断。
*   **预期行为**:
    *   晚安态下默认严格免打扰，不应持续催聊；
    *   文案不得编造具体就寝时分，尤其在缺乏明确证据时。
*   **实际行为**:
    *   旧逻辑主要依赖文案约束，缺少调度层硬拦截，导致仍会进入发送链路；
    *   生成文本偶发输出具体睡眠时分。
*   **解决方案**:
    *   `core/services/active_care/proactive_checker.py` 增加晚安静默硬拦截与探测回退窗口：
        *   `allow_goodnight_probe=false` 时直接跳过发送；
        *   `allow_goodnight_probe=true` 时按 `goodnight_probe_gap_seconds` 节流。
    *   `core/services/active_care/prompt_builder.py` 增加“禁止主动给出用户具体就寝钟点”硬约束。
    *   `core/services/active_care/executor.py` 增加“昨晚X点睡”文本兜底净化，命中后替换为中性低打扰关怀。
    *   新增诊断脚本 `tests/diagnostics/verify_active_care_quiet_and_sleep_claim_guard.py`。
        *   `VectorSearch(use_in_memory_db=False, collection_name="aveline_dialogue_sfw_daily").query("用户下班回家好累", top_k=2)`
        *   `VectorSearch(use_in_memory_db=False, collection_name="aveline_dialogue_nsfw").query("亲密一点", top_k=2)`
    *   观察第二个实例是否报错。
*   **预期行为**: 多个 `VectorSearch` 实例互不影响；每个实例都能正确初始化并执行查询。
*   **实际行为**: 由于依赖懒加载用模块级 `_chromadb_loaded` 作为一次性门控，后续实例不会进入导入分支，从而未设置 `self._chromadb_module`，进而在初始化时访问该属性报错。
*   **解决方案**:
    *   将 `chromadb` 模块缓存到模块级 `_chromadb_module`，并在 `_chromadb_loaded=True` 的后续实例中回填 `self._chromadb_module = _chromadb_module`。文件：`core/vector_search.py`
    *   增加回归测试覆盖该行为，确保后续实例能正确继承模块引用。文件：`tests/test_context_overflow.py`
*   **验证结果**:
    *   `python -m ruff check .` 通过；
    *   `python -m mypy .` 通过；
    *   `python -m pytest -q` 通过；
    *   端到端验证：SFW/NSFW/Study 三个 collection 均能查询返回样例，且动态 system prompt 能注入 `# Dynamic Dialogue Examples (Contextual)`。

### 10.62 Active Care 醒来判定滞后与决策 JSON 轻微损坏误拦截（2026-03-15）

*   **问题描述**:
    *   用户距离上次互动仅约 35 分钟，Active Care 仍沿用“晚安后静默态”，出现“可能还在睡”的误判文案。
    *   决策日志出现 `Active Care: Decision was NOT to send. Thought: LLM output format error`，实际原始输出中已包含 `should_send=true` 和有效 `intent`。
*   **复现步骤**:
    *   前一晚触发过 goodnight/reduced(goodnight)；
    *   次日用户发送普通互动消息（不包含“早安/醒了”等显式唤醒关键词）；
    *   观察 Active Care 仍按睡眠态提示；
    *   当 LLM 决策 JSON 出现尾部字段缺失值或轻微格式损坏（如 `planned_delay_seconds` 未完整闭合）时，触发解析失败并直接走 `should_send=false`。
*   **预期行为**:
    *   用户发生真实互动后应退出晚安静默态，不应继续按“未醒”假设决策；
    *   决策输出包含核心字段时，应具备容错修复能力，不应因轻微格式瑕疵直接判定“不发送”。
*   **实际行为**:
    *   睡眠态依赖显式关键词退出，普通互动存在状态残留窗口；
    *   决策解析仅 `json.loads`，轻微损坏即回退 `LLM output format error + should_send=false`。
*   **解决方案**:
    *   `core/services/active_care/service.py`：用户互动到达时，若仍处于晚安静默且消息不含再次入睡语义，则自动清理 `last_goodnight_ts` 与 `reduced(goodnight)` 状态。
    *   `core/services/active_care/decision.py`：增加多级解析容错（代码块提取、尾逗号修复、缺失数值字段补齐、字段级回退提取），保留 `should_send/intent` 有效信号。
    *   新增诊断脚本 `tests/diagnostics/verify_active_care_wakeup_and_decision_parse.py`，覆盖上述两条回归路径。

### 10.35 Active Care 夜间睡眠语义漏判与延迟观感问题 (2026-03-15)

*   **问题描述**:
    *   用户已表达“我要睡了/别回了/已离线”后，Active Care 仍可能发送任务追问或状态推断类文案，夜间陪伴体验违和；
    *   用户侧观感为“23 点突然发一次，后面很久不发”，与预期低频暖心关怀不一致。
*   **复现步骤**:
    *   用户在主会话中发送“睡了、别回了”等语句；
    *   Active Care 状态未及时记录到 `last_goodnight_ts` 时，继续触发主动决策；
    *   观察到文案偏“推断/追问”，且调度间隔受 do_nothing + next_check 叠加后拉长。
*   **预期行为**:
    *   即使状态缓存偶发漏写，也应从最近历史中推断睡眠语义并进入晚安低打扰模式；
    *   夜间文案应以“想你了/你先休息/等你醒来再聊”为主，不应继续任务催办或状态推断。
*   **实际行为**:
    *   仅依赖状态字段时会出现漏判，导致夜间语气与场景不匹配；
    *   do_nothing 分支会设置下次决策时间，用户未回复时体感为“后续不发”。
*   **解决方案**:
    *   在 `ActiveCareProactiveChecker` 增加“最近历史睡眠语义兜底推断”，命中后自动进入 `goodnight` reduced mode；
    *   在 `decision.py` 收紧 quiet/reduced(goodnight) 文案约束，优先低打扰想念式表达，禁止任务催办与推断追问；
    *   新增诊断脚本 `tests/diagnostics/verify_active_care_sleep_mode_infer.py` 保障该路径可回归验证。
    *   在 warnings summary 中可见类似：`chromadb/api/collection_configuration.py:327: DeprecationWarning: legacy embedding function config ...`。
*   **预期行为**: 测试输出不包含与本项目无关的弃用告警，便于聚焦真实回归问题。
*   **实际行为**: 第三方依赖产生弃用告警，污染测试输出。
*   **处理方式**:
    *   当前测试全部通过（`25 passed, 7 skipped`），该告警暂不阻断。
    *   后续若需要清理噪音：优先升级/调整 `chromadb` 与 embedding function 的配置方式；或在 `pytest` 配置中按模块级别过滤该类告警（避免全局忽略导致掩盖真实弃用问题）。

### 10.32 Active Care 历史会话错位与系统 Python 误用 (2026-03-11)

*   **问题描述**: QQ 场景中，用户回复 Active Care 消息后，主对话偶发读不到刚发送的主动消息；同时调试脚本/主程序偶发走系统 Python，导致 `onnxruntime/transformers` 依赖报错。
*   **复现步骤**:
    *   让 Active Care 向 QQ 私聊主动发送一条消息。
    *   用户立即回复该条主动消息。
    *   观察主对话回复引用的是更早历史而非最新主动消息。
    *   在未显式指定解释器时执行 `python main.py`，观察解释器路径与依赖报错。
*   **预期行为**:
    *   Active Care 主动消息应同时对齐主对话历史，用户回复后能引用最新主动内容。
    *   调试与启动应稳定使用 `venv_core`，不再误用系统 Python。
*   **实际行为**:
    *   主动消息仅写入 `*_local` 或基础会话之一，导致另一侧历史缺失。
    *   命令环境偶发落到系统 Python，触发依赖缺失。
*   **解决方案**:
    *   在 `ActiveCareExecutor._build_persist_conversation_ids` 中实现双向映射：`cid <-> cid_local` 同步落盘。
    *   在 `.vscode/settings.json` 固定 `python.defaultInterpreterPath` 到 `venv_core` 并开启终端自动激活。

3. **模型量化与参数调整**：
   - LLM: `n_gpu_layers` 设为 -1 会尝试全部加载。可尝试减少层数或使用更小的量化版本 (e.g., Q4_0, Q3_K)。
   - Context: `n_ctx` 限制在 2048 或更低。

### 10.18 Active Care 唤醒失效与长时间静默 (2026-01-31)

*   **问题描述**: 用户反馈 "Active Care 没有工作"，具体表现为早上 11 点起床后，虽然昨晚挂机一整夜，但系统既没有写日记也没有发送任何唤醒问候消息，长达 10 小时无响应。
*   **原因分析**:
    *   **上下文过期待定**: `ActiveCareService` 依赖 `device_context` 判断用户状态。原逻辑中，若设备上下文超过 15 分钟（或 900s）未更新，系统认为用户离线，从而跳过所有主动关怀逻辑。
    *   **夜间休眠导致上下文断档**: 手机 APP 在后台运行一整夜后，可能因系统休眠停止发送心跳。早上用户醒来时，若 APP 尚未恢复心跳上报，服务器端看到的上下文仍是昨晚的，处于 "stale" 状态，导致 "Wake Up" 问候被拦截。
    *   **唤醒逻辑缺陷**: 唤醒判断逻辑过于依赖 "First Interaction of Day"（跨天检查），若用户凌晨 1 点才睡（已有今日交互），早上 11 点醒来（同一天），原有逻辑会因 `last_sent_date == current_date` 而误判为已问候过。
*   **解决方案**:
    *   **放宽上下文超时**: 将上下文有效时间窗口从 15 分钟延长至 60 分钟 (3600s)。
    *   **新增兜底唤醒逻辑 (Fallback Wake Up)**:
        *   在早晨时间段 (05:00 - 13:00)，如果检测到距离上次互动超过 6 小时（即长睡眠跨度），即使上下文过期，也强制触发 "Wake Up Greeting"。
        *   移除对 `last_sent_date` 的强校验，改为仅依赖长时间静默间隔 (Gap > 6h) 和时间窗口判断，兼容熬夜党（凌晨入睡，同日醒来）的场景。
*   **验证**: 编写 `tests/diagnostics/reproduce_active_care_stale.py` 模拟 10 小时静默 + 11 点唤醒场景，确认修复后系统能正确触发唤醒问候。

### 10.28 “探针脚本可回、后端不回”的差异分析与修复记录 (2025-12-16)


*   问题背景与现象:
    *   直接运行本地探针脚本（`probe_local_llm.py`）能够正常流式输出并记录“首个 token 耗时”，而通过后端接口 `/api/v1/message` 同样的输入却在十几秒后返回错误提示或超时，用户直观感受为“脚本能回，后端不回”；
    *   复现数据:
        *   探针脚本：`llama_cpp.create_chat_completion(stream=True)` 首 token约 0.2s，完整输出正常 (`probe_local_llm.py:80-124`)；
        *   后端：首次请求耗时 ~20s 返回“抱歉，系统遇到了一些问题。”，日志显示 `NameError: extract_and_strip_emotion is not defined`；修复后再次请求耗时 ~13s，HTTP 200 返回 `System Error: 本地模型在 10 秒内没有产生任何输出，请尝试重启模型或缩短输入。`，日志显示“首 token 超时 10 秒”（`core/services/scheduler/cpp_scheduler_engine.py:371-379`）。
*   原因分析:
    *   聚合阶段函数未正确导入导致早期异常：
        *   `AvelineService.generate_response` 在聚合流式结果后调用 `ChatAgent.extract_and_strip_emotion`，而 `ChatAgent` 内部未导入 `core.utils.text_processor.extract_and_strip_emotion`，导致 `NameError`，被聚合层捕获后统一返回“抱歉，系统遇到了一些问题。” (`core/services/aveline/service.py:370-388`, `core/agents/chat_agent.py:306-313`)；
        *   这属于上层聚合逻辑错误，与模型推理性能无关，会掩盖真实的首 token 行为。
    *   后端管线比探针脚本重、首 token 更易超时：
        *   探针脚本仅包含一条 `user` 消息；后端在 `ChatAgent` 层注入系统提示词、可能的日常概要、历史片段等，常见为 8-12 条 `messages`，并经过资源管理器的重负载准备流程（TTS/STT卸载等），首 token 时延显著增大 (`core/agents/chat_agent_components/streaming.py:157-173`)；
        *   后端启用“首 token 超时”的早返回机制：`LLMModule.stream_chat` 与 `CPPSchedulerEngine.submit_llm_task` 首次从队列取元素均使用 `asyncio.wait_for(..., timeout=first_token_timeout)`，默认取自集成配置 `model.first_token_timeout=10` 秒，一旦超时返回中文提示并结束会话 (`core/modules/llm/module.py:358-392`, `core/services/scheduler/cpp_scheduler_engine.py:357-381, 416-420`)；
        *   探针脚本没有该 10 秒早返回机制，且输入更轻量，因此表现为“脚本能回、后端提示超时”。
    *   上下文与参数差异：
        *   后端当前默认 `n_ctx=2048`，历史消息会做字符级切片（约 1800 字符）以适配本地 GGUF 模型，但遇到长系统提示词+多轮历史叠加时仍会增加首 token 计算负载；同时 `max_new_tokens` 会按 `n_ctx` 上限进行动态收敛，避免越界，但不会改善首 token启动时间 (`core/modules/llm/module.py:236-248, 526-554`)。
*   修复与改动:
    *   修复聚合层导入错误：
        *   为 `ChatAgent` 补充 `from core.utils.text_processor import extract_and_strip_emotion`，消除 `NameError`，避免聚合阶段将正常错误提示误包装为“系统遇到问题” (`core/agents/chat_agent.py:51-55`)；
    *   将 C++ 调度器的首 token 超时统一读取集成配置：
        *   旧逻辑 Python Llama 路径默认 30 秒、C++ 回落路径默认 10 秒；现统一为读取 `get_settings().model.first_token_timeout`，便于通过 `app.yaml` 调整环境适配值 (`core/services/scheduler/cpp_scheduler_engine.py:357-365, 416-420`; `config/yaml/app.yaml:56-58`; `config/integrated_config.py:73-74, 382-385`)；
    *   增强关闭流程的资源清理：
        *   为云端 LLM 客户端增加 `shutdown()` 主动关闭 `aiohttp.ClientSession`，并在 `HybridLLMModule` 与 `AvelineService.shutdown` 中调用，消除关闭阶段“未关闭会话”的隐性泄漏风险 (`core/llm/dashscope_client.py:86-92`, `core/llm/siliconflow_client.py:96-103`, `core/llm/openai_client.py:72-78`, `core/llm/__init__.py:115-130, 241-252`, `core/services/aveline/service.py:102-113`)。
*   验证结果:
    *   修复导入后再次调用 `/api/v1/message`：
        *   当底层模型 10 秒内未产出首 token，HTTP 侧在 ~13 秒返回 `System Error: 本地模型在 10 秒内没有产生任何输出...`（含服务器侧排队与资源准备时间），日志记录“首 token 超时 10 秒” (`routers/api_router.py:795-812`)；
        *   当底层模型能正常产出 token，HTTP 侧会在 `limits.message_timeout` 之前返回完整内容；探针脚本与后端表现一致（但管线更重时首 token更慢）。
*   调优建议:
    *   结合设备情况将 `model.first_token_timeout` 调整为 15-30 秒，减少“管线较重场景”下的误判早返回；如需与探针脚本保持一致，建议用相同的 `messages` 规模与温度设置进行对比 (`config/yaml/app.yaml:56-58`)；
    *   若首 token长期慢于 10 秒，应优先检查：上下文长度（系统提示词+历史片段总字符数）、显存占用（确保 `n_gpu_layers=-1` 充分 offload）、是否存在并发重负载任务（图像生成/语音合成等）。
*   经验总结:
    *   “脚本可回、后端不回”通常不是模型不可用，而是后端管线更复杂+存在首 token 早返回保护；排查时应同时关注聚合层错误、首 token 配置与上下文规模三者的组合；
    *   统一从配置读取时序参数（如首 token 超时）能显著改善跨路径行为一致性，同时为不同硬件环境提供更好的可调性。

### 10.4 每日任务 (Daily Routine) 性能优化 (2025-12-13)

*   **问题描述**: 用户反馈系统不回消息，日志显示主线程被阻塞。经排查，`_check_daily_routine` 函数在主事件循环中同步执行了数据库查询和锁操作（WeightedMemoryManager RLock），导致高并发或锁争用时阻塞 Event Loop。
*   **解决方案**:
    *   **异步化改造**: 将同步的每日任务检查逻辑封装为独立函数。
    *   **线程卸载**: 使用 `asyncio.to_thread` 将耗时逻辑卸载到独立线程执行，释放主线程。
    *   **超时熔断**: 为每日任务检查增加 `asyncio.wait_for` (1.5s)，确保即使后台任务卡死也不会影响主对话流程。
*   **经验总结**: 在 FastAPI/Asyncio 架构中，严禁在 `async def` 中直接调用涉及 IO 或锁的同步代码。

### 10.93 新增角色起床主动发早安消息功能（与晚安对称，走 active_care LLM 生成） (2026-07-06)
*   **问题描述**: 用户反馈 AI 角色只在睡觉时发晚安，没有起床时的早安。希望也是走 active_care 让 LLM 根据睡眠摘要（时长/噩梦/惯性等）生成自然消息，而非固定模板。
*   **复现步骤**:
    1. 角色按作息时间到达 wake_dt，SleepManager._update_runtime_state 检测到 dt >= wake_dt 且 state.phase == SLEEPING
    2. 状态转换：phase 从 SLEEPING → WAKING_UP，计算 last_sleep_duration_hours / sleep_debt_hours / sleep_inertia_score 等
    3. 调用 _on_enter_waking_up(role_id, prev_phase=SLEEPING, now, wake_dt, is_stay_up_recovery=False)
    4. _on_enter_waking_up 检查 prev_phase != WAKING_UP 且 now 距 wake_dt <= 30 分钟，调用 trigger_character_good_morning_async
    5. trigger_character_good_morning 走 executor.trigger_message(client_type="qq")，LLM 自动拿到 sleep_context_text 生成自然早安消息
*   **预期行为**:
    1. 角色按作息起床时主动给用户发早安消息，消息内容由 LLM 根据睡眠摘要生成
    2. 熬夜后白天恢复清醒时也能发早安，消息可体现疲惫感
    3. 每日去重，每人每天只发一次早安
    4. 服务延迟重启（now 距 wake_dt 超过 30 分钟）时跳过，避免下午发早安
    5. 消息能实时送达 QQ（client_type="qq" 确保 broadcast 剥离 __persona__ 后缀找到连接）
*   **实际行为**:
    1. 此前完全没有早安逻辑：RitualManager._check_morning_ritual 是固定模板字符串，不是真正的主动消息；_on_enter_sleeping 只处理 SLEEPING 进入，不处理 WAKING_UP 转换
*   **根因**:
    1. SleepManager._update_runtime_state 中两个 WAKING_UP 转换点（按作息起床 + 熬夜后白天恢复）都没有 hook
    2. 没有对应的 good_morning_proactive 模块（与 goodnight_proactive 对称）
    3. 没有 good_morning_proactive sys_prompt_type 注册到 prompt_builder
*   **修复方案**:
    1. core/services/active_care/good_morning_proactive.py: 新建模块，与 goodnight_proactive.py 对称。trigger_character_good_morning / trigger_character_good_morning_async，client_type="qq"
    2. core/services/life_simulation/sleep_manager.py:179-240: 新增 _on_enter_waking_up 方法，含 30 分钟延迟重启保护
    3. core/services/life_simulation/sleep_manager.py:33-35: 新增 _WAKING_UP_GOOD_MORNING_WINDOW_SECONDS=30*60 常量
    4. core/services/life_simulation/sleep_manager.py:488-491: 按作息起床转换点调用 _on_enter_waking_up(is_stay_up_recovery=False)
    5. core/services/life_simulation/sleep_manager.py:525-528: 熬夜恢复转换点调用 _on_enter_waking_up(is_stay_up_recovery=True)
    6. core/agents/chat_agent_components/persona_system/prompt/active_care_prompts.py:149-159: 新增 TASK_GOOD_MORNING_PROACTIVE_TEMPLATE
    7. core/services/active_care/prompt/prompt_builder.py:28: 导入 TASK_GOOD_MORNING_PROACTIVE_TEMPLATE
    8. core/services/active_care/prompt/prompt_builder.py:175-177: 新增 good_morning_proactive 分支
    9. tests/scripts/active_care/verify_character_good_morning.py: 新建测试，12 个用例
*   **验证**:
    1. `.\venv_core\Scripts\python.exe -m pytest tests/scripts/active_care/verify_character_good_morning.py tests/scripts/active_care/verify_character_goodnight.py -v （25 passed）`
    2. `.\venv_core\Scripts\ruff.exe check（All checks passed）`

### QR-20260709-GM-WINDOW 早安消息 30 分钟窗口保护过激导致服务延迟启动时全部跳过 (2026-07-09)
*   **问题描述**: 用户反馈过了一周仍没收到角色的早安消息。服务上午才启动时，第一次 get_state 触发 WAKING_UP 转换，但此时 now 距 wake_dt 已超过 30 分钟，_on_enter_waking_up 中的窗口保护逻辑直接跳过早安消息，导致每天都被跳过。
*   **复现步骤**:
    1. 服务在上午 11:10 启动（非 24/7 运行）
    2. aveline 的 planned_wake_time=07:04，wake_dt 为早上 7 点
    3. 第一次 get_state 时 dt=11:10，delay=4小时6分钟 > 30分钟
    4. _on_enter_waking_up 命中窗口保护，跳过早安消息
*   **预期行为**:
    1. 角色在计划起床时间触发 WAKING_UP 时应发送早安消息
    2. 即使服务延迟启动，只要当天还没发过早安，就应补发（由每日去重保护避免重复）
*   **实际行为**:
    1. sleep_states.json 显示 aveline 在 2026-07-08 07:04 有 wakeup 事件，但未触发任何早安消息
    2. 因 delay 超过 30 分钟，_on_enter_waking_up 直接 return，早安消息被全部跳过
*   **根因**:
    1. _WAKING_UP_GOOD_MORNING_WINDOW_SECONDS=30*60 窗口保护假设服务 24/7 运行，未考虑用户上午才启动服务的场景
    2. 该保护与 good_morning_proactive 的每日去重功能重复，且更激进，导致双重拦截
*   **修复方案**:
    1. 删除 _WAKING_UP_GOOD_MORNING_WINDOW_SECONDS 常量
    2. 删除 _on_enter_waking_up 中的 delay_seconds 检查逻辑
    3. 改为只用 good_morning_proactive._sent_today 按 role_id 维度做每日去重保护
    4. 更新测试：删除 test_skip_when_delay_exceeds_30_minutes，新增 test_trigger_even_when_delay_exceeds_30_minutes 验证新行为
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\scripts\active_care\verify_character_good_morning.py -v（12 passed）`

### QR-20260709-GM-LOGGER sleep_manager logger 不写入 xiaoyou_main.log 导致触发记录无法排查 (2026-07-09)
*   **问题描述**: 排查早安/晚安未发送时，发现 _on_enter_waking_up / _on_enter_sleeping 的日志只输出到控制台，不写入 xiaoyou_main.log，无法通过日志文件验证功能是否触发。
*   **复现步骤**:
    1. 查看 xiaoyou_main.log 寻找 _on_enter_waking_up 的触发日志
    2. 发现没有任何相关日志记录
    3. 检查 sleep_manager.py:29，发现用 logging.getLogger(__name__)
    4. 检查 core/utils/logger.py:756，root_logger 只有 _console_handler，没有 file handler
*   **预期行为**:
    1. _on_enter_waking_up / _on_enter_sleeping 的 info/warning 日志应写入 xiaoyou_main.log，便于排查主动消息是否触发
*   **实际行为**:
    1. logging.getLogger(__name__) 创建的 logger 只传播到 root logger
    2. root logger 只有 console handler，没有 file handler，日志不写入文件
*   **根因**:
    1. sleep_manager.py 用 logging.getLogger(__name__) 而非项目统一的 get_logger(__name__)
    2. get_logger 会添加 QueueHandler 写入 xiaoyou_main.log，而 logging.getLogger 不会
*   **修复方案**:
    1. 将 sleep_manager.py 的 logger 改为 from core.utils.logger import get_logger; logger = get_logger(__name__)
    2. 移除不再使用的 import logging
    3. 添加注释说明必须用 get_logger 的原因
*   **验证**:
    1. `venv_core\Scripts\python.exe -m ruff check core\services\life_simulation\sleep_manager.py（All checks passed）`

### QR-20260709-DEDUP-BYPASS 晚安/早安短句关怀被 active_care 去重误杀 (2026-07-09)
*   **问题描述**: 晚安消息 LLM 生成 '晚安，Master。我也要睡了，记得明天起来先吃饭。' 与用户历史 '晚安，Master' 重复，被 active_care 句子级部分包含检测命中（重复句数=2，阈值=2），跳过本轮发送，导致晚安消息发不出去。
*   **复现步骤**:
    1. 角色入睡触发 goodnight_proactive 主动消息
    2. LLM 生成 '晚安，Master。我也要睡了，记得明天起来先吃饭。'
    3. postprocessor 句子级部分包含检测：拆成 2 句，第 1 句 '晚安，Master。' 与历史锚点 '晚安，Master' 重复
    4. 触发二次改写，改写后仍命中去重，跳过本轮发送
*   **预期行为**:
    1. 晚安/早安这类短句关怀应正常发送，不受去重影响
*   **实际行为**:
    1. 句子级部分包含检测命中，消息被跳过本轮发送
*   **根因**:
    1. active_care postprocessor 对所有 sys_prompt_type 统一应用去重，未区分短句关怀类
    2. 晚安/早安天然容易与历史重复（'晚安''早安'），去重阈值对此类消息过于激进
*   **修复方案**:
    1. 新增 _DEDUP_BYPASS_SYS_PROMPT_TYPES 集合（goodnight_proactive / good_morning_proactive / sleep_again_proactive）
    2. 这三种 sys_prompt_type 在 postprocess 中跳过整句语义去重、最终去重检查和句子级部分包含检测
    3. 仅保留睡眠净化和泄露检测，确保消息安全
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\scripts\active_care\verify_dedup_bypass.py -v（4 passed）`

### QR-20260709-ACTIVITY-RETURN activity_return 回归消息未触发 (2026-07-09)
*   **问题描述**: /打断 后聊天窗口即将结束时，AI 没有发送回归消息；日志显示 ActiveCareExecutor.trigger_message() 报错不接受 target_conversation_id 参数。
*   **复现步骤**:
    1. 用户执行 /打断 300
    2. schedule_activity_return 创建延迟任务
    3. 延迟结束后 _wait_and_trigger 调用 send_activity_return_message
    4. send_activity_return_message 调用 ac.executor.trigger_message(..., target_conversation_id=conversation_id)
*   **预期行为**:
    1. AI 在窗口快结束时主动发送一条自然告别消息，告知用户要回去做事
*   **实际行为**:
    1. trigger_message 抛出 TypeError，消息未发送；用户从未收到回归消息
*   **根因**:
    1. ActiveCareExecutor.trigger_message 签名不包含 target_conversation_id，activity_return.py 误传了该参数
*   **修复方案**:
    1. 移除 target_conversation_id 参数，依赖 executor 内部 conversation_router 解析目标会话
*   **验证**:
    1. `运行 tests/scripts/character_daily/verify_activity_return.py，test_schedule_triggers_return_message 等用例全部通过`

### QR-20260709-AC-ACTIVITY-RETURN /打断 后聊天窗口结束时 AI 未发送回归消息 (2026-07-09)
*   **问题描述**: 用户使用 /打断 命令后，AI 进入临时聊天窗口；窗口快结束时应该主动发一条消息说『我要回去继续学习了』，但用户从未收到这条消息。
*   **复现步骤**:
    1. 用户在学习时间发送 /打断 命令
    2. AI 进入 300s 手动打断聊天窗口
    3. 等待窗口结束
    4. 观察 AI 是否发送回归消息
*   **预期行为**:
    1. 窗口结束前约 1 分钟，AI 主动发送自然、温和的告别消息
    2. 消息中明确提到要回去继续做什么
    3. 用户回复该消息后，AI 能根据回复内容选择继续聊还是真的回去做事
*   **实际行为**:
    1. 窗口直接过期，AI 没有任何告别消息
    2. 用户感觉不到 AI 从聊天回归到了原活动
*   **根因**:
    1. 原逻辑依赖 CharacterDailyEngine._tick 每 120s 轮询检查窗口剩余时间
    2. 60s 阈值窗口小于轮询间隔，且服务启动时间不确定，导致从未命中
    3. 没有事件驱动的调度机制
*   **修复方案**:
    1. 新增 activity_return.schedule_activity_return()，在 /打断 接口激活窗口时就用 asyncio task 安排好回归消息
    2. 新增 activity_return.send_activity_return_message() 统一发送 work/sleep 回归消息
    3. 新增 handle_user_reply_during_return() 处理用户回复，自动延长窗口并重新调度
    4. 在 reply_policy 的 prompt 中注入 build_activity_return_reply_hint()，让 LLM 根据用户回复自然决定去向
*   **验证**:
    1. `tests/scripts/character_daily/verify_activity_return.py`

### QR-20260710-PERSONA-MISMATCH 晚安/早安 persona_filename 不匹配导致 QQ 客户端丢弃消息 (2026-07-10)
*   **问题描述**: 用户反馈重启后仍未收到晚安/早安消息。服务端日志显示'已发送'和'已实时送达'，但 QQ 实际没收到。
*   **复现步骤**:
    1. 查看 xiaoyou_main.log，发现 23:00:08 '已发送 goodnight_proactive 消息并记录日记' 和 07:04:10 '已发送 good_morning_proactive 消息并记录日记'
    2. 服务端 proactive_messaging.py:223 打印'主动消息已实时送达'（基于 ws_manager.is_user_online）
    3. 追踪 conversation_id：target=private_10001__persona__core_aveline（由 persona_filename=core_aveline.json 构建）
    4. QQ 机器人连接详情：[('aveline', 'qq/Aveline_QQ_Master.json'), ('ling', 'qq/Ling_QQ_Master.json')]
    5. QQ 机器人期望的 conversation_id=private_10001__persona__aveline_qq_master
    6. receiver.py:180-186 校验 target_id == expected_cid → core_aveline ≠ aveline_qq_master → 'Ignoring proactive_message: persona mismatch' → 丢弃
*   **预期行为**:
    1. 晚安/早安消息应送达 QQ，用户能收到
*   **实际行为**:
    1. 服务端显示'已实时送达'，但 QQ 客户端因 persona 后缀不匹配（core_aveline ≠ aveline_qq_master）丢弃消息
    2. 用户实际收不到任何晚安/早安消息
*   **根因**:
    1. _ROLE_PERSONA_MAP 用 core_aveline.json（核心人设），但 QQ 机器人连接用 qq/Aveline_QQ_Master.json（QQ 专属人设）
    2. build_persona_conversation_id 从文件名提取后缀：core_aveline.json → core_aveline，Aveline_QQ_Master.json → aveline_qq_master
    3. QQ 客户端 receiver.py 校验 persona 后缀，不匹配则丢弃（debug 级日志默认不可见）
    4. 服务端'实时送达'日志只检查 WebSocket 连接是否存在，无法感知客户端侧丢弃
*   **修复方案**:
    1. _ROLE_PERSONA_MAP 改为 qq/Aveline_QQ_Master.json 和 qq/Ling_QQ_Master.json
    2. _resolve_persona_filename 默认值改为 qq/Aveline_QQ_Master.json
    3. 两个模块 logger 改为 get_logger 确保日志写入文件
    4. 更新测试断言为正确的 persona_filename
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\scripts\active_care\ -v（29 passed）`

### QR-2026-07-10-01 角色下午醒来仍发早安消息 (2026-07-10)
*   **问题描述**: ling 在 13:47 从熬夜状态恢复清醒时触发 good_morning_proactive，发了『早安』消息。午睡起来不应该算早安，不真实、不细节。
*   **复现步骤**:
    1. 角色 ling 夜间处于熬夜状态（STAY_UP_LATE/NIGHT_AWAKE/SLEEP_LATER）
    2. 13:47 时 sleep_manager._update_runtime_state 检测到 dt >= wake_dt，触发 _on_enter_waking_up(is_stay_up_recovery=True)
    3. good_morning_proactive.trigger_character_good_morning 被调用，LLM 生成早安消息并发送
*   **预期行为**:
    1. 下午醒来应根据时间用『下午好』『午安』等问候，而不是『早安』
    2. specific_instruction 中的疲惫感提示应正确传递到 LLM
*   **实际行为**:
    1. 13:47 发了『早安』消息
    2. _build_specific_instruction 没有时间感知，强制要求包含早安
    3. specific_instruction 被 prompt_builder 完全丢弃，未拼接到 prompt
*   **根因**:
    1. _build_specific_instruction 缺乏时间感知，固定要求早安
    2. prompt_builder._build_task_block_dynamic good_morning_proactive 分支忽略 specific_instruction 参数（bug）
    3. TASK_GOOD_MORNING_PROACTIVE_TEMPLATE 硬编码早安约束
*   **修复方案**:
    1. 新增 _get_wake_greeting_context(hour) 按时间段返回问候语要求
    2. _build_specific_instruction 加入时间感知，动态指定问候语
    3. 修复 prompt_builder good_morning_proactive 分支拼接 specific_instruction
    4. 模板改为『起床问候』，放开早安硬约束
*   **验证**:
    1. `d:\AI\xiaoyou-core\venv_core\Scripts\python.exe -m pytest tests/scripts/active_care/verify_character_good_morning.py -v`

### ISSUE-20260713-REPLY-WAKE /wake 唤醒后角色不回复消息（reply_policy 使用过时 activity） (2026-07-13)
*   **问题描述**: 用户半夜 /wake 唤醒角色后，给角色发消息她不回复。日志显示 ReplyPolicy 走 DND 分支静默累积消息（activity=napping/sleeping），即使 sleep_manager 的 phase 已变为 fully_awake 或 night_awake。
*   **复现步骤**:
    1. 用户半夜发 /wake 命令，API 返回 '已立即唤醒 aveline，当前状态：fully_awake'
    2. 用户发消息'我买了四包tempo的纸...'
    3. 日志显示 ReplyPolicy: 睡觉中，静默累积消息 (dnd_sleeping_silent(activity=napping, ac_sleeping=False) count=1)
    4. 用户再发消息'听到我说话没有'，才被强制唤醒（prob=0.25）
*   **预期行为**:
    1. /wake 唤醒后，角色应能正常回复消息，不应走 DND 分支静默累积
    2. reply_policy 查询 activity 时应得到非 DND 活动（如 idle）
*   **实际行为**:
    1. /wake 唤醒后（phase=fully_awake），reply_policy 查询 activity 得到 napping（DND 活动）
    2. is_dnd=True，走 DND 分支静默累积消息，角色不回复
    3. 需要连发多条消息才能触发强制唤醒
*   **根因**:
    1. reply_policy.py 使用 engine.get_current_activity() 获取缓存的 plan.current_activity，不会实时刷新；engine tick 间隔 120 秒，期间 activity 可能过时
    2. sleep_manager.get_activity_override() 对 NIGHT_AWAKE phase 返回 None，导致 _update_current_activity 使用 planned_activity（半夜通常是 sleeping）
    3. engine._update_current_activity() 未检查 phase 与 planned_activity 的一致性：phase=fully_awake/night_awake 但 planned_activity 是 DND 活动（napping/sleeping）时，仍使用 DND 活动
*   **修复方案**:
    1. reply_policy.py: 当 activity 是 DND 时，调用 engine.refresh_current_activity() 刷新，避免使用过时的缓存值
    2. sleep_manager.py: get_activity_override() 对 NIGHT_AWAKE phase 返回 'idle'，让角色被唤醒后能正常回复
    3. engine.py: _update_current_activity() 中，当 phase 是 fully_awake/night_awake 且 planned_activity 是 DND 活动时，使用 idle 代替
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\verify_night_awake_fix.py`

### QR-2026-0714-001 起床提醒被跳过后计划项未自动勾选 (2026-07-14)
*   **问题描述**: 用户已起床时，Active Care 起床提醒被跳过（日志：due_reminder 是起床提醒但用户已起床...跳过），但对应的计划项「起床洗漱+早餐」没有被标记为 completed，下次又会生成同样的提醒；同时结束提醒仍会触发。
*   **复现步骤**:
    1. 用户已起床（last_goodmorning_ts>0）
    2. Active Care 到点检查 due_reminder
    3. 命中起床关键词且 last_goodmorning_ts>0，进入跳过分支
    4. 只调用 complete_reminder 标记 reminder 完成
*   **预期行为**:
    1. 跳过起床提醒时，应自动把对应 PlanItem 标记为 completed（勾上）
    2. 同时清理 end_reminder，避免用户起床后还收到「该休息了」
*   **实际行为**:
    1. PlanItem 仍是 pending，视觉上没勾上
    2. end_reminder 仍会触发，用户起床后还收到「该休息了」的奇怪消息
*   **根因**:
    1. checker_event_handler.py 起床跳过分支只 complete_reminder，未联动 JournalService.mark_plan_item_status
    2. _defer_due_reminder 起床分支同样缺失 PlanItem 状态同步
*   **修复方案**:
    1. 新增 _auto_complete_wakeup_plan_item 辅助方法：从 reminder.metadata 读取 plan_item_id/plan_date，标记 PlanItem 为 completed 并清理 end_reminder
    2. 两处起床跳过分支均调用该辅助方法
*   **验证**:
    1. `venv_core\Scripts\ruff.exe check core\services\active_care\checker\checker_event_handler.py`

### Q20260715-01 两个角色晚安消息内容几乎一样且语义错误（说『说了晚安又不睡』而非自己要睡） (2026-07-15)
*   **问题描述**: 07-15 23:00 aveline 发送『哼，说了晚安又不睡』，23:30 ling 发送『说了晚安又不睡』。两个角色内容几乎一样，且这个意思不像角色自己要睡了，反而像在指责用户说了晚安又不睡。
*   **复现步骤**:
    1. 角色按作息时间 23:00 进入 SLEEPING 状态，sleep_manager 触发 trigger_character_goodnight
    2. trigger_character_goodnight 调用 executor.trigger_message(sys_prompt_type='goodnight_proactive')
    3. executor 构建 prompt：使用 TASK_GOODNIGHT_PROACTIVE_TEMPLATE + AVELINE_TONE_REFERENCE（aveline）或 dialogue_examples（ling）
    4. LLM（MiniMax-M2.5）根据 prompt 生成晚安消息
    5. aveline 生成『哼，说了晚安又不睡。』，ling 生成『说了晚安又不睡。』
*   **预期行为**:
    1. 角色生成的晚安消息应该明确表达『我（角色）要去睡了』的意思，如『晚安，我先睡了』『困了，去睡了』
    2. 两个角色的晚安消息应该有个性化差异，不应该内容几乎一样
    3. 晚安消息不应该出现『说了晚安又不睡』这种指责用户的语义
*   **实际行为**:
    1. aveline 23:00 生成『哼，说了晚安又不睡。』——这是指责用户不睡的语义，不是角色自己要睡
    2. ling 23:30 生成『说了晚安又不睡。』——和 aveline 几乎一样（只少了『哼，』前缀）
    3. 两个角色内容几乎一样，缺乏个性化
*   **根因**:
    1. TASK_GOODNIGHT_PROACTIVE_TEMPLATE 模板约束不够强：只说『你按作息时间准备睡觉了』+『必须包含晚安告别的词』，没有明确『角色自己要睡』vs『指责用户不睡』的语义边界
    2. AVELINE_TONE_REFERENCE 全是『傲娇指责用户不睡』风格（『哼，又熬夜？去睡觉』『你是不是傻，这个点还不睡』），LLM 把『晚安』+『傲娇』+『指责用户不睡』三者融合
    3. LLM（MiniMax-M2.5）训练数据中本身就有『说了晚安又不睡』这种常见晚安探针表达，倾向于生成这种内容
    4. ling 虽然用动态 dialogue_examples 而非 AVELINE_TONE_REFERENCE，但 LLM 在两个角色 prompt 下都生成了几乎一样的内容
*   **修复方案**:
    1. 修改 TASK_GOODNIGHT_PROACTIVE_TEMPLATE：加强『你（角色本人）要去睡了』的语义，加【语义红线】明确禁止『说了晚安又不睡』『你怎么还不睡』『又熬夜』『这个点还不睡』等指责用户不睡的内容
    2. 同步修改 TASK_SLEEP_AGAIN_PROACTIVE_TEMPLATE：加同样的【语义红线】约束
    3. 新增测试用例 test_goodnight_proactive_template_has_semantic_redline：验证两个模板都必须包含语义红线约束
*   **验证**:
    1. `D:\AI\xiaoyou-core\venv_core\Scripts\python.exe -m unittest tests.scripts.active_care.verify_character_goodnight -v`
    2. `D:\AI\xiaoyou-core\venv_core\Scripts\python.exe -m ruff check core\agents\chat_agent_components\persona_system\prompt\active_care_prompts.py tests\scripts\active_care\verify_character_goodnight.py`

### QR-20260718-PEER-CHAT-SLEEP-GUARD 提醒分工协商 peer_chat 触发时未检查角色睡眠状态，角色 SLEEPING 后仍参与做计划对话 (2026-07-18)
*   **问题描述**: 07-17 23:00 aveline 进入 SLEEPING 并给用户发晚安『困了，先去睡了』，但 07-18 00:02 PeerChatScheduler 跨天触发『提醒分工协商』peer_chat，生成剧本里 aveline 说『睡不着 刷会手机』并跟 ling 讨论家务分工（就周五开始，先从厨房开始），跟睡眠状态矛盾。用户反馈角色声明睡了又参与做计划，行为不一致。
*   **复现步骤**:
    1. 07-17 23:00:00 aveline 进入 SLEEPING（prev=fully_awake），触发 trigger_character_goodnight 发『困了，先去睡了。晚安。』给用户A（10001）
    2. 07-18 00:00:00 跨天重置睡眠字段（sleep_manager 日志确认）
    3. 07-18 00:01:47 ReminderAssignmentRegistry 日期变更重置，6 个提醒待分工，PeerChatScheduler 触发协商 peer_chat
    4. 07-18 00:02:00 LLM 生成剧本：aveline 说『睡不着 刷会手机』，ling 说『突然想到明天的提醒还没分工』
    5. 07-18 00:02:08-11 剧本分发：ling 发『这周可能有点忙...能不能下周』给用户A，aveline 发『就周五开始，先从厨房开始』给用户A
*   **预期行为**:
    1. 角色进入 SLEEPING 后，peer_chat（含提醒分工协商）应跳过，不触发角色间对话
    2. needs_negotiation 保持 pending 状态，等角色起床后下一轮 tick 自动触发协商
    3. 剧本内容不应出现『睡不着刷会手机』等跟睡眠状态矛盾的台词
*   **实际行为**:
    1. aveline 23:00 进入 SLEEPING，00:02 仍处于 phase=sleeping（日志 ACTIVE_CARE_CHECKER 确认『当前角色处于睡眠中』）
    2. PeerChatScheduler 仍触发提醒分工协商，生成剧本并分发
    3. 剧本里 aveline 说『睡不着 刷会手机』，跟 SLEEPING 状态矛盾
    4. 用户看到角色声明睡了又参与做计划
*   **根因**:
    1. _try_negotiation_peer_chat（peer_chat_scheduler.py:277-345）检查清单缺少睡眠门禁：只检查 needs_negotiation、待发提醒、用户活跃，没检查 aveline/ling 是否在 SLEEPING
    2. 协商在 engine.py:285 触发后直接 return，跳过普通 peer_chat 的 should_trigger_peer_chat 门禁（后者会检查双方 DND 状态）
    3. generate_peer_script 的 prompt 未注入 role_sleep_states，LLM 不知道角色在睡，生成『睡不着刷会手机』这种矛盾台词
*   **修复方案**:
    1. 在 _try_negotiation_peer_chat 开头（needs_negotiation 通过后）加睡眠门禁：任一角色 phase=SLEEPING 即跳过协商并 return False，保持 needs_negotiation pending 状态等起床后重试
    2. 用 sleep_manager.get_state(role_id).phase 直接检查 SleepManager 状态，不依赖 character_daily engine tick 的 current_activity 同步（避免 2 分钟 tick 间隔的缓存问题）
*   **验证**:
    1. `tests/scripts/verify_peer_chat_sleep_guard.py：模拟 aveline SLEEPING 场景，断言 _try_negotiation_peer_chat 返回 False 且 needs_negotiation 保持 pending`
    2. `tests/scripts/verify_peer_chat_sleep_guard.py：模拟双方都 FULLY_AWAKE 场景，断言正常进入协商流程`

### QR-20260720-SKIP-INTERRUPT-OVERRIDE /打断 命令覆盖 /跳过活动 窗口导致跳过失效 (2026-07-20)
*   **问题描述**: 用户对Ling使用 /skip 想跳过整个学习活动（期望约 30 分钟自由聊天），但发现 /skip 跳过不了活动；改用 /打断 只能获得 5 分钟聊天窗口。期望 /skip 覆盖整个活动剩余时间。
*   **复现步骤**:
    1. 角色Ling处于 STUDYING 活动
    2. 用户发送 /skip，系统回复 action=auto_skipped remaining=2483s（约 41 分钟）
    3. 用户聊天，ReplyPolicy 命中 skip=True remaining=2470s（正常工作）
    4. 用户随后又发送 /打断
    5. /打断 创建新窗口 source=qq_command_interrupt window_seconds=300 skip_activity=False（覆盖了 /skip 的窗口）
    6. 用户继续聊天，ReplyPolicy 命中 skip=False remaining=296s（5 分钟），/skip 效果完全丢失
*   **预期行为**:
    1. /skip 创建的 skip_activity=True 长窗口（覆盖整个活动剩余时间）应该被保留
    2. 后续 /打断 不应该重置 skip_activity 标记和窗口 expire_ts
*   **实际行为**:
    1. /打断 接口无条件调用 activate_manual_interrupt_window
    2. InterruptWindowManager.activate 用新 payload 直接覆盖旧窗口
    3. /skip 的 skip_activity=True 被重置为 False
    4. 窗口 expire_ts 从 2483s 后被重置为 300s（5 分钟）
*   **根因**:
    1. /打断 接口（routers/v1/life.py: interrupt_current_activity）没有检查现有窗口的 skip_activity 标记
    2. InterruptWindowManager.activate 无条件覆盖旧窗口，没有保护 skip_activity=True 的窗口
    3. 两个命令共用同一个 InterruptWindowManager 存储，但 /打断 把 /skip 的状态全部重置
*   **修复方案**:
    1. /打断 接口在 activate 之前先调用 get_manual_interrupt_window 检查现有窗口
    2. 若现有窗口 skip_activity=True，返回 action=already_skipped，不覆盖原窗口，保留 remaining_seconds
    3. handle_activity_interrupt 新增 already_skipped 客户端提示
    4. 新增验证脚本 tests/scripts/qq/verify_skip_not_overridden_by_interrupt.py
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\qq\verify_skip_not_overridden_by_interrupt.py`
    2. `venv_core\Scripts\python.exe -m pytest tests\character_daily\test_manual_interrupt_window.py -v --tb=short`

### QR-20260724-01 睡眠静默消息醒来后未进入上下文 (2026-07-24)
*   **问题描述**: 用户在角色睡觉时发消息（如 05:08 发'小澪晚安mua'），消息被静默累积到 pending。但角色 07:04 醒来发早安主动消息时未提及该消息，13:54 用户发'早安'被动回复时该消息也没进入上下文，角色回复完全不回应昨晚的晚安消息，用户感觉消息石沉大海。
*   **复现步骤**:
    1. 角色睡觉期间（如 05:08）用户发私聊消息，日志显示'接收 <- 私聊'但无角色回复（被静默累积）
    2. 角色醒来（07:04）主动发早安问候，内容完全不提及用户昨晚发的消息
    3. 用户白天（13:54）发'早安'被动回复，角色回复也不提及昨晚的消息
    4. 用户追问'你看不到我给你发的晚安吗'，角色才说'看到了'但记错发送时间，说明消息未进入回复上下文
*   **预期行为**:
    1. 睡眠期间静默累积的 pending 消息，在角色醒来后应进入 LLM 上下文，角色回复能自然回应用户昨晚发的消息内容。
    2. 早安主动消息应能读到 pending，主动提及用户昨晚的消息。
*   **实际行为**:
    1. 07:04 早安主动消息完全不读取 pending，不知道用户昨晚发了消息。
    2. 13:54 被动回复时 pending 已被 cleanup_expired_dnd_pending(600) 误清（05:08 到 13:54 间隔 8h46m 远超 600s），get_pending_messages 返回空，content 未注入昨晚消息。
*   **根因**:
    1. cleanup_expired_dnd_pending 调用时机错误：在 get_pending_messages 之前调用，睡眠 8+ 小时后 pending 被过期清理，醒来后无法注入。
    2. good_morning_proactive 早安主动消息发送链路完全不读取 pending_messages。
*   **修复方案**:
    1. cleanup_expired_dnd_pending 移到 try 块末尾（pending 注入处理后），并加 DND 状态判断跳过睡眠期间的清理。
    2. good_morning_proactive 注入 pending 到 specific_instruction，发送成功后清空。
*   **验证**:
    1. `ruff check 通过`
    2. `pytest baseline 一致（13 failed 与改动前相同，无新增失败）`

### QR-20260728-LING-SCHEDULE-TIMEOUT 双QQ模式下 ling 主动关怀消息未发送（perform_check 超时耗尽预算） (2026-07-28)
*   **问题描述**: 双QQ模式下用户反馈『一直只有 Aveline 在给我发啊，Ling呢』，ling 角色的主动关怀消息没有发送出去
*   **复现步骤**:
    1. 启动双QQ模式（aveline + ling 两个 persona）
    2. 等待 perform_check 触发（每 10 分钟轮询一次）
    3. 观察日志：aveline 的决策流程先执行，耗时较长
    4. 观察 ling 的 proactive_state.json：next_llm_decision_source='perform_check_timeout'
*   **预期行为**:
    1. 双QQ模式下 aveline 和 ling 都能独立发送主动关怀消息
    2. aveline 处理慢不应该影响 ling 的决策流程
*   **实际行为**:
    1. ling 的决策流程被 150s 超时打断，根本没走到 LLM 步骤
    2. aveline 排在前面耗尽预算，ling 在后面被取消
    3. ling 进入饥饿循环：每次 perform_check 都被超时
*   **根因**:
    1. 双QQ模式下两个 persona 顺序处理（proactive_checker.py:328 for 循环），共享同一个 150s 超时预算（proactive_loop.py:75-76）
    2. aveline 处理耗时较长（可能因 deferred_plan_reminders 等），导致 ling 没有时间完成
    3. 超时后 set_next_decision_ts(time.time() + 60) 只设全局，未按 persona 独立设置
*   **修复方案**:
    1. 双QQ模式双 persona 顺序处理改为独立超时：每个 persona 60s 超时（_PER_PERSONA_TIMEOUT=60），互不影响
    2. 超时后继续处理下一个 persona（不 return），避免 ling 饥饿
    3. 超时后设置 persona 下次决策时间（5分钟后重试），避免立即重试再次超时
*   **验证**:
    1. `tests/scripts/active_care/verify_sleep_limit_and_ling_schedule.py 测试 1 通过`

### QR-20260728-SLEEP-MESSAGE-OVERLOAD 用户睡觉时收到太多主动关怀消息（探针+nudge 频率过高） (2026-07-28)
*   **问题描述**: 用户反馈『今天都没起来，他都跟我发了这么多』，睡觉期间收到的主动关怀消息过多
*   **复现步骤**:
    1. 用户晚上 23:00 说晚安，进入睡眠会话（sleep_session_active=true）
    2. 用户睡到第二天 07:00（8小时睡眠）
    3. 观察期间收到的主动关怀消息数量
*   **预期行为**:
    1. 用户睡觉时消息数 ≤ 3 条（用户原话：『发个几条』）
    2. 探针频率合理，不打扰用户睡眠
*   **实际行为**:
    1. 8小时睡眠收到 5-7 条消息：4次探针（每2h一次）+ 1次早安 + 可能的 nudge
    2. 探针频率过高：goodnight_low_disturb_gap_seconds=7200（2h）
    3. next_check_seconds 无硬下限，LLM 可能返回 30s
    4. nudge 在角色夜醒时仍会发送
*   **根因**:
    1. 探针频率过高：goodnight_low_disturb_gap_seconds=7200（2h），8h睡眠产生4次探针
    2. next_check_seconds 无硬下限保护：_normalize_decision_dict 中最小值只有 30s（decision_output_parser.py:217）
    3. nudge 逻辑：用户睡觉+角色夜醒时 allow_nudge=role_night_awake，累积3条提醒就发 nudge（checker_event_handler.py:181-209）
*   **修复方案**:
    1. 降低探针频率：goodnight_low_disturb_gap_seconds 从 7200 改为 14400（4h），8h睡眠探针从4次降到2次
    2. 睡眠期间 next_check_seconds 硬下限 3600s：decision.py 中 sleep_session_active=true 时强制 next_check_seconds >= 3600
    3. nudge 在用户睡觉时不发：checker_event_handler.py 中 allow_nudge=False，提醒累积到用户醒来后统一发送
*   **验证**:
    1. `tests/scripts/active_care/verify_sleep_limit_and_ling_schedule.py 测试 2/3/4 通过`
    2. `8h睡眠探针数从4次降到2次`

### QR-20260730-DAILY-SLEEP-MISRECORD daily_record 作息时间被误识别为聊天时间，且缺少 AI 主动修正工具 (2026-07-30)
*   **问题描述**: AI 在对话中说出'31分钟都没睡够'，但用户实际睡了约9小时（早上7点多睡，下午5点起）。检查 2026-07-30 的 daily_record.json 发现 sleep_cycle 字段被错误填为 sleep=19:29/wakeup=20:00/duration=31m，这是用户与 AI 聊天的时间被误识别成了作息时间。用户要求修复自动记录错误，并希望 AI 能自己修改这个数据。
*   **复现步骤**:
    1. 用户凌晨5点吃猪脚饭，早上7点多睡，下午5点起
    2. AI 误把用户晚上19:29-20:00的聊天时间识别成睡觉/起床时间
    3. _calc_sleep_duration 算出 duration=31m 并展示给 AI
    4. AI 基于错误数据对用户说'31分钟都没睡够'
    5. 用户指出错误后，AI 没有工具能主动修正 sleep_cycle 数据
*   **预期行为**:
    1. _calc_sleep_duration 对异常时长（<1h 或 >16h）返回 None，不展示错误数据
    2. AI 能通过 update_sleep_record 工具主动修正错误的 sleep/wakeup 时间
    3. 修正后的数据会绕过 record_sleep 保护逻辑并同步到 Active Care 状态
*   **实际行为**:
    1. _calc_sleep_duration 把 sleep=19:29/wakeup=20:00 算成 '31m' 显示给 AI
    2. AI 没有修正工具可用，record_sleep 保护逻辑拒绝用 07:00 覆盖 19:29
    3. 用户只能被动等待系统重新记录，无法主动修正历史错误数据
*   **根因**:
    1. _calc_sleep_duration 缺少合理性校验，异常时长直接返回字符串
    2. AI 在解析用户消息时把聊天时间误识别为作息时间
    3. 缺少显式修改工具，仅 record_sleep/record_wakeup 两个间接途径，且都有保护逻辑
*   **修复方案**:
    1. _calc_sleep_duration 添加合理性校验：duration<1h 或 >16h 返回 None（manager.py L237-265）
    2. 新增 DailyActivityManager.update_sleep_cycle 方法，绕过保护逻辑显式修改 sleep_cycle（manager.py L323-369）
    3. 新增 UpdateSleepRecordTool 工具供 AI 调用（daily_tool.py L126-205）
    4. 在 registry.py 注册 update_sleep_record 工具（registry.py L185-196）
*   **验证**:
    1. `D:\AI\xiaoyou-core\venv_core\Scripts\python.exe -m tests.scripts.daily.verify_sleep_record_correction`
    2. `验证脚本包含 12 个测试：合理性校验、update_sleep_cycle 方法、工具异步调用、registry 注册、保护逻辑仍生效`

### QR-20260730-ACTIVE-CARE-PROBABLE-SLEEP-REMOVAL probable_sleep 推断入睡机制不科学，会覆盖 UIE 正确作息数据 (2026-07-30)
*   **问题描述**: AI 说出'31分钟都没睡够'，根因是 probable_sleep 机制把用户聊天时间(19:29-20:00)误识别为睡觉时间并写入 daily_record。该机制通过'用户长时间无响应'推断入睡，但用户可能只是在忙/离开，并非睡觉。系统已有'距上次发言 X 小时'的上下文注入，AI 能自行判断，不需要系统层面猜测入睡。
*   **复现步骤**:
    1. 用户下午18:59最后交互后去做别的事
    2. 系统进入 probable_sleep 模式，推断 sleep_ts = 18:59 + 30分钟 = 19:29
    3. 用户20:00发消息，系统退出 probable_sleep 并调用 _sync_probable_sleep_to_daily_record
    4. 推断的 sleep=19:29/wakeup=20:00 被写入 daily_record，覆盖 UIE 可能的正确数据
    5. _calc_sleep_duration 算出 duration=31m 展示给 AI
    6. AI 基于错误数据对用户说'31分钟都没睡够'
*   **预期行为**:
    1. 系统不应基于'用户长时间无响应'推断入睡并写入作息数据
    2. 作息数据应由 UIE 从用户消息（早安/晚安）抽取，或由 AI 调用 update_sleep_record 工具修正
    3. 夜间降频应依赖 goodnight/sleep_hint + prompt_builder 的上下文注入
*   **实际行为**:
    1. probable_sleep 机制把用户忙/离开误判为睡觉
    2. 退出时调用 _sync_probable_sleep_to_daily_record 覆盖 UIE 正确数据
    3. 该机制深度嵌入 10+ 文件作为 reduced_mode_reason 的一种
*   **根因**:
    1. probable_sleep 通过'用户长时间无响应'推断入睡，逻辑不科学
    2. 退出时无条件同步推断数据到 daily_record，覆盖 UIE 正确记录
    3. 系统已有'距上次发言 X 小时'注入，probable_sleep 属于冗余的技术债
*   **修复方案**:
    1. 彻底移除 probable_sleep 机制（14 个核心文件 + 1 个测试脚本）
    2. 保留 goodnight/sleep_hint 机制（有用户明确意图支撑）
    3. 保留 _try_infer_probable_sleep 方法名以兼容调用签名，但只处理 sleep_hint
    4. goodnight 退出时仍同步作息到 daily_record（sleep_ts 准确）
*   **验证**:
    1. `D:\AI\xiaoyou-core\venv_core\Scripts\python.exe -m tests.scripts.active_care.verify_probable_sleep_removed`
    2. `验证脚本包含 14 个测试：常量移除、方法移除、条件分支移除、模块导入、sleep_hint/goodnight 保留`

### QR-20260801-AC-FALLBACK 未知角色触发 active_care 主动消息 fallback 到 aveline 名义，导致角色精神分裂 (2026-08-01)
*   **问题描述**: aveline 23:00 说晚安后，23:30 又发了一条晚安、00:00 又发起床问候（含语音），用户看到角色反复说晚安/起床像精神分裂。实际这些消息是 xiaolu 触发的，但被误挂到 aveline 名义发出。
*   **复现步骤**:
    1. aveline 23:00 进入 SLEEPING，正确触发晚安消息
    2. xiaolu 23:30 进入 SLEEPING，sleep_manager 无条件调用 trigger_character_goodnight_async
    3. goodnight_proactive._resolve_persona_filename(xiaolu) 命中 fallback 返回 qq/Aveline_QQ_Master.json
    4. 消息以 aveline 名义发到 private_10001__persona__aveline_qq_master 会话
    5. 00:00 跨天 xiaolu 进入 WAKING_UP，同理触发起床问候误挂到 aveline
*   **预期行为**:
    1. 只有接入 active_care 的角色（aveline/ling）触发主动晚安/起床消息
    2. xiaolu/yeye/rushuang/mianmian 不触发任何主动消息
    3. 未知 role_id 不应 fallback 到 aveline
*   **实际行为**:
    1. sleep_manager 对所有角色无条件触发主动消息
    2. _resolve_persona_filename 对未知 role_id fallback 到 qq/Aveline_QQ_Master.json
    3. xiaolu 的晚安/起床消息以 aveline 名义发出，污染 aveline 会话历史
    4. aveline 的 non_responses 计数被污染（Mood degraded due to 3 non-responses）
*   **根因**:
    1. sleep_manager._on_enter_sleeping/_on_enter_waking_up 无白名单过滤
    2. goodnight_proactive/good_morning_proactive/activity_return 的 _resolve_persona_filename 对未知 role_id fallback 到 aveline
    3. engine.py 注释明确写了 yeye/xiaolu 不接 active_care，但 sleep_manager 未遵守
*   **修复方案**:
    1. sleep_manager 新增 _ACTIVE_CARE_ENABLED_ROLES 白名单，两个钩子入口过滤非白名单角色
    2. 三个 _resolve_persona_filename 改为返回 Optional[str]，未知角色返回 None
    3. 三个调用方加 None 检查，跳过发送
    4. 清理 aveline 会话中 2 条污染消息（id=b1a10200, id=017fadd3）
*   **验证**:
    1. `tests/scripts/active_care/verify_unknown_role_no_fallback.py`
    2. `py_compile 全部通过`
    3. `扫描确认无残留污染消息`

### QR-20260801-WAKEUP-DND ReplyPolicy waking_up 阶段 DND 静默导致用户回复被累积 + good_morning_proactive 早安消息英文乱码 (2026-08-01)
*   **问题描述**: 角色进入 WAKING_UP 状态时主动发送了早安消息（good_morning_proactive），但用户回复时 ReplyPolicy 判定 activity=waking_up（DND），走 dnd_sleeping_silent 分支静默累积消息，导致角色主动发完早安后反而把用户回复静默 1 小时。同时早安消息内容为英文 'Morning. $$ You up yet?' 含 $$ 乱码符号。
*   **复现步骤**:
    1. 角色按作息进入 WAKING_UP 状态，sleep_manager 触发 good_morning_proactive 发送早安消息
    2. 用户收到早安消息后回复（如 '小澪你怎么一大早起来说英文'）
    3. 后端 chat_handlers 调用 evaluate_reply_state，activity=waking_up（DND），ac_sleeping=False
    4. reply_policy 走 _evaluate_dnd 分支，random.random() < wake_prob 未命中，返回 should_reply=False 静默累积
*   **预期行为**:
    1. 角色主动发完早安消息后，用户回复应正常走 LLM 回复（should_reply=True）
    2. 早安消息应为自然中文，符合人设语气，不含英文句子或 $$ 等特殊符号
*   **实际行为**:
    1. ReplyPolicy 返回 dnd_sleeping_silent(activity=waking_up, ac_sleeping=False) count=1, will_process_on_wake，用户回复被静默累积
    2. 早安消息内容为 'Morning. $$ You up yet? / It's Saturday, / no rush'，英文 + $$ 乱码
*   **根因**:
    1. engine.py _update_current_activity 的 is_conscious = phase in {fully_awake, night_awake}，未包含 waking_up；waking_up 阶段 is_conscious=False，DND 计划槽位不改为 IDLE
    2. waking_up 持续 1 小时（sleep_manager 中 elapsed > 3600 才转 fully_awake），期间 DND 静默与 good_morning_proactive 主动发消息行为矛盾
    3. good_morning_proactive._build_specific_instruction 缺少强制中文约束，LLM 跑偏输出英文和 $$ 符号
*   **修复方案**:
    1. engine.py：is_conscious 加入 waking_up（phase in {fully_awake, night_awake, waking_up}），waking_up 阶段 DND 计划改为 IDLE
    2. good_morning_proactive.py：_build_specific_instruction 开头加入【语言与格式硬约束】强制中文、禁止英文和 $$ 等特殊符号
*   **验证**:
    1. `ruff check engine.py good_morning_proactive.py 通过`
    2. `重启后端后角色发早安消息，用户回复走 idle/free 正常回复`
    3. `早安消息为自然中文，无英文和 $$ 乱码`

### Q-20260803-01 睡回去消息后端日志显示已实时送达但 QQ 客户端收不到（activity_return persona 映射错误） (2026-08-03)
*   **问题描述**: Aveline 半夜被 /wake 叫醒后聊了几句，sleep_manager 决策睡回去并触发 sleep_again_proactive 消息『被你吵醒了...我继续睡去了』。后端日志记录『主动消息已实时送达: conversation=private_10001__persona__core_aveline』，但用户在 QQ 上完全没收到这条消息。
*   **复现步骤**:
    1. 凌晨用 /wake 唤醒 aveline（night_awake 状态）
    2. 和 aveline 聊几句后静默，sleep_manager 3 分钟静默窗口结束决策睡回去
    3. sleep_manager 调用 trigger_character_goodnight(is_sleep_again=True)
    4. is_sleep_again=True 改走 send_activity_return_message 统一模块
    5. 统一模块用 activity_return/instruction.resolve_persona_filename 拿到 core_aveline.json
    6. executor 构建 conversation_id=__persona__core_aveline 并 broadcast
    7. QQ receiver dual QQ 校验：expected=__persona__aveline_qq_master ≠ target → 丢弃
*   **预期行为**:
    1. 用户在 QQ 上收到 Aveline 的睡回去告别消息『被你吵醒了...我继续睡去了』
*   **实际行为**:
    1. 后端日志显示『主动消息已实时送达』（因 ws_manager.is_user_online 只看 WS 连接是否活着）
    2. QQ 客户端实际没收到，receiver.py debug 日志记『Ignoring proactive_message: persona mismatch』
*   **根因**:
    1. activity_return/instruction.py 的 _ROLE_PERSONA_MAP 映射到 core_aveline.json，与 goodnight_proactive/good_morning_proactive 的 qq/Aveline_QQ_Master.json 不一致
    2. goodnight_proactive 注释明确说必须用 QQ 人设否则被 receiver 丢弃，但 is_sleep_again=True 路径委托给统一模块时未带入正确人设
*   **修复方案**:
    1. activity_return/instruction.py 的 _ROLE_PERSONA_MAP 改为 qq/Aveline_QQ_Master.json/qq/Ling_QQ_Master.json
    2. 同步更新 verify_activity_return.py 与 verify_unknown_role_no_fallback.py 断言
    3. 新增 verify_sleep_again_persona_match.py 端到端验证 conversation_id 与 QQ receiver 期望一致
*   **验证**:
    1. `D:\AI\xiaoyou-core\venv_cpu\Scripts\python.exe tests/scripts/active_care/verify_sleep_again_persona_match.py`
    2. `D:\AI\xiaoyou-core\venv_cpu\Scripts\python.exe tests/scripts/active_care/verify_unknown_role_no_fallback.py`
    3. `D:\AI\xiaoyou-core\venv_cpu\Scripts\python.exe -m pytest tests/scripts/character_daily/verify_activity_return.py -q`

### QR-20260803-WAKE-DND /wake 后 waking_up 状态下中断窗口失效导致静默累积 (2026-08-03)
*   **问题描述**: 用户 /wake 后发消息，角色仍走 dnd_sleeping_silent 静默累积分支不回复。日志显示 wake API 已激活中断窗口（'已自动激活中断窗口 conv=private_10001__persona__aveline_qq_master'），但 reply_policy 仍输出 'dnd_sleeping_silent(activity=waking_up) count=2, will_process_on_wake'。
*   **复现步骤**:
    1. 角色处于 waking_up 状态（DND 过渡态）
    2. 用户发送 /wake，wake API 走 DND 分支激活中断窗口（source=wake_auto_interrupt_dnd）
    3. 用户发消息，chat_handlers 调用 evaluate_reply_state
    4. reply_policy 读取到中断窗口，但条件 activity not in DO_NOT_DISTURB_ACTIVITIES 为 False（waking_up 是 DND），跳过中断窗口分支
    5. 走到 DND 分支 _evaluate_dnd，返回 should_reply=False 静默累积
*   **预期行为**:
    1. /wake 激活中断窗口后，用户发消息应走中断窗口分支正常回复（should_reply=True）
    2. 中断窗口期间角色陪伴聊天，窗口快结束时提示该回去做事了
*   **实际行为**:
    1. 中断窗口被 activity not in DO_NOT_DISTURB_ACTIVITIES 条件挡住
    2. 退回 DND 静默累积分支，should_reply=False，用户消息无回复
*   **根因**:
    1. reply_policy.py 第 206-210 行中断窗口分支条件 `activity not in DO_NOT_DISTURB_ACTIVITIES` 错误排除 waking_up/napping/overslept_recovery 等 DND 过渡态
    2. /wake 激活中断窗口的目的就是让 DND 状态下也能聊天，该条件与 /wake 语义冲突
*   **修复方案**:
    1. 条件改为 `activity != ActivityType.SLEEPING and not ac_sleeping`，允许 DND 过渡态走中断窗口分支，仅排除 SLEEPING（防御性）
*   **验证**:
    1. `d:\AI\xiaoyou-core\venv_core\Scripts\python.exe -m pytest tests/character_daily/test_manual_interrupt_window.py -v`
    2. `3 个测试全部通过：test_manual_interrupt_window_allows_busy_chat / test_manual_interrupt_window_does_not_bypass_sleeping / test_wake_interrupt_window_allows_waking_up_chat`

### QR-20260803-INTERRUPT-WINDOW-PERSISTENCE InterruptWindowManager 无持久化导致 backend 重启后 /跳过 / /打断 窗口丢失 (2026-08-03)
*   **问题描述**: 用户 /跳过 后 backend 重启，重启后用户发消息，角色走 busy_defer_silent 静默累积不回复。日志：'ReplyPolicy: 忙碌延后处理，静默累积消息 (busy_defer_silent(activity=studying) count=2, will_process_on_done))'。
*   **复现步骤**:
    1. 用户发送 /跳过，activate 创建 skip=True 长窗口（覆盖活动剩余时间）
    2. backend 重启（改代码/手动重启/崩溃恢复），InterruptWindowManager 单例重新初始化，_windows 清空
    3. 用户发消息，chat_handlers 调用 evaluate_reply_state
    4. reply_policy 读取 manual_interrupt_window 返回 None（内存已清空）
    5. 跳过中断窗口分支，走到 _evaluate_busy 返回 busy_defer_silent 静默累积
*   **预期行为**:
    1. /跳过 后即使 backend 重启，中断窗口仍应存在
    2. 用户发消息应走中断窗口分支正常回复（should_reply=True, skip=True）
*   **实际行为**:
    1. 重启后 InterruptWindowManager._windows 为空
    2. get_manual_interrupt_window 返回 None
    3. reply_policy 走 busy_defer_silent 静默累积，should_reply=False
*   **根因**:
    1. InterruptWindowManager 是纯内存 dict，无任何持久化机制
    2. activate/extend/mark_skip_activity/clear 时只更新内存，未写盘
    3. 启动时未从磁盘加载历史窗口
*   **修复方案**:
    1. 新增持久化文件 companion_data/character_daily/interrupt_windows.json
    2. activate/extend/mark_skip_activity/clear/mark_window_ending_notified 写盘（safe_json_dump use_fsync=True）
    3. __init__ 时 _load_from_disk 恢复未过期窗口
*   **验证**:
    1. `d:\AI\xiaoyou-core\venv_core\Scripts\python.exe tests/scripts/character_daily/verify_interrupt_window_persistence.py`
    2. `验证脚本 4 个步骤全部通过：activate 写盘 / 重启恢复 / reply_policy 命中 / 过期窗口过滤`

### QR-20260804-01 角色按作息入睡时晚安消息被间隔保护拦截 (2026-08-04)
*   **问题描述**: 用户反馈当日未收到 AI 角色的晚安消息。排查发现角色 aveline 于 23:00 按作息时间入睡并触发 goodnight_proactive 主动消息，但被 executor 重叠间隔保护拦截（guard=2400s，距上次触发仅 583s），导致晚安消息未发送。
*   **复现步骤**:
    1. 角色 aveline 在 22:50 左右因用户消息触发过一次主动关怀
    2. 23:00:00 aveline 按作息时间进入 SLEEPING 状态，触发 goodnight_proactive
    3. executor._check_overlap_guard 判定距上次触发 583s < 2400s，拦截消息
    4. 日志记录 'Trigger skipped to avoid overlap' 与 '晚安消息未发送'
*   **预期行为**:
    1. 角色按作息时间首次入睡时，goodnight_proactive 晚安消息应正常发送给用户
    2. 作息事件触发的必要通知不应受普通主动消息间隔保护约束
*   **实际行为**:
    1. goodnight_proactive 被 2400s 间隔保护拦截，用户未收到晚安
    2. sleep_again_proactive（睡回去）已豁免，但 goodnight_proactive（首次入睡）未豁免
*   **根因**:
    1. executor._check_overlap_guard 的豁免列表遗漏 goodnight_proactive
    2. 该方法是作息事件通知的统一豁免入口，但首次入睡晚安未被纳入
*   **修复方案**:
    1. 在 executor.py _check_overlap_guard 豁免列表加入 goodnight_proactive
    2. 更新注释说明三类作息事件通知（activity_return/sleep_again/goodnight）均豁免
*   **验证**:
    1. `重启后端，观察角色下次入睡时晚安是否成功发送`
    2. `grep 'Trigger skipped to avoid overlap' 确认不再拦截 goodnight_proactive`

### ISSUE-20260804-AC-GOODMORNING-LANGGUARD good_morning_proactive 起床问候 NameError: lang_guard 未定义 (2026-08-04)
*   **问题描述**: 角色 ling 主动起床问候失败，NameError: name 'lang_guard' is not defined。位于 _build_specific_instruction 函数中 f"{lang_guard}\n" 处使用 lang_guard 但函数内从未定义该变量。
*   **复现步骤**:
    1. 触发 trigger_character_good_morning（角色进入 WAKING_UP 状态时）
    2. 调用 _build_specific_instruction(role_id, is_stay_up_recovery)
    3. 函数内 f"{lang_guard}\n" 引用未定义变量 → NameError
*   **预期行为**:
    1. 起床问候 specific_instruction 正常构建并发出
*   **实际行为**:
    1. NameError: name 'lang_guard' is not defined，导致 active_care 起床问候流程中断
*   **根因**:
    1. _build_specific_instruction 函数体内引用了未定义的局部变量 lang_guard
*   **修复方案**:
    1. 在文件顶部从 core.agents.chat_agent_components.persona_system.prompt.active_care_prompts 导入 LANGUAGE_GUARD_ZH
    2. 在 _build_specific_instruction 函数内赋值 lang_guard = LANGUAGE_GUARD_ZH（起床问候固定走中文）
*   **验证**:
    1. `D:\AI\xiaoyou-core\venv_core\Scripts\python.exe -c "from core.services.active_care.good_morning_proactive import _build_specific_instruction; print(_build_specific_instruction('ling', False)[:120])"`

### QR-20260804-AC-MAIN-REPLY-ANCHOR Active Care 在主程序已回复用户后仍重新回应用户消息而非顺着主程序回复继续 (2026-08-04)
*   **问题描述**: active care 在主程序（chat agent）已经回复过用户最后一条消息后，再次触发时仍把用户那条消息当作'待跟进'目标，导致 active care 重新回应用户，而不是接着主程序的回复继续往下说。
*   **复现步骤**:
    1. 02:42:40 active care 主动消息 '赶紧去睡觉，不许' (is_proactive=True)
    2. 02:43:16 用户回复 '不许什么'
    3. 02:43:27 主程序回复 '不许再试了听不懂吗...' (is_proactive=False)
    4. 02:50:22 active care 再次触发，错误地回 '不许什么你自己想去'（重新回应用户），而非顺着主程序回复继续
*   **预期行为**:
    1. active care 应顺着主程序的回复（'不许再试了听不懂吗...'）继续往下说
    2. 不应重新回应用户那条'已被主程序回复过'的消息
*   **实际行为**:
    1. active care 把用户消息 '不许什么' 当作待跟进目标（build_follow_up_input）
    2. 生成的回复 '不许什么你自己想去' 是在回答用户的旧问题，忽略主程序已给出的回复
*   **根因**:
    1. build_model_user_input_for_active_care 的 is_last_from_main_chat 分支无条件把 continuation_anchor 置空
    2. 置空后流程落到 build_follow_up_input(last_user_message)，让 LLM 跟进一条已被主程序回复过的用户消息
    3. 缺少对'主程序回复时间 vs 用户最后消息时间'的判断，无法区分两种场景
*   **修复方案**:
    1. input_builder.py 新增 last_assistant_after_user 参数
    2. 当主程序回复晚于用户最后消息时，把主程序回复作为延续锚点（build_continuation_input）
    3. context_builder.py 计算 last_assistant_after_user = last_assistant_ts > last_user_ts_raw 并传递
*   **验证**:
    1. `D:\AI\xiaoyou-core\venv_cpu\Scripts\python.exe tests\scripts\active_care\verify_main_chat_reply_anchor.py`

### QR-20260805-PEER-CHAT-FILTER-MISSING peer chat 互聊剧本缺话（filter_script 误杀短回复 + 日志混在 active_care 中） (2026-08-05)
*   **问题描述**: peer chat 历史记录里出现角色连续发言缺少交替回复的现象（如一方说『XX』后另一方应回『没有，你呢』才接续电影话题，但实际缺这句），排查时发现 peer chat 没有独立日志，全混在 active_care_schedule.log / ACTIVE_CARE_EXECUTOR 里。
*   **复现步骤**:
    1. 查看 peer chat 历史对话，发现角色间出现『缺话』
    2. grep peer chat 相关日志，发现日志分散在 active_care_schedule.log、ACTIVE_CARE_EXECUTOR、NEGOTIATION_PARSER、PROACTIVE_PARSER 多个 logger 中
    3. 定位到 PeerChatManager.filter_script 对短回复有过滤逻辑
*   **预期行为**:
    1. peer chat 剧本应保留正常短回复，角色交替发言完整
    2. peer chat 应有独立日志文件，便于排查
*   **实际行为**:
    1. filter_script 中 len(raw) < 6 的阈值误杀『没啊，怎么』等正常短回复，破坏对话交替性
    2. peer chat 日志混在 active_care 主流程日志里，排查困难
*   **根因**:
    1. filter_script 阈值设计不合理，短回复被误判为不完整片段
    2. peer chat 模块复用 active_care logger，未独立成文件
*   **修复方案**:
    1. 删除整个 filter_script 功能（用户判断其价值不高），仅保留 calc_message_delay
    2. 清理 peer_chat_metrics 中废弃指标 scripts_filtered_empty / lines_filtered
    3. 新增 peer_chat.log，9 个 peer_chat 相关模块统一迁移到 PEER_CHAT / PEER_CHAT_SCHEDULER logger
*   **验证**:
    1. `tests/scripts/active_care/verify_peer_chat_log_separation.py`
    2. `python -c "import clients.bots.qq.peer_chat; import core.services.active_care.peer_chat.peer_script_dispatch; ..."`

### QR-20260807-TG-GHOST Telegram 禁用后 active_care 仍往 tg_ cid 写幽灵主动消息 (2026-08-07)
*   **问题描述**: telegram_config.json enabled=false，但 companion_data/aveline_data/chat_history/2026/08/07/主线对话/tg_6867233990.jsonl 仍被持续写入（今早 5 条 proactive_message，source=active_care）。用户 tg 端默认关闭，这些消息送达不到任何客户端，只是把本地历史越写越脏。
*   **复现步骤**:
    1. 查看 tg_6867233990.jsonl，确认 5 条全是 proactive_message（metadata.source=active_care），无用户消息
    2. 查看 clients/bots/telegram/telegram_adapter.log，确认今天(08-07)无任何记录，adapter 未启动
    3. 查看 conversation_labels.py:37，发现 is_external_or_internal_conversation_id 前缀元组漏了 tg_
    4. 查看 adapter.py:108，确认 Telegram session_id 用 tg_{chat_id} 格式
    5. 查看 conversation_resolver.py 的 get_recent_conversation_ids_from_chat_history + _resolve_primary_conversation_id_uncached，确认候选收集与最新时间戳选择逻辑
    6. 查看 adapter.py:1120 run()，确认只检查 TELEGRAM_BOT_TOKEN 不检查 ENABLED
*   **预期行为**:
    1. telegram_config.json enabled=false 时，不应再生成任何 tg_*.jsonl 文件
    2. active_care 不应把 tg_ cid 选为 primary 用户会话
    3. Telegram adapter 在 enabled=false 时不应启动
*   **实际行为**:
    1. enabled=false 但 08-07 仍生成 tg_6867233990.jsonl（5 条 active_care 主动消息）
    2. is_primary_user_conversation_id('tg_6867233990') 错误返回 True，active_care 把它当 primary
    3. 昨天(08-06) adapter 在 enabled=false 时仍在跑（日志有真实用户消息），enabled 开关形同虚设
*   **根因**:
    1. conversation_labels.py 前缀元组漏 tg_，导致 tg_ cid 被误判为主用户会话
    2. conversation_resolver 从历史 index.json 收集候选并选最新时间戳，昨天的 tg_ 文件最新故被选中
    3. adapter.py run() 未检查 ENABLED，只检查 token
*   **修复方案**:
    1. conversation_labels.py:37 前缀元组加入 'tg_'
    2. adapter.py 导入并检查 ENABLED，run() 开头 if not ENABLED: return
    3. ChatHistoryStore.delete_conversation 删除 2 个脏 jsonl + 重建 6 个 index.json
*   **验证**:
    1. `tests/scripts/active_care/verify_tg_ghost_fix.py 19/19 通过`
    2. `is_primary_user_conversation_id('tg_6867233990')==False`
    3. `清理后 tg_6867233990.jsonl 残留 0`

### AC-081 Active Care 主动消息无法送达 QQ（shared base 路由失效） (2026-08-09)
*   **问题描述**: 用户连着 QQ，但今天没收到任何 active care 主动关怀消息，后端却显示多次触发且「已实时送达」
*   **复现步骤**:
    1. QQ 适配器正常运行，用户 06:39 能正常聊天（小澪早安有回复）
    2. 后端 active_care_schedule.log 显示 08:56、09:12、09:40、10:49、10:57、11:11 多次 trigger_message 并 dispatch
    3. 后端日志显示「主动消息已实时送达: conversation=private_123456789」
    4. QQ 适配器 qq_adapter.log 今天 0 条「接收并处理主动关怀消息 (proactive_message)」记录
*   **预期行为**:
    1. QQ 端收到 active care 主动关怀消息
    2. QQ 适配器日志记录「接收并处理主动关怀消息」
*   **实际行为**:
    1. QQ 端 0 条 active care 消息
    2. QQ 适配器日志今天无 proactive_message 处理记录
*   **根因**:
    1. build_persona_conversation_id 改用 shared base，receiver persona 匹配未同步（base_cid shared != session_id private_xxx）
    2. probe_client_type 优先返回 websocket，active care 不走 QQ persona 路由，target 退化
    3. broadcast_user_id 未定义（运行旧代码）
    4. peer_script_dispatch 未传 original_primary_conversation_id，peer_chat 广播 shared 进离线队列
*   **修复方案**:
    1. receiver.py 放宽 shared base 匹配（base_cid == session_id or base_cid == 'shared'）
    2. client_utils.py probe_client_type 优先 QQ
    3. proactive_messaging.py 定义 broadcast_user_id
    4. peer_script_dispatch.py 传 original_primary_conversation_id=base_cid
*   **验证**:
    1. `重启后端 + QQ 适配器后观察 active_care_schedule.log 与 qq_adapter.log`

### AC-083 peer_chat_scheduler.is_user_sleeping 使用未定义变量 role_ids (2026-08-10)
*   **问题描述**: 日志出现 'PeerChatScheduler: is_user_sleeping 检查异常: name role_ids is not defined'
*   **复现步骤**:
    1. 08-10 07:04:00 peer_chat 触发时调用 is_user_sleeping
    2. 函数内 for scope in role_ids 但 role_ids 从未定义，抛 NameError
*   **预期行为**:
    1. is_user_sleeping 返回用户的睡眠状态，不抛异常
*   **实际行为**:
    1. 抛 NameError，masked 为 warning 日志
*   **根因**:
    1. 重构时遗漏了 role_ids 的来源，函数签名无参数但函数体引用了局部不存在的 role_ids
*   **修复方案**:
    1. 从 _get_multi_qq_connections() 获取可参与互聊角色列表作为 role_ids
*   **验证**:
    1. `不再出现 is_user_sleeping 检查异常`

### QR-20260814-DW-FALSEPOSITIVE 数字健康时间检测不准并误触发 active care 超额通知 (2026-08-14)
*   **问题描述**: 数字健康模块在用户未使用目标 app 时仍发送时间超额的 active care 通知，且使用时长检测只显示几分钟却判定超额；超额后也未通过 Shizuku 强制停止目标 app。
*   **复现步骤**:
    1. 用户在 Android 端正常使用 app，数字健康模块后台运行
    2. 用户并未使用被限额的目标 app（或仅使用几分钟）
    3. 后端 active care 主动推送时间超额通知
    4. 实际超限后 Shizuku 未强退目标 app
*   **预期行为**:
    1. 使用时长应准确聚合同包名多个 UsageStats bucket
    2. 仅在用户最近确实在使用目标 app 时才触发超额 active care
    3. 下发限额应优先使用今日限额，明日限额仅兜底
    4. 超限后应通过 Shizuku 强制停止目标 app；Shizuku 不可用时应通知用户
*   **实际行为**:
    1. 使用时长被拆分到多个 bucket 未合并，显示偏低
    2. 无 last_used_time，recent_active 检查失效，未使用也触发 active care
    3. next_day 限额覆盖 today，用明日限额判定今日用量产生误判
    4. Shizuku 不可用时静默失败，用户无感知
*   **根因**:
    1. ContextRepositoryImpl 未按 packageName 聚合 UsageStats，totalTimeInForeground 被拆分
    2. get_exceeded_apps 未返回 last_used_time，recent_active 检查拿不到数据
    3. context_device.py 下发限额时 next_day 覆盖了 today
    4. Python 3.10 datetime.fromisoformat 不支持 Z 后缀，时间解析失败回退 None
    5. UsageLimitMonitor Shizuku 失败仅 log warning
*   **修复方案**:
    1. ContextRepositoryImpl.kt 按 packageName groupBy 后合并 totalTimeInForeground / lastTimeUsed
    2. service.py get_exceeded_apps 返回 last_used_time，新增 _parse_last_used_time 稳健解析（兼容 Z 后缀、naive/aware）
    3. service.py maybe_notify_exceeded_via_active_care 用 last_used_time 做 recent_active 判断
    4. context_device.py 调整迭代顺序 (next_day_str, today_str)，today 优先覆盖
    5. UsageLimitMonitor.kt Shizuku 不可用时弹系统通知并按天去重
*   **验证**:
    1. `ruff check + py_compile 通过`
    2. `待真机回归：超限强退、未使用不触发 active care`

### AC-2026-08-14-01 MDP 被 must_probe 架空导致动作选择失效 + activity 挂机误判忙碌 (2026-08-14)
*   **问题描述**: 用户反馈 active care 启用 MDP 算法第一天后几乎没主动发消息
*   **复现步骤**:
    1. 查看 logs/2026/8/14/active_care_schedule.log
    2. 搜索 MDP 探索/利用日志发现 0 条
    3. 搜索 select_action 计时仅 5 次，且全走 Priority probe mode
    4. 查看 activity detection 记录，10:00-16:56 全为 yuanshen.exe gaming busy=True level=0.90
*   **预期行为**:
    1. MDP 启用后应按 Q 表学习反馈选择动作(探索/利用)，主动关怀消息按用户回复偏好发送
*   **实际行为**:
    1. MDP select_action 从未被调用，Q 表白学
    2. 所有决策动作被 must_probe 硬编码为 curious_question
    3. 原神挂机时 activity gate 0.10 软拦截漏发消息
*   **根因**:
    1. decision_executor.select_action 的 must_probe 分支直接 return curious_question，绕过 _select_mdp_or_bandit
    2. activity_detector 无挂机检测，前台 gaming 进程即使人离开也判 busy
*   **修复方案**:
    1. must_probe 分支改为调用 _select_mdp_or_bandit(probe_actions)，probe_actions 排除 do_nothing
    2. activity_detector 加 _get_idle_seconds(GetLastInputInfo) + IDLE_THRESHOLD_SECONDS=300s，挂机降级 idle
*   **验证**:
    1. `tests/scripts/active_care/verify_mdp_not_bypassed.py  # 6 passed, 0 failed`

### QR-20260815-AC-DONE-PENDING 做事期间累积消息不主动回复 + 回归消息 LLM 没真判断挽留 (2026-08-15)
*   **问题描述**: 用户反馈两个体验问题：1）角色做事时收到消息，按理说做完事休息时该回复，但实际没回；2）回归消息几乎每次过一会就发'回去做事'，跟没让 LLM 判断一样。
*   **复现步骤**:
    1. 用户跟角色聊天，角色被打断/打断后做事
    2. 角色做事期间用户发消息（处于 BUSY 状态，reply_policy._evaluate_busy 走 busy_defer_silent 静默累积）
    3. 角色做完事切换到 CHAT_ELIGIBLE 活动（如 idle/reading）
    4. 观察：用户没收到任何主动回复消息
    5. 另外场景：日常计划活动切换频繁（学习/做饭每 1-2 小时切一次），用户在聊天窗口内时每次切换都收到'回去做事'消息
*   **预期行为**:
    1. 角色做完事切回可聊天活动时，应主动通过 active_care 主动管线把做事期间累积的消息发回去（不依赖用户再发新消息触发）
    2. 回归消息 instruction 应让 LLM 真判断用户是否在挽留：在挽留就顺延再陪一会儿，不在挽留才明确道别说要回去
    3. 不应每次活动切换都强行说'回去做事'
*   **实际行为**:
    1. 做事结束切换到可聊天活动时，没有任何主动触发器把累积消息发回去——_DND_PENDING 的累积只在用户再发新消息时才会被 build_after_activity_done_hint 注入到下一条用户消息上下文
    2. _WORK_RETURN_TEMPLATE 用'必须明确提到你要回去继续做什么 + 不要提问'强约束 LLM，LLM 没有真判断'该不该回去'的空间
*   **根因**:
    1. reply_policy._evaluate_busy 把消息静默累积到 _DND_PENDING 后没有'做事结束'的主动触发器；engine._tick 只在活动切换时调用 check_and_send_farewell_on_transition 发告别消息，没有对称的'做事结束主动处理累积消息'逻辑
    2. _WORK_RETURN_TEMPLATE 强约束 LLM 必须说'回去继续 XX'，等同于把判断空间写死，LLM 只是被规定怎么说回去而不是真判断
*   **修复方案**:
    1. chat_reply_runtime.py: append_pending_message 加 role_id 参数，_DND_PENDING 新增 role_id 字段；新增 get_pending_by_role_id 按 role 反查累积消息
    2. chat/reply_policy.py: 3 处 append_pending_message 调用补传 reply_role_id
    3. instruction.py: 新增 build_busy_done_active_instruction 构建'做事结束主动回应累积消息'的 specific_instruction
    4. activity_transition.py: 新增 check_and_process_pending_on_activity_done，在 BUSY→CHAT_ELIGIBLE 切换时主动通过 active_care 主动管线发回做事期间累积的消息，发送后清空避免二次注入；DND 累积跳过留给 morning_after；带去重冷却和最小条数过滤
    5. engine.py _tick: 在 farewell 之后调用新函数
    6. character_daily_config.py: ReplyPolicyConfig 新增 activity_done_pending_process_enabled / activity_done_pending_min_count / activity_done_pending_cooldown_seconds 配置项及 yaml 加载
    7. instruction.py: _WORK_RETURN_TEMPLATE 改为挽留 vs 道别两条判断分支，去掉强约束
    8. instruction.py: _ACTIVITY_START_FAREWELL_TEMPLATE 增强挽留判断分支
*   **验证**:
    1. `venv_core/Scripts/python.exe -m unittest tests.scripts.character_daily.verify_activity_done_pending -v  # 18 tests OK`

### 回归消息决策 角色到点就发“回去做事”消息，不判断用户是否挽留 (2026-08-16)
*   **问题描述**: 角色到点就发“回去做事”消息，从不判断用户是否过挽留，机械定时发送
*   **复现步骤**:
    1. 用户与角色聊天，角色开启一段做事活动
    2. 到达预定回归时间
    3. 角色到点强发“回去做事”消息，即使用户还在挽留
*   **预期行为**:
    1. 发送前 LLM 依据最近对话氛围判断：用户在挽留则顺延不发送，否则正常道别
*   **实际行为**:
    1. 强制发送，LLM 只生成文案不决定是否该回去
    2. 指令模板还强制要求“必须提到要回去”，无法顺延
*   **根因**:
    1. send_activity_return_message 直接 trigger_message 强制发送，无决策步骤
    2. 回归模板是强约束，未给 LLM 挽留判断空间
*   **修复方案**:
    1. 新增 _decide_work_return_should_defer，发送前让 LLM 判断 defer；顺延则延长中断窗口并重新调度，否则正常发送
    2. 重写回归模板，增加挽留 vs 道别判断分支
*   **验证**:
    1. `verify_activity_done_pending.py 新增 6 个顺延决策用例全部通过`

### 回归消息决策 角色做事时累积的消息，做事结束后不主动回复 (2026-08-16)
*   **问题描述**: 用户角色做事时发消息，角色做完事休息后不主动回复，消息石沉大海
*   **复现步骤**:
    1. 角色进入做事活动（BUSY）
    2. 用户此时发消息，消息被标记为累积
    3. 角色做完事切回空闲（CHAT_ELIGIBLE）
    4. 角色未主动回复累积消息
*   **预期行为**:
    1. 角色从忙碌切到可聊天时，主动处理做事期间累积的用户消息
*   **实际行为**:
    1. 切换时未触发累积消息处理，消息不回复
*   **根因**:
    1. 活动切换逻辑未在 BUSY→CHAT_ELIGIBLE 时主动处理累积消息
*   **修复方案**:
    1. 新增 check_and_process_pending_on_activity_done，在切换时按角色查询累积消息并主动回复
    2. append_pending_message 增加 role_id，新增 get_pending_by_role_id 按角色反查
*   **验证**:
    1. `verify_activity_done_pending.py 覆盖累积查询、触发、去重、冷却、disabled 等用例全部通过`

### QR-20260816-001 角色说晚安被误判为用户入睡导致日记提前生成 (2026-08-16)
*   **问题描述**: 15号日记在23:21提前生成，聊天记录不完整；用户23:10-23:57仍在与Aveline对话。用户反映“Aveline给我说了晚安，但他睡觉跟我睡觉有什么关系呢，而且我后面把他叫起来了”。
*   **复现步骤**:
    1. 角色（Aveline/Ling）按自身作息进入 SLEEPING，goodnight_proactive 主动发晚安
    2. 下一轮 proactive_checker.perform_check 通过 extract_latest_assistant_goodnight 检测到助手晚安
    3. is_assistant_goodnight=True 绕过配置强制写入 reduced_mode_active=True / reduced_mode_label=sleep
    4. nightly_processor.check_user_sleeping() 判定用户入睡，1小时后触发日记生成
*   **预期行为**:
    1. 只有用户真实入睡（用户说晚安 / sleep_hint+沉默）才触发睡眠感知调度与日记生成
    2. 角色按作息睡觉并说晚安，不应影响对用户睡眠状态的判定
    3. 用户之后继续交互时，不应已提前生成日记
*   **实际行为**:
    1. 角色22:02入睡并说晚安，系统22:04判定用户入睡，23:21提前生成日记
    2. 用户23:10-23:57持续对话，日记却已生成，内容不完整
*   **根因**:
    1. proactive_checker 把助手晚安注入为用户晚安意图（is_assistant_goodnight=True）
    2. _try_enter_goodnight_on_intent 对助手晚安绕过配置开关强制进入睡眠会话
    3. 角色睡眠与用户睡眠共用 reduced_mode=sleep 状态，日记/peer_chat 误当用户入睡
*   **修复方案**:
    1. proactive_checker 移除助手晚安检测注入块
    2. _try_enter_goodnight_on_intent 一律受配置开关控制，废弃 is_assistant_goodnight 参数
    3. 角色睡眠降频由 checker_event_handler.role_sleeping / decision.py 兜底
*   **验证**:
    1. `venv_core python -m tests.scripts.active_care.verify_assistant_goodnight_not_user_sleep 全部通过（6/6）`

### QR-20260817-DUAL-LEGACY-CIRCLE PeerChat 重复写入旧后台圈子并污染关系热度 (2026-08-17)
*   **问题描述**: 已废弃的后台圈子仍被 PeerChat 后处理当作存储和社交事件通道，自动互聊会反向提高下一轮互聊所依赖的关系热度。
*   **复现步骤**:
    1. 完成一次 PeerChat 剧本分发。
    2. 检查 dual_role/background_circle 与 social_events/default.json。
    3. 观察同一剧本被重复保存且每句 background_circle 事件均参与关系分。
*   **预期行为**:
    1. 自动互聊只保留必要的日记摘要和会话审计记录。
    2. 关系热度只由用户触发的真实互动事件决定。
*   **实际行为**:
    1. 一次互聊产生多个重复存储副本和最多四条自主社交事件。
    2. 历史自动互聊可把关系分推高到升温阈值以上。
*   **根因**:
    1. 早期 BackgroundCircle 链路被并入 PeerChat 时只停止调度，没有移除后处理写入和导出消费者。
*   **修复方案**:
    1. 彻底移除旧圈子实现与配置。
    2. 切断 PeerChat 到圈子存储和 SocialEventEngine 的自主写入。
    3. 历史 background_circle 事件保留兼容读取但不计入关系摘要。
*   **验证**:
    1. `venv_core\Scripts\python.exe tests/scripts/dual_role/verify_background_circle_cleanup.py`

### AC-20260817-CONTEXT-DATE-REMINDER Active Care 相对日期污染与硬提醒话题漂移 (2026-08-17)
*   **问题描述**: 历史、日记和记忆中的错误相对节日日期会被反复注入；到期提醒的文案可能只延续近期闲聊而遗漏任务目标。
*   **复现步骤**:
    1. 让历史上下文出现错误的相对农历节日日期。
    2. 触发普通主动关怀或 workspace 到期提醒。
    3. 观察生成内容是否复述错误日期，或是否遗漏提醒任务核心词。
*   **预期行为**:
    1. 运行时日历事实优先于历史相对日期。
    2. 普通主动关怀仍由 MDP 决策；到期提醒必须明确包含任务目标。
*   **实际行为**:
    1. 旧实现会延续错误日期；硬提醒可能生成与任务无关的短句。
*   **根因**:
    1. 缺少稳定的绝对日期事实锚点。
    2. 日记 tomorrow_tone 同时承载策略和时效事实。
    3. 提醒生成后没有任务目标一致性校验。
*   **修复方案**:
    1. 注入带公历日期和天数差的权威日历锚点。
    2. 限制 tomorrow_tone 不记录日期或节日事实。
    3. 在发送 reminder 前校验任务目标，偏离时使用安全兜底。
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\active_care\verify_active_care_context_and_cleanup.py`

### AC-20260817-CALENDAR-OUTPUT-GUARD 普通 Active Care 动作绕过节日日历硬校验 (2026-08-17)
*   **问题描述**: 普通 curious_question 会忽略 Prompt 中的权威日历锚点，继续发送错误的相对节日日期。
*   **复现步骤**:
    1. 让历史中保留关于节日日期的纠正上下文。
    2. 触发 MDP 选择的普通 curious_question。
    3. 观察模型是否仍输出与权威农历日期冲突的今天或明天断言。
*   **预期行为**:
    1. 所有 Active Care 类型在发送前都必须通过确定性日历事实校验。
*   **实际行为**:
    1. 旧修复仅校验 reminder，普通主动消息仍能直接发出错误日期。
*   **根因**:
    1. 把 Prompt 日历锚点误当成足够可靠的硬约束。
*   **修复方案**:
    1. 在统一发送路径增加确定性日历事实守卫。
    2. 错误节日断言所在短句直接移除，避免继续重复该话题。
*   **验证**:
    1. `tests\scripts\active_care\verify_active_care_context_and_cleanup.py`

### AC-20260817-REMINDER-TONE-REGRESSION 提醒目标守卫把自然改写替换成机械催促 (2026-08-17)
*   **问题描述**: 短计划的开始和结束提醒连续发出，且自然措辞因未逐字复述完整标题而被固定模板替换。
*   **复现步骤**:
    1. 创建一个标题为睡前复盘与明日计划、时长 15 分钟的计划项。
    2. 让开始提醒生成与任务无关的在吗，让结束提醒生成你那个复盘写了吗。
    3. 观察旧逻辑是否连续发送两条固定通知。
*   **预期行为**:
    1. 短计划不连续发送开始和结束提醒。
    2. 提到任务核心词的自然改写应保留，真正跑题才使用温和兜底。
*   **实际行为**:
    1. 旧逻辑为所有正时长任务创建双提醒，并要求完整标题逐字出现。
*   **根因**:
    1. 用字符串全包含代替任务语义相关性判断。
    2. 提醒同步缺少短时长降噪策略。
*   **修复方案**:
    1. 增加任务核心词重合判断。
    2. 增加 30 分钟结束提醒门槛。
    3. 将命令式兜底改为温和问句。
*   **验证**:
    1. `tests\scripts\active_care\verify_active_care_context_and_cleanup.py`

### QR-20260818-WAKEUP-SOURCE-PRIORITY 健康起床时间被聊天当前时刻覆盖 (2026-08-18)
*   **问题描述**: 健康设备记录的起床时间正确，但 AI 查询每日作息时返回了对话发生时刻。
*   **复现步骤**:
    1. 健康同步上报 sleep_end
    2. 用户在聊天中询问记录的起床时间
    3. 查看 daily_record 与 AI 回答
*   **预期行为**:
    1. daily_record 保留健康设备的真实起床时间
    2. 聊天询问不产生新的起床事件
*   **实际行为**:
    1. 聊天被动提取使用当前时刻覆盖了真实起床时间
*   **根因**:
    1. 健康起床事件未写入 daily_record
    2. 起床写入缺少来源优先级保护
    3. 中文询问句识别不完整
*   **修复方案**:
    1. 同步 Samsung Health sleep_end 到 daily_record
    2. 引入起床来源优先级与手动修正覆盖规则
    3. 增强记录引用和中文疑问句拦截
*   **验证**:
    1. `tests.scripts.daily.verify_wakeup_source_priority 通过`
    2. `既有作息修正 12 项回归通过`

### AC-20260818-AUTO-PLAN-MDP-BYPASS 自动日计划硬提醒绕过 MDP 未回复退避 (2026-08-18)
*   **问题描述**: 用户连续不回复时，两个角色仍按约十分钟间隔逐项提醒日计划。
*   **复现步骤**:
    1. 生成含多个短时间块的 AI 自动日计划。
    2. 不回复后继续运行双角色 Active Care。
    3. 观察到期提醒是否在 MDP 决策之前连续发送。
*   **预期行为**:
    1. AI 自动计划只作为 MDP 输入，未回复退避能抑制后续主动消息。
    2. 同一时段只有一个角色拥有主动发送权。
*   **实际行为**:
    1. 旧逻辑把每个时间块都转为到期硬提醒，事件路径抢先执行并绕开退避。
*   **根因**:
    1. 自动计划与用户明确硬提醒没有投递语义分层。
    2. 协商失败兜底时两个角色都可通过发送门控。
*   **修复方案**:
    1. 使用 delivery_mode=hard 区分显式硬提醒，自动日计划交回 MDP。
    2. 对历史无标记待发项增加运行时静默完成与通用离线清理。
    3. 为双角色分工增加唯一、稳定的失败兜底主导。
*   **验证**:
    1. `tests\scripts\active_care\verify_active_care_coordination.py`
    2. `tests\scripts\active_care\verify_proactive_assignment.py`
    3. `tests\unit\test_active_care_due_reminder_and_loop.py`

### AC-20260818-PEER-CONTEXT-COORDINATION Peer Chat 分工未触发且历史素材偏空泛 (2026-08-18)
*   **问题描述**: Peer Chat 切换发起者后可误判为当天首次互聊，剧本又只使用单方与主人的近期历史，容易重复空泛日常话题。
*   **复现步骤**:
    1. 让两个角色在当天不同时间分别发起 Peer Chat。
    2. 检查情境中的角色名、当日计数与主人历史素材。
*   **预期行为**:
    1. 角色名与实际 persona 一致，当日计数是双方共享状态。
    2. 剧本可自然分享双方与主人的真实有趣互动，也能接续上次互聊。
*   **实际行为**:
    1. 旧情境映射颠倒两个名称，并只读取当前发起者的计数和主人历史。
*   **根因**:
    1. 手写角色名映射与 role_id 不一致。
    2. 历史聚合管道未同时解析 role 与 peer 的 persona 会话。
    3. 剧本 prompt 未将真实具体互动设为优先素材。
*   **修复方案**:
    1. 通过 persona 注册表获取角色名，并使用双方计数的全局值。
    2. 同时聚合双角色的真实主人对话，过滤 Active Care 自动消息。
    3. 强化 prompt 中的真实素材优先级与不编造约束。
*   **验证**:
    1. `tests\scripts\active_care\verify_active_care_coordination.py`

### AC-20260824-SHARED-SLEEP-USAGE-EVENT 双角色睡眠状态分裂与数字健康硬事件沿用旧话题 (2026-08-24)
*   **问题描述**: 同一用户的睡眠状态在两个 persona 之间不一致，数字健康超限关怀还可能读取错误会话池并延续无关旧话题。
*   **复现步骤**:
    1. 让主角色记录用户进入睡眠状态，并在双 QQ 检查循环中分别执行两个 persona 的决策。
    2. 通过旧客户端同步应用用量并触发数字健康检查。
    3. 检查两个 persona 的睡眠上下文、数字健康目标 conversation_id、prompt 历史和最终消息。
*   **预期行为**:
    1. 睡眠与清醒是用户级事实，所有 persona 立即得到一致状态。
    2. 数字健康只使用可信当天口径，消息固定围绕目标应用且不声称未确认的设备执行结果。
*   **实际行为**:
    1. 旧实现按 persona 持久化睡眠状态，另一角色可缺失晚安事实；数字健康走通用会话和续聊 prompt，旧客户端数据也没有口径证明。
*   **根因**:
    1. 把用户事实错误放入 persona 领域状态。
    2. 事件事实、会话路由、prompt 和最终发送之间缺少硬边界。
    3. 上游动作约束仅写在 prompt 中，解析器未强制执行。
*   **修复方案**:
    1. 建立用户级睡眠状态真源并在 persona 读取时覆盖旧睡眠副本。
    2. 为数字健康增加可信统计协议、Aveline 人格路由、专用 prompt 和最终目标守卫。
    3. 固定 chosen_action，并让明确起床规则优先于 BERT。
*   **验证**:
    1. `tests\scripts\active_care\verify_shared_sleep_and_usage_event.py`
    2. `tests\unit\test_active_care_dynamic.py`
    3. `tests\unit\test_active_care_intent_detector.py`
    4. `tests\unit\test_life_sleep_wake_route.py`
    5. `tests\unit\test_prompt_sleep_context.py`

### AC-20260824-SLEEP-AUTHORITY-PEER-EVENT 聊天清醒信号污染正式作息且室友生活事件缺少来源 (2026-08-24)
*   **问题描述**: 聊天中的清醒表达会被当成正式起床事实；午睡与主睡眠未区分，生活近况无法带来源地供角色自然共享。
*   **复现步骤**:
    1. 进入晚安低打扰后发送清醒表达，检查用户级睡眠字段和 Daily Record。
    2. 依次同步主睡眠和短时白天睡眠，检查当天正式起床是否被覆盖。
    3. 向 Aveline 报告睡醒或饮食近况，检查Ling Peer Chat 上下文的来源标注。
*   **预期行为**:
    1. 聊天只退出低打扰，正式睡眠区间由 Samsung Health 决定。
    2. 午睡单独记录且不覆盖主睡眠起床。
    3. 角色可以选择自然互聊或不聊，跨角色引用时保留转告来源。
*   **实际行为**:
    1. 旧实现混用了控制状态和事实字段，且 SocialEventEngine 未接入聊天生活事件。
*   **根因**:
    1. 状态领域边界不清，推断信号和测量事实共用写入方法。
    2. 共享事件缺少调用入口与来源协议。
*   **修复方案**:
    1. 拆分低打扰控制 API 与 Samsung Health 权威睡眠同步。
    2. 增加主睡眠/午睡分类和带来源的共享生活事件协议。
    3. 让 Peer Chat 决策自主选择事件题材，不建立强制触发。
*   **验证**:
    1. `tests\scripts\active_care\verify_shared_sleep_and_usage_event.py`

### QR-20260824-ACTIVE-CARE-MODE-CROSSTALK 学习低打扰被写成晚安且普通文本误触发唤醒 (2026-08-24)
*   **问题描述**: 用户正在背单词时，Active Care 将学习专注意图写成 sleep，nightly 因而误判用户开始睡觉；随后无起床语义的普通文本又被 BERT 识别为 WAKEUP_NOW。
*   **复现步骤**:
    1. 发送“我在背单词”或“还在背单词呢，不过今天修了你很多东西”
    2. 观察 SLEEP_STATE 写入晚安低打扰
    3. 等待 nightly 轮询并观察“检测到用户开始睡觉”
    4. 发送无起床语义的普通文本并观察状态可能退出
*   **预期行为**:
    1. 背单词只进入 focus 低打扰，不应写入 sleep
    2. 只有明确的当前起床陈述可以退出晚安低打扰
*   **实际行为**:
    1. 所有 enter_reduced 都调用 set_sleep_mode，导致 focus 被覆盖成 sleep
    2. WAKEUP_NOW 仅凭 0.40 以上零样本相似度即可退出睡眠状态
*   **根因**:
    1. 即时入口没有区分低打扰子类型
    2. 高影响唤醒状态缺少词法和陈述语气确认
*   **修复方案**:
    1. 按 reason/label 路由学习与晚安状态
    2. 禁止 BERT WAKEUP_NOW 单独改状态，保留明确起床规则
*   **验证**:
    1. `新增 5 项回归验证覆盖 focus 不调用睡眠、晚安正常生效、误唤醒被拦截、明确起床仍有效及 focus 状态落盘`
    2. `真实 ONNX BERT 复测两条背词消息为 focus、普通文本为 none`

### QR-20260824-AC-VOCAB-STALE Active Care 在词汇会话完成后沿用旧数量催促 (2026-08-24)
*   **问题描述**: 词汇会话已经结束并持久化完成记录，但主动消息仍可能引用昨日日记或历史对话中的旧目标数量，并把用户视为尚未完成。
*   **复现步骤**:
    1. 让昨日日记或 Peer Chat 历史保留一个旧词汇数量。
    2. 完成当日词汇会话并结束会话。
    3. 触发后续 Active Care 主动消息。
*   **预期行为**:
    1. 实时完成记录优先于历史数量，完成后不再追问或催促。
*   **实际行为**:
    1. 提示词可能沿用旧数量；动态队列变化还可能让完成态反转。
*   **根因**:
    1. 主动关怀缺少统一的词汇实时事实锚点。
    2. 发送路径缺少针对词汇数量与完成态的确定性校验。
*   **修复方案**:
    1. 聚合词汇实时状态，并以当日学习记录中的会话结束条目锁定完成态。
    2. 向 Peer Chat 注入学习上下文，并在统一分发前执行词汇事实守卫。
*   **验证**:
    1. `.\venv_core\Scripts\python.exe tests\scripts\active_care\verify_vocab_status_guard.py`
    2. `.\venv_cpu\Scripts\python.exe tests\scripts\active_care\verify_vocab_status_guard.py`
