# 小优核心 (XiaoYou Core)

<div align="center">
  <strong>面向资源受限环境的高性能异步AI Agent核心系统</strong>
</div>

## 项目简介

小优核心是一个专为资源受限环境设计的AI Agent基础设施，提供高效的LLM推理、多模态交互和实时通信能力。系统采用异步并发架构，优化资源利用，支持多种部署场景，包括本地部署、边缘设备和云端部署。

## 核心特性

### 高性能LLM推理引擎
- 支持多种模型适配（LLaMA、Qwen、GLM等）
- 高效缓存机制，提升推理速度
- 异步处理架构，优化资源利用
- 模型并行加载和推理支持
- 智能模型选择和切换

### 实时通信与交互
- WebSocket服务器，支持高并发连接
- 完善的心跳机制和错误处理
- 支持多种消息类型处理
- 支持HTTP API和WebSocket API双接口
- 完善的请求超时和错误处理机制

### 多模态处理能力
- 语音识别(ASR)集成，支持多种模型大小
- 文本转语音(TTS)支持，支持声音克隆和多语言
- 图像处理和生成能力，基于Stable Diffusion
- 视觉理解和分析能力
- 多模态大模型支持

### 智能记忆管理
- 上下文管理和会话记忆
- 长期记忆存储和检索
- 向量检索功能
- 记忆优化和压缩
- 加权记忆管理机制

### 灵活配置系统
- 基于Pydantic v2的统一配置管理
- 支持环境变量覆盖和配置热更新
- 多环境适配（开发、测试、生产）
- YAML配置文件支持
- 自动模型检测和配置

### 多客户端支持
- Web前端界面（React + TypeScript）
- Android客户端
- QQ机器人
- 微信机器人
- 支持自定义客户端开发

### 智能生活模拟
- 生活状态模拟和监控
- 主动关怀和交互
- 情感系统和响应
- 生活事件处理

## 架构设计

小优核心采用清晰的四层架构设计，实现了高内聚、低耦合的系统结构：

1. **Core Engine Layer (`core/core_engine/`)**
   - 系统生命周期管理
   - 配置管理
   - 事件总线
   - 模型管理
   - 关键组件：`CoreEngine`, `EventBus`, `LifecycleManager`, `ConfigManager`, `ModelManager`

2. **Service Layer (`core/services/`)**
   - 业务逻辑实现
   - 模块协调和编排
   - 关键组件：`AvelineService`（主要角色逻辑）, `ActiveCareService`（主动关怀）, `TaskScheduler`（任务调度）, `MonitoringSystem`（监控系统）, `LifeSimulationService`（生活模拟）

3. **Module Layer (`core/modules/`)**
   - 功能能力封装
   - 模型交互管理
   - 关键组件：`LLMModule`（大语言模型）, `ImageModule`（图像生成）, `VisionModule`（视觉理解）, `VoiceModule`（语音能力）, `MemoryModule`（记忆管理）

4. **Interface Layer (`core/interfaces/`)**
   - 外部通信处理
   - HTTP和WebSocket接口
   - API路由管理

## 快速开始

### 环境要求

- Python 3.10+
- CUDA支持（推荐，用于加速模型推理）或CPU模式
- 最低4GB可用内存（推荐8GB以上）
- 足够的磁盘空间用于模型存储

### 安装依赖

```bash
# 基础依赖
pip install -r requirements/core.txt

# 模型依赖（GPU版）
pip install -r requirements/models-gpu.txt

# 或模型依赖（CPU版）
pip install -r requirements/models-cpu.txt

# 语音功能依赖
pip install -r requirements/voice.txt

# 开发依赖
pip install -r requirements/dev.txt
```

### 配置设置

1. 复制配置示例文件
```bash
cp config/config_example.py config/config.py
cp .env.example .env
```

2. 根据需要修改配置项：
   - 模型路径和参数
   - 服务器配置（主机、端口等）
   - 多模态功能开关
   - 日志级别和格式
   - 环境变量覆盖

