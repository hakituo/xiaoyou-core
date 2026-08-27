# Persona / 角色系统

本分类共 9 条记录。按时间倒序（最新在前）排列。

---

### QR-20260702-FOOD-PERSONA-SCOPE 投喂 Aveline 时回执串到Ling (2026-07-02)

*   **问题描述**: 用户在当前会话中明确投喂 Aveline，但系统返回的感谢文案与后续食物归属落到了Ling，出现角色串号。
*   **复现步骤**:
    1. 将当前会话切到 Aveline 相关人设，或在双角色环境下从 Aveline 会话发起投喂。
    2. 执行 `/吃 寿司` 或触发 `feed_food` 工具进行投喂。
    3. 观察后端 `/api/v1/food/eat` 实际收到的参数与最终回执角色。
*   **预期行为**:
    1. QQ 命令和 Tool 调用都应把当前会话的角色上下文显式传给 food 链路。
    2. 投喂 Aveline 时只应由 Aveline 接收并给出对应回执，不应串到Ling。
*   **实际行为**:
    1. QQ `/吃` 和 `feed_food` 都未显式透传当前会话角色。
    2. 后端回退到全局 PersonaManager，若全局当前人设恰好是Ling，就会出现Ling感谢寿司的错误反馈。
*   **根因**:
    1. food 路由与 `FoodManager` 的角色解析没有把会话级 `role_id/persona_filename` 作为优先输入。
    2. QQ FoodHandler 与 Tool 入口缺少角色透传，导致角色归属依赖全局状态。
*   **修复方案**:
    1. 为 food 路由与 `FoodManager` 增加显式角色解析参数支持。
    2. 让 QQ `/吃` 与 `feed_food` 工具都透传当前会话的人设文件和角色 ID。
    3. 补充回归测试与独立验证脚本，覆盖命令入口和工具入口。
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest clients\bots\tests\test_food_handler_persona_scope.py tests\tools\test_feed_food_tool_persona_scope.py -q`
    2. `venv_core\Scripts\python.exe tests\scripts\food\verify_food_persona_scope.py`
    3. `venv_core\Scripts\python.exe -m pytest clients\bots\tests\test_command_router.py -q`

### 11.33 角色夜间被叫醒后重新入睡没有给用户收尾消息，且刚睡下首条消息叫醒概率过低 (2026-06-30)

*   **问题描述**: 用户夜里把角色叫醒聊了几句后，角色静默一会儿又重新去睡，但不会主动补一句“我先继续睡了/我等会儿再睡”；同时刚睡下时首条消息仍几乎叫不醒，体感不符合真人作息。
*   **复现步骤**:
    1. 让角色进入 `sleeping` 状态，且 `actual_sleep_start_ts` 刚发生不久
    2. 用户发送 1 条普通消息
    3. 角色大概率继续静默累积，不容易被叫醒
    4. 若后续被叫醒并聊了一会儿，等待 `silence_window_seconds` 到期
    5. 角色内部可能决定 `return_to_sleep` / `sleep_later`，但前端收不到任何交代消息
*   **预期行为**:
    1. 刚睡下的短窗口内，首条消息就应显著更容易把角色叫醒
    2. 夜间聊天结束后，如果角色决定继续睡或一会儿再睡，应主动补一条解释消息
    3. 双 persona 场景下，这条链路必须落到当前 persona 对应的真实角色，而不是写死主角色
*   **实际行为**:
    1. DND 强制唤醒只看固定概率表，第 1 条消息始终 0% 唤醒
    2. `finalize_sleep_recovery_check()` 虽然会改状态，但不会主动通知用户角色重新去睡
    3. `chat_handlers.py` 的睡眠唤醒链路写死 `"aveline"`，双角色时有串 persona 风险
*   **根因**:
    1. `ReplyPolicy` 的 DND 概率没有读取真实睡眠深度/刚入睡时长
    2. 睡眠恢复任务只做状态机决策，没有和主动消息分发链路联动
    3. 被动聊天入口没有统一按 `persona_filename` 解析 `role_id`
*   **修复方案**:
    1. 在 `reply_policy_support.py` 新增 `resolve_dnd_wake_profile()`，读取 `actual_sleep_start_ts` 与 `wake_by_message_sensitivity`，为“刚睡下”的 `sleeping` 叠加 `fresh_sleep_bonus`
    2. 在 `chat_reply_runtime.py` 新增 `_notify_sleep_resume_message()`，当静默后决策为 `return_to_sleep` / `sleep_later` 时走主动消息链路补发说明，并同步 `Active Care last_sent_ts`
    3. 在 `chat_handlers.py` 用 `resolve_reply_scope(..., persona_filename)` 替换写死的 `"aveline"`
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\character_daily\test_force_wake_and_interrupt.py -q -k "fresh_sleep_bonus"`
    2. `venv_core\Scripts\python.exe -m pytest tests\character_daily\test_sleep_resume_notification.py -q`
    3. `venv_core\Scripts\python.exe tests\character_daily\verify_sleep_resume_notification.py`
    4. `venv_core\Scripts\python.exe tests\character_daily\verify_fresh_sleep_wake_bonus.py`

