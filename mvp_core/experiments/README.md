# MVP Core 实验与基准测试指南

本目录包含了 MVP Core 的各项性能测试和实验脚本。这些脚本用于验证系统的异步隔离能力、吞吐量以及在不同负载下的表现。

## 目录结构

- `comprehensive_experiment.py`: **核心实验脚本**。集成了并发性能对比、阻塞延迟测试、延迟分布统计和稳定性测试。支持模拟负载（Mock）和真实模型负载（Real）。
- `visualize_benchmark.py`: 用于生成测试结果的可视化图表。
- `mock_tts_server.py`: 用于模拟 TTS 服务的后台响应（供测试使用）。

## 实验结果

所有实验结果（JSON 数据和 PNG 图表）将统一保存在 `mvp_core/experiment_results` 目录下。

## 环境准备

请确保您已安装项目根目录下的依赖：

```bash
pip install -r ../requirements.txt
```

此外，运行真实实验需要 `matplotlib` 和 `numpy` 用于绘图：

```bash
pip install matplotlib numpy
```

## 模型准备

为了运行真实基准测试（Real Workload），您需要准备以下模型：

### 1. LLM 模型 (GGUF 格式)
推荐使用 **Qwen2.5-7B-Instruct** 的 GGUF 量化版本。
- **下载地址**: [HuggingFace](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF) 或 [ModelScope](https://modelscope.cn/models/qwen/Qwen2.5-7B-Instruct-GGUF)
- **推荐文件**: `qwen2.5-7b-instruct-q4_k_m.gguf`
- **存放建议**: 建议存放在 `models/llm/` 目录下。

### 2. Stable Diffusion 模型 (可选)
用于图像生成负载测试。
- **模型**: 任意 SD 1.5 或 SDXL 的 `.safetensors` 模型。
- **存放建议**: `models/img/check_point/`。

## 运行实验

现在所有实验都通过 `comprehensive_experiment.py` 统一运行。

### 基本用法

```bash
python comprehensive_experiment.py [参数]
```

### 参数说明

- `--mode`: 架构模式 (默认: `xy_core`)
  - `single_thread`: 单线程串行执行（基准线）。
  - `naive_async`: 普通异步执行（无调度器，受 GIL 影响严重）。
  - `xy_core`: 使用 GlobalTaskScheduler 进行任务调度和隔离。
  
- `--workload`: 负载类型 (默认: `mock`)
  - `mock`: 使用 CPU 空转模拟计算负载，无需下载模型。
  - `real`: 加载真实 LLM 和 SD 模型进行测试（需先配置模型路径）。

- `--exp`: 实验编号 (默认: `0` 运行所有)
  - `1`: 并发性能对比 (Concurrency Comparison)
  - `2`: 阻塞延迟测试 (Blocking Latency)
  - `3`: 延迟分布统计 (Latency Distribution)
  - `4`: 稳定性与资源监控 (Stability & Resources)
  - `0`: 运行以上所有实验

- `--output`: 结果输出文件名 (默认: `comprehensive_results.json`)

### 常用运行示例

**1. 快速验证系统调度逻辑（推荐）**
使用 Mock 负载对比不同架构的性能。

```bash
# 运行 xy-core 模式的所有实验
python comprehensive_experiment.py --mode xy_core --workload mock

# 运行 naive_async 模式的所有实验（用于对比）
python comprehensive_experiment.py --mode naive_async --workload mock
```

**2. 运行特定实验**
例如，只运行“阻塞延迟测试”（Experiment 2）。

```bash
python comprehensive_experiment.py --mode xy_core --exp 2
```

**3. 真实模型负载测试**
需要确保代码中配置的模型路径正确。

```bash
python comprehensive_experiment.py --mode xy_core --workload real
```

## 结果可视化

运行完实验后，可以使用 `visualize_benchmark.py` 生成可视化图表：

```bash
python visualize_benchmark.py
```

该脚本会自动读取 `experiment_results` 目录下所有的 `comprehensive_results*.json` 文件，并生成以下图表：
- `exp1_concurrency_rps.png`: 并发数与吞吐量 (RPS) 的关系。
- `exp2_blocking_latency.png`: 主线程阻塞延迟对比。
- `exp3_latency_dist.png`: 任务延迟分布（箱线图）。
- `exp4_stability.png`: 稳定性测试结果（完成数 vs 错误数）。

## 常见问题

**Q: `workload` 为 `real` 时报错找不到模型？**
A: 请打开 `comprehensive_experiment.py` 文件，在文件顶部的 `CONFIG` 字典中修改模型路径，确保路径指向您本地的真实模型文件。

**Q: 实验结果在哪里？**
A: 运行结束后，会在当前目录下生成 `comprehensive_results.json`（或您指定的文件名）。您可以编写脚本或手动查看此 JSON 文件。后续可以使用 `visualize_benchmark.py` 对其进行绘图。

## 开发者指南

为了保持代码整洁和可维护性，`comprehensive_experiment.py` 采用了清晰的分层结构：

1.  **配置区 (Config)**: 集中管理所有模型路径和 API 地址。
2.  **模拟组件区 (Mock Classes)**: 定义了 MockLLM, MockVL 等模拟类，使用 CPU 矩阵运算模拟真实负载的阻塞特性。
3.  **真实组件加载区 (Real Imports)**: 使用 `load_real_adapters` 函数进行延迟加载，只有在 `workload='real'` 时才引入重型依赖 (torch, diffusers 等)。
4.  **上下文/工厂模式 (Context/Factory)**: `ExperimentContext` 类负责根据模式初始化相应的适配器（Mock 或 Real）。
5.  **实验逻辑区 (Experiment Runner)**: `ExperimentRunner` 类包含所有实验的核心逻辑，通过调用统一的接口与适配器交互，实现了实验逻辑与底层实现的解耦。

如果您需要添加新的实验或支持新的模型，请遵循此结构进行扩展。
