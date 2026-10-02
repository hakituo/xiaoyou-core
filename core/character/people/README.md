# People Profile 模块

人物档案模块维护用户自身、外部人物及 Aveline/Ling 角色档案。Nightly 入口采用薄门面，具体职责如下：

| 文件 | 职责 |
|------|------|
| `extractor.py` | 增量总流程、共享 LLM 重试和兼容委托 |
| `conversation_source.py` | 提取水位、原始 JSONL 对话读取、轮次分批 |
| `signal_gate.py` | 汇总蒸馏元数据，以时间窗和零 API 规则筛选候选批次 |
| `external_profile_service.py` | 外部 `PERSON` 档案提取、去重、更新与创建 |
| `role_update_service.py` | Aveline/Ling `ROLE` 档案演化提取与事实持久化 |
| `manager.py` | 档案加载、缓存、查询与保存 |
| `models.py` | 档案数据模型 |

`PeopleProfileExtractor` 不直接扫描文件、解析业务 JSON 或写入 `KnownFact`。手动调用不传 `memory_managers` 时保留全量提取；nightly 传入所有记忆 scope 后启用蒸馏信号门控，无线索时为 0 次 LLM。