### 启动服务

#### 方式1：使用启动脚本

```bash
# 启动Web服务
start_web.bat

# 启动所有服务
start_services.bat

# 启动宠物功能
start_pet.bat
```

#### 方式2：直接运行Python脚本

```bash
# 启动FastAPI服务器
python main.py
```

#### 方式3：使用uvicorn命令

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## 项目结构

```
├── api/                     # API相关代码
├── chromadb/                # ChromaDB向量数据库
├── clients/                 # 客户端实现
│   ├── android/             # Android客户端
│   ├── bots/                # 机器人客户端
│   │   ├── qq_bot.py        # QQ机器人
│   │   └── wx_bot.py        # 微信机器人
│   └── frontend/            # Web前端
│       ├── Aveline_UI/      # 主UI界面
│       └── packages/        # 前端包管理
├── config/                  # 配置文件
│   ├── yaml/                # YAML配置文件
│   │   ├── app.yaml         # 应用配置
│   │   └── env.yaml         # 环境配置
│   ├── asr_config.json      # ASR配置
│   ├── config.py            # 配置加载
│   ├── config_example.py    # 配置示例
│   ├── config_loader.py     # 配置加载器
│   └── integrated_config.py # 集成配置管理
├── cpp_scheduler/           # C++调度器
├── core/                    # 核心功能模块
│   ├── agents/              # AI Agent实现
│   ├── api/                 # API定义
│   ├── cache/               # 缓存实现
│   ├── character/           # 角色定义和配置
│   ├── core_engine/         # 核心引擎
│   ├── emotion/             # 情感系统
│   ├── env/                 # 环境管理
│   ├── image/               # 图像处理
│   ├── interfaces/          # 接口层
│   ├── lifecycle/           # 生命周期管理
│   ├── llm/                 # LLM相关
│   ├── managers/            # 管理器
│   ├── modules/             # 功能模块
│   ├── services/            # 服务层
│   ├── tools/               # 工具函数和学习工具
│   ├── utils/               # 通用工具
│   └── voice/               # 语音处理
├── data/                    # 数据目录
├── demo/                    # 演示代码
├── docs/                    # 文档目录
├── external/                # 外部依赖
├── history/                 # 会话历史
├── legacy/                  # 遗留代码
├── logs/                    # 日志目录
├── maintenance/             # 维护脚本
├── memory/                  # 记忆管理
├── models/                  # 模型文件
├── multimodal/              # 多模态相关
├── output/                  # 输出目录
├── paper/                   # 论文相关
├── ref_audio/               # 参考音频
├── requirements/            # 依赖列表
├── routers/                 # API路由
│   ├── __init__.py          # 路由初始化
│   ├── api_router.py        # API路由
│   ├── health_router.py     # 健康检查路由
│   ├── memory_router.py     # 记忆管理路由
│   ├── session_router.py    # 会话管理路由
│   └── websocket_router.py  # WebSocket路由
├── scripts/                 # 工具脚本
├── services/                # 服务相关
├── src/                     # 源代码
├── static/                  # 静态资源
├── temp/                    # 临时文件
├── templates/               # HTML模板
├── tests/                   # 测试用例
├── venv_core/               # 虚拟环境
├── voice/                   # 语音处理
├── .env                     # 环境变量
├── .env.example             # 环境变量示例
├── LICENSE                  # 许可证文件
├── main.py                  # FastAPI应用入口
├── PROJECT_TECHNICAL_REFERENCE.md  # 项目技术参考文档
├── pyproject.toml           # Python项目配置
├── readme.md                # 项目说明文档
├── requirements.txt         # 依赖列表
├── setup.py                 # 安装脚本
├── start_pet.bat            # 启动宠物功能
├── start_services.bat       # 启动所有服务
└── start_web.bat            # 启动Web服务
```

## 主要功能模块

