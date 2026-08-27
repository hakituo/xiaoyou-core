# Auto Heal 自愈服务

运行时日志驱动的自动 bug 检测与修复系统。灵感来自 OpenAI Symphony，但更注重**运行时真实信号**（日志 error、业务指标异常）而非静态代码扫描。

## ⚠️ 安全警告

**本服务会修改你的源代码文件。** 请务必了解以下安全机制后再启用。

## 安全机制（7 层防护）

### 1. 受保护文件（可分析，不自动修改）
以下文件**可以被检查、分析、提建议**，但**不会自动修改**。系统会生成 Markdown 建议报告供人工审阅：

| 文件 | 原因 |
|------|------|
| `main.py` | 程序入口 |
| `core/core_engine/lifecycle_manager.py` | 服务生命周期管理 |
| `core/core_engine/event_bus.py` | 事件总线 |
| `core/lifecycle/lifespan.py` | 启动/关闭编排 |
| `core/services/auto_heal/*` | 自愈服务自身（防止自修改） |
| `core/utils/logger.py` | 日志系统 |
| `core/utils/log_sanitizer.py` | 日志脱敏 |
| `core/utils/error_handler.py` | 错误处理 |
| `config/integrated_config.py` | 全局配置 |

如需修改黑名单，编辑 `patch_manager.py` 中的 `_PROTECTED_FILES` 集合。

### 2. 目录白名单
只能修改以下目录中的文件：
- `core/`
- `config/`
- `routers/`
- `memory/`

其他目录（如 `scripts/`、`tests/`、`cpp_scheduler/`）的文件不会被触碰。

### 3. 文件扩展名白名单
只能修改以下类型的文件：
- `.py` — Python 源码
- `.yaml` / `.yml` — YAML 配置
- `.json` — JSON 配置
- `.toml` — TOML 配置

`.exe`、`.dll`、`.so`、`.db` 等二进制文件不会被触碰。

### 4. 每日补丁数量上限
- **每天最多应用 10 个补丁**（`_MAX_DAILY_PATCHES = 10`）
- **每个文件每天最多修改 3 次**（`_MAX_PATCHES_PER_FILE = 3`）
- 超过上限后，补丁仍然会生成但不会应用，等待次日重置

### 5. 补丁体积限制
- 单个补丁最大 **512KB**（`_MAX_PATCH_SIZE_BYTES`）
- 超过此大小的补丁会被拒绝，防止 LLM 生成超大修改

### 6. 三重备份 + 回滚
每个补丁应用时：
1. **内存备份**：Patch 对象保存 `rollback_code`（原始代码完整副本）
2. **文件备份**：自动创建 `.auto_heal_backup` 文件（与原文件同目录）
3. **备份验证**：写入备份后立即读取验证，备份不正确则**中止操作**
4. **失败自动恢复**：应用补丁失败时，自动从内存备份恢复原文件
5. **一键回滚 API**：`POST /api/v1/auto-heal/patches/{id}/rollback`

### 7. 人工审批（默认）
- **默认 `auto_apply = False`**：补丁生成后需要人工审批才能应用
- 只有通过 API 主动调用 `apply` 才会写入文件
- 可通过配置设为 `auto_apply = True`，但**强烈不建议**

## 报告系统

每次自愈任务完成后，系统会自动生成 **Markdown 格式的回顾报告**，保存在 `logs/auto_heal_reports/` 目录下。

### 报告类型

| 类型 | 说明 |
|------|------|
| `anomaly_detected` | 检测到异常 |
| `root_cause_found` | 定位到根因 |
| `patch_generated` | 补丁已生成，等待审批 |
| `patch_applied` | 补丁已应用 |
| `patch_rolled_back` | 补丁已回滚 |
| `suggestion_for_protected` | 受保护文件的建议报告（不自动修改） |
| `daily_summary` | 每日总结 |

### 报告内容示例

```markdown
# 自愈报告: 受保护文件问题建议: core/core_engine/lifecycle_manager.py

| 字段 | 值 |
|------|-----|
| 报告ID | `a1b2c3d4e5f6` |
| 类型 | suggestion_for_protected |
| 时间 | 2026-05-01 14:30:00 |
| 异常ID | `f6e5d4c3b2a1` |
| 严重程度 | high |
| 涉及文件 | `core/core_engine/lifecycle_manager.py` |
| 受保护文件 | 是（仅建议，不自动修改） |
| 置信度 | 0.75 |

## 根因分析

在 initialize_default_services 方法中，服务注册顺序可能导致...

## 修复建议

建议在注册 aveline_service 之前先检查依赖...

## 结论

文件 `core/core_engine/lifecycle_manager.py` 是受保护的核心文件，
自愈服务不会自动修改。请根据上述分析手动修复。
```