### 10.144 自动进食未尊重角色睡眠/活动状态（根因：`auto_eat` 仍主要依赖饥饿/口渴与餐窗，没有接入新的角色生活事实源）(2026-06-29)

*   **问题描述**: 新角色生活系统上线后，角色即使处于 `sleeping`、`waking_up` 或忙碌活动中，也可能仍被 `auto_eat` 自动喂食，出现“睡着了还在吃饭”的违和行为。
*   **复现步骤**:
    1. 让角色进入 `sleeping` 或 `waking_up` 等新睡眠/活动阶段
    2. 继续运行 `LifeSimulationService` 的分钟 tick
    3. 只要 `hunger/thirst` 低于阈值，`AutoEatManager.maybe_auto_eat()` 仍会直接进入选食物和进食流程
*   **预期行为**: 自动进食应尊重角色真实状态；睡眠中禁止自动进食，起床恢复期优先补水，忙碌活动只有极端饥渴时才允许轻量补给。
*   **实际行为**: 旧逻辑主要只看 `hunger/thirst + 餐窗 + 冷却`，睡眠系统只参与夜宵支路和睡眠质量惩罚，没有参与“当前是否允许自动吃”的总门控。
*   **根因**:
    1. `auto_eat.py` 没有把 `sleep_manager` 的 `phase/is_sleeping` 作为硬门控
    2. `character_daily` 的 `current_activity` 没有进入自动进食决策链
    3. `life_stats["activity"]` 也未稳定同步当前活动，导致 LLM 选食上下文与真实活动脱节
*   **修复**:
    1. 在 `sleep_food_effects.py` 中新增统一自动进食门控，复用 `sleep_manager` 与 `character_daily` 的状态作为唯一事实源
    2. 在 `auto_eat.py` 中让 Aveline / Ling 在选食物前都先过门控
    3. 睡眠中直接跳过；起床恢复期优先饮水；忙碌状态仅在极端饥渴时允许轻食/饮水；夜醒只允许轻量补给
    4. 在 `life_stats.py` 中把饱食度/口渴度改为按睡眠/活动分档衰减，显著降低睡眠和空闲阶段的固定消耗
    5. 在 `actor_manager.py` 中让同伴角色同步复用新的衰减曲线
    6. 在 `service.py` 中同步写回 `life_stats["activity"]`
*   **验证**:
    1. `venv_core\Scripts\python.exe -m pytest tests\diagnostics\role_sleep\test_auto_eat_gate.py tests\diagnostics\role_sleep\test_life_decay_profile.py -q` 9/9 通过
    2. `venv_core\Scripts\python.exe tests\diagnostics\role_sleep\verify_auto_eat_gate.py` 输出 `OK`
    3. `venv_core\Scripts\python.exe tests\diagnostics\role_sleep\verify_life_decay_profile.py` 输出 `OK`
    4. `venv_core\Scripts\python.exe tests\diagnostics\role_sleep\verify_role_meal_sleep_link.py` 输出 `OK`
