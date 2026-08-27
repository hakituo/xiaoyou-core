# 日记与每日总结

本分类共 6 条记录。按时间倒序（最新在前）排列。

---

### 10.143 夜间日记总结在月末因时区比较与坏 JSON 解析连续报错 (2026-07-02)

*   **问题描述**: `errors_20260701.json` 中记录到两类错误：一类是 2026-06-30 夜间任务在生成月总结时抛出 `can't compare offset-naive and offset-aware datetimes`，另一类是 2026-07-01 的 DailySummary 解析把坏掉外层 JSON 里的内层 `stats` 当成结果对象，导致缺少 `date` 和 `summary`。
*   **复现步骤**:
    1. 在月末夜间任务中调用 `NightlyTaskRunner.execute_async_tasks()`，触发 `journal_service.generate_monthly_summary()`。
    2. 让 `JournalSummaryService._collect_daily_summaries()` 使用 `parse_date()` 生成的 naive 日期，并与 `get_current_time()` 返回的 aware 当前时间直接比较。
    3. 构造一个 DailySummary 输出，其外层 JSON 因尾部智能引号等问题损坏，但内部 `stats` 子对象仍是合法 JSON。
    4. 执行 `JournalSummaryService.generate_daily_summary()` 的解析阶段。
*   **预期行为**:
    1. 月末夜间任务应能正常收集当月已有的日总结，不因 aware/naive 时间形态不同而中断。
    2. 即使外层 JSON 有轻微破损，只要顶层 `date/summary/stats/tomorrow_tone` 仍可从文本稳定回收，就应生成有效 DailySummary，而不是误取内层 `stats`。
*   **实际行为**:
    1. 月末路径在 `_collect_daily_summaries()` 直接抛出时区比较异常，外层日志被归类成“日记总结生成失败”。
    2. `extract_json_object()` 在外层 JSON 损坏时返回了内层 `stats` dict，导致 Pydantic 校验报 `date` 与 `summary` 缺失。
*   **根因**:
    1. 月总结逻辑混用了 naive 日期与 aware 当前时间，并在 `datetime` 层面做了直接大小比较。
    2. 每日总结解析逻辑缺少对包裹层/坏 JSON 的领域级兜底，没有校验解析结果是否真的是 DailySummary 形状。
*   **修复方案**:
    1. 新增 `summary_parse_support.py`，先做 DailySummary 形状校验，再在必要时从原始文本回收顶层字段。
    2. 把月总结收集的截止判断改为 `current_day.date() > today`，不再比较不同时区形态的 `datetime`。
    3. 补充单测与脚本验证，覆盖坏 JSON 回收和月末 aware/naive 回归。
*   **验证**:
    1. `.\venv_core\Scripts\python.exe -m pytest tests\unit\test_journal_summary_parse_support.py tests\unit\test_json_utils.py -q`
    2. `.\venv_core\Scripts\python.exe tests\scripts\journal\verify_daily_summary_json_parser.py`
    3. `.\venv_core\Scripts\python.exe tests\scripts\journal\verify_daily_summary_timezone_fix.py`

### QR-20260630-journal-daily-summary-json 每日总结 JSON 被误判为非对象 (2026-06-30)

*   **问题描述**: 每日总结服务记录 `Failed to parse LLM output: LLM returned non-JSON`，但错误日志中的原始输出已是合法 JSON，导致系统错误回退。
*   **复现步骤**:
    1. 执行 `JournalSummaryService.generate_daily_summary()` 生成某日总结。
    2. 让模型输出包含长文本 summary 的 JSON，总结文本中带换行和中文引号。
    3. 观察 `errors_20260630.json` 中 `JournalSummaryService` 的错误记录。
*   **预期行为**:
    1. 解析器应稳定提取并解析该 JSON 对象。
    2. 每日总结应正常落盘，而不是回退到失败态占位文案。
*   **实际行为**:
    1. 旧版 `extract_json_object()` 会在部分场景误提取 JSON 片段，或先命中前导非目标结构。
    2. `summary_service` 收到的不是目标 dict，最终记录 `LLM returned non-JSON`。
