# 资源隔离调度架构 - 部署指南

## 1. 架构概述

### 1.1 新架构设计理念

资源隔离调度架构是一个高性能、可扩展的多模态AI服务框架，专为并发处理LLM推理、TTS语音合成和图像生成任务而设计。该架构的核心设计理念包括：

- **资源隔离**：根据任务类型（CPU/GPU）和优先级进行资源隔离，确保不同类型任务不会相互干扰
- **优先级调度**：支持任务优先级机制，确保高优先级任务能够及时响应
- **异步处理**：长时间运行的任务（如图像生成）采用异步队列处理模式
- **统一接口**：提供统一的黑盒接口，简化服务调用和集成

### 1.2 核心组件

- **资源隔离调度器**：架构的核心，负责任务分配和资源管理
- **GPU LLM Worker**：处理大语言模型推理任务，支持实时响应
- **CPU TTS Worker**：处理语音合成任务，利用多线程并行处理
- **GPU图像生成队列**：异步处理图像生成请求，支持任务优先级
- **统一API服务**：提供HTTP接口，支持任务提交、状态查询和资源监控

## 2. 新架构优势

### 2.1 性能提升

- **并发处理能力增强**：不同类型任务可以并行执行，不再相互阻塞
- **资源利用率提高**：根据任务类型自动分配最优资源，最大化硬件利用效率
- **响应时间优化**：高优先级任务能够优先获取资源，缩短关键任务响应时间

### 2.2 可靠性改进

- **故障隔离**：单个组件故障不会影响整个系统运行
- **错误处理增强**：完善的异常处理机制，确保任务失败不会导致系统崩溃
- **任务监控**：支持实时监控任务状态和进度

### 2.3 可维护性提升

- **模块化设计**：清晰的组件划分，便于维护和升级
- **统一接口**：简化客户端集成，减少集成复杂度
- **配置灵活**：支持多种配置选项，可以根据实际需求进行调整

## 3. 系统要求

### 3.1 硬件要求

| 组件 | 最低要求 | 推荐配置 |
|------|---------|--------|
| CPU | 4核8线程 | 8核16线程以上 |
| 内存 | 16GB | 32GB以上 |
| GPU | NVIDIA GPU (LLM/图像生成) | NVIDIA RTX 40系列或A系列，16GB+ VRAM |
| 存储 | 100GB SSD | 500GB SSD以上 |

### 3.2 软件要求

- **操作系统**：Windows 10/11 64位或Ubuntu 20.04/22.04 LTS
- **编译器**：MSVC 2022 (Windows) 或 GCC 9.4+/Clang 10+ (Linux)
- **CMake**：3.14或更高版本
- **依赖库**：
  - libuv 1.48.0+ (异步IO)
  - Threads (多线程支持)
  - Python 3.8+ (如需使用Python API)

## 4. 安装部署

### 4.1 从源码构建

#### Windows平台

```bash
# 克隆代码库
git clone https://github.com/your-org/xiaoyou-core.git
cd xiaoyou-core/cpp_scheduler

# 创建构建目录
mkdir build
cd build

# 配置和构建
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . --config Release

# 安装
cmake --install .
```

#### Linux平台

```bash
# 克隆代码库
git clone https://github.com/your-org/xiaoyou-core.git
cd xiaoyou-core/cpp_scheduler

# 创建构建目录
mkdir build
cd build

# 配置和构建
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)

# 安装
sudo make install
```

### 4.2 使用预编译包

对于Windows和Linux平台，我们提供了预编译的二进制包，可以从GitHub Releases页面下载：

1. 访问项目的GitHub仓库的Releases页面
2. 下载对应平台的最新发布包
3. 解压到目标目录
4. 按照配置说明进行设置

## 5. 配置说明

### 5.1 配置文件

系统使用JSON格式的配置文件，默认位置为`config.json`。配置文件包含以下主要部分：

```json
{
  "server": {
    "port": 8080,
    "thread_pool_size": 4
  },
  "resources": {
    "gpu_allocation": {
      "llm_percentage": 70,
      "image_percentage": 30
    },
    "max_concurrent_tasks": 10
  },
  "engines": {
    "llm": "qwen2.5",
    "tts": "coqui",
    "image": "sd1.5-turbo"
  },
  "logging": {
    "level": "INFO",
    "file": "scheduler.log"
  }
}
```

### 5.2 环境变量

以下环境变量可以覆盖配置文件中的设置：

