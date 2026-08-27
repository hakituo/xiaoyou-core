# Question_Reviewer 问题回顾索引

本目录由 `Question_Reviewer.md` 拆分而来，按问题类别归档。
新增记录请通过 `scripts/doc_records/update_project_records.py` 自动写入对应分类文件。

## 分类目录

| 文件 | 类别 | 条目数 |
|------|------|--------|
| [01_active_care.md](01_active_care.md) | Active Care 主动关怀 | 83 |
| [14_scheduler_phase_aware.md](14_scheduler_phase_aware.md) | Phase-Aware 调度器 | 4 |
| [03_cpp_scheduler.md](03_cpp_scheduler.md) | C++ 调度器与 GPU | 25 |
| [05_tts_stt_voice.md](05_tts_stt_voice.md) | TTS / STT / 语音 | 15 |
| [13_image_vision.md](13_image_vision.md) | 图片生成与视觉 | 15 |
| [02_android_frontend.md](02_android_frontend.md) | Android / 前端 | 25 |
| [06_qq_message_split.md](06_qq_message_split.md) | QQ 适配器与消息断句 | 21 |
| [08_websocket_network.md](08_websocket_network.md) | WebSocket 与网络 | 6 |
| [07_memory_system.md](07_memory_system.md) | 记忆系统 | 13 |
| [11_persona_character.md](11_persona_character.md) | Persona / 角色系统 | 9 |
| [12_diary_journal.md](12_diary_journal.md) | 日记与每日总结 | 6 |
| [16_life_simulation.md](16_life_simulation.md) | 生命模拟与自动进食 | 7 |
| [15_chat_agent.md](15_chat_agent.md) | 主对话 Agent | 32 |
| [04_llm_model.md](04_llm_model.md) | LLM 与模型调用 | 15 |
| [09_build_test_env.md](09_build_test_env.md) | 构建 / 测试 / 环境 | 30 |
| [17_misc.md](17_misc.md) | 其他 | 1 |
| **合计** |  | **307** |

## 分类规则

新增记录时，`update_project_records.py` 会按 entry 的 `category` 字段路由到对应文件；若未指定 `category`，则按标题关键词自动归类。