### 报告 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/auto-heal/reports` | 获取报告列表（支持 `?type=suggestion_for_protected` 过滤） |
| GET | `/api/v1/auto-heal/reports/{id}` | 获取报告详情（Markdown 格式） |

## 工作流程

```
日志 Error
  → 错误回调 → AnomalyDetector（聚类/去重/指纹计算）
  → 规则匹配（5种规则）→ AnomalyEvent
  → RootCauseAnalyzer（traceback → 源码定位 → LLM 分析）
  → 判断是否受保护文件？
      ├── 是 → 生成建议报告（Markdown）→ 人工审阅
      └── 否 → PatchGenerator（LLM 生成修复代码 + diff）
              → PatchSandbox（语法检查 + import 验证 + ruff 检查）
              → 生成补丁报告 → 人工审批 / 自动应用
              → Workspace.write_source_file()（安全沙箱写入 + 自动备份）
              → 可一键回滚
```

## 模型配置

在 `model_config.json` 中配置自愈服务使用的模型：

```json
{
  "auto_heal_models": {
    "analysis": "cloud:siliconflow:Qwen/Qwen3.5-27B",
    "patch_generation": "cloud:siliconflow:Qwen/Qwen3.5-27B"
  }
}
```

- `analysis`：根因分析使用的模型（需要推理能力强）
- `patch_generation`：补丁生成使用的模型（需要代码生成能力强）

## 异常检测规则

| 规则名 | 类型 | 条件 | 自动修复 |
|--------|------|------|---------|
| `error_burst` | 错误暴增 | 5分钟内 >15 次错误 | ❌ |
| `repeated_same_error` | 重复异常 | 10分钟内同一错误 >5 次 | ✅ |
| `active_care_flood` | 业务指标异常 | 一天主动关怀 >50 条 | ✅ |
| `llm_timeout_cluster` | 错误聚集 | 10分钟内 LLM 超时 >5 次 | ✅ |
| `service_unhealthy` | 服务降级 | 有服务不健康 | ❌ |

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/auto-heal/stats` | 获取统计信息 |
| GET | `/api/v1/auto-heal/patches` | 获取所有补丁 |
| GET | `/api/v1/auto-heal/patches/pending` | 获取待审批补丁 |
| GET | `/api/v1/auto-heal/patches/{id}` | 获取补丁详情（含 diff） |
| POST | `/api/v1/auto-heal/patches/{id}/apply` | 应用补丁 |
| POST | `/api/v1/auto-heal/patches/{id}/rollback` | 回滚补丁 |
| POST | `/api/v1/auto-heal/patches/{id}/reject` | 拒绝补丁 |
| POST | `/api/v1/auto-heal/check` | 手动触发异常检查 |
| GET | `/api/v1/auto-heal/reports` | 获取报告列表 |
| GET | `/api/v1/auto-heal/reports/{id}` | 获取报告详情（Markdown） |
| POST | `/api/v1/auto-heal/source/read` | 读取源码文件 |
| POST | `/api/v1/auto-heal/source/write` | 写入源码文件 |

## 配置

在 `config/integrated_config.py` 中添加（可选）：

```python
class AutoHealSettings(BaseSettings):
    enabled: bool = True          # 是否启用自愈服务
    auto_apply: bool = False      # 是否自动应用补丁（强烈建议 False）
    check_interval: float = 30.0  # 检查间隔（秒）
```

## 紧急恢复

如果自愈服务导致了问题：

1. **立即禁用**：在配置中设置 `enabled = False` 并重启
2. **回滚补丁**：调用 `POST /api/v1/auto-heal/patches/{id}/rollback`
3. **手动恢复**：找到 `.auto_heal_backup` 文件，手动覆盖回原文件
4. **最坏情况**：用 git 恢复：`git checkout -- <file>`

## 文件结构

```
core/services/auto_heal/
├── __init__.py              # 模块导出
├── models.py                # 数据模型（AnomalyEvent, Patch, HealReport 等）
├── anomaly_detector.py      # 异常检测器（5种规则 + 错误指纹）
├── root_cause_analyzer.py   # 根因分析器（traceback 解析 + LLM 分析）
├── patch_generator.py       # 补丁生成器（LLM 生成代码 + diff）
├── patch_sandbox.py         # 补丁验证器（语法 + import + ruff）
├── patch_manager.py         # 补丁管理器（补丁的生成、验证、应用和回滚）
├── report_generator.py      # 报告生成器（生成、保存和管理自愈报告）
├── heal_service.py          # 自愈服务主类（编排 + 安全机制）
└── README.md                # 本文件
```
