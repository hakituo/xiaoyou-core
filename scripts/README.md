# scripts 目录说明

## 目录约定

- `scripts/doc_records/`
  - 正式维护脚本
  - 负责更新 `UPDATES.md` 与 `Question_Reviewer/` 分类文件夹
  - 包含：
    - `update_project_records.py`：日常维护入口，按类别追加新记录
    - `split_question_reviewer.py`：一次性拆分脚本，把旧 `Question_Reviewer.md` 按类别拆到 `Question_Reviewer/` 文件夹
    - `question_categories.py`：分类定义（类别文件名、显示名、关键词），新增/调整类别改这里
- `scripts/qq/`
  - QQ 侧数据维护脚本
  - 负责修复或清理 QQ 会话相关的历史数据
- `scripts/git/`
  - Git 提交前检查脚本
  - 负责调用 `gitleaks` 扫描暂存区敏感信息
- `scripts/`
  - 保留现有通用维护脚本
  - 暂不大规模迁移旧文件，避免破坏历史调用路径

## 当前约束

- 新增“项目维护类脚本”优先放到带语义的子目录里，不要继续直接堆在 `scripts` 根目录
- `UPDATES.md` 与 `Question_Reviewer/` 的更新统一走 `scripts/doc_records/update_project_records.py`，不要再手工新建/编辑 `Question_Reviewer/` 里的 `.md` 文件
- 分类定义统一在 `scripts/doc_records/question_categories.py` 维护，不要在其他脚本里重复定义
- 验证脚本放在 `tests/scripts/`，不要把正式工具和验证脚本混在一起

## 文档记录脚本

示例命令：

```powershell
venv_core\Scripts\python.exe scripts\doc_records\update_project_records.py `
  --payload-file scripts\doc_records\payload_update_doc_rules.json `
  --project-root D:\AI\xiaoyou-core
```

`question_reviewers` 数组里的 entry 可选 `category` 字段（如 `01_active_care`）指定分类文件名，缺省时按标题关键词自动归类。

