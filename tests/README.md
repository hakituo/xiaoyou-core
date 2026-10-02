# Xiaoyou Core 测试与工具目录 (tests/)

本目录存放 Xiaoyou Core 的测试与诊断工具。已于 2026-07-04 做过一次全面整理，删除约 250 个一次性验证脚本，目录结构如下。

## 目录结构

```
tests/
├── benchmark/          # 性能基准测试
├── character_daily/    # 角色日程 pytest 测试
├── diagnostics/        # 长期诊断与审计工具（手动运行，非 pytest）
├── integration/        # 集成测试
├── journal_plan/       # 日记/计划 pytest 测试
├── scheduler/          # 调度器测试
├── scripts/            # 测试相关的长期维护脚本
│   ├── doc_records/    # 配套验证 scripts/doc_records/
│   └── git/            # 配套验证 .githooks/
├── stress/             # 压力测试
├── tools/              # 工具相关测试
├── unit/               # pytest 单元测试（主力回归测试）
├── utils/              # 工具函数测试
├── README.md           # 本文件
└── conftest.py         # pytest 配置
```

---

## 1. 单元测试 (`unit/`)

主力 pytest 回归测试，覆盖核心模块。约 130+ 个测试文件。

运行：
```powershell
venv_core\Scripts\python.exe -m pytest tests/unit -v
```

部分测试需要环境变量或 GPU，未满足时自动 skip：
- `XIAOYOU_RUN_INTEGRATION_TESTS=1` - 集成测试
- `XIAOYOU_RUN_GPU_TESTS=1` - GPU 推理测试
- `XIAOYOU_RUN_IMAGE_TESTS=1` - 图像生成测试

---

## 2. 角色日程测试 (`character_daily/`)

角色日程与主动关怀的 pytest 测试，包括活动解析、计划执行、消息延后、睡眠恢复等。

---

## 3. 日记/计划测试 (`journal_plan/`)

日记总结与计划检查点的 pytest 测试。

---

## 4. 集成测试 (`integration/`)

跨模块集成测试。

---

## 5. 调度器测试 (`scheduler/`)

C++ 调度器 Python 绑定的并发测试。

---

## 6. 压力测试 (`stress/`)

长期压力测试，验证内存与风格稳定性。

---

## 7. 工具测试 (`tools/`)

喂食工具 persona scope 等工具相关测试。

---

## 8. 工具函数测试 (`utils/`)

工具函数（如日志清理）测试。

---

## 9. 基准测试 (`benchmark/`)

LLM/TTS/内存优化的性能基准测试。

---

## 10. 诊断与审计工具 (`diagnostics/`)

**非 pytest 测试**，手动运行的长期诊断工具。包括：

| 类型 | 前缀 | 说明 |
|------|------|------|
| 审计 | `audit_*.py` | 系统 prompt、缓存、记忆等审计 |
| 检查 | `check_*.py` | ComfyUI、TTS、BERT、记忆状态检查 |
| 测量 | `measure_*.py` | 延迟、prompt 长度测量 |
| 基准 | `benchmark_*.py` | C++ 索引、热启动基准 |
| 调试 | `debug_*.py` | Persona、TTS、搜索调试 |
| 报告 | `report_*.py` | 记忆融合、离线评估报告 |
| BERT 评估 | `bert_*_test.py` | BERT 重要度/意图/速度评估 |
| 其他 | | 架构分析、移动端复现、smoke 测试等 |

---

## 11. 测试相关脚本 (`scripts/`)

测试相关的长期维护脚本：

| 文件 | 说明 |
|------|------|
| `audit_tests.py` | **长期维护工具**：扫描 tests/ 健康度（死引用、无 assert 的 test_*.py、一次性脚本蔓延、超大文件等） |
| `verify_tests_cleanup.py` | 验证 tests/ 目录清理优化是否成功 |
| `check_bert_load.py` | BERT 模型加载诊断 |
| `export_bge_onnx.py` | BGE 模型 ONNX 导出 |
| `ingest_knowledge.py` | 知识库导入 |
| `verify_qwen3_tts_gpu_optimization.py` | Qwen3 TTS GPU 优化验证 |
| `doc_records/verify_*.py` | 配套验证 `scripts/doc_records/` |
| `git/verify_git_tooling.py` | 配套验证 `.githooks/` 与 git 工具 |

---

## 如何运行

### 全量测试（并行，推荐）
`pyproject.toml` 的 `addopts` 已默认带 `-n 4`（pytest-xdist），直接裸跑即并行：
```powershell
venv_core\Scripts\python.exe -m pytest -q
```
实测（32 核 Windows）：串行 52s → `-n 4` 30s。**不要用 `-n auto`**：本机会起 32 个 worker，
每个都要重复 import 整套 core 重型依赖，反而退化到 72s 并暴露共享资源竞争。需要串行排查时：
```powershell
venv_core\Scripts\python.exe -m pytest -q -n 0
```

