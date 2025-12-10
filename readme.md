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

### 实时通信与交互
- WebSocket服务器，支持高并发连接
- 完善的心跳机制和错误处理
- 支持多种消息类型处理
- 支持HTTP API和WebSocket API双接口

### 多模态处理能力
- 语音识别(ASR)集成
- 文本转语音(TTS)支持
- 图像处理和生成能力
- 多模态大模型支持

### 智能记忆管理
- 上下文管理
- 长期记忆存储
- 向量检索功能
- 记忆优化和压缩

### 灵活配置系统
- 统一配置管理
- 环境变量覆盖支持
- 多环境适配
- 配置热更新支持

### 多客户端支持
- Web前端界面
- Android客户端
- QQ机器人
- 微信机器人

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
   - 关键组件：`AvelineService`（主要角色逻辑）, `ActiveCareService`（主动关怀）, `TaskScheduler`（任务调度）, `MonitoringSystem`（监控系统）

3. **Module Layer (`core/modules/`)**
   - 功能能力封装
   - 模型交互管理
   - 关键组件：`LLMModule`（大语言模型）, `ImageModule`（图像生成）, `VisionModule`（视觉理解）, `VoiceModule`（语音能力）, `MemoryModule`（记忆管理）

4. **Interface Layer (`core/interfaces/`)**
   - 外部通信处理
   - HTTP和WebSocket接口

## 快速开始

### 环境要求

- Python 3.10+
- CUDA支持（推荐，用于加速模型推理）或CPU模式
- 最低4GB可用内存（推荐8GB以上）

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
```

2. 根据需要修改配置项，包括：
   - 模型路径和参数
   - 服务器配置（主机、端口等）
   - 多模态功能开关
   - 日志级别和格式

### 启动服务

#### 方式1：使用启动脚本

```bash
# 启动Web服务
start_web.bat

# 启动所有服务
start_services.bat
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
│   ├── config.py            # 配置加载
│   └── config_example.py    # 配置示例
├── core/                    # 核心功能模块
│   ├── agents/              # AI Agent实现
│   ├── api/                 # API定义
│   ├── cache/               # 缓存实现
│   ├── character/           # 角色定义
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
│   ├── tools/               # 工具函数
│   ├── utils/               # 通用工具
│   └── voice/               # 语音处理
├── cpp_scheduler/           # C++调度器
├── routers/                 # API路由
├── scripts/                 # 工具脚本
├── static/                  # 静态资源
├── templates/               # HTML模板
├── tests/                   # 测试用例
├── .env.example             # 环境变量示例
├── LICENSE                  # 许可证文件
├── main.py                  # FastAPI应用入口
├── pyproject.toml           # Python项目配置
├── requirements.txt         # 依赖列表
├── setup.py                 # 安装脚本
├── start_pet.bat            # 启动宠物功能
├── start_services.bat       # 启动所有服务
├── start_web.bat            # 启动Web服务
└── PROJECT_TECHNICAL_REFERENCE.md  # 项目技术参考文档
```

## 主要功能模块

### 1. 核心引擎模块 (`core/core_engine/`)
- **配置管理**：统一管理系统配置，支持环境变量覆盖和配置热更新
- **事件总线**：实现系统内部组件之间的通信
- **生命周期管理**：管理系统的启动、运行和关闭
- **模型管理**：管理模型的加载、卸载和推理

### 2. 服务层模块 (`core/services/`)
- **AvelineService**：主要角色逻辑，处理角色交互和情感表达
- **ActiveCareService**：主动关怀服务，根据用户状态主动发起交互
- **TaskScheduler**：任务调度服务，管理系统定时任务
- **MonitoringSystem**：监控系统，监控系统资源和运行状态

### 3. 功能模块 (`core/modules/`)
- **LLMModule**：大语言模型集成，处理文本生成和理解
- **ImageModule**：图像生成模块，基于Stable Diffusion实现图像生成
- **VisionModule**：视觉理解模块，支持图像内容理解
- **VoiceModule**：语音处理模块，支持TTS和ASR功能
- **MemoryModule**：记忆管理模块，管理上下文和长期记忆

### 4. 通信模块
- **HTTP API**：提供RESTful API接口
- **WebSocket API**：提供实时通信接口
- **多客户端支持**：支持Web、Android、QQ机器人、微信机器人等多种客户端

## 配置说明

### 配置文件

小优核心使用统一的配置管理系统，配置文件主要包括：

1. **config/config.py**：主配置文件，包含系统级配置
2. **config/yaml/app.yaml**：应用级配置，包含业务逻辑配置
3. **config/yaml/env.yaml**：环境级配置，包含环境相关配置
4. **.env**：环境变量文件，用于覆盖配置

### 配置项

主要配置项包括：

- **server**：服务器配置（主机、端口、reload等）
- **llm**：LLM模型配置（模型路径、参数、推理配置等）
- **image**：图像生成配置（模型路径、参数等）
- **voice**：语音处理配置（ASR、TTS模型路径等）
- **memory**：记忆管理配置（存储路径、向量维度等）
- **log**：日志配置（级别、格式、输出路径等）

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
   ```

### 开发流程

1. 创建分支
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. 编写代码
3. 运行测试
   ```bash
   pytest tests/
   ```
4. 提交代码
   ```bash
   git add .
   git commit -m "Add your feature description"
   git push origin feature/your-feature-name
   ```
5. 创建Pull Request

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

### 部署

#### 本地部署
1. 按照快速开始指南安装依赖
2. 配置系统
3. 启动服务

#### Docker部署
（暂未支持，敬请期待）

#### 云端部署
1. 安装依赖
2. 配置系统
3. 使用PM2或Supervisor管理进程
4. 配置反向代理（Nginx或Apache）

## 客户端使用

### Web前端
1. 启动服务后，访问 http://localhost:8000
2. 注册或登录账号
3. 开始与AI交互

### Android客户端
1. 编译并安装Android客户端
2. 配置服务器地址
3. 开始与AI交互

### QQ机器人
1. 配置QQ机器人参数
2. 启动QQ机器人
   ```bash
   cd clients/bots
   python qq_bot.py
   ```
3. 在QQ中添加机器人为好友
4. 开始与机器人交互

### 微信机器人
1. 配置微信机器人参数
2. 启动微信机器人
   ```bash
   cd clients/bots
   python wx_bot.py
   ```
3. 扫描二维码登录微信
4. 开始与机器人交互

## 贡献指南

欢迎提交Issue和Pull Request来改进项目。在贡献前，请先了解以下内容：

1. **代码风格**：遵循PEP 8规范
2. **提交规范**：使用语义化提交信息
3. **测试要求**：新增功能必须包含测试用例
4. **文档要求**：新增功能必须更新文档
5. **架构要求**：遵循系统的四层架构设计

## 许可证

本项目采用MIT许可证。详见[LICENSE](LICENSE)文件。

## 技术栈

- **后端框架**：FastAPI, Uvicorn
- **前端框架**：React, TypeScript, Vite
- **数据库**：SQLite, Redis（可选）
- **AI框架**：PyTorch, Transformers, Diffusers
- **通信协议**：WebSocket, HTTP/HTTPS
- **开发语言**：Python 3.10+, TypeScript, Java（Android）

## 联系方式

- 项目地址：https://github.com/hakituo/xiaoyou-core
- 问题反馈：https://github.com/hakituo/xiaoyou-core/issues
- 讨论交流：（暂未开放，敬请期待）

## 致谢

感谢所有为小优核心项目做出贡献的开发者和用户！