### 1. 核心引擎模块 (`core/core_engine/`)
- **配置管理**：基于Pydantic v2的统一配置管理，支持环境变量覆盖和YAML配置
- **事件总线**：实现系统内部组件之间的异步通信，支持事件过滤和优先级
- **生命周期管理**：管理系统的启动、运行和关闭，支持服务注册和初始化
- **模型管理**：管理模型的加载、卸载和推理，支持智能模型选择

### 2. 服务层模块 (`core/services/`)
- **AvelineService**：主要角色逻辑，处理角色交互和情感表达
- **ActiveCareService**：主动关怀服务，根据用户状态主动发起交互
- **TaskScheduler**：任务调度服务，管理系统定时任务和异步任务
- **MonitoringSystem**：监控系统，监控系统资源和运行状态
- **LifeSimulationService**：生活模拟服务，模拟角色的生活状态和行为

### 3. 功能模块 (`core/modules/`)
- **LLMModule**：大语言模型集成，处理文本生成和理解，支持多种模型适配
- **ImageModule**：图像生成模块，基于Stable Diffusion实现图像生成和处理
- **VisionModule**：视觉理解模块，支持图像内容理解和分析
- **VoiceModule**：语音处理模块，支持TTS和ASR功能，支持声音克隆
- **MemoryModule**：记忆管理模块，管理上下文和长期记忆，支持向量检索

### 4. 通信模块
- **HTTP API**：提供RESTful API接口，支持多种请求和响应格式
- **WebSocket API**：提供实时通信接口，支持心跳和错误处理
- **多客户端支持**：支持Web、Android、QQ机器人、微信机器人等多种客户端
- **完善的请求处理**：支持请求超时、错误处理和速率限制

### 5. 语音处理模块
- **ASR**：支持多种模型大小（tiny、base、small、medium、large）
- **TTS**：支持声音克隆、多语言、语速和音调调整
- **声音处理**：支持音频文件上传和处理
- **实时语音交互**：支持实时语音输入和输出

### 6. 图像处理模块
- **图像生成**：基于Stable Diffusion，支持多种模型和LoRA
- **图像分析**：支持屏幕分析和内容理解
- **图像上传和处理**：支持多种图像格式和大小

## 配置说明

### 配置系统

小优核心使用基于Pydantic v2的统一配置管理系统，支持多种配置方式：

1. **环境变量**：使用`XIAOYOU_`前缀的环境变量
2. **YAML配置文件**：`config/yaml/app.yaml`和`config/yaml/env.yaml`
3. **.env文件**：环境变量文件，用于本地开发
4. **配置热更新**：支持运行时配置更新

### 核心配置项

#### 服务器配置
```yaml
server:
  port: 8000              # HTTP服务端口
  host: 0.0.0.0           # 绑定地址
  ws_port: 8765           # WebSocket服务端口
  ws_heartbeat_interval: 30  # WebSocket心跳间隔（秒）
  ws_timeout: 60          # WebSocket超时时间（秒）
  max_connections: 10     # 最大连接数
```

#### 模型配置
```yaml
model:
  text_path: /path/to/llm/model  # 文本模型路径
  vision_path: /path/to/vision/model  # 视觉模型路径
  image_gen_path: /path/to/sd/model  # 图像生成模型路径
  device: cuda            # 设备类型（cpu/cuda）
  gpu_enabled: true       # 是否启用GPU
  load_mode: local        # 模型加载模式（online/local）
```

#### 语音配置
```yaml
voice:
  enabled: true           # 是否启用语音功能
  default_engine: local   # 默认语音引擎
  default_voice: zh-CN-XiaoxiaoNeural  # 默认语音
  gpt_model_path: /path/to/gpt/model  # GPT模型路径
  sovits_model_path: /path/to/sovits/model  # SoVITS模型路径
```

