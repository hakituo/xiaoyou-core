# 小悠 AI (xiaoyou-core)

一个轻量级、高性能的多平台AI聊天助手核心系统，特别优化了低配置电脑的运行性能。系统支持WebSocket实时通信、智能记忆管理、语音合成，以及多平台集成能力。

## 🌟 功能特性

### 核心功能
- 📱 **多平台集成**：支持Web界面，预留QQ、微信平台集成接口
- 💬 **实时通信**：基于WebSocket的高效异步消息传输系统
- 🧠 **智能记忆系统**
  - 短期上下文记忆（可配置长度和优先级）
  - 自动和手动历史记录保存与加载
  - 基于重要性的智能记忆裁剪算法
  - 长期记忆数据库存储关键信息
- 🔊 **语音合成**：双引擎支持（Edge TTS高质量云服务 + pyttsx3本地备份）
- 💻 **系统集成**：实时系统状态监控与资源管理

### 性能优化（适合低配置电脑）
- 🚀 **资源优化策略**
  - 动态延迟导入非核心依赖，显著减少启动时间和内存占用
  - 智能缓存管理，使用LRU算法自动淘汰不常用项
  - 严格的内存使用监控和限制
  - 自动垃圾回收与资源清理机制

- 💾 **数据处理优化**
  - 默认历史记录限制为10条，可动态调整
  - 基于消息重要性的智能裁剪算法
  - 文本长度限制防止资源滥用
  - 批量处理与异步执行耗时操作

- 🔌 **连接与并发管理**
  - WebSocket心跳机制（30秒间隔，60秒超时）确保连接稳定
  - 连接数限制（默认10个）防止资源耗尽
  - 异步I/O模型最大化系统吞吐量
  - 任务队列限制并发执行数量

- 🛡️ **稳定性保障**
  - 完善的异常捕获和错误处理
  - 自动重试机制提高可靠性
  - 优雅退出确保资源正确释放
  - 详细的日志系统便于问题诊断

### 命令系统
- 💻 **系统命令**：
  - `/system` - 获取当前系统信息与资源使用情况
  - `/clear` - 清空当前对话历史记录
  - `/memory` - 查看记忆系统状态与统计信息
- 🔍 **高级功能**：
  - `/save` - 将当前对话保存到文件
  - `/load` - 从文件加载对话历史
- 📋 **便捷工具**：
  - `/help` - 查看所有可用命令及其用法
  - `/setmemory [num]` - 设置历史记录最大长度（默认10条）

## 🛠️ 技术栈

### 后端
- **语言**: Python 3.7+
- **Web框架**: Flask
- **WebSocket**: 原生WebSockets
- **数据库**: SQLite (长期记忆存储)
- **AI集成**: 通义千问API (dashscope)
- **语音合成**: Edge TTS（首选）+ pyttsx3（备用）
- **工具库**: jieba, SnowNLP, python-dotenv, psutil
- **向量存储**: ChromaDB（知识库检索）

### 前端
- **核心**: HTML5, CSS3, JavaScript
- **UI**: 原生JavaScript实现
- **通信**: WebSocket API
- **本地存储**: localStorage

### 系统架构
- **异步处理**: 异步I/O模型
- **缓存系统**: 自定义LRU缓存
- **连接管理**: WebSocket心跳机制
- **资源优化**: 动态延迟导入, 智能内存管理

## 📁 项目结构

```
xiaoyou-core/
├── app.py                  # Flask Web服务器
├── ws_server.py            # WebSocket实时通信服务实现
├── start.py                # 一键启动脚本
├── bots/                   # 多平台集成模块
│   ├── qq_bot.py           # QQ平台集成支持
│   └── wx_bot.py           # 微信平台集成支持
├── core/                   # 核心功能模块
│   ├── llm_connector.py    # LLM连接器（含命令系统）
│   ├── vector_search.py    # 向量检索与知识库集成
│   ├── models/             # AI模型实现
│   │   └── qianwen_model.py # 通义千问模型封装
│   └── utils.py            # 工具函数与性能优化功能集合
├── memory/                 # 记忆管理系统
│   ├── memory_manager.py   # 上下文记忆与历史记录管理
│   └── long_term_db.py     # 长期记忆数据库管理
├── voice/                  # 语音文件存储目录
├── history/                # 对话历史保存目录
├── templates/              # 前端模板
│   ├── index.html          # Web聊天主界面
│   └── ultimate_xiaoyou_optimized.html  # 优化版界面
├── static/                 # 前端静态资源
│   ├── script.js           # 前端JavaScript交互逻辑
│   └── style.css           # 前端界面样式
├── .env                    # 环境变量配置
├── long_term_memory.db     # 长期记忆数据库文件
└── readme.md               # 项目说明文档
```

## 🚀 快速开始

### 环境要求
- Python 3.7+
- 至少 1GB RAM（推荐 2GB+）
- 至少 50MB 磁盘空间
- 支持的操作系统：Windows, macOS, Linux

### 安装配置

1. 克隆或下载项目到本地
2. 安装必要依赖：
   ```bash
   pip install flask websockets python-dotenv jieba snownlp pyttsx3 chromadb
   
   # 如需使用通义千问API，还需安装
   pip install dashscope
   ```