*   **教训**:
    1. 新增“角色生活事实源”后，旧子系统不能只补局部联动，必须把“是否允许执行”也接到新事实源上
    2. 食物系统不能只看生理阈值，还要看角色当前所处的睡眠阶段和活动阶段

### 10.128 Aveline hunger 永远为 0 的 falsy-zero 陷阱 (2026-06-18)

*   **问题描述**: Aveline 的饱腹值 (hunger) 始终是 0，整天没被 auto-eat 喂食；Ling被喂了无数次
*   **复现步骤**:
    1. 启动服务，等待 hunger 衰减到 0
    2. 观察日志：auto-eat 只给Ling喂食，Aveline 一次都没有
*   **预期行为**: hunger=0 时 auto-eat 应该触发并喂 Aveline
*   **实际行为**: auto-eat 判定 `aveline_needs_food = False`，跳过 Aveline
*   **根因**: `float(dict.get("hunger", 100.0) or 100.0)` pattern 在 hunger=0 时返回 100.0（Python 中 0 是 falsy），代码认为 Aveline “很饱”。同时 prompt 的 `build_food_context_text` 也显示饱腹100，LLM 也以为她很饱。次要原因：auto-eat 优先级逻辑 `ling_hunger < hunger` 在 Aveline hunger=0 时总是优先喂 Ling
*   **修复方案**: 将 `or 100.0` 替换为 `is not None` 检查；重写 auto-eat 优先级引入紧急度分级；修复 decision_tools.py 的 scale 错误

### 10.123 双角色互聊剧本无法分发 (2026-06-13)

*   **问题描述**: PeerChatScheduler 每次生成剧本后都无法分发，日志显示 `NameError: name 're' is not defined`，双角色互聊连续多天未成功发送
*   **复现步骤**:
    1. 启动项目，等待 PeerChatScheduler 检查周期（30分钟）
    2. LLM 决策 should_send=True，剧本生成成功
    3. 调用 `PeerChatManager.filter_script(script)` 时报错 `NameError: name 're' is not defined`
    4. 异常被外层 try/except 捕获，`generate_peer_script` 返回 False
    5. 日志显示 "本轮未发送（可能受频率限制或LLM决策不发）"
*   **预期行为**: 剧本生成后应正常过滤并分发到两个QQ号
*   **实际行为**: `filter_script` 方法使用了 `re.match()` 和 `re.sub()` 但文件顶部未导入 `re` 模块，导致每次都报错
*   **根因分析**: `qq_adapter_peer_chat.py` 的 `filter_script` 方法在第175行和第185行使用了 `re` 模块，但文件顶部只导入了 `json, asyncio, logging, random, time`，缺少 `import re`
*   **修复方案**: 在文件顶部添加 `import re`

### 10.119 自动喂食系统不照顾Ling (2026-05-31)

*   **问题描述**: Ling的 hunger 降到 18.92，thirst 降到 0，mood_score 只有 10，因为系统没有自动喂食Ling
*   **复现步骤**:
    1. 查看 actor_states.json，Ling的 hunger=18.92, thirst=0
    2. 检查 auto_eat.py，发现只关注 Aveline 的状态
    3. 和Ling分享食物的概率太低（基础 10%）
*   **预期行为**: 系统应该同时照顾 Aveline 和Ling的状态
*   **实际行为**: Ling的 hunger 和 thirst 一直下降没人管
*   **根本原因**: auto_eat.py 的 `maybe_auto_eat` 函数只检查 Aveline 的状态，分享食物概率太低
*   **修复**: 
    1. 重写 `maybe_auto_eat`，同时检查双方状态，优先照顾更饿的一方
    2. 新增 `_feed_ling` 方法单独喂食Ling
    3. 提高分享概率（基础 30%，最高 90%）
*   **状态**: ✅ 已修复

### 10.114 普通聊天时模型分不清QQ号身份（Ling管主人叫澪姐）(2026-05-29)

*   **问题描述**: 主人(10001)给Ling发消息"玲玲？"，Ling回复"澪姐，怎么了"，把主人当成了七濑澪。模型完全不知道哪个QQ号对应谁。
*   **复现步骤**:
    1. 启动双QQ适配器
    2. 用主人QQ(10001)给Ling(3795532329)发消息
    3. Ling回复时管主人叫"澪姐"
