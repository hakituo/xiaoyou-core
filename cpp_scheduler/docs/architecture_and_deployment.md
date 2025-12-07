# C++ 异步调度器系统 - 架构与部署指南

## 1. 系统架构概述

### 1.1 核心架构设计

我们的C++异步调度器系统实现了一个专业级、厂商级的资源隔离与调度架构，能够同时运行三个核心AI功能组件：

```
┌──────────────────┐
│   C++异步调度器     │   <— 黑盒的核心价值
└───────┬──────────┘
        │
        ├── GPU worker #1 ──► LLM (实时)
        │
        ├── CPU worker ─────► TTS (实时，不用GPU)
        │
        └── GPU worker #2 ──► 图像生成（异步队列）
```

### 1.2 关键特性

- **资源隔离**：三个核心组件在不同的计算资源上运行，避免了GPU争用问题
- **异步并发**：所有组件都以异步方式运行，提供最大的吞吐量
- **拓扑调度**：智能任务调度系统确保关键任务优先处理
- **实时响应**：LLM和TTS组件提供近实时响应能力
- **稳定运行**：通过全面的监控和资源限制确保系统稳定性

### 1.3 组件说明

#### 1.3.1 GPU LLM Worker

- **功能**：负责大语言模型的推理
- **资源需求**：独占GPU资源，提供低延迟响应
- **配置路径**：`config/workers/gpu_llm.json`
- **支持模型**：Qwen2.5、Llama系列等

#### 1.3.2 CPU TTS Worker

- **功能**：负责文本到语音转换
- **资源需求**：仅使用CPU资源，不影响GPU
- **配置路径**：`config/workers/cpu_tts.json`
- **支持模型**：Coqui Glow-TTS CPU版本、MeloTTS CPU版本

#### 1.3.3 GPU 图像生成 Worker

- **功能**：负责图像生成任务
- **资源需求**：使用GPU资源，但以队列方式异步执行
- **配置路径**：`config/workers/gpu_image.json`
- **支持模型**：Stable Diffusion 1.5 Turbo、SDXL Turbo

#### 1.3.4 API 服务

- **功能**：提供统一的REST API接口
- **配置路径**：`config/api_server.json`
- **支持协议**：HTTP/HTTPS

#### 1.3.5 监控与优化

- **功能**：系统资源监控、性能优化、自动调参
- **配置路径**：`config/monitoring.json`、`config/optimization.json`

## 2. 系统要求

### 2.1 硬件要求

| 组件 | 最低要求 | 推荐配置 |
|------|----------|----------|
| CPU | 8核 | 16核或更高 |
| GPU | NVIDIA GPU，4GB VRAM | NVIDIA GPU，8GB+ VRAM |
| 内存 | 16GB RAM | 32GB+ RAM |
| 存储 | 20GB SSD | 50GB+ NVMe SSD |

### 2.2 软件要求

- **操作系统**：Linux (Ubuntu 20.04+/CentOS 8+) 或 Windows 10/11
- **编译器**：GCC 9.0+ (Linux) 或 MSVC 2019+ (Windows)
- **CUDA**：CUDA 11.3+ (如果使用GPU)
- **cuDNN**：cuDNN 8.2+ (如果使用GPU)
- **CMake**：3.18+
- **依赖库**：
  - nlohmann/json
  - libuv 1.x (事件循环)
  - spdlog (日志)
  - OpenSSL (HTTPS)
  - curl (HTTP客户端)

## 3. 安装指南

### 3.1 克隆代码仓库

```bash
git clone https://github.com/your-org/ai-scheduler.git
cd ai-scheduler
```

### 3.2 安装依赖

#### 3.2.1 Ubuntu/Debian

```bash
# 安装系统依赖
sudo apt-get update
sudo apt-get install -y build-essential cmake libssl-dev curl git

# 安装CUDA和cuDNN (如果使用GPU)
# 请参考NVIDIA官方文档安装适合您系统的CUDA和cuDNN版本
```

#### 3.2.2 CentOS/RHEL

```bash
sudo yum install -y gcc-c++ cmake3 openssl-devel curl git
sudo ln -s /usr/bin/cmake3 /usr/bin/cmake
```

#### 3.2.3 Windows

1. 安装Visual Studio 2019或更高版本（确保安装了C++开发工作负载）
2. 安装CMake 3.18+
3. 安装Git
4. 安装CUDA和cuDNN (如果使用GPU)

### 3.3 构建系统