3. 配置环境变量：
   编辑 `.env` 文件，填入以下配置：
   ```
   # 通义千问 API Key (可选，如果不配置将使用模拟回复)
   QIANWEN_API_KEY=your_api_key_here
   
   # 系统配置（可根据需要调整）
   MAX_HISTORY_LENGTH=10
   MAX_CONNECTIONS=10
   ```

### 启动应用

```bash
# 直接运行启动脚本
python start.py
```

应用启动后，默认在 http://localhost:5000 提供服务，同时通过WebSocket进行实时通信。打开浏览器访问该地址即可开始使用。

> 注意：一键启动功能会同时启动 WebSocket 服务器和 Flask Web 应用，无需分别运行。

#### 高级用户选项：分别启动（用于调试）

1. 先启动 WebSocket 服务器：
```bash
python ws_server.py
```

2. 在新窗口启动 Flask 应用：
```bash
python app.py
```

## ⚙️ 配置说明

### 系统核心配置
- `MAX_HISTORY_LENGTH`: 最大历史记录长度（默认10条，可通过命令调整）
- `MAX_CONNECTIONS`: 最大并发连接数限制（默认10个）
- `HEARTBEAT_INTERVAL`: WebSocket心跳检测间隔（默认30秒）
- `HEARTBEAT_TIMEOUT`: WebSocket连接超时时间（默认60秒）

### 语音合成配置
- TTS引擎自动选择（Edge TTS优先，失败自动回退到pyttsx3）
- 支持语速和音量调整（有安全范围限制）
- 语音文件自动缓存管理

### 性能优化选项
- 延迟加载非核心依赖（jieba, snownlp等）
- 智能缓存系统（LRU算法自动管理）
- 文本长度限制防止资源滥用

## 💡 使用指南

### 基本对话
1. 启动应用后，在浏览器中打开 http://localhost:5000
2. 在输入框中输入消息，点击发送按钮或按回车键
3. 对话内容会实时显示在聊天界面中
4. AI回复后，可点击消息旁的🔊图标播放语音

### 命令系统使用
在聊天输入框中输入以下命令：

- **查看帮助**：`/help` - 显示所有可用命令及其用法
- **清空对话**：`/clear` - 清空当前对话历史记录
- **保存历史**：`/save` - 将当前对话保存到文件
- **加载历史**：`/load` - 从文件加载对话历史
- **查看内存**：`/memory` - 查看当前记忆系统状态与统计信息
- **调整记忆长度**：`/setmemory [num]` - 设置历史记录最大长度（默认10条）
- **系统信息**：`/system` - 查看系统信息与资源使用情况

### 记忆与历史管理
- 对话历史会自动保存在 `history/` 目录下
- 重要信息会存储在长期记忆数据库中
- 使用 `/save` 和 `/load` 命令可以手动管理历史记录
- 不同用户的历史记录相互独立（通过user_id区分）
- 记忆系统会智能裁剪，优先保留重要消息

## 🔧 故障排除

### 常见问题解决
1. **WebSocket连接失败**
   - 检查网络连接是否正常
   - 确认防火墙没有阻止端口访问
   - 查看服务日志确认WebSocket服务启动成功
   - 尝试刷新页面或重启浏览器

2. **语音合成不工作**
   - 检查pyttsx3库是否正确安装
   - Edge TTS需要网络连接，pyttsx3为本地备份
   - 确认系统音频设备设置正确
   - 检查日志中的具体错误信息

3. **内存占用过高**
   - 使用`/setmemory [较小值]`命令减小历史记录长度
   - 定期使用`/clear`命令清空对话历史
   - 重启应用释放资源

4. **历史记录管理问题**
   - 检查`history/`目录权限是否正确
   - 确保磁盘空间充足
   - 手动检查历史文件格式是否正确

### 日志与调试
- 系统日志保存在`flask_app.log`和`startup.log`
- 重要错误会同时显示在控制台和日志文件中
- 调试时建议分别启动WebSocket和Flask服务

## 📝 注意事项

- **资源优化**：系统已针对低配置电脑优化，但仍建议定期重启以释放资源
- **API密钥保护**：请妥善保管您的通义千问API密钥，避免泄露
- **数据安全**：历史记录和记忆数据保存在本地，请注意文件系统安全
- **语音功能**：Edge TTS需要网络连接，音质更佳；pyttsx3为离线备份方案
- **连接限制**：默认最大并发连接数为10个，可根据系统性能调整

## 🔮 未来规划

- [ ] 增强上下文理解和长期记忆能力
- [ ] 进一步优化资源使用效率
- [ ] 扩展更多第三方AI模型支持
- [ ] 完善语音识别与合成功能
- [ ] 增强多平台集成和适配
- [ ] 优化用户界面和交互体验
- [ ] 增加插件系统支持自定义功能扩展

## 📄 许可证

本项目采用 MIT 许可证开源。

```
MIT License

Copyright (c) 2025 小悠AI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

小悠AI - 为低配置电脑优化的高性能AI聊天助手！

© 2025 hakituo