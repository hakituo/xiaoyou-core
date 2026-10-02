# Maintenance (维护工具)

## 概述

维护工具目录包含Xiaoyou-Core项目的各种维护、诊断、清理和优化工具。这些工具用于系统健康检查、问题排查、代码分析、数据整理等维护任务。

## 目录结构

```
maintenance/
├── check_diffusers.py         # 检查Diffusers库配置
├── check_imports.py           # 检查导入依赖
├── check_runtime.py           # 检查运行时环境
├── code_semantic_index.py     # 代码语义索引
├── debug_import.py            # 调试导入问题
├── diagnose_backend.py        # 后端诊断工具
├── find_large_files.py        # 查找大文件
├── inspect_dll.py             # 检查DLL依赖
├── probe_local_llm.py         # 探测本地LLM
├── verify_build_config.py     # 验证构建配置
├── README.md                  # 本文档
├── backend_tidy_backlog_2026-03-06.md # 后端整理待办
├── data_organization_execution_plan_claude_style.md # 数据整理计划
└── hybrid_memory_analysis_playbook.md # 混合记忆分析手册
```

## 工具分类

### 1. 诊断工具

#### diagnose_backend.py

后端服务诊断工具，用于检查后端服务状态。

**功能**:
- HTTP服务器健康检查
- WebSocket连接测试
- 系统状态API检查
- 服务状态验证

**使用方法**:

```bash
python maintenance/diagnose_backend.py
```

**输出示例**:

```
✅ [HTTP Server]: Status: 200
✅ [Health API]: Response received
   - Service llm: healthy
   - Service tts: healthy
   - Service stt: healthy
✅ [System Stats API]: Data received
✅ [WebSocket]: Connected successfully
```

#### check_runtime.py

运行时环境检查工具，用于验证核心服务功能。

**功能**:
- 核心引擎初始化测试
- 生命模拟服务测试
- MVP核心服务测试
- 数据库连接测试

**使用方法**:

```bash
python maintenance/check_runtime.py
```

#### check_imports.py

导入依赖检查工具，用于验证Python导入是否正常。

**功能**:
- 检查核心模块导入
- 检查服务模块导入
- 检查工具模块导入
- 生成导入报告

**使用方法**:

```bash
python maintenance/check_imports.py
```

#### debug_import.py

导入问题调试工具，用于排查导入错误。

**功能**:
- 逐个测试导入
- 显示详细错误信息
- 提供修复建议

**使用方法**:

```bash
python maintenance/debug_import.py
```

### 2. 检查工具

#### check_diffusers.py

Diffusers库配置检查工具。

**功能**:
- 检查Diffusers版本
- 验证模型路径
- 检查CUDA支持
- 验证Pipeline配置

**使用方法**:

```bash
python maintenance/check_diffusers.py
```

#### verify_build_config.py

构建配置验证工具。

**功能**:
- 验证CMake配置
- 检查编译选项
- 验证依赖版本
- 检查环境变量

**使用方法**:

```bash
python maintenance/verify_build_config.py
```

### 3. 探测工具

#### probe_local_llm.py

本地LLM探测工具。

**功能**:
- 探测可用LLM模型
- 检查模型加载状态
- 测试推理功能
- 测量性能指标

**使用方法**:

```bash
python maintenance/probe_local_llm.py
```

#### inspect_dll.py

DLL依赖检查工具。

**功能**:
- 检查DLL依赖关系
- 验证CUDA库
- 检查Python扩展
- 生成依赖报告

**使用方法**:

```bash
python maintenance/inspect_dll.py
```

### 4. 分析工具

#### code_semantic_index.py

代码语义索引工具。

**功能**:
- 构建代码语义索引
- 分析代码结构
- 生成依赖图
- 支持代码搜索

**使用方法**:

```bash
python maintenance/code_semantic_index.py
```

#### find_large_files.py

大文件查找工具。

**功能**:
- 扫描项目目录
- 查找大文件
- 按大小排序
- 生成清理建议

**使用方法**:

```bash
python maintenance/find_large_files.py
```

**输出示例**:

```
Large files (> 100MB):
1. models/llm/qwen-7b.gguf (4.2GB)
2. models/vision/qwen-vl.bin (2.8GB)
3. cache/embeddings/cache.bin (512MB)
```

## 文档

### backend_tidy_backlog_2026-03-06.md

后端整理待办清单，记录需要整理和优化的后端代码。

**内容**:
- 待重构模块列表
- 技术债务记录
- 优化建议
- 优先级排序

### data_organization_execution_plan_claude_style.md

数据整理执行计划，详细说明数据整理的步骤和方法。

**内容**:
- 数据分类标准
- 整理流程
- 迁移计划
- 验证方法

### hybrid_memory_analysis_playbook.md

混合记忆分析手册，记录记忆系统的分析方法。

**内容**:
- 记忆结构分析
- 权重计算方法
- 检索优化策略
- 性能调优指南

## 使用场景

### 1. 系统启动前检查

```bash
# 检查运行时环境
python maintenance/check_runtime.py

# 检查导入依赖
python maintenance/check_imports.py

# 诊断后端服务
python maintenance/diagnose_backend.py
```

### 2. 问题排查

```bash
# 调试导入问题
python maintenance/debug_import.py

# 检查DLL依赖
python maintenance/inspect_dll.py

# 探测本地LLM
python maintenance/probe_local_llm.py
```

### 3. 性能优化

```bash
# 查找大文件
python maintenance/find_large_files.py

# 构建代码索引
python maintenance/code_semantic_index.py

# 检查Diffusers配置
python maintenance/check_diffusers.py
```

### 4. 构建验证

```bash
# 验证构建配置
python maintenance/verify_build_config.py
```

## 最佳实践

### 定期维护

建议定期运行以下维护任务：

| 任务 | 频率 | 工具 |
|------|------|------|
| 环境检查 | 每周 | `check_runtime.py` |
| 依赖检查 | 每月 | `check_imports.py` |
| 大文件扫描 | 每月 | `find_large_files.py` |
| 后端诊断 | 出现问题时 | `diagnose_backend.py` |

### 问题排查流程

1. **导入错误**: 使用 `debug_import.py` 定位问题
2. **服务异常**: 使用 `diagnose_backend.py` 检查服务状态
3. **性能问题**: 使用 `find_large_files.py` 检查资源占用
4. **LLM问题**: 使用 `probe_local_llm.py` 验证模型

## 相关文档

- [系统架构文档](../PROJECT_TECHNICAL_REFERENCE.md)
- [测试系统文档](../tests/README.md)
- [核心层文档](../core/README.md)