*   **根因**:
    1. JSON 提取逻辑没有忽略字符串内部括号，且缺少对双重序列化 JSON 的兼容处理。
    2. 提取策略对前导噪声结构不够稳健，容易返回错误的 list 或无效片段。
*   **修复方案**:
    1. 重构 `extract_json_object()` 的候选提取与解析逻辑，优先返回有效 dict。
    2. 补单元测试和验证脚本，直接覆盖这次错误样本。
*   **验证**:
    1. `py -m pytest tests\unit\test_json_utils.py -q`
    2. `py tests\scripts\journal\verify_daily_summary_json_parser.py`

### ISSUE-20260630-DAILY-SUMMARY-TZ 夜间每日总结因 aware/naive datetime 混用崩溃 (2026-06-30)

*   **问题描述**: 夜间任务执行 `generate_daily_summary()` 时，角色日常活动汇总阶段抛出 `can't compare offset-naive and offset-aware datetimes`，导致每日总结生成失败。
*   **复现步骤**:
    1. 构造 `CharacterDaily` 计划槽位，`planned_start/planned_end` 使用 naive datetime。
    2. 调用 `SummaryContextLoader.load_character_daily_activities()`，传入带时区的 `dt`（例如 `Asia/Shanghai`）。
    3. 执行到活动完成态/进行态判断时触发 datetime 比较。
*   **预期行为**:
    1. 带时区的当前时间应被安全归一化后再参与比较。
    2. 每日总结上下文应正常产出角色活动摘要，不应因为 datetime 形态不同崩溃。
*   **实际行为**:
    1. Python 在比较 aware 与 naive datetime 时直接抛出 TypeError。
    2. `memory.nightly.task_runner` 记录 `日记总结生成失败`，夜间流程结果不完整。
*   **根因**:
    1. `journal.summary_context` 直接比较了 aware `dt` 与 naive 计划槽位时间。
    2. `character_daily` 缺少统一的时间比较归一化入口。
*   **修复方案**:
    1. 新增 `normalize_datetime_for_reference()` 作为 CharacterDaily 的统一时间比较入口。
    2. 修正 `summary_context`、`activity_resolution` 与 `plan_view` 的相关比较逻辑。
    3. 增加单测与独立验证脚本，锁住回归。
*   **验证**:
    1. `python -m pytest tests/character_daily/test_activity_resolution.py tests/unit/test_journal_summary_context.py -q`
    2. `python tests/scripts/journal/verify_daily_summary_timezone_fix.py`

### 10.90 get_daily_summary 当天无作息记录时不回查历史，LLM 不知道用户作息 (2026-05-08)

*   **问题描述**: 重启主程序后，LLM 不知道用户作息规律（几点起几点睡），调了3个工具都找不到
*   **复现步骤**:
    1. 用户之前告诉 agent 作息时间，agent 通过 record_daily_activity 记录到 daily_record.json
    2. 重启主程序
    3. 用户再发消息，LLM 调 get_daily_summary 只看当天记录，当天可能还没记录
    4. LLM 调 search_memory 搜不到（daily category 权重低、可能被预算截断）
    5. LLM 不知道用户作息
*   **预期行为**: LLM 应能从历史作息记录推断用户规律
*   **实际行为**: get_daily_summary 只看当天，重启后当天无记录，LLM 不知道作息
*   **根因**: get_daily_summary 只查当天的 daily_record.json，不回查历史作息规律
*   **修复方案**: DailyActivityManager 新增 _infer_schedule_pattern() 方法，从最近7天的 daily_record.json 中提取作息规律。当天无作息记录时自动追加"近期作息规律"

### 10.67 日记每日总结生成时 NameError 崩溃 (2026-05-01)