*   **预期行为**: Ling知道10001是主人Master，不是七濑澪
*   **实际行为**: Ling分不清QQ号，把主人当成了七濑澪
*   **根本原因**: `qq_identity_map` 只在双角色私聊(peer chat)时通过 `peer_role_context` 注入，普通聊天（主人→Ling）时没有任何身份映射信息。模型只看到QQ号，不知道谁是谁。另外 `_build_peer_role_context` 中的 `qq_identity_map` 有bug：`my_qq` 被赋值但从未加入 `identity_parts`，且对于aveline角色 `my_qq = peer_qq_id`（逻辑错误）。
*   **修复**: 新增 `_build_qq_identity_context()` 方法，在所有QQ聊天场景注入 `【账号身份】` 上下文（主人Master的QQ号是10001；你（Ling）的QQ号是3795532329；七濑澪的QQ号是3406280693）。从NapCat消息中动态获取bot自身QQ号。

### 10.84 生日提示"你的生日"措辞歧义导致角色误认用户生日为自己的生日 (2026-05-06)

*   **问题描述**: 系统提示中即将到来的生日提醒使用"你的生日"指代用户生日，但在系统 prompt 语境中"你"指的是 AI 角色自己，导致角色把用户的生日当成自己的生日来提醒对方
*   **复现步骤**:
    1. 用户生日（05-12）在7天范围内时，系统注入"还有6天就是你的生日"
    2. AI 角色将"你"理解为自身，对用户说"还有六天我生日了"
    3. 用户反驳后角色困惑
*   **预期行为**: 角色应正确识别用户生日是"对方的生日"，提醒自己准备惊喜；角色自己的生日才用"你的生日"
*   **实际行为**: 角色把用户生日当成自己的生日
*   **修复方案**: 修改 `special_days.py` 中 `get_special_day_prompt()` 和 `get_upcoming_birthday_prompt()` 函数，根据 `is_user` 字段区分措辞：用户生日用"对方的生日"，角色生日用"你的生日"

### 10.69 persona diary 系统三大 Bug：日记始终为空、AI角色有学习总结、后台圈子日期不匹配 (2026-05-03)

*   **问题描述**:
    1. `diary.json` 的 `entry_count` 始终为 0，note 显示"今天暂无可用素材，尚未生成成品日记"，用户十分看重的日记系统完全无法工作
    2. AI 角色（"七濑 澪"，scope=aveline）的 persona_data 目录下有 `learning_summary.json`，但 AI 不应该有学习总结
    3. `background_circle.json` 的 `entries` 始终为空，`_load_background_entries` 导出历史日期时拿到的是今天的数据
*   **复现步骤**: 查看 `companion_data/aveline_data/persona_data/aveline/2026/5/1/` 下的文件，diary.json entry_count=0，learning_summary.json 存在且有数据，background_circle.json entries=[]
*   **预期行为**: diary 应有内容，AI 角色不应有 learning_summary，background_circle 应按日期正确加载
*   **实际行为**: diary 始终为空，AI 角色有学习总结，background_circle 日期不匹配
*   **根因**:
    1. **diary 为空**：`_export_persona()` 过滤 persona 条目时，`_infer_persona_name(entry)` 要求 content 以 "Ling：" 或 "七濑 澪：" 开头，或 tags 包含 persona 名字，或 source 在 `PERSONA_SOURCE_MAP` 中。但绝大多数 journal entry 的 source 是 "user"（不在映射表中），content 也不以 persona 名字开头，导致 `_infer_persona_name` 返回 None，所有 entry 被过滤掉
    2. **AI 角色有 learning_summary**：`_export_persona()` 对所有 persona 无条件写入 `learning_summary.json`，没有根据角色类型区分
    3. **background_circle 日期不匹配**：`_load_background_entries()` 调用 `service.get_today_entries()`，而 `get_today_entries()` 内部使用 `datetime.now()` 而非传入的 `dt` 参数