| 环境变量 | 说明 | 默认值 |
|---------|------|-------|
| `SCHEDULER_PORT` | API服务端口 | 8080 |
| `SCHEDULER_THREAD_POOL_SIZE` | 工作线程池大小 | CPU核心数 |
| `SCHEDULER_CONFIG_PATH` | 配置文件路径 | ./config.json |
| `SCHEDULER_LOG_LEVEL` | 日志级别 | INFO |

### 5.3 资源配置最佳实践

- **线程池大小**：一般设置为CPU核心数的1-2倍
- **GPU分配**：
  - LLM和图像生成共享GPU时，根据负载比例分配
  - 推荐LLM任务优先（70%-80%）
  - 高强度图像生成场景可适当增加图像生成GPU分配
- **最大并发任务数**：根据系统内存和GPU显存大小调整，避免OOM错误

## 6. 启动和管理

### 6.1 启动服务

#### Windows

```cmd
# 使用默认配置启动
ai_scheduler.exe

# 指定配置文件
ai_scheduler.exe --config your_config.json
```

#### Linux

```bash
# 使用默认配置启动
./ai_scheduler

# 指定配置文件
./ai_scheduler --config your_config.json
```

### 6.2 作为系统服务运行

#### Linux (systemd)

创建服务文件 `/etc/systemd/system/ai-scheduler.service`：

```ini
[Unit]
Description=AI Resource Isolation Scheduler
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/scheduler
ExecStart=/path/to/scheduler/ai_scheduler --config /path/to/scheduler/config.json
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用并启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-scheduler.service
sudo systemctl start ai-scheduler.service
```

#### Windows (服务)

可以使用NSSM工具将程序安装为Windows服务：

```cmd
nssm install "AI Scheduler" "C:\path\to\ai_scheduler.exe"
nssm set "AI Scheduler" AppParameters "--config C:\path\to\config.json"
nssm start "AI Scheduler"
```

## 7. API使用指南

### 7.1 REST API接口

服务提供以下主要REST API接口：

#### 7.1.1 LLM推理接口

```bash
# 发送LLM推理请求
curl -X POST http://localhost:8080/api/v1/llm/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt":"你好，请介绍一下自己","model":"qwen2.5","temperature":0.7}'
```

#### 7.1.2 TTS合成接口

```bash
# 发送TTS合成请求
curl -X POST http://localhost:8080/api/v1/tts/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text":"这是一段测试文本","voice":"coqui","speed":1.0}'
```

#### 7.1.3 图像生成接口

```bash
# 发送图像生成请求（异步）
curl -X POST http://localhost:8080/api/v1/image/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt":"一只可爱的小猫","width":512,"height":512,"use_turbo":true,"steps":20}'
```

#### 7.1.4 任务状态查询

```bash
# 查询任务状态
curl -X GET http://localhost:8080/api/v1/task/status/{task_id}
```

#### 7.1.5 资源统计查询

```bash
# 查询系统资源使用情况
curl -X GET http://localhost:8080/api/v1/system/resources
```

### 7.2 API客户端使用

#### C++客户端

```cpp
#include "api/api_client.h"

// 创建API客户端
auto client = ai_scheduler::api::createDefaultAPIClient("http://localhost:8080");

// 生成LLM响应
auto llmResponse = client->generateLLM("请介绍一下自己", "qwen2.5", 0.7);
if (llmResponse.isSuccess()) {
    std::cout << "LLM响应: " << llmResponse.body << std::endl;
}

// 异步生成图像
client->generateImageAsync("一只可爱的小狗", [](const ai_scheduler::api::ClientResponse& response) {
    if (response.isSuccess()) {
        std::cout << "图像生成成功!" << std::endl;
    }
}, 512, 512, true, 20);
```

## 8. 监控和维护

### 8.1 日志管理

系统日志默认保存在`./scheduler.log`，可以通过配置文件或环境变量修改日志级别和位置。日志级别包括：

- DEBUG: 详细调试信息
- INFO: 一般信息（默认）
- WARNING: 警告信息
- ERROR: 错误信息
- FATAL: 致命错误

### 8.2 常见问题排查

| 问题 | 可能原因 | 解决方法 |
|------|---------|--------|
| GPU内存不足 | 并发任务过多或模型过大 | 减少并发任务数或使用更小的模型 |
| 服务启动失败 | 端口被占用或配置错误 | 检查端口占用情况，检查配置文件格式 |
| 任务执行超时 | 模型加载慢或任务队列过长 | 优化模型加载，调整队列参数 |
| CPU使用率过高 | 线程池设置过大 | 减少线程池大小至CPU核心数 |