```bash
# 创建构建目录
mkdir build
cd build

# 配置构建
cmake .. -DCMAKE_BUILD_TYPE=Release

# 编译
cmake --build . --config Release -j$(nproc)

# 安装
cmake --install . --prefix /usr/local  # Linux
t# 在Windows上，构建完成后会在build/Release目录中生成可执行文件
```

## 4. 配置说明

### 4.1 配置文件结构

系统配置文件位于`config/`目录下，主要包括：

```
config/
├── system_config.json      # 主配置文件
├── workers/
│   ├── gpu_llm.json        # LLM工作器配置
│   ├── cpu_tts.json        # TTS工作器配置
│   └── gpu_image.json      # 图像生成工作器配置
├── api_server.json         # API服务器配置
├── monitoring.json         # 监控配置
└── optimization.json       # 优化配置
```

### 4.2 主配置文件说明

创建一个默认配置文件：

```bash
./ai_scheduler --generate-config /path/to/config.json
```

主配置文件包含以下主要部分：

#### 4.2.1 全局配置

```json
{
  "global": {
    "log_level": "info",
    "metrics_collection_interval_ms": 1000,
    "enable_profiling": false,
    "enable_statistics": true,
    "shutdown_timeout_ms": 5000,
    "temp_directory": "/tmp/ai_scheduler",
    "models_directory": "models",
    "max_concurrent_requests": 100
  }
}
```

#### 4.2.2 工作器配置示例

```json
{
  "workers": {
    "gpu_llm": {
      "enabled": true,
      "max_threads": 4,
      "min_threads": 2,
      "queue_capacity": 100,
      "batch_size": 8,
      "gpu_id": 0,
      "max_gpu_memory_mb": 8192,
      "model_path": "models/llm/model.bin",
      "context_size": 4096,
      "temperature": 0.7
    },
    "cpu_tts": {
      "enabled": true,
      "max_threads": 8,
      "min_threads": 4,
      "queue_capacity": 200,
      "model_path": "models/tts/coqui_models/",
      "voice": "en-US"
    },
    "gpu_image": {
      "enabled": true,
      "max_threads": 2,
      "min_threads": 1,
      "queue_capacity": 50,
      "batch_size": 2,
      "gpu_id": 0,
      "max_gpu_memory_mb": 4096,
      "model_path": "models/image/stable_diffusion/",
      "default_width": 512,
      "default_height": 512,
      "steps": 20
    }
  }
}
```

### 4.3 关键配置参数说明

#### 4.3.1 GPU资源管理

为了避免GPU资源争用，需要特别注意以下配置：

1. **GPU内存限制**：
   - LLM工作器和图像生成工作器的GPU内存限制总和不应超过实际可用GPU内存
   - 建议为系统预留约10%的GPU内存作为缓冲

2. **GPU利用率阈值**：
   - LLM工作器的阈值可以设置得较高（如0.8-0.9）
   - 图像生成工作器的阈值应设置得较低（如0.6-0.7），避免长时间占用GPU

3. **异步队列配置**：
   - 图像生成工作器的队列容量应合理设置，避免内存溢出
   - 适当设置批处理超时时间，平衡响应速度和吞吐量

#### 4.3.2 性能调优参数

- **线程数配置**：
  - LLM工作器：根据GPU性能和CPU核心数调整
  - TTS工作器：可设置较高线程数，充分利用CPU资源
  - 图像生成工作器：通常不需要太多线程

- **批处理大小**：
  - 根据GPU内存和任务大小动态调整
  - 设置合理的最大和最小批处理大小限制

## 5. 部署最佳实践

### 5.1 单机部署

对于单机部署，我们推荐以下配置：

1. **准备足够的GPU内存**：
   - 至少8GB GPU内存用于LLM
   - 至少4GB GPU内存用于图像生成

2. **CPU核心分配**：
   - 为TTS工作器分配尽可能多的CPU核心
   - 为系统和其他服务预留足够的CPU资源

3. **启动命令**：
   ```bash
   ./ai_scheduler --config /path/to/config.json
   ```

### 5.2 容器化部署

使用Docker进行容器化部署：

1. **构建Docker镜像**：
   ```bash
   docker build -t ai-scheduler .
   ```

2. **运行容器**：
   ```bash
   docker run --gpus all -p 8080:8080 -v /path/to/models:/app/models -v /path/to/config:/app/config ai-scheduler
   ```

3. **环境变量**：
   - `AI_SCHEDULER_CONFIG`：配置文件路径
   - `AI_SCHEDULER_LOG_LEVEL`：日志级别

### 5.3 监控与健康检查