#### 记忆配置
```yaml
memory:
  default_history_length: 10  # 默认历史记录长度
  max_history_length: 50      # 最大历史记录长度
  memory_pruning_threshold: 0.3  # 记忆修剪阈值
  long_term_memory_db: long_term_memory.db  # 长期记忆数据库
```

## 开发指南

### 开发环境搭建

1. 克隆代码仓库
2. 创建Python虚拟环境
   ```bash
   python -m venv venv
   ```
3. 激活虚拟环境
   ```bash
   # Windows
   venv\Scripts\activate
   
   # Linux/Mac
   source venv/bin/activate
   ```
4. 安装依赖
   ```bash
   pip install -r requirements/dev.txt
   ```
5. 配置开发环境
   ```bash
   cp config/config_example.py config/config.py
   cp .env.example .env
   ```

### 开发流程

1. 创建分支
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. 编写代码，遵循PEP 8规范
3. 运行测试
   ```bash
   pytest tests/
   ```
4. 检查代码质量
   ```bash
   # 运行lint检查
   flake8
   
   # 运行类型检查
   mypy .
   ```
5. 提交代码，使用语义化提交信息
   ```bash
   git add .
   git commit -m "feat: add new feature description"
   git push origin feature/your-feature-name
   ```
6. 创建Pull Request，描述功能和变更

### API开发

1. 在`routers/`目录下创建或修改路由文件
2. 遵循RESTful API设计规范
3. 添加适当的请求验证和错误处理
4. 使用依赖注入管理服务和资源
5. 添加API文档和示例

## 测试和部署

### 测试

#### 单元测试
```bash
pytest tests/unit/
```

#### 集成测试
```bash
pytest tests/integration/
```

#### 性能测试
```bash
python tests/performance/test_performance.py
```

#### API测试
```bash
# 使用curl测试API
curl -X POST http://localhost:8000/api/v1/message -H "Content-Type: application/json" -d '{"content": "你好"}'

# 使用WebSocket测试
wscat -c ws://localhost:8765
```

### 部署

#### 本地部署
1. 按照快速开始指南安装依赖
2. 配置系统，设置适当的环境变量
3. 启动服务，使用适当的启动方式

#### 云端部署
1. 选择合适的云服务器（推荐Ubuntu 20.04+）
2. 安装Python 3.10+和必要的依赖
3. 配置环境变量和配置文件
4. 使用PM2或Supervisor管理进程
   ```bash
   # 使用PM2管理
   pm2 start "uvicorn main:app --host 0.0.0.0 --port 8000" --name xiaoyou-core
   
   # 使用Supervisor
   # 创建配置文件 /etc/supervisor/conf.d/xiaoyou-core.conf
   ```
5. 配置反向代理（Nginx或Apache）
   ```nginx
   server {
       listen 80;
       server_name your-domain.com;
       
       location / {
           proxy_pass http://localhost:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       }
       
       location /ws {
           proxy_pass ws://localhost:8765;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_set_header Host $host;
       }
   }
   ```
6. 配置SSL证书（推荐使用Let's Encrypt）

## 客户端使用

### Web前端
1. 启动服务后，访问 http://localhost:8000
2. 开始与AI交互，支持文本、语音和图像输入
3. 查看会话历史和记忆
4. 配置客户端设置

### Android客户端
1. 编译并安装Android客户端
2. 配置服务器地址（默认：http://localhost:8000）
3. 开始与AI交互，支持文本和语音输入
4. 查看会话历史

### QQ机器人
1. 配置QQ机器人参数（`clients/bots/config.json`）
2. 启动QQ机器人
   ```bash
   cd clients/bots
   python qq_bot.py
   ```
3. 在QQ中添加机器人为好友
4. 开始与机器人交互，支持文本和图像

### 微信机器人
1. 配置微信机器人参数（`clients/bots/config.json`）
2. 启动微信机器人
   ```bash
   cd clients/bots
   python wx_bot.py
   ```
3. 扫描二维码登录微信
4. 开始与机器人交互，支持文本和图像

## 贡献指南