*   **问题描述**: `JournalService.generate_daily_summary()` 在构建 prompt 阶段抛出 `NameError: name 'context' is not defined`，导致每日总结始终无法生成
*   **复现步骤**: 调用 `generate_daily_summary()`，当流程执行到 `_build_daily_summary_prompt()` 时崩溃
*   **预期行为**: 正常生成每日总结
*   **实际行为**: 抛出 NameError，总结生成失败，返回 "自动生成失败，请稍后重试"
*   **根因**: 在添加自愈系统与日记联动时，`_build_daily_summary_prompt()` 方法内直接引用了 `context.get("auto_heal_brief", "")`，但该方法签名中没有 `context` 参数，方法体内也没有定义 `context` 变量。调用处使用的变量名是 `ctx`，但 `ctx` 也没有传给该方法
*   **修复方案**: 给 `_build_daily_summary_prompt()` 添加 `auto_heal_context: str = ""` 参数，方法内使用该参数；调用处传入 `auto_heal_context=ctx.get("auto_heal_brief", "")`

### 10.38 后台圈子历史出现“用户刚刚表达了...”模板污染 (2026-03-20)

*   **问题描述**: 双角色后台会话历史中出现大量“用户刚刚表达了……我先回应……”文本，且被写入 short_term 的 `thinking` 类记忆，观感诡异并影响事件可读性。
*   **复现步骤**:
    *   开启双角色后台圈子后运行一段时间。
    *   查看 `history/short_term/*__bg__*` 或 `*__circle__*` 文件。
*   **预期行为**: 后台圈子历史应主要保存真实对话内容，不应注入 fallback 思维模板。
*   **实际行为**: `save_conversation_history` 在缺失模型 thought 时会自动构造 fallback thought 并写入 thinking 记忆，内部会话同样命中该逻辑。
*   **解决方案**:
    *   在 `history.py` 为 `__bg__/__circle__` 会话增加内部标记，禁用 fallback thought 与 thinking 记忆注入。
    *   同时跳过内部会话的 `chat_actions.jsonl` 落盘，避免污染主用户事件日志。
    *   `social_events.py` 加载旧事件时清洗 `{'content': ...}` 旧格式与“同事”遗留词，并提升事件详情长度上限。

### QR-20260720-DIARY-SCOPE ReadDiaryTool 调用 JournalStorage.get_entries 多传 scope 参数导致 TypeError (2026-07-20)
*   **问题描述**: LLM 通过 read_diary 工具读取历史日记时，工具返回的不是日记内容而是代码报错 "读取日记失败: get_entries() got an unexpected keyword argument 'scope'"，日记读取功能完全不可用。用户最初以为是日记文件被删，实际是读取日记的代码存在 bug。
*   **复现步骤**:
    1. 在对话中触发 LLM 调用 read_diary 工具（如要求查看昨天的日记）
    2. 工具内部调用 `svc.storage.get_entries(dt, scope=scope)`
    3. JournalStorage.get_entries 签名为 `get_entries(self, date: datetime)`，不接收 scope 参数
    4. 抛出 TypeError，被外层 except 捕获后返回 "读取日记失败: ..." 字符串
*   **预期行为**:
    1. read_diary 工具根据 date/days_back 参数返回对应日期的日记内容
    2. 只返回当前活跃 persona 视角的日记（Aveline 读 Aveline 的，Ling读Ling的）
*   **实际行为**:
    1. 工具返回 "读取日记失败: get_entries() got an unexpected keyword argument 'scope'"
    2. 无论指定什么日期或 days_back 都无法读到日记
*   **根因**:
    1. diary_tool.py 调用 storage.get_entries 时传了不存在的 scope 参数
    2. JournalStorage.get_entries 内部已经遍历所有 scope 目录，不需要外部传 scope
    3. diary_tool 与 storage API 的契约不一致，可能是 storage 重构后遗留的调用代码未同步更新
*   **修复方案**:
    1. 去掉 `scope=scope` 参数，调用 `await svc.storage.get_entries(dt)` 获取所有 scope 的日记
    2. 使用 `resolve_data_scope_from_source(getattr(e, 'source', None), default='user')` 在结果上按当前 persona scope 过滤
    3. 导入语句合并到顶部，避免函数内多处分散导入