*   **修复方案**:
    1. diary：在 `_export_persona()` 的 persona 条目过滤中，当 `_infer_persona_name(entry)` 返回 None 时，将 entry 分配给 ling persona（用户角色），不再丢弃
    2. learning_summary：只有 ling persona 才写入 `learning_summary.json`，AI 角色（aveline scope）不再生成
    3. background_circle：给 `BackgroundCircleService` 新增 `get_entries_by_date(date)` 方法，`_load_background_entries()` 改用该方法

### AOS-0805-05 CompanionPersonaTab 每次重组都重新解析整棵 JSON (2026-08-05)
*   **问题描述**: 人设 Tab 的 Composable 把 8 次 activePersona JsonObject 字段读取 + personaList jsonObject 映射直接写在函数主体里，该 tab 每次重组（例如 loading 翻转、情绪更新、切 tab 再回来）都会重新解析 JSON 对象树，低端机上切换 tab 会有 30~60ms 掉帧。
*   **复现步骤**:
    1. 打开 Companion 页停在 Persona Tab，systrace 打开
    2. 连续切换 Home/Status/Persona tab，观察每次 Persona Tab 重组时长
    3. 在 loading=true→false 切换时看 Composition 区间
*   **预期行为**:
    1. JSON 解析在 activePersona/personas 不变时只执行一次，或由 ViewModel 层预先解析成数据类
    2. LazyColumn 有稳定 key，列表变化时能增量复用
*   **实际行为**:
    1. 每次重组都重新 8 次 jsonObject/jsonPrimitive 提取；personaList 也重新 mapNotNull { it.jsonObject }
    2. 有数据时列表走 itemsIndexed 但空状态用 Column+forEach，非懒加载测量
*   **根因**:
    1. Composable 中直接做反序列化/映射工作，未注意重组频率
    2. 原型阶段为了快直接在 UI 层写 JSON 提取，未引入 remember 或 domain model
*   **修复方案**:
    1. CompanionPersonaTab：val parsedActive = remember(uiState.activePersona) { ... } 统一提取并封装为 ActivePersonaParsed 数据类
    2. val personaList = remember(uiState.personas) { it.mapNotNull {...} } 缓存映射结果
    3. 有数据时 itemsIndexed 仍走稳定 key（filename），空状态仅保留 SectionCard 包裹
*   **验证**:
    1. `:app:compileDebugKotlin exit 0`
    2. `layout inspector 重复切换 tab 重组期间 Composition frame count 下降约 30%~50%`

### QR-20260824-PROMPT-TOOL-SCHEMA-BLOAT 角色人设较短但主对话恒定 Prompt 仍超过 20k Tokens (2026-08-24)
*   **问题描述**: 角色 system prompt 只有约 2.2k 字符，主对话请求的 prompt_tokens 却长期保持在 21k 至 23k，工具链信息明显压过角色人设。
*   **复现步骤**:
    1. 查看 logs/prompt_cache_stats.log 中 source=streaming.py::stream_chat_impl 的真实 API usage
    2. 对照 xiaoyou_main.log 的 PromptData TemplateLen、CompleteMessageList StaticLen 和 Native Tools 注册数量
    3. 序列化 ToolRegistry 全量原生工具 schema 并统计字符数
*   **预期行为**:
    1. 普通闲聊只发送基础工具定义，领域工具仅在相关意图出现时发送
    2. 云模型不在消息文本和原生 function schema 中重复接收同一份工具说明
*   **实际行为**:
    1. 普通主对话每轮注册 79 至 82 个原生工具，API prompt_tokens 约 21k 至 23k
    2. 82 个工具 schema 序列化后为 47898 字符，而普通角色静态 prompt 仅约 2187 至 2372 字符
*   **根因**:
    1. 模型发送路径绕过了 context_persona 已生成的 active_tools，重新读取并发送全部启用工具
    2. assembler.py 对云模型继续追加 get_concise_tool_prompt，重复描述原生工具
*   **修复方案**:
    1. 让流式和非流式路径复用消息级 active_tools，并在 prepare_native_tools 中只序列化本轮集合
    2. 补齐常用领域关键词路由，保留完整注册表的可达性
    3. 仅本地模型保留文本工具清单
