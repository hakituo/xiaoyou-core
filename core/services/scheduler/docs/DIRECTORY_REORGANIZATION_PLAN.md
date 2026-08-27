# scheduler 目录整理规划

**规划日期**: 2026-04-26
**规划版本**: 1.0

## 一、现状分析

### 1.1 当前目录结构

```
core/services/scheduler/
├── README.md
├── REFACTORING_NOTES.md
├── REFACTORING_PLAN_CPP_SCHEDULER_ENGINE.md
├── async_scheduler.py
├── async_task_wrapper.py
├── bio_state.py
├── bio_system_manager.py
├── circuit_breaker.py
├── cpp_client.py
├── cpp_config_builder.py
├── cpp_llm_handler.py
├── cpp_scheduler_engine.py
├── cpu_task_processor.py
├── error_utils.py
├── gpu_resource_manager.py
├── health_monitor.py
├── inference_executor.py
├── inference_stats.py
├── inference_utils.py
├── kv_cache_manager.py
├── llm_model_manager.py
├── nvidia_smi_monitor.py
├── python_llm_handler.py
├── scheduler_lifecycle.py
├── scheduler_wrapper.py
├── startup_config.py
├── task_scheduler.py
├── task_scheduler_adapter.py
└── 评估报告.md
```

### 1.2 问题

1. **文件过多**：28 个文件混在一起，难以管理
2. **分类不清**：不同功能的文件没有分类
3. **文档混杂**：文档文件和代码文件混在一起
4. **DLL 文件**：用户提到 DLL 文件乱在一起（需要确认具体位置）

## 二、整理方案

### 2.1 建议的目录结构

```
core/services/scheduler/
├── README.md                           # 主文档
├── cpp_scheduler_engine.py             # 主引擎
├── scheduler_wrapper.py                # C++ 绑定包装
│
├── model/                              # 模型管理
│   ├── __init__.py
│   ├── llm_model_manager.py           # LLM 模型管理
│   └── gpu_resource_manager.py        # GPU 资源管理
│
├── inference/                          # 推理执行
│   ├── __init__.py
│   ├── inference_executor.py          # 推理执行器
│   ├── cpp_llm_handler.py             # C++ 后端处理
│   ├── python_llm_handler.py          # Python 后端处理
│   ├── inference_stats.py             # 推理统计
│   └── inference_utils.py             # 推理工具
│
├── lifecycle/                          # 生命周期
│   ├── __init__.py
│   ├── scheduler_lifecycle.py         # 调度器生命周期
│   └── health_monitor.py              # 健康监控
│
├── bio/                                # 生物系统
│   ├── __init__.py
│   ├── bio_state.py                   # 生物状态
│   └── bio_system_manager.py          # 生物系统管理
│
├── utils/                              # 工具模块
│   ├── __init__.py
│   ├── error_utils.py                 # 错误处理
│   ├── circuit_breaker.py             # 断路器
│   ├── kv_cache_manager.py            # KV Cache 管理
│   ├── nvidia_smi_monitor.py          # NVIDIA SMI 监控
│   └── startup_config.py              # 启动配置
│
├── task/                               # 任务调度
│   ├── __init__.py
│   ├── task_scheduler.py              # 任务调度器
│   ├── task_scheduler_adapter.py      # 任务调度适配器
│   ├── async_scheduler.py             # 异步调度器
│   ├── async_task_wrapper.py          # 异步任务包装
│   └── cpu_task_processor.py          # CPU 任务处理器
│
├── client/                             # 客户端
│   ├── __init__.py
│   ├── cpp_client.py                  # C++ 客户端
│   └── cpp_config_builder.py          # C++ 配置构建器
│
└── docs/                               # 文档
    ├── REFACTORING_NOTES.md
    ├── REFACTORING_PLAN_CPP_SCHEDULER_ENGINE.md
    └── 评估报告.md
```

### 2.2 整理原则

1. **按功能分类**：将文件按功能分组到不同的子目录
2. **保持兼容**：通过 `__init__.py` 保持导入路径兼容
3. **文档分离**：将文档文件移动到 `docs/` 子目录
4. **清晰命名**：子目录名称清晰表达其功能

## 三、实施步骤

### 3.1 准备阶段

1. **创建子目录**：创建所有需要的子目录
2. **创建 `__init__.py`**：为每个子目录创建 `__init__.py` 文件
3. **备份当前状态**：创建 Git 分支或备份

### 3.2 执行阶段

1. **移动文件**：按照规划移动文件到相应的子目录
2. **更新导入路径**：更新所有文件中的导入路径
3. **更新 `__init__.py`**：在 `__init__.py` 中导出必要的类和函数

### 3.3 验证阶段

1. **运行测试**：运行所有测试确保功能正常
2. **检查导入**：检查所有导入路径是否正确
3. **更新文档**：更新相关文档

## 四、风险评估

### 4.1 主要风险

| 风险 | 可能性 | 影响 | 应对措施 |
|------|--------|------|---------|
| 导入路径错误 | 高 | 高 | 充分测试，保持兼容 |
| 循环依赖 | 中 | 中 | 清晰的依赖关系图 |
| 功能缺失 | 低 | 高 | 详细测试用例 |

### 4.2 回滚计划

如果整理后出现严重问题：

1. **立即回滚**：恢复到备份状态
2. **分析问题**：定位问题原因
3. **修复问题**：修复后重新整理

## 五、预期收益

### 5.1 代码组织

- **清晰分类**：文件按功能分组，易于查找
- **易于维护**：相关文件集中在一起
- **易于扩展**：新功能可以轻松添加到相应的子目录

### 5.2 开发效率

- **快速定位**：根据功能快速找到相关文件
- **减少冲突**：不同功能的文件分离，减少修改冲突
- **易于理解**：目录结构清晰，易于理解

## 六、总结

本规划提出了将 scheduler 目录按功能分类整理的方案，将 28 个文件整理到 8 个子目录中，使目录结构更清晰、更易于维护。整理过程需要谨慎进行，确保所有功能正常。

**建议**：由于这是一个较大的改动，建议先与用户讨论后再执行，避免引入不必要的风险。
