# scripts 目录说明

## 目录约定

- `scripts/doc_records/`
  - 正式维护脚本
  - 负责维护 `docs/updates/` 更新日志（按日期一天一个文件）与 `Question_Reviewer/` 分类文件夹
  - 包含：
    - `update_project_records.py`：按日期把 updates 记录写入 `docs/updates/YYYY/MM/YYYY-MM-DD.md`，并按类别追加 Question_Reviewer 记录（自动化场景使用，如模型注册 `--record`）
    - `split_updates_to_daily.py`：一次性把根 `UPDATES.md` 拆到 `docs/updates/`；`--index` 重建索引与根入口，`--check` 校验日期文件结构
    - `split_question_reviewer.py`：一次性拆分脚本，把旧 `Question_Reviewer.md` 按类别拆到 `Question_Reviewer/` 文件夹
    - `question_categories.py`：分类定义（类别文件名、显示名、关键词），新增/调整类别改这里
- `scripts/qq/`
  - QQ 侧数据维护脚本
  - 负责修复或清理 QQ 会话相关的历史数据
- `scripts/git/`
  - Git 提交前检查脚本
  - 负责调用 `gitleaks` 扫描暂存区敏感信息
- `scripts/model_registry/`
  - 云端模型注册脚本
  - `register_cloud_model.py`：交互式接入新模型（选 provider → 在线搜/手填模型 → 自动写入全部注册点）
  - 注册点：`config/settings_model.py` 的 `PROVIDER_DEFAULT_MODELS`、`core/llm/model_capabilities.py` 的
    `VISION_MODEL_KEYWORDS`、视觉路由与 OpenRouter 连通性验证脚本，可选改 `model_routing.yaml` 的默认模型
  - 验证脚本：见 `tests/scripts/model_registry/verify_register_cloud_model.py`
- `scripts/`
  - 保留现有通用维护脚本
  - 暂不大规模迁移旧文件，避免破坏历史调用路径

## 当前约束

- 新增“项目维护类脚本”优先放到带语义的子目录里，不要继续直接堆在 `scripts` 根目录
- 接入新云端模型一律走 `scripts/model_registry/register_cloud_model.py`，不要手改注册点；
  手改容易漏掉多模态名单或验证脚本，出现“能选但发图走 VL 中转”的半成品注册
- 更新日志按日期归档：新记录直接写 `docs/updates/YYYY/MM/YYYY-MM-DD.md`（不存在则创建），不要回头改历史日期文件；根 `UPDATES.md` 只是入口，索引 `docs/updates/README.md` 由 `split_updates_to_daily.py --index` 重建
- `Question_Reviewer/` 的更新统一走 `scripts/doc_records/update_project_records.py`，不要再手工新建/编辑里面的 `.md` 文件
- 分类定义统一在 `scripts/doc_records/question_categories.py` 维护，不要在其他脚本里重复定义
- 验证脚本放在 `tests/scripts/`，不要把正式工具和验证脚本混在一起

## 文档记录脚本

示例命令：

```powershell
venv_core\Scripts\python.exe scripts\doc_records\update_project_records.py `
  --payload-file scripts\doc_records\payload_update_doc_rules.json `
  --project-root D:\projects\xiaoyou
```

`question_reviewers` 数组里的 entry 可选 `category` 字段（如 `01_active_care`）指定分类文件名，缺省时按标题关键词自动归类。

日常写更新日志不需要 payload：直接编辑当天的 `docs/updates/YYYY/MM/YYYY-MM-DD.md`（不存在就按现有格式新建），写完跑一次
`venv_core\Scripts\python.exe scripts\doc_records\split_updates_to_daily.py --index` 刷新索引与根入口即可。