1. **Prometheus监控**：
   - 默认在9090端口暴露Prometheus指标
   - 监控指标包括：
     - 任务队列长度
     - 任务执行时间
     - GPU/CPU利用率
     - 内存使用情况

2. **健康检查API**：
   - `GET /api/v1/health`：返回系统健康状态
   - `GET /api/v1/status`：返回详细的系统状态信息

### 5.4 高可用部署（可选）

对于需要高可用性的场景：

1. **负载均衡**：
   - 使用Nginx或HAProxy作为负载均衡器
   - 配置多台服务器运行调度器实例

2. **状态共享**：
   - 使用Redis或类似服务共享任务状态
   - 实现任务调度协调

3. **故障转移**：
   - 配置自动健康检查和故障转移机制
   - 使用监控系统检测服务状态

## 6. 性能优化建议

### 6.1 GPU资源优化

1. **模型优化**：
   - 使用量化后的模型（INT8/INT4）减少GPU内存占用
   - 为不同组件选择适当的模型大小

2. **显存管理**：
   - 合理设置每个工作器的显存限制
   - 启用梯度检查点技术（如果支持）

3. **调度策略**：
   - 对图像生成任务使用优先级队列
   - 实现基于资源使用情况的动态任务调度

### 6.2 CPU资源优化

1. **线程亲和性**：
   - 为TTS工作器设置CPU亲和性，绑定到特定核心
   - 避免线程频繁切换带来的开销

2. **批处理优化**：
   - 根据实际负载调整TTS工作器的批处理大小
   - 实现自适应批处理机制

### 6.3 网络优化

1. **API优化**：
   - 启用压缩减少网络流量
   - 实现请求限流保护系统

2. **模型加载优化**：
   - 使用内存映射技术加载大模型
   - 实现模型预热机制

## 7. 故障排查

### 7.1 常见问题及解决方案

1. **GPU内存不足**：
   - 减小模型大小或使用量化版本
   - 降低批处理大小
   - 减少并发任务数量

2. **系统响应缓慢**：
   - 检查CPU/GPU利用率是否过高
   - 调整线程数和队列大小
   - 增加系统资源

3. **服务启动失败**：
   - 检查配置文件格式是否正确
   - 确认模型文件路径是否存在
   - 查看日志文件了解详细错误信息

4. **任务执行超时**：
   - 增加任务超时阈值
   - 优化模型性能
   - 检查系统资源是否充足

### 7.2 日志系统

日志文件默认位于`logs/`目录，包含以下日志文件：

- `ai_scheduler.log`：主服务日志
- `gpu_llm_worker.log`：LLM工作器日志
- `cpu_tts_worker.log`：TTS工作器日志
- `gpu_image_worker.log`：图像生成工作器日志
- `api_server.log`：API服务器日志

日志级别可在配置文件中设置，支持的级别有：TRACE、DEBUG、INFO、WARNING、ERROR、FATAL。

## 8. 安全建议

### 8.1 API安全

1. **启用HTTPS**：
   ```json
   "api_server": {
     "enable_ssl": true,
     "ssl_cert_path": "ssl/cert.pem",
     "ssl_key_path": "ssl/key.pem"
   }
   ```

2. **实现访问控制**：
   - 配置API密钥认证
   - 设置IP白名单

3. **输入验证**：
   - 对所有API输入进行严格验证
   - 限制请求大小和频率

### 8.2 系统安全

1. **最小权限原则**：
   - 以非root用户运行服务
   - 限制文件系统访问权限

2. **定期更新**：
   - 定期更新依赖库和模型
   - 关注安全补丁和更新

3. **隔离环境**：
   - 使用容器或虚拟机隔离运行环境
   - 实现网络隔离策略

## 9. 更新与维护

### 9.1 系统更新

1. **更新代码**：
   ```bash
git pull origin main
cd build
cmake --build . --config Release
```

2. **更新模型**：
   - 将新模型放置在`models/`目录
   - 更新配置文件中的模型路径
   - 重启服务加载新模型

### 9.2 数据备份

1. **配置备份**：
   - 定期备份配置文件
   - 使用版本控制管理配置变更

2. **日志归档**：
   - 配置日志轮转
   - 定期归档重要日志

## 10. 支持与反馈

如有任何问题或建议，请通过以下方式联系我们：

- **技术支持**：support@ai-scheduler.com
- **GitHub Issues**：https://github.com/your-org/ai-scheduler/issues
- **社区论坛**：https://forum.ai-scheduler.com

---

本文档由AI调度器开发团队维护，最后更新日期：2023年12月15日。