> ⚠️ 没装 `pytest-xdist` 的环境（例如只按旧 `requirements` 装的 `venv_cpu`）会因为 addopts 里的
> `-n` 直接报 `unrecognized arguments: -n`。两种解法：按 `requirements/base.txt` 装上
> `pytest-xdist`（已记录版本），或临时清空 addopts 跑：
> ```powershell
> python -m pytest -q -o addopts=""
> ```

### 运行单元测试
```powershell
venv_core\Scripts\python.exe -m pytest tests/unit -v
```

### 运行单个测试文件
```powershell
venv_core\Scripts\python.exe -m pytest tests/unit/test_chat_agent.py -v
```

### 运行诊断工具
```powershell
venv_core\Scripts\python.exe tests\diagnostics\audit_system_prompt.py
venv_core\Scripts\python.exe tests\diagnostics\check_comfy_status.py
```

### 运行 tests/ 健康审计
```powershell
venv_core\Scripts\python.exe tests\scripts\audit_tests.py
```

### 验证 tests/ 目录清理优化
```powershell
venv_core\Scripts\python.exe tests\scripts\verify_tests_cleanup.py
```

---

## 维护规范

1. **禁止一次性 verify_*.py 蔓延**：历史 fix 验证脚本不要新增到 tests/ 下。如需验证某个 fix，直接写到 `tests/unit/test_*.py` 作为长期回归测试，或在 `Question_Reviewer/` 中文字记录。

2. **禁止 tests/ 根目录散落 .py**：除 `conftest.py` 外，所有 .py 文件必须放入 `unit/`、`diagnostics/`、`scripts/` 等子目录。

3. **禁止 tests/scripts/ 顶层堆放一次性脚本**：`tests/scripts/` 顶层只允许白名单内的长期工具（见 `audit_tests.py` 的 `ALLOWED_SCRIPTS_TOPLEVEL`）。一次性数据脚本请放入正式 `scripts/` 目录的语义子目录。

4. **禁止 `.ps1/.bat` 启动脚本**：项目启动脚本统一放在 `start_scripts/`，tests/ 下不再保留。

5. **禁止 `__pycache__` 提交**：定期清理，`audit_tests.py` 会自动检测。

6. **新增 pytest 测试必须有 assert**：`audit_tests.py` 会检测用 `print` 不用 `assert` 的 test_*.py 并报警。

7. **资源隔离**：大型集成测试请加 `pytest.mark.skipif` 或在文件头检查环境变量。

8. **定期审计**：建议每月跑一次 `audit_tests.py`，及时发现死引用和质量退化。

9. **数据操作脚本归位**：`import_*`、`cleanup_*`、`migrate_*`、`fix_*` 等数据操作脚本应放在 `scripts/` 下语义子目录（`scripts/import/`、`scripts/cleanup/`、`scripts/migrate/`），不要放在 `tests/`。

---

## 历史清理记录

- **2026-09-22**：
  - **假测试清零**：6 个无 assert 的 `test_*.py` 归位——`test_model_path_fix.py` 删除（它把解析逻辑
    抄进测试里自证），其用例表转成 `tests/unit/test_openai_compat_model_id.py` 断言真实函数
    `routers.openai_compat._extract_cloud_model_id`；其余 5 个依赖真实后端/模型/本机数据的脚本移入
    `diagnostics/`（新增 obsidian 端点、meme 语义检索、VL 模型、人物档案提取器两个）并修正路径。
  - **并行化**：`pyproject.toml` 的 `addopts` 带 `-n 4`（pytest-xdist），全量 52s → 30s，
    详见上面「如何运行」。实测 `-n auto` 在 32 核机器上反而更慢。
  - **结果**：`audit_tests.py` 的「无 assert 的 test_*.py」警告由 6 条清零；本地裸跑不再必然报红。

- **2026-07-04**：
  - **目录清理**：删除约 250 个一次性验证脚本（verify_*_fix.py、verify_*_optimization*.py、test_*_refactor.py 等），整理 tests/ 根目录散落文件，迁移数据操作脚本到 `scripts/`，新增 `audit_tests.py` 长期维护工具。
  - **质量优化**：移动 41 个依赖外部资源的手动测试到 `diagnostics/`（pytest 不再收集），给 13 个无 assert 的 test_*.py 加 assert 改为真正 pytest 测试，改进 `audit_tests.py` 识别 unittest 风格 self.assertXxx，删除 3 个死引用测试。
  - **验证结果**：`audit_tests.py` 0 警告，`verify_tests_cleanup.py` 9 项全通过，`pytest tests/unit --collect-only` 收集 422 个测试 0 error。
  - 详见 `docs/updates/`（按日期归档的更新日志）。