## 9. 性能优化建议

### 9.1 硬件优化

- 使用高性能SSD存储模型文件
- 为不同任务类型配置专用GPU（如有条件）
- 确保有足够的系统内存以避免内存交换

### 9.2 配置优化

- 根据实际负载调整线程池大小
- 为频繁使用的模型预热，减少首次加载延迟
- 针对不同任务类型设置合理的优先级
- 调整批处理大小以平衡吞吐量和延迟

### 9.3 客户端优化

- 使用异步API减少等待时间
- 实现客户端缓存机制，避免重复请求
- 合理设置请求超时时间

## 10. 版本迁移指南

### 10.1 从旧版本迁移

如果您正在从旧版本迁移到新的资源隔离架构，请注意以下变化：

1. **配置文件格式变更**：新版使用JSON格式配置，请参考配置示例进行转换
2. **API接口变更**：部分API路径和参数已更新，请参考API文档更新客户端
3. **资源分配方式变更**：新版支持更细粒度的资源控制，请重新配置资源分配

### 10.2 数据迁移

对于存储的模型数据，新版保持兼容性，可以直接使用现有模型文件。

## 11. 安全注意事项

### 11.1 访问控制

- 默认配置下，服务只监听本地地址（127.0.0.1）
- 在生产环境中，建议配置防火墙规则限制访问
- 考虑使用反向代理（如Nginx）添加身份验证层

### 11.2 数据安全

- 敏感数据（如API密钥）不应硬编码在配置文件中
- 考虑使用环境变量或加密的配置文件存储敏感信息
- 确保API通信使用HTTPS（在生产环境中）

## 12. 使用Docker部署

### 12.1 Docker部署优势

使用Docker和Docker Compose可以简化部署流程，确保环境一致性，便于扩展和维护。以下是使用Docker部署的主要优势：

- **环境一致性**：避免"在我机器上能运行"的问题
- **简化部署**：一键启动所有服务组件
- **版本管理**：便于服务升级和回滚
- **资源隔离**：各服务组件独立运行，互不干扰
- **扩展性**：轻松扩展服务实例数量

### 12.2 环境要求

- Docker 20.10+  
- Docker Compose 2.0+  
- 至少16GB RAM（推荐32GB+）  
- NVIDIA GPU（用于LLM推理和图像生成）  
- NVIDIA Container Toolkit（启用GPU支持）

### 12.3 Docker Compose配置

创建`docker-compose.yml`文件，包含以下配置：

```yaml
version: '3.8'

services:
  # Redis服务 - 用于任务队列和缓存
  redis:
    image: redis:7.0-alpine
    container_name: xiaoyou-redis
    restart: always
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command:
      - "redis-server"
      - "--appendonly yes"
      - "--requirepass ${REDIS_PASSWORD:-xiaoyou_redis_pass}"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  # FastAPI应用服务
  fastapi:
    build:
      context: .
      dockerfile: Dockerfile.fastapi
    container_name: xiaoyou-fastapi
    restart: always
    depends_on:
      redis:
        condition: service_healthy
    ports:
      - "8000:8000"
    volumes:
      - ./models:/app/models:ro
      - ./logs:/app/logs
    environment:
      - ENVIRONMENT=production
      - REDIS_URL=redis://redis:6379/0
      - REDIS_PASSWORD=${REDIS_PASSWORD:-xiaoyou_redis_pass}
      - SECRET_KEY=${SECRET_KEY:-change_me_in_production}
      - INFER_SERVICE_HOST=tts
      - INFER_SERVICE_PORT=8001
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 8G

  # TTS服务
  tts:
    build:
      context: .
      dockerfile: Dockerfile.tts
    container_name: xiaoyou-tts
    restart: always
    volumes:
      - ./tts_models:/app/tts_models
    ports:
      - "8001:8001"
    environment:
      - ENVIRONMENT=production
      - TTS_SKIP_MODEL_VALIDATION=false
      - TTS_DOWNLOAD_AT_INIT=true
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G

  # go-cqhttp服务（QQ机器人）
  go-cqhttp:
    image: silicer/go-cqhttp:latest
    container_name: xiaoyou-gocqhttp
    restart: always
    depends_on:
      - fastapi
    ports:
      - "5700:5700"
      - "9000:9000"
    volumes:
      - ./bots/config:/data
    environment:
      - CGO_ENABLED=0
    command:
      - "-d"
      - "/data"

  # Nginx反向代理（可选）
  nginx:
    image: nginx:alpine
    container_name: xiaoyou-nginx
    restart: always
    depends_on:
      - fastapi
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/conf.d:/etc/nginx/conf.d
      - ./nginx/ssl:/etc/nginx/ssl
      - ./nginx/html:/usr/share/nginx/html
    environment:
      - NGINX_HOST=xiaoyou-core.local

volumes:
  redis_data:
    driver: local
```