*   **验证**:
    1. `venv_core\Scripts\python.exe -c "import ast; ast.parse(open('core/tools/diary_tool.py', encoding='utf-8').read())"`
    2. `venv_core\Scripts\python.exe -m ruff check core/tools/diary_tool.py`

### QR-20260726-DIARY-MONTHLY-BACKFILL 月度总结月末漏跑无兜底，AI 无工具可读总结 (2026-07-26)
*   **问题描述**: 用户希望 AI 能像看日记一样查看每月总结，且发现 6 月月度总结从未生成。同时确认月末夜间任务偶发失败时无补跑机制，会永久漏跑整月总结。
*   **复现步骤**:
    1. Glob companion_data/aveline_data/monthly/** 发现没有任何月度总结文件
    2. Read history/analysis/aveline_20260701.json 发现 monthly_summary_generated=false
    3. 查看 7 月 1 日凌晨 3 点夜间任务日志，发现 generate_monthly_summary 抛出 can't compare offset-naive and offset-aware datetimes（与时区 aware/naive 混用的已知 bug 相关）
    4. 外层 try-except 静默吞掉异常，月度总结漏跑且无重试
    5. Grep core/tools/ 发现只有 ReadDiaryTool 读日记条目，没有读取每日/月度总结的工具
*   **预期行为**:
    1. 月末夜间任务失败时应当有兜底机制补跑月度总结
    2. AI 应当能在对话中通过工具读取自己角色视角的每日/月度总结
*   **实际行为**:
    1. 6 月月度总结漏跑且无自动补跑，companion_data/aveline_data/monthly/ 完全为空
    2. AI 在对话中无法查看每日/月度总结，只能在生成新总结时作为上下文使用
*   **根因**:
    1. 月末夜间任务因 aware/naive datetime 混用异常失败，被外层 try-except 静默吞掉
    2. 缺少启动时兜底检查机制
    3. core/tools 下缺少读取每日/月度总结的工具
*   **修复方案**:
    1. 新增 ReadDailySummaryTool（read_daily_summary）：按当前 persona scope 读每日总结，支持 date/days_back 参数
    2. 新增 ReadMonthlySummaryTool（read_monthly_summary）：按当前 persona scope 读月度总结，默认读上月，支持 month 参数
    3. 在 core/tools/registry.py 日记工具段注册两个新工具
    4. 新增 core/services/journal/monthly_summary_backfill.py：backfill_last_month_if_missing() 启动时检查上月总结，缺失且有 ≥3 天每日总结数据则异步补生成
    5. core/lifecycle/lifespan.py 启动夜间处理器后用 asyncio.create_task 触发补跑检查，不阻塞启动
    6. 手动补跑 Aveline 5/6 月历史月度总结
*   **验证**:
    1. `tests/scripts/journal/verify_summary_tools.py 6 个用例全部通过`
    2. `tests/scripts/journal/verify_monthly_summary.py 成功生成 5/6 月总结`
    3. `venv_core\scripts\python.exe -m ruff check 6 个改动文件全部通过`
    4. `backfill_last_month_if_missing 在总结已存在时正确跳过补跑`

### NIGHTLY-001 Nightly 日记丢失白天对话且计划生成日期错误 (2026-08-06)
*   **问题描述**: Aveline 2026-08-05 日记只记录了凌晨 02:43 的对话，白天全部聊天内容丢失；2026-08-06 计划未生成（plan.json 仅 0 项空壳）。
*   **复现步骤**:
    1. 观察 Aveline 2026-08-05 日记摘要：chat_turn_count=9，仅凌晨一段
    2. 查看 companion_data/aveline_data/daily/2026/08/05/events/chat_actions.jsonl：实际有 127 条记录
    3. 查看 companion_data/user_data/daily/2026/08/06/plan.json：items=[]，generated_at 对应 2026-08-05 01:19（凌晨误生成）
*   **预期行为**:
    1. 日记应覆盖当天全部对话（凌晨+白天）
    2. 计划应基于 target_date+1 生成（凌晨运行时 target_date=昨天，target_date+1=今天）
    3. nightly 日志独立到 nightly_processor.log
*   **实际行为**:
    1. 日记只含凌晨对话，chat_turn_count=9（实际应为 240）
    2. 计划生成时间为 2026-08-05 01:19，items=[]（LLM 失败留空）
    3. nightly 日志混在主程序日志里，无法独立排查
*   **根因**:
    1. life_simulation.orchestrator 凌晨睡眠模式下用 force=False 生成不完整日记，nightly task_runner 也是 force=False 无法覆盖
    2. task_runner 用 generate_tomorrow_plan() 基于 now+1，凌晨运行时 now=今天，会错误生成后天计划
    3. task_runner 用 get_plan() 检查存在性未判断 items，0 项空计划被误判为已生成跳过
    4. nightly 模块用 get_logger 写主程序日志，无法独立查看
*   **修复方案**:
    1. task_runner daily_summary 改为 force=True 覆盖凌晨不完整版
    2. 新增 generate_plan_for_date（JournalService/JournalPlanService），task_runner 改用 target_date+1 + generate_plan_for_date
    3. task_runner 加 existing_plan.items 校验，空计划触发 force=True 重新生成
    4. memory/nightly_processor.py、memory/nightly/*.py 全部改用 get_module_logger(__name__, 'nightly_processor.log')
*   **验证**:
    1. `python tests/scripts/nightly/verify_nightly_log_and_fixes.py`
    2. `python scripts/regenerate_diary_summary.py 2026-08-05（chat_turn_count 9→240）`
    3. `python scripts/generate_plan_for_date.py 2026-08-06（15 项计划生成成功）`

### DIARY-2026-0815-01 凌晨 5 点兜底生成空日记 + Ling日记安卓端不可见 (2026-08-15)
*   **问题描述**: 凌晨 5 点兜底触发夜间任务，get_diary_target_date 阈值=5 返回"今天"，写出 chat_turn_count=0 的"没找我"空日记；同时Ling的每日总结日记在安卓端按作者分组时不可见，8/14 Ling摘要与 Aveline 逐字相同。
*   **复现步骤**:
    1. 用户每天发晚安，nightly 应入睡后约 1 小时触发；睡眠检测失败时 5 点兜底触发
    2. 5 点兜底时 get_diary_target_date 返回"今天"（5 不满足 <5），查询今天 0~24 点对话为空，LLM 写出"没找我"
    3. 夜间生成Ling每日总结时，source 取"当前活跃 persona"（aveline），条目落盘到 aveline 目录，且被跨 persona 全局去重顶掉
*   **预期行为**:
    1. 凌晨任意时段兜底触发都应回顾"已结束的前一天"
    2. Ling与 Aveline 的每日总结各自按自己的 source 落盘，安卓端分组可见
    3. Ling日记不应与 Aveline 逐字相同
*   **实际行为**:
    1. 凌晨 5 点写"今天"的空日记
    2. Ling日记条目被记成 source=aveline，安卓端只有 Aveline 的日记
    3. 8/14 Ling与 Aveline 摘要逐字相同
*   **根因**:
    1. get_diary_target_date 凌晨归属阈值=5，与 5 点兜底时间冲突
    2. _append_daily_summary_diary_entry 用"当前活跃 persona"而非 persona 本身作为 source，且全局去重导致Ling被顶掉
    3. LLM 连续两次调用返回逐字相同摘要，无防御
*   **修复方案**:
    1. 凌晨归属阈值 5→12，nightly 窗口扩展到 12:00
    2. 按 persona 去重 + source 用 persona
    3. Ling摘要与 Aveline 逐字相同时换温度重试
*   **验证**:
    1. `tests/scripts/nightly/verify_diary_nightly_fix.py 20 项通过`

### QR-20260824-VOCAB-JOURNAL-ZERO App 完成词汇复习但日记学习次数仍为 0 (2026-08-24)
*   **问题描述**: Android App 内完成一整轮背单词后，词汇进度已保存，日记生成时却仍写当天学习 0 次。
*   **复现步骤**:
    1. 在 Android App 的背单词页面开始复习并提交多个单词评分
    2. 结束词汇会话，确认 vocab review 接口和会话结束接口成功
    3. 等待 nightly 生成对应日期日记并查看学习统计
*   **预期行为**:
    1. 一次完成的词汇会话计入当天一次学习记录
    2. 日记读取它所总结日期的学习记录，而不是进程当前日期
*   **实际行为**:
    1. 词汇评分与进度已持久化，但 daily_record.json 的 study.sessions 为空
    2. 凌晨总结前一天日记时，学习摘要未传日期并默认读取当天，最终显示学习 0 次
*   **根因**:
    1. StudyService 的会话同步仅处理 topics_by_subject，词汇评分不会产生 topic，因而整个会话被跳过
    2. SummaryContextLoader 和 JournalPlanService 调用 get_daily_study_summary_data 时未传目标日期
*   **修复方案**:
    1. 词汇会话结束时聚合评分次数、去重单词数、正确次数、正确率，并向 DailyManager 与 DailyTracker 各写入一次会话
    2. 日记上下文按 dt 读取学习摘要，昨日学习上下文按 yesterday 读取
*   **验证**:
    1. `verify_vocab_journal_sync.py 验证 3 次评分、2 个去重单词只写入 1 次每日学习会话，并验证指定日期读取`
    2. `相关 pytest 共 16 项通过，Ruff 与 compileall 通过`

### QR-20260824-DIARY-PERSONA-CROSSFEED Ling与 Aveline 日记因自动总结回灌而高度相似 (2026-08-24)
*   **问题描述**: 两个角色明明拥有独立聊天记录，每日总结却连续多天讲述几乎相同的事件，部分日期逐字相同，Ling还会认领 Aveline 亲自参与的对话。
*   **复现步骤**:
    1. nightly 对同一目标日期先以 persona=aveline 强制生成每日总结
    2. Aveline 总结被追加为 source=aveline、type=daily_summary 的日记条目
    3. 随后以 persona=ling 生成，get_entries 同时读取三个 scope，format_diary_context 把 Aveline 自动总结完整放入Ling Prompt
    4. 重复运行 nightly 后比较两个 scope 的 diary_summary.json
*   **预期行为**:
    1. 角色只认领自己的直接聊天、主动行为和随手片段
    2. 共享客观资料只能作为背景，任何自动总结都不能再次成为生成素材
    3. Aveline 与Ling拥有明显不同的叙事选择和语言风格
*   **实际行为**:
    1. 2026-08-20 两篇总结逐字相同，2026-08-22 两篇以相同顺序复述凌晨健康咨询和晚间物理话题
    2. 两边聊天轮数和原始 event_id 明显不同，证明不是聊天目录直接共用
    3. 旧 nightly 仅在逐字相同时提高 temperature 重试，未移除 Prompt 中的污染正文
*   **根因**:
    1. format_diary_context 未按 type、thought 或 persona 过滤 JournalEntry
    2. nightly 固定先生成 Aveline 再生成Ling，使自动总结回灌具有稳定方向；重复执行后形成双向反馈
    3. 两套角色 Prompt 高度同构，且未明确共享背景不能用于认领第一人称经历
*   **修复方案**:
    1. 建立日记原始片段白名单并排除全部自动总结和其他 persona 条目
    2. 收紧聊天历史 scope 与事件类型过滤
    3. 分别重写两名角色的 system/user Prompt
    4. 新增字符归一化相似度防护，在保存前完成身份边界重写
    5. 重生成问题日期并同步更新摘要文件与自动总结条目
*   **验证**:
    1. `新增 4 组隔离单测，连同解析测试共 6 项通过`
    2. `既有 nightly 日记验证 26 项全部通过`
    3. `重生成后四天跨角色相似度均低于 0.15，且每日日记正文均不相同`

### QR-20260825-SLEEP-PLAN-ALL-CHECKED 夜间生成的用户计划被旧晚安信号全部勾选 (2026-08-25)
*   **问题描述**: 用户当天计划生成后很快在 Android 中全部显示为勾选，但用户并未完成这些任务。
*   **复现步骤**:
    1. 用户发送晚安并进入晚安低打扰
    2. 夜间处理在稍后生成当前日期的新计划
    3. Active Care 下一轮仍从历史中识别同一条晚安并调用睡眠结算
    4. 打开 Android 学习计划页面查看 checkbox
*   **预期行为**:
    1. 同一条晚安只触发一次睡眠结算
    2. 睡眠信号不能修改在其后才生成的计划
    3. 跳过和完成在客户端中具有不同显示语义
*   **实际行为**:
    1. 2026-08-25 05:27 生成 19 项计划，05:36 被同一条 02:01 晚安信号全部标记为 skipped
    2. 后端把 skipped 写成 [x] 加跳过标记，Android 仅依据 [x] 显示为已完成
*   **根因**:
    1. 晚安意图入口缺少已处理信号屏障
    2. 睡眠结算缺少计划 generated_at 与 sleep_ts 的因果顺序检查
    3. Markdown 传输格式把 skipped 和 completed 压缩成同一个 checkbox 布尔值
*   **修复方案**:
    1. 增加晚安信号幂等判断并将 sleep_ts 传给计划结算
    2. 拒绝结算晚于 sleep_ts 生成的计划
    3. skipped 使用未勾选 Markdown，并兼容解析历史错误格式
*   **验证**:
    1. `新增回归测试覆盖旧信号不得清空新计划、重复晚安不得二次处理、skipped 不得输出为 [x]`
    2. `计划相关 pytest 5 项通过，Ruff 通过，今日 19 项数据确认均为 pending`

### QR-20260825-SHARED-DETERMINISTIC-PLANNING 用户与角色每日计划生成逻辑分叉且依赖日常 LLM (2026-08-25)
*   **问题描述**: 同一天重复生成用户或角色计划时结果可能变化，用户计划生成和检查点重排还产生额外 LLM 调用，Journal 与 Workspace 两套任务来源也可能漂移。
*   **复现步骤**:
    1. 强制重新生成同一天的用户计划并比较项目、时间与顺序
    2. 为同一角色重复生成同一天计划并比较活动槽位
    3. 触发中午或傍晚检查点，观察计划模型调用与状态变化
    4. 比较 Study Daily plan.md 与 Workspace daily tasks 的自动生成来源
*   **预期行为**:
    1. 同一日期、owner 和事实输入产生稳定计划，不同日期允许小幅变化
    2. 固定事项优先且不冲突，总时长和事项数量受到日类型容量约束
    3. 检查点只重排剩余事项，不误把未完成项目变成 completed
    4. Journal 是用户主计划真源，Workspace 只消费快照且自动计划不批量建硬提醒
*   **实际行为**:
    1. 用户生成与重排依赖 LLM、JSON 解析和失败重试
    2. 角色模板池依赖 Python random 选项与时长
    3. Workspace 根据学习摘要另行生成任务并逐项创建提醒
    4. 睡眠 skipped 项无法可靠区分自动延期与用户主动跳过
*   **根因**:
    1. 缺少跨用户与角色计划共用的候选、评分和容量排程抽象
    2. 计划项缺少来源键、滚动次数和结算原因等兼容元数据
    3. Journal 与 Workspace 的主从边界没有在代码和文档中明确
*   **修复方案**:
    1. 实现共享稳定哈希评分与冲突感知的贪心容量排程
    2. 用户与角色分别从真实学习事实或 YAML 业务模板构建候选并复用同一引擎
    3. 检查点改为确定性剩余计划重排，睡眠结算记录 sleep 原因并限制次日滚动次数
    4. Workspace 自动任务只镜像 Journal 主计划，保留手动 Workspace 提醒行为
*   **验证**:
    1. `新增测试覆盖稳定性、日期变化、固定优先、无冲突、容量、重复惩罚、真实候选、手动保留、滚动上限和日类型策略`
    2. `计划改造定向 pytest 35 项全部通过，Ruff 与独立验证脚本通过`
    3. `宽跑发现的 21 项失败均为计划改造范围外的既有角色消息策略兼容问题，已在更新记录中如实注明`
