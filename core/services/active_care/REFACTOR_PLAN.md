# Active Care 重构计划

## 一、现状问题

1. **目录混乱**：42 个 .py 文件平铺在同一目录，无分层
2. **大文件未解耦**：多个文件超过 20K，职责混杂
3. **跨文件重复代码**：`_extract_json_block`、关键词映射等在多处重复

## 二、重构策略

分两阶段执行：
- **阶段 A**：大文件拆分（可多 agent 并行，互不依赖）
- **阶段 B**：目录整理（阶段 A 全部完成后统一执行，避免 import 冲突）

---

## 阶段 A：大文件拆分（8 个并行轨道）

### 轨道 1：activity_detector.py (40K) → activity_maps.py

| 项目 | 内容 |
|------|------|
| 源文件 | `activity_detector.py` |
| 拆出 | `activity_maps.py` — `PROCESS_CATEGORY_MAP`、`WINDOW_TITLE_KEYWORD_MAP`、`_is_system_process`、`_classify_by_process_name`、`_classify_by_window_title`、`_extract_relevant_keyword` |
| 保留 | `UserActivityDetector`、`ActivityDetectionResult`、`UserActivityCategory`、单例函数 |
| 预估减少 | ~355 行（文件从 40K 降到 ~8K） |
| 耦合 | 零耦合 — 映射表和分类方法全是纯数据/纯函数 |
| 兼容 | `activity_detector.py` import 新模块，原有 API 不变 |

### 轨道 2：decision.py (60K) → decision_output_parser.py + decision_instruction_builder.py

| 项目 | 内容 |
|------|------|
| 源文件 | `decision.py` |
| 拆出1 | `decision_output_parser.py` — `ACTIVE_CARE_OUTPUT_SCHEMA`、`PEER_CHAT_OUTPUT_SCHEMA`、`_build_output_format_schema`、`_build_peer_chat_output_format`、`_extract_json_block`、`_load_decision_dict`、`_normalize_decision_dict`、`_repair_json_text`、`_infer_should_send_from_keywords`、`_parse_decision_output`、`_build_regex_fallback`、`_parse_peer_chat_output`、`_build_peer_chat_regex_fallback` |
| 拆出2 | `decision_instruction_builder.py` — `_build_daily_routine_probe_instruction`、`_USER_COVERED_KEYWORDS`、`_detect_user_already_covered`、`_build_specific_instruction` |
| 保留 | `ActiveCareDecision` 类（`select_action_bandit`、`decide_proactive_content`、`decide_peer_chat`） |
| 预估减少 | ~530 行（文件从 60K 降到 ~35K） |
| 耦合 | JSON 解析零耦合；指令构建通过参数传入，弱耦合 |
| 兼容 | `ActiveCareDecision` 委托调用新模块函数 |

### 轨道 3：postprocessor.py (36K) → sleep_sanitizer.py + deduplicator.py + leak_detector.py

| 项目 | 内容 |
|------|------|
| 源文件 | `postprocessor.py` |
| 拆出1 | `sleep_sanitizer.py` — `SleepSanitizer` 全部（4 个静态方法） |
| 拆出2 | `deduplicator.py` — `Deduplicator` 全部（7 个静态方法） |
| 拆出3 | `leak_detector.py` — `LeakDetector` 全部（2 个静态方法） |
| 保留 | `ActiveCarePostprocessor`、`PostprocessContext`、`LanguageHandler` |
| 预估减少 | ~355 行（文件从 36K 降到 ~20K） |
| 耦合 | 零耦合 — 全是静态方法，无状态依赖 |
| 兼容 | `ActiveCarePostprocessor.postprocess` import 新模块类 |

### 轨道 4：prompt_builder.py (26K) → prompt_context_builders.py + topic_diversity.py