### 12.4 Dockerfile示例

#### 12.4.1 FastAPI Dockerfile (Dockerfile.fastapi)

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建日志目录
RUN mkdir -p /app/logs

# 设置环境变量
ENV PYTHONUNBUFFERED=1

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "-m", "uvicorn", "core.api:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

#### 12.4.2 TTS Dockerfile (Dockerfile.tts)

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    espeak \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# 复制TTS相关依赖
COPY tts_requirements.txt .

# 安装TTS依赖
RUN pip install --no-cache-dir -r tts_requirements.txt

# 复制TTS服务代码
COPY multimodal/tts_manager.py .
COPY core/startup.py .

# 创建模型目录
RUN mkdir -p /app/tts_models

# 暴露端口
EXPOSE 8001

# 启动命令
CMD ["python", "-m", "uvicorn", "tts_manager:tts_app", "--host", "0.0.0.0", "--port", "8001"]
```

### 12.5 部署步骤

1. **准备配置文件**

   创建`.env`文件，包含必要的环境变量：

   ```
   # .env 文件示例
   # 应用配置
   SECRET_KEY=your_secure_secret_key_here
   ENVIRONMENT=production
   
   # Redis配置
   REDIS_PASSWORD=secure_redis_password
   
   # 模型配置
   MODEL_PATH=/app/models
   TTS_MODEL=tts_models/tts_models--multilingual--multi-dataset--your_tts
   
   # 服务配置
   SERVER_PORT=8000
   WS_PORT=8765
   ```

2. **创建目录结构**

   ```bash
   mkdir -p bots/config nginx/conf.d nginx/ssl logs models tts_models
   ```

3. **配置go-cqhttp**

   在`bots/config/config.yml`中配置go-cqhttp：

   ```yaml
   account:
     uin: your_qq_number
     password: ''
   
   message:
     post-format: array
     ignore-invalid-cqcode: true
     force-fragment: false
     fix-url: true
     report-self-message: false
     remove-reply-at: false
     extra-reply-data: false
   
   output:
     log-level: info
     log-aging: 15
     log-force-new: false
     debug: false
   
   servers:
     - http:
         host: 0.0.0.0
         port: 5700
         timeout: 5
         middlewares:
           accesslog: false
         post:
           - url: http://fastapi:8000/api/v1/qq/callback
             secret: your_callback_token
     - ws-reverse:
         universal: ws://fastapi:8000/api/v1/qq/websocket
         reconnect-interval: 3000
         middlewares:
           access-token: your_access_token
   ```

4. **启动服务**

   ```bash
   # 使用docker-compose启动所有服务
   docker-compose up -d
   
   # 查看服务状态
   docker-compose ps
   
   # 查看日志
   docker-compose logs -f
   ```

### 12.6 Docker部署最佳实践

1. **资源限制**：根据实际硬件配置调整docker-compose.yml中的资源限制
2. **持久化存储**：确保模型文件和数据使用卷挂载持久化
3. **安全配置**：
   - 使用强密码和密钥
   - 配置适当的网络隔离
   - 考虑使用HTTPS（生产环境）
4. **监控配置**：
   - 配置日志收集
   - 考虑添加Prometheus和Grafana监控
5. **定期更新**：
   - 定期更新Docker镜像
   - 定期备份配置和数据

### 12.7 GPU支持配置

如果需要在Docker容器中使用GPU，确保安装了NVIDIA Container Toolkit并修改docker-compose.yml：

```yaml
# 在需要GPU的服务中添加
fastapi:
  # 其他配置...
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

## 13. 结论

新的资源隔离调度架构为多模态AI服务提供了更高的性能、更好的可靠性和更灵活的配置选项。通过合理的资源分配和任务调度，系统能够高效地处理不同类型的AI任务，满足各种应用场景的需求。使用Docker部署可以进一步简化安装过程，提高系统的可移植性和一致性。

---

**文档版本**: 1.1.0  
**最后更新**: 2025-11-15  
**维护者**: AI Scheduler Team