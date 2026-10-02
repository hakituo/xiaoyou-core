# 工具领域清单

本清单由现有注册元数据整理；角色是否可用以 `config/tool_profiles.json` 和 `tool_access` 为准。完整工具定义不常驻发送。

| 领域 | 数量 | 工具 | 加载判断 |
|---|---:|---|---|
| core | 3 | `get_current_time`, `calculator`, `text_to_speech` | 按需 |
| information | 2 | `web_search`, `get_weather` | 按需 |
| daily_record | 3 | `record_daily_activity`, `get_daily_summary`, `update_sleep_record` | 按需 |
| journal | 4 | `write_diary`, `read_diary`, `read_daily_summary`, `read_monthly_summary` | 按需 |
| plan | 8 | `generate_tomorrow_plan`, `generate_today_plan`, `get_plan`, `add_plan_item`, `update_plan_item`, `remove_plan_item`, `mark_plan_item_status`, `get_character_daily_plan` | 按需 |
| todo | 1 | `manage_todo` | 所有角色常驻（查看/记一条/划掉/删除合一） |
| file | 3 | `aveline_daily_data`, `study_data_management`, `create_file` | 按需 |
| food | 7 | `buy_food`, `feed_food`, `list_food`, `show_inventory`, `crave_food`, `list_food_cravings`, `get_aveline_meals` | 按需 |
| shop | 4 | `browse_shop`, `buy_shop_item`, `show_gift_inventory`, `use_gift_item` | 按需 |
| study | 8 注册 / 7 默认启用 | `get_study_profile`, `search_knowledge_base`, `update_word_progress`, `word_quiz`, `get_current_focus_session`, `get_focus_session_summary`(兼容禁用), `enter_study_mode`, `exit_study_mode` | 按需；`get_current_focus_session` 已统一 current/recent/session 查询 |
| study_teaching | 4 | `study_get_context`, `study_record_teaching`, `study_record_answer`, `study_record_confusion` | 按需；与 study 分领域，避免单领域超过 search_tools 的 8 条返回上限 |
| reminder | 1 | `set_reminder` | 按需 |
| user_status | 4 | `record_body_metrics`, `add_user_status`, `remove_user_status`, `get_user_status` | 按需 |
| health | 1 | `query_health_data` | 按需 |
| memory_search | 3 | `search_memory`, `search_chat_history`, `query_person_profile` | 按需 |
| memory_write | 5 | `record_preference`, `record_experience`, `record_active_task`, `complete_active_task`, `record_summary` | 按需 |
| companion | 3 | `check_peer_status`, `get_bionic_state`, `update_character_state` | 现场状态仅叶常驻，其他按需或禁用 |
| communication | 2 | `notify_master`, `message_peer` | 同伴消息仅Aveline/Ling常驻，其他按需或禁用 |
| active_care | 5 | `adjust_active_care_frequency`, `pause_active_care`, `schedule_active_care_message`, `toggle_active_care`, `get_active_care_status` | 按需 |
| device_observe | 8 | `check_running_processes`, `look_at_screen`, `capture_phone_screen`, `get_device_location`, `get_app_usage_time`, `list_installed_apps`, `list_paired_bluetooth_devices`, `scan_bluetooth_devices` | 按需 |
| device_control | 6 | `force_stop_app`, `start_app`, `pair_bluetooth_device`, `unpair_bluetooth_device`, `set_wallpaper`, `set_app_limit` | 按需 |
| scene | 3 | `list_scenes`, `enable_scene`, `disable_scene` | 按需 |
| tool_discovery | 1 | `search_tools` | 通用常驻入口 |

共 89 个注册工具、23 个领域。新增工具必须补齐元数据，并明确角色可用范围和加载方式。禁用的兼容工具仍计入注册数量，但不会出现在模型可用 schema 中。