| 项目 | 内容 |
|------|------|
| 源文件 | `prompt_builder.py` |
| 拆出1 | `prompt_context_builders.py` — `_load_special_events_injection`、`_build_device_context_text`、`extract_known_sleep_time_fact`、`_build_bio_context_text`、`_build_health_reminder_prompt`、`_build_food_context_text`、`_build_study_context_text`、`_load_active_care_persona_cfg`、`_build_persona_active_care_style` |
| 拆出2 | `topic_diversity.py` — `detect_topic_category`、`_compute_keyword_overlap`、`check_topic_cooldown`、`build_topic_diversity_constraint` |
| 保留 | `build_active_care_prompt`、`_build_context_guard`、`_build_continuation_guard`、`_build_task_block_dynamic`、`_build_temporal_anchor`、`_build_dedup_constraint`、`PromptSection`、`ActiveCarePromptBuildResult` |
| 预估减少 | ~295 行（文件从 26K 降到 ~14K） |
| 耦合 | 上下文构建零耦合；话题多样性零耦合；模块级缓存需一并迁移 |
| 兼容 | `build_active_care_prompt` import 新模块函数 |

### 轨道 5：priority_analyzer.py (34K) → daily_push_priority.py + portrait_keyword_map.py

| 项目 | 内容 |
|------|------|
| 源文件 | `priority_analyzer.py` |
| 拆出1 | `daily_push_priority.py` — `build_daily_push_priority_candidates`、`_build_daily_push_priority_fallback`、`analyze_daily_push_priority` |
| 拆出2 | `portrait_keyword_map.py` — `_PORTRAIT_KEYWORD_MAP`、`_check_portrait_keyword_coverage`（同时合并 decision.py 中的 `_USER_COVERED_KEYWORDS` 和 `_detect_user_already_covered`） |
| 保留 | `PriorityAnalyzer`（`build_priority_focus`、`get_priority_probe_signature`、`get_priority_probe_cooldown_seconds`） |
| 预估减少 | ~335 行（文件从 34K 降到 ~16K） |
| 耦合 | 候选构建零耦合；LLM 分析弱耦合（需 bert_analyzer） |
| 兼容 | `PriorityAnalyzer` 委托调用新模块；`decision_instruction_builder.py`（轨道2）import `portrait_keyword_map.py` 替代内联映射 |
| **依赖** | 轨道 2（`portrait_keyword_map.py` 需要被 `decision_instruction_builder.py` 引用） |

### 轨道 6：decision_executor.py (21K) → action_builder.py + context_gatherer.py

| 项目 | 内容 |
|------|------|
| 源文件 | `decision_executor.py` |
| 拆出1 | `action_builder.py` — `build_available_actions`、`apply_action_overrides`、`_is_override_allowed`、`should_force_send` |
| 拆出2 | `context_gatherer.py` — `get_workspace_snapshot`、`get_recent_history`、`get_user_signal_and_intent`、`get_life_and_emotion_state`、`build_urgent_needs`、`sanitize_device_context`、`_parse_device_context_ts` |
| 保留 | `DecisionExecutor`（`select_action` 委托调用新模块） |
| 预估减少 | ~430 行（文件从 21K 降到 ~6K） |
| 耦合 | 动作构建零耦合（纯规则）；上下文收集弱耦合（需 intent_detector/life_sim） |
| 兼容 | `DecisionExecutor` 委托调用新模块函数 |

### 轨道 7：context.py (21K) → conversation_resolver.py + schedule_config_loader.py

| 项目 | 内容 |
|------|------|
| 源文件 | `context.py` |
| 拆出1 | `conversation_resolver.py` — `_is_active_care_candidate_conversation_id`、`_dedupe_conversation_ids`、`_get_active_conversation_ids_from_ws`、`_get_recent_conversation_ids_from_session_manager`、`_get_recent_conversation_ids_from_chat_history`、`get_candidate_conversation_ids`、`resolve_primary_conversation_id`、`_resolve_primary_conversation_id_uncached`、所有 persona token 方法 |
| 拆出2 | `schedule_config_loader.py` — `_get_daily_data_paths`、`_build_default_push_schedule`、`_build_default_quiet_hours`、`_cleanup_legacy_schedule_files`、`_load_schedule_configs`、`get_schedule_configs` |
| 保留 | `ActiveCareContext`（`get_latest_history`、`update_recent_user_message`、`get_recent_user_message`、`get_latest_device_context`） |
| 预估减少 | ~350 行（文件从 21K 降到 ~10K） |
| 耦合 | 会话解析零耦合；配置加载零耦合；缓存需归属到对应模块 |
| 兼容 | `ActiveCareContext` 委托调用新模块 |

