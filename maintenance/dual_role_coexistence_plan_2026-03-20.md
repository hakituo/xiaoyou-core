# 双角色共存架构规划（Aveline ↔ Ling）

## 1. 目标

把当前“主角色 + 单向后台助手”的实现，收敛为“前台角色与后台角色可双向切换、双向感知、双向互动”的统一架构：

- 前台是 Aveline 时，后台是Ling；
- 前台是Ling时，后台是 Aveline；
- 两者共享同一套关系/仿生世界观，但保持各自独立对话记忆与人设语气；
- QQ 与 Web 行为一致，避免一端有互动、另一端没有互动的割裂。

## 2. 当前实现现状（代码级，2026-03-20 最新）

### 2.1 已落地能力

1. 前后台双向切换已可用：
   - 前台为 Aveline 时，后台自动映射Ling；
   - 前台为Ling时，后台自动映射 Aveline；
   - 运行时由 `role_runtime(front_role/back_role/back_user_id)` 统一解析。
2. 自然语言切前台已可用：
   - “让Ling到前台” -> `core_ling.json`
   - “让小澪到前台” -> `core_aveline.json`
3. 前后台执行链统一：
   - 主回复与后台建议都复用主程序 `chat_agent.stream_chat`，不是另起一套推理链。
4. 关系事件共享已增强：
   - 新增 `social_events`（饮食/关怀/切换/关系提及/后台建议）；
   - 写入后会注入前台 system context，前台可回答“你们最近关系怎么样”。
5. 会话级持久化已落地：
   - `social_events` 会按会话写入 `companion_data/dual_role/social_events/*.json`；
   - 重启后可恢复最近互动事件。
6. 事件识别已复用后端成熟链路：
   - 接入 `bert_analyzer.analyze_intent + analyze(分类/话题/权重)`；
   - 形成“后端语义优先 + 规则兜底 + 30秒去重”。

### 2.2 当前仍存在的不足

1. 后台协作仍偏“单条建议”：
   - 当前是每轮最多一条 `back_thought`，缺少连续多轮后台对话轨迹建模。
2. 关系评估仍偏事件堆叠：
   - 已有事件记忆，但“关系总结”尚未做时间衰减与强度分层。
3. 端侧一致性尚未完全收口：
   - `group_member_message` 仍主要在 `group_mode` 下显式输出；
   - QQ 侧“后台旁白可见/仅内化”开关还未正式配置化。
4. 规则配置化不足：
   - BERT 阈值、事件类型映射、去重窗口目前仍在代码常量中，调优成本偏高。

## 3. 目标形态（统一双角色模型）

定义统一运行时结构：

- FrontRole：当前对用户直出的角色（由 persona_filename 决定）。
- BackRole：当前后台协作角色（由角色映射表决定，Front 的互补角色）。
- SharedSocialState：关系值、共同吃饭、最近互动、双角色仿生快照（共享）。
- FrontHistory / BackHistory：两套独立会话历史（隔离）。

核心原则：

1. 角色互补映射固定且可配置（不是硬编码在 if/else）。
2. 前后台都能“知道对方存在”，但只允许 FrontRole 对用户直出。
3. BackRole 建议生成采用“稳定触发策略”替代随机触发（可按关键词 + 时间窗）。
4. 无论前台是谁，协作链路都走同一套函数，只是 Front/Back 参数互换。

## 4. 实施方案（分阶段）

### 阶段 A：角色路由抽象

在 AvelineService 增加角色路由解析：

- 输入：persona_filename + conversation_id
- 输出：
  - front_role_id（aveline 或 ling）
  - back_role_id（ling 或 aveline）
  - back_user_id（`${conversation_id}__bg__${back_role_id}`）

并把现有“ling_primary_mode 分支”替换为统一 `role_runtime` 分支。

### 阶段 B：后台建议生成通用化

把当前“Ling background interaction”抽成通用函数：

- `_generate_background_thought(front_role, back_role, user_input, social_state, model_hint, user_name)`

函数内部：

1. 根据 back_role 选择对应人设配置和 style retriever（Aveline/Ling 各一套）；
2. 构造后台短建议 prompt（同模板，不同角色词槽）；
3. 使用 back_user_id 写入后台独立历史；
4. 返回统一结构：`{speaker, role, thought, social_state}`。

### 阶段 C：前台注入模板统一

前台系统提示注入改为模板驱动，不再写死“你的助手/妹妹Ling”：

- `你当前前台角色：{front_name}；后台协作者：{back_name}`
- `后台建议：{thought}`
- `关系状态：{relationship_summary}`
- `仿生状态：{front_bio}/{back_bio}`

### 阶段 D：事件与端侧一致性

统一发送 `group_member_message`（含 source=background）：

- Web：保持展示；
- QQ：新增可配置开关（默认关），可选择显示“后台旁白”或仅内化进前台回复。

## 5. 验收标准

1. 切到Ling后，连续 10 轮对话都能在系统日志看到 Aveline 后台建议生成记录。
2. 切到 Aveline 后，连续 10 轮对话都能看到Ling后台建议记录。
3. 两个方向下，前后台 user_id 独立，短期历史文件不混用。
4. social_state 的关系值与仿生状态在两个方向都持续更新。
5. QQ 与 Web 对“是否展示后台消息”的差异仅来自开关，不来自后端逻辑缺失。

## 6. 当前结论（更新）

“彼此不知道彼此存在”的核心问题已从架构层面被打通：  
当前已进入“可用版双向联动”，并具备共享事件记忆与重启恢复能力。  
现阶段瓶颈从“是否联动”转为“联动质量与一致性”。

## 7. 下一步实施清单（按优先级）

### P0：关系总结质量提升（本周先做）

1. 引入关系时间衰减模型：
   - 近24小时事件权重更高，历史事件逐步衰减；
   - 区分事件类型系数（meal/care/background_chat/switch）。
2. 输出结构化关系摘要：
   - 增加 `relationship_summary` 字段（升温中/稳定亲密/轻微疏离）；
   - 前台回答关系问题时优先使用摘要 + 最近1~2条证据事件。
3. 阈值配置化：
   - 将 BERT 置信度阈值、去重窗口、事件权重迁移到统一配置源，减少硬编码调参。

### P1：后台协作连续性提升

1. 从“单条建议”升级为“短会话片段”：
   - 支持后台角色连续2~3轮内部协商；
   - 前台仅消费摘要，不直接暴露全部内部细节。
2. 增加后台触发策略：
   - 结合语义触发 + 时间窗 + 事件强度，而非纯关键词/固定概率。

### P1：端侧一致性与可控展示

1. QQ/Web 统一后台展示策略：
   - 新增显式配置：`show_background_messages`；
   - 支持“仅内化到前台回复 / 额外展示后台旁白”两种模式。
2. 统一观测指标：
   - 记录“后台建议命中率、前台引用率、关系问答一致性”。

### P2：治理与维护

1. 建立双角色回归用例：
   - 覆盖“切前台、问关系、饮食互动、重启恢复”。
2. 文档同步：
   - `UPDATES.md` 记录增量；
   - 技术参考文档补充 dual_role 数据流和配置项说明。
