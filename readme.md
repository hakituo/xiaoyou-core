# 小优核心 (XiaoYou Core)

<div align="center">
  <strong>面向资源受限环境的高性能异步AI Agent核心系统</strong>
</div>

## 项目简介

小优核心是一个专为资源受限环境设计的AI Agent基础设施，提供高效的LLM推理、多模态交互和实时通信能力。系统采用异步并发架构，优化资源利用，支持多种部署场景。

## 核心特性

- **高性能LLM推理引擎**
  - 支持多种模型适配
  - 高效缓存机制，提升推理速度
  - 异步处理架构，优化资源利用

- **实时通信与交互**
  - WebSocket服务器，支持并发连接
  - 完善的心跳机制和错误处理
  - 支持多种消息类型处理

- **多模态处理能力**
  - 语音识别(ASR)集成
  - 文本转语音(TTS)支持
  - 图像处理能力

- **智能记忆管理**
  - 上下文管理
  - 长期记忆存储
  - 向量检索功能

- **灵活配置系统**
  - 统一配置管理
  - 环境变量覆盖支持
  - 多环境适配

## 实验与研究

项目包含丰富的实验脚本和研究成果，位于`paper/`目录下：

- **综合实验框架**：`paper/experiment/`目录包含完整的性能测试和评估脚本
- **多语言论文**：提供中文和英文两种语言的技术论文
- **实验结果分析**：详细的性能测试报告和优化建议

## 快速开始

### 环境要求

- Python 3.8+
- CUDA支持（推荐）或CPU模式
- 最低2GB可用内存

### 安装依赖

```bash
# 基础依赖
pip install -r requirements/requirements.txt

# 多模态功能依赖（可选）
pip install -r multimodal_requirements.txt
```

### 配置设置

1. 复制配置示例文件
```bash
cp config/config_example.py config/config.py
```

2. 根据需要修改配置项，包括：
   - 模型路径和参数
   - 服务器配置
   - 多模态功能开关

### 启动服务

```bash
# 启动Flask Web服务
python start.py

# 启动WebSocket服务
python ws_server.py
```

## 项目结构

```
├── config/          # 配置文件和示例
├── core/            # 核心功能模块
│   ├── text_infer.py        # LLM推理核心
│   ├── llm_connector.py     # 模型连接管理
│   ├── cache.py             # 缓存实现
│   └── vector_search.py     # 向量检索
├── memory/          # 内存管理模块
├── multimodal/      # 多模态处理
├── paper/           # 论文和实验资料
│   ├── CN/          # 中文论文
│   ├── EN/          # 英文论文
│   └── experiment/  # 实验脚本
├── scripts/         # 工具脚本
├── static/          # 静态资源
├── templates/       # HTML模板
├── start.py         # Flask应用入口
└── ws_server.py     # WebSocket服务器
```

## 主要模块说明

### LLM推理引擎
- **core/text_infer.py**: 实现高效的文本推理逻辑
- **core/llm_connector.py**: 管理不同模型的连接和交互
- **core/model_adapter.py**: 为各种模型提供统一接口

### 通信系统
- **ws_server.py**: 处理WebSocket连接和消息
- **app.py**: Flask应用主逻辑

### 记忆与检索
- **memory/memory_manager.py**: 管理上下文和长期记忆
- **memory/long_term_db.py**: 长期记忆存储实现
- **core/vector_search.py**: 向量相似度搜索

### 多模态能力
- **multimodal/stt_connector.py**: 语音识别连接
- **multimodal/tts_manager.py**: 文本转语音管理
- **multimodal/image_gen.py**: 图像处理功能

## 文档资源

项目提供详细的文档，位于`docs/`目录：
- **安装指南**: `MANUAL_INSTALL_GUIDE.md`
- **模型部署**: `MODEL_DEPLOYMENT_GUIDE.md`
- **项目结构**: `PROJECT_STRUCTURE.md`
- **缓存实现**: `cache_implementation.md`

## 贡献指南

欢迎提交Issue和Pull Request来改进项目。在贡献前，请先查看相关文档了解项目结构和规范。

## 许可证

本项目采用MIT许可证。详见[LICENSE](LICENSE)文件。