欢迎提交Issue和Pull Request来改进项目。在贡献前，请先了解以下内容：

1. **代码风格**：遵循PEP 8规范，使用4个空格缩进
2. **提交规范**：使用语义化提交信息（feat:, fix:, docs:, style:, refactor:, test:, chore:）
3. **测试要求**：新增功能必须包含测试用例，确保测试覆盖率
4. **文档要求**：新增功能必须更新文档，包括README.md和代码注释
5. **架构要求**：遵循系统的四层架构设计，保持模块间低耦合
6. **类型提示**：所有函数和方法必须添加类型提示
7. **错误处理**：完善的错误处理和日志记录

### 提交PR流程

1. Fork项目仓库
2. 创建特性分支
3. 编写代码和测试
4. 运行测试和代码检查
5. 提交代码，使用语义化提交信息
6. 创建Pull Request，描述功能和变更
7. 等待代码审查和合并

## 许可证

本项目采用MIT许可证。详见[LICENSE](LICENSE)文件。

## 技术栈

- **后端框架**：FastAPI, Uvicorn
- **异步框架**：asyncio
- **前端框架**：React, TypeScript, Vite
- **AI框架**：PyTorch, Transformers, Diffusers, Whisper
- **配置管理**：Pydantic v2
- **数据库**：SQLite, Redis（可选）
- **通信协议**：WebSocket, HTTP/HTTPS
- **开发语言**：Python 3.10+, TypeScript, Java（Android）
- **代码质量**：Flake8, MyPy, Pytest

## 性能优化

1. **异步架构**：使用asyncio实现高性能异步处理
2. **缓存机制**：完善的缓存系统，减少重复计算
3. **模型优化**：支持模型量化和优化，降低资源消耗
4. **内存管理**：智能内存管理和垃圾回收
5. **并发控制**：合理的并发控制和资源限制
6. **请求队列**：请求队列和优先级管理

## 安全考虑

1. **输入验证**：完善的输入验证和清理
2. **请求限制**：速率限制和IP限制
3. **敏感信息保护**：敏感信息加密和保护
4. **CORS配置**：合理的CORS配置，支持跨域请求
5. **错误处理**：完善的错误处理，避免信息泄露
6. **日志管理**：安全的日志管理，避免敏感信息泄露

## 监控和维护

1. **系统监控**：实时监控系统资源和运行状态
2. **日志管理**：完善的日志记录和分析
3. **健康检查**：提供健康检查API
4. **性能指标**：实时性能指标和统计
5. **错误报告**：完善的错误报告和分析

## 联系方式

- 项目地址：https://github.com/hakituo/xiaoyou-core
- 问题反馈：https://github.com/hakituo/xiaoyou-core/issues
- 讨论交流：（暂未开放，敬请期待）

## 致谢

感谢所有为小优核心项目做出贡献的开发者和用户！

感谢以下开源项目的支持：
- FastAPI
- PyTorch
- Transformers
- Diffusers
- Whisper
- Stable Diffusion
- Mirai（QQ机器人框架）

## 更新日志

### v0.5.0
- 重构配置系统，基于Pydantic v2
- 增强语音处理功能，支持声音克隆
- 完善图像处理和生成能力
- 增强记忆管理系统
- 优化异步架构和性能
- 完善错误处理和日志记录

### v0.4.0
- 增加生活模拟功能
- 完善多模态处理能力
- 增强API和WebSocket接口
- 优化模型管理和加载
- 完善测试和文档

### v0.3.0
- 增加语音识别和TTS功能
- 完善图像处理功能
- 增强记忆管理系统
- 优化配置系统

### v0.2.0
- 实现核心引擎和服务层
- 完善WebSocket通信
- 增加基本的LLM推理功能
- 实现基本的记忆管理

### v0.1.0
- 项目初始化
- 实现基本架构和核心功能
- 支持基本的HTTP和WebSocket接口
- 支持基本的LLM推理