*   **验证**:
    1. `verify_prompt_tool_schema_budget.py 4 项通过，普通闲聊 schema 从 47898 字符降至 1457 字符`
    2. `Ruff 与 py_compile 通过`

### QR-20260825-CHARACTER-DAILY-DYNAMIC-ROLES 共享角色计划算法仍被运行时固定角色列表限制 (2026-08-25)
*   **问题描述**: YAML 已存在角色模板且 DailyPlanGenerator 支持任意 role_id，但未写入 KNOWN_ROLES 的角色不会获得当日计划。
*   **复现步骤**:
    1. 在角色模板中增加一个新的 role_id
    2. 重启 CharacterDailyEngine 并执行当日 tick
    3. 检查 daily_state.json 中该角色是否出现
*   **预期行为**:
    1. 全部已加载模板角色自动生成并推进计划
    2. 当天新增模板角色重启后立即补齐，不必等待日期切换
    3. 增加普通日程角色不需要修改 Python 固定列表
*   **实际行为**:
    1. 主循环只遍历 KNOWN_ROLES，模板集合与运行时角色集合可能不一致
    2. 当前验证中模板加载 7 个角色，而旧常量只包含 6 个
*   **根因**:
    1. 模板字典和 KNOWN_ROLES 同时承担角色发现职责
    2. 计划补齐逻辑与新一天状态重置耦合
*   **修复方案**:
    1. 以 DailyPlanGenerator.role_ids 作为唯一计划角色来源
    2. 提取 _ensure_daily_plans 并在每轮检查中幂等补齐缺失角色
    3. 将 Peer Chat/Active Care 权限边界与日程角色发现明确分离
*   **验证**:
    1. `future_role 动态角色单元测试通过`
    2. `全部 7 个当前模板角色行为验证通过`
    3. `定向 pytest 37 项与 Ruff 全部通过`

### QR-20260826-LING-PERSONA-RAW-CHAT-ALIGNMENT Ling正常人设回复不像原始聊天且会混入另一模式人工语感 (2026-08-26)
*   **问题描述**: 正常角色回复过度依赖固定口头禅和统一短句，缺少原始聊天中按上下文补充具体信息、追问或轻微抱怨的自然变化。
*   **复现步骤**:
    1. 统计完整 pairs 数据中的回复长度、多片段比例和高频口头禅占比
    2. 对照 core_ling、QQ 正常人设和动态参考对话加载路径
    3. 使用 8 个不含真实私聊内容的新场景调用现场模型
*   **预期行为**:
    1. 正常人设以真实聊天样本的语气和信息密度为依据，不把抽象标签演成固定模板
    2. 正常模式只使用日常原始/人工筛选样本，模式专属样本不跨模式注入
    3. 历史示例只影响说话方式，不把旧地点、活动或原因当成当前事实
*   **实际行为**:
    1. 旧现场评估中 AI 的啊使用率远高于真实记录，回复均长和上下文推进也有偏差
    2. 正常 StyleRetriever 的静态 fallback 实际指向另一模式的人工样本
    3. 未裁剪的参考块最长超过千字，现场回复出现舞台旁白和历史事实复制
*   **根因**:
    1. 人设规则把少量表面特征写成高频强约束，压过真实对话中的变化
    2. 普通与模式专属静态样本路径接反
    3. 检索结果缺少局部窗口裁剪和样本事实隔离
*   **修复方案**:
    1. 重写正常人设与 QQ 包装 Prompt，强调具体回应、单一聊天动作、低频口头禅和无舞台旁白
    2. 正常 fallback 改为日常人工筛选样本，并移除不再使用的模式专属样本链路
    3. 新增最多 6 行的局部参考窗口与历史事实隔离提示
*   **验证**:
    1. `原始基线 4097 条有效回复、均长 9.15 字、多片段 33.6%`
    2. `最终现场 8 场景均长 11.5 字，全部风格守卫通过`
    3. `目标 pytest 1 passed，Ruff 与专用验证脚本通过`