### 轨道 8：peer_script_generator.py (34K) → peer_script_dispatch.py + peer_script_hooks.py

| 项目 | 内容 |
|------|------|
| 源文件 | `peer_script_generator.py` |
| 拆出1 | `peer_script_dispatch.py` — `_dispatch_script` |
| 拆出2 | `peer_script_hooks.py` — `_run_peer_post_hooks`、`_register_peer_chat_social_event`、`__build_patrol_persona` |
| 保留 | `PeerScriptGenerator`（`generate_peer_script`、`_load_peer_config`、`_gather_peer_context`、`_generate_script_llm`） |
| 预估减少 | ~220 行（文件从 34K 降到 ~22K） |
| 耦合 | 分发逻辑弱耦合（需 aveline_service）；hooks 弱耦合（需 host 引用） |
| 兼容 | `PeerScriptGenerator` 委托调用新模块 |

---

## 阶段 B：目录整理（阶段 A 完成后）

将 50+ 个文件按职责归入子目录：

```
active_care/
├── core/                    # 核心调度
│   ├── proactive_checker.py
│   ├── service.py
│   ├── proactive_loop.py
│   ├── watchdog.py
│   └── startup_handler.py
├── decision/                # 决策相关
│   ├── decision.py
│   ├── decision_executor.py
│   ├── decision_context.py
│   ├── decision_tools.py
│   ├── decision_output_parser.py
│   ├── decision_instruction_builder.py
│   └── action_builder.py
├── detection/               # 检测相关
│   ├── activity_detector.py
│   ├── activity_maps.py
│   ├── intent_detector.py
│   └── gate_scorer.py
├── postprocess/             # 后处理
│   ├── postprocessor.py
│   ├── sleep_sanitizer.py
│   ├── deduplicator.py
│   └── leak_detector.py
├── peer_chat/               # 双角色互聊
│   ├── peer_chat_scheduler.py
│   ├── peer_script_generator.py
│   ├── peer_script_dispatch.py
│   ├── peer_script_hooks.py
│   └── peer_chat_metrics.py
├── prompt/                  # Prompt 构建
│   ├── prompt_builder.py
│   ├── prompt_context_builders.py
│   └── topic_diversity.py
├── state/                   # 状态管理 (已存在)
│   └── ...
├── scheduling/              # 调度相关
│   ├── scheduler_logic.py
│   ├── schedule_adapter.py
│   ├── delayed_scheduler.py
│   └── delayed_task_handler.py
├── storage/                 # 存储相关
│   ├── storage.py
│   ├── state_persistence.py
│   └── user_profile_service.py
├── checker/                 # 检查器子模块
│   ├── checker_init_state.py
│   ├── checker_client_gate.py
│   └── checker_throttle.py
└── shared/                  # 共享工具
    ├── constants.py
    ├── vocabulary.py
    ├── context_gatherer.py
    ├── conversation_resolver.py
    ├── schedule_config_loader.py
    ├── daily_push_priority.py
    ├── portrait_keyword_map.py
    ├── response_generator.py
    ├── qq_connection_resolver.py
    ├── hardware_intent.py
    ├── persona_resolver.py
    ├── sleep_policy.py
    ├── sleep_session_manager.py
    ├── sleep_daily_record_sync.py
    ├── user_response_handler.py
    └── peer_user_activity_tracker.py
```

> 阶段 B 需要全局替换 import 路径，建议单独执行。

---

## 执行顺序

```
轨道1 ─┐
轨道2 ─┤
轨道3 ─┤  ← 8 个 agent 并行
轨道4 ─┤
轨道6 ─┤
轨道7 ─┤
轨道8 ─┘
轨道5 ──→ 等轨道2完成后启动（portrait_keyword_map 依赖）
         │
         ▼
      阶段 B：目录整理（全部完成后）
```

## 每个轨道的交付物

1. 新模块文件（含中文注释）
2. 修改后的源文件（委托调用 + 兼容入口）
3. py_compile 验证通过
4. 更新 README.md / UPDATES.md
5. 验证脚本更新
